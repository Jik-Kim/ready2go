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
  - pick_object (서랍): 짧은 변 잡기, 폭 확인, 들어 올린 뒤 놓침 확인 / place_object: handover_zone 빈 칸,
    서랍 안 pose·slot (#120 ②·#166 — 이웃·벽 겹침은 움직이기 전 거부, 실물 미확인)
  값은 params/skills.yaml (10/05~06 로봇 실측), 장소는 config/places.yaml, 물체 크기는 knowledge/world.jsonld.

실행 (PC2, DSR 드라이버 실행 중):
    ros2 run ready2go_skills skill_server
    ros2 run ready2go_skills skill_server --ros-args -p joint_vel_deg_s:=10.0   # 처음은 저속 (safety.md 11)
"""
import copy
import dataclasses
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
from ready2go_skills.core import clear_plan as clp, neighbor_check as nc
from ready2go_skills.core import pick_plan as pp, place_plan as plp, pose_math as pm, skill_flow as sf

ACTIONS = ("move_to_named_pose", "drawer_control", "nudge_object", "pick_object", "place_object")
IN_DRAWER_POSES = ("drawer_top_view", "drag_down")   # 서랍 위에서 서랍 위로 가는 기준 포즈 — 서랍 밖으로 빼지 않고 바로 관절 이동
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
NEIGHBOR_TOO_CLOSE = nc.NEIGHBOR_TOO_CLOSE   # pick·nudge: scan 의 옆 물체가 벌린 손가락·끄는 길에 걸림 (움직이기 전) [사용자 10/09]
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
NOT_AT_START_POSE = "NOT_AT_START_POSE"    # 노드 시작 자세가 아님 → 움직이기 전 거부 (노드 안에서 시작 자세로 알아서 가지 않음, #168)


def find_config_dir():
    env = os.environ.get("READY2GO_CONFIG_DIR")
    if env:
        return Path(env)
    for d in Path(__file__).resolve().parents:
        if (d / "config" / "poses.yaml").exists():
            return d / "config"
    return Path.home() / "ready2go" / "config"


_YAML_CACHE = {}


def _yaml_cached(path, loads=None, copy_=True):
    """YAML 을 파일 수정 시각·크기가 바뀔 때만 다시 파싱 (돌려줄 땐 복사 — 받은 쪽이 고쳐도 다음 호출에 안 섞임).
    이동 감시 반복(0.05 s)마다 skills.yaml 을 다시 파싱하던 것(약 50 ms)이 감시 주기를 두 배로 늘렸음 [P2 시뮬레이션 10/10 측정].
    loads: 다른 형식(json.loads — world.jsonld). copy_=False 는 읽기만 하는 쪽 (복사 비용도 아낌)."""
    path = Path(path)
    st = path.stat()
    key = (st.st_mtime_ns, st.st_size)
    hit = _YAML_CACHE.get(path)
    if hit is None or hit[0] != key:
        try:
            data = (loads or yaml.safe_load)(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, ValueError):
            data = None
        if not isinstance(data, dict) and hit is not None:
            return copy.deepcopy(hit[1])                # 저장하는 중(빈 파일·반쯤 쓴 파일)에 읽음 → 전 값, 다음 호출에 다시 읽음
        hit = (key, data)                                #   [P2 시뮬레이션 10/11: 돌리는 중 skills.yaml 저장 → None → SKILL_EXCEPTION]
        _YAML_CACHE[path] = hit
    return copy.deepcopy(hit[1]) if copy_ else hit[1]


def _width_m(width_mm):
    """그리퍼 폭 mm → m (결과 JSON 용). NaN·inf·숫자 아님이면 None — 결과에 NaN 을 싣지 않음."""
    if isinstance(width_mm, bool) or not isinstance(width_mm, (int, float)) or not math.isfinite(width_mm):
        return None
    return round(width_mm / 1000.0, 4)


# ---- 파지 공간 만들기 [제안 10/11 B, 계약 승인 전] — 계획(core/clear_plan)이 묻는 "집을 수 있나·놓을 수 있나"를
#      서버의 실제 사전 검사로 답함. 움직이는 메서드는 막아 두고 처음 움직이려는 순간 = 가능으로 봄 (로봇은 안 움직임).
NO_FREE_SPACE = "NO_FREE_SPACE"          # nudge_object make_room: 치울 물체를 놓을 빈 자리가 서랍에 없음 (움직이기 전)
TRAY = "handover_zone"                   # 전달 트레이 — pick_object 가 트레이에서도 집음 (return_items, 3차 챌린지 전 10/12)
FREE_SLOT = "free"                       # place_object slot "free": 고정 aside 대신 서랍 안 빈 자리 (B free·make_room 과 같은 core/clear_plan)
OCCLUSION_UNKNOWN = "OCCLUSION_UNKNOWN"  # nudge_object make_room: 가림 관계(occluded_by) 모름·박스 모델 — 움직이기 전, 다시 찍기
_MOTION = ("_to_drawer_view", "_line", "_blend", "_named", "_movej", "_grip", "_over_then_down", "_line_slow", "_exit_drawer",
           "_transit", "_step")
_QUIET = type("_Quiet", (), {k: staticmethod(lambda *a, **kw: None) for k in ("info", "warn", "warning", "error", "debug")})()
_DRY_GOAL = type("_DryGoal", (), {"is_cancel_requested": False, "publish_feedback": staticmethod(lambda f: None)})()


class _WouldMove(Exception):
    """사전 검사를 다 통과하고 처음으로 움직이려 함 = 가능."""


def _would_move(*a, **kw):
    raise _WouldMove()


class _Dry:
    """서버를 감싼 판단 전용 사본: 메서드는 서버 것을 이 사본에 묶어 부르고(self.<움직임> 이 막힘), 상태(held·disp)는 사본 것.
    파일에 쓰는 held 저장(property setter)도 타지 않음."""

    def __init__(self, srv, held=None):
        self.__dict__.update(_srv=srv, held=held, disp=dict(srv.disp))

    def __getattr__(self, name):
        if name in _MOTION:
            return _would_move
        if name == "get_logger":
            return lambda: _QUIET
        attr = getattr(type(self._srv), name, None)
        if isinstance(attr, property):
            return attr.fget(self)
        if callable(attr) and not isinstance(attr, type):
            return attr.__get__(self)
        return getattr(self._srv, name)


def _dry_call(fn):
    try:
        out = fn()
    except _WouldMove:
        return True, "", ""
    except Exception as e:                                       # 설정·계산 예외 = 못 함
        return False, sf.SKILL_EXCEPTION, repr(e)[:120]
    o = out[0] if isinstance(out, tuple) else out
    return bool(o.success), o.error_code or "", o.reason or ""


def _scan_of(objs, tid):
    """계획 중인 물체 목록 → inspect_region 결과 형식 (목표 + 나머지)."""
    t = next(o for o in objs if o["id"] == tid)
    return {"target_found": True, "target": t, "candidates": [o for o in objs if o["id"] != tid], "visible_count": len(objs)}


class DryOracle:
    """core/clear_plan 의 oracle — pick(objs, id)·place(objs, held_id, pose|slot)·wall_nudge(objs, id). 로봇은 안 움직임."""

    def __init__(self, srv, drawer_id):
        self.srv, self.drawer = srv, drawer_id
        self.calls = 0

    def pick(self, objs, oid):
        self.calls += 1
        t = next(o for o in objs if o["id"] == oid)
        if t.get("occluded_by"):                                 # 위에 얹힌 물체 (분할 비전 occluded_by)
            return False, "COVERED", "위에 다른 물체"
        dry = _Dry(self.srv)
        return _dry_call(lambda: dry._do_pick_object(_DRY_GOAL, {"target": t, "approach_offset": [0, 0, 0.1], "scan": _scan_of(objs, oid)}))

    def place(self, objs, held_id, pose_or_slot):
        self.calls += 1
        h = next(o for o in objs if o["id"] == held_id)
        srv, prm = self.srv, self.srv.prm()
        size = srv._size_or_none(h["class"]) or prm["place"]["default_obstacle_size_m"]
        gw = srv.grasp_width(h["class"], size, prm) or size[1]
        dry = _Dry(srv, held={"class": h["class"], "id": held_id, "width_m": gw, "drawer_id": self.drawer,
                              "tcp_above_floor_m": size[2] * prm["pick"].get("grip_height_ratio", 0.5), "long_side": False})
        p = {"location": self.drawer, "scan": _scan_of(objs, held_id)}
        p.update({"slot": pose_or_slot} if isinstance(pose_or_slot, str) else {"pose": pose_or_slot})
        return _dry_call(lambda: dry._place_in_drawer(_DRY_GOAL, p, self.drawer))

    def wall_nudge(self, objs, oid):
        """기존 벽 넛지 계획(mp.plan_drag) → 예상 위치. 끄는 길에 높이가 겹치는 물체가 있으면 거부 (그땐 계획이 밀기로 넘김)."""
        self.calls += 1
        srv, prm = self.srv, self.srv.prm()
        t = next(o for o in objs if o["id"] == oid)
        place = srv.places()[self.drawer]
        size = srv._size_or_none(t["class"])
        if not size:
            return None, sf.BAD_PARAMS, f"{t['class']} 크기 모름"
        try:
            plan = mp.plan_drag(target=t, size_m=size, interior_m=place["interior_m"], g=srv._drag_g(self.drawer, t["class"]),
                                drag=prm["drag"])
        except Exception as e:
            return None, sf.SKILL_EXCEPTION, repr(e)[:100]
        if plan.error_code:
            return None, plan.error_code, plan.reason
        if not plan.needed:
            return None, "NOT_NEEDED", plan.reason
        if plan.push_to_xy_m is not None:                        # 뒤에서 밀어 벽에 붙임 → 벽에 붙어 축에 맞춤 [예상]
            hit = srv._push_finger_blocker(plan, t, objs, prm.get("neighbor") or {"margin_mm": 5.0})
            if hit:                                              # 손가락 내려갈 자리에 이웃 → 실제 넛지도 거부 (계획은 그 이웃부터)
                return None, NEIGHBOR_TOO_CLOSE, f"뒤에서 밀 손가락 자리에 {hit}"
            px, py = plan.push_dir
            half = size[1] / 2.0
            p = list(t["pose"]["position"])
            if px:
                p[0] = half + 0.0005 if px < 0 else place["interior_m"][0] - half - 0.0005
            else:
                p[1] = half + 0.0005 if py < 0 else place["interior_m"][1] - half - 0.0005
            after = dict(t, pose=dict(t["pose"], position=p, yaw=math.pi / 2 if px else 0.0))
        else:
            after = clp.moved(t, plan.shift_x_m, plan.shift_y_m)
        size_of = srv._size_cached()
        group = {oid} | clp.riders(objs, oid)
        others = [o for o in objs if o["id"] not in group]
        dx, dy = (after["pose"]["position"][i] - t["pose"]["position"][i] for i in (0, 1))
        for k in range(1, 21):
            mid = clp.moved(t, dx * k / 20.0, dy * k / 20.0)
            hit = next((o["id"] for o in others if clp.collide(mid, o, size_of)), None)
            if hit:
                return None, NEIGHBOR_TOO_CLOSE, f"끄는 길에 {hit}"
        return after, "", plan.reason



class _HeldOracle(DryOracle):
    """빈 자리 찾기(clear_plan.find_free_pose)용 — 놓기 검사는 실제(또는 예정) 쥔 상태로, 다시 집기 검사는 DryOracle 그대로."""

    def __init__(self, srv, drawer_id, held):
        super().__init__(srv, drawer_id)
        self.held = held

    def place(self, objs, held_id, pose_or_slot):
        self.calls += 1
        dry = _Dry(self.srv, held=dict(self.held))
        p = {"location": self.drawer, "scan": _scan_of(objs, held_id), "pose": pose_or_slot}
        return _dry_call(lambda: dry._place_in_drawer(_DRY_GOAL, p, self.drawer))

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
        self.held_file = Path(self.declare_parameter("held_file", "/tmp/r2g_skill_held.json").value)
        self.hold_unknown = None             # 재시작 때 쥔 기록이 있는데 그리퍼 폭을 못 읽음 = 쥐었는지 모름 → 그리퍼 쓰는 동작 거부 (P2 5절)
        self._held = self._restore_held()    # 들고 있는 물체 {class, id, width_m, drawer_id, tcp_above_floor_m} — 파일에도 저장(재시작 뒤 복원)
        self.tray_file = Path(self.declare_parameter("tray_file", "/tmp/r2g_skill_tray.json").value)
        self.tray = {}                       # 장소별 쓴 칸 — 파일에도(B trayclear 가 지움). 서버를 다시 켜면 빈 트레이로 시작(예전과 같음)
        self.locked = None                   # 잠금 사유(skill_flow.LOCKING_CODES). 사람이 로봇을 확인하고 서버를 다시 띄울 때까지 모든 동작 거부
        self.gate = sf.MotionGate()          # 5개 액션 전체에서 한 번에 하나만 실행 (#73 E 리뷰)
        group = ReentrantCallbackGroup()
        self._servers = [ActionServer(self, Skill, f"/skills/{a}", self._execute_for(a), callback_group=group,
                                      goal_callback=self._on_goal,
                                      cancel_callback=lambda _: CancelResponse.ACCEPT) for a in ACTIONS]
        self.get_logger().info(f"스킬 서버 준비: /skills/{{{','.join(ACTIONS)}}} (관절 {self.joint_vel}°/s, "
                               f"기대 TCP {self.expected_tcp}·툴 {self.expected_tool}, config {cfg})")

    @property
    def held(self):
        return getattr(self, "_held", None)

    @held.setter
    def held(self, v):
        """바뀔 때마다 파일에 저장/삭제 — 서버를 다시 켜도 쥔 물체를 잊지 않게 [사용자 10/08: 재시작 뒤 놓기 NOT_HOLDING]."""
        self._held = v
        f = getattr(self, "held_file", None)
        if f is None:
            return
        try:
            if v:
                f.write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
            else:
                f.unlink(missing_ok=True)
        except OSError as e:
            self.get_logger().warning(f"쥔 물체 기록 실패 {f}: {e}")

    @property
    def tray(self):
        """트레이 쓴 칸 {장소: [칸 번호]}. tray_file 이 있으면 매번 파일에서 읽음 — 사람이 트레이를 비우고 `B trayclear`(파일 삭제)로
        알리면 서버를 다시 켜지 않아도 다음 놓기부터 1번 칸 [사용자 10/11]."""
        f = getattr(self, "tray_file", None)
        if f is None:
            return dict(getattr(self, "_tray", {}))
        try:
            v = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return v if isinstance(v, dict) else {}

    @tray.setter
    def tray(self, v):
        self._tray = dict(v)
        f = getattr(self, "tray_file", None)
        if f is None:
            return
        try:
            if v:
                f.write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
            else:
                f.unlink(missing_ok=True)
        except OSError as e:
            self.get_logger().warning(f"트레이 칸 기록 실패 {f}: {e}")

    def _restore_held(self):
        """서버 시작 때: 저장된 쥔 물체가 있고 그리퍼가 실제로 같은 폭으로 쥐고 있으면(check_hold) 되살림. 아니면 기록 지움."""
        f = self.held_file
        try:
            saved = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        g = self.prm()["gripper"]
        try:
            rg = Rg2(self.rg2_ip)
            try:
                st = rg.status()
            finally:
                rg.close()
            hold = gc.check_hold(width_m=st.width_mm / 1000.0, width_at_grasp_m=float(saved["width_m"]),
                                 min_width_m=g["min_width_m"], slip_tolerance_m=g["slip_tolerance_m"])
        except Exception as e:                              # 그리퍼를 못 읽음 = 쥐었는지 모름: 빈손으로 보지 않음 (기록은 남김 — 다음 시작 때 다시)
            self.get_logger().warning(f"쥔 물체 복원 못 함 (그리퍼 읽기 실패: {e}) — 그리퍼 쓰는 동작 거부, 확인 뒤 서버 재시작")
            self.hold_unknown = saved
            return None
        if hold.reason == gc.HELD:                          # 저장한 폭과 slip_tolerance 안일 때만 (활짝 열림·빈손 닫힘·많이 다름은 아님)
            self.get_logger().info(f"쥔 물체 복원: {saved.get('class')} (그리퍼 폭 {st.width_mm:.1f} mm, 저장 {float(saved['width_m']) * 1000:.1f} mm)")
            return saved
        if hold.reason == gc.SENSOR_INVALID:                # 폭 NaN·범위 밖 — 쥐었는지 모름: 메모리엔 안 올리되 기록은 남김 (다음 시작 때 다시) [D #216]
            self.get_logger().warning(f"쥔 물체 복원 보류 — 그리퍼 폭 이상 ({st.width_mm!r} mm), 기록 유지 {f}. "
                                      "그리퍼 쓰는 동작 거부, 확인 뒤 서버 재시작")
            self.hold_unknown = saved
            return None
        self.get_logger().info(f"저장된 쥔 물체 {saved.get('class')} 무시 — 그리퍼가 쥐고 있지 않음 ({hold.reason}, 폭 {st.width_mm:.1f} mm)")
        f.unlink(missing_ok=True)
        return None

    def _refuse_if_hold_unknown(self):
        """쥐었는지 모르면(재시작 때 폭 못 읽음) 그리퍼를 벌리거나 닫는 동작을 움직이기 전에 거부 — 빈손으로 보고 집기를
        시작하면 쥔 물체를 떨어뜨림 [P2 5절 '보유 불명확을 빈손으로 갱신하지 않음·그리퍼 명령 전 차단']. 기준 포즈 이동은 허용.
        풀기: 사람이 그리퍼를 확인 → 서버 재시작(폭이 정상이면 복원·빈손이면 기록 지움)."""
        u = getattr(self, "hold_unknown", None)
        if not u:
            return None
        return sf.Outcome(False, gc.SENSOR_INVALID, reason=f"쥐었는지 모름 — 재시작 때 그리퍼 폭 못 읽음 (기록 {u.get('class')}). "
                                                            "그리퍼 확인 뒤 스킬 서버 재시작 (로봇 동작 없음)")

    def poses(self):
        """파일이 바뀌면 다시 읽음 — 교시값을 고친 뒤 서버를 재시작하지 않아도 되게."""
        return _yaml_cached(self.cfg_dir / "poses.yaml")

    def prm(self):
        return _yaml_cached(self.params_file)

    def places(self):
        return _yaml_cached(self.cfg_dir / "places.yaml")

    def item(self, cls):
        """온톨로지 size_m [긴 변, 짧은 변, 높이] 과 item_grasp.yaml 잡는 힘."""
        # 파일이 바뀔 때만 다시 읽음 — 서랍 안 놓기 자리 맞춤이 후보마다 이웃 크기를 물어 매번 디스크에서 읽던 것(한 번 10 ms × 약 900)이
        # 막힌 aside 에서 10~20 s 걸림 [PC2 10/12 B unpack "계산이 엄청 오래"]
        world = _yaml_cached(self.cfg_dir.parent / "knowledge" / "world.jsonld", loads=json.loads, copy_=False) or {}
        items = world.get("world", {}).get("items", {})
        if cls not in items or "size_m" not in items[cls]:
            raise ValueError(f"온톨로지에 {cls!r} 크기 없음")
        grasp = _yaml_cached(self.cfg_dir / "item_grasp.yaml", copy_=False) or {}
        force = (grasp.get(cls) or {}).get("grip_force")
        return [float(v) for v in items[cls]["size_m"]], force

    def grasp_width(self, cls, size_m, prm, long_side=False):
        """온톨로지 `config/item_grasp.yaml` 의 `grasp_width_m` — 실제로 잡는 부위의 폭 (망치는 외접박스 짧은 변 75 mm 가 아니라 손잡이).
        long_side 면 `grasp_width_long_m` (긴 변 양끝을 잡은 폭 — 장난감차는 바퀴 빼고 몸통) [실측 PC2 10/11].
        없으면 None (온톨로지 변을 씀). 0 이하·그 변보다 큰 값은 움직이기 전에 거부 (#43). prm 은 쓰지 않음(호환)."""
        key, side = ("grasp_width_long_m", size_m[0]) if long_side else ("grasp_width_m", size_m[1])
        grasp = _yaml_cached(self.cfg_dir / "item_grasp.yaml") or {}
        w = (grasp.get(cls) or {}).get(key)
        if w is None:
            return None
        if isinstance(w, bool) or not isinstance(w, (int, float)) or not 0.0 < w <= side:
            raise ValueError(f"{cls} {key} 은 0 초과·그 변({side}) 이하: {w!r}")
        return float(w)

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

    def _named(self, goal, pose_name, drawer_id=None, moving=False):
        """기준 포즈로 관절 이동 (낮으면 먼저 수직으로 올림). 성공이면 Outcome(True), 아니면 실패 Outcome.
        moving: 앞 직선이 반지름 안에서 아직 움직이는 중 (닫기 → 홈 한 동작 [사용자 10/10]) — 관절 이동이 거부되면 멈춘 뒤 다시."""
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
        if self._over_drawer(cur) and pose_name not in IN_DRAWER_POSES:
            # 서랍 위(탑뷰 등)에서 홈 쪽으로 바로 관절 이동하면 팔이 열린 앞판·손잡이로 내려와 침
            # [실측 10/07 PC2: 탑뷰 → 닫기(홈 경유) 2 s 만에 충돌 알람 7060] → 앞판 위 높이로 서랍 밖까지 빼고 관절 이동
            bad = self._exit_drawer(goal, cur)
            if bad:
                return bad
            cur = self.robot.posx()
            if cur is None:
                return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 서랍 밖으로 뺀 뒤 높이 확인 못 함")
        if pose_name in ("drawer_top_view", "drawer_approach") and self._over_tray(cur):
            # 트레이 위에서 서랍 쪽 자세로: 여기서 high_z(325)·safe_z(300)로 수직으로 올리면 팔이 거의 펴져 제어기가 출발 안 함
            # [실측 PC2 10/12 B unpack: 트레이 놓기 → 탑뷰 lift (543.8, 225.5) z 100 → 325, 1 s 그대로 NOT_REACHED 두 번]
            # → 트레이 놓은 뒤 늘 하던 대로 홈(free_lift_z 로 올린 뒤 관절 이동)을 거쳐 감 (Runner 도 놓기 → 탑뷰로 바로 감)
            bad = self._named(goal, "home")
            if not bad.success:
                return bad
            cur = self.robot.posx()
            if cur is None:
                return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 홈 뒤 높이 확인 못 함")
        tr = self.prm()["transit"]
        # 관절 이동은 경로 높이를 보장하지 않음 → 낮으면 먼저 수직으로 올림 (#83 D 재검토 P1).
        # 서랍 위: safe_z(300). 그 밖(트레이 등): free_lift_z(150) — 트레이 쪽 z 300은 팔이 거의 펴져 위험
        lift_z = tr["safe_z_mm"] if self._over_drawer(cur) else tr["free_lift_z_mm"]
        if pose_name == "drawer_top_view" and not self._over_drawer(cur):
            lift_z = max(lift_z, tr["high_z_mm"])          # 홈 쪽에서 보는 자세로: 앞판·손잡이 위로 올린 뒤 (10/06 실물, 낮게 가면 손잡이에 걸림)
        if pose_name == "drawer_approach":
            lift_z = max(lift_z, tr["safe_z_mm"])          # 홈 → z 300 → ready: drawer_control 열기·b_demo 와 같은 경로 (10/06 통합: 홈에서 바로 가면 손잡이보다 낮게 지나감)
        # 서랍 밖·빈손일 때만 (홈 → high_z 325 → 탑뷰: 이어지는 곳 305 > 앞판 295.5). 서랍 안(safe_z 300)·물체를 든 채면 테두리 여유가 작아 멈췄다 감
        blend = tr.get("blend_mm", 0.0) if cur[2] < lift_z and not self._over_drawer(cur) and not self.held else 0.0
        if blend and pose_name == "drawer_top_view":       # 탑뷰: 올리는 끝 50 mm 부터 회전 시작 → 올라가기·회전이 같이 끝남 [사용자 10/08].
            # 홈(z 196) → z 275 에서 관절 이동 시작해도 손잡이(y −66) 위 약 59 mm·앞판(y −87) 위 약 49 mm [계산 m0609_kin]
            blend = min(max(blend, tr.get("view_lift_blend_mm", blend)), 0.45 * (lift_z - cur[2]))
        up = mp.with_z(cur, lift_z)
        if cur[2] < lift_z:                                 # 올리다 끝 blend_mm 안에서 관절 이동을 바로 보냄 — 멈추지 않고 한 동작 [사용자 10/07]
            bad = self._line(goal, up, self._free_vel(cur), "lift", radius=blend)
            if bad:
                return bad
        goal.publish_feedback(Skill.Feedback(stage=f"to_{pose_name}"))
        vel, acc = self.joint_vel, self.joint_acc
        if pose_name in ("drawer_top_view", "drawer_approach") or (pose_name == "home" and not self.held and not getattr(self, "hold_unknown", None)):
            # 탑뷰·바텀뷰(J6 약 200° 회전)·손잡이 앞 → 이 이동만 따로 빠르게 [사용자 10/08]. 빈손 홈도 같은 속도
            # [사용자 10/12 "서랍 닫고 홈 가는 게 느림, ready 갈 때랑 같게"] — 쥔 채·쥐었는지 모름(hold_unknown, #223)이면 서버 관절 속도 그대로 (#235 A·PM)
            sp = self.prm()["speed"]
            vel, acc = sp.get("view_joint_deg_s", vel), sp.get("view_joint_acc_deg_s2", acc)
        ok = self.robot.movej_async(joints, vel, acc)
        if ok is False and (blend or moving):               # 올라가는 중이라 거부 → 다 올라간 뒤 다시 (멈췄다 감)
            bad = self._wait_pose(goal, up, self._free_vel(cur), "lift") if blend else self._settle(goal)
            if bad:
                return bad
            ok = self.robot.movej_async(joints, vel, acc)
        bad = sf.after_command(ok, what="movej", stop=self.robot.stop, get_state=self.state)
        if bad:
            return bad
        done = sf.wait_motion(get_state=self.state, cancel_requested=lambda: goal.is_cancel_requested,
                              stop=self.robot.stop, timeout_s=self.move_timeout, arrived=self._at_joints(joints),
                              watch=self._joint_watch())
        if not done.success:
            return done
        bad = self._settle(goal)
        if bad:
            return bad
        reached = sf.check_reached(joints, self.robot.posj(), self.reach_tol)
        if reached.success and pose_name == "home":
            self.home_posx = self.robot.posx()             # 놓기 때 서랍 → 홈 위로 높게 돌아오는 데 씀
        return reached

    def _free_vel(self, cur=None):
        """빈 공간 직선 속도 (서랍 밖으로 빼기·들고 나오기·트레이 위 올리기 등). cur 를 주면 서랍 위에서는 line_mm_s 로 —
        누르기·끌기·집기/놓기 마지막·손잡이 접근은 각자 속도 그대로 [사용자 10/07 저녁 "이동은 빠르게, 넛지·주요 기능은 조심"]."""
        sp = self.prm()["speed"]
        if cur is not None and self._over_drawer(cur):
            return self._in_vel()
        return sp.get("free_mm_s", sp["line_mm_s"])

    def _in_vel(self):
        """서랍 안·위 직선 속도 (경유점 → 물체 위, 집으러 내려가기, 서랍 안에서 올리기) — 큰 이동보다 느리게
        [사용자 10/07 밤 "탑뷰·옮기기·문 열고 닫기는 크게 빠르게, 서랍 안 움직임은 속도 낮춰"]."""
        sp = self.prm()["speed"]
        return sp.get("in_drawer_mm_s", sp["line_mm_s"])

    def _exit_drawer(self, goal, cur):
        """서랍 위 → 앞판·손잡이 위 높이(high_z, 지금이 더 높으면 그대로)로 올린 뒤 서랍 밖(base y = exit_y)까지 수평으로 뺀다."""
        tr, vel = self.prm()["transit"], self._free_vel()
        z = max(cur[2], tr["high_z_mm"])
        if cur[2] < z - 0.5:
            bad = self._line(goal, mp.with_z(cur, z), vel, "exit_lift", radius=tr.get("blend_mm", 0.0))
            if bad:
                return bad
        out = list(cur[:1]) + [tr["exit_y_mm"], z] + list(cur[3:])
        return self._line(goal, out, vel, "exit_drawer")

    def _over_tray(self, cur, margin_m=0.06):
        """TCP 가 전달 트레이(handover_zone) 바닥 위·둘레 margin 안에 있는지 (높이 상관없음)."""
        pl = self.places().get("handover_zone") or {}
        tf, size = pl.get("tf") or {}, pl.get("interior_m")
        if not tf.get("translation_m") or not size:
            return False
        p = mp.from_base(tf, [v / 1000.0 for v in cur[:3]])
        return -margin_m <= p[0] <= size[0] + margin_m and -margin_m <= p[1] <= size[1] + margin_m

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
        # 홈에서 수직으로 high_z 까지 올린 뒤 들어감 — 낮게 가면 열린 손잡이에 걸림 [실측 10/06]. 올리기는 _named 가 (끝에서 이어서)
        o = self._named(goal, "drawer_top_view", drawer_id)
        return None if o.success else o

    def _lower_touch(self, goal, target, vel, stage):
        """놓기 마지막: 천천히 내리다 바닥(받침)에 닿으면(z 힘이 place.touch_n 넘게 변함) 그 자리에서 멈춤 — 계산한 높이보다
        place.touch_overtravel_mm 까지 더 내려감, 그래도 안 닿으면 거기서 멈춤 [사용자 10/10 "2 mm 위에서 떨구는 느낌, 바닥에 얌전히"].
        잡은 높이가 실제와 조금 달라도(서랍 바닥 tf 오차·비스듬히 잡힘) 바닥에 붙여 놓음. touch_n 0 이면 예전처럼 계산 높이까지."""
        pl = self.prm()["place"]
        n = float(pl.get("touch_n") or 0.0)
        if n <= 0:
            return self._line(goal, target, vel, stage)
        base = self._tare(pl.get("touch_settle_s"))

        def touched():
            f = self.robot.tool_force()
            if f is None or base is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="힘 조회 실패")
            if abs(f[2] - base[2]) >= n:
                return sf.Outcome(True, reason=f"바닥 닿음 {abs(f[2] - base[2]):.1f} N")
            return None
        deeper = mp.with_z(target, target[2] - float(pl.get("touch_overtravel_mm", 0.0)))
        return self._line(goal, deeper, vel, stage, watch=touched)

    def _tare(self, settle_s=None):
        """멈춘 뒤 잠깐 기다렸다가 여러 번 읽은 평균 = 힘 기준값. 두산 툴 힘은 관절 토크 추정이라 멈춘 직후 흔들림 (10/06)."""
        sp = self.prm()["force"]
        time.sleep(sp["tare_settle_s"] if settle_s is None else settle_s)
        fs = [f for f in (self.robot.tool_force() for _ in range(int(sp["tare_samples"]))) if f is not None]
        return [sum(f[i] for f in fs) / len(fs) for i in range(6)] if fs else None

    def _travel_z(self, drawer_id, cur_z):
        """서랍 안 옆 이동 높이 = 서랍 바닥 + 안쪽 높이(테두리) + transit.in_drawer_clear_mm, 지금이 더 높으면 그대로.
        서랍 안 물건은 테두리보다 낮음 → 쌓여 있어도(망치·캐러멜·지우개 약 55 mm) 옆으로 지날 때 안 닿음 [사용자 10/08]."""
        place = self.places().get(drawer_id) or {}
        tf, inner = place.get("tf") or {}, place.get("interior_m")
        clear = self.prm()["transit"].get("in_drawer_clear_mm")
        if not tf.get("translation_m") or not inner or clear is None:
            return cur_z
        return max(cur_z, 1000.0 * (tf["translation_m"][2] + inner[2]) + float(clear))

    def _over_then_down(self, goal, drawer_id, cur, above, stage, turn_down=False):
        """서랍 안: (낮으면 수직으로 travel_z 까지) → travel_z 높이로 목표 바로 위까지 수평 → 목표 위(above)로 수직.
        경유점 높이로 옆으로 가다 비스듬히 내려가면 쌓인 물건에 닿음 [사용자 10/08]. 블렌딩 한 번 (모서리 반지름 blend_mm).
        turn_down: 손목 방향은 내려가는 구간에서만 바꿈 — 옆으로 가는 구간이 짧은데 많이 돌면 제어기가 블렌딩을 받고도 출발 안 함
        [실측 PC2 10/10 집기: 16 mm 옆 + 49° 회전 → NOT_REACHED 두 번]."""
        tz = max(self._travel_z(drawer_id, cur[2]), above[2])     # 쌓인 물체 위(above)가 이동 높이보다 높으면 그 높이로 옆 이동
        pts = []
        if tz - cur[2] > 1.0:
            pts.append(mp.with_z(cur, tz))
        over = [above[0], above[1], tz] + list(cur[3:] if turn_down else above[3:])
        if math.dist((pts[-1] if pts else cur)[:3], over[:3]) > 1.0:
            pts.append(over)
        if not pts or math.dist(pts[-1][:3], above[:3]) > 1.0:
            pts.append(list(above))
        else:
            pts[-1] = list(above)
        if len(pts) == 1:
            return self._line(goal, above, self._in_vel(), stage)
        r = self.prm()["transit"].get("blend_mm", 0.0)
        return self._blend(goal, pts, [r] * (len(pts) - 1) + [0.0], self._in_vel(), stage)

    def _clear_to_continue(self, goal):
        """노드 안에서 다음 명령(그리퍼 포함)을 보내기 직전: 취소 → CANCELED, 안전·비상정지 → ESTOP, 상태 조회 실패 → STATE_UNKNOWN.
        아무 명령도 보내지 않고 돌려줌 (정지 명령도 안 보냄 — 이미 멈춘 상태). 문제없으면 None (#181 E 재리뷰 P1)."""
        early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)
        if early:
            return early
        st = self.robot.state()
        if st is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="다음 명령 전 로봇 상태 조회 실패 — 보내지 않음")
        if sf.stopped_by_estop(st):
            return sf.Outcome(False, sf.ESTOP, reason=f"다음 명령 전 로봇 상태 {st} (안전·비상정지) — 보내지 않음")
        return None

    def _movej(self, goal, joints, stage, in_drawer=False):
        """관절 이동 1번 (제한 확인 → 자동 모드 → 비동기 → 도착). 성공이면 Outcome(True).
        in_drawer: 서랍 안으로 들어가는 경유점(drag_down) — speed.in_drawer_joint_* (서버 관절 속도와 따로, 탑뷰와 같게)."""
        err = self._joint_bad(joints, f"{stage} 목표")
        if err:
            return err
        goal.publish_feedback(Skill.Feedback(stage=stage))
        if not self.robot.auto():
            return sf.after_command(False, what="자동 모드 전환", stop=self.robot.stop, get_state=self.state)
        early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)
        if early:
            return early
        vel, acc = self.joint_vel, self.joint_acc
        if in_drawer:                                       # 탑뷰 → 경유점: 거의 손목(J6 약 170°)만 돌아감 → 탑뷰처럼 따로 빠르게 [사용자 10/10 "넛지하러 갈 때 돌리는 게 느림"]
            sp = self.prm()["speed"]
            vel = sp.get("in_drawer_joint_deg_s", vel)
            acc = sp.get("in_drawer_joint_acc_deg_s2", acc)
        bad = sf.after_command(self.robot.movej_async(joints, vel, acc), what=f"movej({stage})",
                               stop=self.robot.stop, get_state=self.state)
        if bad:
            return bad
        done = sf.wait_motion(get_state=self.state, cancel_requested=lambda: goal.is_cancel_requested,
                              stop=self.robot.stop, timeout_s=self.move_timeout, arrived=self._at_joints(joints),
                              watch=self._joint_watch())
        if not done.success:
            return done
        bad = self._settle(goal)
        if bad:
            return bad
        return sf.check_reached(joints, self.robot.posj(), self.reach_tol)

    def _settle(self, goal=None, timeout_s=2.0):
        """관절 이동 '도착'(관절 오차 reach_tol 안)은 감속이 끝나기 전일 수 있음 → 다음 직선·블렌딩 명령 전에 이동 중이 아닐 때까지
        기다림. 멈추면 None. [실측 10/07 밤 PC2, 관절 90°/s: drag_down 도착 직후 보낸 moveb 가 실행되지 않고 1 s 뒤 NOT_REACHED, 남은 204 mm]
        실패는 정지 + 정지 확인 뒤 돌려줌 — 이동 중에 다음 명령을 보내지 않음 [#139 PM·E 리뷰]:
        비상정지 = ESTOP, 취소 = CANCELED, 상태 조회 1 s 넘게 실패 = STATE_UNKNOWN, timeout_s 안에 안 멈춤 = NOT_REACHED."""
        def halt(o):
            return sf._halt(self.robot.stop, self.state, time.monotonic, time.sleep, 0.05, 3.0, o)

        t0, unknown_since = time.monotonic(), None
        while True:
            now = time.monotonic()
            if goal is not None and goal.is_cancel_requested:
                return halt(sf.Outcome(False, sf.CANCELED, canceled=True, reason="취소 요청으로 정지 (관절 이동 뒤 멈춤 확인 중)"))
            st = self.state()
            if sf.stopped_by_estop(st):
                return sf.Outcome(False, sf.ESTOP, reason=f"로봇 상태 {st} (안전·비상정지)")
            if st is None:
                unknown_since = unknown_since or now
                if now - unknown_since > 1.0:
                    return halt(sf.Outcome(False, sf.STATE_UNKNOWN, reason="관절 이동 뒤 상태 조회 실패 1 s 넘음 — 정지"))
            elif st != sf.STATE_MOVING:
                return None
            else:
                unknown_since = None
            if now - t0 >= timeout_s:
                self.get_logger().warn(f"관절 이동 뒤 {timeout_s:g} s 안에 멈추지 않음 — 정지")
                return halt(sf.Outcome(False, sf.NOT_REACHED, reason=f"관절 이동 뒤 {timeout_s:g} s 안에 멈추지 않아 정지"))
            time.sleep(0.05)

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

    def _line(self, goal, posx, vel, stage, watch=None, tol_mm=1.0, tol_deg=1.0, radius=0.0, resend=True):
        """직선 이동 1회 (자동 모드 → 취소 확인 → 비동기 명령 → 끝날 때까지, 좌표로 판단 _wait_pose). 성공이면 None, 아니면 Outcome.
        resend: 출발하지 않은 명령을 한 번 다시 (_send_wait). 접촉 감시(watch)·아주 느린 직선(_line_slow)은 다시 보내지 않음."""
        goal.publish_feedback(Skill.Feedback(stage=stage))
        if not self.robot.auto():
            return sf.after_command(False, what="자동 모드 전환", stop=self.robot.stop, get_state=self.state)
        early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)
        if early:
            return early
        sp = self.prm()["speed"]                          # 부드럽게: 가속 = 속도(1 s에 최고 속도), 회전 따로 (10/06 기울일 때 쿵쿵)
        kw = {"radius": radius} if radius > 0 else {}
        start = self.robot.posx() if resend and watch is None else None

        def send():
            early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)
            if early:
                return early
            return sf.after_command(self.robot.movel_async(posx, vel, sp["line_acc_ratio"] * vel, sp["turn_deg_s"],
                                                           sp["turn_acc_deg_s2"], **kw), what=f"movel({stage})",
                                    stop=self.robot.stop, get_state=self.state)

        def wait():
            if radius > 0:                                  # 이어서 갈 이동: 끝 radius 안에 들어오면 바로 돌려줌 (멈추지 않음) [사용자 10/07]
                return self._wait_pose(goal, posx, vel, stage, watch, tol_mm=radius, tol_deg=180.0, settle_s=0.0)
            return self._wait_pose(goal, posx, vel, stage, watch, tol_mm, tol_deg)
        return self._send_wait(goal, send, wait, start, posx, stage)

    def _send_wait(self, goal, send, wait, start, end, stage):
        """보내고 끝까지. 받기만 하고 출발하지 않으면(start 에서 1 mm·0.5° 안에 선 NOT_REACHED, 목표는 2 mm 넘게 떨어짐)
        멈춘 걸 확인하고 한 번만 다시 — 앞 이동이 끝날 무렵 보낸 명령이 실행되지 않음
        [실측 10/07 밤 PC2 drag_down 뒤 moveb, 10/08 아침 놓기 트레이 위 도착 뒤 lower_fast 남은 73.6 mm]. start None = 다시 보내지 않음.
        방향도 본다: 위치는 그대로인데 돌기만 하다 선 이동은 출발한 것 — 다시 보내지 않음 [#156 E 리뷰 P2].
        방향은 회전 행렬로 비교해 같은 자세의 다른 표기(B 180° 에서 A·C 가 함께 바뀜)는 같은 방향으로 봄."""
        bad = send() or wait()
        if bad is None or bad.error_code != sf.NOT_REACHED or start is None:
            return bad
        now = self.robot.posx()
        if (now is None or math.dist(now[:3], start[:3]) >= 1.0
                or pm.rotation_angle(pm.rot(*now[3:6]), pm.rot(*start[3:6])) >= 0.5
                or math.dist(start[:3], [float(v) for v in end[:3]]) < 2.0):
            return bad
        self.get_logger().warn(f"[{stage}] 이동이 출발하지 않음 — 한 번 다시 보냄 ({bad.reason})")
        return self._settle(goal) or send() or wait()

    def _wait_pose(self, goal, posx, vel, stage, watch=None, tol_mm=1.0, tol_deg=1.0, settle_s=0.1, still_s=1.0,
                   still_mm=0.05, still_deg=0.05):
        """직선·블렌딩 이동이 끝날 때까지 — 좌표(위치·방향)로만 판단 (10/07 실물).
        관절 변화로 '이동 중'을 보면 천천히 출발하는 동안(가속 = 속도, 1 mm/s 누르기·10 mm/s 끌기) 멈춤으로 잘못 봐
        누르기는 정지 명령 없이 끝나고(감시 없이 계속 내려감), 끌기는 0.3 mm 에서 섰음.
        - 목표 tol_mm·tol_deg 안 + settle_s 동안 그대로 = 도착 (None). settle_s 0 = 안에 들어오기만 하면 (이어서 갈 이동)
        - '그대로' = 0.05 s 간격 읽기 사이 0.05 mm·0.05° 안 (10/07: 0.01 이면 멈춰도 읽기 값 흔들림으로 도착이 늦어짐 [추정])
        - watch 가 Outcome = 정지·확인 후 그 결과 (성공 결과면 None — 접촉 감지)
        - 위치·방향이 still_s 동안 그대로인데 목표 밖 = 정지·확인 후 NOT_REACHED
        - 비상정지 = ESTOP, 취소·좌표 조회 1 s 넘게 끊김·시간 초과 = 정지 확인 후 해당 코드"""
        def halt(o):                                        # 정지 + 정지 확인 (_halt). 성공 결과(접촉 감지)면 None
            done = sf._halt(self.robot.stop, self.state, time.monotonic, time.sleep, 0.05, 3.0, o)
            return None if done.success else self._where(done, stage, posx)

        goal_mm, goal_rot = [float(v) for v in posx[:3]], pm.rot(*[float(v) for v in posx[3:6]])
        cur = self.robot.posx()
        dist = math.dist(cur[:3], goal_mm) if cur else 0.0
        limit = max(self.move_timeout, 2.0 * dist / max(vel, 1e-6) + 5.0)
        watch = self._joint_watch(watch)
        t0 = time.monotonic()
        last, still_since, unknown_since = None, None, None
        while True:
            now = time.monotonic()
            st = self.robot.state()
            if sf.stopped_by_estop(st):
                return sf.Outcome(False, sf.ESTOP, reason=f"로봇 상태 {st} (안전·비상정지)")
            if goal.is_cancel_requested:
                return halt(sf.Outcome(False, sf.CANCELED, canceled=True, reason="취소 요청으로 정지"))
            hit = watch()
            if hit is not None:
                return halt(hit)
            p = self.robot.posx()
            if p is None:
                unknown_since = unknown_since or now
                if now - unknown_since > 1.0:
                    return halt(sf.Outcome(False, sf.STATE_UNKNOWN, reason="좌표 조회 실패 1 s 넘음 — 정지"))
            else:
                unknown_since = None
                r = pm.rot(*p[3:6])
                if last is not None and (math.dist(p[:3], last[:3]) < still_mm
                                         and pm.rotation_angle(r, pm.rot(*last[3:6])) < still_deg):
                    still_since = still_since or now
                else:
                    still_since, last = None, p
                there = math.dist(p[:3], goal_mm) <= tol_mm and pm.rotation_angle(r, goal_rot) <= tol_deg
                if there and (settle_s <= 0 or (still_since is not None and now - still_since >= settle_s)):
                    return None
                if not there and still_since is not None and now - still_since > still_s:
                    return halt(sf.Outcome(False, sf.NOT_REACHED, reason=f"위치·방향이 {still_s:g} s 동안 그대로 — 목표 전에 멈춤"))
            if now - t0 > limit:
                return halt(sf.Outcome(False, sf.MOTION_TIMEOUT, reason=f"{limit:.0f} s 안에 끝나지 않아 정지"))
            time.sleep(0.05)

    def _line_slow(self, goal, posx, vel, stage, watch=None):
        """아주 느린 직선 (누르기 1 mm/s, 힘 맞추기 0.1 mm) — 도착 판정 0.05 mm."""
        return self._line(goal, posx, vel, stage, watch, tol_mm=0.05, tol_deg=0.5, resend=False)

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

    def _blend(self, goal, points, radii, vel, stage):
        """posx 경유점들을 직선 블렌딩으로 한 번에 (자동 모드 → 취소 확인 → 비동기 → 마지막 점 도착까지). 성공이면 None."""
        goal.publish_feedback(Skill.Feedback(stage=stage))
        if not self.robot.auto():
            return sf.after_command(False, what="자동 모드 전환", stop=self.robot.stop, get_state=self.state)
        early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)
        if early:
            return early
        sp = self.prm()["speed"]
        start = self.robot.posx()
        if start is not None:                               # 반지름이 구간 절반에 딱 맞으면 제어기가 반올림으로 거부 → 여유 (모든 블렌딩 공통) [실측 PC2 10/08]
            radii = mp.safe_blend_radii(start, points, radii)

        def send():
            early = sf.canceled_before_motion(lambda: goal.is_cancel_requested)   # 보낼 때마다 확인 (재전송 전 취소) [#139 E 리뷰 P1]
            if early:
                return early
            return sf.after_command(self.robot.moveb_async(points, radii, vel, sp["line_acc_ratio"] * vel, sp["turn_deg_s"],
                                                           sp["turn_acc_deg_s2"]), what=f"moveb({stage})",
                                    stop=self.robot.stop, get_state=self.state)
        bad = self._send_wait(goal, send, lambda: self._wait_pose(goal, points[-1], vel, stage), start, points[-1], stage)
        if bad is None or bad.error_code != sf.NOT_REACHED or start is None:
            return bad
        now = self.robot.posx()
        if (now is None or math.dist(now[:3], start[:3]) >= 1.0
                or pm.rotation_angle(pm.rot(*now[3:6]), pm.rot(*start[3:6])) >= 0.5):
            return bad                                      # 출발은 했다가 선 것 — 그대로 실패
        # 다시 보내도 출발 안 함 = 제어기가 이 블렌딩을 못 받음(짧은 구간에서 손목 크게 돌림 등) [실측 PC2 10/10 "방향 1 s" 반복]
        # → 멈추지 말고 점마다 직선으로 (끊기지만 끝까지 감)
        self.get_logger().warn(f"[{stage}] 블렌딩이 출발 안 함 — 점마다 직선으로 ({bad.reason})")
        for k, p in enumerate(points):
            bad = self._settle(goal) or self._line(goal, p, vel, f"{stage}:{k + 1}")
            if bad:
                return bad
        return None

    def _carry_route(self, drawer_id):
        """poses.yaml carry_line 경유점 posx (집은 뒤 → 트레이 직선 블렌딩). 없으면 None."""
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
        if (err := self._refuse_if_hold_unknown()):
            return err, None
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
        if state == "open" and self.held:                    # 손잡이를 잡으려면 그리퍼를 벌림 → 쥔 물체가 떨어짐 (트레이에서 집은 뒤 열기 등) — 움직이기 전
            return sf.Outcome(False, HOLDING_OBJECT, reason=f"{self.held['class']} 를 든 채 열지 않음 — 먼저 놓기"), None
        if state == "open":
            return self._open_drawer(goal, drawer_id, place, oc, dc, closed, pull, disp, params)
        if state == "close":                                # then_home: 닫고 빼면서 홈까지 한 동작 (B 명령 전용, Runner 는 안 씀) [사용자 10/10]
            return self._close_drawer(goal, drawer_id, oc, dc, pull, then_home=params.get("then_home") is True)
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
        # 시작 자세 = 손잡이 앞(ready, drawer_approach) — Runner open_drawer 가 move_to_named_pose(drawer_approach) 를 먼저 보냄.
        # 노드 안에서 ready 로 알아서 가지 않음(숨은 이동 없음, #168 사용자 10/08). 아니면 그리퍼도 움직이기 전에 거부.
        if self.robot.posx() is None:                                # 좌표를 모르면 그리퍼 전에 실패 (#83 E 검토 P1)
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 시작 자세 확인 못 함"), None
        if not sf.check_reached(joints, self.robot.posj(), self.reach_tol).success:
            return sf.Outcome(False, NOT_AT_START_POSE,
                              reason="손잡이 앞(drawer_approach)에서 시작 — 먼저 move_to_named_pose(drawer_approach)"), None
        self._grip(oc["handle_open_width_mm"], 20)
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

        # 손잡이까지 한 번에 (1 cm 전에서 멈추지 않음) [사용자 10/07]. 가속 = 속도라 끝 1 cm 는 약 55 mm/s 로 줄며 도착 [계산], 접촉 감시 그대로
        bad = self._line(goal, handle, speed["line_mm_s"], "reach_handle", watch=touched)
        if bad:
            if sf.is_safety(bad):
                return bad, None
            now = self.robot.posx()                          # 접촉으로 멈춤 → 그대로 뒤로 빼고 실패
            back = self._line(goal, mp.offset_posx(now, pull, oc["retreat_mm"]), speed["line_mm_s"], "retreat") \
                if now else sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패")
            return sf.worse(bad, back), None
        st = self._grip(0, oc["handle_grip_force_n"])
        if st.width_mm / 1000.0 <= oc["handle_min_width_m"]:     # 못 잡음 → 그리퍼 열고 접근 실패와 같은 자리(60 mm 뒤)로 빼고 멈춤 [사용자 10/08]
            self._grip(oc["handle_open_width_mm"], 20)
            failed = sf.Outcome(False, GRASP_FAILED, reason=f"손잡이를 못 잡음 (폭 {st.width_mm:.1f} mm)")
            now = self.robot.posx()
            back = self._line(goal, mp.offset_posx(now, pull, oc["retreat_mm"]), speed["line_mm_s"], "retreat") \
                if now else sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패")
            return sf.worse(failed, back), None
        start = self.robot.posx()
        base_f = self._tare()
        target = mp.offset_posx(handle, pull, distance * 1000.0)
        verdict = {}
        stuck_n = (dc.get("stuck_force_by_drawer_n") or {}).get(drawer_id, dc["stuck_force_n"])   # 아래 칸은 결착이 커서 따로 [실측 10/11]

        def watch():
            now, f = self.robot.posx(), self.robot.tool_force()
            if now is None or f is None or base_f is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="좌표·힘 조회 실패")
            moved = mp.travel_mm(start, now, pull) / 1000.0
            resist = abs(sum((f[i] - base_f[i]) * pull[i] for i in range(3)))
            v = dp.judge_opening(moved, distance, resist, stuck_n, dc["pos_tol_m"])
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
                return bad, {"drawer_displacement": round(disp + moved, 4), "close_confirmed": False,
                             "open_distance_m": round(distance, 4)}
        self.disp[drawer_id] = disp + moved
        self._grip(oc["handle_open_width_mm"], 20)
        now = self.robot.posx()
        bad = self._line(goal, mp.offset_posx(now, pull, oc["retreat_mm"]), speed["line_mm_s"], "retreat")
        if bad:
            return bad, None
        home = self._named(goal, "home")                   # 손잡이 쪽(ready) 관절 자세를 풀어 둠 — 다음 동작은 홈에서 시작
        if not home.success:
            return home, {"drawer_displacement": round(self.disp[drawer_id], 4), "close_confirmed": False,
                          "open_distance_m": round(distance, 4)}
        # open_distance_m = 이번에 명령한 인출 거리 — open_drawer verify(drawer_displacement ≥ 0.9 × distance) 근거 [P2 4절].
        # drawer_displacement 는 손잡이를 쥔 TCP 가 당긴 거리로 추정(서랍 거리 센서 없음)
        out = {"drawer_displacement": round(self.disp[drawer_id], 4), "close_confirmed": False, "open_distance_m": round(distance, 4)}
        return sf.Outcome(True, reason=f"열림 {self.disp[drawer_id] * 1000:.1f} mm"), out

    def _close_drawer(self, goal, drawer_id, oc, dc, pull, then_home=False):
        """닫기: 손잡이를 잡지 않고 45° 자세(교시 params `close_push.<서랍>`)로 앞판을 밀어 닫는다 [사용자 10/08~].
        (예전 홈 자세 수직 손끝 밀기는 두 칸 모두 close_push 교시 뒤 안 써서 10/12 코드 정리로 뺌)"""
        if not oc.get("close_enabled", False):
            return sf.Outcome(False, sf.NOT_IMPLEMENTED, reason="닫기 꺼짐 — 사람이 손으로 닫기 "
                                                                "(params drawer_open_close.close_enabled)"), None
        if self.held:
            return sf.Outcome(False, HOLDING_OBJECT, reason=f"{self.held['class']} 를 든 채 닫지 않음"), None
        tilted = (oc.get("close_push") or {}).get(drawer_id)
        if not tilted:
            return sf.Outcome(False, DRAWER_NOT_CONFIGURED, reason=f"{drawer_id} 닫기 자세(close_push) 교시 전"), None
        return self._close_drawer_tilted(goal, drawer_id, oc, dc, pull, tilted, then_home)

    def _push_closed(self, goal, drawer_id, oc, dc, pull, pre, contact_closed, then_home=False):
        """pre(밀기 시작, 이미 도착)에서 닫히는 방향으로 contact_closed(닫혔을 때 TCP)보다 close_overtravel 만큼 더 밂.
        빠르게 → 마지막 push_slow_last_mm 천천히, 일찍 크게 걸리면 멈춤, 끝나면 여는 방향으로 retreat_mm 빼기 (홈은 안 감)."""
        speed = self.prm()["speed"]
        push = [-c for c in pull]
        base_f = self._force_quick()                       # 밀기 감시(15 N) 기준 — 0.7 s 기다리지 않고 바로 (도착 직후 흔들림 몇 N, 판정엔 충분 [추정]) [사용자 10/07]

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
        # close_confirmed 근거 [P2 4절]: 밀기 끝 TCP 기준 닫힘 위치까지 남은 거리 ≤ 허용오차, 밀기가 중간에 멈추지 않음
        out = {"drawer_displacement": round(self.disp[drawer_id], 4), "close_confirmed": confirmed,
               "close_remaining_m": round(rem, 4) if math.isfinite(rem) else None, "close_pos_tol_m": oc["close_pos_tol_m"],
               "close_push_interrupted": bad is not None}   # 밀기가 힘 감시·이동 실패로 끝 전에 멈춤
        if sf.is_safety(bad):                               # 안전 정지·취소 뒤엔 후퇴하지 않음
            return bad, out
        if bad and not confirmed:
            res = bad
        elif not confirmed:
            res = sf.Outcome(False, dp.CLOSE_NOT_CONFIRMED, reason=f"닫힘 위치에 못 감 (남은 {rem * 1000:.1f} mm)")
        else:
            res = None
        # then_home: 지금 가던 길(빼기 → high_z 로 올리기 → exit_y 로 빼기 → 홈) 그대로, 모서리만 home_blend_mm 반지름으로 이어 한 번에
        # (moveb) [사용자 10/10 "세 동작을 하나로, 뚝뚝 끊기는 게 싫음"]. 위·아래 칸 모두 관절 연속, J5 최대 113.5°, 홈 관절로 끝남 [계산 m0609_kin].
        # 홈 TCP 는 이번 서버에서 홈에 도착했을 때 읽은 값(home_posx). 없으면 빼기 끝에서 이어서 _named 홈.
        r = float(oc.get("home_blend_mm", 10.0)) if then_home and res is None else 0.0
        home_x = getattr(self, "home_posx", None) if r else None
        retreat = mp.offset_posx(now, pull, oc["retreat_mm"]) if now else None
        if retreat is None:
            back = sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 후퇴 못 함")
        elif home_x:
            tr = self.prm()["transit"]
            z = max(retreat[2], tr["high_z_mm"])
            pts = [retreat] + ([mp.with_z(retreat, z)] if retreat[2] < z - 0.5 else []) \
                + [[retreat[0], tr["exit_y_mm"], z] + list(retreat[3:]), list(home_x)]
            first = min(r, float(oc.get("home_blend_first_mm", r)))   # 빼기 끝 모서리는 작게 — 위 칸 손잡이·앞판에서 먼저 떨어진 뒤 올라가게
            back = self._blend(goal, pts, [first] + [r] * (len(pts) - 2) + [0.0], speed["line_mm_s"], "retreat_home")
        else:
            back = self._line(goal, retreat, speed["line_mm_s"], "retreat", radius=r)
        res = sf.worse(res, back)
        if res:
            return res, out
        self.disp[drawer_id] = 0.0
        out["drawer_displacement"] = 0.0
        if r:
            joints, _ = sf.pose_joints(self.poses(), "home")
            if not (home_x and joints and sf.check_reached(joints, self.robot.posj(), self.reach_tol).success):
                o = self._named(goal, "home", moving=not home_x)    # 홈 TCP 에 왔는데 관절이 조금 다르면 관절 이동으로 마무리
                if not o.success:
                    return o, out
        return sf.Outcome(True, reason=f"닫힘 위치 도달 (남은 {rem * 1000:.1f} mm)" + (" → 홈" if r else "")), out

    def _close_drawer_tilted(self, goal, drawer_id, oc, dc, pull, cp, then_home=False):
        """닫기 (위·아래 공통) — 수직에서 로봇 쪽으로 기울인(45°, 20° 는 손잡이에 닿음) 손끝으로 앞판 중앙을 닫히는 방향(y)으로 밂 [사용자 10/08].
        교시(params close_push.<서랍>): start_posj·start_posx = 서랍 끝까지 연 상태 앞판 3 cm 앞, end_posx = 닫힌 상태 앞판에 손끝이 닿는 자리
        (같은 손목·높이). 서랍 위(탑뷰 등)면 먼저 홈 — 열린 앞판을 치지 않게 (#133). 그리퍼는 닫은 채 밂."""
        tol = oc.get("close_push_xz_tol_mm", 5.0)
        start_x, end = cp.get("start_posx"), cp.get("end_posx")
        if not start_x or not end:
            return sf.Outcome(False, DRAWER_NOT_CONFIGURED, reason=f"{drawer_id} close_push 의 start_posx·end_posx 교시 전"), None
        start_x, end = [float(v) for v in start_x], [float(v) for v in end]
        # 미는 동안 손목·x·z 는 시작 자세 그대로, 닫힘 판정은 끝 자세의 y 만 — 시작·끝을 따로 교시하면 C 가 180° 다르게 찍힐 수 있음
        # (그리퍼 축 반 바퀴, 미는 데는 같음) [실측 B 10/08 위 칸 C +90 vs −90]. x·z 가 많이 다르면 잘못 잰 것 → 교시값끼리 비교해 움직이기 전 거부 (#181 C 리뷰)
        off = max(abs(start_x[k] - end[k]) for k in (0, 2))
        if off > tol:
            return sf.Outcome(False, DRAWER_NOT_CONFIGURED,
                              reason=f"닫기 시작·끝 자세의 x·z 차이 {off:.1f} mm — 같은 높이·x 로 다시 교시"), None
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), None
        if self._over_drawer(cur):
            o = self._named(goal, "home")
            if not o.success:
                return o, None
        early = self._clear_to_continue(goal)              # 홈 이동 뒤 취소·안전정지면 그리퍼도 움직이지 않음 (#181 E 리뷰)
        if early:
            return early, None
        self._grip(0, 20)
        o = self._movej(goal, cp["start_posj"], "to_close_start")
        if not o.success:
            return o, None
        pre = self.robot.posx()
        if pre is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), None
        off = max(abs(pre[k] - start_x[k]) for k in range(3))
        if off > tol:                                       # start_posj 와 start_posx 가 서로 다른 자리 (옮겨 적다 틀림) → 밀지 않음. 이미 움직였으므로 이동 뒤 코드
            return sf.Outcome(False, dp.CLOSE_NOT_CONFIRMED,
                              reason=f"닫기 시작 자세 도착 위치가 start_posx 와 {off:.1f} mm 다름 — 밀지 않고 멈춤, start_posj·start_posx 다시 교시"), None
        return self._push_closed(goal, drawer_id, oc, dc, pull, pre, [pre[0], end[1], pre[2]] + list(pre[3:6]), then_home)

    # --- 끌기 (nudge_object) ---
    def _press_relax(self, goal, above, end_mm, expect_z, d, speed):
        """누를 자리 위(above)에서 내려가 닿음 확인 → 끄는 힘으로 맞춤. (실패 Outcome 또는 None, 누른 posx, 그때 힘 N).
        안전 코드가 아닌 실패는 above 로 올라간 뒤 돌려줌 → 호출자가 같은 자리에서 다시 시도할 수 있음."""
        base_f = self._tare(d.get("tare_settle_s"))           # 넛지는 0.4 s [사용자 10/11 "넛지 너무 느림"], 없으면 force.tare_settle_s
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
            bad = self._line_slow(goal, end_mm + above[3:], d["press_speed_mm_s"], "press" if k == 0 else f"press:{k + 1}",
                                  watch=contact)
            if bad:
                return (bad if sf.is_safety(bad) else sf.worse(bad, self._line(goal, above, self._in_vel(), "lift"))), None, None
            if "z1" not in state:
                break                                       # 끝까지 내려가도 안 닿음
            reads = self._force_reads(int(d["press_confirm"]), d["confirm_gap_s"])
            if reads is None or base_f is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="힘 조회 실패"), None, None
            ns = [abs(f[2] - base_f[2]) for f in reads]
            if all(n >= d["touch_force_n"] for n in ns):    # 멈춘 채 연속 press_confirm 번 모두 넘음 = 지우개에 닿음 [사용자 10/07]
                state["z"] = state["z1"]
                break
            state["resumed"] = True                         # 튄 값 → 그 자리에서 다시 내려감 (출발 무시 구간 없이)
        if "z" not in state or abs(state["z"] - expect_z) > d["contact_z_tol_mm"]:
            back = self._line(goal, above, self._in_vel(), "lift")
            why = (f"접촉 높이 z {state['z']:.2f} 가 예상 {expect_z:.1f} ± {d['contact_z_tol_mm']:g} 밖 — 오검출로 보고 끌지 않음"
                   if "z" in state else "예상 높이보다 내려가도 접촉 없음 (또는 멈춘 뒤 확인에서 계속 튐) — 물체 위치·높이 확인")
            return sf.worse(sf.Outcome(False, NO_OBJECT_CONTACT, reason=why), back), None, None
        pressed = self.robot.posx()
        if pressed is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), None, None
        # 닿음은 큰 힘(touch_force_n)으로 확실히 확인 — 조금만 내려가도 힘이 튐 [사용자 10/07]. 확인·정지하는 동안 더 눌리므로
        # 멈춘 자리에서 relax_step_mm 씩 올리며 멈춘 뒤 힘을 재서 끄는 힘(drag_force_n, 2 N 에서 잘 끌림 [실측 10/06]) 상한 이하면 그 높이로 끈다
        bad, _, held_n = self._relax(goal, pressed, base_f, d)
        if bad:
            return (bad if sf.is_safety(bad) else sf.worse(bad, self._line(goal, above, self._in_vel(), "lift"))), None, None
        # 힘 맞추기의 목표는 명령 위치에 누적되고, 한 칸이 덜 움직였어도 넘어가므로(_relax_step) 끌기 시작은 실제 멈춘 자리로
        # — "누른 z 그대로 끌기"가 명령 좌표(+0.1 mm)로 바뀌지 않게 [#135 E 리뷰]
        pressed = self.robot.posx()
        if pressed is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 끌기 시작 위치 모름"), None, None
        return None, pressed, held_n

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
            self._held_f = f
            if n <= hi:
                if n < lo and k > 0:                        # 한 칸에 범위를 지나침 → 반 칸 내려가서 끔 (그 사이 힘)
                    p = mp.with_z(p, p[2] - d["relax_step_mm"] / 2.0)
                    bad = self._relax_step(goal, p, "relax:half_back")
                    if bad:
                        return bad, p, n
                return None, p, n
            if k == int(d["relax_max_steps"]):
                break
            p = mp.with_z(p, p[2] + d["relax_step_mm"])
            bad = self._relax_step(goal, p, f"relax:{k + 1}")
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

    def _grip_width(self):
        """지금 그리퍼 폭 mm (조회 실패면 0 — 그러면 벌리는 명령을 보냄)."""
        r = Rg2(self.rg2_ip)
        try:
            return float(r.status().width_mm)
        except Exception:
            return 0.0
        finally:
            r.close()

    def _force_quick(self):
        """기다리지 않고 0.03 s 간격 3번 평균 (조회 실패만이면 None)."""
        fs = self._force_reads(3, 0.03)
        return [sum(f[i] for f in fs) / len(fs) for i in range(6)] if fs else None

    def _force_still(self, settle_s):
        """멈춘 채 settle_s 기다린 뒤 여러 번 읽은 평균 (_tare 와 같은 방식). 모두 조회 실패면 None."""
        time.sleep(settle_s)
        fs = [f for f in (self.robot.tool_force() for _ in range(int(self.prm()["force"]["tare_samples"]))) if f is not None]
        return [sum(f[i] for f in fs) / len(fs) for i in range(6)] if fs else None

    def _relax_step(self, goal, posx, stage):
        """힘 맞추기 한 칸. 눌린 채 0.1 mm 는 제어기가 덜 움직여 0.05 mm 판정 전에 멈출 수 있음
        [실측 10/07 PC2: relax:2 남은 0.1 mm 로 NOT_REACHED → 끌기 실패] → 그 경우만 실패로 끝내지 않고 다음 칸으로
        (목표는 명령 위치에 누적되므로 다음 칸이 더 올림). 힘이 범위에 안 들어오면 relax_max_steps 뒤 PUSH_BLOCKED 그대로."""
        bad = self._step(goal, posx, stage)
        if bad and bad.error_code == sf.NOT_REACHED:
            self.get_logger().warn(f"[nudge_object] {bad.reason} — 힘 맞추기는 계속")
            return None
        return bad

    def _step(self, goal, posx, stage):
        """아주 짧은 직선 (힘 맞추기 0.1 mm) — 느린 이동이라 좌표로 판단 (_line_slow)."""
        return self._line_slow(goal, posx, self.prm()["drag"]["press_speed_mm_s"], stage)

    def _push_finger_blocker(self, plan, target, objs, nb):
        """뒤에서 밀기 시작 자리(닫은 손가락이 내려갈 곳)와 겹치는 이웃 id — 손가락 반두께 = 옆면까지(along_mm), 옆으로 = 닫은 손끝 바깥(fingertip_outer_mm)."""
        g = self.prm()["gripper"]
        return nc.finger_spot_blocker(center_m=plan.press_xy_m, push_dir=plan.push_dir, target_id=target.get("id"), objects=objs,
                                      size_of=self._size_or_none, default_size_m=self.prm()["place"]["default_obstacle_size_m"],
                                      half_along_mm=g["wall_clearance_mm"]["along_mm"], half_lat_mm=g["fingertip_outer_mm"],
                                      margin_mm=nb["margin_mm"])

    def _drag_g(self, drawer_id, cls):
        """끌기·벽 판단에 쓰는 그리퍼·서랍 값 (nudge_object 와 파지 공간 계획이 같은 값을 쓰게)."""
        prm = self.prm()
        return dict(prm["gripper"], wall_offset_mm=(prm.get("drawer_wall_offset_mm") or {}).get(drawer_id),
                    wall_tcp_min_mm=(prm["drag"].get("wall_tcp_min_by_drawer_mm") or {}).get(drawer_id),
                    reach_x_max_mm=(prm.get("drawer_reach_x_mm") or {}).get(drawer_id),
                    max_open_mm=prm["pick"]["max_open_width_m"] * 1000.0, tilt_align_deg=prm["pick"]["tilt_align_deg"],
                    axis_grasp=bool(prm["pick"].get("axis_grasp")), front_tilt_within_mm=prm["pick"].get("front_tilt_within_mm"),
                    round=cls in (prm["pick"].get("round_classes") or []) and bool(prm["pick"].get("round_wall")))

    def _size_cached(self):
        """계획용 size_of — 온톨로지를 한 번만 읽음 (모르는 class 는 place.default_obstacle_size_m)."""
        default, cache = self.prm()["place"]["default_obstacle_size_m"], {}

        def size_of(cls):
            if cls not in cache:
                cache[cls] = self._size_or_none(cls) or list(default)
            return cache[cls]
        return size_of

    def _do_nudge_object(self, goal, params):
        if (err := self._refuse_if_hold_unknown()):
            return err, None
        target, drawer_id = params.get("target") or {}, params.get("drawer_id")
        frame = (target.get("pose") or {}).get("frame")
        if frame != drawer_id:                              # 다른 칸 좌표로 이 칸을 끌지 않음 — 움직이기 전 거부 (#181 E 리뷰)
            return sf.Outcome(False, sf.BAD_PARAMS, reason=f"target.pose.frame {frame!r} ≠ drawer_id {drawer_id!r}"), None
        prm, place = self.prm(), self.places().get(drawer_id) or {}
        if not place.get("tf") or not place.get("interior_m"):
            return sf.Outcome(False, DRAWER_NOT_CONFIGURED, reason=f"{drawer_id} tf·interior_m 없음"), None
        err = motion_guard.precheck_nudge(target=target, displacement_m=self.disp.get(drawer_id),
                                          tf_at_travel_m=place.get("tf_at_travel_m"), params=prm["motion_guard"])
        if err:
            return sf.Outcome(False, err.error_code, reason=err.reason), None
        if params.get("make_room"):                         # 파지 공간 만들기 한 단계 [제안 10/11 B, 계약 승인 전]
            return self._make_room(goal, params, drawer_id, target)
        if params.get("topple"):                            # 쌓인 물체 무너뜨리기 [사용자 10/13, 제안]
            return self._topple(goal, params, drawer_id, target)
        size, _ = self.item(target.get("class"))
        g = self._drag_g(drawer_id, target.get("class"))
        plan = mp.plan_drag(target=target, size_m=size, interior_m=place["interior_m"], g=g, drag=prm["drag"])
        out = {"pushed": False, "push_vector_m": [0.0, 0.0], "clearance_before_m": round(plan.clearance_before_m, 4),
               "floor_z_m": 0.0, "target_after": None}         # 성공일 때만 채움 — 실패 결과의 좌표로 집지 않게 (#37 E)
        if params.get("check_only"):                          # 판단 결과 공개 [E #245 제안]: 넛지가 필요한지·넛지로도 안 되는 이유 (기존 error_code 그대로)
            out.update(needed=bool(plan.needed) and not plan.error_code, plan_code=plan.error_code or None)
        if plan.error_code:                                   # check_only 재판단이면 runner.md 대로 PUSH_LIMIT
            return sf.Outcome(False, PUSH_LIMIT if params.get("check_only") else plan.error_code, reason=plan.reason), out
        if not plan.needed:
            out["target_after"] = target                      # 움직이지 않음 → 위치 그대로
            return sf.Outcome(True, reason=plan.reason), out
        if params.get("check_only"):                          # 재판단인데 아직 끌어야 함 → 집지 않게 멈춤 (runner.md, #83 D 리뷰)
            return sf.Outcome(False, PUSH_LIMIT, reason=f"check_only: 아직 잡을 수 없는 자리 — {plan.reason}"), out
        # 다른 물체 위에 얹힌 물체도 높이 상관없이 넛지 [사용자 10/13 "높이상관없이 넛지로가자", #254 시뮬레이션: 구석 쌓임은 위에서 눌러
        # 끌기로 대부분 떨어뜨리거나 넘어뜨림 → 다시 보고 집기]. 받침 = 비전 top_z − 물체 높이 (맨 위 물체는 비전 윗면이 맞음, 10/11):
        # 누르는 높이·뒤에서 미는 손끝은 받침 위 기준, 밑에 깔린 받침은 이웃 확인에서 뺌. (10/12 까지는 NOT_ON_FLOOR 로 거부 — 손끝을
        # 바닥 위 3 mm 로 내려 받침 위로 떨어질 뻔함 [사용자 10/12 PC2 몽키 위 캐러멜])
        stacked = motion_guard.support_m(target, size[2], prm["motion_guard"]["on_floor_tolerance_m"])
        top_max = place["interior_m"][2] - prm["pick"]["stack_top_clear_m"]
        if stacked > 0 and stacked + size[2] > top_max:     # 테두리 가까이 높이 쌓임 — 서랍 안 옆 이동 높이와 닿음 (집기와 같은 상한)
            return sf.Outcome(False, motion_guard.NOT_ON_FLOOR, reason=f"쌓인 윗면 {(stacked + size[2]) * 1000:.0f} mm > "
                                                                       f"{top_max * 1000:.0f} mm (테두리 − stack_top_clear_m)"), out

        def not_under(objs):                                # 받침(밑에 깔린 것)은 끄는 길·손가락 자리 이웃이 아님 — 손끝이 그 위에 있음
            if stacked <= 0:
                return objs
            under = {o["id"] for o in plp.objects_under(target=target, objects=objs, size_of=self._size_or_none)}
            return [o for o in objs if o["id"] not in under]
        who, why = self._neighbor(params, drawer_id, lambda objs, nb: nc.drag_blocker(
            target=target, size_m=size, shift_y_m=plan.shift_y_m, shift_x_m=plan.shift_x_m, objects=not_under(objs),
            size_of=self._size_or_none, default_size_m=prm["place"]["default_obstacle_size_m"], margin_mm=nb["margin_mm"],
            support_m=stacked, below_tol_m=nb["below_tol_m"]))
        if why or who:                                      # 끌다가 옆 물체를 밀지 않게 — 움직이기 전 [사용자 10/09 랜덤 배치]
            return (sf.Outcome(False, sf.BAD_PARAMS, reason=why) if why else
                    sf.Outcome(False, NEIGHBOR_TOO_CLOSE, reason=f"끄는 길에 {who} — 띄우거나 {who} 먼저 치우기")), out
        tf, d = place["tf"], prm["drag"]
        speed = prm["speed"]
        if plan.push_to_xy_m is not None:                               # 벽까지 밀기는 뒤에서 [사용자 10/11]
            who, why = self._neighbor(params, drawer_id, lambda objs, nb: self._push_finger_blocker(plan, target, not_under(objs), nb))
            if why or who:                                              # 손가락 내려갈 자리에 이웃 — 움직이기 전 [사용자 10/12 PC2]
                return (sf.Outcome(False, sf.BAD_PARAMS, reason=why) if why else
                        sf.Outcome(False, NEIGHBOR_TOO_CLOSE, reason=f"뒤에서 밀 손가락 자리에 {who} — {who} 먼저 치우기")), out
            return self._push_from_behind(goal, drawer_id, target, plan, tf, d, out, support_m=stacked)
        on_x = plan.axis == "x"                                         # 앞뒤 벽에서 끌기 [사용자 10/10]
        wall = mp.dir_to_base(tf, (plan.wall_normal_x, 0.0, 0.0) if on_x else (0.0, plan.wall_normal_y, 0.0))   # 누르는 쪽 벽 (base)
        if d.get("close_axis", "object") == "wall":                    # 닫힘 축 = 옆벽 법선 [실측 B 10/06, 지우개 잘 끌림]
            tip_v = d["wall_tip_below_mm"]                             # 기울인 손끝이 TCP 아래 (실측)
            along = wall
        else:
            tip_v = mp.tip_contact(math.radians(d["tilt_deg"]), g)[1]  # 기울인 닫은 손끝의 가장 낮은 점 깊이 (TCP 아래, 계산)
            yaw = target["pose"]["yaw"]
            along = mp.dir_to_base(tf, (math.cos(yaw), math.sin(yaw), 0.0))  # 닫힘 축 = 물체 긴 변 (얇은 쪽이 옆벽)
        contact_z_m = stacked + size[2] + tip_v / 1000.0                    # 쌓였으면 받침 위 윗면
        # 10/06 실물로 맞춘 순서 (scripts/b_demo.py 와 같음): 탑뷰 → 서랍 안 경유점 movej → y 를 누를 자리 y 로 →
        # 제자리 기울이기 → 누를 자리 위 start_above_mm → 누르기(오검출 대책) → 옆으로 끌기 → 올라감
        bad = self._to_drawer_view(goal, drawer_id)
        if bad:
            return bad, out
        self._grip(0, 20)                                   # 누르기용으로 닫기 (탑뷰, 서랍 위 높이)
        down = (self.poses().get("drag_down") or {}).get(drawer_id)
        if down:
            o = self._movej(goal, down, "to_object:down", in_drawer=True)
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
        # 테두리 위 높이로 누를 자리 바로 위까지 → 기울이며 수직으로 내려옴, 블렌딩 한 번 (사이 멈춤 없음) [사용자 10/07·10/08]
        bad = self._over_then_down(goal, drawer_id, cur, above, "to_object:over")
        if bad:
            return bad, out
        attempts = int(d.get("press_attempts", 1))
        for attempt in range(1, attempts + 1):             # 끌기 전(누르기·힘 맞추기) 실패는 같은 자리에서 다시 — 물체는 아직 안 움직임 [사용자 10/07 "넛지 안 되면 닫지 말고 다시"]
            bad, pressed, held_n = self._press_relax(goal, above, end_mm, expect_z, d, speed)
            if not bad:
                break
            now = self.robot.posx()
            if sf.is_safety(bad) or attempt == attempts or now is None or math.dist(now[:3], above[:3]) > 1.0:
                return bad, out
            self.get_logger().warn(f"[nudge_object] {attempt}/{attempts} 실패 ({bad.error_code}: {bad.reason}) — 다시 누르기")
            goal.publish_feedback(Skill.Feedback(stage=f"retry:{attempt + 1}"))
        shift_y, shift_x = plan.shift_y_m, plan.shift_x_m
        if d.get("shift_mm") and not on_x:                  # 누른 높이·각도 그대로 고정 거리만 수평 이동 [사용자 10/07 "3 cm 이동만, 힘만 맞으면 잘 끌림"]
            shift_y = math.copysign(d["shift_mm"] / 1000.0, plan.shift_y_m)   # 방향은 계획(옆벽 반대)
        shift = mp.dir_to_base(tf, (shift_x, shift_y, 0.0))
        shift = [shift[0], shift[1], 0.0]                     # 수평으로만 (b_demo 와 같음): 서랍 tf 기울기로 41.7 mm 에 z −0.5 mm 가 섞이면
        #   끌면서 더 눌림 — 위치로 누르면 1 mm 에 2 → 10 N [실측 10/06] → 10/06 저녁 통합 PUSH_BLOCKED 15.1 N
        # 끄기 직전 힘 0점 다시 [사용자 10/10 "옮기기 직전에 힘값 리셋"] — 힘 맞추기 마지막 측정보다 멈춘 뒤 평균이 안정
        base_drag = self._tare(d.get("tare_settle_s")) or self._held_f
        max_z = d.get("max_force_z_n", d["max_force_n"])

        def blocked():
            f = self.robot.tool_force()
            if f is None or base_drag is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="힘 조회 실패")
            side = math.hypot(f[0] - base_drag[0], f[1] - base_drag[1])   # 옆(끄는 쪽) — 잘 끌리다 8 N 에서 멈춤 → 15 [사용자 10/10]
            dz = abs(f[2] - base_drag[2])                                  # 위아래 — 14 N 이면 열린 서랍이 앞으로 넘어감 [사용자 10/07]
            if side > d["max_force_n"]:
                return sf.Outcome(False, PUSH_BLOCKED, reason=f"끄는 중 옆 힘 {side:.1f} N > {d['max_force_n']:g} N")
            if dz > max_z:
                return sf.Outcome(False, PUSH_BLOCKED, reason=f"끄는 중 위아래 힘 {dz:.1f} N > {max_z:g} N")
            return None

        drag_to = [pressed[i] + 1000.0 * shift[i] for i in range(3)] + pressed[3:]
        bad = self._line(goal, drag_to, d["speed_mm_s"], "drag", watch=blocked)
        if sf.is_safety(bad):                               # 안전 정지·취소 뒤엔 올리지도 않음
            return bad, out
        now = self.robot.posx()
        if now is None:
            return sf.worse(bad, sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 올리지 못함")), out
        bad = sf.worse(bad, self._line(goal, mp.with_z(now, now[2] + d["lift_mm"]), self._in_vel(), "lift"))
        moved = mp.from_base(tf, [v / 1000.0 for v in now[:3]])
        before = mp.from_base(tf, [v / 1000.0 for v in pressed[:3]])
        dx = moved[0] - before[0] if (on_x or plan.shift_x_m) else 0.0     # 대각선(손잡이 쪽 비스듬)이면 둘 다 [사용자 10/10]
        dy = moved[1] - before[1] if (not on_x or plan.shift_y_m) else 0.0
        after = json.loads(json.dumps(target))
        after["pose"]["position"] = [target["pose"]["position"][0] + dx, target["pose"]["position"][1] + dy, 0.0]
        out.update(pushed=True, push_vector_m=[round(dx, 4), round(dy, 4)])   # floor_z_m: 바닥은 서랍 좌표 z=0
        if bad:
            return bad, out                                 # target_after 는 None (실패 결과 좌표로 집지 않음)
        out["target_after"] = after
        return sf.Outcome(True, reason=f"{held_n:.1f} N 으로 눌러 {'대각선 x·y' if dx and dy else ('앞뒤로 x' if on_x else '옆으로 y')} "
                                 f"{f'{dx * 1000:+.1f}·{dy * 1000:+.1f}' if dx and dy else f'{(dx or dy) * 1000:+.1f}'} mm 끌기"), out

    def _push_from_behind(self, goal, drawer_id, target, plan, tf, d, out, support_m=0.0):
        """물체 뒤에서 닫은 손가락 옆면으로 벽까지 밂 [사용자 10/11 PC2 "벽으로 밀칠 땐 지우개 뒤에서 밀기, 공간 충분"].
        탑뷰 → 닫기 → 서랍 안 경유점 → 테두리 위로 시작 자리 위 → 수직으로 손끝 바닥 위 push_tip_above_floor_mm 까지
        → 벽 쪽으로 계산한 끝까지 수평 밀기(push_speed_mm_s, 힘은 안전 상한만) → push_back_mm 물러남 → 올라감 (다음은 탑뷰에서 다시 보기).
        support_m: 쌓인 물체면 받침 높이 — 손끝은 받침 위 push_tip_above_floor_mm [사용자 10/13]."""
        g = self.prm()["gripper"]
        bad = self._to_drawer_view(goal, drawer_id)
        if bad:
            return bad, out
        self._grip(0, 20)
        down = (self.poses().get("drag_down") or {}).get(drawer_id)
        if down:
            o = self._movej(goal, down, "to_object:down", in_drawer=True)
            if not o.success:
                return o, out
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), out
        tcp_z = support_m + (d.get("push_tip_above_floor_mm", 3.0) + mp.tip_below_tcp_mm(0.9, g)) / 1000.0   # 닫은 손끝 = TCP − 10 mm [실측]
        nx, ny = plan.push_dir
        close_dir = mp.dir_to_base(tf, (-ny, nx, 0.0))                 # 닫힘 축 ⟂ 미는 방향 — 손가락 두 개가 나란히 판처럼
        (sx, sy), (ex, ey) = plan.press_xy_m, plan.push_to_xy_m
        low = mp.gripper_posx([1000.0 * v for v in pp.to_base(tf, (sx, sy, tcp_z))], close_dir, cur[3:])
        above = mp.with_z(low, low[2] + 30.0)
        bad = self._over_then_down(goal, drawer_id, cur, above, "to_object:over")
        if bad:
            return bad, out
        # 힘으로 끝을 찾지 않음 — 계산한 거리만 밂 [사용자 10/11 PC2 "넛지 말고 얼마나 밀면 끝에 도달할지만 계산해서"]. 힘은 안전 상한만
        base_f = self._tare(settle_s=0.2)
        max_z = d.get("max_force_z_n", d["max_force_n"])

        def guard(stage_name):
            def watch():
                f = self.robot.tool_force()
                if f is None or base_f is None:
                    return sf.Outcome(False, dp.SENSOR_INVALID, reason="힘 조회 실패")
                dz, side = abs(f[2] - base_f[2]), math.hypot(f[0] - base_f[0], f[1] - base_f[1])
                if dz > max_z or side > d["max_force_n"]:
                    return sf.Outcome(False, PUSH_BLOCKED, reason=f"{stage_name} 중 힘 위아래 {dz:.1f}·옆 {side:.1f} N — 상한 {max_z:g}·{d['max_force_n']:g} N")
                return None
            return watch
        bad = self._line(goal, low, self.prm()["speed"]["grasp_mm_s"], "push_down", watch=guard("밀 자리로 내려가기"))
        if bad:
            now = self.robot.posx()
            back = self._line(goal, mp.with_z(now, now[2] + d["lift_mm"]), self._in_vel(), "lift") if now and not sf.is_safety(bad) else None
            return sf.worse(bad, back) if back else bad, out
        pressed = self.robot.posx() or low
        end = mp.gripper_posx([1000.0 * v for v in pp.to_base(tf, (ex, ey, tcp_z))], close_dir, pressed[3:])
        end = [end[0], end[1], pressed[2]] + list(pressed[3:])         # 수평으로만 (서랍 tf 기울기로 z 가 섞여 바닥을 긁지 않게)
        push_v = d.get("push_speed_mm_s", d["speed_mm_s"])
        bad = self._line(goal, end, push_v, "push", watch=guard("밀기"))
        if sf.is_safety(bad):
            return bad, out
        now = self.robot.posx()
        if now is not None and not bad:
            # 벽과 손가락 사이에 낀 물체가 올릴 때 마찰로 딸려 올라옴 [사용자 10/11 PC2] → 미는 반대쪽으로 조금 물러난 뒤 올림
            back_v = mp.dir_to_base(tf, (-nx, -ny, 0.0))
            k = d.get("push_back_mm", 5.0)
            bad = self._line(goal, [now[0] + back_v[0] * k, now[1] + back_v[1] * k, now[2]] + list(now[3:]), push_v, "push_back")
            if sf.is_safety(bad):
                return bad, out
        now = self.robot.posx()
        if now is None:
            return sf.worse(bad, sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 올리지 못함")), out
        bad = sf.worse(bad, self._line(goal, mp.with_z(now, now[2] + d["lift_mm"]), self._in_vel(), "lift"))
        a = mp.from_base(tf, [v / 1000.0 for v in pressed[:3]])
        b = mp.from_base(tf, [v / 1000.0 for v in now[:3]])
        tcp_move = (b[0] - a[0]) * nx + (b[1] - a[1]) * ny
        gap = d.get("push_start_gap_mm", 10.0) / 1000.0
        move = max(0.0, min(tcp_move - gap, abs(plan.shift_x_m) + abs(plan.shift_y_m)))   # 닿기 전 빈 거리 뺀 물체 이동 [추정]
        dx, dy = nx * move, ny * move
        out.update(pushed=True, push_vector_m=[round(dx, 4), round(dy, 4)])
        if bad:
            return bad, out
        after = json.loads(json.dumps(target))
        yaw = after["pose"]["yaw"]
        after["pose"]["position"] = [target["pose"]["position"][0] + dx, target["pose"]["position"][1] + dy, 0.0]
        after["pose"]["yaw"] = round(yaw / (math.pi / 2)) * (math.pi / 2)   # 벽에 붙어 누웠다고 봄 — 다시 찍어 확인
        out["target_after"] = after
        return sf.Outcome(True, reason=f"뒤에서 밀어 {'x' if nx else 'y'} {(dx or dy) * 1000:+.1f} mm (계산한 끝까지, {d.get('push_back_mm', 5.0):g} mm 물러나 올림)"), out

    def _room_objs(self, params, drawer_id, tid, what):
        """make_room·topple 공통: scan 물체 목록(가림 관계 occluded_by 확인) → (objs, None) | (None, 거부 Outcome).
        가림 필드 (runner.md 7.1): null = 모름, 결과 전체에 없음 = 박스 모델(관계 정보 없음). 모름을 '위에 없음'([])으로 바꾸지 않음 —
        위에 얹힌 물체를 밀거나 누를 수 있음 [A·PM #226 리뷰 10/12]. 움직이기 전 거부 → 다시 찍기 (C select_obstacle occlusion_unknown 과 같은 방식)"""
        objs, why = plp.scan_objects(params.get("scan"), drawer_id)
        if why:
            return None, sf.Outcome(False, sf.BAD_PARAMS, reason=f"{what}: {why}")
        if tid not in {o["id"] for o in objs}:
            return None, sf.Outcome(False, sf.BAD_PARAMS, reason=f"{what}: 목표 {tid!r} 가 scan 에 없음")
        if not any("occluded_by" in o for o in objs):
            return None, sf.Outcome(False, OCCLUSION_UNKNOWN, reason=f"{what}: 가림 필드 없음(박스 모델) — 위에 얹힌 관계를 몰라 공간 만들기 안 함")
        unknown = [o["id"] for o in objs if not isinstance(o.get("occluded_by"), list)]
        if unknown:
            return None, sf.Outcome(False, OCCLUSION_UNKNOWN, reason=f"{what}: 위에 얹힌 관계 모름(occluded_by null·누락) {unknown} — 다시 찍기")
        return [dict(o, occluded_by=list(o["occluded_by"])) for o in objs], None

    def _room_cfg(self, drawer_id):
        prm, place = self.prm(), self.places()[drawer_id]
        mr = prm.get("make_room") or {}
        return clp.Config(interior_m=place["interior_m"], frame=drawer_id, size_of=self._size_cached(),
                          axes=clp.AXES if prm["drag"].get("push_inward_ok") else clp.AXES[:3],
                          max_shift_m=prm["drag"]["max_shift_mm"] / 1000.0, max_chain=int(mr.get("max_chain", 2)),
                          round_classes=tuple(prm["pick"].get("round_classes") or ()),
                          press_finger_r_mm=float(mr["press_finger_r_mm"]),
                          remove_first=bool(mr.get("remove_first", True)),
                          topple_extra_mm=float(mr.get("topple_extra_mm", 5.0)), topple_gap_mm=float(mr.get("topple_gap_mm", 5.0)),
                          reach_x_m=((prm.get("drawer_reach_x_mm") or {}).get(drawer_id) or 0.0) / 1000.0 or None)

    def _topple(self, goal, params, drawer_id, target):
        """쌓인 물체 무너뜨리기 [사용자 10/13 "집을 위치 없다고 포기하는 것도 웃김 — 비전으로 다시 보고 집으면 됨", 제안 — 계약 승인 전].
        nudge_object topple: true + target(맨 위 물체) + scan(직전 inspect_region 결과 전체, 가림 관계 필요). core/clear_plan.topple_move 로
        받침 밖 바닥까지 끄는 가장 짧은 서랍 축 방향·거리를 고르고(끄는 길·떨어질 자리 확인), 윗면을 눌러 끎 — 끈 뒤 자세는 모름 → 다시 보고 집기.
        check_only 면 고르기만 (움직이지 않음). 받침 관계가 없으면 높이·footprint 로 밑 물체를 찾아 씀 (pick 의 쌓임 판단과 같음)."""
        out = {"pushed": False, "push_vector_m": [0.0, 0.0], "clearance_before_m": 0.0, "floor_z_m": 0.0, "target_after": None,
               "topple": None}
        tid = target.get("id")
        objs, bad = self._room_objs(params, drawer_id, tid, "topple")
        if bad:
            return bad, out
        t = next(o for o in objs if o["id"] == tid)
        if not clp.below(objs, tid):                              # 분할 관계가 없어도 높이로 받침이 보이면 그걸로
            for b in plp.objects_under(target=t, objects=objs, size_of=self._size_or_none):
                b["occluded_by"] = list(b["occluded_by"]) + [tid]
        a = clp.topple_move(objs, tid, self._room_cfg(drawer_id))
        if a is None:
            why = ("밑에 깔린 물체 없음 (쌓이지 않음)" if not clp.below(objs, tid) else
                   "위에 다른 물체가 얹힘 — 맨 위부터" if clp.riders(objs, tid) else
                   "누를 점·끌 방향·떨어질 빈 자리 없음")
            return sf.Outcome(False, mp.NO_PUSH_ACCESS, reason=f"무너뜨리기 못 함: {why}"), out
        out["topple"] = {"dir": list(a.dir), "dist_m": round(a.dist_m, 4), "landed_pose": a.to_pose, "reason": a.reason}
        self.get_logger().info(f"[topple] {a.reason}")
        if params.get("check_only"):
            return sf.Outcome(True, reason=f"check_only: {a.reason} (움직이지 않음)"), out
        res, o2 = self._press_move(goal, drawer_id, t, a.dir, a.dist_m, 0.0, False, a.extra.get("press_xy_m"))
        out.update(pushed=o2["pushed"], push_vector_m=o2["push_vector_m"])
        if res.success:
            res = sf.Outcome(True, reason=f"{a.reason} ({res.reason})")
        return res, out

    def _make_room(self, goal, params, drawer_id, target):
        """파지 공간 만들기 한 단계 [제안 10/11 B, 계약 승인 전 — #117]. scan(직전 inspect_region 결과 전체) 필수.
        core/clear_plan 이 다음 동작 하나를 고름: 위에 얹힌 것·막는 것을 집어 빈 자리에 / 목표를 빈 쪽으로 넛지 / 사방이 막히면
        한쪽으로 쭉 밀고(옆 물체 같이) 일부 되돌아오기 / 벽 넛지. 판단은 이 서버의 사전 검사(DryOracle, 움직이지 않음).
        지금 바로 집을 수 있으면 움직이지 않고 make_room.ready_to_pick. 동작 하나 뒤엔 다시 보고(inspect_region) 다시 부름."""
        out = {"pushed": False, "push_vector_m": [0.0, 0.0], "clearance_before_m": 0.0, "floor_z_m": 0.0, "target_after": None,
               "make_room": None}
        scan = params.get("scan")
        tid = target.get("id")
        objs, bad = self._room_objs(params, drawer_id, tid, "make_room")
        if bad:
            return bad, out
        cfg = self._room_cfg(drawer_id)
        a = clp.plan_next(objs, tid, DryOracle(self, drawer_id), cfg)
        info = {"action": a.kind, "moved_id": a.target or None, "ready_to_pick": False, "reason": a.reason,
                "pushed_ids": [], "pushed_after": []}
        out["make_room"] = info
        by = {o["id"]: o for o in objs}
        self.get_logger().info(f"[make_room] {tid}: {a.kind} {a.target} — {a.reason}")
        if params.get("check_only"):                              # 판단 결과 공개 [E #245 제안] — 일반 넛지 check_only 와 같은 필드
            out.update(needed=a.kind not in ("pick", "fail"), plan_code=(a.code or mp.NO_PUSH_ACCESS) if a.kind == "fail" else None)
        if a.kind == "pick":
            info.update(action="none", moved_id=None, ready_to_pick=True)
            out["target_after"] = by[tid]
            return sf.Outcome(True, reason="이미 집을 수 있음 — 움직이지 않음"), out
        if a.kind == "fail":
            info["moved_id"] = None                               # 움직이지 않음 — 옮기려던 물체는 reason 에 [C #226 리뷰]
            code = a.code if a.code in (NEIGHBOR_TOO_CLOSE, NO_FREE_SPACE, mp.NO_PUSH_ACCESS) else mp.NO_PUSH_ACCESS
            return sf.Outcome(False, code, reason=f"공간을 만들 수 없음: {a.reason}"), out
        if params.get("check_only"):                              # 판단만 — 어떤 동작이든 움직이지 않음 [E #226 리뷰 P1]
            info["moved_id"] = None
            return sf.Outcome(False, PUSH_LIMIT, reason=f"check_only: 아직 잡을 수 없는 자리 — 다음 동작 {a.kind} {a.target}: {a.reason}"), out
        expect = clp.apply(objs, a, cfg)                          # 동작 뒤 예상 (목표 위치) — 실제는 다시 보고 확인
        out["target_after"] = next(o for o in expect if o["id"] == tid)
        info["moved_after"] = clp.as_pose(next(o for o in expect if o["id"] == a.target))   # 옮긴 물체 예상 자리 (다시 보기 전)
        # 같이 밀린 물체 (sweep) — 역순 복구(FR-ACT-04)에 움직인 물체 전부가 필요 [C #226 리뷰]. 예상 자리, 다시 보기 전
        info["pushed_ids"] = [i for i in a.pushed if i != a.target]
        info["pushed_after"] = [dict(clp.as_pose(next(o for o in expect if o["id"] == i)), id=i) for i in info["pushed_ids"]]
        moved = by[a.target]
        if a.kind in ("unstack", "remove"):                       # 집어서 빈 자리에 내려놓기 (서랍 안 놓기 검사 그대로)
            res, _ = self._do_pick_object(goal, {"target": moved, "approach_offset": [0, 0, 0.1], "scan": scan})
            if not res.success:
                out["target_after"] = None
                return res, out
            res, pl = self._place_in_drawer(goal, {"location": drawer_id, "pose": a.to_pose, "scan": scan}, drawer_id)
            info["placed_pose"] = (pl or {}).get("placed_pose")
            if not res.success:
                out["target_after"] = None
                return res, out
            return sf.Outcome(True, reason=f"{a.reason} — 다시 보고 다시 부르기"), out
        if a.kind == "wall_nudge":                                # 기존 벽 넛지 그대로 (끄는 길 이웃 확인 포함)
            p2 = {k: v for k, v in params.items() if k not in ("make_room", "check_only")}
            res, o2 = self._do_nudge_object(goal, dict(p2, target=moved))
            o2 = o2 or {}
            out.update({k: o2[k] for k in ("pushed", "push_vector_m", "clearance_before_m", "floor_z_m") if k in o2})
            if a.target == tid:                                   # 목표 자신 — 끈 실제 거리로 낸 예상 위치
                out["target_after"] = o2.get("target_after")
            else:                                                 # 이웃을 끔 — 목표는 그대로, 안쪽 결과는 옮긴 물체 쪽으로 [E #226 리뷰 P2]
                info["moved_after"] = clp.as_pose(o2["target_after"]) if o2.get("target_after") else None
            if not res.success:
                out["target_after"] = None
            return res, out
        res, o2 = self._press_move(goal, drawer_id, moved, a.dir, a.dist_m, a.back_m, bool(a.pushed), a.extra.get("press_xy_m"))
        out.update(pushed=o2["pushed"], push_vector_m=o2["push_vector_m"])
        if not res.success:
            out["target_after"] = None
        return res, out

    def _press_move(self, goal, drawer_id, target, u, dist_m, back_m, push_others, press_xy_m=None):
        """물체 윗면(press_xy_m, 없으면 가운데)을 닫은 손끝으로 눌러 서랍 축 u 로 dist_m 끌고(앞 물체는 같이 밀림), back_m 되돌아온 뒤 올라감
        [제안 10/11 B — 파지 공간 만들기 넛지·좌우 밀기]. 누르기·힘 맞추기·끄는 중 힘 감시는 벽 넛지(_do_nudge_object)와 같음.
        같이 밀 물체가 있으면 누르는 힘을 drag.sweep_force_n 으로 (손끝 밑에서 미끄러지지 않게 [추정 — 실물 확인 필요])."""
        out = {"pushed": False, "push_vector_m": [0.0, 0.0]}
        prm, place = self.prm(), self.places()[drawer_id]
        tf, d, g, speed = place["tf"], prm["drag"], prm["gripper"], prm["speed"]
        if push_others and d.get("sweep_force_n"):
            d = dict(d, drag_force_n=d["sweep_force_n"])
        size, _ = self.item(target.get("class"))
        trail = mp.dir_to_base(tf, (-u[0], -u[1], 0.0))          # 손끝을 끄는 반대쪽으로 기울임 (벽 넛지: 벽 쪽 = 끄는 반대쪽)
        if d.get("close_axis", "object") == "wall":
            tip_h, tip_v, along = 0.0, d["wall_tip_below_mm"], trail
        else:
            tip_h, tip_v = mp.tip_contact(math.radians(d["tilt_deg"]), g)
            yaw = target["pose"]["yaw"]
            along = mp.dir_to_base(tf, (math.cos(yaw), math.sin(yaw), 0.0))
        cx, cy = press_xy_m or target["pose"]["position"][:2]      # 누를 점 (계획: 더 높은 이웃에 손가락이 안 걸리는 점, 없으면 가운데)
        px, py = cx + u[0] * tip_h / 1000.0, cy + u[1] * tip_h / 1000.0   # 닿는 점이 누를 점에 오게 TCP 를 끄는 쪽으로
        support = motion_guard.support_m(target, size[2], prm["motion_guard"]["on_floor_tolerance_m"])   # 쌓였으면 받침 위 윗면 (무너뜨리기)
        contact_z_m = support + size[2] + tip_v / 1000.0
        bad = self._to_drawer_view(goal, drawer_id)
        if bad:
            return bad, out
        self._grip(0, 20)
        down = (self.poses().get("drag_down") or {}).get(drawer_id)
        if down:
            o = self._movej(goal, down, "to_object:down", in_drawer=True)
            if not o.success:
                return o, out
        start_mm = [1000.0 * v for v in pp.to_base(tf, (px, py, contact_z_m + d["start_above_mm"] / 1000.0))]
        end_mm = [1000.0 * v for v in pp.to_base(tf, (px, py, contact_z_m - d["search_below_mm"] / 1000.0))]
        expect_z = 1000.0 * pp.to_base(tf, (px, py, contact_z_m))[2]
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), out
        above = mp.gripper_posx(start_mm, along, cur[3:], tilt_toward=trail, tilt_deg=d["tilt_deg"])
        if not down:
            cur = mp.with_z(cur, prm["transit"]["safe_z_mm"])
        bad = self._over_then_down(goal, drawer_id, cur, above, "to_object:over")
        if bad:
            return bad, out
        for attempt in range(1, int(d.get("press_attempts", 1)) + 1):
            bad, pressed, held_n = self._press_relax(goal, above, end_mm, expect_z, d, speed)
            if not bad:
                break
            now = self.robot.posx()
            if sf.is_safety(bad) or attempt == int(d.get("press_attempts", 1)) or now is None or math.dist(now[:3], above[:3]) > 1.0:
                return bad, out
            goal.publish_feedback(Skill.Feedback(stage=f"retry:{attempt + 1}"))
        base_drag = self._tare(d.get("tare_settle_s")) or self._held_f
        max_z = d.get("max_force_z_n", d["max_force_n"])

        def blocked():
            f = self.robot.tool_force()
            if f is None or base_drag is None:
                return sf.Outcome(False, dp.SENSOR_INVALID, reason="힘 조회 실패")
            side, dz = math.hypot(f[0] - base_drag[0], f[1] - base_drag[1]), abs(f[2] - base_drag[2])
            if side > d["max_force_n"] or dz > max_z:
                return sf.Outcome(False, PUSH_BLOCKED, reason=f"끄는 중 힘 옆 {side:.1f}·위아래 {dz:.1f} N — 상한 {d['max_force_n']:g}·{max_z:g} N")
            return None

        v = mp.dir_to_base(tf, (u[0], u[1], 0.0))
        to = [pressed[i] + dist_m * 1000.0 * (v[i] if i < 2 else 0.0) for i in range(3)] + list(pressed[3:])   # 수평으로만
        bad = self._line(goal, to, d["speed_mm_s"], "drag", watch=blocked)
        if not bad and back_m > 0.0:                              # 양쪽 공간: 민 만큼의 일부를 눌린 채 되돌아옴 [사용자 10/11]
            now = self.robot.posx() or to
            back = [now[i] - back_m * 1000.0 * (v[i] if i < 2 else 0.0) for i in range(3)] + list(now[3:])
            bad = self._line(goal, back, d["speed_mm_s"], "drag_back", watch=blocked)
        if sf.is_safety(bad):
            return bad, out
        now = self.robot.posx()
        if now is None:
            return sf.worse(bad, sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — 올리지 못함")), out
        bad = sf.worse(bad, self._line(goal, mp.with_z(now, now[2] + d["lift_mm"]), self._in_vel(), "lift"))
        a, b = mp.from_base(tf, [x / 1000.0 for x in pressed[:3]]), mp.from_base(tf, [x / 1000.0 for x in now[:3]])
        out.update(pushed=True, push_vector_m=[round(b[0] - a[0], 4), round(b[1] - a[1], 4)])
        if bad:
            return bad, out
        return sf.Outcome(True, reason=f"{held_n:.1f} N 으로 눌러 {dist_m * 1000:.0f} mm 끌고 {back_m * 1000:.0f} mm 되돌아옴"
                                       f" (실제 {out['push_vector_m'][0] * 1000:+.1f}·{out['push_vector_m'][1] * 1000:+.1f} mm)"), out

    # --- 집기 ---
    def _do_pick_object(self, goal, params):
        if (err := self._refuse_if_hold_unknown()):
            return err, None
        if "source_slot" in params:                         # 칸 번호로 집기는 안 함 — 트레이를 찍은 target(pose.frame handover_zone)으로
            return sf.Outcome(False, UNSUPPORTED_PARAMS, reason="트레이에서 집기는 source_slot 대신 inspect_region(handover_zone) 의 target"), None
        if self.held:
            return sf.Outcome(False, HOLDING_OBJECT, reason=f"이미 {self.held['class']} 를 들고 있음"), None
        target = params.get("target") or {}
        frame = (target.get("pose") or {}).get("frame")
        if frame == TRAY and params.get("drawer_id") in (None, TRAY):
            return self._pick_from_tray(goal, params, target)
        drawer_id = params.get("drawer_id") or frame       # 계약엔 drawer_id 없음 → pose.frame
        if drawer_id != frame:                              # 둘 다 왔는데 다르면 어느 칸인지 모름 — 움직이기 전 거부 (#181 E 리뷰)
            return sf.Outcome(False, sf.BAD_PARAMS, reason=f"target.pose.frame {frame!r} ≠ drawer_id {drawer_id!r}"), None
        if drawer_id not in ("drawer_top", "drawer_bottom"):
            return sf.Outcome(False, sf.BAD_PARAMS, reason=f"target.pose.frame 이 서랍이 아님: {drawer_id!r}"), None
        prm, place = self.prm(), self.places().get(drawer_id) or {}
        cls = target.get("class")
        size, grip_force = self.item(cls)
        # 쌓인 물체 집기 [사용자 10/09, P2 3개 겹침]: 윗면이 테두리 − stack_top_clear_m 이하면 받침(top_z − 높이) 위에서 집음
        max_top = None
        if prm["pick"].get("allow_stacked") and place.get("interior_m"):
            max_top = place["interior_m"][2] - prm["pick"]["stack_top_clear_m"]
        err = motion_guard.precheck_pick(target=target, height_m=size[2], displacement_m=self.disp.get(drawer_id),
                                         tf_at_travel_m=place.get("tf_at_travel_m"), params=prm["motion_guard"],
                                         max_top_m=max_top)
        if err:
            return sf.Outcome(False, err.error_code, reason=err.reason), None
        gw = dict(prm["gripper"], wall_offset_mm=(prm.get("drawer_wall_offset_mm") or {}).get(drawer_id),
                  reach_x_max_mm=(prm.get("drawer_reach_x_mm") or {}).get(drawer_id),
                  max_open_mm=prm["pick"]["max_open_width_m"] * 1000.0, tilt_align_deg=prm["pick"]["tilt_align_deg"],
                  axis_grasp=bool(prm["pick"].get("axis_grasp")), front_tilt_within_mm=prm["pick"].get("front_tilt_within_mm"),
                  round=cls in (prm["pick"].get("round_classes") or []) and bool(prm["pick"].get("round_wall")))
        wall = mp.wall_blocks_grasp(target=target, size_m=size, interior_m=place.get("interior_m") or [0, 0, 0], g=gw)
        # 짧은 변이 벽에 걸리면: 넛지할 수 있으면 넛지 먼저(WALL_TOO_CLOSE), 넛지를 못 하는 자리면 긴 변 양끝으로 [사용자 10/10 우선순위]
        # 원통형이 옆벽에 붙으면 넛지 없이 긴 변 양끝 + 벽 쪽으로 기울임 (굴러감) [사용자 10/10 PC2 립밤]
        long_side = False
        ag = None                                           # 긴 변 양끝·서랍 축 파지 [사용자 10/10 "그리퍼 기준 파지"]
        if gw["axis_grasp"] and not gw["round"] and mp.axis_grasp_fits(size, gw) and mp.is_crosswise(target["pose"]["yaw"]):
            gd = dict(gw, wall_tcp_min_mm=(prm["drag"].get("wall_tcp_min_by_drawer_mm") or {}).get(drawer_id))
            ag = mp.plan_axis_grasp(target=target, size_m=size, interior_m=place.get("interior_m") or [0, 0, 0], g=gd,
                                    drag=prm["drag"])
            if ag.drag is not None:                         # 넛지 먼저 / 못 함 — 움직이기 전 거부
                return sf.Outcome(False, WALL_TOO_CLOSE, reason=ag.reason), None
            wall, long_side = None, True
        round_side = (mp.round_edge_dir(target=target, size_m=size, interior_m=place.get("interior_m") or [0, 0, 0], g=gw)
                      if gw["round"] else None)             # 원통형 가장자리 → 넛지 없이 그 벽 쪽 기울여 긴 변 [사용자 10/10]
        if round_side is not None:
            long_side = True
        elif ag is None and gw["round"] and mp.long_side_ok(target=target, size_m=size, interior_m=place.get("interior_m") or [0, 0, 0], g=gw):
            wall, long_side = None, True                    # 원통형은 긴 변 양끝 먼저 — 짧은 변이 벽에 걸려도 넛지(굴러감) 없이 [사용자 10/10 "원통형만 긴 변"]
        elif wall:
            gd = dict(gw, wall_tcp_min_mm=(prm["drag"].get("wall_tcp_min_by_drawer_mm") or {}).get(drawer_id))
            dp_ = mp.plan_drag(target=target, size_m=size, interior_m=place.get("interior_m") or [0, 0, 0], g=gd, drag=prm["drag"])
            long_side = not dp_.needed and dp_.error_code is None and mp.long_side_ok(
                target=target, size_m=size, interior_m=place.get("interior_m") or [0, 0, 0], g=gw)
        if wall and not long_side:                          # 움직이기 전 거부 (#83 A 요청, #80 D P1 후속)
            return sf.Outcome(False, WALL_TOO_CLOSE, reason=wall), None
        support = motion_guard.support_m(target, size[2], prm["motion_guard"]["on_floor_tolerance_m"]) if max_top else 0.0
        if support > 0 and params.get("scan") is not None:   # 쌓임: 높이는 깔린 물체의 온톨로지 높이로 (비전은 무엇이 밑인지만) [사용자 10/11]
            objs_, why_ = plp.scan_objects(params.get("scan"), drawer_id)
            s_ont = None if why_ else plp.ontology_support_m(target=target, objects=objs_, size_of=self._size_or_none)
            if s_ont is not None:
                # 덮인 물체는 비전 윗면이 번져 높게 나옴 → 온톨로지 [사용자 10/11]. 맨 위 물체(위에 아무것도 없음)는 비전 윗면이 맞음
                # (차키 52.8 = 몽키 18.5 + 캐러멜 18.5 + 차키 15.8) — 헛관계로 온톨로지 받침이 낮게 나오면 손가락이 받침 위로 내려감
                # [실측 PC2 10/12: "몽키가 캐러멜 위" 헛관계로 받침 18.5, 실제 37] → 맨 위 물체는 둘 중 높은 값 (높게 틀리면 못 집을 뿐)
                top_clear = isinstance(target.get("occluded_by"), list) and not target["occluded_by"]
                support = max(s_ont, support) if top_clear else s_ont
        by_cls = (prm["pick"].get("tcp_above_top_by_class_m") or {}).get(cls)   # 물건별 잡는 높이 (윗면 기준, 음수 = 아래) — 키 큰 물건 [실측으로 채움]
        pick_prm = dict(prm["pick"], tcp_above_top_m=by_cls) if by_cls is not None else prm["pick"]
        plan = pp.plan_drawer_grasp(target=target, size_m=size, tf=place["tf"], params=pick_prm, support_m=support,
                                    long_side=long_side)
        # 긴 변 잡기가 손잡이 쪽 벽 가까이면 그 벽 쪽으로 기울여 잡음 — 앞판이 테두리보다 높아 수직 몸통이 닿음 [사용자 10/10 PC2]
        tilt = None                                         # (기울일 쪽 서랍 방향, 각도, 이름, 손가락 닫힘 축) — 서랍 축 네 방향만 [사용자 10/10 교시]
        tilt_x = (mp.front_tilt_x_mm(target=target, size_m=size, interior_m=place.get("interior_m") or [0, 0, 0], g=gw)
                  if ag is None and long_side and round_side is None and prm["pick"].get("front_tilt_deg") else None)
        if tilt_x is not None:
            fz = mp.from_base(place["tf"], plan.position_m)[2] - prm["pick"].get("front_tilt_lower_mm", 0.0) / 1000.0
            plan = dataclasses.replace(plan, position_m=pp.to_base(place["tf"], (tilt_x / 1000.0, target["pose"]["position"][1], fz)))
            tilt = ((-1.0, 0.0, 0.0), prm["pick"]["front_tilt_deg"], "손잡이 쪽", (0.0, 1.0, 0.0))
        if round_side is not None:                          # 교시 자세 기준: TCP 는 물체 가운데보다 벽 쪽·아래 [실측 사용자 10/10 PC2 립밤 왼벽]
            rw = prm["pick"]["round_wall"]
            ox, oy = target["pose"]["position"][:2]
            vx, vy = round_side
            tz = support + size[2] / 2.0 - rw["tcp_below_center_mm"] / 1000.0
            k = rw["tcp_to_wall_mm"] / 1000.0
            plan = dataclasses.replace(plan, position_m=pp.to_base(place["tf"], (ox + vx * k, oy + vy * k, tz)))
            name = "옆벽 쪽" if vy else ("손잡이 쪽" if vx < 0 else "안쪽 벽 쪽")
            tilt = ((vx, vy, 0.0), rw["tilt_deg"], name, (1.0, 0.0, 0.0) if vy else (0.0, 1.0, 0.0))
        if ag is not None and ag.tilt_dir is not None:      # 가로로 손잡이 쪽 벽에 붙음: 손잡이 쪽으로 기울이고 손가락은 서랍 y (교시 방향)
            # 기울이면 손끝이 덜 내려가 윗부분만 잡혀 불안정 [사용자 10/11 PC2 "x·y 는 완벽, 더 깊이"] → front_tilt_lower_mm 더 내림
            fz = mp.from_base(place["tf"], plan.position_m)[2] - prm["pick"].get("front_tilt_lower_mm", 0.0) / 1000.0
            plan = dataclasses.replace(plan, position_m=pp.to_base(place["tf"], (*ag.tcp_xy_m, fz)))
            tilt = (ag.tilt_dir, prm["pick"]["front_tilt_deg"], "손잡이 쪽", (0.0, 1.0, 0.0))
        g, speed = prm["gripper"], prm["speed"]
        expected_w = self.grasp_width(cls, size, prm, long_side=long_side) or plan.expected_width_m   # 벌림은 외접박스 짧은 변(긴 변 잡기면 긴 변) 그대로
        if not long_side and cls in (prm["pick"].get("open_by_grasp_width") or []) and self.grasp_width(cls, size, prm):
            # 손잡이를 잡는 물건(몽키·망치): 벌림 = 잡는 폭 + 여유 — 머리 폭(외접 짧은 변)만큼 벌리면 손가락 자리가 넓어 이웃·벽에 걸림
            # [사용자 10/11 PC2 "몽키 엄청 벌리고 내려감, 육안으로 충분" → 몽키·망치 둘 다]
            plan = dataclasses.replace(plan, open_width_m=expected_w + prm["pick"]["open_margin_m"])
        pick_min_w = max(g["min_width_m"], g.get("pick_min_width_m") or 0.0)   # 성공 하한 10 mm [사용자 10/08, #43] — 놓침 2 mm 와 별개
        def neighbor(long_, open_m):
            fp_t, fp_s = (({**target, "pose": {**target["pose"], "yaw": target["pose"]["yaw"] + math.pi / 2}}, [size[1], size[0], size[2]])
                          if long_ else (target, size))             # 손가락 자리: 긴 변 잡기면 90° 돌린 것과 같음
            under = {o["id"] for o in plp.objects_under(target=target, objects=plp.scan_objects(params.get("scan"), drawer_id)[0] or [],
                                                        size_of=self._size_or_none)} if support > 0 and params.get("scan") else set()
            return self._neighbor(params, drawer_id, lambda objs, nb: nc.pick_blocker(   # 밑에 깔린 받침은 빼고 (비전 윗면이 높게 나와도) [사용자 10/11]
                target=fp_t, size_m=fp_s, open_mm=open_m * 1000.0, objects=[o for o in objs if o["id"] not in under], size_of=self._size_or_none,
                default_size_m=prm["place"]["default_obstacle_size_m"], finger_mm=g["fingertip_outer_mm"],
                margin_mm=nb["margin_mm"], support_m=support, below_tol_m=nb["below_tol_m"],
                finger_half_width_mm=g.get("tip_radius_mm"), fingertip_floor_m=tip_floor_m,
                fingertip_clear_m=float(nb.get("fingertip_clear_mm", 2.0)) / 1000.0,
                under_clear_m=((prm["pick"].get("under_clear_by_class_mm") or {}).get(cls) or 0.0) / 1000.0 or None,
                under_smear_m=float(prm["pick"].get("under_smear_mm", 5.0)) / 1000.0))
        # 손끝이 내려가는 가장 낮은 높이(닫은 손끝 = 받침 + 물건별·높이 비율, 벌린 손끝은 그보다 위) — 그보다 낮은 이웃은 손가락 자리에
        # 있어도 안 닿음 [사용자 10/12 PC2: 가림막(손끝 25 mm) 긴 변 옆 지우개 14.2·립밤 22.2 로 NEIGHBOR_TOO_CLOSE "높이가 더 높아 그냥 잡힘"].
        # 높이 계산으로 잡을 때만 (기울여 잡기·원통 벽은 손끝이 더 내려갈 수 있어 예전처럼 높이 안 봄)
        tip_floor_m = None
        if prm["pick"].get("grip_height_ratio") is not None and round_side is None and tilt is None:
            th = (prm["pick"].get("tip_above_floor_by_class_mm") or {}).get(cls)
            if th is None:
                th = max(float(prm["pick"].get("min_tip_above_floor_mm", 2.0)), size[2] * 1000.0 * float(prm["pick"]["grip_height_ratio"]))
            tip_floor_m = support + float(th) / 1000.0
        who, why = neighbor(long_side, plan.open_width_m)
        if who and not why and not long_side and tilt is None and mp.long_side_ok(
                target=target, size_m=size, interior_m=place.get("interior_m") or [0, 0, 0], g=gw) \
                and mp.front_tilt_x_mm(target=target, size_m=size, interior_m=place.get("interior_m") or [0, 0, 0], g=gw) is None:
            # 짧은 변 손가락 자리에 이웃 → 긴 변 양끝(손가락이 끝으로 감)이 비면 긴 변으로 [P2 시뮬레이션 10/10: 가림막 밑 지우개 옆 립밤]
            lplan = pp.plan_drawer_grasp(target=target, size_m=size, tf=place["tf"], params=pick_prm, support_m=support, long_side=True)
            lwho, lwhy = neighbor(True, lplan.open_width_m)
            if not lwho and not lwhy:
                who, long_side, plan = None, True, lplan
                expected_w = self.grasp_width(cls, size, prm, long_side=True) or plan.expected_width_m
        if why or who:                                      # 움직이기 전 거부 [사용자 10/09 랜덤 배치]
            return (sf.Outcome(False, sf.BAD_PARAMS, reason=why) if why else
                    sf.Outcome(False, NEIGHBOR_TOO_CLOSE, reason=f"벌린 손가락 자리에 {who} — 띄우거나 {who} 먼저 치우기")), None
        # 집기 계획 그대로의 쥘 상태 — place_object check_only 가 집기 전에 이걸로 놓기를 판단 [#241 리뷰 P1: 짧은 변 가정 → 실제 긴 변]
        self._pick_planned = {"class": cls, "id": target.get("id"), "width_m": expected_w, "drawer_id": drawer_id,
                              "tcp_above_floor_m": size[2] * (prm["pick"].get("grip_height_ratio") or 0.5), "long_side": long_side}
        bad = self._to_drawer_view(goal, drawer_id)
        if bad:
            return bad, None
        close_dir = mp.horizontal_angle_dir(plan.long_axis_deg + 90.0)
        if tilt is not None:                                # 기울일 땐 손가락도 서랍 축에 딱 맞춤 — 교시한 앞뒤·좌우 자세 그대로, 대각선 금지 [사용자 10/10]
            close_dir = mp.dir_to_base(place["tf"], tilt[3])
        off = params.get("approach_offset", 0.10)              # 태스크·온톨로지는 [0, 0, 0.1] (m) — z 만 씀
        approach = float(off[2] if isinstance(off, (list, tuple)) else off) * 1000.0
        down = (self.poses().get("drag_down") or {}).get(drawer_id)
        if down:
            # 넛지와 같은 길 [사용자 10/07 저녁, 10/08]: 탑뷰(팔 거의 펴짐)에서 바로 직선으로 가면 특이점 → 서랍 중앙 경유점 movej
            # → y 를 목표 y 로 → 목표 위(grasp + approach, 최대 30 mm)를 블렌딩 한 번에 (사이 멈춤 없음)
            # 경유점은 서랍 안 — 벌린 RG2 는 손끝이 더 내려옴 → 끌기처럼 닫고 지나감, 목표 위에서 벌림 [#136 PM 리뷰]
            self._grip(0, 20)
            jnow = self.robot.posj()
            tol = float(prm["pick"].get("at_waypoint_tol_deg", 0.5))
            if jnow and len(jnow) >= 6 and all(math.isfinite(v) for v in jnow[:6]) and max(
                    abs(a_ - b_) for a_, b_ in zip(jnow[:6], down)) <= tol:
                self.get_logger().info(f"[pick] 이미 경유점(실측 관절 {tol}° 안) — 경유점 이동 건너뜀 [E #245]")
            else:
                o = self._movej(goal, down, "to_object:down", in_drawer=True)
                if not o.success:
                    return o, None
            cur = self.robot.posx()
            if cur is None:
                return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), None
            # 잡는 손목 방향은 경유점에 도착한 뒤 그 손목 기준으로 (넛지와 같음). 탑뷰(그리퍼 180° 돌림)에서 미리 정하면
            # 경유점에서 손목을 반 바퀴 다시 돌리며 목표로 가 경유점을 안 지나는 것처럼 보임 [사용자 10/08]
            grasp = mp.gripper_posx([1000.0 * v for v in plan.position_m], close_dir, cur[3:])
            # 잡는 각도는 경유점(테두리 위)에서 J6 만 돌려 먼저 맞춤 — 내려가며 돌리면 벌린 손가락이 테두리 아래에서 한동안 옆벽 쪽으로
            # 벌어져 있어 비스듬한 물체 옆 벽에 닿음 [실측 PC2 10/10]. 옆 구간에서 돌리면 제어기가 출발 안 함 [실측 PC2 10/10].
            # 그리퍼 수직(B 180°)에서 J6 +θ = posx (C − A) +θ [계산 m0609_kin]
            turn = (grasp[5] - grasp[3]) - (cur[5] - cur[3])
            turn = (turn + 180.0) % 360.0 - 180.0
            jnow = self.robot.posj()
            if abs(turn) > 1.0 and jnow:
                o = self._movej(goal, list(jnow[:5]) + [jnow[5] + turn], "to_object:turn", in_drawer=True)
                if not o.success:
                    return o, None
                cur = self.robot.posx() or cur
                grasp = list(grasp[:3]) + list(cur[3:])
            by_height = prm["pick"].get("grip_height_ratio") is not None and round_side is None
            if by_height:
                # 온톨로지 높이로 계산 [사용자 10/11 "넛지 빼고 온톨로지 높이 반영해서, 벌려서 높이만큼 빠르게 내려가 집기"]: 닫은 손끝(잡는 폭 — 손끝 표)이
                # 받침 위 물체 높이 × grip_height_ratio. 지우개 손끝 약 5~6 mm 3/3 [실측 10/04]·립밤 교시 손끝 약 11 mm [실측 10/10] = 높이 절반. 덮개 판 등은 물건별 값
                floor_mm = 1000.0 * pp.to_base(place["tf"], (target["pose"]["position"][0], target["pose"]["position"][1], support))[2]
                tip_h = (prm["pick"].get("tip_above_floor_by_class_mm") or {}).get(cls)
                if tip_h is None:
                    tip_h = max(float(prm["pick"].get("min_tip_above_floor_mm", 2.0)), size[2] * 1000.0 * float(prm["pick"]["grip_height_ratio"]))
                grasp = mp.with_z(grasp, floor_mm + float(tip_h) + mp.tip_below_tcp_mm(expected_w * 1000.0, g))
            vert = list(grasp)                              # 기울이지 않은 잡는 자세 — 들고 나올 때 이걸로 되돌림 (놓으러 갈 때 J6 계산은 수직 기준)
            if tilt is not None:                            # 손끝은 벽 쪽, 몸통은 서랍 안쪽 — 테두리 위 옆 구간에서 기울임 (넛지와 같음)
                grasp = mp.gripper_posx(grasp[:3], close_dir, grasp[3:], tilt_toward=mp.dir_to_base(place["tf"], tilt[0]),
                                        tilt_deg=tilt[1])
            above = mp.with_z(grasp, grasp[2] + min(approach, 30.0))
            # 경유점에서 미리 벌리고(테두리 위 높이라 안 닿음) 테두리 위로 목표 위 → 잡는 높이 1 cm 위까지 블렌딩 한 번 — 목표 위에서 멈춰
            # 벌리고 다시 내려가지 않음 [사용자 10/10 "동작이 너무 많고 복잡"]. 마지막 1 cm 만 천천히 [사용자 10/07]
            self._grip(plan.open_width_m * 1000.0, 20)
            slow_mm = 0.0 if by_height else prm["pick"].get("slow_last_mm", 0.0)   # 높이 계산이면 한 번에 빠르게 [사용자 10/11 "존나 빠르게"]
            near = mp.with_z(grasp, grasp[2] + slow_mm) if slow_mm > 0 else grasp
            bad = self._over_then_down(goal, drawer_id, cur, near, "to_object:over", turn_down=tilt is None)   # 손목은 이미 맞춤 — 테두리 위로 목표 바로 위 → 수직 [사용자 10/08]
        else:                                               # 경유점 교시 전 서랍: 예전처럼 safe_z 로 옮김
            grasp = mp.gripper_posx([1000.0 * v for v in plan.position_m], close_dir, self._cur_angles())
            vert = list(grasp)
            above = mp.with_z(grasp, max(prm["transit"]["safe_z_mm"], grasp[2] + min(approach, 30.0)))   # 서랍 테두리만 넘는 높이 (10/06 사용자: 쓸데없이 높이지 않음)
            bad = self._transit(goal, above, "to_object")
        if bad:
            return bad, None
        if not down:
            self._grip(plan.open_width_m * 1000.0, 20)
        slow_mm = 0.0 if (down and by_height) else prm["pick"].get("slow_last_mm", 0.0)   # 잡는 높이 1 cm 전까지 빠르게, 마지막만 천천히 [사용자 10/07]
        bad = None
        if slow_mm > 0 and grasp[2] + slow_mm < self.robot.posx()[2] - 1.0:
            bad = self._line(goal, mp.with_z(grasp, grasp[2] + slow_mm), self._in_vel(), "descend_fast")
        if math.dist(self.robot.posx()[:3], grasp[:3]) > 0.5:              # 높이 계산이면 블렌딩이 이미 잡는 높이까지 → 안 움직임
            bad = bad or self._line(goal, grasp, speed["grasp_mm_s"], "descend")
        if bad:
            return bad, None
        grasp_z_now = (self.robot.posx() or grasp)[2]                 # 실제로 닫은 TCP 높이

        def pick_out(ok, hand, **evidence):
            """결과 output_json — 파지 성공(grasp_ok)과 손 상태(hand)를 따로 [P2 4절·Critical: 파지 실패 ≠ 빈손].
            hand: holding(쥠 확인) / empty(빈손 확정 = 닫힌 폭 ≤ gripper.min_width_m 2 mm) / released(실패 뒤 다시 벌림 확인 — 쥐지 않았지만
            빈손 확정 아님) / unknown(못 읽음·잡은 채 멈춤). 빈손 기준은 [E-B-C-GRIPPER-OBSERVATION-20261011-10, #43] 과 같음.
            grasp_evidence: 닫은 폭·grip_detected(같은 pick 의 닫기), 들어 올린 뒤 검사 — pick verify 근거."""
            ev = {"closed_width_m": _width_m(st.width_mm),
                  "grasp_detected": st.grip_detected, "min_width_m": pick_min_w, **evidence}
            return {"object_id": target.get("id"), "class": cls, "grasp_ok": ok, "hand": hand, "grasp_evidence": ev}
        force = float(params.get("grip_force") or grip_force or (g.get("grip_force_by_class_n") or {}).get(cls)   # 요청 > 온톨로지 > B 물건별 > 기본
                      or g["default_grip_force_n"])
        goal.publish_feedback(Skill.Feedback(stage="close"))
        st = self._grip(0, force)
        tol = g["grasp_width_tolerance_m"]
        if long_side:                                       # 긴 변 양끝: 비전 각도가 조금 틀리면 비스듬히 물려 폭이 커짐 [실측 PC2 10/11 캐러멜 79.7/75 ≈ 6°]
            th = math.radians(prm["pick"].get("long_side_yaw_slack_deg", 0.0))
            tol += max(0.0, size[0] * math.cos(th) + size[1] * math.sin(th) - size[0])
        chk = gc.check_grasp(width_m=st.width_mm / 1000.0, grasp_detected=st.grip_detected, min_width_m=pick_min_w,
                             expected_width_m=expected_w, width_tolerance_m=tol)
        if chk.reason == gc.SENSOR_INVALID:                    # 닫은 폭을 못 읽음 = 쥐었는지 모름 → 그리퍼 명령 없이 그 자리에서 멈춤, 쥔 것으로 기억 [P2 체크리스트 5]
            floor0 = pp.to_base(place["tf"], (target["pose"]["position"][0], target["pose"]["position"][1], 0.0))[2]
            self.held = {"class": cls, "id": target.get("id"), "width_m": expected_w, "drawer_id": drawer_id,
                         "tcp_above_floor_m": grasp_z_now / 1000.0 - floor0 - support, "long_side": long_side}
            return sf.Outcome(False, dp.SENSOR_INVALID, reason=f"닫은 뒤 그리퍼 폭 이상 ({st.width_mm!r}) — 쥔 것으로 기억, 확인 필요"), \
                pick_out(False, "unknown", close=chk.reason)
        if not chk.ok:
            st_open = self._grip(plan.open_width_m * 1000.0, 20)
            back = self._line(goal, above, self._in_vel(), "lift")
            w_open = _width_m(st_open.width_mm)                # 다시 벌린 폭 = 벌림 명령 ± 2 mm 면 released (빈손 확정 아님 [#43 결정 10])
            opened = w_open is not None and abs(w_open - plan.open_width_m) <= g["slip_tolerance_m"]
            return sf.worse(sf.Outcome(False, GRASP_FAILED, reason=f"파지 실패 {chk.reason} (폭 {st.width_mm:.1f} mm, "
                                                                 f"기대 {expected_w * 1000:.1f} mm)"),
                            back), pick_out(False, "released" if opened else "unknown", close=chk.reason, open_width_m=w_open)
        floor_z = pp.to_base(place["tf"], (target["pose"]["position"][0], target["pose"]["position"][1], 0.0))[2]
        # 닫아서 잡음 → 바로 쥔 것으로 기억: 들어 올리다 멈춰도(비상정지·이동 실패) 빈손으로 보지 않음 [P2 5절 보유 불명확]
        self.held = {"class": cls, "id": target.get("id"), "width_m": chk.width_m, "drawer_id": drawer_id,
                     "tcp_above_floor_m": grasp_z_now / 1000.0 - floor_z - support,   # 물체 자기 바닥 기준 — 놓을 땐 바닥에 놓음
                     "long_side": long_side}                                        # 긴 변 양끝을 쥠 → 놓을 때 손가락 방향 90° [사용자 10/10]
        if tilt is not None and down:
            # 기울여 집었으면 그 자세를 기억 — 원래 자리로 되돌릴 때(putback·return_to_original_pose) 수직으로는 손가락이 벽 밖이라
            # 거부됨 → 같은 자세로 거꾸로 놓음 [사용자 10/12 PC2: 손잡이 벽 립밤 putback WALL_TOO_CLOSE (꼭짓점 x −5.8 mm)]
            at = self.robot.posx() or grasp
            self.held = dict(self.held, tilt_back={
                "drawer_id": drawer_id, "position": list(target["pose"]["position"][:2]), "yaw": float(target["pose"]["yaw"]),
                "tcp_mm": [float(at[0]), float(at[1]), float(grasp_z_now)], "angles": [float(v) for v in grasp[3:]],
                # 위치는 서랍 좌표로도 — 놓을 때 지금 tf 로 바꿈 (그사이 서랍 tf 다시 교시·몇 mm 밀림 대비, #235 A·PM)
                "tcp_drawer_m": [float(v) for v in mp.from_base(place["tf"], [at[0] / 1000.0, at[1] / 1000.0, grasp_z_now / 1000.0])],
                "vert_angles": [float(v) for v in vert[3:]], "deg": float(tilt[1]), "name": tilt[2],
                "open_mm": plan.open_width_m * 1000.0})
        route = self._carry_route(drawer_id)
        # 집고 수직으로 테두리 위 높이까지 → 경유점 1(서랍 중앙, 같은 높이)로 수평, 블렌딩 한 번 — 비스듬히 가면 쌓인 물건에 닿음 [사용자 10/08].
        # 도착 뒤 잠깐 멈춤 [사용자 10/06 저녁]
        if route:
            up = mp.with_z(grasp, self._travel_z(drawer_id, max(grasp[2], route[0][2])))
            # 올리면서 서랍 x·y 각각 가운데 쪽으로 조금(미미한 대각선) — 벽에 붙은 물체가 벽에 끌려 기울지 않게
            # [사용자 10/10 "올리다 윗벽에 부딪혀 기울어짐, x·y 2 mm 정도 간격 두며 올라오게"]
            away = float(prm["pick"].get("lift_away_mm", 0.0))
            if away > 0:
                ox, oy = target["pose"]["position"][:2]
                sx = math.copysign(away, place["interior_m"][0] / 2 - ox) / 1000.0
                sy = math.copysign(away, place["interior_m"][1] / 2 - oy) / 1000.0
                v = mp.dir_to_base(place["tf"], (sx, sy, 0.0))
                up = [up[0] + 1000.0 * v[0], up[1] + 1000.0 * v[1]] + list(up[2:])
            r = self.prm()["transit"].get("blend_mm", 0.0)
            # 경유점 1 은 위치만 — 손목은 잡은 방향 그대로 (짧은 옆 구간에서 크게 돌리면 제어기가 출발 안 함 [실측 PC2 10/10 45° 지우개
            # 들어 올리기 NOT_REACHED]). 원래 방향은 놓으러 갈 때 긴 구간(들고 나오기 1→2)에서 돌아감
            back = list(route[0][:3]) + list(vert[3:])      # 기울여 잡았으면 테두리 위 옆 구간에서 수직으로 되돌림
            bad = self._blend(goal, [up, back], [r, 0.0], self._in_vel(), "lift")
        else:
            bad = self._line(goal, above, self._in_vel(), "lift")
        if bad:
            return bad, pick_out(False, "unknown", close=chk.reason)    # 닫아서 잡은 뒤 멈춤 — 기억은 쥔 채 (사람 확인)
        if route:
            time.sleep(prm["carry"]["pause_s"])
        st2 = Rg2(self.rg2_ip)
        try:
            w2 = st2.status().width_mm / 1000.0
        finally:
            st2.close()
        hold = gc.check_hold(width_m=w2, width_at_grasp_m=chk.width_m, min_width_m=g["min_width_m"],
                             slip_tolerance_m=g["slip_tolerance_m"])
        if hold.reason == gc.SENSOR_INVALID:                  # 들어 올린 뒤 폭을 못 읽음 = 쥐었는지 모름 → 쥔 것으로 기억(빈손으로 보지 않음) + 멈춤 [P2 체크리스트 5]
            return sf.Outcome(False, dp.SENSOR_INVALID, reason=f"들어 올린 뒤 그리퍼 폭 이상 ({w2!r}) — 쥔 것으로 기억, 확인 필요"), \
                pick_out(False, "unknown", close=chk.reason, lift=hold.reason)
        if not hold.held:                                     # DROPPED = 폭이 빈손 닫힘(≤ min_width_m)까지 줄어듦 — 실측 빈손
            self.held = None
            return sf.Outcome(False, GRASP_FAILED, reason=f"들어 올리다 놓침 ({hold.reason})"), \
                pick_out(False, "empty", close=chk.reason, lift=hold.reason, lift_width_m=_width_m(w2 * 1000.0))
        out = dict(pick_out(True, "holding", close=chk.reason, lift=hold.reason, lift_width_m=_width_m(w2 * 1000.0)),
                   pick_pose_drawer_frame=target.get("pose"))
        stacked = (f", 받침 {support * 1000:.1f} mm 위" if support else "") + (", 긴 변 양끝" if long_side else "") + \
            (f", {tilt[2]}으로 {tilt[1]:.0f}° 기울임" if tilt is not None else "") + (", 가로 → 긴 변" if ag is not None else "")
        return sf.Outcome(True, reason=f"{cls} 파지 (폭 {chk.width_m * 1000:.1f} mm, {hold.reason}{stacked})"), out

    def _pick_from_tray(self, goal, params, target):
        """전달 트레이(handover_zone)에서 집기 — return_items 처럼 트레이 물건을 서랍에 다시 넣을 때 [사용자 10/12 "트레이뷰로 보고 물체 집으면 됨"].
        target = inspect_region(handover_zone) 결과의 target 그대로 (pose.frame handover_zone), scan(선택) = 그 결과 전체 → 옆 물체 확인.
        확인은 모두 움직이기 전: yaw_valid → 바닥 위(top_z, 쌓임 없음) → 손 닿는 범위(interior_m) → 벌린 손가락 자리의 이웃.
        길: 트레이 위가 아니면 tray_view 로 → J6 만 돌려 잡는 방향 → 목표 위 free_lift_z → 수직으로 내려(1 cm 전까지 빠르게) 닫기 → free_lift_z 로.
        트레이는 서랍과 달리 벽에 붙여 놓지 않음(칸 가운데) → 넛지·기울이기 없이 짧은 변, 원통형만 긴 변 양끝 (서랍과 같은 규칙, 놓을 때 쥔 방향 그대로).
        잡는 높이도 서랍과 같음: 닫은 손끝 = 바닥 + 물체 높이 × grip_height_ratio (물건별 tip_above_floor_by_class_mm)."""
        prm, place = self.prm(), self.places().get(TRAY) or {}
        tf, interior = place.get("tf") or {}, place.get("interior_m")
        if not tf.get("translation_m") or not interior:
            return sf.Outcome(False, PLACE_NOT_CONFIGURED, reason=f"{TRAY} tf·interior_m 측정 전"), None
        cls = target.get("class")
        size, grip_force = self.item(cls)
        err = motion_guard.check_yaw(target) or motion_guard.check_on_floor(target, size[2], prm["motion_guard"]["on_floor_tolerance_m"])
        if err:
            return sf.Outcome(False, err.error_code, reason=err.reason), None
        x, y = target["pose"]["position"][:2]
        if not (0.0 <= x <= interior[0] and 0.0 <= y <= interior[1]):    # 손 닿는 범위(닫힌 손끝 중심) 밖 — 사람이 옮겨 놓은 물체 등
            return sf.Outcome(False, sf.BAD_PARAMS, reason=f"트레이 손 닿는 범위 밖 ({x * 1000:.0f}, {y * 1000:.0f}) mm — "
                                                          f"interior_m {interior[0] * 1000:.0f} × {interior[1] * 1000:.0f}"), None
        g, speed, pk = prm["gripper"], prm["speed"], prm["pick"]
        long_side = cls in (pk.get("round_classes") or [])
        plan = pp.plan_drawer_grasp(target=target, size_m=size, tf=tf, params=pk, support_m=0.0, long_side=long_side)
        expected_w = self.grasp_width(cls, size, prm, long_side=long_side) or plan.expected_width_m
        if not long_side and cls in (pk.get("open_by_grasp_width") or []) and self.grasp_width(cls, size, prm):
            plan = dataclasses.replace(plan, open_width_m=expected_w + pk["open_margin_m"])
        tip_h = (pk.get("tip_above_floor_by_class_mm") or {}).get(cls)
        ratio = float(pk.get("grip_height_ratio") or 0.5)
        if tip_h is None:
            tip_h = max(float(pk.get("min_tip_above_floor_mm", 2.0)), size[2] * 1000.0 * ratio)
        fp_t, fp_s = (({**target, "pose": {**target["pose"], "yaw": target["pose"]["yaw"] + math.pi / 2}}, [size[1], size[0], size[2]])
                      if long_side else (target, size))             # 손가락 자리: 긴 변 잡기면 90° 돌린 것과 같음 (서랍과 같음)
        who, why = self._neighbor(params, TRAY, lambda objs, nb: nc.pick_blocker(
            target=fp_t, size_m=fp_s, open_mm=plan.open_width_m * 1000.0, objects=objs, size_of=self._size_or_none,
            default_size_m=prm["place"]["default_obstacle_size_m"], finger_mm=g["fingertip_outer_mm"],
            margin_mm=nb["margin_mm"], support_m=0.0, below_tol_m=nb["below_tol_m"], finger_half_width_mm=g.get("tip_radius_mm"),
            fingertip_floor_m=float(tip_h) / 1000.0, fingertip_clear_m=float(nb.get("fingertip_clear_mm", 2.0)) / 1000.0))
        if why or who:
            return (sf.Outcome(False, sf.BAD_PARAMS, reason=why) if why else
                    sf.Outcome(False, NEIGHBOR_TOO_CLOSE, reason=f"트레이에서 벌린 손가락 자리에 {who} — 띄우거나 {who} 먼저")), None
        # 쥔 물체 id 는 트레이 것임을 붙여 둠 — 서랍 scan 의 같은 이름(eraser#1 등)과 섞이지 않게 (놓기 판단에서 서랍 물체로 오인 방지)
        held_id = f"{TRAY}/{target.get('id')}"
        self._pick_planned = {"class": cls, "id": held_id, "width_m": expected_w, "drawer_id": TRAY,
                              "tcp_above_floor_m": size[2] * ratio, "long_side": long_side}
        # --- 여기부터 움직임 ---
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), None
        if not self._over_tray(cur):                        # 서랍 위·홈 등 → 트레이 탑뷰로 (서랍 밖으로 빼기·올리기는 _named 가)
            o = self._named(goal, "tray_view")
            if not o.success:
                return o, None
            cur = self.robot.posx()
            if cur is None:
                return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패 — tray_view 뒤"), None
        floor_mm = 1000.0 * pp.to_base(tf, (x, y, 0.0))[2]
        grasp = mp.gripper_posx([1000.0 * v for v in plan.position_m], mp.horizontal_angle_dir(plan.long_axis_deg + 90.0), cur[3:])
        grasp = mp.with_z(grasp, floor_mm + float(tip_h) + mp.tip_below_tcp_mm(expected_w * 1000.0, g))
        # 잡는 손목 방향은 지금 자리에서 J6 만 돌려 먼저 (서랍·놓기와 같음 — 옆으로 가며 크게 돌리면 제어기가 출발 안 함 [실측 PC2 10/10·10/12])
        turn = ((grasp[5] - grasp[3]) - (cur[5] - cur[3]) + 180.0) % 360.0 - 180.0
        jnow = self.robot.posj()
        if abs(turn) > 1.0 and jnow:
            o = self._movej(goal, list(jnow[:5]) + [jnow[5] + turn], "tray:turn", in_drawer=True)   # 손목만 — 서랍 경유점과 같은 관절 속도
            if not o.success:
                return o, None
            cur = self.robot.posx() or cur
            grasp = list(grasp[:3]) + list(cur[3:])
        off = params.get("approach_offset", 0.10)
        approach = float(off[2] if isinstance(off, (list, tuple)) else off) * 1000.0
        above = mp.with_z(grasp, max(prm["transit"]["free_lift_z_mm"], grasp[2] + min(approach, 30.0)))   # 트레이 테두리 위 (놓기와 같은 높이)
        self._grip(plan.open_width_m * 1000.0, 20)
        bad = self._line(goal, above, self._free_vel(), "tray:over")
        slow_mm = pk.get("slow_last_mm", 0.0)               # 잡는 높이 1 cm 전까지 빠르게, 마지막만 천천히 (트레이 바닥 휨 1.9 mm [실측 10/10])
        if not bad and slow_mm > 0 and grasp[2] + slow_mm < above[2] - 1.0:
            bad = self._line(goal, mp.with_z(grasp, grasp[2] + slow_mm), speed["line_mm_s"], "descend_fast")
        bad = bad or self._line(goal, grasp, speed["grasp_mm_s"], "descend")
        if bad:
            return bad, None
        grasp_z_now = (self.robot.posx() or grasp)[2]
        pick_min_w = max(g["min_width_m"], g.get("pick_min_width_m") or 0.0)

        def pick_out(ok, hand, **evidence):                 # 서랍 집기와 같은 결과 형식 (contracts/examples/pick_object_result.json)
            ev = {"closed_width_m": _width_m(st.width_mm), "grasp_detected": st.grip_detected, "min_width_m": pick_min_w, **evidence}
            return {"object_id": target.get("id"), "class": cls, "grasp_ok": ok, "hand": hand, "grasp_evidence": ev}
        force = float(params.get("grip_force") or grip_force or (g.get("grip_force_by_class_n") or {}).get(cls)
                      or g["default_grip_force_n"])
        goal.publish_feedback(Skill.Feedback(stage="close"))
        st = self._grip(0, force)
        tol = g["grasp_width_tolerance_m"]
        if long_side:
            th = math.radians(pk.get("long_side_yaw_slack_deg", 0.0))
            tol += max(0.0, size[0] * math.cos(th) + size[1] * math.sin(th) - size[0])
        chk = gc.check_grasp(width_m=st.width_mm / 1000.0, grasp_detected=st.grip_detected, min_width_m=pick_min_w,
                             expected_width_m=expected_w, width_tolerance_m=tol)
        held = {"class": cls, "id": held_id, "width_m": expected_w, "drawer_id": TRAY,
                "tcp_above_floor_m": (grasp_z_now - floor_mm) / 1000.0, "long_side": long_side}
        if chk.reason == gc.SENSOR_INVALID:                    # 쥐었는지 모름 → 쥔 것으로 기억하고 그 자리에서 멈춤 (서랍과 같음)
            self.held = held
            return sf.Outcome(False, dp.SENSOR_INVALID, reason=f"닫은 뒤 그리퍼 폭 이상 ({st.width_mm!r}) — 쥔 것으로 기억, 확인 필요"), \
                pick_out(False, "unknown", close=chk.reason)
        if not chk.ok:
            st_open = self._grip(plan.open_width_m * 1000.0, 20)
            back = self._line(goal, above, self._free_vel(), "lift")
            w_open = _width_m(st_open.width_mm)
            opened = w_open is not None and abs(w_open - plan.open_width_m) <= g["slip_tolerance_m"]
            return sf.worse(sf.Outcome(False, GRASP_FAILED, reason=f"파지 실패 {chk.reason} (폭 {st.width_mm:.1f} mm, "
                                                                 f"기대 {expected_w * 1000:.1f} mm)"),
                            back), pick_out(False, "released" if opened else "unknown", close=chk.reason, open_width_m=w_open)
        self.held = dict(held, width_m=chk.width_m)          # 닫아서 잡음 → 바로 쥔 것으로 (올리다 멈춰도 빈손으로 보지 않음)
        bad = self._line(goal, above, self._in_vel(), "lift")
        if bad:
            return bad, pick_out(False, "unknown", close=chk.reason)
        st2 = Rg2(self.rg2_ip)
        try:
            w2 = st2.status().width_mm / 1000.0
        finally:
            st2.close()
        hold = gc.check_hold(width_m=w2, width_at_grasp_m=chk.width_m, min_width_m=g["min_width_m"],
                             slip_tolerance_m=g["slip_tolerance_m"])
        if hold.reason == gc.SENSOR_INVALID:
            return sf.Outcome(False, dp.SENSOR_INVALID, reason=f"들어 올린 뒤 그리퍼 폭 이상 ({w2!r}) — 쥔 것으로 기억, 확인 필요"), \
                pick_out(False, "unknown", close=chk.reason, lift=hold.reason)
        if not hold.held:
            self.held = None
            return sf.Outcome(False, GRASP_FAILED, reason=f"들어 올리다 놓침 ({hold.reason})"), \
                pick_out(False, "empty", close=chk.reason, lift=hold.reason, lift_width_m=_width_m(w2 * 1000.0))
        # 집은 칸은 빈 칸으로 (다음 트레이 놓기가 그 칸을 다시 씀) — 칸 x 폭 안에 있을 때만
        n = int(place.get("slots") or 1)
        i = min(range(n), key=lambda k: abs(pp.slot_centers(interior[:2], n)[k][0] - x))
        tray = self.tray
        if i in (tray.get(TRAY) or []) and abs(pp.slot_centers(interior[:2], n)[i][0] - x) <= interior[0] / n / 2.0:
            tray[TRAY] = [k for k in tray[TRAY] if k != i]
            self.tray = tray
        out = dict(pick_out(True, "holding", close=chk.reason, lift=hold.reason, lift_width_m=_width_m(w2 * 1000.0)),
                   pick_pose_drawer_frame=target.get("pose"))
        return sf.Outcome(True, reason=f"{cls} 트레이에서 파지 (폭 {chk.width_m * 1000:.1f} mm, {hold.reason}"
                                       f"{', 긴 변 양끝' if long_side else ''})"), out

    def _with_tray_held(self, params, loc, held):
        """트레이에서 집은(집을) 물체는 서랍 scan 에 없음 → 서랍 안 놓기 판단(이웃·빈 자리)용으로 그 물체를 서랍 밖 자리(−1 m)에 넣은 scan.
        놓기·빈 자리 검사는 쥔 물체를 빼고 이웃을 보므로 이 자리는 판단에 쓰이지 않음. 서랍에서 집은 물체는 그대로(scan 에 있어야 함, #166)."""
        scan = params.get("scan")
        if not held or held.get("drawer_id") != TRAY or not isinstance(scan, dict):
            return params
        objs, why = plp.scan_objects(scan, loc)
        if why or held["id"] in {o["id"] for o in objs}:
            return params                                   # 형식 오류는 놓기가 그대로 거부
        size = self._size_or_none(held["class"]) or self.prm()["place"]["default_obstacle_size_m"]
        me = {"id": held["id"], "class": held["class"], "top_z": float(size[2]), "occluded_by": [],
              "pose": {"frame": loc, "position": [-1.0, -1.0, 0.0], "yaw": 0.0, "yaw_valid": True}}
        return dict(params, scan=dict(scan, candidates=list(scan.get("candidates") or []) + [me]))

    # --- 놓기 ---
    def _do_place_object(self, goal, params):
        if (err := self._refuse_if_hold_unknown()):
            return err, None
        loc = params.get("location")
        if loc in ("drawer_top", "drawer_bottom"):
            if params.get("check_only"):
                return self._place_check(params, loc)
            params = self._with_tray_held(params, loc, self.held)   # 트레이에서 집은 물체를 서랍에 (return_items)
            if params.get("slot") == FREE_SLOT:
                return self._place_free(goal, params, loc)
            return self._place_in_drawer(goal, params, loc)
        if loc != "handover_zone":
            return sf.Outcome(False, UNSUPPORTED_PARAMS, reason=f"놓기는 handover_zone·drawer_top·drawer_bottom 만: {loc!r}"), None
        if not self.held:
            return sf.Outcome(False, NOT_HOLDING, reason="들고 있는 물체 없음"), None
        prm, place = self.prm(), self.places().get(loc) or {}
        tf, interior = place.get("tf") or {}, place.get("interior_m")
        if not tf.get("translation_m") or not interior:
            return sf.Outcome(False, PLACE_NOT_CONFIGURED, reason=f"{loc} tf·interior_m 측정 전"), None
        slots = pp.slot_centers(interior[:2], int(place.get("slots") or 1))
        tray = self.tray
        used = tray.setdefault(loc, [])
        free = [i for i in range(len(slots)) if i not in used]
        if not free:
            return sf.Outcome(False, TRAY_FULL, reason=f"{loc} {len(slots)}칸 모두 사용"), None
        i = free[0]
        g, pl, speed = prm["gripper"], prm["place"], prm["speed"]
        # 서랍 → 트레이 (10/06 사용자): 집어서 올린 뒤 서랍 앞판 위 높이(high_z)로 로봇 쪽(홈 위)으로 당겨 서랍 영역을 빠져나오고,
        # 거기서 트레이 칸 위로 바로 (보는 자세·tray_view 를 거치지 않음 — 팔을 편 자세에서 특이점·꺾임)
        z_m = mp.place_tcp_above_floor_m(self.held["tcp_above_floor_m"], pl["drop_m"])
        pos = [1000.0 * v for v in pp.to_base(tf, (slots[i][0], slots[i][1], z_m))]
        close_dir = mp.dir_to_base(tf, (0.0, 1.0, 0.0) if self.held.get("long_side") else (1.0, 0.0, 0.0))   # 칸이 x로 늘어섬 → 물체 긴 변은 y, 손가락은 x로 (긴 변 잡기면 y로)
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
                bad = self._line(goal, route[0], self._in_vel(), "carry:1")
                if bad:
                    return bad, None
                time.sleep(prm["carry"]["pause_s"])
                cur = self.robot.posx() or cur
            # 집은 손목 방향 → 놓는 손목 방향은 경유점 1(서랍 가운데, 테두리 위)에서 J6 만 돌려 먼저 [실측 PC2 10/10: 1→2 구간(64 mm)에서
            # 65° 되돌리는 블렌딩을 제어기가 출발 안 함]. 그리퍼 수직이면 J6 +θ = posx (C − A) +θ.
            # 들고 나오기 경유점도 위치만 쓰고 손목은 놓는 방향 그대로 — 긴 변 잡기(손가락 y)는 경유점 방향(손가락 x)과 90° 달라
            # 4번 → 칸 위에서 돌리다 제어기가 출발 안 함 [실측 PC2 10/10 손잡이 쪽 지우개 carry NOT_REACHED]
            turn = ((target[5] - target[3]) - (cur[5] - cur[3]) + 180.0) % 360.0 - 180.0
            jnow = self.robot.posj()
            if abs(turn) > 1.0 and jnow:
                o = self._movej(goal, list(jnow[:5]) + [jnow[5] + turn], "carry:turn", in_drawer=True)
                if not o.success:
                    return o, None
            pts = [list(p[:3]) + list(target[3:]) for p in route[1:]] + \
                [list(target[:2]) + [route[-1][2]] + list(target[3:])]   # 칸 위(4번 높이)
            slow_c = pl.get("slow_last_mm", 0.0)
            if slow_c > 0 and target[2] + slow_c < pts[-1][2] - 1.0:   # 칸 위에서 멈추지 않고 놓는 높이 1 cm 위까지 이어서 [사용자 10/10]
                pts.append(mp.with_z(target, target[2] + slow_c))
            rad = prm["carry"]["radius_mm"]
            here = self.robot.posx() or route[0]
            seq = [here] + pts
            radii = [min(rad, math.dist(seq[k][:3], seq[k + 1][:3]) / 2.0, math.dist(seq[k + 1][:3], seq[k + 2][:3]) / 2.0)
                     for k in range(len(pts) - 1)] + [0.0]   # 반지름은 앞뒤 구간 절반까지 (짧은 구간 1→2)
            bad = self._blend(goal, pts, radii, self._free_vel(), "carry")
            if bad:
                return bad, None                            # 놓는 자리로는 grasp_mm_s 로 살포시 (10/06 저녁: 놓기는 빠르게 하지 않음)
            above = list(pts[-2] if len(pts) > len(route) else pts[-1])   # 칸 위(4번 높이) — 놓은 뒤 여기로
        elif self._over_drawer(cur):                        # 서랍 위인데 들고 나오기 경유점(carry_line) 교시 전 — 움직이지 않음
            return sf.Outcome(False, sf.POSE_NOT_TAUGHT,         # (예전 carry_out movesj 경로는 두 칸 carry_line 교시 뒤 안 써서 10/12 정리로 뺌)
                              reason=f"poses.yaml carry_line.{self.held.get('drawer_id') or 'drawer_top'} 경유점 없음"), None
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
        if hold.reason == gc.SENSOR_INVALID:                  # 폭을 못 읽음 = 쥐었는지 모름 → 빈손으로 바꾸지 않고, 그리퍼 명령 없이 멈춤 [P2 체크리스트 5]
            return sf.Outcome(False, dp.SENSOR_INVALID, reason=f"옮기는 중 그리퍼 폭 이상 ({w!r}) — 쥔 물체 기억 유지, 확인 필요"), None
        if not hold.held:
            self.held = None
            return sf.Outcome(False, gc.FAILURE_CODE["transport"], reason=f"옮기는 중 놓침 ({hold.reason})"), None
        slow_mm = pl.get("slow_last_mm", 0.0)               # 놓는 높이(물체 바닥이 트레이 바닥 위) 1 cm 전까지 빠르게, 마지막만 천천히 [사용자 10/07]
        bad = None
        now = self.robot.posx()
        if slow_mm > 0 and now and target[2] + slow_mm < now[2] - 1.0:
            bad = self._line(goal, mp.with_z(target, target[2] + slow_mm), speed["line_mm_s"], "lower_fast")
        bad = bad or self._lower_touch(goal, target, speed["grasp_mm_s"], "lower")
        if bad:
            return bad, None
        goal.publish_feedback(Skill.Feedback(stage="release"))
        self._grip(self.held["width_m"] * 1000.0 + pl["release_extra_mm"], 20)
        used.append(i)
        self.tray = tray
        cls = self.held["class"]
        self.held = None
        back = self._line(goal, above, self._free_vel(), "lift")
        out = {"slot": f"{loc}_{i + 1}", "placed_pose": {"frame": loc, "position": [round(slots[i][0], 4),
                                                                                     round(slots[i][1], 4), 0.0]}}
        if back:                                            # 놓기는 끝났지만 올라오지 못함 → 그 오류 (안전 오류 보존)
            return back, out
        return sf.Outcome(True, reason=f"{cls} → {loc} {i + 1}번 칸"), out


    def _neighbor(self, params, drawer_id, check):
        """입력 scan(직전 inspect_region 결과 전체)이 있으면 check(objs, params.neighbor) → (막는 이웃 id, None).
        scan 형식·다른 서랍이면 (None, 이유) → BAD_PARAMS. scan 이 없으면 확인 안 함 (None, None) — 예전과 같음."""
        scan = params.get("scan")
        if scan is None:
            return None, None
        objs, why = plp.scan_objects(scan, drawer_id)
        if why:
            return None, why
        return check(objs, self.prm()["neighbor"]), None

    def _size_or_none(self, cls):
        """이웃 footprint 용 온톨로지 size_m — 모르는 class 면 None (place.default_obstacle_size_m 을 씀)."""
        try:
            return self.item(cls)[0]
        except (ValueError, TypeError, OSError):
            return None

    def _planned_held(self, obj, loc, scan):
        """check_only 를 집기 전에 부를 때: 실제 pick_object 를 판단 전용으로 돌려 그 집기 계획(긴 변·잡는 폭)대로 쥐었다고 봄
        [#241 리뷰 P1: 짧은 변 가정이면 손잡이 벽 립밤처럼 실제로는 긴 변(72.5 mm)으로 잡을 때 놓기 판단이 달라짐].
        → (held, None) | (None, 집기 거부 Outcome) — 집기가 움직이기 전 거부되면 놓기 판단도 통과시키지 않음."""
        if not isinstance(obj, dict) or not obj.get("id") or not obj.get("class") or not isinstance(obj.get("pose"), dict):
            return None, sf.Outcome(False, sf.BAD_PARAMS, reason="check_only: 쥔 물체가 없으면 object(scan 의 집을 물체)가 필요")
        dry = _Dry(self)
        try:
            from_tray = (obj.get("pose") or {}).get("frame") == TRAY       # 트레이 물체: scan 은 놓을 서랍 것 → 트레이 이웃 확인은 실제 집기에서
            o, _ = dry._do_pick_object(_DRY_GOAL, {"target": obj, "approach_offset": [0, 0, 0.1], "scan": None if from_tray else scan})
        except _WouldMove:
            planned = dry.__dict__.get("_pick_planned")
            if planned and planned.get("drawer_id") in (loc, TRAY):
                return dict(planned), None
            return None, sf.Outcome(False, sf.BAD_PARAMS, reason=f"check_only: {obj['id']} 집기 계획이 {loc} 가 아님")
        except Exception as e:                                    # 설정·계산 예외 = 판단 못 함 → 통과 아님
            return None, sf.Outcome(False, sf.SKILL_EXCEPTION, reason=f"check_only: 집기 판단 예외 {e!r:.100}")
        return None, sf.Outcome(False, o.error_code or sf.BAD_PARAMS, reason=f"check_only: 집기부터 거부 — {o.reason}")

    def _free_pose(self, params, loc, held):
        """slot "free": 서랍 안 빈 자리 — `B free`·make_room 과 같은 core/clear_plan.find_free_pose (벽·이웃 놓기 검사 통과,
        목표(scan.target) 둘레 비움, 다시 바로 집을 수 있는 곳 먼저, 아래 칸은 손 닿는 깊이 안). → (pose, None) | (None, Refusal)
        [PC2 10/12 Unpacking: aside 두 곳이 가려진 지우개의 방향 모름 footprint 에 걸려 거부 → 쥔 채 정지. 같은 scan 으로 빈 자리 (120, 230) 있음]"""
        objs, why = plp.scan_objects(params.get("scan"), loc)
        if why:
            return None, plp.Refusal(sf.BAD_PARAMS, why)
        if held["id"] not in {o["id"] for o in objs}:
            return None, plp.Refusal(sf.BAD_PARAMS, f"쥔(쥘) 물체 {held['id']!r} 가 scan 에 없음 — 집을 때 쓴 촬영 결과를 넘겨야 함")
        place = self.places().get(loc) or {}
        if not place.get("interior_m"):
            return None, plp.Refusal(PLACE_NOT_CONFIGURED, f"{loc} interior_m 측정 전")
        prm, scan = self.prm(), params["scan"]
        # 빈 자리 찾기 전용: occluded_by 모름(null·누락)을 [] 로 — '쌓임 없음'으로 보면 모든 물체를 바닥 물체로 세어 충돌을 다 검사함
        # (보수적). 가림 관계 판단(make_room·select_obstacle)에 이 목록을 다시 쓰지 말 것 — 거기선 모름을 바꾸지 않음 (runner.md 7.1) [A·PM #241]
        objs = [dict(o, occluded_by=list(o.get("occluded_by") or [])) for o in objs]
        tid = (scan.get("target") or {}).get("id") if scan.get("target_found") else None
        cfg = clp.Config(interior_m=place["interior_m"], frame=loc, size_of=self._size_cached(),
                         round_classes=tuple(prm["pick"].get("round_classes") or ()),
                         reach_x_m=((prm.get("drawer_reach_x_mm") or {}).get(loc) or 0.0) / 1000.0 or None)
        pose = clp.find_free_pose(objs, held["id"], [tid] if tid and tid != held["id"] else [], _HeldOracle(self, loc, held), cfg)
        if pose is None:
            return None, plp.Refusal(NO_FREE_SPACE, f"{loc} 안에 {held['class']} 를 놓을 빈 자리 없음")
        return pose, None

    def _place_free(self, goal, params, loc):
        """slot "free" 놓기: 빈 자리를 고른 뒤 그 pose 로 서랍 안 놓기 — 결과 slot = "free", placed_pose = 놓은 자리."""
        empty = {"slot": None, "placed_pose": None}
        if not self.held:
            return sf.Outcome(False, NOT_HOLDING, reason="들고 있는 물체 없음"), dict(empty)
        pose, bad = self._free_pose(params, loc, self.held)
        if bad:
            return sf.Outcome(False, bad.error_code, reason=bad.reason), dict(empty)
        o, out = self._place_in_drawer(goal, dict({k: v for k, v in params.items() if k != "slot"}, pose=pose), loc)
        if out and out.get("placed_pose") is not None:
            out["slot"] = FREE_SLOT
        return o, out

    def _place_check(self, params, loc):
        """check_only: 서랍 안 놓기 사전 검사만 — 어떤 동작도 하지 않음 [PC2 10/12 Unpacking: 놓을 데가 없는데 먼저 집어 쥔 채 정지].
        쥐고 있으면 그 상태로, 아직 안 쥐었으면 `object`(scan 의 집을 물체)를 실제 pick_object 집기 계획대로 쥐었다고 보고 판단
        (집기가 움직이기 전 거부면 그 코드로 거부). slot "free" 면 빈 자리를 고름.
        통과 = 성공 + 놓을 예정 slot·planned_pose (placed_pose 는 null — 놓지 않았음), 거부 = 실제 놓기와 같은 오류 코드·blocked_by.
        결과에 늘 check_only: true — 실행 기록·run_report 에서 실제로 놓은 것처럼 보이지 않게 [C #241 리뷰]."""
        empty = {"slot": None, "placed_pose": None, "check_only": True}
        if self.held:
            held = dict(self.held)
        else:
            held, refused = self._planned_held(params.get("object"), loc, params.get("scan"))
            if refused:
                return refused, dict(empty)
        p = self._with_tray_held({k: v for k, v in params.items() if k not in ("check_only", "object")}, loc, held)
        slot_name = None
        if p.get("slot") == FREE_SLOT:
            pose, bad = self._free_pose(p, loc, held)
            if bad:
                return sf.Outcome(False, bad.error_code, reason=f"check_only: {bad.reason}"), dict(empty)
            p, slot_name = dict({k: v for k, v in p.items() if k != "slot"}, pose=pose), FREE_SLOT
        dry = _Dry(self, held=held)
        try:
            o, out = dry._place_in_drawer(_DRY_GOAL, p, loc)
        except _WouldMove:
            slot, pose = dry.__dict__.get("_place_planned") or (None, None)
            where = slot_name or slot or f"({pose['position'][0]:.3f}, {pose['position'][1]:.3f})"
            return sf.Outcome(True, reason=f"check_only: {held['class']} → {loc} {where} 놓을 수 있음 (움직이지 않음)"), \
                {"slot": slot_name or slot, "placed_pose": None, "planned_pose": pose, "check_only": True}
        except Exception as e:                                    # 설정·계산 예외 = 못 함 (움직이지 않음)
            return sf.Outcome(False, sf.SKILL_EXCEPTION, reason=f"check_only: {e!r:.120}"), dict(empty)
        out = dict(out or empty, placed_pose=None, check_only=True)
        if o.success:                                             # 움직이지 않고 끝난 성공은 없음 — 그래도 판단만으로 처리
            return sf.Outcome(True, reason=f"check_only: {o.reason}"), out
        return sf.Outcome(False, o.error_code, reason=f"check_only: {o.reason}"), out

    def _place_in_drawer(self, goal, params, loc):
        """서랍 안 놓기 (#120 ②, 계약 #166 — runner.md 7.1 place_object). 확인은 모두 움직이기 전, 거부면 placed_pose null.
        길 [사용자 10/08: 서랍 안 물건이 약 55 mm 쌓일 수 있음 → 서랍 안 옆 이동은 travel_z(테두리 + in_drawer_clear_mm) 높이에서만]:
        서랍 안 경유점(drag_down) → travel_z 로 수직 → 놓을 자리 위로 수평 → 수직으로 내려 approach(최대 30 mm) → 놓침 확인
        → 1 cm 전까지 빠르게·마지막 천천히 → 벌림(쥔 폭 + release_extra) → travel_z 로 수직 → 경유점 위(travel_z)로."""
        empty = {"slot": None, "placed_pose": None}

        def refuse(code, reason, by=None):
            return sf.Outcome(False, code, reason=reason), (dict(empty, blocked_by=by) if by else dict(empty))
        if not self.held:
            return refuse(NOT_HOLDING, "들고 있는 물체 없음")
        prm, place = self.prm(), self.places().get(loc) or {}
        pose, slot, bad = plp.resolve_pose(params, loc, place.get("place_slots"))
        if bad:
            return refuse(bad.error_code, bad.reason)
        objs, why = plp.scan_objects(params.get("scan"), loc)
        if why:
            return refuse(sf.BAD_PARAMS, why)
        held_id = self.held.get("id")
        if held_id not in {o["id"] for o in objs}:            # 쥔 물체를 집을 때와 다른 촬영 결과 (#166)
            return refuse(sf.BAD_PARAMS, f"쥔 물체 {held_id!r} 가 scan 에 없음 — 집을 때 쓴 촬영 결과를 넘겨야 함")
        tf, interior = place.get("tf") or {}, place.get("interior_m")
        down = (self.poses().get("drag_down") or {}).get(loc)
        if not tf.get("translation_m") or not interior or not down:
            return refuse(PLACE_NOT_CONFIGURED, f"{loc} tf·interior_m·drag_down 경유점 교시 전")
        err = motion_guard.check_travel(self.disp.get(loc), place.get("tf_at_travel_m"),
                                        prm["motion_guard"]["travel_tolerance_m"])
        if err:
            return refuse(err.error_code, err.reason)
        g, pl, speed = prm["gripper"], prm["place"], prm["speed"]
        size, _ = self.item(self.held["class"])
        open_mm = self.held["width_m"] * 1000.0 + pl["release_extra_mm"]
        gw = dict(g, wall_offset_mm=(prm.get("drawer_wall_offset_mm") or {}).get(loc),
                  reach_x_max_mm=(prm.get("drawer_reach_x_mm") or {}).get(loc),
                  max_open_mm=prm["pick"]["max_open_width_m"] * 1000.0, tilt_align_deg=prm["pick"]["tilt_align_deg"],
                  axis_grasp=bool(prm["pick"].get("axis_grasp")), front_tilt_within_mm=prm["pick"].get("front_tilt_within_mm"),
                  wall_tcp_min_mm=(prm["drag"].get("wall_tcp_min_by_drawer_mm") or {}).get(loc),
                  round=self.held["class"] in (prm["pick"].get("round_classes") or []) and bool(prm["pick"].get("round_wall")))

        long_held = bool(self.held.get("long_side"))
        tb = self.held.get("tilt_back")
        back_tilt = bool(tb and not slot and tb.get("drawer_id") == loc and plp.same_place(
            pose, tb, tol_mm=float(pl.get("tilt_back_tol_mm", 0.0)), tol_deg=float(pl.get("tilt_back_tol_deg", 0.0))))
        support = None                                      # 다른 물체 위에 놓기 (명령한 pose 만, place.allow_stack_place) — 받침은 이웃 확인에서 뺌
        if not slot and not back_tilt and pl.get("allow_stack_place"):
            goal_id = ((params.get("scan") or {}).get("target") or {}).get("id")   # 찾는 목표 위에는 안 얹음 (Unpacking 중 목표는 꺼내야 함)
            support = plp.stack_support(pose=pose, held_id=held_id, held_size_m=size, size_of=self._size_or_none,
                                        objects=[o for o in objs if o["id"] != goal_id],
                                        max_top_m=interior[2] - prm["pick"]["stack_top_clear_m"])
            if support is not None:
                objs = [o for o in objs if o["id"] != support["id"]]

        def check(p_):
            # 긴 변 양끝을 쥐었으면 손가락이 긴 변 끝에 있음 → 90° 돌린 물체로 손가락 자리·벽 확인 (집기 footprint 와 같음)
            pc, sc = ((dict(p_, yaw=p_["yaw"] + math.pi / 2), [size[1], size[0]] + list(size[2:])) if long_held else (p_, size))
            bad_ = plp.check_place(pose=pc, held_id=held_id, held_size_m=sc, open_mm=open_mm, objects=objs,
                                   size_of=self._size_or_none, interior_m=interior, place=pl,
                                   g=dict(g, wall_offset_mm=(prm.get("drawer_wall_offset_mm") or {}).get(loc)),
                                   finger_half_width_mm=g.get("tip_radius_mm"))   # 손가락 띠만 (집기와 같음)
            if back_tilt and bad_ is not None and bad_.error_code == WALL_TOO_CLOSE:
                return None                                 # 집을 때 기울인 자세 그대로 되돌림 — 그 자세로 이미 거기 있었음 (이웃 확인은 위에서 통과)
            if bad_ or not slot:
                return bad_
            # 남은 물건을 아직 집을 수 있어야 함 — 놓은 물체가 남은 물건의 벌린 손가락 자리에 들어가면 안 됨 [P2 무작위 배치 10/10]
            me = {"id": held_id, "class": self.held["class"], "top_z": self.held.get("tcp_above_floor_m", 0.0) + size[2],
                  "pose": dict(p_, yaw_valid=True)}
            nb = prm.get("neighbor") or {}
            for o in objs:
                if o["id"] == held_id or not (o.get("pose") or {}).get("yaw_valid"):
                    continue
                osz = self._size_or_none(o.get("class"))
                if not osz:
                    continue
                blocked = True
                round_o = o.get("class") in (prm["pick"].get("round_classes") or [])
                ways = (True,) if round_o else ((False, True) if mp.axis_grasp_fits(osz, gw) else (False,))   # 원통형은 긴 변으로 잡음
                for long_ in ways:
                    if long_ and not round_o and not mp.long_side_ok(target=o, size_m=osz, interior_m=interior, g=gw):
                        continue                                    # 긴 변이 벽에 걸리면 그 길은 없음 (집기와 같은 판단)
                    ot, os_ = (({**o, "pose": {**o["pose"], "yaw": o["pose"]["yaw"] + math.pi / 2}}, [osz[1], osz[0], osz[2]])
                               if long_ else (o, osz))
                    if not nc.pick_blocker(target=ot, size_m=os_, open_mm=os_[1] * 1000.0 + g["open_margin_mm"], objects=[me],
                                           size_of=self._size_or_none, default_size_m=pl["default_obstacle_size_m"],
                                           finger_mm=g["fingertip_outer_mm"], margin_mm=nb.get("margin_mm", 5.0), support_m=0.0,
                                           below_tol_m=nb.get("below_tol_m", 0.003), finger_half_width_mm=g.get("tip_radius_mm")):
                        blocked = False
                        break
                if blocked:
                    return plp.Refusal(plp.PLACE_BLOCKED, f"놓으면 {o['id']} 를 집을 손가락 자리를 막음", o["id"])
            # 고정 자리는 나중에 넛지 없이 다시 집을 수 있어야 함(되돌리기) [P2 시뮬레이션 10/10: aside 에 놓은 가림막을 못 다시 집음]
            # 다시 볼 때 비전 오차(repick_noise_mm·deg)만큼 틀려도 넛지 없이 [P2 시뮬레이션 10/11: 아래 칸 aside_1 가림막을 ±3 mm 로 보면
            # 손잡이 쪽 벽에 걸려 넛지 → 안쪽으로 못 끌어 NO_PUSH_ACCESS]
            e_m, e_r = pl.get("repick_noise_mm", 0.0) / 1000.0, math.radians(pl.get("repick_noise_deg", 0.0))
            for dx, dy, dyaw in ([(0.0, 0.0, 0.0)] + [(sx * e_m, sy * e_m, sr * e_r) for sx in (-1, 1) for sy in (-1, 1) for sr in (-1, 1)]
                                 if e_m or e_r else [(0.0, 0.0, 0.0)]):
                q_ = dict(p_, position=[p_["position"][0] + dx, p_["position"][1] + dy] + list(p_["position"][2:]), yaw=p_["yaw"] + dyaw,
                          yaw_valid=True)
                dp_ = mp.plan_drag(target={"pose": q_}, size_m=size, interior_m=interior, g=gw, drag=prm["drag"])
                if dp_.needed or dp_.error_code:
                    return plp.Refusal(WALL_TOO_CLOSE, f"놓으면 다시 집을 때 넛지 필요 ({dp_.reason})", "wall")
            return None
        # 고정 자리(slot)는 큰 물체(가림막)면 벽·이웃에 안 걸리게 가장 적게 옮겨 맞춤 [P2 시뮬레이션 10/10]. 명령한 pose(되돌리기)는
        # 바닥에 그대로 놓을 때만 복구 허용 오차 안(restore_fit_max_mm)으로 방향은 그대로 옮기기만 — 원래 자리를 이웃이 살짝 막으면
        # 놓을 수 있는 aside 에서 집어 aside 에 다시 놓던 것 [PC2 10/12 Unpacking: 가림막 밑 립밤이 굴러 원래 자리 가장자리 ~10 mm 막음]
        # (기울여 되돌리기·쌓아 놓기는 집을 때 자세·받침 기준이라 옮기지 않음)
        shift = (pl.get("slot_fit_max_mm", 0.0) if slot
                 else 0.0 if back_tilt or support is not None else pl.get("restore_fit_max_mm", 0.0))
        pose, bad = plp.fit_slot(pose=pose, check=check, max_shift_mm=shift, step_mm=float(pl.get("slot_fit_step_mm", 2.0)),
                                 turn=bool(slot))
        if bad:
            return refuse(bad.error_code, bad.reason, bad.blocked_by)
        support_m = float(support["top_z"]) if support is not None else 0.0
        pos_m, long_deg = plp.place_tcp_m(tf, pose, support_m + mp.place_tcp_above_floor_m(self.held["tcp_above_floor_m"], pl["drop_m"]))
        travel_z = self._travel_z(loc, 0.0)                    # 서랍 안 옆 이동 높이 (넛지·집기와 같음) [사용자 10/08]
        self._place_planned = (slot, pose)                     # check_only 가 돌려줄 예정 자리 (판단 전용 사본에만 남음)
        # --- 여기부터 움직임 ---
        bad = self._to_drawer_view(goal, loc)
        if bad:
            return bad, dict(empty)
        if not sf.check_reached(down, self.robot.posj(), self.reach_tol).success:
            o = self._movej(goal, down, "place:down", in_drawer=True)
            if not o.success:
                return o, dict(empty)
        cur = self.robot.posx()
        if cur is None:
            return sf.Outcome(False, sf.STATE_UNKNOWN, reason="현재 좌표 조회 실패"), dict(empty)
        target = mp.gripper_posx([1000.0 * v for v in pos_m], mp.horizontal_angle_dir(long_deg + (0.0 if self.held.get("long_side") else 90.0)), cur[3:])
        if back_tilt:
            # 집기 거꾸로: 경유점에서 J6 만 돌려 집을 때 수직 손목 방향 맞춤 → 집을 때 TCP(+ drop_m)·집을 때 기울인 손목 그대로
            # (손가락 ± 를 다시 고르면 J6 가 반 바퀴 달라 손목 카메라가 벽 쪽으로 갈 수 있음 — 기억한 각도를 그대로 씀)
            va = tb["vert_angles"]
            turn = ((va[2] - va[0]) - (cur[5] - cur[3]) + 180.0) % 360.0 - 180.0
            jnow = self.robot.posj()
            if abs(turn) > 1.0 and jnow:
                o = self._movej(goal, list(jnow[:5]) + [jnow[5] + turn], "place:turn", in_drawer=True)
                if not o.success:
                    return o, dict(empty)
                cur = self.robot.posx() or cur
            xyz = ([1000.0 * v for v in pp.to_base(tf, tb["tcp_drawer_m"])] if tb.get("tcp_drawer_m") else list(tb["tcp_mm"]))
            target = [xyz[0], xyz[1], xyz[2] + 1000.0 * pl["drop_m"]] + list(tb["angles"])
            open_mm = min(open_mm, float(tb.get("open_mm") or open_mm))   # 집을 때 벌린 만큼만 (그 자리에서 손가락이 들어갔던 폭)
        else:
            # 놓는 손목 방향은 경유점(테두리 위)에서 J6 만 돌려 먼저 맞춤 (집기와 같음) — 옆으로 가며 크게 돌리면 제어기가 출발 안 함
            # [실측 PC2 10/12 run ef9250: aside_1 로 99° 돌리며 place:over → 1 s 두 번 멈춘 뒤 점마다 직선, 2~3 s 지연]
            turn = ((target[5] - target[3]) - (cur[5] - cur[3]) + 180.0) % 360.0 - 180.0
            jnow = self.robot.posj()
            if abs(turn) > 1.0 and jnow:
                o = self._movej(goal, list(jnow[:5]) + [jnow[5] + turn], "place:turn", in_drawer=True)
                if not o.success:
                    return o, dict(empty)
                cur = self.robot.posx() or cur
                target = list(target[:3]) + list(cur[3:])
        above = mp.with_z(target, target[2] + min(pl["approach_m"] * 1000.0, 30.0))
        route = self._carry_route(loc)
        back = list(route[0]) if route else list(cur)          # 돌아갈 서랍 안 경유점 (= drag_down TCP)
        vel = self._in_vel()
        bad = self._over_then_down(goal, loc, cur, above, "place:over", turn_down=not back_tilt)   # 옆 이동은 travel_z 에서만, 내려가기는 수직 (넛지·집기와 같음)
        if bad:
            return bad, dict(empty)
        r = Rg2(self.rg2_ip)
        try:
            w = r.status().width_mm / 1000.0
        finally:
            r.close()
        hold = gc.check_hold(width_m=w, width_at_grasp_m=self.held["width_m"], min_width_m=g["min_width_m"],
                             slip_tolerance_m=g["slip_tolerance_m"])
        if hold.reason == gc.SENSOR_INVALID:                  # 폭을 못 읽음 = 쥐었는지 모름 → 빈손으로 바꾸지 않고 열지 않음 [P2 체크리스트 5]
            return sf.Outcome(False, dp.SENSOR_INVALID, reason=f"놓기 직전 그리퍼 폭 이상 ({w!r}) — 쥔 물체 기억 유지, 확인 필요"), dict(empty)
        if not hold.held:                                     # ③ 놓기 직전 (domain.md 놓침 확인)
            self.held = None
            return sf.Outcome(False, gc.FAILURE_CODE["transport"], reason=f"놓기 직전 놓침 ({hold.reason})"), dict(empty)
        slow_mm = pl.get("slow_last_mm", 0.0)
        bad = None
        now = self.robot.posx()
        landed = {}
        if slow_mm > 0 and now and target[2] + slow_mm < now[2] - 1.0:
            # 빠르게 내려가는 구간도 힘을 봄 — 쥔 물체가 비전이 못 본 물체(쌓였던 받침 등)에 먼저 닿으면 거기서 멈춤
            # [사용자 10/12 PC2: 몽키 위 캐러멜 putback 이 바닥 높이까지 내려가며 몽키를 누름]
            base_fast = self._tare(pl.get("touch_settle_s"))
            fast_n = float(pl.get("fast_guard_n") or prm["drag"]["press_max_force_n"])

            def hit():
                f = self.robot.tool_force()
                if f is None or base_fast is None:
                    return sf.Outcome(False, dp.SENSOR_INVALID, reason="힘 조회 실패")
                if abs(f[2] - base_fast[2]) >= fast_n:
                    p_ = self.robot.posx()
                    landed["z"] = p_[2] if p_ else None
                    return sf.Outcome(True, reason=f"내려가다 {abs(f[2] - base_fast[2]):.1f} N — 다른 물체 위에 닿음")
                return None
            bad = self._line(goal, mp.with_z(target, target[2] + slow_mm), vel, "descend_fast", watch=hit)
        if not bad and "z" not in landed:
            bad = self._lower_touch(goal, target, speed["grasp_mm_s"], "descend")
        if bad:
            return bad, dict(empty)
        if landed:                                            # 그 자리(받침 위)에 놓음 — 더 누르지 않음
            above_mm = (landed["z"] - target[2]) if landed.get("z") is not None else float("nan")
            self.get_logger().warn(f"[place_object] 계산한 놓는 높이보다 {above_mm:.1f} mm 위에서 닿음 — 다른 물체 위에 놓음 (비전이 못 본 받침?)")
        bad = self._clear_to_continue(goal)                   # 그리퍼 열기 전: 취소·비상정지면 열지 않음
        if bad:
            return bad, dict(empty)
        goal.publish_feedback(Skill.Feedback(stage="release"))
        self._grip(open_mm, 20)
        cls = self.held["class"]
        self.held = None                                      # 연 뒤에는 다시 보내도 NOT_HOLDING (중복 놓기 없음, #166)
        out = {"slot": slot, "placed_pose": pose}             # 명령한 자리 (재인식 아님) — 연 뒤에만
        for pose_x, st in ((mp.with_z(target, travel_z), "lift"), (mp.with_z(back, max(back[2], travel_z)), "back")):
            bad = self._line(goal, pose_x, vel, st)
            if bad:                                           # 놓기는 끝났지만 올라오지 못함 → 그 오류 + placed_pose
                return bad, out
        where = (slot or f"({pose['position'][0]:.3f}, {pose['position'][1]:.3f}) yaw {pose['yaw']:.2f}") + (
            f" — 집을 때처럼 {tb['name']}으로 {tb['deg']:.0f}° 기울여" if back_tilt else "")
        return sf.Outcome(True, reason=f"{cls} → {loc} {where}"), out


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
