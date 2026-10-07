"""B 스킬 서버 (BACKEND=real): Runner 의 원자 동작을 `/skills/<동작>` Skill 액션으로 받는다 (#10·#13·#15).

이름·형식은 docs/interfaces.md·runner.md 7.1 과 C 의 mock_backend.py 와 같다 → Runner 코드는 그대로, 백엔드만 바뀜.
공통 (core/skill_flow.py):
  - 취소 요청 → MoveStop → 멈출 때까지 기다림 → canceled (그리퍼는 그대로, 잡은 물건을 떨어뜨리지 않음)
  - 안전·비상정지 상태 → error_code ESTOP
  - 움직이기 전 펜던트 TCP·툴 확인 → 다르면 TOOL_NOT_SET (motion_guard, calibration_meta.yaml 기준)
구현 상태:
  - move_to_named_pose: poses.yaml 관절각으로 movej, 도착 확인 (낮은 곳이면 먼저 수직으로 올림)
  - drawer_control (drawer_top): 손잡이 잡고 당겨 열기(걸림 감시) / 주먹으로 밀어 닫기(위치 + 힘). 시연 1차 10/06
  - nudge_object: 기울인 손끝으로 눌러(힘 감지) 서랍 옆으로만 끌기 — 옆벽에 붙어 짧은 변으로 못 잡을 때 (트러블슈팅 2)
  - pick_object (서랍): 짧은 변 잡기, 폭 확인, 들어 올린 뒤 놓침 확인 / place_object: handover_zone 빈 칸
  값은 params/skills.yaml (10/05~06 로봇 실측), 장소는 config/places.yaml, 물체 크기는 knowledge/world.jsonld.

실행 (PC2, DSR 드라이버 실행 중):
    ros2 run ready2go_skills skill_server
    ros2 run ready2go_skills skill_server --ros-args -p joint_vel_deg_s:=10.0   # 처음은 저속 (safety.md 11)
"""
import json
import math
import os
import time
from pathlib import Path

import rclpy
import yaml
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from ready2go_interfaces.action import Skill
from ready2go_skills.adapters.dsr import Dsr
from ready2go_skills.adapters.rg2 import Rg2
from ready2go_skills.core import drawer_plan as dp, grasp_check as gc, motion_guard, motion_plan as mp
from ready2go_skills.core import pick_plan as pp, pose_math as pm, skill_flow as sf

ACTIONS = ("move_to_named_pose", "drawer_control", "nudge_object", "pick_object", "place_object")
def _params_file():
    """params/skills.yaml: 소스(symlink 설치) → 설치된 share 순서."""
    src = Path(__file__).resolve().parents[2] / "params" / "skills.yaml"
    if src.exists():
        return src
    try:
        from ament_index_python.packages import get_package_share_directory
        return Path(get_package_share_directory("ready2go_skills")) / "params" / "skills.yaml"
    except Exception:  # noqa: BLE001 — ROS 없는 테스트 환경
        return src


PARAMS_FILE = _params_file()
NO_OBJECT_CONTACT = "NO_OBJECT_CONTACT"  # 끌기: 내려가도 물체 윗면 접촉을 못 느낌 (runner.md nudge_object 표)
PUSH_BLOCKED = "PUSH_BLOCKED"            # 끌기 중 힘이 너무 큼 (걸림, runner.md 기존 코드)
WALL_TOO_CLOSE = "WALL_TOO_CLOSE"        # pick_object: 짧은 변으로 잡으면 손가락·관절이 서랍 벽에 닿음 → nudge_object 먼저 (움직이기 전)
JOINT_LIMIT = "JOINT_LIMIT"              # 관절이 안전 제한(params joint_limits_deg, 펜던트 안전 설정보다 조금 안쪽)을 넘음/넘을 목표 → 정지·거부
PUSH_LIMIT = "PUSH_LIMIT"                # check_only 재판단에서 아직 잡을 수 없는 자리 (runner.md 기존 코드)
GRASP_FAILED = "GRASP_FAILED"
NOT_HOLDING = "NOT_HOLDING"
HOLDING_OBJECT = "HOLDING_OBJECT"        # 물건을 든 채 서랍 닫기 거부
TRAY_FULL = "TRAY_FULL"
PLACE_NOT_CONFIGURED = "PLACE_NOT_CONFIGURED"
UNSUPPORTED_PARAMS = "UNSUPPORTED_PARAMS"
DRAWER_NOT_CONFIGURED = "DRAWER_NOT_CONFIGURED"
DRAWER_STATE_UNKNOWN = "DRAWER_STATE_UNKNOWN"    # 서버가 인출 거리를 모름(재시작) — 열린 서랍에 닫힘 기준으로 다가가면 충돌
DRAWER_ALREADY_OPEN = "DRAWER_ALREADY_OPEN"
OTHER_DRAWER_OPEN = "OTHER_DRAWER_OPEN"        # 서랍은 한 번에 하나만 엶 (위·아래가 겹쳐 접근·시야를 막음)
GRIPPER_ERROR = "GRIPPER_ERROR"


def find_config_dir():
    env = os.environ.get("READY2GO_CONFIG_DIR")
    if env:
        return Path(env)
    for d in Path(__file__).resolve().parents:
        if (d / "config" / "poses.yaml").exists():
            return d / "config"
    return Path.home() / "ready2go" / "config"


class SkillServer(Node):
    def __init__(self):
        super().__init__("skill_server")
        self.joint_vel = float(self.declare_parameter("joint_vel_deg_s", 20.0).value)   # [팀 확정 필요] 저속 → 정상
        self.joint_acc = float(self.declare_parameter("joint_acc_deg_s2", 20.0).value)
        self.move_timeout = float(self.declare_parameter("move_timeout_s", 30.0).value)  # 서버 쪽 안전 상한
        self.reach_tol = float(self.declare_parameter("reach_tol_deg", 0.5).value)
        sf.check_server_params(joint_vel_deg_s=self.joint_vel, joint_acc_deg_s2=self.joint_acc,   # NaN·0·음수 → 안 뜸
                               move_timeout_s=self.move_timeout, reach_tol_deg=self.reach_tol)
        cfg = Path(self.declare_parameter("config_dir", str(find_config_dir())).value)
        self.cfg_dir = cfg
        meta = yaml.safe_load((cfg / "calibration" / "calibration_meta.yaml").read_text(encoding="utf-8"))
        self.expected_tcp, self.expected_tool = motion_guard.expected_tool(meta)
        self.robot = Dsr(self, self.declare_parameter("dsr_prefix", "/dsr01/dsr_controller2").value)
        self.state = sf.MotionState(self.robot.state, self.robot.posj)   # 상태값 + 관절 변화 (실물에서 이동 중 표시가 안 뜸, 10/06)
        self.params_file = Path(self.declare_parameter("params_file", str(PARAMS_FILE)).value)
        self.rg2_ip = os.environ.get("RG2_HOST") or self.prm()["gripper"]["rg2_ip"]
        self.disp = {}                       # 서랍별 인출 거리(m) — drawer_control 결과. 서버 재시작 후엔 모름 → 집기 거부
        self.held = None                     # 들고 있는 물체 {class, id, width_m, tcp_above_floor_m}
        self.tray = {}                       # 장소별 쓴 칸
        self.locked = None                   # 잠금 사유(skill_flow.LOCKING_CODES). 사람이 로봇을 확인하고 서버를 다시 띄울 때까지 모든 동작 거부
        self.gate = sf.MotionGate()          # 5개 액션 전체에서 한 번에 하나만 실행 (#73 E 리뷰)
        group = ReentrantCallbackGroup()
        self._servers = [ActionServer(self, Skill, f"/skills/{a}", self._execute_for(a), callback_group=group,
                                      goal_callback=self._on_goal,
                                      cancel_callback=lambda _: CancelResponse.ACCEPT) for a in ACTIONS]
        self.get_logger().info(f"스킬 서버 준비: /skills/{{{','.join(ACTIONS)}}} (관절 {self.joint_vel}°/s, "
                               f"기대 TCP {self.expected_tcp}·툴 {self.expected_tool}, config {cfg})")

    def poses(self):
        """매 호출마다 다시 읽음 — 교시값을 고친 뒤 서버를 재시작하지 않아도 되게."""
        return yaml.safe_load((self.cfg_dir / "poses.yaml").read_text(encoding="utf-8"))

    def prm(self):
        return yaml.safe_load(self.params_file.read_text(encoding="utf-8"))

    def places(self):
        return yaml.safe_load((self.cfg_dir / "places.yaml").read_text(encoding="utf-8"))

    def item(self, cls):
        """온톨로지 size_m [긴 변, 짧은 변, 높이] 과 item_grasp.yaml 잡는 힘."""
        world = json.loads((self.cfg_dir.parent / "knowledge" / "world.jsonld").read_text(encoding="utf-8"))
        items = world.get("world", {}).get("items", {})
        if cls not in items or "size_m" not in items[cls]:
            raise ValueError(f"온톨로지에 {cls!r} 크기 없음")
        grasp = yaml.safe_load((self.cfg_dir / "item_grasp.yaml").read_text(encoding="utf-8")) or {}
        force = (grasp.get(cls) or {}).get("grip_force")
        return [float(v) for v in items[cls]["size_m"]], force

    def _on_goal(self, _request):
        """실행 중인 동작이 있으면 새 goal 을 받지 않음 (Runner 는 거절로 받음, 로봇 동작 없음)."""
        return GoalResponse.REJECT if self.gate.busy() else GoalResponse.ACCEPT

    def _execute_for(self, action):
        handler = getattr(self, f"_do_{action}", None)

        def execute(goal):
            try:
                params = json.loads(goal.request.params_json or "{}")
            except json.JSONDecodeError as e:
                return self._finish(goal, action, sf.Outcome(False, sf.BAD_PARAMS, reason=str(e)))
            self.get_logger().info(f"[{action}] {params}")
            if handler is None:
                return self._finish(goal, action, sf.Outcome(False, sf.NOT_IMPLEMENTED,
                                                             reason="10/06 실측 후 구현 (로봇 동작 없음)"))
            # gate 진입 → 잠금 확인 → 취소 확인 → 툴 확인 → handler. 잠금 설정도 gate 안에서 (skill_flow.execute_skill)
            outcome, output = sf.execute_skill(lambda: handler(goal, params), gate=self.gate,
                                               locked=lambda: self.locked, set_locked=lambda why: self._lock(action, why),
                                               cancel_requested=lambda: goal.is_cancel_requested,
                                               check_tool=self._check_tool, stop=self.robot.stop,
                                               get_state=self.state)
            return self._finish(goal, action, outcome, output)
        return execute

    def _check_tool(self):
        err = motion_guard.check_tool(*self.robot.tool_names(), self.expected_tcp, self.expected_tool)
        return sf.Outcome(False, err.error_code, reason=err.reason) if err else None

    def _lock(self, action, why):
        self.locked = f"{action}: {why}"
        self.get_logger().error(f"[{action}] 잠금 — 펜던트에서 로봇 상태 확인 후 skill_server 재시작 필요")

    def _finish(self, goal, action, outcome, output=None):
        if outcome.canceled:
            goal.canceled()
        elif outcome.success:
            goal.succeed()
        else:
            goal.abort()
        if outcome.success:                  # rclpy 는 같은 호출 위치에서 severity 를 바꾸면 ValueError (#73 E 리뷰)
            self.get_logger().info(f"[{action}] 성공: {outcome.reason}")
        else:
            self.get_logger().warning(f"[{action}] {outcome.error_code}: {outcome.reason}")
        return Skill.Result(success=outcome.success, error_code=outcome.error_code,
                            output_json="" if output is None else json.dumps(output, ensure_ascii=False))

    # --- 동작 ---
    def _do_move_to_named_pose(self, goal, params):
        return self._named(goal, params.get("pose_name", ""), params.get("drawer_id")), None

    def _named(self, goal, pose_name, drawer_id=None):
        """기준 포즈로 관절 이동 (낮으면 먼저 수직으로 올림). 성공이면 Outcome(True), 아니면 실패 Outcome."""
        joints, err = sf.pose_joints(self.poses(), pose_name, drawer_id)
        if err:
            return err
        err = self._joint_bad(joints, f"{pose_name} 목표")
        if err:
            return err
        goal.publish_feedback(Skill.Feedback(stage="auto_mode"))
        if not self.robot.auto():            # 모드 전환은 이동 명령이 아님 → 명시적 거부로 처리
            return sf.after_command(False, what="자동 모드 전환", stop=self.robot.stop, get_state=self.state)
        early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)   # 모드 전환 중 취소됐으면 movej 를 보내지 않음
        if early:
            return early
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 관절 이동 전 높이 확인 못 함")
        tr = self.prm()["transit"]
        # 관절 이동은 경로 높이를 보장하지 않음 → 낮으면 먼저 수직으로 올림 (#83 D 재검토 P1).
        # 서랍 위: safe_z(300). 그 밖(트레이 등): free_lift_z(150) — 트레이 쪽 z 300은 팔이 거의 펴져 위험
        lift_z = tr["safe_z_mm"] if self._over_drawer(cur) else tr["free_lift_z_mm"]
        if pose_name == "drawer_top_view" and not self._over_drawer(cur):
            lift_z = max(lift_z, tr["high_z_mm"])          # 홈 쪽에서 보는 자세로: 앞판·손잡이 위로 올린 뒤 (10/06 실물, 낮게 가면 손잡이에 걸림)
        if pose_name == "drawer_approach":
            lift_z = max(lift_z, tr["safe_z_mm"])          # 홈 → z 300 → ready: drawer_control 열기·b_demo 와 같은 경로 (10/06 통합: 홈에서 바로 가면 손잡이보다 낮게 지나감)
        if cur[2] < lift_z:
            bad = self._line(goal, mp.with_z(cur, lift_z), self.prm()["speed"]["line_mm_s"], "lift")
            if bad:
                return bad
        goal.publish_feedback(Skill.Feedback(stage=f"to_{pose_name}"))
        bad = sf.after_command(self.robot.movej_async(joints, self.joint_vel, self.joint_acc), what="movej",
                               stop=self.robot.stop, get_state=self.state)
        if bad:
            return bad
        done = sf.wait_motion(get_state=self.state, cancel_requested=lambda: goal.is_cancel_requested,
                              stop=self.robot.stop, timeout_s=self.move_timeout, arrived=self._at_joints(joints),
                              watch=self._joint_watch())
        if not done.success:
            return done
        reached = sf.check_reached(joints, self.robot.posj(), self.reach_tol)
        if reached.success and pose_name == "home":
            self.home_posx = self.robot.posx()             # 놓기 때 서랍 → 홈 위로 높게 돌아오는 데 씀
        return reached

    def _over_drawer(self, cur):
        """TCP 가 서랍 안쪽(벽 포함 여유 40 mm) 위에 있는지 — 최대 인출 tf 기준."""
        for name in ("drawer_top", "drawer_bottom"):
            pl = self.places().get(name) or {}
            tf, size = pl.get("tf") or {}, pl.get("interior_m")
            if not tf.get("translation_m") or not size:
                continue
            p = mp.from_base(tf, [v / 1000.0 for v in cur[:3]])
            if -0.04 <= p[0] <= size[0] + 0.04 and -0.04 <= p[1] <= size[1] + 0.04 and p[2] > -0.02:
                return True
        return False

    def _to_drawer_view(self, goal, drawer_id):
        """서랍 위 작업 전: 서랍 위가 아니면 홈 → drawer_top_view (관절 이동). ready(손잡이 쪽) 자세는 J2가 반대로 꺾여 있어
        보는 자세로 바로 못 감 → 홈을 거쳐 관절 자세를 풀고 올라감 [사용자 확인 B 10/06]. 이미 서랍 위면 그대로."""
        cur = self.robot.posx()
        if cur and self._over_drawer(cur):
            return None
        o = self._named(goal, "home")
        if not o.success:
            return o
        bad = self._go_high(goal)                           # 홈에서 수직으로 쭉 올린 뒤 들어감 — 낮게 가면 열린 손잡이에 걸림 [실측 10/06]
        if bad:
            return bad
        o = self._named(goal, "drawer_top_view", drawer_id)
        return None if o.success else o

    def _go_high(self, goal, xy=None):
        """지금 방향 그대로 transit.high_z_mm 까지 직선 (xy 를 주면 그 위치로). 서랍 앞판·손잡이 위를 지날 때."""
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패")
        prm = self.prm()
        high = prm["transit"]["high_z_mm"]
        up = mp.with_z(cur, max(cur[2], high))
        bad = self._line(goal, up, prm["speed"]["line_mm_s"], "go_high")
        if bad or xy is None:
            return bad
        return self._line(goal, [xy[0], xy[1]] + up[2:], prm["speed"]["line_mm_s"], "go_high_over")

    def _tare(self):
        """멈춘 뒤 잠깐 기다렸다가 여러 번 읽은 평균 = 힘 기준값. 두산 툴 힘은 관절 토크 추정이라 멈춘 직후 흔들림 (10/06)."""
        sp = self.prm()["force"]
        time.sleep(sp["tare_settle_s"])
        fs = [f for f in (self.robot.tool_force() for _ in range(int(sp["tare_samples"]))) if f is not None]
        return [sum(f[i] for f in fs) / len(fs) for i in range(6)] if fs else None

    def _movej(self, goal, joints, stage):
        """관절 이동 1번 (제한 확인 → 자동 모드 → 비동기 → 도착). 성공이면 Outcome(True)."""
        err = self._joint_bad(joints, f"{stage} 목표")
        if err:
            return err
        goal.publish_feedback(Skill.Feedback(stage=stage))
        if not self.robot.auto():
            return sf.after_command(False, what="자동 모드 전환", stop=self.robot.stop, get_state=self.state)
        early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)
        if early:
            return early
        bad = sf.after_command(self.robot.movej_async(joints, self.joint_vel, self.joint_acc), what=f"movej({stage})",
                               stop=self.robot.stop, get_state=self.state)
        if bad:
            return bad
        done = sf.wait_motion(get_state=self.state, cancel_requested=lambda: goal.is_cancel_requested,
                              stop=self.robot.stop, timeout_s=self.move_timeout, arrived=self._at_joints(joints),
                              watch=self._joint_watch())
        if not done.success:
            return done
        return sf.check_reached(joints, self.robot.posj(), self.reach_tol)

    def _joint_bad(self, joints, what):
        """관절 제한 확인 (펜던트 안전 설정 J5 ±135° → params 는 그보다 안쪽). 넘으면 Outcome, 아니면 None."""
        lim = self.prm().get("joint_limits_deg") or {}
        for name, (lo, hi) in lim.items():
            v = joints[int(name[1:]) - 1]
            if not lo <= v <= hi:
                return sf.Outcome(False, JOINT_LIMIT, reason=f"{what} {name} {v:.1f}° — 제한 [{lo:g}, {hi:g}]° 밖")
        return None

    def _joint_watch(self, extra=None):
        """이동 중 관절 제한 감시 (+ 다른 watch). 넘기 전에 멈춰 펜던트 안전 정지까지 가지 않게."""
        def watch():
            j = self.robot.posj()
            if j is not None:
                bad = self._joint_bad(j, "이동 중")
                if bad:
                    return bad
            return extra() if extra else None
        return watch

    def _at_joints(self, joints):
        """wait_motion arrived: 관절각이 목표와 reach_tol 안. 조회 실패면 False."""
        return lambda: sf.check_reached(joints, self.robot.posj(), self.reach_tol).success

    def _at_posx(self, posx, tol_mm=1.0, tol_deg=1.0):
        """wait_motion arrived: TCP 위치·방향이 목표 근처. 조회 실패면 False."""
        def at():
            cur = self.robot.posx()
            if cur is None:
                return False
            d = math.dist(cur[:3], [float(v) for v in posx[:3]])
            return d <= tol_mm and pm.rotation_angle(pm.rot(*cur[3:]), pm.rot(*posx[3:])) <= tol_deg
        return at

    # --- 공통 이동 ---
    def _line(self, goal, posx, vel, stage, watch=None):
        """직선 이동 1회 (자동 모드 → 취소 확인 → 비동기 명령 → 끝날 때까지). 성공이면 None, 아니면 Outcome."""
        goal.publish_feedback(Skill.Feedback(stage=stage))
        if not self.robot.auto():
            return sf.after_command(False, what="자동 모드 전환", stop=self.robot.stop, get_state=self.state)
        early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)
        if early:
            return early
        sp = self.prm()["speed"]                          # 부드럽게: 가속 = 속도(1 s에 최고 속도), 회전 따로 (10/06 기울일 때 쿵쿵)
        bad = sf.after_command(self.robot.movel_async(posx, vel, sp["line_acc_ratio"] * vel, sp["turn_deg_s"],
                                                      sp["turn_acc_deg_s2"]), what=f"movel({stage})",
                               stop=self.robot.stop, get_state=self.state)
        if bad:
            return bad
        done = sf.wait_motion(get_state=self.state, cancel_requested=lambda: goal.is_cancel_requested,
                              stop=self.robot.stop, timeout_s=self.move_timeout, watch=self._joint_watch(watch),
                              arrived=self._at_posx(posx))
        return None if done.success else self._where(done, stage, posx)

    def _where(self, done, stage, posx):
        """NOT_REACHED 이유에 단계·멈춘 곳·남은 거리를 붙인다 (10/06 저녁 nudge NOT_REACHED 0.3 s — 어느 이동인지 로그로 몰랐음)."""
        if done.error_code != sf.NOT_REACHED:
            return done
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.NOT_REACHED, reason=f"[{stage}] {done.reason}, 현재 좌표 조회 실패")
        left = math.dist(cur[:3], [float(v) for v in posx[:3]])
        return sf.Outcome(False, sf.NOT_REACHED, reason=f"[{stage}] {done.reason} — 멈춘 곳 {[round(v, 1) for v in cur]}, "
                                                     f"목표 {[round(float(v), 1) for v in posx]}, 남은 {left:.1f} mm")

    def _spline(self, goal, points, stage):
        """경유점 posj 목록을 관절 스플라인으로 (자동 모드 → 취소 확인 → 비동기 → 마지막 점 도착까지). 성공이면 None."""
        goal.publish_feedback(Skill.Feedback(stage=stage))
        if not self.robot.auto():
            return sf.after_command(False, what="자동 모드 전환", stop=self.robot.stop, get_state=self.state)
        early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)
        if early:
            return early
        for k, p in enumerate(points):
            err = self._joint_bad(p, f"경유점 {k + 1}")
            if err:
                return err
        sp = self.prm()["speed"]
        bad = sf.after_command(self.robot.movesj_async(points, sp["spline_deg_s"], sp["spline_acc_deg_s2"]),
                               what=f"movesj({stage})", stop=self.robot.stop, get_state=self.state)
        if bad:
            return bad
        done = sf.wait_motion(get_state=self.state, cancel_requested=lambda: goal.is_cancel_requested,
                              stop=self.robot.stop, timeout_s=self.move_timeout, arrived=self._at_joints(points[-1]),
                              watch=self._joint_watch())
        if not done.success:
            return done
        reached = sf.check_reached(points[-1], self.robot.posj(), self.reach_tol)
        return None if reached.success else reached

    def _blend(self, goal, points, radii, vel, stage):
        """posx 경유점들을 직선 블렌딩으로 한 번에 (자동 모드 → 취소 확인 → 비동기 → 마지막 점 도착까지). 성공이면 None."""
        goal.publish_feedback(Skill.Feedback(stage=stage))
        if not self.robot.auto():
            return sf.after_command(False, what="자동 모드 전환", stop=self.robot.stop, get_state=self.state)
        early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)
        if early:
            return early
        sp = self.prm()["speed"]
        bad = sf.after_command(self.robot.moveb_async(points, radii, vel, sp["line_acc_ratio"] * vel, sp["turn_deg_s"],
                                                      sp["turn_acc_deg_s2"]), what=f"moveb({stage})",
                               stop=self.robot.stop, get_state=self.state)
        if bad:
            return bad
        done = sf.wait_motion(get_state=self.state, cancel_requested=lambda: goal.is_cancel_requested,
                              stop=self.robot.stop, timeout_s=self.move_timeout, watch=self._joint_watch(),
                              arrived=self._at_posx(points[-1]))
        return None if done.success else self._where(done, stage, points[-1])

    def _carry_route(self, drawer_id):
        """poses.yaml carry_line 경유점 posx (집은 뒤 → 트레이 직선 블렌딩). 없으면 None (예전 carry_out movesj)."""
        route = (self.poses().get("carry_line") or {}).get(drawer_id or "drawer_top")
        return [list(p) for p in route] if route else None

    def _transit(self, goal, target, stage):
        """safe_z 로 수직 이동 → 그 자리에서 방향만 돌림 → safe_z 에서 목표 위로 → 목표로 내려감.
        방향 바꾸기와 옮기기를 나눔: drawer_top_view(팔 거의 펴짐, J3 약 10°)에서 옮기며 30° 기울이다 특이점에 걸림 (10/06 실물).
        제자리에서 서랍 벽 쪽으로 기울이면 플랜지가 안쪽으로 와서 팔이 덜 펴짐."""
        prm = self.prm()
        safe, vel = prm["transit"]["safe_z_mm"], prm["speed"]["line_mm_s"]
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패")
        level = mp.with_z(cur, safe if self._over_drawer(cur) else max(cur[2], safe))   # 서랍 위면 높아도 safe_z 로 내림
        for pose, st in ((level, f"{stage}:level"),
                         (list(level[:3]) + list(target[3:]), f"{stage}:turn"),
                         (mp.with_z(target, max(safe, target[2])), f"{stage}:over"),
                         (list(target), f"{stage}:down")):
            bad = self._line(goal, pose, vel, st)
            if bad:
                return bad
        return None

    def _grip(self, width_mm, force_n):
        """RG2 이동 (끝날 때까지). 실패하면 예외 → run_guarded 가 정지 확인 후 SKILL_EXCEPTION."""
        g = Rg2(self.rg2_ip)
        try:
            return g.move(width_mm, force_n)
        finally:
            g.close()

    def _cur_angles(self):
        cur = self.robot.posx()
        if cur is None:
            raise RuntimeError("현재 좌표 조회 실패")
        return cur[3:]

    # --- 서랍 ---
    def _do_drawer_control(self, goal, params):
        drawer_id, state = params.get("drawer_id"), params.get("state")
        prm, place = self.prm(), self.places().get(drawer_id) or {}
        oc, dc = prm["drawer_open_close"], prm["drawer_control"]
        closed = (oc["handle_grasp_posx"] or {}).get(drawer_id)
        if closed is None or not place.get("tf"):
            return sf.Outcome(False, DRAWER_NOT_CONFIGURED, reason=f"{drawer_id} 손잡이·tf 측정 전"), None
        pull = dp.pull_direction(place["tf"]["quaternion_xyzw"])
        if "displacement" in params:                        # 서버 재시작 뒤 사람이 상태를 알려줄 때 (m)
            self.disp[drawer_id] = float(params["displacement"])
        if state == "close" and drawer_id not in self.disp:
            return sf.Outcome(False, DRAWER_STATE_UNKNOWN, reason="인출 거리를 모름 — params displacement 로 알려주기"), None
        disp = self.disp.get(drawer_id, 0.0)                # 열기: 서버 시작 때는 닫혀 있다고 봄 (README 시작 조건)
        others = [d for d, v in self.disp.items() if d != drawer_id and v > 0.01]
        if state == "open" and others:
            return sf.Outcome(False, OTHER_DRAWER_OPEN, reason=f"{others[0]} 이 열려 있음 — 먼저 닫기"), None
        if state == "open" and disp > 0.01:
            return sf.Outcome(False, DRAWER_ALREADY_OPEN, reason=f"이미 {disp * 1000:.0f} mm 열림"), \
                {"drawer_displacement": round(disp, 4), "close_confirmed": False}
        handle = mp.handle_posx(closed, pull, disp)
        if state == "open":
            return self._open_drawer(goal, drawer_id, place, oc, dc, closed, pull, disp, params)
        if state == "close":
            return self._close_drawer(goal, drawer_id, oc, dc, closed, pull, handle)
        return sf.Outcome(False, sf.BAD_PARAMS, reason=f"state 는 open/close: {state!r}"), None

    def _open_drawer(self, goal, drawer_id, place, oc, dc, closed, pull, disp, params):
        max_travel = float(place.get("max_travel_m") or 0)
        distance = float(params.get("distance", max_travel - disp))
        bad = dp.check_open_distance(distance, max_travel - disp + 1e-6)
        if bad:
            return sf.Outcome(False, bad.error_code, reason=bad.reason), None
        speed = self.prm()["speed"]
        joints, err = sf.pose_joints(self.poses(), "drawer_approach", drawer_id)
        if err:
            return err, None
        cur = self.robot.posx()
        if cur is None:                                              # 높이를 모르면 그리퍼·관절 이동 전에 실패 (#83 E 검토 P1)
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 관절 이동 전 높이 확인 못 함"), None
        self._grip(oc["handle_open_width_mm"], 20)
        # Runner 의 open_drawer 는 move_to_named_pose(drawer_approach) 를 먼저 보냄 → 이미 ready 면 다시 올렸다 내리지 않음 (10/06 통합 실물)
        if not sf.check_reached(joints, self.robot.posj(), self.reach_tol).success:
            if cur[2] < self.prm()["transit"]["safe_z_mm"]:              # 낮은 곳에서 바로 관절 이동하지 않음
                bad = self._line(goal, mp.with_z(cur, self.prm()["transit"]["safe_z_mm"]), speed["line_mm_s"], "lift")
                if bad:
                    return bad, None
            goal.publish_feedback(Skill.Feedback(stage="approach"))
            err = self._joint_bad(joints, "drawer_approach 목표")
            if err:
                return err, None
            if not self.robot.auto():
                return sf.after_command(False, what="자동 모드 전환", stop=self.robot.stop, get_state=self.state), None
            bad = sf.after_command(self.robot.movej_async(joints, self.joint_vel, self.joint_acc), what="movej(drawer_approach)",
                                   stop=self.robot.stop, get_state=self.state)
            if bad:
                return bad, None
            done = sf.wait_motion(get_state=self.state, cancel_requested=lambda: goal.is_cancel_requested,
                                  stop=self.robot.stop, timeout_s=self.move_timeout, arrived=self._at_joints(joints),
                                  watch=self._joint_watch())
            if not done.success:
                return done, None
            reached = sf.check_reached(joints, self.robot.posj(), self.reach_tol)
            if not reached.success:
                return reached, None
        handle = mp.offset_posx(mp.handle_posx(closed, pull, disp), pull, oc["handle_grasp_back_mm"])   # 실측보다 조금 덜 들어감
        reach_f = self._tare()

        def touched():                                       # 손잡이 앞에서 무언가에 닿음 = 서랍이 덜 닫혔거나 위치가 다름 (10/06 실물)
            f = self.robot.tool_force()
            if f is None or reach_f is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="힘 조회 실패")
            push = abs(sum((f[i] - reach_f[i]) * pull[i] for i in range(3)))
            if push >= oc["handle_contact_n"]:
                return sf.Outcome(False, GRASP_FAILED, reason=f"손잡이 접근 중 {push:.1f} N 접촉 — 서랍이 끝까지 닫혔는지 확인")
            return None

        slow = oc.get("handle_slow_last_mm", 0.0)          # 잡기 1 cm 전까지는 빠르게, 마지막만 천천히 [사용자 10/06 저녁] (접촉 감시는 둘 다)
        bad = self._line(goal, mp.offset_posx(handle, pull, slow), speed["line_mm_s"], "reach_handle_fast",
                         watch=touched) if slow > 0 else None
        if bad is None:
            bad = self._line(goal, handle, speed["approach_mm_s"], "reach_handle", watch=touched)
        if bad:
            if sf.is_safety(bad):
                return bad, None
            now = self.robot.posx()                          # 접촉으로 멈춤 → 그대로 뒤로 빼고 실패
            back = self._line(goal, mp.offset_posx(now, pull, oc["retreat_mm"]), speed["line_mm_s"], "retreat") \
                if now else sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패")
            return sf.worse(bad, back), None
        st = self._grip(0, oc["handle_grip_force_n"])
        if st.width_mm / 1000.0 <= oc["handle_min_width_m"]:
            self._grip(oc["handle_open_width_mm"], 20)
            return sf.Outcome(False, GRASP_FAILED, reason=f"손잡이를 못 잡음 (폭 {st.width_mm:.1f} mm)"), None
        start = self.robot.posx()
        base_f = self._tare()
        target = mp.offset_posx(handle, pull, distance * 1000.0)
        verdict = {}

        def watch():
            now, f = self.robot.posx(), self.robot.tool_force()
            if now is None or f is None or base_f is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="좌표·힘 조회 실패")
            moved = mp.travel_mm(start, now, pull) / 1000.0
            resist = abs(sum((f[i] - base_f[i]) * pull[i] for i in range(3)))
            v = dp.judge_opening(moved, distance, resist, dc["stuck_force_n"], dc["pos_tol_m"])
            if v.error_code:
                verdict["v"], verdict["moved"] = v, moved
                return sf.Outcome(False, v.error_code, reason=v.reason)
            return None

        bad = self._line(goal, target, speed["pull_mm_s"], "pull", watch=watch)
        moved = mp.travel_mm(start, self.robot.posx() or start, pull) / 1000.0
        if bad:
            near_end = moved >= distance - oc["stopper_window_mm"] / 1000.0
            if not (bad.error_code == dp.DRAWER_STUCK and near_end):   # 끝 근처에서 걸림 = 스토퍼 도달로 봄
                self.disp[drawer_id] = disp + moved
                if not sf.is_safety(bad):                   # 안전 정지·취소 뒤엔 그리퍼도 그대로
                    self._grip(oc["handle_open_width_mm"], 20)
                return bad, {"drawer_displacement": round(disp + moved, 4), "close_confirmed": False}
        self.disp[drawer_id] = disp + moved
        self._grip(oc["handle_open_width_mm"], 20)
        now = self.robot.posx()
        bad = self._line(goal, mp.offset_posx(now, pull, oc["retreat_mm"]), speed["line_mm_s"], "retreat")
        if bad:
            return bad, None
        home = self._named(goal, "home")                   # 손잡이 쪽(ready) 관절 자세를 풀어 둠 — 다음 동작은 홈에서 시작
        if not home.success:
            return home, {"drawer_displacement": round(self.disp[drawer_id], 4), "close_confirmed": False}
        out = {"drawer_displacement": round(self.disp[drawer_id], 4), "close_confirmed": False}
        return sf.Outcome(True, reason=f"열림 {self.disp[drawer_id] * 1000:.1f} mm"), out

    def _close_drawer(self, goal, drawer_id, oc, dc, closed, pull, handle):
        """닫기: 손잡이를 잡지 않고, 홈 자세(그리퍼 수직 아래) 그대로 손끝을 손잡이 높이에 두고 밀어서 닫는다 — 힘이 느껴질 때까지
        [사용자 제안 10/06]. 손잡이 쪽(ready, J2 반대) 자세로 가지 않아 열린 서랍 위를 돌아가지 않음."""
        if not oc.get("close_enabled", False):
            return sf.Outcome(False, sf.NOT_IMPLEMENTED, reason="닫기 꺼짐 — 사람이 손으로 닫기 "
                                                                "(params drawer_open_close.close_enabled)"), None
        if self.held:
            return sf.Outcome(False, HOLDING_OBJECT, reason=f"{self.held['class']} 를 든 채 닫지 않음"), None
        prm = self.prm()
        speed = prm["speed"]
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), None
        home = getattr(self, "home_posx", None)
        if home and not self._over_drawer(cur):             # 트레이 쪽에서 홈을 거치지 않고 손잡이 앞으로 바로 [사용자 10/06 저녁]
            cur = list(cur[:3]) + list(home[3:])            # 미는 자세 = 홈 자세 방향(그리퍼 수직)
        else:
            o = self._named(goal, "home")
            if not o.success:
                return o, None
            cur = self.robot.posx()
            if cur is None:
                return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), None
        self._grip(oc["handle_open_width_mm"], 20)          # 살짝 벌린 두 손끝으로 손잡이 앞을 밂
        tip_z = handle[2] + mp.tip_below_tcp_mm(oc["handle_open_width_mm"], prm["gripper"])   # 손끝 = 손잡이 높이
        off = oc["vertical_push_offset_mm"]
        pre = mp.offset_posx(list(handle[:2]) + [tip_z] + list(cur[3:]), pull, off + oc["push_standoff_mm"])
        bad = self._line(goal, pre, speed["line_mm_s"], "to_drawer_front")
        if bad:
            return bad, None
        closed = list(closed[:2]) + [tip_z] + list(cur[3:])
        contact_closed = mp.offset_posx(closed, pull, off)  # 닫혔을 때 TCP 위치 (손끝 앞면이 닫힌 손잡이에)
        push = [-c for c in pull]
        base_f = self._tare()

        def remaining_m(now):
            return max(0.0, mp.travel_mm(contact_closed, now, pull) / 1000.0)

        def guard():                                        # 위치까지 밀되, 일찍 크게 걸리면 멈춤 (힘으로 판정하지 않음, 사용자 10/06)
            now, f = self.robot.posx(), self.robot.tool_force()
            if now is None or f is None or base_f is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="좌표·힘 조회 실패")
            resist = abs(sum((f[i] - base_f[i]) * push[i] for i in range(3)))
            if resist > dc["push_stop_force_n"]:
                rem = remaining_m(now)
                if rem <= oc["close_pos_tol_m"]:
                    return sf.Outcome(True, reason=f"닫힘 (남은 {rem * 1000:.1f} mm에서 {resist:.0f} N)")
                return sf.Outcome(False, dp.CLOSE_NOT_CONFIRMED, reason=f"닫힘 {rem * 1000:.1f} mm 전에 {resist:.0f} N — 걸림")
            return None

        target = mp.offset_posx(contact_closed, pull, -dc["close_overtravel_m"] * 1000.0)   # 닫힌 손잡이 y 보다 조금 더
        slow = oc.get("push_slow_last_mm", 0.0)
        bad = None
        if slow > 0 and mp.travel_mm(target, pre, pull) > slow:   # 빠르게 밀다가 마지막 slow mm 는 천천히 (끝에서 세게 박지 않게, 10/06 저녁)
            bad = self._line(goal, mp.offset_posx(target, pull, slow), speed["push_mm_s"], "push", watch=guard)
        if bad is None:
            bad = self._line(goal, target, speed.get("push_slow_mm_s", speed["push_mm_s"]) if slow > 0 else speed["push_mm_s"],
                             "push_slow", watch=guard)
        now = self.robot.posx()
        rem = remaining_m(now) if now else math.inf
        confirmed = bad is None and rem <= oc["close_pos_tol_m"]
        self.disp[drawer_id] = rem if rem != math.inf else self.disp.get(drawer_id, 0.0)
        out = {"drawer_displacement": round(self.disp[drawer_id], 4), "close_confirmed": confirmed}
        if sf.is_safety(bad):                               # 안전 정지·취소 뒤엔 후퇴하지 않음
            return bad, out
        if bad and not confirmed:
            res = bad
        elif not confirmed:
            res = sf.Outcome(False, dp.CLOSE_NOT_CONFIRMED, reason=f"닫힘 위치에 못 감 (남은 {rem * 1000:.1f} mm)")
        else:
            res = None
        back = self._line(goal, mp.offset_posx(now, pull, oc["retreat_mm"]), speed["line_mm_s"], "retreat") if now else \
            sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 후퇴 못 함")
        res = sf.worse(res, back)
        if res:
            return res, out
        self.disp[drawer_id] = 0.0
        out["drawer_displacement"] = 0.0
        return sf.Outcome(True, reason=f"닫힘 위치 도달 (남은 {rem * 1000:.1f} mm)"), out

    # --- 끌기 (nudge_object) ---
    def _relax(self, goal, pressed, base_f, d):
        """닿음 확인 뒤 멈춘 자리에서 relax_step_mm 씩 올리며, 멈춘 뒤 잰 힘 z 가 drag_force_n [하한, 상한] 의 상한 이하가 되면 그 높이.
        → (Outcome 또는 None, 끌기 시작 posx, 그때 힘 N). relax_max_steps 올려도 상한을 넘으면 PUSH_BLOCKED (걸림으로 봄)."""
        lo, hi = (float(v) for v in d["drag_force_n"])
        p, n = list(pressed), None
        for k in range(int(d["relax_max_steps"]) + 1):
            f = self._force_still(d["relax_settle_s"])
            if f is None or base_f is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="힘 조회 실패"), p, n
            n = abs(f[2] - base_f[2])
            if n <= hi:
                if n < lo and k > 0:                        # 한 칸에 범위를 지나침 → 반 칸 내려가서 끔 (그 사이 힘)
                    p = mp.with_z(p, p[2] - d["relax_step_mm"] / 2.0)
                    bad = self._step(goal, p, "relax:half_back")
                    if bad:
                        return bad, p, n
                return None, p, n
            if k == int(d["relax_max_steps"]):
                break
            p = mp.with_z(p, p[2] + d["relax_step_mm"])
            bad = self._step(goal, p, f"relax:{k + 1}")
            if bad:
                return bad, p, n
        return sf.Outcome(False, PUSH_BLOCKED, reason=f"{d['relax_max_steps'] * d['relax_step_mm']:.1f} mm 올려도 누르는 힘 "
                                                     f"{n:.1f} N > {hi:g} N (끄는 힘 {lo:g}~{hi:g} N)"), p, n

    def _force_reads(self, count, gap_s):
        """멈춘 채 gap_s 간격으로 count 번 읽기. 하나라도 조회 실패면 None."""
        out = []
        for _ in range(count):
            time.sleep(gap_s)
            f = self.robot.tool_force()
            if f is None:
                return None
            out.append(f)
        return out

    def _force_still(self, settle_s):
        """멈춘 채 settle_s 기다린 뒤 여러 번 읽은 평균 (_tare 와 같은 방식). 모두 조회 실패면 None."""
        time.sleep(settle_s)
        fs = [f for f in (self.robot.tool_force() for _ in range(int(self.prm()["force"]["tare_samples"]))) if f is not None]
        return [sum(f[i] for f in fs) / len(fs) for i in range(6)] if fs else None

    def _step(self, goal, posx, stage, tol_mm=0.05, arrive_s=2.0):
        """아주 짧은 직선 (relax 0.2 mm). 짧고 느린 이동은 관절 변화가 작아 '이동 중'이 안 떠 wait_motion 이 목표 전에 멈춤으로
        볼 수 있음 (10/06 저녁 누른 뒤 되돌아오기 1.5 mm 에서 NOT_REACHED 0.3 s 추정) → 멈춤 판정 뒤에도 좌표가 목표 tol_mm 안에 들 때까지 기다린다."""
        goal.publish_feedback(Skill.Feedback(stage=stage))
        if not self.robot.auto():
            return sf.after_command(False, what="자동 모드 전환", stop=self.robot.stop, get_state=self.state)
        early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)
        if early:
            return early
        sp, v = self.prm()["speed"], self.prm()["drag"]["press_speed_mm_s"]
        bad = sf.after_command(self.robot.movel_async(posx, v, sp["line_acc_ratio"] * v, sp["turn_deg_s"], sp["turn_acc_deg_s2"]),
                               what=f"movel({stage})", stop=self.robot.stop, get_state=self.state)
        if bad:
            return bad
        done = sf.wait_motion(get_state=self.state, cancel_requested=lambda: goal.is_cancel_requested,
                              stop=self.robot.stop, timeout_s=self.move_timeout, watch=self._joint_watch())
        if not done.success:
            return done
        t0 = time.monotonic()
        while True:
            cur = self.robot.posx()
            if cur is not None and math.dist(cur[:3], [float(x) for x in posx[:3]]) <= tol_mm:
                return None
            if time.monotonic() - t0 > arrive_s:
                late = sf.Outcome(False, sf.NOT_REACHED, reason=f"{arrive_s:g} s 안에 목표 {tol_mm:g} mm 안으로 안 옴")
                return self._where(sf._halt(self.robot.stop, self.state, time.monotonic, time.sleep, 0.05, 3.0, late), stage, posx)
            time.sleep(0.05)

    def _do_nudge_object(self, goal, params):
        target, drawer_id = params.get("target") or {}, params.get("drawer_id")
        prm, place = self.prm(), self.places().get(drawer_id) or {}
        if not place.get("tf") or not place.get("interior_m"):
            return sf.Outcome(False, DRAWER_NOT_CONFIGURED, reason=f"{drawer_id} tf·interior_m 없음"), None
        err = motion_guard.precheck_nudge(target=target, displacement_m=self.disp.get(drawer_id),
                                          tf_at_travel_m=place.get("tf_at_travel_m"), params=prm["motion_guard"])
        if err:
            return sf.Outcome(False, err.error_code, reason=err.reason), None
        size, _ = self.item(target.get("class"))
        g = dict(prm["gripper"])
        plan = mp.plan_drag(target=target, size_m=size, interior_m=place["interior_m"], g=g, drag=prm["drag"])
        out = {"pushed": False, "push_vector_m": [0.0, 0.0], "clearance_before_m": round(plan.clearance_before_m, 4),
               "floor_z_m": 0.0, "target_after": None}         # 성공일 때만 채움 — 실패 결과의 좌표로 집지 않게 (#37 E)
        if plan.error_code:                                   # check_only 재판단이면 runner.md 대로 PUSH_LIMIT
            return sf.Outcome(False, PUSH_LIMIT if params.get("check_only") else plan.error_code, reason=plan.reason), out
        if not plan.needed:
            out["target_after"] = target                      # 움직이지 않음 → 위치 그대로
            return sf.Outcome(True, reason=plan.reason), out
        if params.get("check_only"):                          # 재판단인데 아직 끌어야 함 → 집지 않게 멈춤 (runner.md, #83 D 리뷰)
            return sf.Outcome(False, PUSH_LIMIT, reason=f"check_only: 아직 잡을 수 없는 자리 — {plan.reason}"), out
        tf, d = place["tf"], prm["drag"]
        speed = prm["speed"]
        wall = mp.dir_to_base(tf, (0.0, plan.wall_normal_y, 0.0))      # 옆벽 쪽 (base)
        if d.get("close_axis", "object") == "wall":                    # 닫힘 축 = 옆벽 법선 [실측 B 10/06, 지우개 잘 끌림]
            tip_v = d["wall_tip_below_mm"]                             # 기울인 손끝이 TCP 아래 (실측)
            along = wall
        else:
            tip_v = mp.tip_contact(math.radians(d["tilt_deg"]), g)[1]  # 기울인 닫은 손끝의 가장 낮은 점 깊이 (TCP 아래, 계산)
            yaw = target["pose"]["yaw"]
            along = mp.dir_to_base(tf, (math.cos(yaw), math.sin(yaw), 0.0))  # 닫힘 축 = 물체 긴 변 (얇은 쪽이 옆벽)
        contact_z_m = size[2] + tip_v / 1000.0
        # 10/06 실물로 맞춘 순서 (scripts/b_demo.py 와 같음): 탑뷰 → 서랍 안 경유점 movej → y 를 누를 자리 y 로 →
        # 제자리 기울이기 → 누를 자리 위 start_above_mm → 누르기(오검출 대책) → 옆으로 끌기 → 올라감
        bad = self._to_drawer_view(goal, drawer_id)
        if bad:
            return bad, out
        self._grip(0, 20)                                   # 누르기용으로 닫기 (탑뷰, 서랍 위 높이)
        down = (self.poses().get("drag_down") or {}).get(drawer_id)
        if down:
            o = self._movej(goal, down, "to_object:down")
            if not o.success:
                return o, out
        px, py = plan.press_xy_m
        start_mm = [1000.0 * v for v in pp.to_base(tf, (px, py, contact_z_m + d["start_above_mm"] / 1000.0))]
        end_mm = [1000.0 * v for v in pp.to_base(tf, (px, py, contact_z_m - d["search_below_mm"] / 1000.0))]
        expect_z = 1000.0 * pp.to_base(tf, (px, py, contact_z_m))[2]
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), out
        above = mp.gripper_posx(start_mm, along, cur[3:], tilt_toward=wall, tilt_deg=d["tilt_deg"])
        if not down:                                        # 경유점이 없으면 예전처럼 safe_z 로 높이만
            cur = mp.with_z(cur, prm["transit"]["safe_z_mm"])
        aligned = [cur[0], start_mm[1], cur[2]] + list(cur[3:])
        for pose, st in ((aligned, "to_object:align"), (aligned[:3] + list(above[3:]), "to_object:tilt"),
                         (above, "to_object:over")):
            bad = self._line(goal, pose, speed["line_mm_s"], st)
            if bad:
                return bad, out
        base_f = self._tare()
        z0 = above[2]
        state = {}

        def contact():                                      # 내려가다 닿음 힘(touch_force_n)을 한 번이라도 넘으면 바로 그 자리에서 멈춤 [사용자 10/07]
            f, p = self.robot.tool_force(), self.robot.posx()
            if f is None or p is None or base_f is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="힘·좌표 조회 실패")
            if abs(f[2] - base_f[2]) >= d["press_max_force_n"]:   # 힘 상한: 무시 구간에서도 늘 봄 — 14 N 이면 서랍이 앞으로 넘어감 [사용자 10/07]
                state["z1"] = p[2]
                return sf.Outcome(True, reason=f"상한 {d['press_max_force_n']:g} N 넘음 @ z {p[2]:.2f} — 멈추고 확인")
            if not state.get("resumed") and p[2] > z0 - d["press_ignore_mm"]:
                return None                                 # 출발할 때 힘이 튐 (10/06 z 225.5 오검출) — 처음 내려갈 때만
            state.setdefault("fz", f[2])                    # 내려가는 중 기준 (힘 0점이 흐름)
            dz = f[2] - state["fz"]
            if abs(dz) >= d["touch_force_n"]:
                state["z1"] = p[2]
                return sf.Outcome(True, reason=f"{dz:+.1f} N @ z {p[2]:.2f} — 멈추고 확인")
            return None

        for k in range(int(d["touch_retries"]) + 1):
            state.pop("z1", None)
            bad = self._line(goal, end_mm + above[3:], d["press_speed_mm_s"], "press" if k == 0 else f"press:{k + 1}", watch=contact)
            if bad:
                return bad, out
            if "z1" not in state:
                break                                       # 끝까지 내려가도 안 닿음
            reads = self._force_reads(int(d["press_confirm"]), d["confirm_gap_s"])
            if reads is None or base_f is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="힘 조회 실패"), out
            ns = [abs(f[2] - base_f[2]) for f in reads]
            if all(n >= d["touch_force_n"] for n in ns):    # 멈춘 채 연속 press_confirm 번 모두 넘음 = 지우개에 닿음 [사용자 10/07]
                state["z"] = state["z1"]
                break
            state["resumed"] = True                         # 튄 값 → 그 자리에서 다시 내려감 (출발 무시 구간 없이)
        if "z" not in state or abs(state["z"] - expect_z) > d["contact_z_tol_mm"]:
            back = self._line(goal, above, speed["line_mm_s"], "lift")
            why = (f"접촉 높이 z {state['z']:.2f} 가 예상 {expect_z:.1f} ± {d['contact_z_tol_mm']:g} 밖 — 오검출로 보고 끌지 않음"
                   if "z" in state else "예상 높이보다 내려가도 접촉 없음 (또는 멈춘 뒤 확인에서 계속 튐) — 물체 위치·높이 확인")
            return sf.worse(sf.Outcome(False, NO_OBJECT_CONTACT, reason=why), back), out
        pressed = self.robot.posx()
        if pressed is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), out
        # 닿음은 큰 힘(touch_force_n)으로 확실히 확인 — 조금만 내려가도 힘이 튐 [사용자 10/07]. 확인·정지하는 동안 더 눌리므로
        # 멈춘 자리에서 relax_step_mm 씩 올리며 멈춘 뒤 힘을 재서 끄는 힘(drag_force_n, 2 N 에서 잘 끌림 [실측 10/06]) 상한 이하면 그 높이로 끈다
        bad, pressed, held_n = self._relax(goal, pressed, base_f, d)
        if bad:
            return (bad if sf.is_safety(bad) else sf.worse(bad, self._line(goal, above, speed["line_mm_s"], "lift"))), out
        shift_y = plan.shift_y_m
        if d.get("shift_mm"):                               # 잡을 수 있을 만큼(계획), 시연은 적어도 3 cm [사용자 10/07], 방향은 계획(옆벽 반대)
            shift_y = math.copysign(max(abs(plan.shift_y_m), d["shift_mm"] / 1000.0), plan.shift_y_m)
        shift = mp.dir_to_base(tf, (0.0, shift_y, 0.0))
        shift = [shift[0], shift[1], 0.0]                     # 수평으로만 (b_demo 와 같음): 서랍 tf 기울기로 41.7 mm 에 z −0.5 mm 가 섞이면
        #   끌면서 더 눌림 — 위치로 누르면 1 mm 에 2 → 10 N [실측 10/06] → 10/06 저녁 통합 PUSH_BLOCKED 15.1 N
        base_drag = self._tare()

        def blocked():
            f = self.robot.tool_force()
            if f is None or base_drag is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="힘 조회 실패")
            mag = math.sqrt(sum((f[i] - base_drag[i]) ** 2 for i in range(3)))
            if mag > d["max_force_n"]:
                return sf.Outcome(False, PUSH_BLOCKED, reason=f"끄는 중 힘 {mag:.1f} N > {d['max_force_n']:g} N")
            return None

        drag_to = [pressed[i] + 1000.0 * shift[i] for i in range(3)] + pressed[3:]
        bad = self._line(goal, drag_to, d["speed_mm_s"], "drag", watch=blocked)
        if sf.is_safety(bad):                               # 안전 정지·취소 뒤엔 올리지도 않음
            return bad, out
        now = self.robot.posx()
        if now is None:
            return sf.worse(bad, sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 올리지 못함")), out
        bad = sf.worse(bad, self._line(goal, mp.with_z(now, now[2] + d["lift_mm"]), speed["line_mm_s"], "lift"))
        moved = mp.from_base(tf, [v / 1000.0 for v in now[:3]])
        before = mp.from_base(tf, [v / 1000.0 for v in pressed[:3]])
        dy = moved[1] - before[1]
        after = json.loads(json.dumps(target))
        after["pose"]["position"] = [target["pose"]["position"][0], target["pose"]["position"][1] + dy, 0.0]
        out.update(pushed=True, push_vector_m=[0.0, round(dy, 4)])   # floor_z_m: 바닥은 서랍 좌표 z=0
        if bad:
            return bad, out                                 # target_after 는 None (실패 결과 좌표로 집지 않음)
        out["target_after"] = after
        return sf.Outcome(True, reason=f"{held_n:.1f} N 으로 눌러 옆으로 {dy * 1000:+.1f} mm 끌기"), out

    # --- 집기 ---
    def _do_pick_object(self, goal, params):
        if "source_slot" in params:
            return sf.Outcome(False, UNSUPPORTED_PARAMS, reason="트레이에서 집기는 P2"), None
        if self.held:
            return sf.Outcome(False, HOLDING_OBJECT, reason=f"이미 {self.held['class']} 를 들고 있음"), None
        target = params.get("target") or {}
        drawer_id = params.get("drawer_id") or (target.get("pose") or {}).get("frame")   # 계약엔 drawer_id 없음 → pose.frame
        if drawer_id not in ("drawer_top", "drawer_bottom"):
            return sf.Outcome(False, sf.BAD_PARAMS, reason=f"target.pose.frame 이 서랍이 아님: {drawer_id!r}"), None
        prm, place = self.prm(), self.places().get(drawer_id) or {}
        cls = target.get("class")
        size, grip_force = self.item(cls)
        err = motion_guard.precheck_pick(target=target, height_m=size[2], displacement_m=self.disp.get(drawer_id),
                                         tf_at_travel_m=place.get("tf_at_travel_m"), params=prm["motion_guard"])
        if err:
            return sf.Outcome(False, err.error_code, reason=err.reason), None
        wall = mp.wall_blocks_grasp(target=target, size_m=size, interior_m=place.get("interior_m") or [0, 0, 0],
                                    g=prm["gripper"])
        if wall:                                            # 움직이기 전 거부 (#83 A 요청, #80 D P1 후속)
            return sf.Outcome(False, WALL_TOO_CLOSE, reason=wall), None
        plan = pp.plan_drawer_grasp(target=target, size_m=size, tf=place["tf"], params=prm["pick"])
        g, speed = prm["gripper"], prm["speed"]
        bad = self._to_drawer_view(goal, drawer_id)
        if bad:
            return bad, None
        close_dir = mp.horizontal_angle_dir(plan.long_axis_deg + 90.0)
        grasp = mp.gripper_posx([1000.0 * v for v in plan.position_m], close_dir, self._cur_angles())
        off = params.get("approach_offset", 0.10)              # 태스크·온톨로지는 [0, 0, 0.1] (m) — z 만 씀
        approach = float(off[2] if isinstance(off, (list, tuple)) else off) * 1000.0
        above = mp.with_z(grasp, max(prm["transit"]["safe_z_mm"], grasp[2] + min(approach, 30.0)))   # 서랍 테두리만 넘는 높이 (10/06 사용자: 쓸데없이 높이지 않음)
        bad = self._transit(goal, above, "to_object")
        if bad:
            return bad, None
        self._grip(plan.open_width_m * 1000.0, 20)
        bad = self._line(goal, grasp, speed["grasp_mm_s"], "descend")
        if bad:
            return bad, None
        force = float(params.get("grip_force") or grip_force or g["default_grip_force_n"])
        goal.publish_feedback(Skill.Feedback(stage="close"))
        st = self._grip(0, force)
        chk = gc.check_grasp(width_m=st.width_mm / 1000.0, grasp_detected=st.grip_detected, min_width_m=g["min_width_m"],
                             expected_width_m=plan.expected_width_m, width_tolerance_m=g["grasp_width_tolerance_m"])
        if not chk.ok:
            self._grip(plan.open_width_m * 1000.0, 20)
            back = self._line(goal, above, speed["line_mm_s"], "lift")
            return sf.worse(sf.Outcome(False, GRASP_FAILED, reason=f"파지 실패 {chk.reason} (폭 {st.width_mm:.1f} mm)"),
                            back), {"object_id": target.get("id"), "class": cls, "grasp_ok": False}
        route = self._carry_route(drawer_id)
        # 집고 바로 경유점 1(서랍 중앙)로 직선(대각선) — 쓸데없이 높이지 않음, 도착 뒤 잠깐 멈춤 [사용자 10/06 저녁]
        bad = self._line(goal, route[0] if route else above, speed["line_mm_s"], "lift")
        if bad:
            return bad, None
        if route:
            time.sleep(prm["carry"]["pause_s"])
        st2 = Rg2(self.rg2_ip)
        try:
            w2 = st2.status().width_mm / 1000.0
        finally:
            st2.close()
        hold = gc.check_hold(width_m=w2, width_at_grasp_m=chk.width_m, min_width_m=g["min_width_m"],
                             slip_tolerance_m=g["slip_tolerance_m"])
        if not hold.held:
            return sf.Outcome(False, GRASP_FAILED, reason=f"들어 올리다 놓침 ({hold.reason})"), \
                {"object_id": target.get("id"), "class": cls, "grasp_ok": False}
        floor_z = pp.to_base(place["tf"], (target["pose"]["position"][0], target["pose"]["position"][1], 0.0))[2]
        self.held = {"class": cls, "id": target.get("id"), "width_m": chk.width_m, "drawer_id": drawer_id,
                     "tcp_above_floor_m": plan.position_m[2] - floor_z}
        out = {"object_id": target.get("id"), "class": cls, "pick_pose_drawer_frame": target.get("pose"),
               "grasp_ok": True}
        return sf.Outcome(True, reason=f"{cls} 파지 (폭 {chk.width_m * 1000:.1f} mm, {hold.reason})"), out

    # --- 놓기 ---
    def _do_place_object(self, goal, params):
        loc = params.get("location")
        if loc != "handover_zone":
            return sf.Outcome(False, UNSUPPORTED_PARAMS, reason=f"P1 놓기는 handover_zone 만: {loc!r}"), None
        if not self.held:
            return sf.Outcome(False, NOT_HOLDING, reason="들고 있는 물체 없음"), None
        prm, place = self.prm(), self.places().get(loc) or {}
        tf, interior = place.get("tf") or {}, place.get("interior_m")
        if not tf.get("translation_m") or not interior:
            return sf.Outcome(False, PLACE_NOT_CONFIGURED, reason=f"{loc} tf·interior_m 측정 전"), None
        slots = pp.slot_centers(interior[:2], int(place.get("slots") or 1))
        used = self.tray.setdefault(loc, [])
        free = [i for i in range(len(slots)) if i not in used]
        if not free:
            return sf.Outcome(False, TRAY_FULL, reason=f"{loc} {len(slots)}칸 모두 사용"), None
        i = free[0]
        g, pl, speed = prm["gripper"], prm["place"], prm["speed"]
        # 서랍 → 트레이 (10/06 사용자): 집어서 올린 뒤 서랍 앞판 위 높이(high_z)로 로봇 쪽(홈 위)으로 당겨 서랍 영역을 빠져나오고,
        # 거기서 트레이 칸 위로 바로 (보는 자세·tray_view 를 거치지 않음 — 팔을 편 자세에서 특이점·꺾임)
        z_m = mp.place_tcp_above_floor_m(self.held["tcp_above_floor_m"], pl["drop_m"])
        pos = [1000.0 * v for v in pp.to_base(tf, (slots[i][0], slots[i][1], z_m))]
        close_dir = mp.dir_to_base(tf, (1.0, 0.0, 0.0))                 # 칸이 x로 늘어섬 → 물체 긴 변은 y, 손가락은 x로
        target = mp.gripper_posx(pos, close_dir, self._cur_angles())
        above = mp.with_z(target, max(prm["transit"]["free_lift_z_mm"], target[2] + pl["approach_m"] * 1000.0))
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), None
        legs = []
        route = self._carry_route(self.held.get("drawer_id"))
        if route and self._over_drawer(cur):
            # 들고 나오기(carry_line): 경유점 1(서랍 중앙) → 2·3·4 → 트레이 칸 위(4번 높이) → 놓는 자리를 직선 블렌딩으로 한 번에,
            # 모서리 반지름 carry.radius_mm, 놓는 자리에서만 정지 [사용자 직접교시 10/06 저녁 — 긴 물체는 movesj 가 불안]
            if max(abs(cur[k] - route[0][k]) for k in range(3)) > 1.0:   # 집기가 경유점 1에서 끝나지 않았으면 먼저 거기로
                bad = self._line(goal, route[0], speed["line_mm_s"], "carry:1")
                if bad:
                    return bad, None
                time.sleep(prm["carry"]["pause_s"])
            pts = route[1:] + [list(target[:2]) + [route[-1][2]] + list(target[3:])]   # 칸 위(4번 높이)까지 블렌딩, 거기서 정지
            rad = prm["carry"]["radius_mm"]
            bad = self._blend(goal, pts, [rad] * (len(pts) - 1) + [0.0], speed["line_mm_s"], "carry")
            if bad:
                return bad, None                            # 놓는 자리로는 grasp_mm_s 로 살포시 (10/06 저녁: 놓기는 빠르게 하지 않음)
            above = list(pts[-1])                           # 이미 칸 위 — 다시 올리지 않음, 놓은 뒤에도 여기로
        elif self._over_drawer(cur):
            # 들고 나오기(carry_out): 직접교시 경유점 4개를 movesj 로 한 번에 — 서랍 안 → 서랍 위 → 앞판 넘음 → 트레이 쪽
            # [사용자 직접교시·실물 확인 B 10/06]. 그다음 트레이 칸 위로 직선 (4번 높이, y = 트레이 가운데)
            route = ((self.poses().get("carry_out") or {}).get(self.held.get("drawer_id") or "drawer_top"))
            if not route:
                return sf.Outcome(False, sf.POSE_NOT_TAUGHT, reason="poses.yaml carry_out 경유점 없음"), None
            o = self._movej(goal, route[0], "carry_out:1")         # 첫 경유점은 movej, 나머지 movesj (b_demo 와 같음)
            if not o.success:
                return o, None
            bad = self._spline(goal, route[1:], "carry_out") if len(route) > 1 else None
            if bad:
                return bad, None
            p4 = self.robot.posx()
            if p4 is None:
                return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), None
            above = list(above[:2]) + [p4[2]] + list(above[3:])
        if not (route and self._over_drawer(cur)):
            legs.append((above, "transport"))
        for pose, st in legs:
            bad = self._line(goal, pose, speed["line_mm_s"], st)
            if bad:
                return bad, None
        r = Rg2(self.rg2_ip)
        try:
            w = r.status().width_mm / 1000.0
        finally:
            r.close()
        hold = gc.check_hold(width_m=w, width_at_grasp_m=self.held["width_m"], min_width_m=g["min_width_m"],
                             slip_tolerance_m=g["slip_tolerance_m"])
        if not hold.held:
            self.held = None
            return sf.Outcome(False, gc.FAILURE_CODE["transport"], reason=f"옮기는 중 놓침 ({hold.reason})"), None
        bad = self._line(goal, target, speed["grasp_mm_s"], "lower")
        if bad:
            return bad, None
        goal.publish_feedback(Skill.Feedback(stage="release"))
        self._grip(self.held["width_m"] * 1000.0 + pl["release_extra_mm"], 20)
        used.append(i)
        cls = self.held["class"]
        self.held = None
        back = self._line(goal, above, speed["line_mm_s"], "lift")
        out = {"slot": f"{loc}_{i + 1}", "placed_pose": {"frame": loc, "position": [round(slots[i][0], 4),
                                                                                     round(slots[i][1], 4), 0.0]}}
        if back:                                            # 놓기는 끝났지만 올라오지 못함 → 그 오류 (안전 오류 보존)
            return back, out
        return sf.Outcome(True, reason=f"{cls} → {loc} {i + 1}번 칸"), out


def main():
    rclpy.init()
    node = SkillServer()
    if not node.robot.ready():
        node.get_logger().error("DSR 서비스가 없음 — 드라이버가 실행 중인지 확인")
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:                                 # 실행 중인 goal 은 executor 가 멈추며 끊김 — 로봇 정지는 펜던트·Runner 취소로
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
