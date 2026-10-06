#!/usr/bin/env python3
"""B 스킬 서버(ready2go_skills)의 실제 코드로 시연 흐름을 돌려 로봇 이동 명령을 기록하고, 관절 궤적을 계산한다 (담당 A, 트윈 사전 검증).

  python3 sim/motion_check/trace_skill_flow.py --repo <B 코드가 있는 저장소 경로> --out trace.json [--steps open,nudge,pick,place,close,home]

- ROS·로봇 없이 B 의 `skill_server` 를 불러(ROS 모듈은 가짜로 대신, B 의 test_skill_server_node.py 와 같은 방식) 가짜 로봇에 연결한다.
- 가짜 로봇은 기구학(m0609_kin)을 가진다: movej 는 관절 보간, movel 은 직선(위치 선형·자세 slerp)을 잘게 나눠 IK 로 이어 푼다.
- 힘 센서는 "접촉"이 필요한 단계에서만 흉내 낸다(손잡이 닿기·누르기·서랍 끝·닫힘). 실물 힘 값이 아니다.
- 결과 trace.json: 구간마다 명령 종류·단계 이름·시작/끝 posx·관절 궤적(deg)·J3·J5 최소 절댓값·최소 특이값·관절 최대 변화.
특이점 판정은 기하만 본다. 두산 제어기 내부 보간·특이점 회피와는 다를 수 있다 [추정].
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m0609_kin as kin  # noqa: E402

ERASER = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
          "pose": {"frame": "drawer_top", "position": [0.1769, 0.2895, 0.0], "yaw": 0.0, "yaw_valid": True}}  # b_sk.py 와 같은 값
HOME_J = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]


def stub_ros():
    def mod(name, **attrs):
        try:
            importlib.import_module(name)
            return
        except ImportError:
            pass
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
    mod("rclpy")
    mod("rclpy.action", ActionServer=object, CancelResponse=object, GoalResponse=object)
    mod("rclpy.callback_groups", ReentrantCallbackGroup=object)
    mod("rclpy.executors", MultiThreadedExecutor=object)
    mod("rclpy.node", Node=type("Node", (), {}))
    mod("ready2go_interfaces")
    mod("ready2go_interfaces.action", Skill=types.SimpleNamespace(Feedback=lambda stage: stage))
    mod("dsr_msgs2")
    if "dsr_msgs2.srv" not in sys.modules:                              # 서비스 타입은 이름만 있으면 됨 (B 가 새로 쓰는 것도 자동으로)
        class _AnySrv(types.ModuleType):
            def __getattr__(self, name):
                return object
        sys.modules["dsr_msgs2.srv"] = _AnySrv("dsr_msgs2.srv")
    mod("pymodbus")
    mod("pymodbus.client", ModbusTcpClient=object)


class KinRobot:
    """기구학 가짜 로봇. 명령은 바로 끝난 것으로 보고(state 가 몇 번 '움직임' 후 '정지'), 궤적은 따로 기록."""

    def __init__(self, q0):
        self.j = list(q0)
        self.p = kin.fk_posx(self.j)
        self.segments, self.stage, self.contact, self.grip_events = [], "", None, []
        self._moving = 0
        self.step = ""

    # --- 상태 조회 ---
    def auto(self, *a, **k):
        return True

    def state(self):
        if self._moving:
            self._moving -= 1
            return 2
        return 1

    def posx(self):
        return list(self.p)

    def posj(self):
        return list(self.j)

    def tool_force(self):
        """접촉 흉내: contact(z 이하·y 이상 등)를 지나면 힘을 낸다."""
        f = [0.0] * 6
        c = self.contact
        if c and c(self.p):
            f = list(c(self.p))
        return f

    def tool_names(self):
        return ("GripperDA_v1", "tool_weight")

    def stop(self):
        self._moving = 0
        return True

    # --- 이동 ---
    def movej_async(self, j, vel, acc):
        if getattr(self, "from_line", False):                            # 직선 단계 뒤 바로 관절 이동(예: 열기의 drawer_approach)
            self.stage, self.from_line = "movej", False
        q0, q1 = np.array(self.j, float), np.array(j, float)
        n = max(2, int(np.max(np.abs(q1 - q0)) / 0.5))
        traj = [(q0 + (q1 - q0) * k / n).tolist() for k in range(n + 1)]
        self._record("movej", self.p, kin.fk_posx(j), traj, dict(vel=vel, acc=acc))
        self.j, self.p = list(j), kin.fk_posx(j)
        self._moving = 2
        return True

    def movesj_async(self, points, vel, acc):
        """관절 스플라인: 현재 자세 → 경유점들. Catmull-Rom 으로 근사 (두산 movesj 의 실제 스플라인과 모양이 조금 다를 수 있음 [추정])."""
        P = [np.array(self.j, float)] + [np.array(q, float) for q in points]
        ext = [P[0]] + P + [P[-1]]
        traj = [P[0].tolist()]
        for k in range(1, len(ext) - 2):
            p0, p1, p2, p3 = ext[k - 1], ext[k], ext[k + 1], ext[k + 2]
            n = max(2, int(np.max(np.abs(p2 - p1)) / 0.5))
            for m in range(1, n + 1):
                t = m / n
                q = 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)
                traj.append(q.tolist())
        self._record("movesj", self.p, kin.fk_posx(points[-1]), traj, dict(vel=vel, acc=acc, waypoints=len(points)))
        self.j, self.p = list(points[-1]), kin.fk_posx(points[-1])
        self._moving = 2
        return True

    def movel_async(self, p, vel, acc, rot_vel=30.0, rot_acc=60.0):
        dist = float(np.linalg.norm(np.array(p[:3]) - np.array(self.p[:3])))
        Ts, ang = kin.interp_line(self.p, p, 1)
        n = max(2, int(max(dist / 0.5, ang / 0.25)))                  # 0.5 mm·0.25° 간격
        Ts, _ = kin.interp_line(self.p, p, n)
        q, traj, fail = self.j, [list(self.j)], 0
        for T in Ts[1:]:
            q, ok = kin.ik(T, q)
            fail += 0 if ok else 1
            traj.append(list(map(float, q)))
        self._record("movel", self.p, list(p), traj, dict(vel=vel, acc=acc, rot_vel=rot_vel, rot_acc=rot_acc,
                                                          dist_mm=dist, rot_deg=ang, ik_fail=fail))
        self.j, self.p = traj[-1], list(p)
        self._moving = 2
        return True

    def _record(self, kind, p0, p1, traj, extra):
        a = np.array(traj)
        man = [kin.manipulability(q)[1] for q in traj[:: max(1, len(traj) // 60)]]
        dq = np.abs(np.diff(a, axis=0)) if len(a) > 1 else np.zeros((1, 6))
        self.segments.append(dict(i=len(self.segments), kind=kind, stage=self.stage, start_posx=[round(v, 2) for v in p0],
                                  end_posx=[round(v, 2) for v in p1], joints=[[round(v, 3) for v in q] for q in traj],
                                  min_abs_j3=float(np.min(np.abs(a[:, 2]))), min_abs_j5=float(np.min(np.abs(a[:, 4]))),
                                  min_sigma=float(min(man)), max_step_deg=float(dq.max()),
                                  joint_travel_deg=[round(float(v), 1) for v in np.abs(a[-1] - a[0])], **extra))


def load_server(repo: Path, robot):
    sys.path.insert(0, str(repo / "ros2_ws/src/ready2go_skills"))
    stub_ros()
    from ready2go_skills.core import skill_flow as sf
    from ready2go_skills.core.rg2_protocol import Rg2Status
    ss = importlib.import_module("ready2go_skills.nodes.skill_server")
    real_wait = sf.wait_motion

    def fast_wait(**kw):
        kw.update(settle_s=0.0, sleep=lambda s: None)
        return real_wait(**kw)
    sf.wait_motion = fast_wait

    class Gripper:
        width, holding = 99.0, True                                    # 닫으면 항상 무언가를 잡음(손잡이·지우개): 21 mm

        def __init__(self, ip):
            pass

        def move(self, w, f):
            if w == 0:                                                  # 닫기: 손잡이(열기 단계)는 8 mm, 그 밖은 지우개 21 mm 를 잡음
                Gripper.width = {"open": 8.0, "pick": 21.0}.get(robot.step, 0.9)   # 손잡이 8 mm·지우개 21 mm, 그 밖(끌기 등)은 빈 손 0.9 mm
            else:
                Gripper.width = float(w)
            robot.grip_events.append(dict(before_segment=len(robot.segments), width_mm=Gripper.width, step=robot.step))
            return Rg2Status(Gripper.width, False, w == 0, False)

        def status(self):
            return Rg2Status(Gripper.width, False, True, False)

        def close(self):
            pass
    ss.Rg2 = Gripper
    srv = object.__new__(ss.SkillServer)
    srv.cfg_dir, srv.params_file, srv.rg2_ip = repo / "config", ss.PARAMS_FILE, "x"
    srv.robot, srv.disp, srv.held, srv.tray = robot, {}, None, {}
    srv.state = sf.MotionState(robot.state, robot.posj)
    srv.move_timeout, srv.joint_vel, srv.joint_acc, srv.reach_tol = 30.0, 20.0, 20.0, 0.5
    real_line = ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None):                 # 단계 이름 기록 + 접촉 흉내
        robot.stage, robot.from_line = stage, True
        if stage != "drag":                                             # 끄는 동안은 누른 접촉을 유지(기준 힘이 같게)
            robot.contact = contact_for(stage, robot.p, posx)
        return real_line(self, goal, posx, vel, stage, watch)
    ss.SkillServer._line = line
    if hasattr(ss.SkillServer, "_spline"):                              # 관절 스플라인(movesj)에도 단계 이름
        real_spline = ss.SkillServer._spline

        def spline(self, goal, points, stage, *a, **k):
            robot.stage, robot.contact, robot.from_line = stage, None, False
            return real_spline(self, goal, points, stage, *a, **k)
        ss.SkillServer._spline = spline
    real_named = ss.SkillServer._named

    def named(self, goal, pose_name, drawer_id=None):                   # 관절 이동에도 단계 이름
        robot.stage, robot.contact, robot.from_line = f"to_{pose_name}", None, False
        return real_named(self, goal, pose_name, drawer_id)
    ss.SkillServer._named = named
    return ss, sf, srv, Gripper


def contact_for(stage, p0, p1):
    """접촉이 있어야 끝나는 직선 이동만: 목표까지 가는 길의 중간쯤에서 힘을 낸다 (실물 힘 값 아님)."""
    if stage in ("press",):
        zc = (p0[2] + p1[2]) / 2
        return lambda p: [0.0, 0.0, 30.0, 0, 0, 0] if p[2] <= zc else None
    return None


def save_trace(robot, repo: Path, out, results, eraser, eraser_after):
    """구간 지표(손끝 10 mm·회전 5°당 최대 관절 변화, ◀ 판정)를 붙여 trace.json 저장 + 표 출력. trace_b_demo.py 도 같이 씀."""
    for s in robot.segments:
        n = max(1, len(s["joints"]) - 1)
        unit = max(s.get("dist_mm", 0.0) / n, s.get("rot_deg", 0.0) / n * 2, 1e-9)
        dq = np.abs(np.diff(np.array(s["joints"]), axis=0)).max() if len(s["joints"]) > 1 else 0.0
        s["amp_deg_per_10mm"] = float(dq / unit * 10) if s["kind"] == "movel" else 0.0
        # ◀ 기준 [실물 대조 10/06]: 튄 구간은 J3 10°·0°(10 mm당 11.8°·63°), 튀지 않은 구간은 J3 25° 이상(10 mm당 12.7°까지).
        #   10 mm당 관절 변화만으로는 가르지 못해 J3·J5(특이점까지 거리)를 주 기준으로, 관절 변화는 아주 클 때(> 20°)만 본다
        s["flag"] = bool(s["kind"] == "movel" and (s["min_abs_j3"] < 15 or s["min_abs_j5"] < 10 or s["amp_deg_per_10mm"] > 20.0))
    sha = (repo / ".sha").read_text().strip() if (repo / ".sha").exists() else ""
    if not sha:
        import subprocess
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    Path(out).write_text(json.dumps(dict(repo=str(repo), repo_sha=sha, results=results, eraser=eraser, eraser_after=eraser_after,
                                         grip_events=robot.grip_events, segments=robot.segments), ensure_ascii=False))
    print(f"\n구간 {len(robot.segments)}개 → {out} (B 코드 {sha or '?'})")
    print("판정: 직선 이동(movel)에서 |J3| < 15° 또는 |J5| < 10° 또는 손끝 10 mm(회전 5°)당 관절 변화 > 20° 이면 ◀ "
          "(10/06 실물: J3 10° 이하에서 튐, 25° 이상은 10 mm당 12.7° 여도 정상)")
    print(f"{'#':>3} {'단계':6s} {'명령':6s} {'stage':22s} {'거리mm':>7s} {'회전°':>6s} {'°/10mm':>7s} {'min|J3|':>7s} {'min|J5|':>7s} {'σmin':>6s} 관절 이동량")
    for s in robot.segments:
        print(f"{s['i']:3d} {s['step']:6s} {s['kind']:6s} {s['stage'][:22]:22s} {s.get('dist_mm', 0):7.1f} {s.get('rot_deg', 0):6.1f} "
              f"{s['amp_deg_per_10mm']:7.2f} {s['min_abs_j3']:7.1f} {s['min_abs_j5']:7.1f} {s['min_sigma']:6.3f} {s['joint_travel_deg']}"
              f"{' ◀' if s['flag'] else ''}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="trace.json")
    ap.add_argument("--steps", default="open,nudge,pick,place,close,home")
    a = ap.parse_args()
    repo = Path(a.repo).resolve()
    robot = KinRobot(HOME_J)
    ss, sf, srv, Gripper = load_server(repo, robot)
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)
    after, results = None, []
    for step in a.steps.split(","):
        robot.step = step
        if step == "open":
            action, params = "drawer_control", {"drawer_id": "drawer_top", "state": "open"}
        elif step == "close":
            action, params = "drawer_control", {"drawer_id": "drawer_top", "state": "close"}
        elif step == "nudge":
            action, params = "nudge_object", {"drawer_id": "drawer_top", "target": ERASER}
        elif step == "pick":
            action, params = "pick_object", {"target": after or ERASER, "approach_offset": [0, 0, 0.1]}
        elif step == "place":
            action, params = "place_object", {"location": "handover_zone"}
        else:
            action, params = "move_to_named_pose", {"pose_name": step}
        n0 = len(robot.segments)
        out, data = sf.run_guarded(lambda: getattr(srv, f"_do_{action}")(goal, json.loads(json.dumps(params))),
                                   stop=robot.stop, get_state=srv.state)
        if step == "nudge" and data and data.get("target_after"):
            after = data["target_after"]
        for s in robot.segments[n0:]:
            s["step"] = step
        results.append(dict(step=step, success=out.success, error=out.error_code, reason=getattr(out, "reason", ""),
                            segments=len(robot.segments) - n0))
        print(f"{step:6s} success={out.success} {out.error_code or ''} {getattr(out, 'reason', '') or ''} (이동 {len(robot.segments) - n0}개)")
        if not out.success:
            break
    save_trace(robot, repo, a.out, results, ERASER, after)

if __name__ == "__main__":
    main()
