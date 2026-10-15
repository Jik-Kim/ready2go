"""skill_server 노드 동작 경로 회귀 테스트 (ROS·로봇 없이 가짜 로봇으로). #83 D·E 리뷰.

ROS 패키지가 없으면(CI의 코어 단계) 필요한 모듈만 이 테스트 안에서 가짜로 넣었다가 끝나면 되돌린다.
"""
import dataclasses
import importlib
import json
import math
import re
import sys
import types
from pathlib import Path

import pytest
import yaml

from ready2go_skills.core import skill_flow as sf
from ready2go_skills.core.rg2_protocol import Rg2Status

REPO = Path(__file__).resolve().parents[4]
# 옆벽(y_max)에 붙은 지우개: 10/07 실측 0.2904 = 그때 폭 0.2937 − 3.3 mm. 서랍 좌표계를 다시 재면 폭이 바뀌므로 저장소 places.yaml 폭 기준으로 둔다 (10/10 다시 교시)
# 물건 높이(mm)는 온톨로지 원본에서 — 높이를 실측으로 고치면(#318 캐러멜 18.5 → 21) 시험 기대값도 같이 따라감
ONTO_H_MM = {k: v["size_m"][2] * 1000.0 for k, v in json.loads((REPO / "knowledge" / "world.jsonld").read_text(encoding="utf-8"))["world"]["items"].items()
             if isinstance(v, dict) and v.get("size_m")}


def _support_mm(reason):
    """pick 결과 reason 의 "받침 NN.N mm" 숫자."""
    m = re.search(r"받침 ([\d.]+) mm", reason)
    assert m, reason
    return float(m.group(1))


WALL_Y = round(yaml.safe_load((REPO / "config" / "places.yaml").read_text(encoding="utf-8"))["drawer_top"]["interior_m"][1] - 0.0033, 4)
ERASER_CORNER = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
                 "pose": {"frame": "drawer_top", "position": [0.0275, WALL_Y, 0.0], "yaw": 0.0, "yaw_valid": True}}   # 10/07 실측 (벽에서 3.3 mm)
ERASER_WALL_CROSS = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,                    # 오른쪽 벽에 가로로 → 가로 넛지 [사용자 10/10]
                     "pose": {"frame": "drawer_top", "position": [0.10, WALL_Y, 0.0], "yaw": math.pi / 2, "yaw_valid": True}}
ERASER_FREE = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
               "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.3, "yaw_valid": True}}


def _stub(monkeypatch, name, **attrs):
    try:
        importlib.import_module(name)
        return
    except ImportError:
        pass
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, name, mod)


@pytest.fixture
def server(monkeypatch):
    if not (REPO / "config" / "places.yaml").exists():
        pytest.skip("저장소 config 없음")
    _stub(monkeypatch, "rclpy")
    _stub(monkeypatch, "rclpy.action", ActionServer=object, CancelResponse=object, GoalResponse=object)
    _stub(monkeypatch, "rclpy.callback_groups", ReentrantCallbackGroup=object)
    _stub(monkeypatch, "rclpy.executors", MultiThreadedExecutor=object)
    _stub(monkeypatch, "rclpy.node", Node=type("Node", (), {}))
    _stub(monkeypatch, "ready2go_interfaces")
    _stub(monkeypatch, "ready2go_interfaces.action",
          Skill=types.SimpleNamespace(Feedback=lambda stage: stage))
    _stub(monkeypatch, "dsr_msgs2")
    _stub(monkeypatch, "dsr_msgs2.srv", **{n: object for n in (
        "GetCurrentPosj GetCurrentPosx GetCurrentTcp GetCurrentTool GetRobotMode GetRobotState GetToolForce "
        "MoveBlending MoveJoint MoveLine MoveSplineJoint MoveSplineTask MoveStop SetRobotMode TaskComplianceCtrl SetDesiredForce ReleaseForce ReleaseComplianceCtrl").split()})
    _stub(monkeypatch, "pymodbus")
    _stub(monkeypatch, "pymodbus.client", ModbusTcpClient=object)
    for m in ("ready2go_skills.adapters.dsr", "ready2go_skills.adapters.rg2", "ready2go_skills.nodes.skill_server"):
        monkeypatch.delitem(sys.modules, m, raising=False)
    ss = importlib.import_module("ready2go_skills.nodes.skill_server")

    real_wait = sf.wait_motion

    def fast_wait(**kw):
        kw.update(settle_s=0.0, sleep=lambda s: None)
        return real_wait(**kw)
    monkeypatch.setattr(sf, "wait_motion", fast_wait)
    clock = {"t": 0.0}                                                  # 가짜 시계 — 기다림(0점·힘 맞추기·좌표 판정)을 실제로 안 기다림

    def fake_sleep(dt):
        clock["t"] += dt
    monkeypatch.setattr(ss, "time", types.SimpleNamespace(sleep=fake_sleep, monotonic=lambda: clock["t"]))

    class Robot:
        def __init__(self):
            self.p = [380.0, -6.5, 300.0, 90.0, -90.0, 180.0]
            self.log, self.path = [], None
            self.force = lambda p: [0.0] * 6
            self.j = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]

        def auto(self):
            return True

        def state(self):
            if self.path:
                self.p = self.path.pop(0)
                return 2
            return 1

        def posx(self):
            return list(self.p)

        def posj(self):
            return list(self.j)

        def tool_force(self):
            return self.force(self.p)

        def stop(self):
            self.path = None
            self.log.append("stop")
            return True

        def movel_async(self, p, vel, acc, rot_vel=30.0, rot_acc=60.0, radius=0.0):
            self.log.append(("movel", p))
            s0 = list(self.p)
            self.path = [[s0[i] + (p[i] - s0[i]) * (k + 1) / 40 for i in range(6)] for k in range(40)]   # 0.2 mm 단위 (누르기 연속 확인)
            return True

        def movej_async(self, j, vel, acc):
            self.log.append(("movej", j))
            self.j = list(j)
            return True

        def moveb_async(self, pts, radii, vel, acc, rot_vel=30.0, rot_acc=60.0):
            self.log.append(("moveb", [list(p) for p in pts], list(radii)))
            self.p = list(pts[-1])
            return True

        def movesj_async(self, pts, vel, acc):
            self.log.append(("movesj", [list(p) for p in pts]))
            self.j = list(pts[-1])
            return True

    class Gripper:
        width, holding, held_width = 99.0, False, 21.0   # held_width: 쥐고 닫았을 때 폭 (지우개 21 mm)

        def __init__(self, ip):
            pass

        def move(self, w, f):
            Gripper.width = (Gripper.held_width if Gripper.holding else 0.9) if w == 0 else w
            return Rg2Status(Gripper.width, False, w == 0, False)

        def status(self):
            return Rg2Status(Gripper.width, False, True, False)

        def close(self):
            pass
    monkeypatch.setattr(ss, "Rg2", Gripper)

    srv = object.__new__(ss.SkillServer)
    srv.cfg_dir, srv.params_file, srv.rg2_ip = REPO / "config", ss.PARAMS_FILE, "x"
    srv.robot, srv.disp, srv.held, srv.tray = Robot(), {"drawer_top": 0.226}, None, {}
    srv.state = sf.MotionState(srv.robot.state, srv.robot.posj)
    srv.move_timeout, srv.joint_vel, srv.joint_acc, srv.reach_tol = 30.0, 20.0, 20.0, 0.5
    srv.get_logger = lambda: types.SimpleNamespace(info=lambda *a: None, warn=lambda *a: None, warning=lambda *a: None, error=lambda *a: None)
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)

    def run(action, params):
        return sf.run_guarded(lambda: getattr(srv, f"_do_{action}")(goal, json.loads(json.dumps(params))),
                              stop=srv.robot.stop, get_state=srv.state)
    # [10/15 기본값 켬] 예전 테스트는 끈 동작(경유점에서 닫고·멈추고·손목 따로)을 검사 — 여기서 끈 값으로 고정하고,
    # 켠 동작은 _with_prm 으로 켜거나 yaml_real(저장소 skills.yaml 그대로)로 검사
    yaml_real = ss._yaml_cached

    def legacy(path, **kw):
        d = yaml_real(path, **kw)
        if path.name == "skills.yaml":
            d = dict(d)
            for k, v in LEGACY_FLAGS.items():
                d[k] = {**(d.get(k) or {}), **v}
        return d
    monkeypatch.setattr(ss, "_yaml_cached", legacy)
    return types.SimpleNamespace(ss=ss, srv=srv, run=run, Gripper=Gripper, yaml_real=yaml_real)


LEGACY_FLAGS = {"motion": {"one_turn": False}, "carry": {"direct": False, "spline": False},
                "transit": {"view_blend_in_drawer": False}, "pick": {"open_on_way": False},
                "place": {"touch_window_mm": 0.0}}


def test_check_only_still_needs_drag_returns_push_limit_without_motion(server):
    """#83 D 리뷰 P1: check_only 재판단에서 아직 끌어야 하면 PUSH_LIMIT, 움직이지 않고 target_after 없음."""
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER, "check_only": True})
    assert not out.success and out.error_code == server.ss.PUSH_LIMIT
    assert data["target_after"] is None and data["pushed"] is False
    assert server.srv.robot.log == []


def test_check_only_graspable_succeeds_with_same_target(server):
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_FREE, "check_only": True})
    assert out.success and data["pushed"] is False and data["target_after"] == ERASER_FREE
    assert server.srv.robot.log == []



def test_check_only_reports_needed_and_plan_code(server, monkeypatch):
    """[E #245 제안] nudge check_only 결과에 넛지 필요(needed)·넛지로도 안 되는 이유(plan_code). 기존 error_code 그대로, 움직이지 않음."""
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER, "check_only": True})
    assert out.error_code == server.ss.PUSH_LIMIT and data["needed"] is True and data["plan_code"] is None
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_FREE, "check_only": True})
    assert out.success and data["needed"] is False and data["plan_code"] is None
    real = server.ss.mp.plan_drag
    monkeypatch.setattr(server.ss.mp, "plan_drag", lambda **k: dataclasses.replace(
        real(**k), needed=False, error_code=server.ss.mp.NO_PUSH_ACCESS, reason="시험: 넛지 못 함"))
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER, "check_only": True})
    assert out.error_code == server.ss.PUSH_LIMIT and data["needed"] is False and data["plan_code"] == server.ss.mp.NO_PUSH_ACCESS
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_FREE})
    assert "needed" not in data                                         # check_only 가 아니면 예전 결과 그대로
    assert server.srv.robot.log == []

def test_drag_then_lift_failure_keeps_safety_code_and_drops_target_after(server, monkeypatch):
    """#37 E 검토 P1: 끌기 성공 뒤 lift 가 정지 미확인이면 그 코드, target_after 없음."""
    contact_z = None

    def force(p):
        return [0.0, 0.0, 8.0 * (contact_z - p[2]) if contact_z is not None and p[2] <= contact_z else 0.0, 0.0, 0.0, 0.0]
    server.srv.robot.force = force
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        nonlocal contact_z
        if stage == "press":
            contact_z = (self.robot.p[2] + posx[2]) / 2          # 내려가는 중간에서 접촉
        if stage == "lift":
            return sf.Outcome(False, sf.STOP_UNCONFIRMED, reason="주입")
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER})
    assert out.error_code == sf.STOP_UNCONFIRMED and data["target_after"] is None


def test_drag_success_gives_target_after_and_pick_accepts_list_approach_offset(server):
    contact = {}

    def force(p):                                                       # 위치로 누르면 1 mm 에 약 8 N [실측 10/06: 2 → 10 N]
        z = contact.get("z")
        return [0.0, 0.0, 8.0 * (z - p[2]) if z is not None and p[2] <= z else 0.0, 0.0, 0.0, 0.0]
    server.srv.robot.force = force
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        if stage == "press":
            contact["z"] = (self.robot.p[2] + posx[2]) / 2
        if stage == "drag":
            contact["drag"] = (list(self.robot.p), list(posx))
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    server.ss.SkillServer._line = line
    try:
        out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_WALL_CROSS})
    finally:
        server.ss.SkillServer._line = real_line
    assert out.success and data["pushed"] is True
    prm, place = server.srv.prm(), server.srv.places()["drawer_top"]
    g = dict(prm["gripper"], wall_offset_mm=prm["drawer_wall_offset_mm"]["drawer_top"],
             wall_tcp_min_mm=prm["drag"]["wall_tcp_min_by_drawer_mm"]["drawer_top"], axis_grasp=True,
             max_open_mm=prm["pick"]["max_open_width_m"] * 1000.0, tilt_align_deg=prm["pick"]["tilt_align_deg"],
             front_tilt_within_mm=prm["pick"]["front_tilt_within_mm"])
    plan = server.ss.mp.plan_drag(target=ERASER_WALL_CROSS, size_m=server.srv.item("eraser")[0], interior_m=place["interior_m"], g=g, drag=prm["drag"])
    assert prm["drag"]["shift_mm"] is None and plan.shift_y_m < 0 and plan.axis == "y"   # 가로면 y 넛지 → 긴 변 [사용자 10/10]
    assert data["target_after"]["pose"]["position"][1] == pytest.approx(WALL_Y + plan.shift_y_m, abs=1e-3)   # 누른 z 그대로 그만큼만
    start, end = contact["drag"]
    assert end[2] == pytest.approx(start[2], abs=0.06)                   # 수평으로만 끔 (z 섞이면 더 눌려 15 N 초과, 10/06 저녁). 0.1 mm 올리기 도착 판정 0.05 mm
    assert contact["z"] - 2.5 / 8.0 <= start[2] <= contact["z"] - 1.0 / 8.0   # 5 N 에서 멈춰 확인 → 0.1 mm 씩 올려 1.5~2.5 N 근처에서 끔 [사용자 10/07]
    assert "N 으로 눌러" in out.reason
    server.srv.robot.force = lambda p: [0.0] * 6
    server.Gripper.holding, server.Gripper.held_width = True, 52.0     # 가로 → 긴 변 양끝 [사용자 10/10]
    route = server.srv.poses()["carry_line"]["drawer_top"]
    server.srv.robot.log.clear()
    out, data = server.run("pick_object", {"target": data["target_after"], "approach_offset": [0, 0, 0.1]})
    server.Gripper.holding = False
    assert out.success and data["grasp_ok"] is True
    kind, pts, radii = server.srv.robot.log[-1]                         # 집고 수직으로 테두리 위 → 경유점 1(서랍 중앙)로 수평, 블렌딩 한 번 [사용자 10/08]
    top = server.srv.places()["drawer_top"]
    travel = 1000.0 * (top["tf"]["translation_m"][2] + top["interior_m"][2]) + server.srv.prm()["transit"]["in_drawer_clear_mm"]
    assert kind == "moveb" and pts[-1][:3] == route[0][:3] and pts[0][2] == pytest.approx(max(travel, route[0][2]))
    assert pts[-1][3:] == pts[0][3:]                                    # 경유점까지 손목은 잡은 방향 그대로 [실측 PC2 10/10]
    assert travel - 0.5 <= route[0][2] <= travel + 5.0                  # 경유점 1 = 테두리 위 조금 (z 300 안 올림) — 교시값이 테두리 + 5 mm 보다 조금 높을 수 있음 [실측 10/10 +6.6 mm]
    server.srv.robot.log.clear()
    out, data = server.run("place_object", {"location": "handover_zone"})
    log = server.srv.robot.log
    assert out.success and data["slot"] == "handover_zone_1"
    if log[0][0] == "movej":                                            # 경유점 1 에서 J6 로 놓는 손목 방향 먼저 (있으면)
        log.pop(0)
    kind, pts, radii = log[0]                                           # 2·3·4 → 칸 위(4번 높이) → 놓는 높이 1 cm 위, 직선 블렌딩 한 번 [사용자 10/10]
    assert kind == "moveb" and [q[:3] for q in pts[:3]] == [q[:3] for q in route[1:]] and len(pts) == 5
    assert all(q[3:] == pts[-1][3:] for q in pts)                      # 경유점은 위치만 — 손목은 놓는 방향 그대로 [실측 PC2 10/10]
    seq = [route[0]] + pts                                              # 반지름 100 mm [사용자 10/08], 구간이 짧으면 앞뒤 구간 절반의 90% — 절반 그대로면 제어기 거부 [실측 PC2 10/08]
    half = [min(math.dist(seq[k][:3], seq[k + 1][:3]), math.dist(seq[k + 1][:3], seq[k + 2][:3])) / 2.0 for k in range(4)]
    assert radii == pytest.approx([min(100.0, 0.9 * h) for h in half] + [0.0]) and radii[0] < 100.0   # 1→2 짧은 구간은 절반의 90%
    assert pts[3][2] == pytest.approx(route[-1][2]) and pts[4][:2] == pytest.approx(pts[3][:2]) and pts[4][2] < pts[3][2]   # 칸 위에서 멈추지 않고 내려감
    assert log[1][0] == "movel" and log[1][1][:2] == pytest.approx(pts[3][:2]) and log[1][1][2] < pts[4][2]   # 마지막 1 cm 살포시 내려놓기
    assert log[2][0] == "movel"                                         # 놓은 뒤 위로
    log.clear()
    cp = server.srv.prm()["drawer_open_close"]["close_push"]["drawer_top"]   # 위 칸 닫기 = 45° 기울여 앞판 중앙 밀기 [사용자 10/08]
    start_x = list(cp["start_posx"])                                     # 시작 자세 도착 TCP (= params start_posx, 10/10 10 mm 앞으로)
    real_movej = server.srv.robot.movej_async

    def movej(j, v, a):
        ok = real_movej(j, v, a)
        if list(j) == list(cp["start_posj"]):
            server.srv.robot.p = list(start_x)
        return ok
    server.srv.robot.movej_async = movej
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_top", "state": "close"})
    assert out.success
    assert log[0] == ("movej", cp["start_posj"])                        # 트레이 쪽에서 홈 안 거치고 시작 자세로 바로 (관절 이동)
    closed_y = cp["end_posx"][1] - 2.0                                  # 닫힌 앞판에 닿는 y + 2 mm 더
    assert log[1][1][1] == pytest.approx(closed_y + server.srv.prm()["drawer_open_close"]["push_slow_last_mm"], abs=0.5)   # 빠르게 → 마지막 push_slow_last_mm(10/10 10 mm) 는 천천히 (두 번)
    assert log[2][1][1] == pytest.approx(closed_y, abs=0.5)
    assert log[1][1][3:] == start_x[3:] and log[1][1][2] == pytest.approx(start_x[2], abs=0.5)   # 손목·높이 그대로 서랍 축(≈ y)으로만
    assert log[1][1][0] == pytest.approx(start_x[0], abs=1.0)           # 서랍 축이 base y 에서 조금 기울어 x 는 1 mm 안


def test_named_pose_from_low_non_drawer_spot_lifts_first(server):
    """#83 D 재검토 P1: 트레이 등 서랍 밖 낮은 곳(z 100)에서 home → 먼저 수직 상승(movel), 그 뒤 movej."""
    server.srv.robot.p = [0.0, 0.0, 100.0, 0.0, 180.0, 0.0]
    out, _ = server.run("move_to_named_pose", {"pose_name": "home"})
    log = server.srv.robot.log
    assert out.success
    assert log[0][0] == "movel" and log[0][1][2] == pytest.approx(150.0) and log[1][0] == "movej"


def test_named_pose_from_high_spot_goes_straight(server):
    server.srv.robot.p = [380.0, -6.5, 300.0, 90.0, -90.0, 180.0]
    out, _ = server.run("move_to_named_pose", {"pose_name": "home"})
    assert out.success and server.srv.robot.log[0][0] == "movej"


@pytest.mark.parametrize("start, lifts", [
    ([424.181, -294.601, 363.507, 0.0, 180.0, 0.0], False),     # 탑뷰 (z 363 > high_z) — 그 높이 그대로 빼냄
    ([380.0, -216.0, 253.8, 0.0, 180.0, 0.0], True),            # 서랍 안 낮은 곳 — high_z 325 로 먼저 올림
])
def test_named_home_from_over_drawer_exits_over_front_first(server, start, lifts):
    """[실측 10/07 PC2] 탑뷰 → 닫기(홈 경유)에서 바로 movej 하면 열린 앞판·손잡이를 쳐서 충돌 알람 7060.
    서랍 위에서 서랍 밖 자세로 갈 때는 앞판 위 높이로 서랍 밖(exit_y)까지 수평으로 뺀 뒤 movej."""
    tr = server.srv.prm()["transit"]
    server.srv.robot.p = list(start)
    out, _ = server.run("move_to_named_pose", {"pose_name": "home"})
    log = server.srv.robot.log
    assert out.success
    moves = [e for e in log if e[0] in ("movel", "movej")]
    z = max(start[2], tr["high_z_mm"])
    if lifts:
        assert moves[0][0] == "movel" and moves[0][1][:3] == pytest.approx([start[0], start[1], z])
        moves = moves[1:]
    assert moves[0][0] == "movel" and moves[0][1][:3] == pytest.approx([start[0], tr["exit_y_mm"], z])
    assert moves[1][0] == "movej" and len(moves) == 2


def test_named_top_view_from_over_drawer_does_not_exit(server):
    """서랍 위 → 탑뷰(끌기 뒤 다시 보기)는 서랍 밖으로 빼지 않음 — safe_z 로만 올리고 movej (10/07 실물 동작 그대로)."""
    server.srv.robot.p = [380.0, -216.0, 253.8, 0.0, 180.0, 0.0]
    out, _ = server.run("move_to_named_pose", {"pose_name": "drawer_top_view", "drawer_id": "drawer_top"})
    log = server.srv.robot.log
    assert out.success
    assert log[0][0] == "movel" and log[0][1][1] == pytest.approx(-216.0) and log[0][1][2] == pytest.approx(300.0)
    assert log[1][0] == "movej"


@pytest.mark.parametrize("flag, held, radius", [
    (False, False, 0.0),             # 기본: safe_z 에서 서고 관절 이동 (지금 동작 그대로)
    (True, False, 0.45 * 25.0),      # 켬·빈손: 경유점 1(z 275) → 300 올리기 끝 45% 에서 이음
    (True, True, 0.0),               # 켬이어도 쥔 채면 지금처럼 멈췄다 감
])
def test_top_view_from_waypoint_blends_only_when_flag_and_empty(server, monkeypatch, flag, held, radius):
    """[사용자 10/15 "중앙 경유점 → z 위로 → 뷰, 약간 늦어"] transit.view_blend_in_drawer."""
    _with_prm(server, monkeypatch, transit={"view_blend_in_drawer": flag})
    rb = server.srv.robot
    rb.p = [380.0, -216.0, 275.0, 0.0, 180.0, 0.0]
    if held:
        server.srv.held = {"id": "eraser#1", "class": "eraser", "width_m": 0.02}
    radii, ml = [], rb.movel_async
    rb.movel_async = lambda p, vel, acc, rot_vel=30.0, rot_acc=60.0, radius=0.0: (radii.append(radius), ml(p, vel, acc, rot_vel, rot_acc, radius))[1]
    out, _ = server.run("move_to_named_pose", {"pose_name": "drawer_top_view", "drawer_id": "drawer_top"})
    moves = [e for e in rb.log if e[0] in ("movel", "movej")]
    assert out.success
    assert moves[0][0] == "movel" and moves[0][1][2] == pytest.approx(300.0) and moves[-1][0] == "movej"
    assert radii[0] == pytest.approx(radius)


def test_open_drawer_without_posx_fails_before_any_command(server):
    """#83 E 검토 P1: 서랍 열기에서 현재 좌표를 못 읽으면 그리퍼·관절 이동 없이 STATE_UNKNOWN."""
    server.srv.disp = {}
    server.srv.robot.posx = lambda: None
    server.Gripper.width = 55.0
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_top", "state": "open"})
    assert not out.success and out.error_code == sf.STATE_UNKNOWN
    assert server.srv.robot.log == [] and server.Gripper.width == 55.0


def test_runner_open_path_lifts_before_ready_and_does_not_redo_it(server):
    """10/06 통합 실물: Runner open_drawer = move_to_named_pose(drawer_approach) → drawer_control(open).
    홈(z 195)에서 ready 로 바로 관절 이동하면 손잡이보다 낮게 지나감 → 먼저 z 300, drawer_control 은 ready 를 다시 하지 않음."""
    ready = server.srv.poses()["drawer_approach"]["drawer_top"]
    server.srv.disp = {}
    server.srv.robot.p = [368.0, 6.5, 195.0, 0.0, 180.0, 0.0]
    out, _ = server.run("move_to_named_pose", {"pose_name": "drawer_approach", "drawer_id": "drawer_top"})
    log = server.srv.robot.log
    assert out.success
    assert log[0][0] == "movel" and log[0][1][2] == pytest.approx(300.0) and log[1] == ("movej", ready)
    log.clear()
    server.Gripper.holding, server.Gripper.held_width = True, 7.9                 # 손잡이 꽉 잡은 폭 [실측 B 10/06]
    out, data = server.run("drawer_control", {"drawer_id": "drawer_top", "state": "open"})
    server.Gripper.holding = False
    assert out.success and data["drawer_displacement"] >= 0.9 * data["open_distance_m"] > 0   # open_drawer verify 근거 [P2 4절]
    assert log and log[0][0] == "movel" and log[0][1][1] == pytest.approx(server.srv.prm()["drawer_open_close"]["handle_grasp_posx"]["drawer_top"][1] + server.srv.prm()["drawer_open_close"]["handle_grasp_back_mm"], abs=0.5)   # 손잡이까지 한 번에 (1 cm 전 멈춤 없음, 10/07), 실측보다 handle_grasp_back_mm 덜 (10/08 4 → 10/10 1)
    assert ("movej", ready) not in log


@pytest.mark.parametrize("y", [0.2925, 0.2895, 0.2827])
def test_pick_next_to_side_wall_refused_without_motion(server, y):
    """#83 A 요청(#80 D P1 후속): 끌기 없이 벽에 붙은 지우개를 바로 집으면 움직이기 전에 WALL_TOO_CLOSE."""
    t = json.loads(json.dumps(ERASER_CORNER))
    t["pose"]["position"] = [0.1769, y, 0.0]
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
    assert not out.success and out.error_code == server.ss.WALL_TOO_CLOSE
    assert server.srv.robot.log == []


def test_named_pose_over_joint_limit_refused_without_motion(server):
    """J5 펜던트 안전 제한 ±135° [사용자 10/06] → params 133° 넘는 목표는 움직이기 전 JOINT_LIMIT."""
    server.srv.poses = lambda: {"home": {"joints_deg": [0.0, 0.0, 90.0, 0.0, 134.0, 0.0]}}
    out, _ = server.run("move_to_named_pose", {"pose_name": "home"})
    assert not out.success and out.error_code == server.ss.JOINT_LIMIT and server.srv.robot.log == []


def test_joint_limit_watch_stops_motion(server):
    server.srv.robot.j = [0.0, 0.0, 90.0, 0.0, 133.5, 0.0]                  # 이동 중 133° 넘음 (도착 전)
    server.srv.robot.movej_async = lambda j, v, a: True
    out, _ = server.run("move_to_named_pose", {"pose_name": "drawer_top_view", "drawer_id": "drawer_top"})
    assert not out.success and out.error_code == server.ss.JOINT_LIMIT


def test_line_stopped_short_names_stage_and_distance_left(server):
    """10/06 저녁 nudge NOT_REACHED 0.3 s — 어느 이동인지 로그에 없었음 → 이유에 단계·멈춘 곳·남은 거리."""
    r = server.srv.robot
    real = r.movel_async

    def short(p, *a, **k):
        real(p, *a, **k)
        r.path = r.path[:20]                                    # 절반 가고 멈춤
        return True
    r.movel_async = short
    goal = __import__("types").SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)
    target = [380.0, -6.5, 290.0, 90.0, -90.0, 180.0]
    out = server.srv._line(goal, target, 10.0, "drag")
    assert out.error_code == sf.NOT_REACHED and out.reason.startswith("[drag]") and "남은 5.0 mm" in out.reason


def test_relax_gives_up_with_push_blocked_when_force_stays_high(server):
    """닿음 확인 뒤 정해진 칸만큼 올려도 2.5 N 넘으면 끌지 않고 PUSH_BLOCKED, 위로 빠짐."""
    server.srv.prm = (lambda real: (lambda: {**real(), "drag": {**real()["drag"], "relax_max_steps": 2}}))(server.srv.prm)
    server.srv._force_still = lambda s: [0.0, 0.0, 20.0, 0.0, 0.0, 0.0]
    server.srv._tare = lambda settle_s=None: [0.0] * 6
    contact = {}
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        if stage == "press":
            contact["z"] = (self.robot.p[2] + posx[2]) / 2
        if stage == "drag":
            contact["drag"] = True
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    server.srv.robot.force = lambda p: [0.0, 0.0, 20.0 if contact.get("z") and p[2] <= contact["z"] else 0.0, 0.0, 0.0, 0.0]
    server.ss.SkillServer._line = line
    try:
        out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER})
    finally:
        server.ss.SkillServer._line = real_line
    hi = server.srv.prm()["drag"]["drag_force_n"][1]
    assert out.error_code == server.ss.PUSH_BLOCKED and f"20.0 N > {hi:g} N" in out.reason
    assert "drag" not in contact and data["target_after"] is None
    attempts = server.srv.prm()["drag"]["press_attempts"]
    lifts = [e for e in server.srv.robot.log if e[0] == "movel"]
    assert sum(1 for e in lifts if e[1][2] < contact["z"]) >= attempts      # 끌기 전 실패 → 같은 자리에서 press_attempts 번 누름 [사용자 10/07]
    relax = [e for e in server.srv.robot.log if e[0] == "movel"][-3:-1]   # 마지막 시도: 0.1 mm 씩 두 번 올리고 → 위로 빠짐
    assert relax[1][1][2] - relax[0][1][2] == pytest.approx(0.1)


def test_press_spike_while_moving_is_rechecked_still_and_resumed(server, monkeypatch):
    """내려가다 5 N 넘으면 바로 멈춤 → 멈춘 채 3 번 모두 5 N 넘어야 닿음. 아니면(튄 값) 그 자리에서 다시 내려감 [사용자 10/07]."""
    contact, spiked = {}, {"done": False}

    def force(p):
        z = contact.get("z")
        if z is not None and not spiked["done"] and p[2] <= z + 1.0:          # 닿기 1 mm 전 한 번 튐
            spiked["done"] = True
            return [0.0, 0.0, 6.0, 0.0, 0.0, 0.0]
        return [0.0, 0.0, 8.0 * (z - p[2]) if z is not None and p[2] <= z else 0.0, 0.0, 0.0, 0.0]
    server.srv.robot.force = force
    stages = []
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        stages.append(stage)
        if stage == "press":
            contact["z"] = (self.robot.p[2] + posx[2]) / 2
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER})
    assert out.success and "press:2" in stages and spiked["done"]


def test_press_force_cap_stops_even_in_ignore_window(server, monkeypatch):
    """출발 2 mm 무시 구간에서 닿아도 8 N 상한이면 바로 멈춤 — z 14 N 이면 서랍이 앞으로 넘어감 [사용자 10/07]."""
    contact, stop_z = {}, {}

    def force(p):
        z = contact.get("z")
        return [0.0, 0.0, 8.0 * (z - p[2]) if z is not None and p[2] <= z else 0.0, 0.0, 0.0, 0.0]
    server.srv.robot.force = force
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        if stage == "press":
            contact["z"] = self.robot.p[2] - 0.5                 # 출발 0.5 mm 아래 (예상보다 4.5 mm 높음)
        out = real_line(self, goal, posx, vel, stage, watch, **kw)
        if stage == "press":
            stop_z["z"] = self.robot.p[2]
        return out
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER})
    assert contact["z"] - stop_z["z"] <= 8.0 / 8.0 + 0.25                  # 무시 구간에서 닿아도 8 N 근처에서 멈춤 (가짜 경로 한 칸 여유)


def test_slow_press_is_not_ended_early_when_joint_state_looks_still(server, monkeypatch):
    """10/07 실물: 1 mm/s 누르기를 관절 변화로는 '멈춤'으로 봐 0.3 s 만에 NOT_REACHED(정지 명령 없음) → 좌표로 판단해야 끝까지 감."""
    r = server.srv.robot
    server.srv.state = lambda: 1                                       # 관절·상태로는 늘 '멈춤' (실물 느린 이동)
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)
    target = list(r.p)
    target[2] -= 2.0
    real = r.movel_async

    def slow(p, *a, **k):                                              # 위치는 조금씩 계속 바뀜
        real(p, *a, **k)
        path = r.path
        r.path = None
        r.slow = path
        return True
    r.movel_async = slow
    real_posx = r.posx

    def posx():
        if getattr(r, "slow", None):
            r.p = r.slow.pop(0)
        return real_posx()
    r.posx = posx
    assert server.srv._line_slow(goal, target, 1.0, "press") is None and r.p[2] == pytest.approx(target[2], abs=0.05)
    assert "stop" not in r.log


def test_slow_press_that_really_stops_short_is_halted(server):
    r = server.srv.robot
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)
    r.movel_async = lambda *a, **k: True                               # 명령은 받았는데 안 움직임
    target = list(r.p)
    target[2] -= 2.0
    out = server.srv._line_slow(goal, target, 1.0, "press")
    assert out.error_code == sf.NOT_REACHED and out.reason.startswith("[press]") and "stop" in r.log


def test_relax_step_stall_keeps_going_instead_of_failing(server):
    """[실측 10/07 PC2] 눌린 채 0.1 mm 올리기가 0.1 mm 남기고 멈춰 NOT_REACHED → 끌기 실패.
    힘 맞추기 한 칸의 NOT_REACHED 는 다음 칸으로 넘어가고(목표 누적), 안전 코드는 그대로 멈춤."""
    srv, d = server.srv, server.srv.prm()["drag"]
    warns = []
    srv.get_logger = lambda: types.SimpleNamespace(warn=warns.append)
    mid = sum(d["drag_force_n"]) / 2.0                                  # 끄는 힘 범위 안 [10/10 0.5~1.2 N]
    forces = iter([[0, 0, 4.0, 0, 0, 0], [0, 0, 4.0, 0, 0, 0], [0, 0, mid, 0, 0, 0]])
    srv._force_still = lambda s: next(forces)
    steps = []

    def step(goal, posx, stage):
        steps.append(round(posx[2], 2))
        return sf.Outcome(False, sf.NOT_REACHED, reason=f"[{stage}] 멈춤") if len(steps) == 1 else None
    srv._step = step
    pressed = [522.3, -135.6, 216.5, 0.4, 160.0, 0.0]
    bad, p, n = srv._relax(types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None),
                           pressed, [0.0] * 6, d)
    assert bad is None and n == mid and len(warns) == 1
    assert steps == [round(216.5 + d["relax_step_mm"], 2), round(216.5 + 2 * d["relax_step_mm"], 2)]   # 두 번째 칸은 0.2 mm
    srv._step = lambda goal, posx, stage: sf.Outcome(False, "ESTOP", reason="비상정지")
    srv._force_still = lambda s: [0, 0, 4.0, 0, 0, 0]
    bad, _, _ = srv._relax(types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None),
                           pressed, [0.0] * 6, d)
    assert bad.error_code == "ESTOP"


def test_relax_stall_then_drag_starts_from_actual_stop_not_command(server):
    """#135 E 리뷰: 힘 맞추기 한 칸이 안 움직였는데(NOT_REACHED 허용) 다음 힘이 범위에 들면,
    끌기는 명령 누적 좌표(+0.1 mm)가 아니라 실제 멈춘 z 그대로 수평으로."""
    srv = server.srv
    contact = {}

    def force(p):
        z = contact.get("z")
        return [0.0, 0.0, 8.0 * (z - p[2]) if z is not None and p[2] <= z else 0.0, 0.0, 0.0, 0.0]
    srv.robot.force = force
    mid = sum(srv.prm()["drag"]["drag_force_n"]) / 2.0
    forces = iter([[0, 0, 4.0, 0, 0, 0], [0, 0, mid, 0, 0, 0]])     # 첫 칸 뒤 힘이 범위 안 (실물: 멈춘 사이 힘이 풀림)
    srv._force_still = lambda s: next(forces)
    srv._step = lambda goal, posx, stage: sf.Outcome(False, sf.NOT_REACHED, reason=f"[{stage}] 0.1 mm 남기고 멈춤")   # 로봇 안 움직임
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        if stage == "press":
            contact["z"] = (self.robot.p[2] + posx[2]) / 2
        if stage == "drag":
            contact["drag"] = (list(self.robot.p), list(posx))
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    server.ss.SkillServer._line = line
    try:
        out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER})
    finally:
        server.ss.SkillServer._line = real_line
    assert out.success
    start, end = contact["drag"]
    assert end[2] == pytest.approx(start[2], abs=1e-6)                  # 실제 멈춘 z 그대로 (명령 +0.1 mm 아님)


def test_pick_goes_through_drag_down_like_nudge(server):
    """[사용자 10/07 저녁] 탑뷰에서 목표 위로 바로 가면 특이점 → 넛지와 같은 길: drag_down movej → y 맞추며 목표 위(블렌딩)."""
    srv = server.srv
    down = srv.poses()["drag_down"]["drawer_top"]
    srv.robot.p = [424.181, -294.601, 363.507, 0.0, 180.0, 0.0]        # 탑뷰
    server.Gripper.width = 99.0                                         # 앞 실행에서 벌어진 채 (놓기 뒤 등)
    real_grip = srv._grip
    srv._grip = lambda w, f: srv.robot.log.append(("grip", w)) or real_grip(w, f)
    t = json.loads(json.dumps(ERASER_FREE))
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
    log = srv.robot.log
    assert log.index(("grip", 0)) < log.index(("movej", down))          # 서랍 안 경유점 전에 닫음 [#136 PM 리뷰]
    assert any(e[0] == "grip" and e[1] > 0 for e in log[log.index(("movej", down)):])   # 목표 위에서 벌림
    moves = [e for e in log if e[0] in ("movel", "movej", "moveb")]
    assert ("movej", down) in moves
    i = moves.index(("movej", down))
    assert not any(e[0] == "movel" for e in moves[:i])                 # 탑뷰에서 먼저 내려가는 직선(z 300) 없음
    blend = next(e for e in moves[i + 1:] if e[0] == "moveb")           # (손목 각도가 다르면 사이에 J6 만 돌리는 movej) [10/10]
    assert all(e[0] == "movej" for e in moves[i + 1:moves.index(blend)])
    assert blend[0] == "moveb" and len(blend[1]) == 2                   # y 맞추기 → 목표 위, 한 번에
    assert blend[1][0][1] == pytest.approx(blend[1][1][1])              # 첫 점 = 목표 y
    assert blend[1][1][2] < 300.0                                       # safe_z(300) 로 올리지 않음



def test_pick_skips_drag_down_when_already_there(server):
    """[E #245 제안] 집기 시작 때 실측 관절이 이미 경유점(pick.at_waypoint_tol_deg 안)이면 경유점 movej 를 다시 보내지 않음.
    Runner 기록이 아니라 실제 관절값으로 판단, 그리퍼 닫기는 그대로."""
    srv = server.srv
    down = srv.poses()["drag_down"]["drawer_top"]
    srv.robot.j = [v + 0.2 for v in down]                              # 경유점 0.2° 안
    srv.robot.p = [383.495, -214.323, 275.066, 140.290, 179.999, 140.293]
    real_grip = srv._grip
    srv._grip = lambda w, f: srv.robot.log.append(("grip", w)) or real_grip(w, f)
    out, _ = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    assert ("movej", down) not in srv.robot.log and ("grip", 0) in srv.robot.log
    assert any(e[0] == "moveb" for e in srv.robot.log)                  # 목표로는 그대로 감

HAMMER = {"id": "toy_hammer#1", "class": "toy_hammer", "top_z": 0.025,
          "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}


@pytest.mark.parametrize("width, ok", [(15.3, True), (15.7, True), (9.6, False), (21.0, False)])
def test_hammer_grasp_judged_by_handle_width_not_bbox(server, width, ok):
    """#43: 망치 외접박스 짧은 변은 75 mm(머리)라 손잡이(12.5 mm)를 잡으면 WIDTH_MISMATCH 였음 → pick.grasp_width_m 으로 판정.
    벌림은 손잡이 폭 + 13 mm (pick.open_by_grasp_width [사용자 10/11], 전에는 짧은 변 75 + 13). 10 mm 이하는 성공 아님 [사용자 결정 10/08].
    손잡이 폭 15.5 [실측 PC2 10/11 가로 15.3·세로 15.7, 예전 12.5]."""
    server.Gripper.holding, server.Gripper.held_width = True, width
    try:
        srv = server.srv
        real_grip, grips = srv._grip, []
        srv._grip = lambda w, f: grips.append(w) or real_grip(w, f)
        out, res = server.run("pick_object", {"target": json.loads(json.dumps(HAMMER)), "approach_offset": [0, 0, 0.1]})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out.success is ok and res["grasp_ok"] is ok
    assert 28.5 in [round(w, 1) for w in grips] and 88.0 not in [round(w, 1) for w in grips]   # 벌림 = 15.5 + 13 mm
    if not ok:
        assert out.error_code == server.ss.GRASP_FAILED and "기대 15.5 mm" in out.reason


def test_pick_floor_10mm_even_if_bbox_short_side_matches(server):
    """[사용자 결정 10/08, #43] 집기 성공 하한 10 mm — 빈손·놓침 2 mm 와 별개 값."""
    g = server.srv.prm()["gripper"]
    assert g["pick_min_width_m"] == pytest.approx(0.010) and g["min_width_m"] == pytest.approx(0.002)


def test_bad_grasp_width_refused_before_motion(server, monkeypatch):
    """짧은 변(75 mm)보다 큰 잡는 폭(item_grasp.yaml grasp_width_m)은 설정 오류 — 움직이기 전에 거부."""
    srv = server.srv
    real = server.ss._yaml_cached

    def cached(path, **kw):
        d = real(path, **kw)
        if path.name == "item_grasp.yaml":
            d = {**d, "toy_hammer": {**d["toy_hammer"], "grasp_width_m": 0.2}}
        return d
    monkeypatch.setattr(server.ss, "_yaml_cached", cached)
    out, _ = server.run("pick_object", {"target": json.loads(json.dumps(HAMMER)), "approach_offset": [0, 0, 0.1]})
    assert out.error_code == "SKILL_EXCEPTION" and "grasp_width_m" in out.reason
    assert srv.robot.log == ["stop"]                                    # 이동·그리퍼 명령 없음 (예외 뒤 정지 요청만, plan 오류와 같음)


def _stacked_eraser(top_z):
    t = json.loads(json.dumps(ERASER_FREE))
    t["top_z"] = top_z
    return t


def test_stacked_eraser_picked_on_support_and_remembered_from_own_bottom(server, monkeypatch):
    """[사용자 10/09, P2 망치 25 + 캐러멜 18.5 위 지우개] top_z − 높이 = 받침 43.5 mm 위에서 집음.
    놓을 때 높이는 물체 자기 바닥 기준(바닥에 놓음)."""
    srv, real, seen = server.srv, server.ss.SkillServer._line, []

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        seen.append((stage, posx[2]))
        return real(self, goal, posx, vel, stage, watch, **kw)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    server.Gripper.holding = True
    try:
        floor, _ = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
        floor_held = dict(srv.held)
        seen[:], srv.held = [], None                                    # 놓았다고 치고 다시 집기
        out, data = server.run("pick_object", {"target": _stacked_eraser(0.0115 + 0.0435), "approach_offset": [0, 0, 0.1]})
    finally:
        server.Gripper.holding = False
    assert floor.success and out.success and "받침 43.5 mm" in out.reason and data["grasp_ok"]
    assert srv.held["tcp_above_floor_m"] == pytest.approx(floor_held["tcp_above_floor_m"], abs=1e-4)   # 받침 위 같은 높이로 잡음 (놓을 땐 바닥 기준)


@pytest.mark.parametrize("allow, top_z", [(True, 0.0712), (False, 0.055)])
def test_stack_too_high_or_disabled_refused_before_motion(server, monkeypatch, allow, top_z):
    """윗면이 테두리(71.1) − 10 mm 를 넘거나, allow_stacked false(P1)면 움직이기 전 NOT_ON_FLOOR."""
    srv, real = server.srv, server.srv.prm

    def prm():
        p = real()
        p["pick"]["allow_stacked"] = allow
        return p
    monkeypatch.setattr(srv, "prm", prm)
    out, _ = server.run("pick_object", {"target": _stacked_eraser(top_z), "approach_offset": [0, 0, 0.1]})
    assert out.error_code == "NOT_ON_FLOOR" and srv.robot.log == []


def _scan_with(target, *others):
    return {"target_found": True, "target": target, "visible_count": 1 + len(others), "candidates": list(others)}


CARAMEL_NEXT = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.0185,
                "pose": {"frame": "drawer_top", "position": [0.10, 0.21, 0.0], "yaw": 0.0, "yaw_valid": True}}


def test_pick_refused_before_motion_when_neighbor_in_finger_footprint(server):
    """[사용자 10/09 랜덤 배치] 캐러멜이 지우개 긴 변 끝 쪽 6 cm(중심) — 벌린 손가락 자리(긴 변 양끝 [사용자 10/10])와 겹침
    → 움직이기 전 NEIGHBOR_TOO_CLOSE."""
    t = json.loads(json.dumps(ERASER_FREE))
    end = json.loads(json.dumps(CARAMEL_NEXT))
    end["pose"]["position"][:2] = [0.16, 0.15]
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1], "scan": _scan_with(t, end)})
    assert out.error_code == server.ss.NEIGHBOR_TOO_CLOSE and "caramel_box#1" in out.reason and server.srv.robot.log == []


def test_pick_with_far_neighbor_and_bad_scan(server):
    t = json.loads(json.dumps(ERASER_FREE))
    far = json.loads(json.dumps(CARAMEL_NEXT))
    far["pose"]["position"][1] = 0.26
    other = json.loads(json.dumps(CARAMEL_NEXT))
    other["pose"]["frame"] = "drawer_bottom"                            # 다른 서랍 촬영 → BAD_PARAMS (움직이기 전)
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1], "scan": _scan_with(t, other)})
    assert out.error_code == "BAD_PARAMS" and server.srv.robot.log == []
    server.Gripper.holding = True
    try:
        out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1], "scan": _scan_with(t, far)})
    finally:
        server.Gripper.holding = False
    assert out.success


def test_nudge_refused_when_drag_path_hits_neighbor(server):
    """옆벽(y 294) 지우개를 −y 로 40 mm 끌 때 그 길에 캐러멜 → 움직이기 전 NEIGHBOR_TOO_CLOSE."""
    t = json.loads(json.dumps(ERASER_CORNER))
    cara = json.loads(json.dumps(CARAMEL_NEXT))
    cara["pose"]["position"] = [0.0375, 0.225, 0.0]
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "scan": _scan_with(t, cara)})
    assert out.error_code == server.ss.NEIGHBOR_TOO_CLOSE and data["target_after"] is None and server.srv.robot.log == []


def test_side_wall_offset_lets_33mm_drag_be_picked_but_not_30mm(server):
    """10/07: 오른쪽 옆벽은 서랍 경계보다 7.1 mm 바깥 [실측] → 33 mm 끈 지우개는 집기 통과, 30 mm 는 거부 (움직이지 않음)."""
    t = json.loads(json.dumps(ERASER_CORNER))
    t["pose"]["position"][1] = WALL_Y - 0.030
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
    assert out.error_code == server.ss.WALL_TOO_CLOSE and server.srv.robot.log == []


def test_lift_then_joint_move_without_stop_and_fallback_when_rejected(server):
    """10/07 사용자 "z 올리고 탑뷰 가기 전 멈춤 없이": 올리기는 radius 로 보내고 끝 안에서 관절 이동 (탑뷰는 50 mm, 10/08 "올라가기·회전 같이 끝나게").
    관절 이동이 거부되면(올라가는 중) 다 올라간 뒤 다시 보냄."""
    r = server.srv.robot
    r.p = [368.0, 6.5, 195.0, 0.0, 180.0, 0.0]
    seen, real = [], r.movel_async

    def movel(p, *a, radius=0.0, **k):
        seen.append(radius)
        return real(p, *a, **k)
    r.movel_async = movel
    view = server.srv.poses()["drawer_top_view"]["drawer_top"]
    out, _ = server.run("move_to_named_pose", {"pose_name": "drawer_top_view", "drawer_id": "drawer_top"})
    assert out.success and seen == [50.0] and r.log[-1] == ("movej", view)   # 탑뷰는 끝 50 mm 부터 회전 시작 [사용자 10/08] (다른 포즈는 20)
    r.p, r.log[:], seen[:] = [368.0, 6.5, 195.0, 0.0, 180.0, 0.0], [], []
    real_j, calls = r.movej_async, []

    def movej(j, v, a):
        calls.append(list(j))
        return False if len(calls) == 1 else real_j(j, v, a)
    r.movej_async = movej
    out, _ = server.run("move_to_named_pose", {"pose_name": "drawer_top_view", "drawer_id": "drawer_top"})
    assert out.success and len(calls) == 2 and r.p[2] == pytest.approx(325.0, abs=0.05)   # 다 올라간 뒤 다시


def test_pick_and_place_go_fast_until_1cm_then_slow(server):
    """10/07 사용자: 잡기·놓기는 1 cm 전까지 빠르게(line_mm_s), 마지막 1 cm 만 천천히."""
    server.Gripper.holding = True
    t = json.loads(json.dumps(ERASER_CORNER))
    t["pose"]["position"][:2] = [0.10, WALL_Y - 0.040]                  # 집기 판단 여유 8 mm 로도 바로 집히는 자리 [10/10]
    speeds, real = [], server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        speeds.append((stage, vel, posx[2]))
        return real(self, goal, posx, vel, stage, watch, **kw)
    server.ss.SkillServer._line = line
    try:
        out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
        assert out.success
        out2, _ = server.run("place_object", {"location": "handover_zone"})
    finally:
        server.ss.SkillServer._line = real
        server.Gripper.holding = False
    st = {s: (v, z) for s, v, z in speeds}
    # 서랍 안 내려가기는 in_drawer_mm_s [사용자 10/07 밤], 트레이는 line_mm_s
    # 경유점이 있는 서랍: 목표 위로 가는 블렌딩이 잡는 높이 1 cm 위에서 끝남(따로 빠르게 내려가기 없음) → 마지막 1 cm 만 천천히 [사용자 10/10]
    # 집기 [사용자 10/11 "벌려서 높이만큼 빠르게 내려가 집기"]: 목표 위 → 잡는 높이까지 블렌딩 한 번(서랍 안 속도), 천천히 내려가기 없음
    assert "descend" not in st and "descend_fast" not in st
    assert out2.success and "lower_fast" not in st and st["lower"][0] == 15.0   # 칸 위 → 1 cm 위는 들고 나오기 블렌딩에 포함 [사용자 10/10]
    over = server.srv.prm()["place"]["touch_overtravel_mm"]             # 안 닿으면(가짜 로봇 힘 0) 계산 높이보다 이만큼 더 [사용자 10/10]
    carry = [e for e in server.srv.robot.log if e[0] == "moveb"][-1][1][-1]
    assert carry[2] - st["lower"][1] == pytest.approx(10.0 + over)


def test_pick_turns_wrist_at_waypoint_before_going_down(server):
    """[실측 PC2 10/10] 45° 놓인 지우개: 옆 구간에서 돌리면 제어기가 출발 안 하고, 내려가며 돌리면 벌린 손가락이 테두리 아래에서
    벽에 닿음 → 경유점(테두리 위)에서 J6 만 돌려 잡는 각도를 먼저 맞추고, 목표 위 → 내려가기는 손목 그대로."""
    srv = server.srv
    down = srv.poses()["drag_down"]["drawer_top"]
    server.Gripper.holding = True
    t = json.loads(json.dumps(ERASER_FREE))
    t["pose"]["yaw"] = -0.7                                             # 세로에 가까움 → 짧은 변 (가로면 긴 변 [사용자 10/10])
    srv.robot.log.clear()
    try:
        out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
    finally:
        server.Gripper.holding = False
    assert out.success
    log = srv.robot.log
    i = log.index(("movej", down))
    kind, turned = log[i + 1][:2]
    assert kind == "movej" and turned[:5] == down[:5] and abs(turned[5] - down[5]) > 1.0   # 경유점에서 J6 만
    kind, pts, _ = next(e for e in log[i + 2:] if e[0] == "moveb")
    assert all(p[3:] == pts[0][3:] for p in pts)                        # 목표 위 → 내려가기는 손목 그대로
    # 놓으러 갈 때도 블렌딩 안에서 손목을 되돌리지 않음 — 경유점에서 J6 먼저 [실측 PC2 10/10 65° → carry NOT_REACHED]
    srv.robot.p = list(srv.robot.p[:3]) + [156.1, 180.0, -139.4]       # 집은 손목 방향 그대로 경유점
    srv.robot.log.clear()
    server.Gripper.holding = True
    try:
        out2, _ = server.run("place_object", {"location": "handover_zone"})
    finally:
        server.Gripper.holding = False
    assert out2.success
    log = srv.robot.log
    first_b = next(k for k, e in enumerate(log) if e[0] == "moveb")
    assert any(e[0] == "movej" for e in log[:first_b])                  # 들고 나오기 전에 J6 로 되돌림


def test_lip_balm_on_left_wall_picked_by_ends_tilted_and_placed_turned(server):
    """[사용자 10/10 PC2 "원통형은 기울여서"] 왼쪽 벽에 세로로 붙은 립밤: 넛지하면 굴러감 → 넛지 없이 긴 변 양끝을 잡고(기대 폭 = 긴 변)
    왼벽 쪽으로 20° 기울임, TCP 는 교시대로 가운데보다 벽 쪽 4.6·아래 8.8 mm. 트레이에는 손가락을 y 로 돌려 놓음."""
    prm_ = server.srv.prm()
    server.srv.prm = lambda: prm_
    srv = server.srv
    lip = {"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.020,
           "pose": {"frame": "drawer_top", "position": [0.10, 0.010, 0.0], "yaw": 0.0, "yaw_valid": True}}
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": lip})
    assert out.success and data["pushed"] is False                     # 넛지 안 함
    server.Gripper.holding, server.Gripper.held_width = True, 72.5    # 잡은 폭 [실측 사용자 10/10 PC2]
    srv.robot.log.clear()
    try:
        out, data = server.run("pick_object", {"target": lip, "approach_offset": [0, 0, 0.1]})
        assert out.success and data["grasp_ok"] and "긴 변" in out.reason and "옆벽 쪽" in out.reason and srv.held["long_side"] is True
        grasp = [e[1] for e in srv.robot.log if e[0] == "movel"][-1]
        tf = srv.places()["drawer_top"]["tf"]
        rw = srv.prm()["pick"]["round_wall"]
        local = [1000.0 * v for v in server.ss.mp.from_base(tf, [v / 1000.0 for v in grasp[:3]])]
        assert local[1] == pytest.approx(10.0 - rw["tcp_to_wall_mm"], abs=0.1)
        assert local[2] == pytest.approx(10.0 - rw["tcp_below_center_mm"], abs=0.1)
        assert abs(grasp[4]) == pytest.approx(180.0 - rw["tilt_deg"], abs=0.5)
        srv.robot.p = list(srv.robot.p[:3]) + [151.9, 180.0, 151.9]
        srv.robot.log.clear()
        out2, _ = server.run("place_object", {"location": "handover_zone"})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out2.success


def test_lip_balm_in_middle_also_picked_by_ends(server):
    """[사용자 10/10] 가운데 립밤도 긴 변 양끝 (기울이지 않음). 세로에 가까운 지우개는 짧은 변."""
    srv = server.srv
    lip = {"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.020,
           "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.2, "yaw_valid": True}}
    server.Gripper.holding, server.Gripper.held_width = True, 72.5
    try:
        out, _ = server.run("pick_object", {"target": lip, "approach_offset": [0, 0, 0.1]})
        assert out.success and "긴 변" in out.reason and "기울" not in out.reason and srv.held["long_side"] is True
        srv.held = None
        server.Gripper.held_width = 21.0
        out, _ = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
        assert out.success and srv.held["long_side"] is False                  # 세로에 가까운 지우개는 짧은 변 [사용자 10/10]
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0


def test_place_stops_where_it_touches_the_floor(server):
    """[사용자 10/10 "2 mm 위에서 떨구는 느낌"] 놓기 마지막에 z 힘이 touch_n 넘게 변하면 그 높이에서 멈추고 벌림."""
    srv = server.srv
    server.Gripper.holding = True
    t = json.loads(json.dumps(ERASER_FREE))
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
    assert out.success
    floor = {}

    def force(p):                                                       # 바닥에 닿으면 1 mm 에 2 N
        z = floor.get("z")
        return [0.0, 0.0, 2.0 * (z - p[2]) if z is not None and p[2] < z else 0.0, 0.0, 0.0, 0.0]
    real = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        if stage == "lower":
            floor["z"] = posx[2] + server.srv.prm()["place"]["touch_overtravel_mm"] + 1.0   # 계산 높이보다 1 mm 위에 바닥
        r = real(self, goal, posx, vel, stage, watch, **kw)
        if stage == "lower":
            floor["stop"] = self.robot.p[2]
        return r
    srv.robot.force = force
    server.ss.SkillServer._line = line
    try:
        out2, _ = server.run("place_object", {"location": "handover_zone"})
    finally:
        server.ss.SkillServer._line = real
        server.Gripper.holding = False
    assert out2.success
    n = srv.prm()["place"]["touch_n"]
    assert floor["stop"] == pytest.approx(floor["z"] - n / 2.0, abs=0.3)    # 닿은 뒤 touch_n 만큼 눌린 곳에서 멈춤 (계산 높이까지 안 감)


def test_free_space_speed_only_outside_drawer(server):
    """[사용자 10/07 저녁] 빈 공간 직선은 free_mm_s, 서랍 위에서는 line_mm_s 그대로 (누르기·끌기 등은 각자 값)."""
    sp = server.srv.prm()["speed"]
    assert sp["free_mm_s"] > sp["line_mm_s"]
    assert server.srv._free_vel() == sp["free_mm_s"]
    assert server.srv._free_vel([0.0, 0.0, 100.0, 0.0, 180.0, 0.0]) == sp["free_mm_s"]          # 트레이 쪽
    assert server.srv._free_vel([380.0, -216.0, 253.8, 0.0, 180.0, 0.0]) == sp["in_drawer_mm_s"]   # 서랍 위·안은 느리게
    assert sp["in_drawer_mm_s"] < sp["line_mm_s"] < sp["free_mm_s"]


def test_blend_that_never_starts_is_sent_once_more(server):
    """[실측 10/07 밤 PC2, 관절 90°/s] drag_down 도착 직후 보낸 moveb 가 실행되지 않음 → 남은 204 mm NOT_REACHED.
    출발조차 안 한 블렌딩은 멈춘 걸 확인하고 한 번만 다시 보냄. 두 번째도 안 가면 점마다 직선으로 끝까지
    [실측 PC2 10/10 "방향 1 s" 반복 — 손목 크게 도는 블렌딩은 제어기가 계속 출발 안 함]."""
    r = server.srv.robot
    r.p = [385.4, -286.7, 229.8, 143.0, 180.0, 143.0]
    real, calls = r.moveb_async, []

    def moveb(pts, radii, *a, **k):
        calls.append(1)
        return True if len(calls) == 1 else real(pts, radii, *a, **k)   # 첫 번째는 받기만 하고 안 감
    r.moveb_async = moveb
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)
    pts = [[385.4, -135.2, 229.8, 143.0, 180.0, 143.0], [522.2, -135.2, 221.1, -179.6, -160.0, 180.0]]
    assert server.srv._blend(goal, pts, [20.0, 0.0], 150.0, "to_object:over") is None and len(calls) == 2
    calls.clear()
    r.moveb_async = lambda pts, radii, *a, **k: calls.append(1) or True        # 계속 안 감
    r.p = [385.4, -286.7, 229.8, 143.0, 180.0, 143.0]
    r.log.clear()
    assert server.srv._blend(goal, pts, [20.0, 0.0], 150.0, "to_object:over") is None and len(calls) == 2
    assert [e[1] for e in r.log if isinstance(e, tuple) and e[0] == "movel"] == pts and r.posx()[:3] == pytest.approx(pts[-1][:3])


def test_into_drawer_waypoint_uses_slow_joint_speed(server):
    """[사용자 10/07 밤] 큰 이동(탑뷰·홈)은 관절 설정 속도, 서랍 안 경유점(drag_down)으로 들어갈 땐 in_drawer_joint_*."""
    srv = server.srv
    srv.joint_vel, srv.joint_acc = 90.0, 60.0
    sp = srv.prm()["speed"]
    seen, real = [], srv.robot.movej_async
    srv.robot.movej_async = lambda j, v, a: seen.append((list(j), v, a)) or real(j, v, a)
    down = srv.poses()["drag_down"]["drawer_top"]
    srv.robot.p = [424.181, -294.601, 363.507, 0.0, 180.0, 0.0]
    server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    speeds = {tuple(j): (v, a) for j, v, a in seen}
    assert speeds[tuple(down)] == (sp["in_drawer_joint_deg_s"], sp["in_drawer_joint_acc_deg_s2"])
    view = srv.poses()["drawer_top_view"]["drawer_top"]
    if tuple(view) in speeds:
        assert speeds[tuple(view)] == (90.0, 60.0)                       # 탑뷰는 큰 이동 속도


def test_settle_timeout_stops_and_fails_instead_of_sending_next(server):
    """#139 PM 리뷰: 관절 이동 뒤 2 s 안에 멈추지 않으면 다음 명령을 보내지 않고 정지 + 정지 확인 뒤 실패."""
    srv = server.srv
    states = iter([sf.STATE_MOVING] * 45 + [1] * 50)                   # 2 s 넘게 이동 중 → 정지 명령 뒤 멈춤 (가짜 시계 0.05 s 간격)
    srv.state = lambda: next(states)
    out = srv._settle()
    assert out is not None and not out.success and out.error_code == sf.NOT_REACHED and "stop" in srv.robot.log
    srv.state = lambda: 1
    assert srv._settle() is None
    srv.robot.log.clear()                                               # 상태 조회 실패가 이어지면 '멈춤'으로 보지 않음 [#139 E 리뷰 P2]
    seq = iter([None] * 30 + [1] * 50)
    srv.state = lambda: next(seq)
    out = srv._settle()
    assert out.error_code == sf.STATE_UNKNOWN and "stop" in srv.robot.log


def test_line_that_never_starts_is_sent_once_more(server):
    """[실측 10/08 아침 PC2 P1] 트레이 칸 위 도착(블렌딩) 직후 보낸 lower_fast 가 실행되지 않음 → 남은 73.6 mm NOT_REACHED.
    직선도 출발조차 안 했으면 멈춘 걸 확인하고 한 번만 다시. 두 번째도 안 가면 NOT_REACHED."""
    r = server.srv.robot
    r.p = [578.7, 205.6, 100.4, 45.4, 180.0, 44.7]
    target = [578.8, 205.5, 26.9, 151.9, -180.0, 151.2]                 # 같은 방향 (B 180 에서 C−A 같음), z 만 내려감
    real, calls = r.movel_async, []

    def movel(p, *a, **k):
        calls.append(1)
        return True if len(calls) == 1 else real(p, *a, **k)            # 첫 번째는 받기만 하고 안 감
    r.movel_async = movel
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)
    assert server.srv._line(goal, target, 150.0, "lower_fast") is None and len(calls) == 2
    calls.clear()
    r.movel_async = lambda p, *a, **k: calls.append(1) or True           # 계속 안 감
    r.p = [578.7, 205.6, 100.4, 45.4, 180.0, 44.7]
    out = server.srv._line(goal, target, 150.0, "lower_fast")
    assert out.error_code == sf.NOT_REACHED and len(calls) == 2


def test_line_that_moved_or_turned_is_not_resent(server):
    """#156 E 리뷰 P2: 위치가 출발점 1 mm 안이어도 돌기 시작했으면 출발한 것 — 다시 보내지 않음. 조금 가다 선 것도 그대로.
    같은 방향의 다른 표기([45.4, 180, 44.7] ↔ [151.9, -180, 151.2])는 '안 돎'으로 봄."""
    r = server.srv.robot
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)
    calls = []

    def stuck_at(p):                                                    # 보내면 p 까지만 가고 섬
        def movel(*a, **k):
            calls.append(1)
            r.p = list(p)
            return True
        return movel
    start, target = [500.0, 0.0, 100.0, 0.0, 180.0, 0.0], [510.0, 0.0, 100.0, 0.0, 180.0, 30.0]
    for stop_at in ([500.0, 0.0, 100.0, 0.0, 180.0, 20.0],                 # 제자리에서 20° 돌다 섬 (E 반례)
                    [501.5, 0.0, 100.0, 0.0, 180.0, 0.0],                  # 1.5 mm 가다 섬
                    [504.0, 0.0, 100.0, 0.0, 180.0, 12.0]):                # 반쯤 가다 섬
        calls.clear()
        r.p = list(start)
        r.movel_async = stuck_at(stop_at)
        out = server.srv._line(goal, target, 150.0, "lower_fast")
        assert out.error_code == sf.NOT_REACHED and len(calls) == 1, stop_at
    calls.clear()                                                       # 표기만 다르고 같은 방향 = 출발 안 함 → 한 번 다시
    r.p = [578.7, 205.6, 100.4, 45.4, 180.0, 44.7]
    r.movel_async = stuck_at([578.7, 205.6, 100.4, 151.9, -180.0, 151.2])
    out = server.srv._line(goal, [578.8, 205.5, 26.9, 151.9, -180.0, 151.2], 150.0, "lower_fast")
    assert out.error_code == sf.NOT_REACHED and len(calls) == 2


def test_contact_and_slow_lines_are_not_resent(server):
    """접촉 감시 직선(끌기·손잡이 등)과 아주 느린 직선(누르기·힘 맞추기 0.1 mm)은 서 있어도 다시 보내지 않음 — 막힌 쪽으로 또 밀지 않게."""
    r = server.srv.robot
    calls = []
    r.movel_async = lambda p, *a, **k: calls.append(1) or True
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)
    r.p = [500.0, 0.0, 100.0, 0.0, 180.0, 0.0]
    out = server.srv._line(goal, [500.0, 40.0, 100.0, 0.0, 180.0, 0.0], 10.0, "drag", watch=lambda: None)
    assert out.error_code == sf.NOT_REACHED and len(calls) == 1
    calls.clear()
    out = server.srv._line_slow(goal, [500.0, 0.0, 90.0, 0.0, 180.0, 0.0], 1.0, "press")
    assert out.error_code == sf.NOT_REACHED and len(calls) == 1


def test_cancel_while_settling_does_not_resend_blend(server):
    """#139 E 리뷰 P1: 첫 블렌딩이 출발하지 않은 뒤 멈춤 확인 중 취소 → 두 번째 moveb 를 보내지 않고 CANCELED."""
    srv, r = server.srv, server.srv.robot
    r.p = [385.4, -286.7, 229.8, 143.0, 180.0, 143.0]
    calls = []
    r.moveb_async = lambda pts, radii, *a, **k: calls.append(1) or True    # 받기만 하고 안 감
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)
    real_settle = srv._settle

    def settle(g=None, **kw):
        goal.is_cancel_requested = True                                 # 멈춤 확인 중 취소
        return real_settle(g, **kw)
    srv._settle = settle
    pts = [[385.4, -135.2, 229.8, 143.0, 180.0, 143.0], [522.2, -135.2, 221.1, -179.6, -160.0, 180.0]]
    out = srv._blend(goal, pts, [20.0, 0.0], 150.0, "to_object:over")
    assert out.error_code == sf.CANCELED and len(calls) == 1


def test_open_drawer_refused_unless_at_ready(server):
    """#168 사용자 10/08: 열기 노드는 손잡이 앞(drawer_approach)에서만 시작 — 홈 등 다른 곳이면 그리퍼도 움직이기 전에 NOT_AT_START_POSE."""
    server.srv.disp = {}
    server.Gripper.width = 55.0
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_top", "state": "open"})      # 가짜 로봇은 홈 관절
    assert not out.success and out.error_code == server.ss.NOT_AT_START_POSE
    assert server.srv.robot.log == [] and server.Gripper.width == 55.0


def test_open_drawer_handle_not_grasped_releases_and_backs_off(server):
    """[사용자 10/08] 손잡이를 못 잡으면 그리퍼 열고 여는 방향으로 retreat_mm 빼고 GRASP_FAILED (그 자리에 두지 않음)."""
    srv = server.srv
    srv.disp = {}
    srv.robot.j = list(srv.poses()["drawer_approach"]["drawer_top"])
    server.Gripper.holding = False                                      # 닫으면 0.9 mm = 손잡이 못 잡음
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_top", "state": "open"})
    assert not out.success and out.error_code == server.ss.GRASP_FAILED
    moves = [e for e in srv.robot.log if e != "stop" and e[0] == "movel"]
    reach, back = moves[-2][1], moves[-1][1]
    assert back[1] - reach[1] == pytest.approx(srv.prm()["drawer_open_close"]["retreat_mm"], abs=0.5)   # +y(여는 방향)로 60 mm
    assert server.Gripper.width == srv.prm()["drawer_open_close"]["handle_open_width_mm"]


def test_bottom_drawer_close_refused_until_tilted_pose_taught(server):
    """[실측 B 10/08] 아래 칸은 수직 그리퍼 몸통이 위 서랍 앞판에 닿음 → close_push 교시 전엔 움직이지 않고 DRAWER_NOT_CONFIGURED."""
    prm = server.srv.prm()
    prm["drawer_open_close"]["close_push"] = dict(prm["drawer_open_close"]["close_push"], drawer_bottom=None)
    server.srv.prm = lambda: prm
    server.srv.disp = {"drawer_bottom": 0.226}
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_bottom", "state": "close"})
    assert not out.success and out.error_code == server.ss.DRAWER_NOT_CONFIGURED
    assert server.srv.robot.log == []



def test_taught_close_push_start_and_end_agree_in_x_z(server):
    """params 의 위·아래 close_push: 시작·끝 x·z 가 close_push_xz_tol_mm 안 (아니면 실물에서 움직이기 전 거부), 손목 같음 (C +90 vs −90 섞임 방지)."""
    oc = server.srv.prm()["drawer_open_close"]
    for drawer in ("drawer_top", "drawer_bottom"):
        cp = oc["close_push"][drawer]
        s, e = cp["start_posx"], cp["end_posx"]
        assert max(abs(s[k] - e[k]) for k in (0, 2)) <= oc["close_push_xz_tol_mm"], drawer
        assert all(abs(s[k] - e[k]) < 1.0 for k in (3, 4, 5)), drawer
        assert e[1] < s[1] - 200.0, drawer                               # 끝(닫힘)이 시작(열림 앞)보다 서랍 쪽(−y)으로 200 mm 넘게


def test_tilted_close_goes_to_taught_start_and_pushes_to_end(server):
    """[사용자 10/08] 기울인(45°) 손끝으로 앞판 중앙을 y 로 밀어 닫기 (위·아래 공통): 교시한 start_posj 로 관절 이동 →
    end_posx 를 지나 close_overtravel 만큼 밂(손목 그대로) → 여는 방향으로 빼기. 홈은 가지 않음."""
    srv = server.srv
    prm = srv.prm()
    start = [21.9, 39.2, 115.7, 110.1, -99.3, -23.6]
    end = [381.9, -283.0, 100.0, 90.0, 160.0, 90.0]                    # 닫힌 앞판에 닿는 자리 (예시)
    start_x = [381.9, -27.0, 100.0, 90.0, 160.0, 90.0]                  # 시작 자세 TCP (서랍 앞판 3 cm 앞)
    prm["drawer_open_close"]["close_push"] = {"drawer_top": None, "drawer_bottom": {"start_posj": start, "start_posx": start_x, "end_posx": end}}
    srv.prm = lambda: prm
    srv.disp = {"drawer_bottom": 0.226}
    srv.robot.p = list(start_x)                                         # 시작 자세에 도착했을 때 TCP
    out, data = server.run("drawer_control", {"drawer_id": "drawer_bottom", "state": "close"})
    assert out.success and data["close_confirmed"] is True and srv.disp["drawer_bottom"] == 0.0
    assert data["close_remaining_m"] <= data["close_pos_tol_m"] and data["close_push_interrupted"] is False   # 닫기 근거 [P2 4절]
    log = [e for e in srv.robot.log if e != "stop"]
    assert log[0] == ("movej", start)
    pushes = [e[1] for e in log if e[0] == "movel"]
    deepest = min(p[1] for p in pushes)
    assert deepest == pytest.approx(end[1] - prm["drawer_control"]["close_overtravel_m"] * 1000.0, abs=0.5)
    assert all(p[3:] == end[3:] for p in pushes[:-1])                  # 미는 동안 손목 그대로
    assert pushes[-1][1] > deepest                                      # 마지막은 여는 방향으로 빼기
    assert ("movej", srv.poses()["home"]["joints_deg"]) not in log


def test_tilted_close_then_home_retreats_and_goes_home_without_stopping(server):
    """[사용자 10/10] B close 는 then_home — 빼기를 끝 home_blend_mm 반지름으로 보내고 멈추지 않고 (올리기 →) 홈 관절 이동까지."""
    srv = server.srv
    prm = srv.prm()
    start = [21.9, 39.2, 115.7, 110.1, -99.3, -23.6]
    end = [381.9, -283.0, 100.0, 90.0, 160.0, 90.0]
    start_x = [381.9, -27.0, 100.0, 90.0, 160.0, 90.0]
    prm["drawer_open_close"]["close_push"] = {"drawer_top": None, "drawer_bottom": {"start_posj": start, "start_posx": start_x, "end_posx": end}}
    srv.prm = lambda: prm
    srv.disp = {"drawer_bottom": 0.226}
    srv.robot.p = list(start_x)
    radii, real = [], server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        radii.append((stage, kw.get("radius", 0.0)))
        return real(self, goal, posx, vel, stage, watch, **kw)
    server.ss.SkillServer._line = line
    try:
        out, data = server.run("drawer_control", {"drawer_id": "drawer_bottom", "state": "close", "then_home": True})
    finally:
        server.ss.SkillServer._line = real
    assert out.success and data["close_confirmed"] is True and srv.disp["drawer_bottom"] == 0.0 and "홈" in out.reason
    assert ("retreat", prm["drawer_open_close"]["home_blend_mm"]) in radii       # 홈 TCP 모름 → 빼기 끝에서 멈추지 않고 홈 관절 이동
    log = [e for e in srv.robot.log if e != "stop"]
    assert log[-1] == ("movej", srv.poses()["home"]["joints_deg"])
    # 홈 TCP 를 알면(이번 서버에서 홈에 간 적 있음) 빼기 → 홈 TCP 를 블렌딩 한 번으로, 관절이 맞으면 관절 이동 없음
    home_x = [368.0, 6.2, 196.5, 0.0, 180.0, 0.0]
    srv.home_posx = home_x
    srv.disp = {"drawer_bottom": 0.226}
    srv.robot.p = list(start_x)
    srv.robot.j = list(start)
    srv.robot.log.clear()
    orig_moveb = srv.robot.moveb_async

    def moveb(pts, radii, *a, **kw):
        r = orig_moveb(pts, radii, *a, **kw)
        srv.robot.j = list(srv.poses()["home"]["joints_deg"])            # 홈 TCP 에 도착하면 홈 관절
        return r
    srv.robot.moveb_async = moveb
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_bottom", "state": "close", "then_home": True})
    assert out.success
    log = [e for e in srv.robot.log if e != "stop"]
    tr = prm["transit"]
    kind, pts, radii = log[-1]                                          # 빼기 → 올리기 → 밖으로 → 홈 TCP 를 한 번에
    assert kind == "moveb" and pts[-1] == home_x and len(pts) == 4
    assert pts[1][2] == pytest.approx(tr["high_z_mm"]) and pts[2][1] == pytest.approx(tr["exit_y_mm"]) and pts[2][2] == pytest.approx(tr["high_z_mm"])
    assert radii[0] == pytest.approx(prm["drawer_open_close"]["home_blend_first_mm"]) and radii[1] > radii[0] and radii[-1] == 0.0
    assert ("movej", srv.poses()["home"]["joints_deg"]) not in log


def test_tilted_close_refuses_when_start_and_end_taught_apart(server):
    """시작·끝 교시값의 x·z 가 close_push_xz_tol_mm(5 mm) 넘게 다르면 잘못 잰 것 → 움직이기 전 거부 (DRAWER_NOT_CONFIGURED, #181 C 리뷰).
    start_posx 가 없어도 움직이기 전 거부."""
    srv = server.srv
    prm = srv.prm()
    end = [381.9, -283.0, 100.0, 90.0, -135.0, 90.0]
    bottom = {"start_posj": [21.9, 39.2, 115.7, 110.1, -99.3, -23.6], "start_posx": [381.9, -27.0, 110.0, 90.0, -135.0, 90.0], "end_posx": end}   # z 10 mm 다름
    prm["drawer_open_close"]["close_push"] = {"drawer_top": None, "drawer_bottom": bottom}
    srv.prm = lambda: prm
    srv.disp = {"drawer_bottom": 0.226}
    srv.robot.p = [381.9, -27.0, 400.0, 90.0, -135.0, 90.0]             # 서랍 위 (홈부터 갈 자리)
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_bottom", "state": "close"})
    assert not out.success and out.error_code == server.ss.DRAWER_NOT_CONFIGURED
    assert [e for e in srv.robot.log if e != "stop"] == []
    del bottom["start_posx"]
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_bottom", "state": "close"})
    assert not out.success and out.error_code == server.ss.DRAWER_NOT_CONFIGURED
    assert [e for e in srv.robot.log if e != "stop"] == []


def test_tilted_close_stops_when_arrived_away_from_start_posx(server):
    """start_posj 로 갔는데 TCP 가 start_posx 와 5 mm 넘게 다르면(옮겨 적다 틀림) 밀지 않고 멈춤 — 이미 움직였으므로
    움직이기 전 코드(DRAWER_NOT_CONFIGURED)가 아닌 CLOSE_NOT_CONFIRMED (#181 C 리뷰)."""
    srv = server.srv
    prm = srv.prm()
    start = [21.9, 39.2, 115.7, 110.1, -99.3, -23.6]
    end = [381.9, -283.0, 100.0, 90.0, -135.0, 90.0]
    prm["drawer_open_close"]["close_push"] = {"drawer_top": None, "drawer_bottom": {"start_posj": start, "start_posx": [381.9, -27.0, 100.0, 90.0, -135.0, 90.0], "end_posx": end}}
    srv.prm = lambda: prm
    srv.disp = {"drawer_bottom": 0.226}
    srv.robot.p = [381.9, -27.0, 112.0, 90.0, -135.0, 90.0]             # 도착했는데 z 12 mm 다름
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_bottom", "state": "close"})
    assert not out.success and out.error_code == server.ss.dp.CLOSE_NOT_CONFIRMED
    log = [e for e in srv.robot.log if e != "stop"]
    assert log[-1] == ("movej", start) and not any(e[0] == "movel" for e in log)


def _cancel_after_home(server):
    """홈 이동(_named "home")이 끝난 직후 취소 요청 + 그리퍼 명령 기록. 홈 movej 뒤 로그 위치를 돌려받는 함수."""
    srv = server.srv
    real_named, grips = srv._named, []

    def named(goal, pose_name, *a, **k):
        o = real_named(goal, pose_name, *a, **k)
        if pose_name == "home":
            goal.is_cancel_requested = True                             # 홈 도착 직후 취소
        return o
    srv._named = named
    srv._grip = lambda w, f: grips.append(w)
    return grips


def test_tilted_close_cancel_after_home_sends_no_grip(server):
    """#181 E 리뷰: 서랍 위에서 기울여 닫기 → 홈 이동 뒤 취소면 그리퍼·다음 이동 명령 없이 CANCELED."""
    srv = server.srv
    prm = srv.prm()
    start = [21.9, 39.2, 115.7, 110.1, -99.3, -23.6]
    end = [381.9, -283.0, 100.0, 90.0, -135.0, 90.0]
    prm["drawer_open_close"]["close_push"] = {"drawer_top": None, "drawer_bottom": {"start_posj": start, "start_posx": [381.9, -27.0, 100.0, 90.0, -135.0, 90.0], "end_posx": end}}
    srv.prm = lambda: prm
    srv.disp = {"drawer_bottom": 0.226}
    srv.robot.p = [424.181, -294.601, 363.507, 0.0, 180.0, 0.0]        # 탑뷰 (서랍 위) → 홈부터
    grips = _cancel_after_home(server)
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_bottom", "state": "close"})
    assert not out.success and out.error_code == sf.CANCELED
    log = [e for e in srv.robot.log if e != "stop"]
    home = ("movej", srv.poses()["home"]["joints_deg"])
    assert log[-1] == home and grips == []                              # 홈 movej 뒤 로봇·그리퍼 명령 없음


def test_nudge_and_pick_refuse_other_drawer_frame_without_motion(server):
    """[#181 E 리뷰] 위 칸 좌표(frame drawer_top)로 아래 칸을 끌거나 집지 않음 — drawer_id 와 target.pose.frame 이 다르면 움직이기 전 BAD_PARAMS."""
    out, _ = server.run("nudge_object", {"drawer_id": "drawer_bottom", "target": ERASER_CORNER})
    assert not out.success and out.error_code == server.ss.sf.BAD_PARAMS
    out, _ = server.run("pick_object", {"drawer_id": "drawer_bottom", "target": ERASER_CORNER})
    assert not out.success and out.error_code == server.ss.sf.BAD_PARAMS
    assert server.srv.robot.log == []


@pytest.mark.parametrize("state", [5, 6, 9, None])
@pytest.mark.parametrize("drawer", ["drawer_top", "drawer_bottom"])
def test_close_after_home_safety_stop_sends_nothing_more(server, state, drawer):
    """#181 E 재리뷰 P1: 닫기(45° close_push)에서 홈 이동 직후 안전정지(5)·비상정지(6)·안전정지2(9)·상태 조회 실패면
    그리퍼·다음 이동 명령 0건 — ESTOP / STATE_UNKNOWN. (예전 위 칸 수직 닫기는 10/12 코드 정리로 뺌)"""
    srv = server.srv
    prm = srv.prm()
    start = [21.9, 39.2, 115.7, 110.1, -99.3, -23.6]
    end = [381.9, -283.0, 100.0, 90.0, -135.0, 90.0]
    cp = {"start_posj": start, "start_posx": [381.9, -27.0, 100.0, 90.0, -135.0, 90.0], "end_posx": end}
    prm["drawer_open_close"]["close_push"] = {"drawer_top": cp, "drawer_bottom": cp}
    srv.prm = lambda: prm
    srv.disp = {drawer: 0.226}
    srv.robot.p = [424.181, -294.601, 363.507, 0.0, 180.0, 0.0]        # 탑뷰 (서랍 위) → 홈부터
    server.Gripper.width = 0.9
    real_named, grips = srv._named, []

    def named(goal, pose_name, *a, **k):
        o = real_named(goal, pose_name, *a, **k)
        if pose_name == "home":
            srv.robot.state = lambda: state                             # 홈 도착 직후 상태 주입
        return o
    srv._named = named
    srv._grip = lambda w, f: grips.append(w)
    out, _ = server.run("drawer_control", {"drawer_id": drawer, "state": "close"})
    assert not out.success and out.error_code == (sf.STATE_UNKNOWN if state is None else sf.ESTOP)
    log = [e for e in srv.robot.log if e != "stop"]
    assert log[-1] == ("movej", srv.poses()["home"]["joints_deg"]) and grips == []


def test_view_pose_uses_its_own_faster_joint_speed(server):
    """[사용자 10/08] 탑뷰·바텀뷰 이동만 speed.view_joint_* (J6 약 200° 회전), 다른 기준 포즈는 서버 관절 속도 그대로."""
    srv, speeds = server.srv, []
    real = srv.robot.movej_async

    def movej(j, vel, acc):
        speeds.append((vel, acc))
        return real(j, vel, acc)
    srv.robot.movej_async = movej
    sp = srv.prm()["speed"]
    for drawer in ("drawer_top", "drawer_bottom"):
        out, _ = server.run("move_to_named_pose", {"pose_name": "drawer_top_view", "drawer_id": drawer})
        assert out.success and speeds[-1] == (sp["view_joint_deg_s"], sp["view_joint_acc_deg_s2"])
    out, _ = server.run("move_to_named_pose", {"pose_name": "drawer_approach", "drawer_id": "drawer_top"})
    assert out.success and speeds[-1] == (sp["view_joint_deg_s"], sp["view_joint_acc_deg_s2"])   # 손잡이 앞도 [사용자 10/08]
    out, _ = server.run("move_to_named_pose", {"pose_name": "tray_view"})
    assert out.success and speeds[-1] == (srv.joint_vel, srv.joint_acc)   # 다른 기준 포즈는 서버 속도 (빈손 홈은 10/12 부터 빠르게)


@pytest.mark.parametrize("width_now, restored", [(22.4, True), (0.9, False), (99.0, False), (26.0, False)])
def test_held_object_survives_server_restart_only_if_gripper_still_holds(server, tmp_path, width_now, restored):
    """[사용자 10/08] 서버 재시작 뒤 놓기가 NOT_HOLDING → 쥔 물체를 파일에 저장, 시작 때 그리퍼 폭이 저장 폭과
    slip_tolerance(2 mm) 안이면 되살림. 빈손 닫힘·활짝 열림·폭이 많이 다르면 버리고 파일 지움."""
    srv = server.srv
    srv.held_file = tmp_path / "held.json"
    srv.held = {"class": "eraser", "id": "eraser#1", "width_m": 0.0228, "drawer_id": "drawer_top", "tcp_above_floor_m": 0.03}
    assert json.loads(srv.held_file.read_text())["class"] == "eraser"
    srv._held = None                                                    # 재시작 흉내 (메모리만 사라짐)
    server.Gripper.width = width_now
    srv._held = srv._restore_held()
    assert (srv.held is not None) == restored and srv.held_file.exists() == restored
    srv.held = None
    assert not srv.held_file.exists()



@pytest.mark.parametrize("bad", [float("nan"), -5.0, 150.0])
def test_held_record_kept_when_gripper_width_invalid_at_restart(server, tmp_path, bad):
    """[D #216 P1] 재시작 때 그리퍼 폭이 NaN·범위 밖(SENSOR_INVALID)이면 쥐었는지 모름 — 메모리엔 안 올리되 기록은 남김.
    다음 재시작에 폭이 정상이면 복원."""
    srv = server.srv
    srv.held_file = tmp_path / "held.json"
    srv.held = {"class": "eraser", "id": "eraser#1", "width_m": 0.0228, "drawer_id": "drawer_top", "tcp_above_floor_m": 0.03}
    srv._held = None
    server.Gripper.width = bad
    srv._held = srv._restore_held()
    assert srv.held is None and srv.held_file.exists()
    server.Gripper.width = 22.4
    srv._held = srv._restore_held()
    assert srv.held is not None and srv.held["id"] == "eraser#1" and srv.held_file.exists()
    srv.held = None


@pytest.mark.parametrize("bad", [float("nan"), 150.0, "read_error"])
def test_hold_unknown_after_restart_refuses_gripper_actions_before_motion(server, tmp_path, bad):
    """[P2 5절] 재시작 때 쥔 기록이 있는데 폭을 못 읽으면(이상값·읽기 실패) 빈손으로 보지 않음 — 집기·넛지·서랍·놓기를
    SENSOR_INVALID 로 움직이기 전(그리퍼 명령도 없이) 거부. 기준 포즈 이동은 됨. 폭이 정상인 재시작에서 풀림."""
    srv = server.srv
    srv.held_file = tmp_path / "held.json"
    srv.held = {"class": "eraser", "id": "eraser#1", "width_m": 0.0228, "drawer_id": "drawer_top", "tcp_above_floor_m": 0.03}
    srv._held = None
    real_status = server.Gripper.status
    if bad == "read_error":
        def fail(self):
            raise IOError("RG2 연결 안 됨")
        server.Gripper.status = fail
    else:
        server.Gripper.width = bad
    srv._held = srv._restore_held()
    assert srv.held is None and srv.hold_unknown["id"] == "eraser#1" and srv.held_file.exists()
    grips = []
    srv._grip = lambda *a: grips.append(a)
    for action, params in (("pick_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER}),
                           ("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER}),
                           ("drawer_control", {"drawer_id": "drawer_top", "state": "close"}),
                           ("place_object", {"location": "handover_zone"})):
        out, _ = server.run(action, params)
        assert not out.success and out.error_code == server.ss.gc.SENSOR_INVALID, action
    assert srv.robot.log == [] and grips == []
    out, _ = server.run("move_to_named_pose", {"pose_name": "home"})
    assert out.success
    server.Gripper.status = real_status
    server.Gripper.width = 22.4
    srv.hold_unknown = None                                             # 재시작 흉내
    srv._held = srv._restore_held()
    assert srv.held is not None and srv.hold_unknown is None and srv._refuse_if_hold_unknown() is None
    srv.held = None

def test_in_drawer_moves_sideways_only_above_rim(server):
    """[사용자 10/08] 서랍 안 옆 이동은 테두리 + in_drawer_clear_mm 위에서만, 목표 바로 위에서 수직으로 내려감 (쌓인 물건 약 55 mm).
    경유점(drag_down)이 그 높이보다 낮아도 먼저 수직으로 올린 뒤 옆으로."""
    srv = server.srv
    top = srv.places()["drawer_top"]
    travel = 1000.0 * (top["tf"]["translation_m"][2] + top["interior_m"][2]) + srv.prm()["transit"]["in_drawer_clear_mm"]
    srv.robot.p = [375.6, -217.0, 250.0, 0.0, 180.0, 0.0]               # 테두리보다 낮은 경유점에 있다고 가정
    above = [300.0, -150.0, 215.0, 0.0, 180.0, 0.0]
    srv._over_then_down(types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None),
                        "drawer_top", list(srv.robot.p), above, "to_object:over")
    kind, pts, radii = srv.robot.log[-1]
    assert kind == "moveb" and len(pts) == 3
    assert pts[0][:2] == pytest.approx([375.6, -217.0]) and pts[0][2] == pytest.approx(travel)   # 수직으로 올림
    assert pts[1][:2] == pytest.approx(above[:2]) and pts[1][2] == pytest.approx(travel)        # 그 높이로 목표 바로 위
    assert pts[2] == above and radii[-1] == 0.0                                                 # 수직으로 내려감


# --- 서랍 안 놓기 (#120 ②, 계약 #166) ---
PLACE_EXAMPLES = json.loads((REPO / "contracts/examples/place_object_result.json").read_text(encoding="utf-8"))["cases"]
DRAWER_CASES = [c for c in PLACE_EXAMPLES if c["params"]["location"].startswith("drawer_")]
LIP_HELD = {"class": "lip_balm", "id": "lip_balm#1", "width_m": 0.0195, "drawer_id": "drawer_top", "tcp_above_floor_m": 0.02}
EMPTY_SCAN = {"target_found": False, "target": None, "visible_count": 1,
              "candidates": [{"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.02,
                              "pose": {"frame": "drawer_top", "position": [0.10, 0.10, 0.0], "yaw": 0.0, "yaw_valid": True}}]}
ASIDE_POSE = {"frame": "drawer_top", "position": [0.06, 0.22, 0.0], "yaw": 1.5707}


def _holding_in_drawer(server, slots=None):
    """pick_object 뒤 상태: 서랍 안 경유점(carry_line 1)에서 립밤을 쥐고 있음. slots 를 주면 places.yaml place_slots 교시값으로.
    그리퍼 명령 폭 목록을 돌려줌."""
    srv = server.srv
    srv.held = dict(LIP_HELD)
    server.Gripper.holding, server.Gripper.width = True, 19.5
    srv.robot.p = list(srv.poses()["carry_line"]["drawer_top"][0])
    if slots is not None:
        places = srv.places()
        places["drawer_top"]["place_slots"] = slots
        srv.places = lambda: places
    grips = []
    real = srv._grip
    srv._grip = lambda w, f: grips.append(w) or real(w, f)
    return grips


@pytest.mark.parametrize("case", DRAWER_CASES, ids=[c["case"] for c in DRAWER_CASES])
def test_place_in_drawer_matches_contract_examples(server, monkeypatch, case):
    """contracts/examples/place_object_result.json 의 서랍 안 경우를 노드로 그대로 — 코드·output 이 예시와 같음.
    움직이기 전 거부는 로봇·그리퍼 명령 없음."""
    srv = server.srv
    grips = _holding_in_drawer(server, {"aside_1": {"position": [0.05, 0.05, 0.0], "yaw": 0.0}, "aside_2": None})
    srv.held = dict(LIP_HELD, id=case["_held"]["id"], **{"class": case["_held"]["class"]})
    prm = srv.prm()                                     # 예시는 자리 그대로 놓임 — 비전 오차 여유(repick_noise)로 옮기는 건 아래 따로
    prm["place"].update(repick_noise_mm=0.0, repick_noise_deg=0.0)
    srv.prm = lambda: prm
    if case["case"] == "released_but_lift_failed":
        real_line = server.ss.SkillServer._line

        def line(self, goal, posx, vel, stage, watch=None, **kw):
            if stage == "lift":
                return sf.Outcome(False, sf.STOP_UNCONFIRMED, reason="주입")
            return real_line(self, goal, posx, vel, stage, watch, **kw)
        monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    out, data = server.run("place_object", case["params"])
    assert (out.success, out.error_code) == (case["success"], case["error_code"]), out.reason
    assert data == case["output"]
    if case["error_code"] in ("BAD_PARAMS", "PLACE_BLOCKED", "WALL_TOO_CLOSE"):
        assert srv.robot.log == [] and grips == [] and srv.held is not None


@pytest.mark.parametrize("setup,code", [
    ("not_holding", "NOT_HOLDING"), ("travel", "DRAWER_NOT_AT_TRAVEL"), ("slot_untaught", "PLACE_NOT_CONFIGURED"),
    ("bottom_no_waypoint", "PLACE_NOT_CONFIGURED"), ("held_not_in_scan", "BAD_PARAMS"), ("other_drawer_scan", "BAD_PARAMS"),
])
def test_place_in_drawer_refusals_before_any_command(server, setup, code):
    srv = server.srv
    grips = _holding_in_drawer(server)
    params = {"location": "drawer_top", "pose": dict(ASIDE_POSE), "scan": json.loads(json.dumps(EMPTY_SCAN))}
    if setup == "not_holding":
        srv.held = None
    elif setup == "travel":
        srv.disp = {"drawer_top": 0.20}
    elif setup == "slot_untaught":                                      # 교시 안 된 slot 이름 (aside_1·2 는 10/10 교시)
        params = {"location": "drawer_top", "slot": "aside_9", "scan": params["scan"]}
    elif setup == "bottom_no_waypoint":                                 # 아래 칸 drag_down 교시 전 (저장소 값은 10/10 교시 → 여기서만 지움)
        poses = srv.poses
        srv.poses = lambda: {**poses(), "drag_down": {**poses()["drag_down"], "drawer_bottom": None}}
        srv.disp = {"drawer_bottom": 0.226}
        params["location"] = params["pose"]["frame"] = "drawer_bottom"
        params["scan"]["candidates"][0]["pose"]["frame"] = "drawer_bottom"
    elif setup == "held_not_in_scan":                                   # 다른 촬영 결과 (#166)
        params["scan"]["candidates"][0]["id"] = "lip_balm#2"
    elif setup == "other_drawer_scan":
        params["scan"]["candidates"][0]["pose"]["frame"] = "drawer_bottom"
    out, data = server.run("place_object", params)
    assert not out.success and out.error_code == code
    assert data == {"slot": None, "placed_pose": None}
    assert srv.robot.log == [] and grips == []


def test_place_in_drawer_moves_sideways_only_above_rim(server):
    """[사용자 10/08] 서랍 안 물건이 약 55 mm 쌓일 수 있음 → 경유점 movej → travel_z 로 수직 → 수평 → 수직으로 내려 놓음
    → 벌림 → 수직으로 올라 → 경유점 위(travel_z). travel_z 아래에서는 옆으로 움직이지 않음."""
    from ready2go_skills.core import motion_plan as mp, place_plan as plp
    srv = server.srv
    grips = _holding_in_drawer(server)
    down, waypoint = srv.poses()["drag_down"]["drawer_top"], srv.poses()["carry_line"]["drawer_top"][0]
    prm, place = srv.prm(), srv.places()["drawer_top"]
    pl = prm["place"]
    travel_z = (place["tf"]["translation_m"][2] + place["interior_m"][2]) * 1000.0 + prm["transit"]["in_drawer_clear_mm"]
    out, data = server.run("place_object", {"location": "drawer_top", "pose": ASIDE_POSE, "scan": EMPTY_SCAN})
    assert out.success, out.reason
    assert data == {"slot": None, "placed_pose": ASIDE_POSE} and srv.held is None
    assert grips == [pytest.approx(19.5 + pl["release_extra_mm"])]       # 쥔 폭 + release_extra 로 한 번만 벌림
    log = srv.robot.log
    assert log[0] == ("movej", down)                                    # 서랍 안 경유점 (집기·넛지와 같은 길)
    turns = [e for e in log[1:] if e[0] == "movej"]                     # 경유점에서 J6 만 돌림 (놓는 손목 먼저, ef9250)
    assert all(t[1][:5] == pytest.approx(down[:5]) for t in turns) and len(turns) <= 1
    assert all(e[0] in ("movel", "moveb") for e in log[1:] if e[0] != "movej")
    lines = [p for e in log[1:] if e[0] != "movej" for p in ([e[1]] if e[0] == "movel" else e[1])]   # 블렌딩 경유점까지 펼침
    prev = list(waypoint)
    for p in lines:
        assert math.dist(prev[:2], p[:2]) < 0.01 or min(prev[2], p[2]) >= travel_z - 0.01, (prev, p)
        prev = p
    pos_m, _ = plp.place_tcp_m(place["tf"], ASIDE_POSE, 0.02 + pl["drop_m"])
    low = min(lines, key=lambda p: p[2])
    over = prm["place"]["touch_overtravel_mm"]                          # 안 닿으면 쥔 높이 + drop 보다 이만큼 더 내려가 놓음 [사용자 10/10]
    assert low[:3] == pytest.approx([1000.0 * v for v in pos_m[:2]] + [1000.0 * pos_m[2] - over], abs=1e-6)
    tz = max(travel_z, waypoint[2])                                     # 경유점이 travel_z 보다 높으면 그 높이로 옆 이동 (_travel_z)
    assert lines[0][2] == pytest.approx(tz, abs=1e-6) and lines[-1] == pytest.approx(mp.with_z(waypoint, tz), abs=1e-6)   # 먼저 수직으로, 끝은 경유점 위


def test_place_turns_wrist_at_waypoint_before_moving_over(server):
    """[실측 PC2 10/12 run ef9250] aside 로 손목을 크게 돌리며 옆으로 가면 제어기가 출발 안 함(1 s × 2 멈칫) →
    경유점에서 J6 만 먼저 돌리고, 옆 이동 중엔 손목이 그대로."""
    srv = server.srv
    _holding_in_drawer(server)
    out, _ = server.run("place_object", {"location": "drawer_top", "pose": ASIDE_POSE, "scan": EMPTY_SCAN})
    assert out.success, out.reason
    log = srv.robot.log
    k = next(i for i, e in enumerate(log) if i > 0 and e[0] == "movej")
    assert all(e[0] != "movej" for e in log[k + 1:])                    # 돌린 뒤엔 직선·블렌딩만
    moves = [p for e in log[k + 1:] for p in ([e[1]] if e[0] == "movel" else e[1] if e[0] == "moveb" else [])]
    ang = moves[0][3:]
    assert all(p[3:] == pytest.approx(ang) for p in moves[:3])          # 옆으로 가는 동안 손목 그대로


def test_place_in_drawer_cancel_before_release_keeps_object(server, monkeypatch):
    """그리퍼 열기 직전 취소·비상정지(_clear_to_continue) → 열지 않음, placed_pose null, 쥔 물체 기억 유지."""
    grips = _holding_in_drawer(server)
    monkeypatch.setattr(server.ss.SkillServer, "_clear_to_continue",
                        lambda self, goal: sf.Outcome(False, sf.CANCELED, canceled=True, reason="주입"))
    out, data = server.run("place_object", {"location": "drawer_top", "pose": ASIDE_POSE, "scan": EMPTY_SCAN})
    assert out.error_code == sf.CANCELED and data == {"slot": None, "placed_pose": None}
    assert grips == [] and server.srv.held is not None


def test_place_in_drawer_dropped_before_lowering(server):
    """놓는 자리 위에서 놓침 확인 (domain.md ③) → OBJECT_DROPPED, 내려가지 않음, placed_pose null."""
    grips = _holding_in_drawer(server)
    server.Gripper.width = 0.9                                          # 빈손 닫힘
    out, data = server.run("place_object", {"location": "drawer_top", "pose": ASIDE_POSE, "scan": EMPTY_SCAN})
    assert out.error_code == "OBJECT_DROPPED" and data == {"slot": None, "placed_pose": None}
    assert grips == [] and server.srv.held is None
    stages = [p for e in server.srv.robot.log if e[0] in ("movel", "moveb") for p in ([e[1]] if e[0] == "movel" else e[1])]
    assert min(p[2] for p in stages) > 230.0                            # approach(놓는 높이 + 30 mm)까지만


def test_place_in_drawer_taught_slot_then_not_holding(server):
    _holding_in_drawer(server, {"aside_1": None, "aside_2": {"position": [0.05, 0.24, 0.0], "yaw": 0.0}})
    out, data = server.run("place_object", {"location": "drawer_top", "slot": "aside_2", "scan": EMPTY_SCAN})
    assert out.success and data == {"slot": "aside_2",
                                    "placed_pose": {"frame": "drawer_top", "position": [0.05, 0.24, 0.0], "yaw": 0.0}}
    out, data = server.run("place_object", {"location": "drawer_top", "slot": "aside_2", "scan": EMPTY_SCAN})
    assert out.error_code == "NOT_HOLDING" and data == {"slot": None, "placed_pose": None}   # 연 뒤 다시 보내도 중복 놓기 없음


def test_diagonal_eraser_near_handle_wall_pushed_to_wall(server, monkeypatch):
    """[사용자 10/10 제안, 실측 PC2 비전 yaw −1.0102] 손잡이 쪽 벽 근처 비스듬한 지우개: 손잡이 쪽 벽 쪽으로 기울여 눌러
    손잡이 쪽(x −)으로만 벽까지 끎 — 서랍 여는 방향. y 로는 안 움직임."""
    contact = {}

    def force(p):
        z = contact.get("z")
        return [0.0, 0.0, 8.0 * (z - p[2]) if z is not None and p[2] <= z else 0.0, 0.0, 0.0, 0.0]
    server.srv.robot.force = force
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        if stage == "press":
            contact["z"] = (self.robot.p[2] + posx[2]) / 2
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    t = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
         "pose": {"frame": "drawer_top", "position": [0.0308, 0.06, 0.0], "yaw": -1.0102, "yaw_valid": True}}
    out, data = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
    assert out.error_code == server.ss.WALL_TOO_CLOSE and "벽까지" in out.reason   # 집기 전 넛지 먼저
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t})
    assert out.success and data["pushed"] is True
    dx, dy = data["push_vector_m"]
    assert dx < -0.010 and dy == 0.0


def test_p2_cover_plate_lifted_off_eraser_and_set_aside(server):
    """[P2 시연 시뮬레이션 10/10] 가림막 밑 지우개는 손가락 자리 이웃이 아님 → 집힘. aside_1 에 그대로 두면 손잡이 쪽 벽 밖이라
    자리 안에서 가장 적게 옮겨 놓고(placed_pose = 옮긴 자리), 나중에 넛지 없이 다시 집을 수 있는 자리."""
    srv = server.srv
    plate = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.0405,
             "pose": {"frame": "drawer_top", "position": [0.110, 0.200, 0.0], "yaw": 0.0, "yaw_valid": True}}
    er = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
          "pose": {"frame": "drawer_top", "position": [0.095, 0.185, 0.0], "yaw": 0.0, "yaw_valid": True}}
    scan = {"target_found": True, "target": plate, "candidates": [er], "visible_count": 2}
    server.Gripper.holding, server.Gripper.held_width = True, 74.2
    try:
        out, data = server.run("pick_object", {"target": plate, "approach_offset": [0, 0, 0.1], "scan": scan})
        assert out.success and data["grasp_ok"]
        out, data = server.run("place_object", {"location": "drawer_top", "slot": "aside_1", "scan": scan})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out.success and data["slot"] == "aside_1"
    slot = srv.places()["drawer_top"]["place_slots"]["aside_1"]["position"]
    pp = data["placed_pose"]
    assert 0.0 < math.dist(pp["position"][:2], slot[:2]) <= srv.prm()["place"]["slot_fit_max_mm"] / 1000.0 + 1e-9
    g = dict(srv.prm()["gripper"], wall_offset_mm=srv.prm()["drawer_wall_offset_mm"]["drawer_top"])
    assert server.ss.mp.wall_blocks_grasp(target={"pose": dict(pp, yaw_valid=True)}, size_m=srv.item("cover_plate")[0],
                                          interior_m=srv.places()["drawer_top"]["interior_m"], g=g) is None


def test_long_side_held_place_checks_fingers_at_the_ends(server):
    """[P2 시뮬레이션 10/10] 긴 변 양끝을 쥔 물체를 서랍 안에 놓을 때 손가락은 긴 변 끝 — 끝 바로 옆 이웃(손가락 자리)이면 PLACE_BLOCKED.
    (명령한 자리 그대로의 판단만 보려고 되돌리기 비켜 놓기 restore_fit_max_mm 은 끔)"""
    srv = server.srv
    prm = srv.prm()
    prm["place"] = dict(prm["place"], restore_fit_max_mm=0.0)
    srv.prm = lambda: prm
    er = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
          "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": math.pi / 2, "yaw_valid": True}}   # 가로 → 긴 변
    server.Gripper.holding, server.Gripper.held_width = True, 52.0
    try:
        out, _ = server.run("pick_object", {"target": er, "approach_offset": [0, 0, 0.1]})
        assert out.success and srv.held["long_side"] is True
        nb = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.0185,                              # 놓을 자리 긴 변 끝에서 35 mm
              "pose": {"frame": "drawer_top", "position": [0.10, 0.10 + 0.02625 + 0.035, 0.0], "yaw": 0.0, "yaw_valid": True}}
        scan = {"target_found": True, "target": er, "candidates": [nb], "visible_count": 2}
        out, data = server.run("place_object", {"location": "drawer_top", "scan": scan,
                                                "pose": {"frame": "drawer_top", "position": [0.10, 0.10, 0.0], "yaw": math.pi / 2}})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out.error_code == "PLACE_BLOCKED" and data["blocked_by"] == "caramel_box#1"


def test_aside_place_keeps_remaining_object_pickable(server):
    """[P2 무작위 배치 10/10] aside 에 놓을 때 남은 물건(립밤)의 벌린 손가락 자리를 막지 않는 자리로 — 못 찾으면 PLACE_BLOCKED (예외 아님)."""
    srv = server.srv
    slot = srv.places()["drawer_top"]["place_slots"]["aside_1"]["position"]
    er = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
          "pose": {"frame": "drawer_top", "position": [0.12, 0.20, 0.0], "yaw": 0.0, "yaw_valid": True}}
    lip = {"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.020,
           "pose": {"frame": "drawer_top", "position": [slot[0], slot[1] + 0.045, 0.0], "yaw": 0.0, "yaw_valid": True}}
    scan = {"target_found": True, "target": er, "candidates": [lip], "visible_count": 2}
    server.Gripper.holding = True
    try:
        out, _ = server.run("pick_object", {"target": er, "approach_offset": [0, 0, 0.1], "scan": scan})
        assert out.success
        out, data = server.run("place_object", {"location": "drawer_top", "slot": "aside_1", "scan": scan})
    finally:
        server.Gripper.holding = False
    assert out.error_code != "SKILL_EXCEPTION"
    if out.success:
        me = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115, "pose": dict(data["placed_pose"], yaw_valid=True)}
        g = srv.prm()["gripper"]
        lt = {**lip, "pose": {**lip["pose"], "yaw": math.pi / 2}}                      # 립밤은 긴 변으로 잡음
        assert server.ss.nc.pick_blocker(target=lt, size_m=[0.02, 0.0718, 0.02], open_mm=84.8, objects=[me], size_of=srv._size_or_none,
                                         default_size_m=[0.06, 0.06, 0.06], finger_mm=g["fingertip_outer_mm"], margin_mm=5.0,
                                         support_m=0.0, below_tol_m=0.003, finger_half_width_mm=g["tip_radius_mm"]) is None
    else:
        assert out.error_code in ("PLACE_BLOCKED", "WALL_TOO_CLOSE")


@pytest.mark.parametrize("allow", [False, True])
def test_place_in_drawer_on_top_of_object_only_when_allowed(server, allow):
    """[P2 시뮬레이션 10/11] 쌓기 원위치 복구 — 명령한 pose 가 캐러멜 위면 place.allow_stack_place 일 때만 캐러멜 윗면에 놓음.
    기본(false)은 지금 계약(#166, 지지면 바닥)대로 PLACE_BLOCKED, 움직임 없음."""
    srv = server.srv
    grips = _holding_in_drawer(server)
    prm = srv.prm()
    prm["place"]["allow_stack_place"] = allow
    srv.prm = lambda: prm
    at = {"frame": "drawer_top", "position": [0.10, 0.12, 0.0], "yaw": 0.0}
    scan = json.loads(json.dumps(EMPTY_SCAN))
    scan["candidates"].append({"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.025, "pose": dict(at, yaw_valid=True)})
    out, data = server.run("place_object", {"location": "drawer_top", "pose": at, "scan": scan})
    if not allow:
        assert out.error_code == "PLACE_BLOCKED" and data["blocked_by"] == "caramel_box#1"
        assert srv.robot.log == [] and grips == []
        return
    assert out.success, out.reason
    from ready2go_skills.core import place_plan as plp
    place = srv.places()["drawer_top"]
    pos_m, _ = plp.place_tcp_m(place["tf"], at, 0.025 + 0.02 + prm["place"]["drop_m"])
    low = min((p for e in srv.robot.log if e[0] in ("movel", "moveb") for p in ([e[1]] if e[0] == "movel" else e[1])), key=lambda p: p[2])
    assert low[2] == pytest.approx(1000.0 * pos_m[2] - prm["place"]["touch_overtravel_mm"], abs=1e-6)   # 캐러멜 윗면 기준


def test_place_in_slot_leaves_room_for_vision_error(server):
    """[P2 시뮬레이션 10/11] 고정 자리는 다시 볼 때 ±repick_noise 만큼 틀려도 넛지 없이 다시 집을 수 있게 — 벽에 바짝인 자리는 안쪽으로 옮겨 놓음."""
    srv = server.srv
    _holding_in_drawer(server, {"aside_1": {"position": [0.05, 0.05, 0.0], "yaw": 0.0}, "aside_2": None})
    out, data = server.run("place_object", {"location": "drawer_top", "slot": "aside_1", "scan": EMPTY_SCAN})
    assert out.success, out.reason
    from ready2go_skills.core import motion_plan as mp
    prm, place = srv.prm(), srv.places()["drawer_top"]
    p = data["placed_pose"]
    assert p["position"][:2] != [0.05, 0.05]
    gw = dict(prm["gripper"], round=True, max_open_mm=prm["pick"]["max_open_width_m"] * 1000.0, tilt_align_deg=prm["pick"]["tilt_align_deg"],
              axis_grasp=True, front_tilt_within_mm=prm["pick"]["front_tilt_within_mm"],
              wall_offset_mm=(prm.get("drawer_wall_offset_mm") or {}).get("drawer_top"),
              wall_tcp_min_mm=(prm["drag"].get("wall_tcp_min_by_drawer_mm") or {}).get("drawer_top"))
    size, _ = srv.item("lip_balm")
    for dx in (-0.003, 0.003):
        for dy in (-0.003, 0.003):
            q = dict(p, position=[p["position"][0] + dx, p["position"][1] + dy, 0.0], yaw_valid=True)
            dp = mp.plan_drag(target={"pose": q}, size_m=size, interior_m=place["interior_m"], g=gw, drag=prm["drag"])
            assert not dp.needed and dp.error_code is None, dp.reason


def test_yaml_cache_keeps_last_good_while_file_is_being_written(server, tmp_path):
    """[P2 시뮬레이션 10/11] 돌리는 중 skills.yaml 을 저장하면 빈 파일·반쯤 쓴 파일을 읽어 None → SKILL_EXCEPTION.
    깨진 값이면 전 값을 돌려주고, 제대로 다 쓰이면 새 값."""
    f = tmp_path / "p.yaml"
    f.write_text("a: 1\n", encoding="utf-8")
    yc = server.ss._yaml_cached
    assert yc(f) == {"a": 1}
    f.write_text("", encoding="utf-8")
    assert yc(f) == {"a": 1}
    f.write_text("a: [1, 2\n", encoding="utf-8")
    assert yc(f) == {"a": 1}
    f.write_text("a: 22\n", encoding="utf-8")
    assert yc(f) == {"a": 22}


@pytest.mark.parametrize("drawer, stuck", [("drawer_top", True), ("drawer_bottom", False)])
def test_open_bottom_drawer_tolerates_stronger_start_resistance(server, monkeypatch, drawer, stuck):
    """[실측 PC2 10/11] 아래 칸은 꽉 맞물려 인출 7.3 mm 에서 34.9 N → 30 N 기준으로 DRAWER_STUCK. 아래 칸만 stuck_force_by_drawer_n(45 N)."""
    srv = server.srv
    srv.disp = {}
    srv.robot.j = list(srv.poses()["drawer_approach"][drawer])
    server.Gripper.holding = True                                       # 손잡이 잡음
    pulling = {}
    srv.robot.force = lambda p: [0.0, -35.0 if pulling.get("on") else 0.0, 0.0, 0.0, 0.0, 0.0]   # 여는 방향(+y) 반대 저항 35 N
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        pulling["on"] = stage == "pull"
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    out, _ = server.run("drawer_control", {"drawer_id": drawer, "state": "open"})
    assert (out.error_code == "DRAWER_STUCK") if stuck else out.success, out.reason


def test_nudge_pushes_from_behind_to_handle_wall(server, monkeypatch):
    """[사용자 10/11 PC2] 손잡이 쪽 벽 근처 비스듬한 지우개 — 뒤에서 닫은 손가락 옆면으로 밂. 힘으로 끝을 찾지 않고 계산한 끝
    (벽에 붙어 누운 지우개 뒤 = 11 + 11 + 손가락 옆면 9 mm)까지, 그다음 push_back_mm 물러났다가 올림(벽에 낀 지우개가 딸려 올라옴)."""
    from ready2go_skills.core import motion_plan as mp
    srv = server.srv
    d = srv.prm()["drag"]
    tf = srv.places()["drawer_top"]["tf"]
    target = {"id": "eraser#1", "class": "eraser", "top_z": 0.013,
              "pose": {"frame": "drawer_top", "position": [0.0314, 0.0388, 0.0], "yaw": -1.1321, "yaw_valid": True}}
    stages, speeds = [], {}
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        stages.append(stage)
        speeds[stage] = vel
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": target})
    assert out.success, out.reason
    i = stages.index("push")
    assert stages[i - 1] == "push_down" and stages[i + 1:i + 3] == ["push_back", "lift"] and "press" not in stages
    assert speeds["push"] == speeds["push_back"] == d["push_speed_mm_s"]
    moves = [e[1] for e in srv.robot.log if e != "stop" and e[0] == "movel"]
    a, b, c = (mp.from_base(tf, [v / 1000.0 for v in m[:3]]) for m in moves[i - 1:i + 2])
    assert b[0] * 1000.0 == pytest.approx(11.0 + 11.0 + 9.0 - d["push_over_mm"], abs=0.1) and abs(b[1] - a[1]) < 1e-3   # 계산한 끝, x 로만
    assert (c[0] - b[0]) * 1000.0 == pytest.approx(d["push_back_mm"], abs=0.1) and abs(c[2] - b[2]) < 1e-4            # 같은 높이로 물러남
    assert data["target_after"]["pose"]["yaw"] == pytest.approx(-math.pi / 2)
    assert data["push_vector_m"][0] < 0 and data["push_vector_m"][1] == 0.0


def test_handle_side_tilted_long_grasp_goes_deeper(server, monkeypatch):
    """[사용자 10/11 PC2] 손잡이 쪽 벽에 가로로 붙은 지우개를 기울여 긴 변으로 잡으면 x·y 는 맞는데 덜 내려가 불안정
    → 수직 잡기 높이보다 pick.front_tilt_lower_mm 더 내림."""
    from ready2go_skills.core import motion_plan as mp
    srv = server.srv
    tf = srv.places()["drawer_top"]["tf"]
    target = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
              "pose": {"frame": "drawer_top", "position": [0.0129, 0.0714, 0.0], "yaw": -1.5644, "yaw_valid": True}}   # y 는 옆벽 표(10/12) 여유
    lows = {}
    server.Gripper.holding, server.Gripper.held_width = True, 52.5        # 긴 변 양끝 쥠
    for lower in (0.0, 5.0):
        prm = srv.prm()
        prm["pick"]["front_tilt_lower_mm"] = lower
        prm["pick"]["grip_height_ratio"] = None                          # 예전(윗면 높이) 방식에서의 기울여 잡기 더 내림
        monkeypatch.setattr(srv, "prm", lambda prm=prm: prm)
        srv.robot.log.clear()
        out, data = server.run("pick_object", {"target": target, "approach_offset": [0, 0, 0.1]})
        assert out.success and "긴 변" in out.reason, out.reason
        pts = [p for e in srv.robot.log if e != "stop" and e[0] in ("movel", "moveb") for p in ([e[1]] if e[0] == "movel" else e[1])]
        lows[lower] = min(mp.from_base(tf, [v / 1000.0 for v in p[:3]])[2] for p in pts)
        srv.held = None
    assert (lows[0.0] - lows[5.0]) * 1000.0 == pytest.approx(5.0, abs=0.05)


def test_dry_pick_reports_handle_side_tilt(server):
    """빈 자리 고르기(clear_plan.find_free_pose)가 읽는 DryOracle.last_pick_tilted — 손잡이 쪽 벽에 가로로 붙은 지우개는 기울여 잡음,
    가운데는 수직 [트윈 재생 10/13 A]. 판단만 — 로봇 명령 없음."""
    srv = server.srv
    near = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115, "occluded_by": [],
            "pose": {"frame": "drawer_top", "position": [0.0129, 0.0714, 0.0], "yaw": -1.5644, "yaw_valid": True}}
    mid = dict(near, pose=dict(near["pose"], position=[0.1, 0.15, 0.0], yaw=0.0))
    oracle = server.ss.DryOracle(srv, "drawer_top")
    n = len(srv.robot.log)
    assert oracle.pick([near], "eraser#1")[0] and oracle.last_pick_tilted
    assert oracle.pick([mid], "eraser#1")[0] and not oracle.last_pick_tilted
    assert len(srv.robot.log) == n


def test_pick_height_by_tip_table_without_touch(server):
    """[사용자 10/11 "넛지 빼고 온톨로지 높이 반영, 벌려서 높이만큼 빠르게 내려가 집기"]: 닫은 손끝(잡는 폭 — 손끝 표)이
    바닥 위 온톨로지 높이 × grip_height_ratio. 바닥 찍기·천천히 내려가기 없이 블렌딩 한 번으로 잡는 높이까지."""
    from ready2go_skills.core import motion_plan as mp
    srv = server.srv
    prm = srv.prm()
    g = prm["gripper"]
    target = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.0185,
              "pose": {"frame": "drawer_top", "position": [0.1117, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}
    server.Gripper.holding, server.Gripper.held_width = True, 43.2   # 캐러멜 짧은 변 잡은 폭 [실측 PC2 10/11, grasp_width_m]
    out, _ = server.run("pick_object", {"target": target, "approach_offset": [0, 0, 0.1]})
    assert out.success, out.reason
    closed_tip = srv.held["tcp_above_floor_m"] * 1000.0 - mp.tip_below_tcp_mm(43.2, g)
    assert closed_tip == pytest.approx(ONTO_H_MM["caramel_box"] * prm["pick"]["grip_height_ratio"], abs=0.1)
    stages = [e for e in srv.robot.log if e != "stop" and e[0] == "movel"]
    assert not any(e[3] == prm["speed"]["grasp_mm_s"] for e in stages if len(e) > 3)


def test_long_side_grasp_accepts_slightly_skewed_box_width(server):
    """[실측 PC2 10/11] 캐러멜(버니어 75 × 49, #8) 긴 변 양끝 — 비전 각도 약 6° 틀려 비스듬히 물려 79.7 → WIDTH_MISMATCH 였음.
    긴 변 잡기는 long_side_yaw_slack_deg 만큼 비스듬한 폭까지 허용, 그보다 크면 여전히 실패."""
    srv = server.srv
    target = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.0185,
              "pose": {"frame": "drawer_top", "position": [0.1268, 0.1649, 0.0], "yaw": 1.5708, "yaw_valid": True}}
    for width, ok in ((79.7, True), (86.0, False)):
        srv.held = None
        server.Gripper.holding, server.Gripper.held_width = True, width
        out, _ = server.run("pick_object", {"target": target, "approach_offset": [0, 0, 0.1]})
        assert out.success == ok, out.reason
        assert ok or "WIDTH_MISMATCH" in out.reason


def test_cover_plate_gripped_at_plate_height_not_floor(server):
    """[실측 A 10/03, #8] 덮개 판은 다리 볼트 위 판(아랫면 21, 두께 8 mm) — 바닥 찍은 뒤 닫은 손끝을 판 가운데(25 mm)에."""
    from ready2go_skills.core import motion_plan as mp
    srv = server.srv
    g = srv.prm()["gripper"]
    target = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.0405,
              "pose": {"frame": "drawer_top", "position": [0.11, 0.18, 0.0], "yaw": 0.0, "yaw_valid": True}}
    tf = srv.places()["drawer_top"]["tf"]
    open_tip = mp.tip_below_tcp_mm(74.2 + g["open_margin_mm"], g)
    srv.robot.force = lambda p: [0.0, 0.0, max(0.0, -8.0 * (mp.from_base(tf, [v / 1000.0 for v in p[:3]])[2] * 1000.0 - open_tip)),
                                 0.0, 0.0, 0.0]                         # 벌린 손끝이 바닥에 닿으면 힘
    server.Gripper.holding, server.Gripper.held_width = True, 74.2
    out, _ = server.run("pick_object", {"target": target, "approach_offset": [0, 0, 0.1]})
    assert out.success, out.reason
    closed_tip = srv.held["tcp_above_floor_m"] * 1000.0 - mp.tip_below_tcp_mm(74.2, g)
    want = srv.prm()["pick"]["tip_above_floor_by_class_mm"]["cover_plate"]
    assert want - 2.0 < closed_tip < want + 1.0                          # 물건별 손끝 높이 (10/12 사용자 실물 25 → 20)


def test_stacked_eraser_on_caramel_uses_ontology_height_not_vision_depth(server):
    """[사용자 10/11 PC2] 비전이 캐러멜 윗면을 7~9 mm 높게 봄(25~27 / 18.5) → 지우개 받침을 비전으로 재면 높게 헛잡음.
    scan 에 밑에 깔린 캐러멜이 있으면 받침 = 캐러멜 온톨로지 높이 18.5."""
    er = {"id": "eraser#1", "class": "eraser", "top_z": 0.039,
          "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}
    ca = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.027,
          "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 1.5708, "yaw_valid": True}}
    scan = {"target_found": True, "target": er, "candidates": [ca], "visible_count": 2}
    server.Gripper.holding, server.Gripper.held_width = True, 22.0
    out, _ = server.run("pick_object", {"target": er, "approach_offset": [0, 0, 0.1], "scan": scan})
    assert out.success and _support_mm(out.reason) == pytest.approx(ONTO_H_MM["caramel_box"], abs=0.05), out.reason


def test_gripper_sensor_invalid_never_turns_held_into_empty_hand(server, monkeypatch):
    """[P2 체크리스트 5 — B] 그리퍼 폭을 못 읽으면(NaN) 쥐었는지 모름 → OBJECT_DROPPED·빈손으로 바꾸지 않고 SENSOR_INVALID,
    그리퍼 명령 없음. ① 옮기는 중(트레이) ② 서랍 안 놓기 직전 ③ 집고 들어 올린 뒤."""
    srv = server.srv
    grips = _holding_in_drawer(server)
    server.Gripper.width = float("nan")
    out, data = server.run("place_object", {"location": "handover_zone"})
    assert out.error_code == "SENSOR_INVALID" and srv.held is not None and grips == []
    out, data = server.run("place_object", {"location": "drawer_top", "pose": ASIDE_POSE, "scan": EMPTY_SCAN})
    assert out.error_code == "SENSOR_INVALID" and srv.held is not None and grips == [] and data["placed_pose"] is None
    srv.held = None
    server.Gripper.holding, server.Gripper.held_width = True, float("nan")   # 닫은 폭부터 못 읽음
    out, data = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    assert out.error_code == "SENSOR_INVALID" and srv.held is not None and data["grasp_ok"] is False
    assert data["hand"] == "unknown" and data["grasp_evidence"]["closed_width_m"] is None


def _on_lift(server, fn):
    """닫아서 잡은 뒤(그리퍼 폭 = 쥔 폭) 들어 올리기(stage lift) 이동에 끼어듦 — fn() 이 Outcome 을 돌려주면 그걸로 실패."""
    srv, G = server.srv, server.Gripper
    real_line, real_blend = srv._line, srv._blend

    def hit(stage):
        return stage == "lift" and G.holding and G.width == G.held_width and fn()

    def line(goal, target, vel, stage, **kw):
        return hit(stage) or real_line(goal, target, vel, stage, **kw)

    def blend(goal, pts, radii, vel, stage, **kw):
        return hit(stage) or real_blend(goal, pts, radii, vel, stage, **kw)
    srv._line, srv._blend = line, blend


def test_pick_output_separates_grasp_result_from_measured_hand(server):
    """[P2 4절·Critical] pick 결과에 파지 성공(grasp_ok)과 손 상태(hand)를 따로, verify 근거(닫은 폭·grip_detected·들어 올린 뒤)를 같이."""
    srv = server.srv
    server.Gripper.holding, server.Gripper.held_width = True, 22.0
    out, data = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    assert out.success and data["grasp_ok"] is True and data["hand"] == "holding"
    ev = data["grasp_evidence"]
    assert ev["closed_width_m"] == pytest.approx(0.022) and ev["closed_width_m"] > ev["min_width_m"] == pytest.approx(0.010)
    assert ev["grasp_detected"] is True and ev["close"] == "OK" and ev["lift"] == "HELD"
    json.loads(json.dumps(data))                                         # NaN 없이 JSON 으로 나감
    srv.held = None
    server.Gripper.holding = False                                       # 빈손 닫힘 0.9 mm → 다시 벌림 = released (빈손 확정 아님 [#43 결정 10])
    out, data = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    assert out.error_code == "GRASP_FAILED" and data["grasp_ok"] is False and data["hand"] == "released" and srv.held is None
    assert data["grasp_evidence"]["close"] == "EMPTY_CLOSE"


PICK_EXAMPLES = {c["case"]: c for c in json.loads((REPO / "contracts/examples/pick_object_result.json").read_text(encoding="utf-8"))["cases"]}


def test_pick_result_example_matches_node_output(server):
    """contracts/examples/pick_object_result.json 의 다섯 경우를 노드로 그대로 — error_code·output 이 예시와 같음 (PR #223)."""
    srv, G = server.srv, server.Gripper
    def pick():
        return server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})

    def same(name, out, data):
        ex = PICK_EXAMPLES[name]
        assert (out.success, out.error_code, data) == (ex["success"], ex["error_code"], ex["output"]), name
    G.holding, G.held_width = True, 22.0
    same("held", *pick())
    srv.held, G.holding = None, False
    same("empty_close", *pick())
    G.holding, G.held_width = True, float("nan")
    same("close_width_invalid", *pick())
    srv.held, G.held_width = None, 22.0
    real = srv._line, srv._blend

    def drop():
        G.width = 0.9
    _on_lift(server, drop)
    same("lift_dropped", *pick())
    srv._line, srv._blend = real
    _on_lift(server, lambda: sf.Outcome(False, sf.ESTOP, reason="비상정지"))
    same("stopped_while_lifting", *pick())


def test_pick_stopped_while_lifting_keeps_held_object(server):
    """[P2 5절 보유 불명확] 닫아서 잡은 뒤 들어 올리다 멈추면(비상정지 등) 빈손으로 보지 않음 — 쥔 기억 유지, hand unknown.
    (전에는 들어 올린 뒤 검사까지 가야 held 를 정해서, 그 사이 멈추면 다음 집기가 그리퍼를 벌려 떨어뜨릴 수 있었음)"""
    srv = server.srv
    server.Gripper.holding, server.Gripper.held_width = True, 22.0
    _on_lift(server, lambda: sf.Outcome(False, sf.ESTOP, reason="비상정지"))
    out, data = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    assert out.error_code == sf.ESTOP and data["hand"] == "unknown" and data["grasp_ok"] is False
    assert srv.held is not None and srv.held["width_m"] == pytest.approx(0.022)
    out, _ = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    assert out.error_code == server.ss.HOLDING_OBJECT                    # 다음 집기는 움직이기 전에 거부


def test_pick_dropped_while_lifting_is_measured_empty_hand(server):
    """들어 올리다 폭이 빈손 닫힘까지 줄면(DROPPED) 실측 빈손 — 쥔 기억 지움, hand empty."""
    srv = server.srv
    server.Gripper.holding, server.Gripper.held_width = True, 22.0

    def drop():
        server.Gripper.width = 0.9
        return None
    _on_lift(server, drop)
    out, data = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    assert out.error_code == "GRASP_FAILED" and data["hand"] == "empty" and srv.held is None
    assert data["grasp_evidence"]["lift"] == "DROPPED" and data["grasp_evidence"]["lift_width_m"] == pytest.approx(0.0009)


def test_front_panel_clearance_table_matches_touch_measurements(server):
    """[실측 PC2 10/11] 수직 그리퍼·닫힘 축 서랍 x 로 앞판에 닿기 직전 TCP: 벌림 66 → 59.3 mm, 100.3 → 75.1 mm.
    손잡이 쪽 벽(front)만 이 값, 안쪽 벽은 옆벽 표 그대로."""
    g, mp = server.srv.prm()["gripper"], server.ss.mp
    assert mp.wall_extent_mm(66.0, 0.0, g, front=True) == pytest.approx(59.3)
    assert mp.wall_extent_mm(100.3, 0.0, g, front=True) == pytest.approx(75.1)
    assert mp.wall_extent_mm(66.0, 0.0, g) < 59.3                      # 옆벽 표(10/12 아래 칸 실측으로 고침)는 앞판보다 조금 작음
    assert mp.wall_extent_mm(66.0, math.pi / 2, g, front=True) == pytest.approx(g["wall_clearance_mm"]["along_mm"])   # 닫힘 축이 앞판과 나란하면 그대로


def test_vertical_eraser_near_front_does_not_switch_to_long_side_into_front_panel(server):
    """[실측 PC2 10/11 충돌] 세로 지우개(손잡이 쪽 벽에서 57.4 mm), 짧은 변 손가락 자리에 몽키 → 긴 변 양끝으로 바꿔 65.5 mm 벌리고
    내려가다 앞판에 닿음. 앞판 여유(front_across)로 긴 변 우회가 막혀 움직이기 전 NEIGHBOR_TOO_CLOSE."""
    srv = server.srv
    er = {"id": "eraser#1", "class": "eraser", "top_z": 0.015, "occluded_by": [],
          "pose": {"frame": "drawer_top", "position": [0.0574, 0.1494, 0.0], "yaw": -0.2316, "yaw_valid": True}}
    wr = {"id": "toy_wrench#1", "class": "toy_wrench", "top_z": 0.0159, "occluded_by": None,
          "pose": {"frame": "drawer_top", "position": [0.0795, 0.217, 0.0], "yaw": 0.1254, "yaw_valid": True}}
    scan = {"target_found": True, "target": er, "candidates": [wr], "visible_count": 2}
    grips = []
    srv._grip = lambda *a: grips.append(a)
    out, _ = server.run("pick_object", {"target": json.loads(json.dumps(er)), "approach_offset": [0, 0, 0.1], "scan": scan})
    assert out.error_code == server.ss.NEIGHBOR_TOO_CLOSE and "toy_wrench" in out.reason, out.reason
    assert srv.robot.log == [] and grips == []


def test_tray_slots_kept_in_file_and_cleared_by_deleting_it(server, tmp_path):
    """[사용자 10/11] 트레이 쓴 칸을 파일에도 — `B trayclear`(파일 삭제)로 비움을 알리면 서버 재시작 없이 다음 놓기는 1번 칸."""
    srv = server.srv
    srv.tray_file = tmp_path / "tray.json"
    srv.tray = {}
    slots = []
    for _ in range(2):
        _holding_in_drawer(server)
        out, data = server.run("place_object", {"location": "handover_zone"})
        assert out.success, out.reason
        slots.append(data["slot"])
    assert slots == ["handover_zone_1", "handover_zone_2"]
    assert json.loads(srv.tray_file.read_text()) == {"handover_zone": [0, 1]}
    srv.tray_file.unlink()                                              # B trayclear
    _holding_in_drawer(server)
    out, data = server.run("place_object", {"location": "handover_zone"})
    assert out.success and data["slot"] == "handover_zone_1"


@pytest.mark.parametrize("cls, grasp_w, head_w", [("toy_wrench", 25.9, 61.0), ("toy_hammer", 15.5, 75.0)])
def test_handle_items_open_by_grasp_width_not_head(server, cls, grasp_w, head_w):
    """[사용자 10/11 PC2 "몽키 엄청 벌리고 내려감"] pick.open_by_grasp_width: 벌림 = 손잡이 폭 + 13 mm (머리 폭 + 13 이 아님)."""
    srv = server.srv
    t = {"id": f"{cls}#1", "class": cls, "top_z": 0.025,
         "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}
    server.Gripper.holding, server.Gripper.held_width = True, grasp_w
    grips, real = [], srv._grip
    srv._grip = lambda w, f: grips.append(w) or real(w, f)
    try:
        out, data = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out.success, out.reason
    opens = [round(w, 1) for w in grips if w > 1.0]
    assert round(grasp_w + 13.0, 1) in opens and round(head_w + 13.0, 1) not in opens, opens


@pytest.mark.parametrize("lip_x, ok", [(0.039, True), (0.090, "under")])
def test_restore_slightly_blocked_origin_shifts_within_tolerance(server, lip_x, ok):
    """[PC2 10/12 Unpacking 덤프 05:31~05:32] 가림막을 들 때 밑에 깔린 립밤이 굴러 원래 자리 가장자리를 ~10 mm 막음 → 원래 자리
    놓기 거부 → Runner 가 aside_1 에서 집어 aside_1 에 다시 놓음. 되돌리기(명령한 pose)는 restore_fit_max_mm 안에서 방향은 그대로
    가장 적게 옮겨 놓음. 원래 자리 한가운데(판 가운데 밑으로 다리 사이를 지나는 립밤)는 10/13부터 판 밑에 들어가는 것으로 보고
    그 자리 그대로 놓음 [사용자 10/13 "원복 때도 판 밑엔 물건이 들어갈 수 있다"] — 예전엔 거부(20 mm 로 못 비킴)."""
    srv = server.srv
    srv.disp["drawer_bottom"] = srv.places()["drawer_bottom"]["tf_at_travel_m"]
    plate = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.0352,
             "pose": {"frame": "drawer_bottom", "position": [0.081, 0.066, 0.0], "yaw": -1.569, "yaw_valid": True}}
    lip = {"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.0219,
           "pose": {"frame": "drawer_bottom", "position": [lip_x, 0.202, 0.0], "yaw": 1.534, "yaw_valid": True}}
    scan = {"target_found": False, "target": None, "candidates": [plate, lip], "visible_count": 2}
    origin = {"frame": "drawer_bottom", "position": [0.091, 0.167, 0.0], "yaw": -0.054}
    server.Gripper.holding, server.Gripper.held_width = True, 74.2
    try:
        out, _ = server.run("pick_object", {"target": plate, "approach_offset": [0, 0, 0.1], "scan": scan})
        assert out.success, out.reason
        out, data = server.run("place_object", {"location": "drawer_bottom", "pose": origin, "scan": scan})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out.success, out.reason
    if ok == "under":
        assert data["placed_pose"]["position"][:2] == pytest.approx(origin["position"][:2])
    else:
        pp = data["placed_pose"]
        moved = math.dist(pp["position"][:2], origin["position"][:2])
        assert 0.0 < moved <= srv.prm()["place"]["restore_fit_max_mm"] / 1000.0 + 1e-9
        assert pp["yaw"] == pytest.approx(origin["yaw"]) and srv.held is None


def test_restore_fit_zero_keeps_old_refusal(server):
    """restore_fit_max_mm 0 = 예전처럼 명령한 pose 그대로만 (막히면 거부)."""
    srv = server.srv
    srv.disp["drawer_bottom"] = srv.places()["drawer_bottom"]["tf_at_travel_m"]
    prm = srv.prm()
    prm["place"] = dict(prm["place"], restore_fit_max_mm=0.0)
    srv.prm = lambda: prm
    plate = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.0352,
             "pose": {"frame": "drawer_bottom", "position": [0.081, 0.066, 0.0], "yaw": -1.569, "yaw_valid": True}}
    lip = {"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.0219,
           "pose": {"frame": "drawer_bottom", "position": [0.039, 0.202, 0.0], "yaw": 1.534, "yaw_valid": True}}
    scan = {"target_found": False, "target": None, "candidates": [plate, lip], "visible_count": 2}
    server.Gripper.holding, server.Gripper.held_width = True, 74.2
    try:
        out, _ = server.run("pick_object", {"target": plate, "approach_offset": [0, 0, 0.1], "scan": scan})
        assert out.success, out.reason
        out, data = server.run("place_object", {"location": "drawer_bottom", "scan": scan,
                                                "pose": {"frame": "drawer_bottom", "position": [0.091, 0.167, 0.0], "yaw": -0.054}})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert not out.success and data["blocked_by"] == "lip_balm#1"


# [PC2 10/12 Unpacking run 2026-10-12T06:11:39Z_7d18c6, 덤프 061201_881Z] 판 밑 지우개·립밤이 aside 쪽으로 조금 보임, aside 는 비어 있음
SCAN_1012_PLATE = {"target_found": True, "target": {"id": "eraser#1", "class": "eraser", "pose": {"frame": "drawer_bottom", "position": [0.0772, 0.1443, 0.0], "yaw": 0.0, "yaw_valid": False}, "top_z": 0.0144, "occluded_by": ["cover_plate#1"], "visible_area_m2": 0.000492},
                   "candidates": [{"id": "cover_plate#1", "class": "cover_plate", "pose": {"frame": "drawer_bottom", "position": [0.0749, 0.1944, 0.0], "yaw": -0.2191, "yaw_valid": True}, "top_z": 0.0349, "occluded_by": [], "visible_area_m2": 0.007301},
                                  {"id": "lip_balm#1", "class": "lip_balm", "pose": {"frame": "drawer_bottom", "position": [0.0401, 0.145, 0.0], "yaw": 0.0, "yaw_valid": False}, "top_z": 0.0216, "occluded_by": ["cover_plate#1"], "visible_area_m2": 0.000708}],
                   "visible_count": 3}


def _plate_held(server, scan):
    srv = server.srv
    srv.disp["drawer_bottom"] = srv.places()["drawer_bottom"]["tf_at_travel_m"]
    plate = next(c for c in scan["candidates"] if c["class"] == "cover_plate")
    server.Gripper.holding, server.Gripper.held_width = True, 74.2
    out, _ = server.run("pick_object", {"target": plate, "approach_offset": [0, 0, 0.1]})      # Runner s7.1 은 scan 없이 집음
    assert out.success, out.reason
    return plate


@pytest.mark.parametrize("slot, ok", [("aside_1", False), ("aside_2", True)])
def test_aside_unknown_yaw_neighbor_only_blocks_object_or_finger_band(server, slot, ok):
    """[PC2 10/12 run 7d18c6] 판 밑 지우개는 방향 모름 → 명목 정사각형(57 mm) 그대로 (fail-closed, 보이는 면적으로 안 줄임 [#241 리뷰 P1]).
    다만 놓을 자리는 '판 + 여유'와 '손가락이 내려가는 띠'만 봄(집기와 같음) [사용자 10/12 PC2 립밤 되돌리기 거부]:
    aside_2 는 정사각형이 판 끝 옆 빈 곳에만 걸려 통과, aside_1 은 판·손가락 띠에 걸려 그대로 거부."""
    scan = json.loads(json.dumps(SCAN_1012_PLATE))
    try:
        _plate_held(server, scan)
        out, data = server.run("place_object", {"location": "drawer_bottom", "slot": slot, "scan": scan})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    if ok:
        assert out.success and data["placed_pose"] is not None and server.srv.held is None
    else:
        assert not out.success and out.error_code == "PLACE_BLOCKED" and data["blocked_by"] == "eraser#1"
        assert data["placed_pose"] is None and server.srv.held is not None


@pytest.mark.parametrize("where, ok", [("center_along", True), ("center_across", True), ("leg_corner", "shift"), ("tall", False),
                                       ("target", False)])
def test_cover_plate_restore_over_object_that_fits_under(server, where, ok):
    """[사용자 10/13 PC2 "가림판 원상복구에 립밤이 있어 안 됨 — 원복 때도 판 밑엔 물건이 들어갈 수 있다"] 판을 원래 자리(pose)로
    되돌릴 때 판 밑(아랫면 21 mm)·다리 사이(65 × 35)로 들어가는 물체는 놓기 확인·받침에서 뺌. 다리 자리에 있으면 그 물체를 피해
    되돌리기 허용 거리(place.restore_fit_max_mm) 안에서 비켜 놓음. 키 큰 물체(장난감차)·찾는 목표는 그대로 막음."""
    scan = json.loads(json.dumps(SCAN_1012_PLATE))
    scan["candidates"] = [c for c in scan["candidates"] if c["class"] == "cover_plate"]
    try:
        plate = _plate_held(server, scan)
        x, y, yaw = plate["pose"]["position"][0], plate["pose"]["position"][1], plate["pose"]["yaw"]
        c, s_ = math.cos(yaw), math.sin(yaw)
        u, v, oy = {"center_along": (0.0, 0.0, yaw), "center_across": (0.0, 0.0, yaw + math.pi / 2),
                    "leg_corner": (0.041, 0.028, yaw), "tall": (0.0, 0.0, yaw), "target": (0.0, 0.0, yaw)}[where]
        lip = {"id": "lip_balm#1", "class": "lip_balm" if where != "tall" else "toy_car", "top_z": 0.0215 if where != "tall" else 0.0325,
               "occluded_by": [], "visible_area_m2": 0.0013,
               "pose": {"frame": "drawer_bottom", "position": [x + u * c - v * s_, y + u * s_ + v * c, 0.0], "yaw": oy, "yaw_valid": True}}
        rescan = ({"target_found": True, "target": lip, "candidates": [plate], "visible_count": 2} if where == "target" else
                  {"target_found": True, "target": plate, "candidates": [lip], "visible_count": 2})
        out, data = server.run("place_object", {"location": "drawer_bottom", "pose": {k: plate["pose"][k] for k in ("frame", "position", "yaw")},
                                                "scan": rescan})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    if ok == "shift":                                               # 다리가 립밤 위로 — 비켜 놓음 (다리 자리 밖으로)
        moved = math.dist(data["placed_pose"]["position"][:2], plate["pose"]["position"][:2])
        assert out.success and 0.0 < moved <= 0.021, (out.reason, moved)
    elif ok:
        assert out.success and data["placed_pose"] is not None, out.reason
        floor = 1000.0 * server.ss.pp.to_base(server.srv.places()["drawer_bottom"]["tf"], (x, y, 0.0))[2]
        low = min(e[1][2] for e in server.srv.robot.log if e != "stop" and e[0] == "movel")
        assert low < floor + 40.0                                   # 립밤 위(받침)가 아니라 바닥 기준으로 내려놓음
    else:
        assert not out.success and out.error_code == "PLACE_BLOCKED", out.reason


@pytest.mark.parametrize("on, top", [("surface", 0.029 + 0.0158), ("bolts", 0.0405 + 0.0158)])
def test_key_on_cover_plate_picks_and_restores_at_its_own_height(server, on, top):
    """[사용자 10/13 PC2 사진] 덮개 판 위 차키는 판 면(약 29 mm)에도, 나사 머리 위(약 40 mm)에도 놓임 — 판 온톨로지 높이 40.5
    (나사 포함)·판 비전 top_z(나사, 약 35)는 놓인 면이 아님. 집을 때 받침 = 차키 자기 윗면 − 차키 높이(비전), 되돌릴 때 그 높이 그대로."""
    D = "drawer_bottom"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    plate = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.035, "occluded_by": ["car_key#1"], "visible_area_m2": 0.006,
             "pose": {"frame": D, "position": [0.090, 0.170, 0.0], "yaw": 0.0, "yaw_valid": True}}
    key = {"id": "car_key#1", "class": "car_key", "top_z": top, "occluded_by": [], "visible_area_m2": 0.0027,
           "pose": {"frame": D, "position": [0.090, 0.170, 0.0], "yaw": 0.0, "yaw_valid": True}}   # 세로 → 짧은 변(39) 잡기
    scan = {"target_found": True, "target": key, "candidates": [plate], "visible_count": 2}
    server.Gripper.holding, server.Gripper.held_width = True, 39.0
    try:
        out, _ = server.run("pick_object", {"target": key, "approach_offset": [0, 0, 0.1], "scan": scan})
        assert out.success, out.reason
        assert srv.picked_from[-1]["support_m"] == pytest.approx(top - 0.0158, abs=1e-4)   # 판 온톨로지 40.5 아님
        held = dict(srv.held)
        lows = []
        for keep in (True, False):
            srv.held = dict(held)
            if not keep:
                srv.picked_from = []
            n = len(srv.robot.log)
            rescan = {"target_found": True, "target": dict(key), "candidates": [dict(plate, occluded_by=[])], "visible_count": 2}
            out, data = server.run("place_object", {"location": D, "pose": {k: key["pose"][k] for k in ("frame", "position", "yaw")},
                                                    "scan": rescan})
            assert out.success, out.reason
            lows.append(min(e[1][2] for e in srv.robot.log[n:] if e != "stop" and e[0] == "movel"))
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    # 기억한 받침(판 면 29 / 나사 40.5) vs 기억 없을 때 판 비전 top_z 35 — 차이만큼 낮게·높게 내려놓음
    assert lows[0] - lows[1] == pytest.approx(1000.0 * (top - 0.0158 - 0.035), abs=0.6)


def test_remembered_support_dropped_when_support_moved(server):
    """[트윈 재생 10/13 A] 몽키 → 캐러멜 → 차키 3단: 차키를 받침 37 mm 로 기억 → 캐러멜을 바닥에 복구한 뒤에도 37 mm 에 놓아
    16.5 mm 위에서 떨어뜨림. 받침이던 물체를 옮기면(집기) 그 기억은 버리고 지금 받침 비전 top_z 로 놓음. 받침이 그대로면 기억값."""
    D = "drawer_bottom"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    plate = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.035, "occluded_by": ["car_key#1"], "visible_area_m2": 0.006,
             "pose": {"frame": D, "position": [0.090, 0.170, 0.0], "yaw": 0.0, "yaw_valid": True}}
    key = {"id": "car_key#1", "class": "car_key", "top_z": 0.029 + 0.0158, "occluded_by": [], "visible_area_m2": 0.0027,
           "pose": {"frame": D, "position": [0.090, 0.170, 0.0], "yaw": 0.0, "yaw_valid": True}}
    scan = {"target_found": True, "target": key, "candidates": [plate], "visible_count": 2}
    pose = {k: key["pose"][k] for k in ("frame", "position", "yaw")}
    server.Gripper.holding, server.Gripper.held_width = True, 39.0
    try:
        out, _ = server.run("pick_object", {"target": key, "approach_offset": [0, 0, 0.1], "scan": scan})
        assert out.success, out.reason
        assert srv.picked_from[-1]["under"] == ["cover_plate"]
        held = dict(srv.held)
        lows = []
        for moved in (False, True):
            srv.held = dict(held)
            if moved:                                               # 판을 집어 옮겼다 (다시 같은 자리에 놓였더라도 높이는 다시 봄)
                srv._remember_pick("cover_plate", D, plate["pose"], 0.0)
                assert not any(r["class"] == "car_key" for r in srv.picked_from)
            n = len(srv.robot.log)
            rescan = {"target_found": True, "target": dict(key), "candidates": [dict(plate, occluded_by=[])], "visible_count": 2}
            out, _ = server.run("place_object", {"location": D, "pose": pose, "scan": rescan})
            assert out.success, out.reason
            lows.append(min(e[1][2] for e in srv.robot.log[n:] if e != "stop" and e[0] == "movel"))
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert lows[1] - lows[0] == pytest.approx(1000.0 * (0.035 - 0.029), abs=0.6)   # 기억(판 면 29) 대신 지금 판 top_z 35


def test_putback_onto_cover_plate_when_plate_center_test_misses(server):
    """[사용자 10/13 PC2 "판 위 너무 잘 집는데 putback 이 안 됨 — PLACE_BLOCKED cover_plate#1 와 겹침"] 판 위 물체 가운데가 판 비전
    footprint 밖(가려진 판 위치 치우침·판 끝 나사 위)이면 가운데 기준 받침 찾기(stack_support)가 못 찾음 → 집었던 자리로 되돌릴 땐
    그 자리 몸통과 겹치는 물체를 받침으로 보고 집을 때 받침 높이로 놓음. 기억이 없으면(다른 자리) 예전처럼 막음."""
    D = "drawer_bottom"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    plate = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.036, "occluded_by": ["car_key#1"], "visible_area_m2": 0.005,
             "pose": {"frame": D, "position": [0.090, 0.170, 0.0], "yaw": 0.0, "yaw_valid": True}}
    key = {"id": "car_key#1", "class": "car_key", "top_z": 0.0405 + 0.0158, "occluded_by": [], "visible_area_m2": 0.0027,
           "pose": {"frame": D, "position": [0.090, 0.210, 0.0], "yaw": 0.0, "yaw_valid": True}}   # 판 옆 끝(207.1)보다 3 mm 밖
    scan = {"target_found": True, "target": key, "candidates": [plate], "visible_count": 2}
    pose = {k: key["pose"][k] for k in ("frame", "position", "yaw")}
    server.Gripper.holding, server.Gripper.held_width = True, 39.0
    try:
        out, _ = server.run("pick_object", {"target": key, "approach_offset": [0, 0, 0.1], "scan": scan})
        assert out.success, out.reason
        held = dict(srv.held)
        n = len(srv.robot.log)
        out, data = server.run("place_object", {"location": D, "pose": pose, "scan": scan})        # B putback 과 같은 요청
        assert out.success, out.reason
        low = min(e[1][2] for e in srv.robot.log[n:] if e != "stop" and e[0] == "movel")
        srv.held, srv.picked_from = dict(held), []
        out2, _ = server.run("place_object", {"location": D, "pose": pose, "scan": scan})
        assert not out2.success and out2.error_code == "PLACE_BLOCKED" and "cover_plate#1" in out2.reason
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    floor = 1000.0 * server.ss.pp.to_base(srv.places()[D]["tf"], (0.090, 0.210, 0.0))[2]
    assert low > floor + 40.0                                       # 나사 위(40.5) 받침 높이로 내려놓음 — 바닥까지 안 내려감


def test_place_check_only_before_pick_moves_nothing(server):
    """check_only: 아직 안 쥔 object(scan 의 판)로 놓기 판단만 — 로봇·그리퍼 명령 없음, placed_pose null·planned_pose 예정.
    (립밤을 뺀 장면: 판 밑 지우개만이면 aside_1 은 자리 안에서 비켜 통과, free 도 통과)"""
    srv = server.srv
    srv.disp["drawer_bottom"] = srv.places()["drawer_bottom"]["tf_at_travel_m"]
    scan = json.loads(json.dumps(SCAN_1012_PLATE))
    scan["candidates"] = [c for c in scan["candidates"] if c["class"] != "lip_balm"]   # 립밤(20 mm)은 판 집기 손끝(20 mm)에 걸림 — 아래 시험
    plate = scan["candidates"][0]
    n = len(srv.robot.log)
    for slot in ("aside_1", "free"):
        out, data = server.run("place_object", {"location": "drawer_bottom", "slot": slot, "scan": scan, "object": plate, "check_only": True})
        assert out.success and "움직이지 않음" in out.reason, out.reason
        assert data["slot"] == slot and data["planned_pose"]["frame"] == "drawer_bottom"
        assert data["placed_pose"] is None and data["check_only"] is True          # 놓지 않음 — 실행 기록에서 놓은 것처럼 안 보이게 [C #241]
    assert len(srv.robot.log) == n and srv.held is None
    out, data = server.run("place_object", {"location": "drawer_bottom", "slot": "aside_1", "scan": scan, "check_only": True})
    assert not out.success and out.error_code == "BAD_PARAMS"             # 쥔 것도 object 도 없음


def test_place_check_only_refuses_when_pick_would_refuse(server):
    """집기가 움직이기 전 거부될 물체면 놓기 판단도 통과 아님 — 그 집기 코드로 (판 손끝 20 mm 에 걸리는 판 옆 립밤).
    10/12 PC2 장면의 립밤은 분할 모델이 판 밑(occluded_by 판)이라 해서 10/13부터 통과(다리 사이로 지나감, 사용자 10/13) →
    관계가 없는(판 옆) 립밤으로 바꿔 봄."""
    srv = server.srv
    srv.disp["drawer_bottom"] = srv.places()["drawer_bottom"]["tf_at_travel_m"]
    plate = SCAN_1012_PLATE["candidates"][0]
    out, _ = server.run("place_object", {"location": "drawer_bottom", "slot": "free", "scan": SCAN_1012_PLATE,
                                         "object": plate, "check_only": True})
    assert out.success, out.reason
    side = json.loads(json.dumps(SCAN_1012_PLATE))
    side["candidates"][1]["occluded_by"] = []
    out, data = server.run("place_object", {"location": "drawer_bottom", "slot": "free", "scan": side,
                                            "object": plate, "check_only": True})
    assert not out.success and out.error_code == "NEIGHBOR_TOO_CLOSE" and "집기부터 거부" in out.reason
    assert data["placed_pose"] is None and data["check_only"] is True and srv.held is None


@pytest.mark.parametrize("drawer", ["drawer_top", "drawer_bottom"])
def test_place_check_only_uses_real_grasp_plan(server, drawer):
    """[#241 리뷰 P1] 집기 전 판단은 실제 pick_object 집기 계획 그대로 — 손잡이 벽 립밤은 긴 변(72.5 mm)·기울여 잡음.
    짧은 변(20 mm) 가정이면 (25, 30) mm 놓기가 통과로 나왔다가 실제로 쥔 뒤엔 WALL_TOO_CLOSE 였음 → 집기 전·후 판단이 같아야 함."""
    srv = server.srv
    lip = {"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.0227, "occluded_by": [], "visible_area_m2": 0.00154,
           "pose": {"frame": drawer, "position": [0.0097, 0.1539, 0.0], "yaw": 1.5625, "yaw_valid": True}}
    scan = {"target_found": True, "target": lip, "candidates": [], "visible_count": 1}
    srv.disp[drawer] = srv.places()[drawer]["tf_at_travel_m"]
    pose = {"frame": drawer, "position": [0.025, 0.030, 0.0], "yaw": 1.5707}
    before, bdata = server.run("place_object", {"location": drawer, "pose": pose, "scan": scan, "object": lip, "check_only": True})
    server.Gripper.holding, server.Gripper.held_width = True, 72.5
    try:
        out, _ = server.run("pick_object", {"target": lip, "approach_offset": [0, 0, 0.1], "scan": scan})
        assert out.success and srv.held["long_side"] is True, out.reason
        after, adata = server.run("place_object", {"location": drawer, "pose": pose, "scan": scan, "check_only": True})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert (before.success, before.error_code) == (after.success, after.error_code), (before.reason, after.reason)
    assert bdata.get("planned_pose") == adata.get("planned_pose")


def test_place_check_only_reports_refusal_with_blocker(server):
    """check_only 거부 = 실제 놓기와 같은 오류 코드·blocked_by (움직이지 않음)."""
    srv = server.srv
    srv.disp["drawer_bottom"] = srv.places()["drawer_bottom"]["tf_at_travel_m"]
    scan = json.loads(json.dumps(SCAN_1012_PLATE))
    scan["candidates"] = [c for c in scan["candidates"] if c["class"] != "lip_balm"]   # 판 집기부터 막는 립밤은 뺌
    slot = srv.places()["drawer_bottom"]["place_slots"]["aside_1"]["position"]
    scan["candidates"].insert(0, {"id": "toy_car#1", "class": "toy_car", "top_z": 0.0325, "occluded_by": [],   # 자리 가운데 = 처음 검사에서 먼저
                                  "pose": {"frame": "drawer_bottom", "position": [slot[0], slot[1], 0.0], "yaw": 0.0, "yaw_valid": True}})
    scan["candidates"].append(scan.pop("target"))                       # 목표 지우개는 뒤로 — 자리 가운데 장난감차가 먼저 걸림
    scan["target_found"], scan["target"] = False, None
    n = len(srv.robot.log)
    out, data = server.run("place_object", {"location": "drawer_bottom", "slot": "aside_1", "scan": scan,
                                            "object": scan["candidates"][1], "check_only": True})
    assert not out.success and out.error_code == "PLACE_BLOCKED" and data["blocked_by"] == "toy_car#1"
    assert data["placed_pose"] is None and data["check_only"] is True and len(srv.robot.log) == n


def test_place_free_slot_when_asides_taken(server):
    """slot "free": 서랍 안 빈 자리(B free·make_room 과 같은 core/clear_plan)에 놓음 → slot "free", placed_pose = 놓은 자리.
    빈 자리가 없으면 움직이기 전 NO_FREE_SPACE."""
    srv = server.srv
    scan = json.loads(json.dumps(SCAN_1012_PLATE))
    try:
        _plate_held(server, scan)
        real = server.ss.clp.find_free_pose
        server.ss.clp.find_free_pose = lambda *a, **k: None
        try:
            n = len(srv.robot.log)
            out, data = server.run("place_object", {"location": "drawer_bottom", "slot": "free", "scan": scan})
        finally:
            server.ss.clp.find_free_pose = real
        assert not out.success and out.error_code == "NO_FREE_SPACE" and data["placed_pose"] is None and len(srv.robot.log) == n
        out, data = server.run("place_object", {"location": "drawer_bottom", "slot": "free", "scan": scan})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out.success, out.reason
    assert data["slot"] == "free" and srv.held is None
    p = data["placed_pose"]["position"]
    plate = scan["candidates"][0]["pose"]["position"]
    assert math.dist(p[:2], plate[:2]) > 0.05                            # 판 원래 자리(가려진 지우개)와 떨어진 곳


def test_putback_pick_then_place_at_pick_pose(server):
    """[사용자 10/11 B putback] 파지만 시험 — 집은 뒤 집기 전 pose 로 서랍 안 놓기: 받아지고 그 자리(placed_pose)에 놓고 빈손."""
    srv = server.srv
    server.Gripper.holding, server.Gripper.held_width = True, 22.0
    t = json.loads(json.dumps(ERASER_FREE))
    scan = {"target_found": True, "target": t, "candidates": [], "visible_count": 1}
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1], "scan": scan})
    assert out.success, out.reason
    pose = {k: t["pose"][k] for k in ("frame", "position", "yaw")}
    out, data = server.run("place_object", {"location": "drawer_top", "pose": pose, "scan": scan})
    assert out.success, out.reason
    assert data["placed_pose"]["position"] == pytest.approx(pose["position"]) and srv.held is None


@pytest.mark.parametrize("yaw, width, ok", [(0.0, 30.9, True), (0.0, 40.5, False), (1.5708, 48.0, True), (1.5708, 57.5, False)])
def test_toy_car_judged_by_measured_body_width(server, yaw, width, ok):
    """[실측 PC2 10/11] 장난감차: 세로(짧은 변) 30.9·가로(긴 변 양끝) 48.0 — 외접 박스 40.5·57.5 보다 몸통이 좁아 WIDTH_MISMATCH 였음.
    item_grasp.yaml grasp_width_m / grasp_width_long_m 실측으로 판정 (외접 박스 폭이면 이제 실패)."""
    t = {"id": "toy_car#1", "class": "toy_car", "top_z": 0.0325,
         "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": yaw, "yaw_valid": True}}
    server.Gripper.holding, server.Gripper.held_width = True, width
    try:
        out, data = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out.success is ok, out.reason
    if ok:
        assert ("긴 변" in out.reason) == (yaw != 0.0)


def test_caramel_grip_force_by_class(server):
    """[사용자 10/11 PC2] 캐러멜은 20 N 이면 찌그러짐 → gripper.grip_force_by_class_n 10 N. 다른 물건은 기본 20 N."""
    srv = server.srv
    forces, real = [], srv._grip
    srv._grip = lambda w, f: forces.append((w, f)) or real(w, f)
    car = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.0185,
           "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}
    server.Gripper.holding, server.Gripper.held_width = True, 43.2
    out, _ = server.run("pick_object", {"target": car, "approach_offset": [0, 0, 0.1]})
    assert out.success, out.reason
    assert (0, 10.0) in forces
    srv.held, forces[:] = None, []
    server.Gripper.held_width = 22.0
    out, _ = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    assert out.success and (0, 20.0) in forces


def test_toy_car_grasped_at_thin_upper_part(server):
    """[사용자 10/11 PC2] 장난감차는 위쪽 얇은 부분(잡은 폭 30.9)을 — 닫은 손끝 = 바닥 위 21.8 mm (높이 절반 16.25 + 5.5)."""
    srv = server.srv
    g, mp = srv.prm()["gripper"], server.ss.mp
    t = {"id": "toy_car#1", "class": "toy_car", "top_z": 0.0325,
         "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}
    server.Gripper.holding, server.Gripper.held_width = True, 30.9
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
    assert out.success, out.reason
    closed_tip = srv.held["tcp_above_floor_m"] * 1000.0 - mp.tip_below_tcp_mm(30.9, g)
    assert closed_tip == pytest.approx(21.8, abs=0.1)


def test_tray_view_named_pose_goes_to_taught_joints(server):
    """[실측 PC2 10/11] 새 트레이 탑뷰 tray_view — 교시 관절로 이동 (B trayview)."""
    out, _ = server.run("move_to_named_pose", {"pose_name": "tray_view"})
    assert out.success, out.reason
    assert server.srv.robot.j == pytest.approx(server.srv.poses()["tray_view"]["joints_deg"])


def test_stacked_key_pick_not_blocked_by_bleeding_stack_below(server):
    """[실측 PC2 10/11 분할 모델] 3단 윗면이 몽키 53.7·캐러멜 54·차키 53.7 로 번지고 관계 없음 → 캐러멜이 손가락 자리 이웃으로
    NEIGHBOR_TOO_CLOSE 였음. 차키 위에 아무것도 없고 밑 물체가 더 크면 받침 → 받침 37 (몽키 18.5 + 캐러멜 18.5) 위에서 집음."""
    f = "drawer_top"
    key = {"id": "car_key#1", "class": "car_key", "top_z": 0.0537, "occluded_by": [],
           "pose": {"frame": f, "position": [0.12, 0.19, 0.0], "yaw": 0.0, "yaw_valid": True}}   # 세로 → 짧은 변 39
    car = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.054, "occluded_by": [],
           "pose": {"frame": f, "position": [0.135, 0.175, 0.0], "yaw": -1.5, "yaw_valid": True}}
    wr = {"id": "toy_wrench#1", "class": "toy_wrench", "top_z": 0.0537, "occluded_by": [],
          "pose": {"frame": f, "position": [0.1333, 0.1573, 0.0], "yaw": -1.19, "yaw_valid": True}}
    scan = {"target_found": True, "target": key, "candidates": [car, wr], "visible_count": 3}
    server.Gripper.holding, server.Gripper.held_width = True, 39.0
    out, _ = server.run("pick_object", {"target": key, "approach_offset": [0, 0, 0.1], "scan": scan})
    # 맨 위 차키는 온톨로지(몽키 + 캐러멜)와 비전 37.9(53.7 − 15.8) 중 높은 값 [사용자 10/12]
    want = max(ONTO_H_MM["toy_wrench"] + ONTO_H_MM["caramel_box"], 53.7 - ONTO_H_MM["car_key"])
    assert out.success and _support_mm(out.reason) == pytest.approx(want, abs=0.05), out.reason


# ---- 파지 공간 만들기 nudge_object make_room [제안 10/11 B, 계약 승인 전] ----
def _seg(o):
    """분할 모델 결과 물체 — 가림 필드 occluded_by 를 채움 (없으면 [] = 위에 얹힌 것 없음)."""
    o = json.loads(json.dumps(o))
    o.setdefault("occluded_by", [])
    return o


def test_make_room_needs_scan_and_is_noop_when_already_graspable(server):
    t = _seg(ERASER_FREE)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True})
    assert out.error_code == "BAD_PARAMS" and server.srv.robot.log == []
    far = _seg(CARAMEL_NEXT)
    far["pose"]["position"][1] = 0.26
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True,
                                            "scan": _scan_with(t, far)})
    assert out.success and data["make_room"]["ready_to_pick"] is True and data["make_room"]["action"] == "none"
    assert data["target_after"]["id"] == "eraser#1" and data["pushed"] is False and server.srv.robot.log == []


@pytest.mark.parametrize("case", ["box_model", "target_null", "neighbor_null", "neighbor_missing"])
def test_make_room_refuses_unknown_occlusion_before_motion(server, case):
    """[A·PM #226 리뷰 10/12] 가림 필드 모름(null)·누락·박스 모델(필드 없음)을 '위에 없음'으로 바꾸지 않음 →
    위에 얹힌 물체를 밀거나 누를 수 있으니 움직이기 전 OCCLUSION_UNKNOWN (다시 찍기)."""
    t, nb = _seg(ERASER_FREE), _seg(CARAMEL_NEXT)
    if case == "box_model":
        t.pop("occluded_by"); nb.pop("occluded_by")
    elif case == "target_null":
        t["occluded_by"] = None
    elif case == "neighbor_null":
        nb["occluded_by"] = None
    else:
        nb.pop("occluded_by")
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True, "scan": _scan_with(t, nb)})
    assert out.error_code == server.ss.OCCLUSION_UNKNOWN and data["target_after"] is None and server.srv.robot.log == []


def _press_contact(server):
    """누르면 닿는 가짜 힘 (위치로 누르면 1 mm 에 8 N) — press 단계 중간 높이에서 닿음."""
    contact = {}

    def force(p):
        z = contact.get("z")
        return [0.0, 0.0, 8.0 * (z - p[2]) if z is not None and p[2] <= z else 0.0, 0.0, 0.0, 0.0]
    server.srv.robot.force = force
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        if stage == "press":
            contact["z"] = (self.robot.p[2] + posx[2]) / 2
        contact.setdefault("stages", []).append((stage, list(self.robot.p), list(posx)))
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    return contact, line


def test_make_room_moves_target_away_from_neighbor_then_ready(server, monkeypatch):
    """옆(+y)에 망치가 길게 붙어 짧은 변·긴 변 손가락 자리가 다 막힌 지우개 → 반대쪽(빈 쪽)으로 눌러 끌기 한 번, 수평으로만.
    그 뒤 예상 위치는 다시 부르면 바로 집을 수 있음."""
    t = _seg(ERASER_FREE)
    t["pose"]["yaw"] = 0.0
    cara = {"id": "toy_hammer#1", "class": "toy_hammer", "top_z": 0.025, "occluded_by": [],
            "pose": {"frame": "drawer_top", "position": [0.10, 0.15 + 0.011 + 0.0375 + 0.002, 0.0], "yaw": 0.0, "yaw_valid": True}}
    scan = _scan_with(t, cara)
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1], "scan": scan})
    assert out.error_code == server.ss.NEIGHBOR_TOO_CLOSE and server.srv.robot.log == []   # 지금은 못 집음
    contact, line = _press_contact(server)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True, "scan": scan})
    assert out.success, out.reason
    mr = data["make_room"]
    # 지우개 가운데는 손가락이 더 높은 망치에 걸림 → 예전엔 망치를 밀었음. 10/13 누를 점을 폭 방향으로 비킴(press_point) →
    # 다른 물체를 안 건드리고 지우개 자신을 빈 쪽(-y)으로 넛지 [실측 PC2 10/13 몽키 머리 끝 누름 수정]
    assert mr["action"] == "nudge" and mr["moved_id"] == "eraser#1" and mr["ready_to_pick"] is False, mr
    assert data["pushed"] is True and data["push_vector_m"][1] < 0             # 망치 반대쪽(-y)으로
    assert mr["pushed_ids"] == [] and mr["pushed_after"] == []                  # 같이 밀린 물체 없음 [C #226]
    drags = [s for s in contact["stages"] if s[0] in ("drag", "drag_back")]
    assert drags and all(abs(end[2] - start[2]) < 0.06 for _, start, end in drags)   # 수평으로만
    after = data["target_after"]
    assert after["pose"]["position"][1] < t["pose"]["position"][1]
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": after, "make_room": True,
                                            "scan": _scan_with(after, cara)})
    assert out.success and data["make_room"]["ready_to_pick"] is True       # 다시 보면 바로 집기


def test_make_room_puts_rider_in_free_space_not_on_target(server):
    """캐러멜 위 차 키 → 차 키를 집어 서랍 빈 자리에 (고정 aside 자리 아님), 캐러멜 둘레는 비움."""
    base = json.loads(json.dumps(CARAMEL_NEXT))
    base["pose"]["position"] = [0.10, 0.15, 0.0]
    base["occluded_by"] = ["car_key#1"]
    key = {"id": "car_key#1", "class": "car_key", "top_z": round(0.0185 + 0.0158, 4), "occluded_by": [],
           "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}
    scan = _scan_with(base, key)
    size = server.srv.item("car_key")[0]
    server.Gripper.holding, server.Gripper.held_width = True, 1000.0 * (server.srv.grasp_width("car_key", size, server.srv.prm()) or size[1])
    try:
        out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": base, "make_room": True, "scan": scan})
    finally:
        server.Gripper.holding = False
    assert out.success, out.reason
    mr = data["make_room"]
    assert mr["action"] == "unstack" and mr["moved_id"] == "car_key#1" and mr["placed_pose"]
    px, py = mr["placed_pose"]["position"][:2]
    assert math.hypot(px - 0.10, py - 0.15) > 0.06                        # 목표 위·바로 옆이 아님
    assert server.srv.held is None


def test_place_in_drawer_fast_descent_stops_on_unseen_support(server):
    """[사용자 10/12 PC2] 몽키 위 캐러멜 putback: scan 에 몽키가 없어 바닥 높이로 내려가다 쥔 물체가 몽키에 닿음
    → 빠른 구간도 힘을 봐서(place.fast_guard_n) 거기서 멈추고 더 누르지 않고 그 자리에 놓음 (예전엔 바닥까지 누름)."""
    srv = server.srv
    grips = _holding_in_drawer(server)
    pl = srv.prm()["place"]
    from ready2go_skills.core import place_plan as plp
    pos_m, _ = plp.place_tcp_m(srv.places()["drawer_top"]["tf"], ASIDE_POSE, 0.02 + pl["drop_m"])
    support_z = 1000.0 * pos_m[2] + pl["slow_last_mm"] + 15.0              # 놓는 높이보다 25 mm 위에 받침 윗면
    srv.robot.force = lambda p: [0.0, 0.0, 10.0 * (support_z - p[2]) if p[2] < support_z else 0.0, 0.0, 0.0, 0.0]
    out, data = server.run("place_object", {"location": "drawer_top", "pose": ASIDE_POSE, "scan": EMPTY_SCAN})
    assert out.success, out.reason
    assert grips and srv.held is None                                    # 받침 위에서 벌림
    assert "stop" in srv.robot.log                                       # 빠른 구간에서 닿아 멈춤
    lines = [p for e in srv.robot.log if e[0] in ("movel", "moveb") for p in ([e[1]] if e[0] == "movel" else e[1])]
    assert all(p[2] > 1000.0 * pos_m[2] for p in lines)                  # 마지막 천천히 내리기(놓는 높이 − overtravel)는 안 보냄 = 더 안 누름


def test_make_room_sweep_reports_pushed_ids_and_expected_poses(server, monkeypatch):
    """[C #226 리뷰] sweep 로 같이 밀린 물체를 문장이 아니라 make_room.pushed_ids·pushed_after(예상 자리)로 — 역순 복구용.
    계획(clear_plan)이 sweep 을 고른 경우를 그대로 주입해 서버가 결과에 싣는지만 봄."""
    from ready2go_skills.core import clear_plan as clp
    t = _seg(ERASER_FREE)
    t["pose"]["yaw"] = 0.0
    nb = _seg(CARAMEL_NEXT)
    nb["pose"]["position"] = [0.10, 0.15 - 0.011 - 0.0245 - 0.002, 0.0]
    sweep = clp.Action("sweep", "eraser#1", "30 mm 밀고 15 mm 되돌아옴", dir=(0.0, -1.0), dist_m=0.03, back_m=0.015,
                       pushed=("caramel_box#1",), extra={})
    monkeypatch.setattr(server.ss.clp, "plan_next", lambda *a, **k: sweep)
    contact, line = _press_contact(server)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True, "scan": _scan_with(t, nb)})
    mr = data["make_room"]
    assert mr["action"] == "sweep" and mr["moved_id"] == "eraser#1" and mr["pushed_ids"] == ["caramel_box#1"]
    (pa,) = mr["pushed_after"]
    assert pa["id"] == "caramel_box#1" and pa["frame"] == "drawer_top" and pa["position"][1] < nb["pose"]["position"][1]


def test_make_room_refusal_has_no_moved_id(server, monkeypatch):
    """[C #226 리뷰] 거부(움직이지 않음)면 moved_id null — 옮기려던 물체는 reason 에."""
    from ready2go_skills.core import clear_plan as clp
    t = _seg(ERASER_FREE)
    t["occluded_by"] = ["car_key#1"]
    key = _seg({"id": "car_key#1", "class": "car_key", "top_z": 0.0273,
                "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}})
    fail = clp.Action("fail", "car_key#1", "car_key#1 놓을 빈 자리 없음", code="NO_FREE_SPACE")
    monkeypatch.setattr(server.ss.clp, "plan_next", lambda *a, **k: fail)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True, "scan": _scan_with(t, key)})
    assert out.error_code == "NO_FREE_SPACE" and data["make_room"]["moved_id"] is None and "car_key#1" in out.reason
    assert server.srv.robot.log == []


@pytest.mark.parametrize("kind", ["nudge", "sweep", "unstack", "remove", "wall_nudge"])
def test_make_room_with_check_only_never_moves(server, monkeypatch, kind):
    """[E #226 리뷰 P1] make_room + check_only = 판단만 — 계획이 어떤 동작을 고르든 로봇·그리퍼 명령 0, PUSH_LIMIT, target_after null."""
    from ready2go_skills.core import clear_plan as clp
    t = _seg(ERASER_FREE)
    nb = _seg(CARAMEL_NEXT)
    who = "eraser#1" if kind in ("nudge", "sweep", "wall_nudge") else "caramel_box#1"
    a = clp.Action(kind, who, "주입", dir=(0.0, -1.0), dist_m=0.02, back_m=0.01 if kind == "sweep" else 0.0,
                   to_pose={"frame": "drawer_top", "position": [0.05, 0.05, 0.0], "yaw": 0.0},
                   extra={"after": dict(t, pose=dict(t["pose"], position=[0.10, 0.13, 0.0]))})
    monkeypatch.setattr(server.ss.clp, "plan_next", lambda *x, **k: a)
    grips = []
    monkeypatch.setattr(server.ss.SkillServer, "_grip", lambda self, *x, **k: grips.append(x))
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True, "check_only": True,
                                            "scan": _scan_with(t, nb)})
    assert out.error_code == server.ss.PUSH_LIMIT and kind in out.reason
    assert data["make_room"]["action"] == kind and data["make_room"]["moved_id"] is None and data["target_after"] is None
    assert server.srv.robot.log == [] and grips == []


def test_make_room_neighbor_wall_nudge_keeps_target_after_for_original_target(server, monkeypatch):
    """[E #226 리뷰 P2] 막는 이웃을 벽 넛지 → 안쪽 nudge 결과는 moved_after 로, 바깥 target_after 는 원래 목표(그대로).
    실패면 target_after null."""
    from ready2go_skills.core import clear_plan as clp
    t = _seg(ERASER_FREE)
    nb = _seg(dict(ERASER_CORNER, id="eraser#2"))
    nb_after = json.loads(json.dumps(nb))
    nb_after["pose"]["position"][1] -= 0.04
    a = clp.Action("wall_nudge", "eraser#2", "옆벽 쪽 부족 → y −40 mm", to_pose=clp.as_pose(nb_after), extra={"after": nb_after})
    monkeypatch.setattr(server.ss.clp, "plan_next", lambda *x, **k: a)
    real = server.ss.SkillServer._do_nudge_object
    inner = {"ok": True}

    def nudge(self, goal, params):
        if params.get("make_room"):
            return real(self, goal, params)
        assert params["target"]["id"] == "eraser#2" and "check_only" not in params
        o = {"pushed": True, "push_vector_m": [0.0, -0.04], "clearance_before_m": 0.004, "floor_z_m": 0.0,
             "target_after": nb_after if inner["ok"] else None}
        return (sf.Outcome(True, reason="주입") if inner["ok"] else sf.Outcome(False, "PUSH_BLOCKED", reason="주입")), o
    monkeypatch.setattr(server.ss.SkillServer, "_do_nudge_object", nudge)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True, "scan": _scan_with(t, nb)})
    assert out.success and data["target_after"]["id"] == "eraser#1"
    assert data["target_after"]["pose"]["position"] == t["pose"]["position"]
    assert data["make_room"]["moved_id"] == "eraser#2" and data["make_room"]["moved_after"]["position"][1] == pytest.approx(nb_after["pose"]["position"][1])
    assert data["pushed"] is True and data["push_vector_m"] == [0.0, -0.04]
    inner["ok"] = False
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True, "scan": _scan_with(t, nb)})
    assert out.error_code == "PUSH_BLOCKED" and data["target_after"] is None


def test_push_from_behind_refused_when_neighbor_in_finger_spot(server):
    """[사용자 10/12 PC2] 손잡이 쪽 벽 근처 비스듬한 지우개 바로 뒤에 에어팟 — 뒤에서 밀 손가락이 내려갈 자리에 이웃이면
    움직이기 전 NEIGHBOR_TOO_CLOSE (예전엔 끄는 길만 봐서 손가락이 에어팟 위로 내려갈 수 있었음). 이웃이 없으면 그대로 밂."""
    er = {"id": "eraser#1", "class": "eraser", "top_z": 0.0131, "occluded_by": [],
          "pose": {"frame": "drawer_top", "position": [0.0301, 0.0502, 0.0], "yaw": -1.2977, "yaw_valid": True}}
    ap = {"id": "airpods_case#1", "class": "airpods_case", "top_z": 0.0241, "occluded_by": [],
          "pose": {"frame": "drawer_top", "position": [0.0665, 0.0695, 0.0], "yaw": -1.5698, "yaw_valid": True}}
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": er, "scan": _scan_with(er, ap)})
    assert out.error_code == server.ss.NEIGHBOR_TOO_CLOSE and "뒤에서 밀 손가락" in out.reason and "airpods_case#1" in out.reason
    assert data["target_after"] is None and server.srv.robot.log == []
    far = json.loads(json.dumps(ap))
    far["pose"]["position"] = [0.15, 0.20, 0.0]
    plan_ok = server.ss.DryOracle(server.srv, "drawer_top").wall_nudge([er, far], "eraser#1")
    assert plan_ok[0] is not None                                       # 이웃이 멀면 뒤에서 밀기 계획 그대로
    blocked = server.ss.DryOracle(server.srv, "drawer_top").wall_nudge([er, ap], "eraser#1")
    assert blocked[0] is None and blocked[1] == server.ss.NEIGHBOR_TOO_CLOSE   # 계획도 그 이웃부터 치우게


@pytest.mark.parametrize("drawer", ["drawer_top", "drawer_bottom"])
def test_putback_tilted_pick_places_back_with_same_tilt(server, drawer):
    """[사용자 10/12 PC2] 손잡이 쪽 벽에 가로로 붙은 립밤(아래 칸 (9.7, 153.9) mm yaw 1.5625)은 손잡이 쪽으로 기울여 집음 →
    `B putback` 이 수직으로 놓으려다 손가락 자리가 벽 밖(꼭짓점 x −5.8 mm) WALL_TOO_CLOSE. 원래 자리면 집을 때 자세 그대로 거꾸로 놓음:
    같은 TCP(+ drop_m)·같은 기울임. 기억이 없으면(예전 동작) 그대로 거부, 원래 자리에서 벗어난 pose 도 거부."""
    srv = server.srv
    prm = srv.prm()
    srv.prm = lambda: prm
    lip = {"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.0227, "occluded_by": [], "visible_area_m2": 0.00154,
           "pose": {"frame": drawer, "position": [0.0097, 0.1539, 0.0], "yaw": 1.5625, "yaw_valid": True}}
    scan = {"target_found": True, "target": lip, "candidates": [], "visible_count": 1}
    srv.disp[drawer] = srv.places()[drawer]["tf_at_travel_m"]
    pose = {k: lip["pose"][k] for k in ("frame", "position", "yaw")}
    server.Gripper.holding, server.Gripper.held_width = True, 72.5
    try:
        out, _ = server.run("pick_object", {"target": lip, "approach_offset": [0, 0, 0.1], "scan": scan})
        assert out.success and "기울" in out.reason, out.reason
        tb = srv.held["tilt_back"]
        picked = [e[1] for e in srv.robot.log if e[0] == "movel"][-1]
        held = dict(srv.held)

        srv.held = {k: v for k, v in held.items() if k != "tilt_back"}       # 기억 없음 = 예전: 수직이라 벽 밖 → 거부
        prm = srv.prm()
        no_fit = dict(prm, place=dict(prm["place"], restore_fit_max_mm=0.0))
        real_prm, srv.prm = srv.prm, (lambda: no_fit)
        out, data = server.run("place_object", {"location": drawer, "pose": pose, "scan": scan})
        assert not out.success and out.error_code == "WALL_TOO_CLOSE" and data["blocked_by"] == "wall"
        srv.prm = real_prm                                                    # 지금: 벽에서 복구 허용 오차 안으로 비켜 수직으로 놓음
        srv.held = {k: v for k, v in held.items() if k != "tilt_back"}
        out, data = server.run("place_object", {"location": drawer, "pose": pose, "scan": scan})
        assert out.success and "기울여" not in out.reason
        assert 0.0 < data["placed_pose"]["position"][0] - pose["position"][0] <= prm["place"]["restore_fit_max_mm"] / 1000.0 + 1e-9

        srv.held = dict(held)
        far = dict(pose, position=[pose["position"][0] + 0.010, pose["position"][1], 0.0])
        out, data = server.run("place_object", {"location": drawer, "pose": far, "scan": scan})
        assert out.success and "기울여" not in out.reason                          # 원래 자리 아니면 보통 수직 놓기 (10 mm 안쪽은 수직으로 됨)

        srv.held = dict(held)
        srv.robot.log.clear()
        out, data = server.run("place_object", {"location": drawer, "pose": pose, "scan": scan})
        assert out.success and "기울여" in out.reason, out.reason
        assert srv.held is None and data["placed_pose"]["position"] == pytest.approx(pose["position"])
        lows = [e[1] for e in srv.robot.log if e[0] == "movel"]
        low = min(lows, key=lambda p: p[2])
        assert low[:2] == pytest.approx(tb["tcp_mm"][:2], abs=0.1)                # 집을 때 TCP 그대로
        assert low[2] <= tb["tcp_mm"][2] + 1000.0 * prm["place"]["drop_m"] + 0.1
        assert low[3:] == pytest.approx(picked[3:], abs=0.5)                       # 같은 기울인 손목
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0


@pytest.mark.parametrize("target", ["caramel_wall", "eraser_corner"])
def test_nudge_stacked_target_from_support_height(server, target):
    """[사용자 10/13 "높이상관없이 넛지로가자"] 쌓인 물체도 넛지 — 10/12 PC2 몽키(미검출) 위 캐러멜(손잡이 벽, 뒤에서 밀기)·
    구석 지우개(위에서 눌러 끌기). 손끝·누르는 높이는 받침(top_z − 물체 높이) 위만큼 올라감 — 바닥 물체와 같은 길, 높이만 다름."""
    srv = server.srv
    if target == "caramel_wall":
        t = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.0185, "occluded_by": [], "visible_area_m2": 0.0032,
             "pose": {"frame": "drawer_top", "position": [0.0605, 0.2139, 0.0], "yaw": -0.7897, "yaw_valid": True}}
    else:
        t = dict(ERASER_CORNER)
    lows = []
    for lift in (0.0, 0.0202):                                           # 바닥 / 몽키(18.5) 위 정도
        srv.robot.log.clear()
        srv.robot.p = [380.0, -6.5, 300.0, 90.0, -90.0, 180.0]
        out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": dict(t, top_z=t["top_z"] + lift)})
        assert out.error_code != "NOT_ON_FLOOR", out.reason
        moves = [e[1] for e in srv.robot.log if e != "stop" and e[0] == "movel"]
        assert moves, out.reason
        lows.append(min(p[2] for p in moves))
    h = ONTO_H_MM[t["class"]]                                             # 받침 = top_z − 물체 높이 (바닥이면 0)
    want = max(0.0, (t["top_z"] + 0.0202) * 1000.0 - h) - max(0.0, t["top_z"] * 1000.0 - h)
    assert lows[1] - lows[0] == pytest.approx(want, abs=1.5), lows


def test_nudge_stacked_ignores_support_but_not_others(server):
    """쌓인 물체 넛지: 밑에 깔린 받침은 끄는 길 이웃이 아님(손끝이 그 위), 너무 높이 쌓이면(테두리 − 10 mm 넘음) 움직이기 전 NOT_ON_FLOOR."""
    srv = server.srv
    x, y = ERASER_CORNER["pose"]["position"][:2]
    base = {"id": "toy_wrench#1", "class": "toy_wrench", "top_z": 0.030, "occluded_by": ["eraser#1"],   # 덮인 받침 윗면 번짐 (실제 18.5)
            "pose": {"frame": "drawer_top", "position": [x, y - 0.03, 0.0], "yaw": 1.5707, "yaw_valid": True}}   # 끄는 쪽(−y)으로 걸침
    t = dict(ERASER_CORNER, top_z=0.0185 + 0.0115)
    scan = {"target_found": True, "target": t, "candidates": [base], "visible_count": 2}
    out, _ = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "scan": scan})
    assert out.error_code not in ("NEIGHBOR_TOO_CLOSE", "NOT_ON_FLOOR"), out.reason
    other = dict(base, id="toy_car#1", class_="x", occluded_by=[])                  # 받침 관계가 없으면 그대로 막음
    other = {k: v for k, v in other.items() if k != "class_"}
    other["pose"] = dict(base["pose"], position=[x, y - 0.06, 0.0])
    out, _ = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t,
                                         "scan": dict(scan, candidates=[base, other], visible_count=3)})
    assert out.error_code == "NEIGHBOR_TOO_CLOSE" and "toy_car#1" in out.reason, out.reason
    srv.robot.log.clear()
    high = dict(ERASER_CORNER, top_z=srv.places()["drawer_top"]["interior_m"][2])
    out, _ = server.run("nudge_object", {"drawer_id": "drawer_top", "target": high})
    assert not out.success and out.error_code == "NOT_ON_FLOOR" and srv.robot.log == []


def test_named_top_view_from_tray_goes_home_first(server):
    """[실측 PC2 10/12 B unpack] 트레이에 놓은 뒤(543.8, 225.5, z 100) 바로 탑뷰로: high_z 325 수직 상승은 팔이 거의 펴져
    제어기가 출발 안 함(NOT_REACHED 두 번) → 트레이 위면 홈(free_lift_z 150 으로 올린 뒤 관절 이동)부터."""
    srv = server.srv
    srv.robot.p = [543.8, 225.5, 100.4, 21.2, -180.0, 21.6]
    out, _ = server.run("move_to_named_pose", {"pose_name": "drawer_top_view", "drawer_id": "drawer_top"})
    assert out.success, out.reason
    moves = [e for e in srv.robot.log if e != "stop" and e[0] in ("movel", "movej", "moveb")]
    home = srv.poses()["home"]["joints_deg"]
    assert moves[0][0] == "movel" and moves[0][1][2] == pytest.approx(150.0)
    first_j = next(i for i, e in enumerate(moves) if e[0] == "movej")
    assert list(moves[first_j][1])[:6] == pytest.approx(home)
    assert not any(e[0] == "movel" and e[1][2] > 200.0 for e in moves[:first_j])   # 트레이 위에서 325 로 안 올림


def test_empty_hand_home_uses_view_joint_speed(server):
    """[사용자 10/12] 닫고 홈 가는 게 느림 → 빈손 홈은 손잡이 앞(ready)·탑뷰와 같은 speed.view_joint_deg_s. 쥔 채면 서버 속도 그대로."""
    srv = server.srv
    sp = srv.prm()["speed"]
    seen = []
    real = srv.robot.movej_async
    srv.robot.movej_async = lambda j, v, a: seen.append((v, a)) or real(j, v, a)
    srv.robot.p = [380.0, -6.5, 300.0, 90.0, -90.0, 180.0]
    out, _ = server.run("move_to_named_pose", {"pose_name": "home"})
    assert out.success and seen[-1] == (sp["view_joint_deg_s"], sp["view_joint_acc_deg_s2"])
    srv.held = {"class": "eraser", "id": "eraser#1", "width_m": 0.021, "drawer_id": "drawer_top", "tcp_above_floor_m": 0.006, "long_side": False}
    server.Gripper.holding, server.Gripper.held_width = True, 21.0
    try:
        out, _ = server.run("move_to_named_pose", {"pose_name": "home"})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out.success and seen[-1] == (srv.joint_vel, srv.joint_acc)


def test_hold_unknown_home_uses_server_joint_speed(server):
    """#235 A·PM: 재시작 뒤 쥐었는지 모름(hold_unknown)이면 held 가 None 이어도 빠른 빈손 홈 속도를 쓰지 않음."""
    srv = server.srv
    seen = []
    real = srv.robot.movej_async
    srv.robot.movej_async = lambda j, v, a: seen.append((v, a)) or real(j, v, a)
    srv.robot.p = [380.0, -6.5, 300.0, 90.0, -90.0, 180.0]
    srv.hold_unknown = {"class": "eraser", "id": "eraser#1", "width_m": 0.021}
    out, _ = server.run("move_to_named_pose", {"pose_name": "home"})
    assert out.success and seen[-1] == (srv.joint_vel, srv.joint_acc)


def test_tilt_back_uses_current_drawer_tf(server, monkeypatch):
    """#235 A·PM: tilt_back 위치는 서랍 좌표로 기억 → 그사이 서랍 tf 가 몇 mm 바뀌어도 지금 tf 로 같은 서랍 자리에 놓음."""
    srv = server.srv
    prm = srv.prm()
    srv.prm = lambda: prm
    lip = {"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.0227, "occluded_by": [], "visible_area_m2": 0.00154,
           "pose": {"frame": "drawer_top", "position": [0.0097, 0.1539, 0.0], "yaw": 1.5625, "yaw_valid": True}}
    scan = {"target_found": True, "target": lip, "candidates": [], "visible_count": 1}
    srv.disp["drawer_top"] = srv.places()["drawer_top"]["tf_at_travel_m"]
    server.Gripper.holding, server.Gripper.held_width = True, 72.5
    try:
        assert server.run("pick_object", {"target": lip, "approach_offset": [0, 0, 0.1], "scan": scan})[0].success
        tb = srv.held["tilt_back"]
        places = json.loads(json.dumps(srv.places()))
        places["drawer_top"]["tf"]["translation_m"][0] += 0.004          # 서랍이 base x 로 4 mm 밀림
        monkeypatch.setattr(srv, "places", lambda: places)
        srv.robot.log.clear()
        pose = {k: lip["pose"][k] for k in ("frame", "position", "yaw")}
        out, _ = server.run("place_object", {"location": "drawer_top", "pose": pose, "scan": scan})
        assert out.success and "기울여" in out.reason, out.reason
        low = min((e[1] for e in srv.robot.log if e[0] == "movel"), key=lambda p: p[2])
        assert low[0] == pytest.approx(tb["tcp_mm"][0] + 4.0, abs=0.2) and low[1] == pytest.approx(tb["tcp_mm"][1], abs=0.2)
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0


@pytest.mark.parametrize("key, cara, wrench, chain", [
    ((0.0743, 0.2324, -0.1899), (0.0657, 0.1987, -0.2008, ["car_key#1"]), (0.1487, 0.2161, -0.1872, ["car_key#1", "caramel_box#1"]), True),
    # 두 번째 덤프: "몽키가 캐러멜 위" 헛관계 → 온톨로지 받침이 한 단(캐러멜)만 — 맨 위 차키라 비전 값이 더 높아 그쪽
    ((0.0782, 0.2146, -0.1714), (0.0698, 0.1804, -0.0991, ["car_key#1", "toy_wrench#1"]), (0.152, 0.1989, -0.2232, ["car_key#1"]), False),
])
def test_stacked_key_hanging_off_caramel_edge_picks_with_caramel_as_support(server, key, cara, wrench, chain):
    """[실측 PC2 10/12 B unpack top 몽키 두 번] 캐러멜 끝에 걸친 차키(가운데가 캐러멜 밖 약 10 mm) → 캐러멜을 옆 물체로 봐
    NEIGHBOR_TOO_CLOSE. 분할 관계 + 캐러멜 윗면이 차키 바닥 높이와 맞고 겹치면 받침 → 집기 통과, 받침 37 mm (몽키 + 캐러멜)."""
    def o(i, cls, xyz, top, occ):
        return {"id": i, "class": cls, "top_z": top, "occluded_by": occ, "visible_area_m2": 0.002,
                "pose": {"frame": "drawer_top", "position": [xyz[0], xyz[1], 0.0], "yaw": xyz[2], "yaw_valid": True}}
    k = o("car_key#1", "car_key", key, 0.0528, [])
    c = o("caramel_box#1", "caramel_box", cara[:3], 0.0386, cara[3])
    w = o("toy_wrench#1", "toy_wrench", wrench[:3], 0.0176, wrench[3])
    scan = {"target_found": True, "target": w, "candidates": [k, c], "visible_count": 3}
    server.Gripper.holding, server.Gripper.held_width = True, 39.1
    try:
        out, _ = server.run("pick_object", {"target": k, "approach_offset": [0, 0, 0.1], "scan": scan})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out.success, out.reason
    w, c = ONTO_H_MM["toy_wrench"], ONTO_H_MM["caramel_box"]
    want = max(w + c if chain else max(w, c), 52.8 - ONTO_H_MM["car_key"])   # 온톨로지(몽키 + 캐러멜) / 비전 52.8 − 15.8 중 높은 값
    assert _support_mm(out.reason) == pytest.approx(want, abs=0.25), out.reason
    side = o("caramel_box#1", "caramel_box", (key[0], key[1] - 0.045, 0.0), 0.0185, ["car_key#1"])   # 바닥 차키 옆 헛관계 캐러멜
    floor_key = dict(k, top_z=0.0158)
    assert server.ss.plp.objects_under(target=floor_key, objects=[side], size_of=server.srv._size_or_none) == []


def test_cover_plate_pick_ignores_lower_neighbors_under_fingertips(server):
    """[사용자 10/12 PC2 "가림막 높이가 지우개·립밤보다 높아서 그냥 잡힘"] 가림막 긴 변(손가락 자리) 옆에 반쯤 나온 지우개(14.2)·
    붙은 립밤(22.2) → 예전엔 NEIGHBOR_TOO_CLOSE. 닫은 손끝은 바닥 위 25 mm 아래로 안 내려가므로 그보다 2 mm 넘게 낮은 이웃은 무시.
    낮은 물체(지우개, 손끝 약 5.8 mm)를 집을 땐 옆의 높은 물체는 예전처럼 막음."""
    D = "drawer_bottom"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    plate = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.0344, "occluded_by": [], "visible_area_m2": 0.007291,
             "pose": {"frame": D, "position": [0.093, 0.1739, 0.0], "yaw": -0.0765, "yaw_valid": True}}
    er = {"id": "eraser#1", "class": "eraser", "top_z": 0.0142, "occluded_by": ["cover_plate#1"], "visible_area_m2": 0.000799,
          "pose": {"frame": D, "position": [0.0914, 0.119, 0.0], "yaw": 1.4835, "yaw_valid": True}}
    lip = {"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.0222, "occluded_by": None, "visible_area_m2": 0.000992,
           "pose": {"frame": D, "position": [0.0679, 0.1118, 0.0], "yaw": 1.3196, "yaw_valid": True}}
    scan = {"target_found": True, "target": er, "candidates": [plate, lip], "visible_count": 3}
    server.Gripper.holding, server.Gripper.held_width = True, 74.2
    try:
        out, _ = server.run("pick_object", {"target": plate, "approach_offset": [0, 0, 0.1], "scan": scan})
        assert out.error_code == "NEIGHBOR_TOO_CLOSE" and "lip_balm#1" in out.reason    # 손끝 20 mm(10/12 실물)면 붙은 립밤(20~22)엔 닿음
        srv.held = None
        scan = {"target_found": True, "target": er, "candidates": [plate], "visible_count": 2}
        out, _ = server.run("pick_object", {"target": plate, "approach_offset": [0, 0, 0.1], "scan": scan})
        assert out.success, out.reason                                     # 지우개(11.5·관측 14.2)만이면 통과
        srv.held = None
        tall = dict(lip, id="airpods_case#1", **{"class": "airpods_case"}, top_z=0.0216,
                    pose={"frame": D, "position": [0.0914, 0.119 + 0.030, 0.0], "yaw": 0.0, "yaw_valid": True})
        er2 = dict(er, occluded_by=[])
        server.Gripper.held_width = 21.0
        out, _ = server.run("pick_object", {"target": er2, "approach_offset": [0, 0, 0.1],
                                            "scan": {"target_found": True, "target": er2, "candidates": [tall], "visible_count": 2}})
        assert out.error_code == "NEIGHBOR_TOO_CLOSE"                    # 지우개 손끝(약 6 mm)보다 높은 에어팟은 그대로 막음
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0


def test_cover_plate_pick_uses_ontology_height_for_object_under_it(server):
    """[사용자 10/12 PC2, #236 비전] 판 밑 지우개 occluded_by [판], 비전 top_z 23.4(번짐, 실제 11.5), yaw 모름 → 손끝 25 − 2 에 걸려
    NEIGHBOR_TOO_CLOSE. 목표 밑에 깔린 이웃은 온톨로지 높이로 → 통과. 판과 안 겹치는 옆 물체(덮이지 않음)는 비전 값 그대로 막음."""
    D = "drawer_bottom"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    plate = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.0349, "occluded_by": [], "visible_area_m2": 0.0073,
             "pose": {"frame": D, "position": [0.0973, 0.1605, 0.0], "yaw": 0.009, "yaw_valid": True}}
    er = {"id": "eraser#1", "class": "eraser", "top_z": 0.0234, "occluded_by": ["cover_plate#1"], "visible_area_m2": 0.0006,
          "pose": {"frame": D, "position": [0.1023, 0.2105, 0.0], "yaw": 0.0, "yaw_valid": False}}
    server.Gripper.holding, server.Gripper.held_width = True, 74.2
    try:
        out, _ = server.run("pick_object", {"target": plate, "approach_offset": [0, 0, 0.1],
                                            "scan": {"target_found": True, "target": er, "candidates": [plate], "visible_count": 2}})
        assert out.success, out.reason
        srv.held = None
        side = dict(er, occluded_by=[], pose=dict(er["pose"], position=[0.0973, 0.215, 0.0], yaw_valid=True))   # 판과 안 겹치고 손가락 자리에만 있는 23.4 mm 물체
        out, _ = server.run("pick_object", {"target": plate, "approach_offset": [0, 0, 0.1],
                                            "scan": {"target_found": True, "target": side, "candidates": [plate], "visible_count": 2}})
        assert out.error_code == "NEIGHBOR_TOO_CLOSE"
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0


def test_cover_plate_pick_ignores_object_that_fits_under_it_even_if_relation_unknown(server):
    """[사용자 10/12 PC2 "커버플레이트는 겹쳐도 집을 수 있게"] 판 밑 지우개가 이번엔 occluded_by null(모름)·top_z 25.5(번짐) → 판 집기
    NEIGHBOR_TOO_CLOSE. 판 footprint 와 겹치고 판 밑(21 mm)에 들어가는 크기면 온톨로지 높이로 → 통과. 판 밑에 못 들어가는 장난감차는 막음."""
    D = "drawer_bottom"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    plate = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.0351, "occluded_by": [], "visible_area_m2": 0.007237,
             "pose": {"frame": D, "position": [0.0857, 0.1636, 0.0], "yaw": 0.0394, "yaw_valid": True}}
    er = {"id": "eraser#1", "class": "eraser", "top_z": 0.0255, "occluded_by": None, "visible_area_m2": 0.000415,
          "pose": {"frame": D, "position": [0.0981, 0.2118, 0.0], "yaw": 0.0, "yaw_valid": False}}
    car = dict(er, id="toy_car#1", **{"class": "toy_car"}, top_z=0.0325)
    server.Gripper.holding, server.Gripper.held_width = True, 74.2
    try:
        for nb, ok in ((er, True), (car, False)):
            srv.held = None
            out, _ = server.run("pick_object", {"target": plate, "approach_offset": [0, 0, 0.1],
                                                "scan": {"target_found": True, "target": nb, "candidates": [plate], "visible_count": 2}})
            assert out.success is ok, (nb["id"], out.reason)
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0


@pytest.mark.parametrize("top, occ, ok", [(0.0255, None, True), (0.0255, ["cover_plate#1"], True),
                                          (0.035, None, False), (0.035, ["cover_plate#1"], False), (0.028, None, False)])
def test_cover_plate_under_exception_keeps_observed_height_when_too_tall_to_be_under(server, top, occ, ok):
    """#235 리뷰 P1: 판 footprint 와 일부 겹치는 지우개라도 관측 top_z 가 판 밑(21) + 번짐(5) = 26 mm 를 넘으면(쌓였거나 세워짐)
    단품 높이로 바꾸지 않고 관측 값으로 막음 — 관계 null 이든 판을 가리키든. 번짐 범위(25.5)는 통과."""
    D = "drawer_bottom"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    plate = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.0351, "occluded_by": [], "visible_area_m2": 0.007237,
             "pose": {"frame": D, "position": [0.0857, 0.1636, 0.0], "yaw": 0.0394, "yaw_valid": True}}
    er = {"id": "eraser#1", "class": "eraser", "top_z": top, "occluded_by": occ, "visible_area_m2": 0.000415,
          "pose": {"frame": D, "position": [0.0981, 0.2118, 0.0], "yaw": 0.0, "yaw_valid": False}}
    server.Gripper.holding, server.Gripper.held_width = True, 74.2
    try:
        out, _ = server.run("pick_object", {"target": plate, "approach_offset": [0, 0, 0.1],
                                            "scan": {"target_found": True, "target": er, "candidates": [plate], "visible_count": 2}})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out.success is ok, out.reason
    if not ok:
        assert out.error_code == "NEIGHBOR_TOO_CLOSE" and "eraser#1" in out.reason


def _plate_pick(server, plate, cands, target=None):
    srv = server.srv
    srv.held = None
    server.Gripper.holding, server.Gripper.held_width = True, 74.2
    try:
        return server.run("pick_object", {"target": plate, "approach_offset": [0, 0, 0.1],
                                          "scan": {"target_found": True, "target": target or cands[0], "candidates": [plate] + cands[1:],
                                                   "visible_count": len(cands) + 1}})[0]
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0


def test_cover_plate_pick_ignores_objects_passing_under_between_legs(server):
    """[사용자 10/13 PC2 "립밤 들어가도 그냥 집을 수 있도록", "몽키·망치도 — 넓이가 다리 사이보다 작으면 들어감"]
    분할 모델이 판 밑이라고 한(occluded_by 판) 물체가 다리 안쪽(65 × 35, #8) 사이로 지나갈 폭이면 판 집기 손가락 확인에서 뺌.
    오늘 PC2 장면 그대로: 판 밑 립밤(20 mm, yaw 모름)이 손끝(20 mm) 자리에 걸려 NEIGHBOR_TOO_CLOSE 였음.
    몽키(외접 61)·망치(외접 75, 손잡이 15.5)가 판 짧은 변 쪽으로 가로질러 양쪽 손가락 자리로 삐져나와도 통과."""
    D = "drawer_bottom"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    plate = {"id": "cover_plate#1", "class": "cover_plate", "top_z": 0.0358, "occluded_by": [], "visible_area_m2": 0.007305,
             "pose": {"frame": D, "position": [0.0948, 0.2042, 0.0], "yaw": -0.0158, "yaw_valid": True}}
    er = {"id": "eraser#1", "class": "eraser", "top_z": 0.0143, "occluded_by": ["cover_plate#1"], "visible_area_m2": 0.000435,
          "pose": {"frame": D, "position": [0.098, 0.1563, 0.0], "yaw": 0.0, "yaw_valid": False}}
    lip = {"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.0204, "occluded_by": ["cover_plate#1"], "visible_area_m2": 0.000609,
           "pose": {"frame": D, "position": [0.076, 0.1513, 0.0], "yaw": 0.0, "yaw_valid": False}}
    out = _plate_pick(server, plate, [er, plate, lip])
    assert out.success, out.reason
    across = {"frame": D, "position": [0.0948, 0.2042, 0.0], "yaw": 1.5708 - 0.0158, "yaw_valid": True}   # 판 짧은 변 쪽으로 가로지름
    for cls, top in (("toy_wrench", 0.0195), ("toy_hammer", 0.026)):
        o = {"id": f"{cls}#1", "class": cls, "top_z": top, "occluded_by": ["cover_plate#1"], "visible_area_m2": 0.004, "pose": across}
        out = _plate_pick(server, plate, [o, plate])
        assert out.success, (cls, out.reason)
        # 관계 모름(null)이면 예전 규칙 — 손끝(20) 자리에 18.5·25 mm 는 막음
        out = _plate_pick(server, plate, [dict(o, occluded_by=None), plate])
        assert out.error_code == "NEIGHBOR_TOO_CLOSE" and cls in out.reason, (cls, out.reason)
    # 판 위에 얹힌 몽키(관측 윗면이 판 밑 여유·자기 높이 + 번짐보다 높음)는 빼지 않음
    on_top = {"id": "toy_wrench#1", "class": "toy_wrench", "top_z": 0.058, "occluded_by": ["cover_plate#1"], "visible_area_m2": 0.004,
              "pose": across}
    out = _plate_pick(server, plate, [on_top, plate])
    assert out.error_code == "NEIGHBOR_TOO_CLOSE", out.reason
    # 판 긴 변과 나란히 들어간 장난감차(폭 30.9 ≤ 35 지만 높이 32.5 + 5 < 관측 40)도 관측이 높으면 막음
    car = {"id": "toy_car#1", "class": "toy_car", "top_z": 0.040, "occluded_by": ["cover_plate#1"], "visible_area_m2": 0.002,
           "pose": dict(across, yaw=-0.0158, position=[0.0948, 0.1563, 0.0])}
    out = _plate_pick(server, plate, [car, plate])
    assert out.error_code == "NEIGHBOR_TOO_CLOSE", out.reason


def test_make_room_cluster_touching_bboxes_still_plans(server):
    """[실측 PC2 10/13 B clear top 에어팟, 덤프 inspect_20261013_051358_386Z] 에어팟 둘레에 캐러멜·몽키·지우개가 맞붙음 — 온톨로지
    외접 박스(몽키 머리 61 × 170)가 처음부터 서로 1~2 mm 겹쳐 어느 쪽으로도 0 mm 로 계산 → make_room fail(NEIGHBOR_TOO_CLOSE).
    처음부터 겹친 물체에서 멀어지는 쪽은 막지 않음 → 에어팟 밀기(sweep, check_only, 로봇 안 움직임)."""
    D = "drawer_top"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]

    def o(i, c, x, y, top, yaw):
        return {"id": i, "class": c, "pose": {"frame": D, "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True},
                "top_z": top, "occluded_by": [], "visible_area_m2": 0.002}
    air = o("airpods_case#1", "airpods_case", 0.1069, 0.1802, 0.0246, 0.0061)
    scan = {"target_found": True, "target": air, "visible_count": 4,
            "candidates": [o("caramel_box#1", "caramel_box", 0.1047, 0.1346, 0.0234, 0.0061),
                           o("toy_wrench#1", "toy_wrench", 0.1046, 0.215, 0.0167, -0.1088),
                           o("eraser#1", "eraser", 0.0562, 0.1729, 0.0136, -1.5254)]}
    out, data = server.run("nudge_object", {"drawer_id": D, "target": air, "scan": scan, "make_room": True, "check_only": True})
    mr = data["make_room"]
    # make_room.remove_first false(10/13): 에어팟을 -y 로 밀며 캐러멜·지우개를 같이 밀기 한 번 → 집기 [사용자 10/13]
    assert mr["action"] == "sweep" and "caramel_box#1" in mr["reason"], mr
    assert srv.robot.log == []


def test_make_room_wall_cluster_sweeps_away_from_wall(server):
    """[실측 PC2 10/13 덤프 inspect_20261013_053849_242Z] 오른쪽 벽(y 0)에 붙은 에어팟 — 손잡이 쪽 옆에 14° 돌아 벽에 닿은 캐러멜
    (외접 박스가 벽 밖 4 mm), +y 에 몽키, 안쪽에 지우개 → make_room fail "끄는 길에 caramel_box#1". 옆에 맞붙은 물체는 '앞'이
    아니고, 처음부터 경계 밖으로 그려진 만큼은 봐줌 → 에어팟을 +y 로 밀며 몽키를 같이 밀기(sweep)."""
    D = "drawer_top"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]

    def o(i, c, x, y, top, yaw):
        return {"id": i, "class": c, "pose": {"frame": D, "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True},
                "top_z": top, "occluded_by": [], "visible_area_m2": 0.002}
    air = o("airpods_case#1", "airpods_case", 0.1099, 0.0272, 0.0229, -0.0166)
    scan = {"target_found": True, "target": air, "visible_count": 4,
            "candidates": [o("caramel_box#1", "caramel_box", 0.04, 0.0293, 0.0229, -0.25),
                           o("toy_wrench#1", "toy_wrench", 0.1085, 0.0689, 0.0151, -0.1574),
                           o("eraser#1", "eraser", 0.1723, 0.0119, 0.0128, 0.0064)]}
    out, data = server.run("nudge_object", {"drawer_id": D, "target": air, "scan": scan, "make_room": True, "check_only": True})
    mr = data["make_room"]
    assert mr["action"] == "sweep" and "toy_wrench#1" in mr["reason"] and "caramel_box#1" not in mr["reason"], mr
    assert srv.robot.log == []


def test_open_refused_while_holding(server):
    """손잡이를 잡으려면 그리퍼를 벌림 → 쥔 물체가 떨어짐 — 열기는 움직이기 전 HOLDING_OBJECT.
    열림 알림(displacement, 로봇 동작 없음)과 서랍 상태는 그대로."""
    srv = server.srv
    srv.disp = {}
    srv.held = {"class": "eraser", "id": "eraser#1", "width_m": 0.022, "drawer_id": "drawer_bottom",
                "tcp_above_floor_m": 0.011, "long_side": False}
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_top", "state": "open"})
    assert not out.success and out.error_code == "HOLDING_OBJECT" and srv.robot.log == [] and srv.disp == {}


# ---- 쌓인 물체 무너뜨리기(topple)는 뺌 [사용자 10/13 — 실물 NO_OBJECT_CONTACT, 쌓인 넛지로 충분]
def _key_on_caramel_scan(x=0.13, y=0.15):
    car = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.0185, "occluded_by": ["car_key#1"],
           "pose": {"frame": "drawer_top", "position": [x, y, 0.0], "yaw": 0.0, "yaw_valid": True}}
    key = {"id": "car_key#1", "class": "car_key", "top_z": 0.0185 + 0.0158, "occluded_by": [],
           "pose": {"frame": "drawer_top", "position": [x, y, 0.0], "yaw": 0.0, "yaw_valid": True}}
    return key, {"target_found": True, "target": key, "candidates": [car], "visible_count": 2}


def test_make_room_no_free_space_refused_before_motion(server):
    """make_room: 위 물체를 놓을 빈 자리가 없으면 움직이기 전 NO_FREE_SPACE (무너뜨리기로 넘어가지 않음)."""
    srv = server.srv
    key, scan = _key_on_caramel_scan()
    car = scan["candidates"][0]
    real = server.ss.clp.find_free_pose
    server.ss.clp.find_free_pose = lambda *a, **k: None
    try:
        out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": car, "make_room": True,
                                                "scan": dict(scan, target=car, candidates=[key])})
    finally:
        server.ss.clp.find_free_pose = real
    assert not out.success and out.error_code == "NO_FREE_SPACE", out.reason
    assert data["make_room"]["action"] == "fail" and srv.robot.log == []


def test_nudge_moves_use_slower_nudge_speeds_only_during_nudge(server):
    """[사용자 10/13 PC2 "clear 할 때 넛지하러 갈 때 기울이거나 하는 게 진짜 빨라서 무섭다, 이동 자체도 빨라"] 넛지 동작 중에만
    speed.nudge(서랍 안 직선·경유점 관절·손목 회전)를 씀. 넛지가 끝나면 평소 속도로 돌아옴(탑뷰 등은 그대로)."""
    srv = server.srv
    seen = []
    rb = srv.robot
    ml, mb, mj = rb.movel_async, rb.moveb_async, rb.movej_async
    rb.movel_async = lambda p, vel, acc, rot_vel=30.0, rot_acc=60.0, radius=0.0: (seen.append(("l", vel, rot_vel)), ml(p, vel, acc, rot_vel, rot_acc, radius))[1]
    rb.moveb_async = lambda pts, radii, vel, acc, rot_vel=30.0, rot_acc=60.0: (seen.append(("b", vel, rot_vel)), mb(pts, radii, vel, acc, rot_vel, rot_acc))[1]
    rb.movej_async = lambda j, vel, acc: (seen.append(("j", vel, None)), mj(j, vel, acc))[1]
    import copy
    real = srv.prm()
    prm = copy.deepcopy(real)
    prm["speed"]["nudge"] = nz = {"turn_deg_s": 25.0, "in_drawer_joint_deg_s": 45.0, "view_joint_deg_s": 45.0, "in_drawer_mm_s": 75.0}   # 10/13 기본은 비움(평소 속도)
    srv.prm = lambda: prm
    try:
        server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER})
    finally:
        del srv.prm
    assert seen and srv._careful is False
    assert all(rv == nz["turn_deg_s"] for k, _, rv in seen if k in "lb")               # 손목 회전·기울이기 느리게
    assert all(v <= max(nz["in_drawer_joint_deg_s"], nz["view_joint_deg_s"]) for k, v, _ in seen if k == "j")   # 관절 이동 느리게
    assert srv._speed()["turn_deg_s"] == srv.prm()["speed"]["turn_deg_s"]             # 넛지 밖은 평소 값
    srv._careful = True
    try:                                                                               # 기본 nudge {} = 넛지 중에도 평소 속도 [사용자 10/13]
        assert srv._speed() == srv.prm()["speed"]
    finally:
        srv._careful = False


def test_make_room_remove_first_param_overrides_config(server):
    """[사용자 10/13 "sweep 후 안 되면 어떤 게 방해되는지 파악해서 다른 물건을 빼내기"] B clear 가 같은 밀기를 되풀이했는데 목표가
    그대로면 다음 부름에 remove_first: true — 같은 벽 뭉침에서 밀기 대신 막는 물체를 집어 빈 자리로 옮기는 쪽을 먼저 (check_only)."""
    D = "drawer_top"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]

    def o(i, c, x, y, top, yaw):
        return {"id": i, "class": c, "pose": {"frame": D, "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True},
                "top_z": top, "occluded_by": [], "visible_area_m2": 0.002}
    air = o("airpods_case#1", "airpods_case", 0.1099, 0.0272, 0.0229, -0.0166)
    scan = {"target_found": True, "target": air, "visible_count": 4,
            "candidates": [o("caramel_box#1", "caramel_box", 0.04, 0.0293, 0.0229, -0.25),
                           o("toy_wrench#1", "toy_wrench", 0.1085, 0.0689, 0.0151, -0.1574),
                           o("eraser#1", "eraser", 0.1723, 0.0119, 0.0128, 0.0064)]}
    goal = {"drawer_id": D, "target": air, "scan": scan, "make_room": True, "check_only": True}
    _, base = server.run("nudge_object", goal)
    _, data = server.run("nudge_object", dict(goal, remove_first=True))
    mr = data["make_room"]
    assert base["make_room"]["action"] == "sweep"
    assert mr["action"] != "sweep" and "toy_wrench#1" in mr["reason"], mr   # 몽키만 빈 쪽으로 (에어팟 그대로)
    assert srv.robot.log == []


def test_make_room_wall_airpods_sweeps_once_without_pressing_wrench(server):
    """[실측 PC2 10/13 inspect_20261013_060416_812Z·062342_604Z] 오른쪽 벽 에어팟, 옆(+y) 몽키, 아래 캐러멜, 위 지우개 —
    예전: 몽키 머리를 눌러 +y 45 mm(접촉 없음). 지금: 몽키는 안 누르고 에어팟을 +y 로 밀며 몽키를 같이 밀고 되돌아오기 한 번
    (sweep 최대 make_room.sweep_max_mm) [사용자 10/13 "sweep 먼저", "몽키 헤드 낮은 부분을 자꾸 건드림"]."""
    D = "drawer_top"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]

    def o(i, c, x, y, top, yaw):
        return {"id": i, "class": c, "pose": {"frame": D, "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True},
                "top_z": top, "occluded_by": [], "visible_area_m2": 0.002}
    air = o("airpods_case#1", "airpods_case", 0.1079, 0.0219, 0.0229, 0.0065)
    scan = {"target_found": True, "target": air, "visible_count": 4,
            "candidates": [o("caramel_box#1", "caramel_box", 0.0361, 0.0221, 0.0229, -0.0055),
                           o("toy_wrench#1", "toy_wrench", 0.1135, 0.0525, 0.0161, -0.2055),
                           o("eraser#1", "eraser", 0.1731, 0.0102, 0.0138, 0.0042)]}
    out, data = server.run("nudge_object", {"drawer_id": D, "target": air, "scan": scan, "make_room": True, "check_only": True})
    mr = data["make_room"]
    assert mr["action"] == "sweep" and "toy_wrench#1" in mr["reason"] and "caramel_box#1" not in mr["reason"], mr
    assert srv.robot.log == []


def test_wrench_wall_check_uses_handle_width(server):
    """[실측 PC2 10/13 inspect_20261013_064400_105Z] 앞벽에서 56 mm 떨어져 거의 y 로 누운 몽키 — 손가락은 손잡이 폭(item_grasp 25.9)
    만큼만 벌어지는데 벽 확인을 외접 짧은 변(머리 폭 61)으로 해 "앞뒤 벽에 걸려 짧은 변으로 못 잡음". 손잡이 폭으로 확인."""
    D = "drawer_top"
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    w = {"id": "toy_wrench#1", "class": "toy_wrench", "top_z": 0.0162, "occluded_by": [], "visible_area_m2": 0.005,
         "pose": {"frame": D, "position": [0.0557, 0.1542, 0.0], "yaw": -1.379, "yaw_valid": True}}
    ok, code, reason = server.ss.DryOracle(srv, D).pick([w], w["id"])
    assert ok, (code, reason)
    assert srv.robot.log == []


def _srv_state(server):
    srv = server.srv
    srv.gate = server.ss.sf.MotionGate()
    srv.locked, srv.hold_unknown = None, None
    srv.expected_tcp, srv.expected_tool = "tcp", "tool"
    srv.robot.tool_names = lambda: ("tcp", "tool")
    return srv


def test_check_state_service_reports_without_motion(server):
    """W1 /skills/check_state [#152·#271 C 계약, 제안 10/13 B]: 멈춤·비상정지 아님·제어기 준비·B 잠금 없음·그리퍼 빈손 — 로봇·그리퍼 명령 없음."""
    srv = _srv_state(server)
    server.Gripper.width = 0.9
    resp = srv._srv_check_state(None, types.SimpleNamespace(success=None, message=None))
    st = json.loads(resp.message)
    assert resp.success and st["stopped"] is True and st["estop_active"] is False and st["controller_ready"] is True
    assert st["b_locked"] is False and st["gripper"]["state"] == "empty" and st["tcp_tool_ok"] is True
    assert st["drawers"] == {"drawer_bottom": 0.0, "drawer_top": 0.226}                # 연 적 없는 서랍도 0.0 [C #297]
    assert srv.robot.log == []
    srv.robot.tool_names = lambda: (None, None)
    assert json.loads(srv._srv_check_state(None, types.SimpleNamespace(success=None, message=None)).message)["tcp_tool_ok"] is None


def test_recover_service_clears_b_lock_and_unknown_hold(server):
    """W2 /skills/recover: 조건(멈춤·비상정지 아님·제어기 준비·툴·통신)이 되면 B 잠금을 풀고, 쥐었는지 모름은 그리퍼를 다시 읽어
    같은 폭이면 쥔 기억 복원. 비상정지면 아무것도 안 풂. 로봇·그리퍼 명령 없음."""
    srv = _srv_state(server)
    srv.locked = "pick_object: MOVE_UNCONFIRMED"
    srv.hold_unknown = {"class": "eraser", "id": "eraser#1", "width_m": 0.021}
    server.Gripper.width = 21.0
    real_state = srv.robot.state
    srv.robot.state = lambda: 6                                                     # 비상정지
    r = srv.recover()
    assert not r["recovered"] and "ESTOP_ACTIVE" in r["blockers"] and srv.locked and srv.hold_unknown
    srv.robot.state = real_state
    resp = srv._srv_recover(None, types.SimpleNamespace(success=None, message=None))
    r = json.loads(resp.message)
    assert resp.success and r["recovered"] and srv.locked is None and srv.hold_unknown is None
    assert srv.held and srv.held["id"] == "eraser#1" and r["state"]["gripper"]["state"] == "holding"
    assert srv.robot.log == []
    srv.held = None
    # [E #297 재리뷰 P1] 쥐었는지 모름 기록 21 mm 인데 지금 100 mm(열림)·30 mm(다른 물체) → 복원하지 않고 기록·잠금 유지
    for w in (100.0, 30.0):
        srv.locked = "pick_object: MOVE_UNCONFIRMED"
        srv.hold_unknown = {"class": "eraser", "id": "eraser#1", "width_m": 0.021}
        server.Gripper.width = w
        r = srv.recover()
        assert not r["recovered"] and r["blockers"] == ["HOLD_UNCERTAIN"] and srv.locked and srv.hold_unknown and not srv.held, w
    server.Gripper.width = 0.9                                                        # 빈손 닫힘 확정 → 기록 지우고 풂
    r = srv.recover()
    assert r["recovered"] and srv.hold_unknown is None and srv.held is None and srv.locked is None
    # [E #297 리뷰 P1] 쥔 기록이 없어도 RG2 안전 오류·폭 이상이면 잠금을 안 풂
    srv.locked = "pick_object: MOVE_UNCONFIRMED"
    real_status = server.Gripper.status
    try:
        from ready2go_skills.core.rg2_protocol import Rg2Status
        server.Gripper.status = lambda self: Rg2Status(0.9, False, True, True)          # safety_error
        r = srv.recover()
        assert not r["recovered"] and "SENSOR_INVALID" in r["blockers"] and srv.locked
        server.Gripper.status = lambda self: Rg2Status(-5.0, False, False, False)       # 폭 −5 mm
        st = srv.safe_state()
        assert st["gripper"]["state"] is None and st["sensors_ok"] is False
        assert not srv.recover()["recovered"] and srv.locked
    finally:
        server.Gripper.status = real_status
        srv.locked = None



SAFE_STATE_EXAMPLES = {name: {c["case"]: c for c in json.loads((REPO / f"contracts/examples/{name}.json").read_text(encoding="utf-8"))["cases"]}
                       for name in ("skills_check_state", "skills_recover")}


def _safe_state_cases(server):
    """W1·W2 예시 경우를 노드(가짜 로봇)로 만듦 → {(예시 파일, case): (success, message JSON 푼 것)}. stamp 는 비교에서 뺌."""
    srv, out = _srv_state(server), {}
    trig = lambda f: f(None, types.SimpleNamespace(success=None, message=None))       # noqa: E731
    w1 = lambda: trig(srv._srv_check_state)                                          # noqa: E731
    w2 = lambda: trig(srv._srv_recover)                                              # noqa: E731

    def put(name, case, resp):
        out[(name, case)] = (resp.success, json.loads(resp.message))
    unknown = {"class": "eraser", "id": "eraser#1", "width_m": 0.021}
    real_state = srv.robot.state
    rest = lambda p: [-1.12, 1.39, 0.31, 0.0, 0.0, 0.0]                             # noqa: E731 — 정지 중 영점 치우침 |F| 1.81 N [실측 10/13 일지 32]
    push = lambda p: [-12.0, 10.5, -0.5, 0.0, 0.0, 0.0]                             # noqa: E731 — 손으로 지그시 밀기 |F| 약 16 N
    srv.robot.force = rest
    server.Gripper.width = 0.9
    put("skills_check_state", "stopped_empty", w1())
    srv.robot.force = push
    put("skills_check_state", "external_force", w1())
    srv.locked = "pick_object: MOVE_UNCONFIRMED"
    put("skills_recover", "refused_external_force", w2())
    srv.locked, srv.robot.force = None, rest
    srv.held, server.Gripper.width = dict(unknown), 21.0
    put("skills_check_state", "holding_eraser", w1())
    srv.held = None
    srv.robot.state, server.Gripper.width = (lambda: 6), 0.9                          # 펜던트 비상정지 (DSR 6)
    put("skills_check_state", "estop", w1())
    srv.robot.state = real_state
    srv.locked, srv.hold_unknown, server.Gripper.width = "pick_object: MOVE_UNCONFIRMED", dict(unknown), 21.0
    put("skills_check_state", "hold_unknown_locked", w1())
    real_safe = srv.safe_state
    srv.safe_state = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("robot state service timeout"))
    put("skills_check_state", "query_error", w1())
    put("skills_recover", "server_error", w2())
    srv.safe_state = real_safe
    srv.robot.state = lambda: 6
    put("skills_recover", "refused_estop", w2())
    srv.robot.state, server.Gripper.width = real_state, 100.0                         # 21 mm 기록인데 100 mm 열림
    put("skills_recover", "refused_hold_uncertain", w2())
    assert srv.gate.try_enter()                                                      # 다른 동작 실행 중
    try:
        put("skills_recover", "busy", w2())
    finally:
        srv.gate.exit()
    server.Gripper.width = 21.0
    put("skills_recover", "recovered_restore", w2())
    srv.held = None
    return out


def _no_stamp(m):
    m = json.loads(json.dumps(m))
    for st in (m, m.get("state") or {}):
        st.pop("stamp", None)
    return m


def test_safe_state_examples_match_node_output(server):
    """contracts/examples/skills_check_state.json·skills_recover.json 의 경우를 노드로 그대로 — success·message 가 예시와 같음
    (stamp 만 뺌) [E #297 재리뷰: 예시를 검사하는 검증]. 로봇·그리퍼 명령 없음."""
    got = _safe_state_cases(server)
    want = {(n, c): (ex["success"], ex["message"]) for n, cases in SAFE_STATE_EXAMPLES.items() for c, ex in cases.items()}
    assert set(got) == set(want)
    for k in want:
        assert (got[k][0], _no_stamp(got[k][1])) == (want[k][0], _no_stamp(want[k][1])), k
    assert server.srv.robot.log == []



def test_check_state_external_force_reads_window_without_motion(server):
    """W1 external_force [B 실측 10/13 일지 32]: 멈춘 채 safe_state.external_force_hold_s 동안 rate_hz 로 툴 힘을 읽어(로봇 명령 없음)
    모두 |F| > external_force_n 이면 true. 한 번이라도 못 읽으면 null → W2 는 EXTERNAL_FORCE_UNKNOWN 으로 거절하고 잠금 유지."""
    srv = _srv_state(server)
    fp = srv.prm()["safe_state"]
    need = int(round(fp["external_force_hold_s"] * fp["external_force_rate_hz"]))
    reads = []

    def force(p):
        reads.append(1)
        return [-1.12, 1.39, 0.31, 0.0, 0.0, 0.0]
    srv.robot.force = force
    st = srv.safe_state()
    assert st["external_force"] is False and st["external_force_n"] == 1.81 and len(reads) == need
    calls = {"n": 0}

    def flaky(p):
        calls["n"] += 1
        return None if calls["n"] == 3 else [-12.0, 10.5, -0.5, 0.0, 0.0, 0.0]
    srv.robot.force, srv.locked = flaky, "pick_object: MOVE_UNCONFIRMED"
    r = srv.recover()
    assert not r["recovered"] and r["blockers"] == ["EXTERNAL_FORCE_UNKNOWN"] and srv.locked
    assert srv.robot.log == []
    srv.locked = None


def test_external_force_window_rechecks_motion_after(server):
    """[nomal-npc #335 리뷰 P1] 외력 판정 창(0.5 s) 도중 조그·외부 제어로 로봇이 움직이기 시작하면 창이 끝난 뒤 다시 읽은 상태로
    stopped false·external_force null → W2 는 잠금을 풀지 않음. 창 전에 한 번만 읽던 때는 stopped true·external_force false 로 풀었음."""
    srv = _srv_state(server)
    srv.locked = "pick_object: MOVE_UNCONFIRMED"
    real_state = srv.robot.state
    n = {"force": 0}

    def force(p):                                                  # 두 번째 읽기부터 로봇이 움직이는 중 (DSR 상태 2)
        n["force"] += 1
        if n["force"] == 2:
            srv.robot.state = lambda: 2
        return [-1.12, 1.39, 0.31, 0.0, 0.0, 0.0]
    srv.robot.force = force
    try:
        r = srv.recover()
        assert not r["recovered"] and srv.locked
        assert r["state"]["stopped"] is False and r["state"]["external_force"] is None
        assert r["blockers"][0] == "NOT_STOPPED" and "EXTERNAL_FORCE_UNKNOWN" in r["blockers"]
        srv.robot.state, n["force"] = real_state, 0                 # 창 도중 관절이 바뀐 경우 (DSR 상태는 대기 그대로)

        def nudge(p):
            n["force"] += 1
            if n["force"] == 2:
                srv.robot.j = [v + 0.5 for v in srv.robot.j]
            return [-1.12, 1.39, 0.31, 0.0, 0.0, 0.0]
        srv.robot.force = nudge
        st = srv.safe_state()
        assert st["stopped"] is False and st["external_force"] is None
        assert srv.robot.log == []
    finally:
        srv.robot.state, srv.locked = real_state, None

@pytest.mark.parametrize("case", ["moving", "unknown", "joints"])
def test_external_force_window_rejects_motion_that_returns_before_end(server, case):
    """[E #335 재리뷰 P1, head e3964d1] 창 도중 움직였다가(또는 상태를 못 읽다가) 창 끝 전에 원래 대기·관절로 돌아오면 창 전·후만
    읽어서는 못 봄 → 잠금 해제였음. 힘 읽을 때마다 상태·관절도 읽어 한 번이라도 멈춤이 아니면 그 창은 버림(외력 null) → W2 거절.
    경우마다 새 서버(상태·관절·MotionState 이력 따로) [E 재리뷰 P3]."""
    srv = _srv_state(server)
    srv.locked = "pick_object: MOVE_UNCONFIRMED"
    real_state, real_j = srv.robot.state, list(srv.robot.j)
    go, back = {
        "moving": (lambda: setattr(srv.robot, "state", lambda: 2), lambda: setattr(srv.robot, "state", real_state)),
        "unknown": (lambda: setattr(srv.robot, "state", lambda: None), lambda: setattr(srv.robot, "state", real_state)),
        "joints": (lambda: setattr(srv.robot, "j", [v + 0.5 for v in real_j]), lambda: setattr(srv.robot, "j", list(real_j))),
    }[case]
    n = {"force": 0}

    def force(p):                                                  # 두 번째 읽기에 움직이고(모르고) 여덟 번째에 원래대로
        n["force"] += 1
        if n["force"] == 2:
            go()
        elif n["force"] == 8:
            back()
        return [-1.12, 1.39, 0.31, 0.0, 0.0, 0.0]
    srv.robot.force = force
    try:
        r = srv.recover()
        assert n["force"] == 2                                      # 창 안 주입 샘플까지 갔고, 거기서 창을 버림(끝 전 복귀를 기다리지 않음)
        assert not r["recovered"] and srv.locked
        assert r["state"]["external_force"] is None and "EXTERNAL_FORCE_UNKNOWN" in r["blockers"], r
        assert srv.robot.log == []
    finally:
        srv.robot.state, srv.robot.j, srv.locked = real_state, real_j, None


def test_recover_reads_state_once_and_changes_nothing_on_error(server):
    """[E #297 재리뷰 P2] 복구는 상태를 처음 한 번만 읽고 응답을 다 만든 뒤에 잠금·쥔 기억을 바꿈 — 예전엔 잠금을 푼 뒤 응답용으로
    다시 읽다 예외가 나면 recovered=false 인데 잠금은 이미 풀려 있었음. 첫 조회 성공 → 두 번째부터 예외여도 정상 복구, 응답 state 는
    푼 뒤 값. 첫 조회부터 예외면 SKILL_EXCEPTION 이고 잠금·모름 기록 그대로."""
    srv = _srv_state(server)
    real = srv.safe_state
    calls = []

    def once(*a, **k):
        calls.append(k)
        if len(calls) > 1:
            raise RuntimeError("second read")
        return real(*a, **k)
    for width, held_id in ((21.0, "eraser#1"), (0.9, None)):                # 같은 폭 → 복원 / 빈손 닫힘 → 지움
        srv.locked, srv.held = "pick_object: MOVE_UNCONFIRMED", None
        srv.hold_unknown = {"class": "eraser", "id": "eraser#1", "width_m": 0.021}
        server.Gripper.width, calls[:] = width, []
        srv.safe_state = once
        resp = srv._srv_recover(None, types.SimpleNamespace(success=None, message=None))
        srv.safe_state = real
        r = json.loads(resp.message)
        assert resp.success and r["recovered"] and len(calls) == 1, (width, r)
        assert srv.locked is None and srv.hold_unknown is None and (srv.held or {}).get("id") == held_id
        st = r["state"]
        assert st["b_locked"] is False and st["b_lock_reason"] is None and st["gripper"]["held_id"] == held_id
        assert st["gripper"]["state"] == ("holding" if held_id else "empty") and st["gripper"]["reason"] == ("HELD" if held_id else "")
        assert {k: v for k, v in st.items() if k != "stamp"} == {k: v for k, v in srv.safe_state().items() if k != "stamp"}   # 다시 읽은 W1 과 같음
    srv.locked, srv.held = "pick_object: MOVE_UNCONFIRMED", None
    srv.hold_unknown = {"class": "eraser", "id": "eraser#1", "width_m": 0.021}
    srv.safe_state = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("first read"))
    resp = srv._srv_recover(None, types.SimpleNamespace(success=None, message=None))
    srv.safe_state = real
    assert not resp.success and json.loads(resp.message)["code"] == "SKILL_EXCEPTION"
    assert srv.locked == "pick_object: MOVE_UNCONFIRMED" and srv.hold_unknown and srv.held is None
    assert srv.robot.log == []
    srv.locked = srv.hold_unknown = None

def test_masking_tape_nudge_pushes_inside_hole(server, monkeypatch):
    """[사용자 10/13] 마스킹테이프는 가운데가 뚫려 위에서 누르면 손끝이 구멍으로 빠져 바닥에 닿음 → 넛지 대신 닫은 손가락을
    구멍(가운데)에 넣어 계획한 방향·거리 + hole_slack_mm 만큼 수평으로 밂, hole_back_mm 물러났다가 올림. 누르기(press) 없음."""
    from ready2go_skills.core import motion_plan as mp
    srv = server.srv
    d = srv.prm()["drag"]
    tf = srv.places()["drawer_top"]["tf"]
    tape = {"id": "masking_tape#1", "class": "masking_tape", "top_z": 0.0152,
            "pose": {"frame": "drawer_top", "position": [0.10, 0.021, 0.0], "yaw": 0.0, "yaw_valid": True}}   # 오른쪽 벽(y 0)에 붙음
    stages = []
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        stages.append(stage)
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": tape})
    assert out.success and "구멍" in out.reason, out.reason
    i = stages.index("push")
    assert stages[i - 1] == "push_down" and stages[i + 1:i + 3] == ["push_back", "lift"] and "press" not in stages
    moves = [e[1] for e in srv.robot.log if e != "stop" and e[0] == "movel"]
    a, b, c = (mp.from_base(tf, [v / 1000.0 for v in m[:3]]) for m in moves[i - 1:i + 2])
    assert a[0] == pytest.approx(0.10, abs=1e-3) and a[1] == pytest.approx(0.021, abs=1e-3)       # 구멍(가운데)에 내려감
    assert b[1] > a[1] + d["hole_slack_mm"] / 1000.0 and abs(b[0] - a[0]) < 1e-3                  # +y(벽 반대)로만 밂
    assert (b[1] - c[1]) * 1000.0 == pytest.approx(d["hole_back_mm"], abs=0.1)
    assert data["target_after"]["pose"]["position"][1] > tape["pose"]["position"][1]


def test_force_mode_presses_by_force_and_releases_before_lift(server, monkeypatch):
    """drag.force_mode [사용자 10/13 힘 제어]: 위치로 내려가며 5 N 문턱·멈춘 채 확인·0.1 mm 힘 맞추기 대신 누를 자리 위에서
    두산 힘 제어(z 만, sweep 은 sweep_force_n 가운데)를 켜면 내려가 닿고 그 힘 그대로 끈 뒤, 올리기 전에 풂. 누르기 직선(press) 없음."""
    import copy
    from ready2go_skills.core import clear_plan as clp
    srv = server.srv
    prm = copy.deepcopy(srv.prm())
    prm["drag"]["force_mode"] = True
    monkeypatch.setattr(srv, "prm", lambda: prm)
    calls, held = [], {}

    def force_on(fz, stx, ramp=0.2):                       # 가짜 제어기: 켜면 3 mm 내려가 물체에 닿아 그 힘으로 멈춤
        calls.append(("on", round(fz, 2)))
        srv.robot.p[2] -= 3.0
        held["f"] = fz
        return True

    def force_off(ramp=0.2):
        calls.append(("off",))
        held.pop("f", None)
        return True
    srv.robot.force_on, srv.robot.force_off = force_on, force_off
    srv.robot.force = lambda p: [0.0, 0.0, -held.get("f", 0.0), 0.0, 0.0, 0.0]
    t = _seg(ERASER_FREE)
    t["pose"]["yaw"] = 0.0
    nb = _seg(CARAMEL_NEXT)
    nb["pose"]["position"] = [0.10, 0.15 - 0.011 - 0.0245 - 0.002, 0.0]
    sweep = clp.Action("sweep", "eraser#1", "30 mm 밀고 15 mm 되돌아옴", dir=(0.0, -1.0), dist_m=0.03, back_m=0.015,
                       pushed=("caramel_box#1",), extra={})
    monkeypatch.setattr(server.ss.clp, "plan_next", lambda *a, **k: sweep)
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None, **kw):
        calls.append(("line", stage))
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True, "scan": _scan_with(t, nb)})
    assert out.success, out.reason
    seq = [c[0] if c[0] != "line" else c[1] for c in calls]
    lo, hi = prm["drag"]["sweep_force_n"]
    assert ("on", round((lo + hi) / 2, 2)) in calls and "press" not in seq
    i_on, i_off = seq.index("on"), seq.index("off")
    assert i_on < seq.index("drag") < seq.index("drag_back") < i_off < len(seq) - 1 - seq[::-1].index("lift")
    assert seq.count("on") == 1 and seq.count("off") == 1 and not srv._force_active


def test_force_mode_no_object_releases_and_refuses(server, monkeypatch):
    """힘 제어로 내려가도 예상 윗면 아래 force_search_below_mm 넘게 빠지면(구멍·빈 자리) 풀고 NO_OBJECT_CONTACT, 끌지 않음."""
    import copy
    from ready2go_skills.core import clear_plan as clp
    srv = server.srv
    prm = copy.deepcopy(srv.prm())
    prm["drag"]["force_mode"] = True
    monkeypatch.setattr(srv, "prm", lambda: prm)
    calls = []

    def force_on(fz, stx, ramp=0.2):
        calls.append("on")
        srv.robot.p[2] -= 40.0                                                       # 닿을 것 없이 쭉 내려감
        return True
    srv.robot.force_on = force_on
    srv.robot.force_off = lambda ramp=0.2: calls.append("off") or True
    t = _seg(ERASER_FREE)
    t["pose"]["yaw"] = 0.0
    nudge = clp.Action("nudge", "eraser#1", "빈 쪽(-y)으로 20 mm", dir=(0.0, -1.0), dist_m=0.02, extra={})
    monkeypatch.setattr(server.ss.clp, "plan_next", lambda *a, **k: nudge)
    out, _ = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True, "scan": _scan_with(t)})
    n = int(prm["drag"].get("press_attempts", 1))                                     # 끌기 전 실패는 같은 자리에서 다시 (기존 규칙)
    assert out.error_code == server.ss.NO_OBJECT_CONTACT and calls == ["on", "off"] * n, (out, calls)
    assert not srv._force_active


def test_force_mode_off_is_unchanged_and_release_is_safety_net(server):
    """force_mode 기본 false — 힘 제어를 부르지 않음. 켜져 있던 힘 제어 해제가 실패하면 STATE_UNKNOWN(서버 잠금 코드)."""
    srv = server.srv
    assert srv.prm()["drag"]["force_mode"] is False
    assert srv._force_release() is None                                               # 켜진 적 없으면 아무것도 안 함
    srv._force_active = True
    srv.robot.force_off = lambda ramp=0.2: False
    r = srv._force_release()
    assert r is not None and r.error_code == server.ss.sf.STATE_UNKNOWN and not srv._force_active


# [PC2 10/14 통합 덤프] 위 칸 몽키·캐러멜·차키 쌓음(inspect_20261014_043203_153Z), 아래 칸 판이 지우개·립밤 덮음(…_042948_407Z)
SCAN_1014_TOP_KEY = json.loads('{"target_found": true, "target": {"id": "car_key#1", "class": "car_key", "pose": {"frame": "drawer_top", "position": [0.08, 0.2221, 0.0], "yaw": -1.5122, "yaw_valid": true}, "top_z": 0.0518, "occluded_by": [], "visible_area_m2": 0.002457}, "candidates": [{"id": "caramel_box#1", "class": "caramel_box", "pose": {"frame": "drawer_top", "position": [0.0415, 0.2183, 0.0], "yaw": 1.5701, "yaw_valid": true}, "top_z": 0.0367, "occluded_by": ["car_key#1"], "visible_area_m2": 0.00149}, {"id": "toy_wrench#1", "class": "toy_wrench", "pose": {"frame": "drawer_top", "position": [0.1142, 0.2164, 0.0], "yaw": 0.1783, "yaw_valid": true}, "top_z": 0.0167, "occluded_by": ["car_key#1"], "visible_area_m2": 0.003417}], "visible_count": 3}')
SCAN_1014_BOTTOM_PLATE = json.loads('{"target_found": true, "target": {"id": "eraser#1", "class": "eraser", "pose": {"frame": "drawer_bottom", "position": [0.107, 0.1402, 0.0], "yaw": 1.5667, "yaw_valid": true}, "top_z": 0.0133, "occluded_by": ["cover_plate#1"], "visible_area_m2": 0.000827}, "candidates": [{"id": "cover_plate#1", "class": "cover_plate", "pose": {"frame": "drawer_bottom", "position": [0.1032, 0.1967, 0.0], "yaw": -0.0378, "yaw_valid": true}, "top_z": 0.0351, "occluded_by": [], "visible_area_m2": 0.007296}, {"id": "lip_balm#1", "class": "lip_balm", "pose": {"frame": "drawer_bottom", "position": [0.0754, 0.1439, 0.0], "yaw": 0.0, "yaw_valid": false}, "top_z": 0.0204, "occluded_by": ["cover_plate#1"], "visible_area_m2": 0.000646}], "visible_count": 3}')


def _with_pick(server, monkeypatch, **pick):
    real = server.ss._yaml_cached

    def cached(path, **kw):
        d = real(path, **kw)
        if path.name == "skills.yaml":
            d = {**d, "pick": {**d["pick"], **pick}}
        return d
    monkeypatch.setattr(server.ss, "_yaml_cached", cached)


@pytest.mark.parametrize("swap", [True, False])
def test_pick_crosswise_swaps_to_short_side_before_nudge(server, monkeypatch, swap):
    """[사용자 10/14 PC2 "① 잡기 편한 방식 ② 안 되면 가로세로 바꿔 잡기 ③ 그래도 안 되면 넛지나 sweep"] 가로 차키(쌓인 맨 위)는
    긴 변 양끝이면 옆벽 2.1 mm 부족 → 예전엔 넛지(쌓인 차키 누르기 실패), 짧은 변(90° 돌림)이면 바로 잡힘. 판단만 — 로봇 명령 0."""
    _with_pick(server, monkeypatch, axis_swap=swap)
    srv = server.srv
    srv.disp["drawer_top"] = srv.places()["drawer_top"]["tf_at_travel_m"]
    scan = json.loads(json.dumps(SCAN_1014_TOP_KEY))
    out, _ = server.run("place_object", {"location": "drawer_top", "slot": "free", "scan": scan, "object": scan["target"], "check_only": True})
    if swap:
        assert out.success, out.reason
    else:
        assert out.error_code == "WALL_TOO_CLOSE" and "2.1 mm" in out.reason, out.reason
    assert srv.robot.log == [] and srv.held is None


@pytest.mark.parametrize("repickable_only", [True, False])
def test_free_plate_place_only_then_nudge_on_restore(server, monkeypatch, repickable_only):
    """[PC2 10/14 아래 칸] 판이 지우개·립밤을 덮은 장면: 지우개 손가락 자리를 비우면서 다시 집히는 빈 자리는 없음(옆벽 여유 5.6~25 mm
    부족). 기본(place.free_repickable_only true, #337) = 움직이기 전 NO_FREE_SPACE(집지 않음). false = 놓기만 되는 자리 (60, 232) 에
    놓고, 원복 때 집기 WALL_TOO_CLOSE → 넛지(옆벽 반대 y −) 계획 — 부르는 쪽(Runner)에 원복 넛지가 있어야 함(#345 리뷰)."""
    real = server.ss._yaml_cached

    def cached(path, **kw):
        dd = real(path, **kw)
        if path.name == "skills.yaml":
            dd = {**dd, "place": {**dd["place"], "free_repickable_only": repickable_only}}
        return dd
    monkeypatch.setattr(server.ss, "_yaml_cached", cached)
    srv = server.srv
    d = "drawer_bottom"
    srv.disp[d] = srv.places()[d]["tf_at_travel_m"]
    scan = json.loads(json.dumps(SCAN_1014_BOTTOM_PLATE))
    plate, lip = scan["candidates"]
    out, data = server.run("place_object", {"location": d, "slot": "free", "scan": scan, "object": plate, "check_only": True})
    if repickable_only:
        assert out.error_code == "NO_FREE_SPACE", out.reason
        assert srv.robot.log == [] and srv.held is None
        return
    assert out.success, out.reason
    pose = data["planned_pose"]
    assert pose["position"][:2] == pytest.approx([0.06, 0.232], abs=0.006)
    # 원복: 지우개는 트레이로 갔고, 판은 놓은 자리, 립밤은 판 밑에서 드러나 각도를 앎
    moved = dict(plate, occluded_by=[], pose=dict(pose, yaw_valid=True))
    lip = dict(lip, occluded_by=[], pose=dict(lip["pose"], yaw=0.0, yaw_valid=True))
    back = {"target_found": True, "target": moved, "candidates": [lip], "visible_count": 2}
    out, _ = server.run("place_object", {"location": d, "pose": plate["pose"], "scan": back, "object": moved, "check_only": True})
    assert out.error_code == "WALL_TOO_CLOSE", out.reason                 # 놓기만 되는 자리 — 바로는 못 집음
    out, nd = server.run("nudge_object", {"drawer_id": d, "target": moved, "scan": back, "check_only": True})
    assert out.error_code == "PUSH_LIMIT" and nd["needed"] and "y -" in out.reason, out.reason   # 끌면 집힘 (움직이지 않음)
    assert srv.robot.log == [] and srv.held is None


def _with_prm(server, monkeypatch, **sections):
    """skills.yaml 섹션 일부만 바꿔 읽게 (예: motion={"one_turn": True}, carry={"direct": True})."""
    real = server.ss._yaml_cached

    def cached(path, **kw):
        d = real(path, **kw)
        if path.name == "skills.yaml":
            d = dict(d)
            for k, v in sections.items():
                d[k] = {**(d.get(k) or {}), **v}
        return d
    monkeypatch.setattr(server.ss, "_yaml_cached", cached)


def _turning_movej(server, drawer_id="drawer_top"):
    """가짜 로봇: 경유점(drag_down) J1~J5 로 가는 movej 면 TCP 를 경유점(carry_line 1)에 두고 J6 차이만큼 손목(C)도 돌려 둠 —
    그리퍼 수직에서 J6 +θ = posx (C − A) +θ [계산 m0609_kin]."""
    srv = server.srv
    down = srv.poses()["drag_down"][drawer_id]
    wp = srv.poses()["carry_line"][drawer_id][0]
    real = srv.robot.movej_async

    def movej(j, v, a):
        ok = real(j, v, a)
        if list(j[:5]) == list(down[:5]):
            srv.robot.p = list(wp[:5]) + [wp[5] + (j[5] - down[5])]
        return ok
    srv.robot.movej_async = movej
    return down, wp


def test_pick_one_turn_rotates_wrist_once_on_way_to_waypoint(server, monkeypatch):
    """[사용자 10/14 P2 시연 뒤] motion.one_turn: 탑뷰 → 경유점 관절 이동에 잡는 J6 를 넣어 한 번에 — 경유점 기본 방향 도착 뒤
    J6 만 따로 돌리는 movej 가 없음. 내려가는 손목 각도·잡는 자리는 끔/켬이 같음."""
    srv = server.srv
    down, _ = _turning_movej(server)
    t = json.loads(json.dumps(ERASER_FREE))
    t["pose"]["yaw"] = -0.7
    seen = {}
    for one_turn in (False, True):
        _with_prm(server, monkeypatch, motion={"one_turn": one_turn})
        srv.robot.p, srv.robot.j, srv.held = [380.0, -6.5, 300.0, 90.0, -90.0, 180.0], [0.0, 0.0, 90.0, 0.0, 90.0, 0.0], None
        server.Gripper.holding = True
        srv.robot.log.clear()
        try:
            out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
        finally:
            server.Gripper.holding = False
        assert out.success, out.reason
        log = srv.robot.log
        first_b = next(k for k, e in enumerate(log) if e[0] == "moveb")
        js = [e[1] for e in log[:first_b] if e[0] == "movej" and list(e[1][:5]) == list(down[:5])]   # 경유점·J6 만 (탑뷰 이동 빼고)
        assert len(js) == (1 if one_turn else 2)
        assert (abs(js[0][5] - down[5]) > 1.0) == one_turn
        seen[one_turn] = (js[-1][5], log[first_b][1][-1])
    assert seen[True][0] == pytest.approx(seen[False][0], abs=1e-6)     # 끝 J6 같음
    from ready2go_skills.core import pose_math as pm
    a, b = seen[True][1], seen[False][1]
    assert a[:3] == pytest.approx(b[:3], abs=1e-6)                      # 목표 위로 내려가는 점 같음
    assert pm.rotation_angle(pm.rot(*a[3:6]), pm.rot(*b[3:6])) < 0.05  # 손목도 같은 방향 (표기 ±360 차이는 같은 방향)


def test_place_in_drawer_one_turn_from_waypoint_turns_once_and_keeps_wrist_back(server, monkeypatch):
    """[사용자 10/14 "90° 기준으로 돌려 경유점 만든 뒤 목표 각도로"] 집은 뒤 경유점 자리(손목은 집은 각도)에서 서랍 안 놓기:
    끔 = 경유점 기본 방향 movej → J6 따로 / 켬 = 경유점 movej 없이 J6 한 번. 놓는 자리·손목은 같고, 켬이면 돌아갈 때 손목 그대로."""
    srv = server.srv
    down, wp = _turning_movej(server)
    seen = {}
    for one_turn in (False, True):
        _with_prm(server, monkeypatch, motion={"one_turn": one_turn})
        _holding_in_drawer(server)
        srv.robot.p = list(wp[:5]) + [wp[5] + 50.0]                     # 경유점 자리, 손목은 집은 각도(기본에서 50°)
        srv.robot.j = list(down[:5]) + [down[5] + 50.0]
        srv.robot.log.clear()
        out, _ = server.run("place_object", {"location": "drawer_top", "pose": ASIDE_POSE, "scan": EMPTY_SCAN})
        assert out.success, out.reason
        log = srv.robot.log
        assert (("movej", down) in log) is (not one_turn)
        assert len([e for e in log if e[0] == "movej"]) == (1 if one_turn else 2)
        lines = [p for e in log if e[0] in ("movel", "moveb") for p in ([e[1]] if e[0] == "movel" else e[1])]
        low, back = min(lines, key=lambda p: p[2]), lines[-1]
        assert back[:2] == pytest.approx(wp[:2])
        assert back[3:] == pytest.approx(low[3:] if one_turn else wp[3:])   # 켬: 돌아갈 때 손목 그대로 (다음 관절 이동이 한 번에 돌림)
        seen[one_turn] = low
    assert seen[True] == pytest.approx(seen[False], abs=1e-6)           # 놓는 자리·손목 같음

@pytest.mark.parametrize("direct", [False, True])
def test_carry_direct_turns_wrist_on_long_leg_without_stop(server, monkeypatch, direct):
    """[사용자 10/14 "경유점 두 번"] carry.direct: 경유점 1 에서 J6 만 돌리는 movej 없이, 1→2(짧음)는 집은 손목 그대로,
    2→3(긴 구간)부터 놓는 손목 — 블렌딩 한 번. 끄면 지금처럼 J6 먼저."""
    _with_prm(server, monkeypatch, carry={"direct": direct})
    srv = server.srv
    route = srv.poses()["carry_line"]["drawer_top"]
    grasp_ang = [156.1, 180.0, -139.4]
    srv.held = dict(LIP_HELD)
    server.Gripper.holding, server.Gripper.width = True, 19.5
    srv.robot.p = list(route[0][:3]) + grasp_ang
    srv.robot.log.clear()
    try:
        out, _ = server.run("place_object", {"location": "handover_zone"})
    finally:
        server.Gripper.holding = False
    assert out.success, out.reason
    log = srv.robot.log
    first_b = next(k for k, e in enumerate(log) if e[0] == "moveb")
    assert any(e[0] == "movej" for e in log[:first_b]) is (not direct)
    pts = log[first_b][1]
    assert pts[0][:3] == route[1][:3] and pts[1][:3] == route[2][:3]
    if direct:
        assert pts[0][3:] == grasp_ang and pts[1][3:] == pts[-1][3:] != grasp_ang
    else:
        assert all(p[3:] == pts[-1][3:] for p in pts)


@pytest.mark.parametrize("supported", [True, False])
def test_carry_spline_uses_guided_movesx_or_falls_back_to_moveb(server, monkeypatch, supported):
    """[강사님 피드백 10/13] carry.spline: 칸 위까지 movesx guided(교시점이 아니라 moveb 둥근 경로 위 점) → 마지막 1 cm 위까지 직선.
    드라이버에 movesx 가 없으면 아무것도 안 보내고 지금 moveb 그대로."""
    _with_prm(server, monkeypatch, carry={"spline": True})
    srv = server.srv
    route = srv.poses()["carry_line"]["drawer_top"]

    def movesx(pts, vel, acc, rot_vel=30.0, rot_acc=60.0, const_vel=True):
        if not supported:
            return "unsupported"
        srv.robot.log.append(("movesx", [list(p) for p in pts]))
        srv.robot.p = list(pts[-1])
        return True
    srv.robot.movesx_async = movesx
    srv.held = dict(LIP_HELD)
    server.Gripper.holding, server.Gripper.width = True, 19.5
    srv.robot.p = list(route[0])
    srv.robot.log.clear()
    try:
        out, data = server.run("place_object", {"location": "handover_zone"})
    finally:
        server.Gripper.holding = False
    assert out.success, out.reason
    assert data["slot"] == "handover_zone_1"
    kinds = [e[0] for e in srv.robot.log]
    if not supported:
        assert "movesx" not in kinds and "moveb" in kinds
        return
    assert "moveb" not in kinds
    via = next(e[1] for e in srv.robot.log if e[0] == "movesx")
    assert len(via) == srv.prm()["carry"]["spline_via"]
    assert max(p[2] for p in via) <= max(r[2] for r in route) + 1e-6   # 교시점보다 위로 안 부풂
    k = kinds.index("movesx")
    assert kinds[k + 1] == "movel" and srv.robot.log[k + 1][1][:2] == pytest.approx(via[-1][:2])   # 칸 위 → 1 cm 위까지 직선
    assert via[-1][2] == pytest.approx(route[-1][2]) and srv.robot.log[k + 1][1][2] < via[-1][2]


@pytest.mark.parametrize("window", [0.0, 3.0])
def test_place_touch_window_ignores_early_wobble_but_stops_on_floor(server, monkeypatch, window):
    """[사용자 10/14 PC2] 덮개 판을 같은 free 자리에 한 번은 바닥에, 한 번은 5 mm 위에서 놓음(기울지 않음) — 마지막 천천히 내리기에서
    목표 5 mm 위 흔들림(4 N)을 바닥으로 봄 [추정]. place.touch_window_mm 3: 그건 무시하고 내려가 진짜 바닥(목표)에서 멈춤. 0 = 지금처럼."""
    _with_prm(server, monkeypatch, place={"touch_window_mm": window})
    srv = server.srv
    _holding_in_drawer(server)
    out, _ = server.run("place_object", {"location": "drawer_top", "pose": ASIDE_POSE, "scan": EMPTY_SCAN})
    assert out.success, out.reason
    deeper = [e[1] for e in srv.robot.log if e[0] == "movel"]
    tz = min(p[2] for p in deeper) + srv.prm()["place"]["touch_overtravel_mm"]   # 놓는 목표 높이
    logs = []
    srv.get_logger = lambda: types.SimpleNamespace(info=logs.append, warn=logs.append, warning=logs.append, error=logs.append)
    srv.robot.force = lambda p: [0.0, 0.0, 4.0 if (tz + 4.5 <= p[2] <= tz + 5.5 or p[2] <= tz) else 0.0, 0.0, 0.0, 0.0]
    opened = []
    real_grip = srv._grip
    srv._grip = lambda w, f: opened.append(srv.robot.p[2]) or real_grip(w, f)
    _holding_in_drawer(server)
    srv.robot.log.clear()
    out, _ = server.run("place_object", {"location": "drawer_top", "pose": ASIDE_POSE, "scan": EMPTY_SCAN})
    assert out.success, out.reason
    z = opened[-1]
    msg = next(m for m in logs if "닿아서 멈춤" in m)
    if window:
        assert z == pytest.approx(tz, abs=0.5) and "무시" in msg            # 흔들림은 넘기고 바닥(목표)에서
    else:
        assert z == pytest.approx(tz + 5.0, abs=0.6) and "+5" in msg       # 지금: 5 mm 위에서 놓음 (로그에 남음)


@pytest.mark.parametrize("on_way", [False, True])
def test_pick_open_on_way_opens_during_waypoint_move(server, monkeypatch, on_way):
    """[사용자 10/15 "뷰 찍고 집으러 내려오면서 그리퍼 벌려두면"] pick.open_on_way: 끔 = 탑뷰에서 닫고 경유점 도착 뒤 벌림,
    켬 = 닫지 않고 경유점 관절 이동과 같이 벌림, 목표 위로 가기(moveb) 전에 다 벌림. 잡는 자리·결과는 같음."""
    srv = server.srv
    down, _ = _turning_movej(server)
    _with_prm(server, monkeypatch, pick={"open_on_way": on_way})
    orig = server.Gripper.move
    monkeypatch.setattr(server.Gripper, "move", lambda self, w, f: (srv.robot.log.append(("grip", w)), orig(self, w, f))[1])
    srv.robot.p, srv.robot.j, srv.held = [380.0, -6.5, 300.0, 90.0, -90.0, 180.0], [0.0, 0.0, 90.0, 0.0, 90.0, 0.0], None
    server.Gripper.holding = True
    try:
        out, _ = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    finally:
        server.Gripper.holding = False
    assert out.success, out.reason
    log = srv.robot.log
    first_b = next(k for k, e in enumerate(log) if e[0] == "moveb")
    grips = [e[1] for e in log[:first_b] if e[0] == "grip"]
    assert grips == ([grips[-1]] if on_way else [0, grips[-1]]) and grips[-1] > 0     # 켬이면 닫지 않음, 벌리기는 목표 위로 가기 전에 끝
    wp = next(k for k, e in enumerate(log) if e[0] == "movej" and list(e[1][:5]) == list(down[:5]))
    if not on_way:
        assert log.index(("grip", 0)) < wp < log.index(("grip", grips[-1]))          # 끔: 닫고 → 경유점 → 벌림 (지금 동작)


def test_carry_spline_turns_wrist_first_and_keeps_angles_in_movesx(server, monkeypatch):
    """[실측 PC2 10/15 차키] carry.spline + direct + 손목 90°: 스플라인 안에서 손목 각을 바꾸면 각도 숫자가 점 하나에서 270~360° 뛰어
    J5 한계(STOP_UNCONFIRMED). → 스플라인이면 경유점 1 에서 J6 먼저(carry:turn), movesx 점은 모두 지금 각도 숫자 그대로."""
    _with_prm(server, monkeypatch, carry={"spline": True, "direct": True})
    srv = server.srv
    route = srv.poses()["carry_line"]["drawer_top"]
    seen = {}

    def movesx(pts, vel, acc, rot_vel=30.0, rot_acc=60.0, const_vel=True):
        seen["via"], seen["start"] = [list(p) for p in pts], list(srv.robot.p)
        srv.robot.p = list(pts[-1])
        return True
    srv.robot.movesx_async = movesx
    srv.held = dict(LIP_HELD)
    server.Gripper.holding, server.Gripper.width = True, 19.5
    start = list(route[0])
    start[5] += 90.0                                                    # 집은 손목이 놓는 방향과 90° 다름
    srv.robot.p, srv.robot.j = start, [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
    srv.robot.log.clear()
    try:
        out, _ = server.run("place_object", {"location": "handover_zone"})
    finally:
        server.Gripper.holding = False
    assert out.success, out.reason
    log = srv.robot.log
    turn_k = next(k for k, e in enumerate(log) if e[0] == "movej")         # 경유점 1 에서 J6 먼저
    assert turn_k < len(log) and "via" in seen
    assert all(v[3:6] == seen["start"][3:6] for v in seen["via"])       # 스플라인 안 손목 각 숫자 그대로
    assert max(v[2] for v in seen["via"]) <= max(p[2] for p in route) + 1.0


def test_pick_open_on_way_unfinished_open_is_not_hidden_as_move_failure(server, monkeypatch):
    """[#365 E P1] pick.open_on_way 에서 경유점 이동이 실패했는데 RG2 벌리기가 기다리는 시간 안에 안 끝나면: 일반 이동 실패로
    숨기지 않고 STATE_UNKNOWN(잠금 코드) + 서버 잠금 — 늦게 끝나는 벌리기가 다음 그리퍼 명령과 겹치지 않게."""
    import threading
    srv = server.srv
    down, _ = _turning_movej(server)
    _with_prm(server, monkeypatch, pick={"open_on_way": True})
    gate, started = threading.Event(), threading.Event()
    real = srv._grip

    def slow_grip(w, f):                                                # 장치 지연 — 풀어 줄 때까지 안 끝남
        started.set()
        gate.wait(5.0)
        return real(w, f)
    srv._grip = slow_grip
    srv.grip_wait_s = 0.05
    srv.locked = None
    mj = srv.robot.movej_async
    srv.robot.movej_async = lambda j, vel, acc: False if list(j[:5]) == list(down[:5]) else mj(j, vel, acc)   # 경유점 이동만 거부
    srv.robot.p, srv.robot.j, srv.held = [380.0, -6.5, 300.0, 90.0, -90.0, 180.0], [0.0, 0.0, 90.0, 0.0, 90.0, 0.0], None
    try:
        out, _ = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    finally:
        gate.set()
    assert started.is_set(), out
    assert not out.success and out.error_code == server.ss.sf.STATE_UNKNOWN, out
    assert "벌리기" in out.reason and srv.locked


def test_repo_defaults_are_pc2_tested_and_run_together(server, monkeypatch):
    """[사용자 10/15 "다 잘 돌아가니 이대로 확정"] 저장소 skills.yaml 기본값 = PC2 실물로 확인한 6개 켬. 끈 값 고정(LEGACY_FLAGS)을
    풀고 그대로 집기(open_on_way·one_turn) → 건네기 놓기(spline+direct, 손목 90°)가 잠금 없이 끝남."""
    monkeypatch.setattr(server.ss, "_yaml_cached", server.yaml_real)
    srv = server.srv
    prm = server.yaml_real(srv.params_file)
    want = {"motion": {"one_turn": True}, "carry": {"direct": True, "spline": True},
            "transit": {"view_blend_in_drawer": True}, "pick": {"open_on_way": True}, "place": {"touch_window_mm": 3.0}}
    for sec, kv in want.items():
        for k, v in kv.items():
            assert prm[sec][k] == v, (sec, k, prm[sec][k])
    _turning_movej(server)
    server.Gripper.holding = True
    try:
        out, _ = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    finally:
        server.Gripper.holding = False
    assert out.success, out.reason

    route = srv.poses()["carry_line"]["drawer_top"]
    seen = []
    srv.robot.movesx_async = lambda pts, *a, **kw: (seen.append(len(pts)), setattr(srv.robot, "p", list(pts[-1])), True)[2]
    srv.held = dict(LIP_HELD)
    server.Gripper.holding, server.Gripper.width = True, 19.5
    start = list(route[0])
    start[5] += 90.0
    srv.robot.p, srv.robot.j = start, [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
    try:
        out, _ = server.run("place_object", {"location": "handover_zone"})
    finally:
        server.Gripper.holding = False
    assert out.success, out.reason
    assert seen and getattr(srv, "locked", None) is None                # movesx 로 감, 잠금 없음


def test_dry_place_works_with_grip_height_ratio_null(server, monkeypatch):
    """[10/15 정리] pick.grip_height_ratio 는 null(예전 높이 방식)도 쓸 수 있는 값 — 빈 자리 판단(DryOracle.place)이 None × 높이로
    예외를 내지 않고 0.5 로 봄. 판단만 — 로봇 명령 없음."""
    _with_prm(server, monkeypatch, pick={"grip_height_ratio": None})
    er = _seg(ERASER_FREE)
    pose = {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.0}
    ok, code, reason = server.ss.DryOracle(server.srv, "drawer_top").place([er], "eraser#1", pose)
    assert code != "SKILL_EXCEPTION", reason
    assert server.srv.robot.log == []


def _no_drag_baseline(server, monkeypatch):
    """누르기는 성공했는데 끌기 직전 힘 0점(_tare)도, 힘 맞추기 기준값(_held_f)도 없는 경우 [E #374 P1]."""
    real, real_tare = server.ss.SkillServer._press_relax, server.ss.SkillServer._tare
    pressed = {}

    def press_relax(self, *a, **k):
        r = real(self, *a, **k)
        self.__dict__.pop("_held_f", None)
        pressed["done"] = True
        return r
    monkeypatch.setattr(server.ss.SkillServer, "_press_relax", press_relax)
    monkeypatch.setattr(server.ss.SkillServer, "_tare", lambda self, *a, **k: None if pressed else real_tare(self, *a, **k))
    contact, line = _press_contact(server)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    return contact


def test_wall_nudge_without_force_baseline_lifts_without_drag(server, monkeypatch):
    """[E #374 P1] 기준값 없이 끌면 blocked() 가 movel 뒤에야 거부 → 끌기 명령 전에 SENSOR_INVALID, 그 자리에서 올리기만."""
    contact = _no_drag_baseline(server, monkeypatch)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_WALL_CROSS})
    stages = [s[0] for s in contact["stages"]]
    assert out.error_code == "SENSOR_INVALID" and "drag" not in stages and stages[-1] == "lift", (out, stages)
    assert data["pushed"] is False and data["target_after"] is None


def test_make_room_press_move_without_force_baseline_lifts_without_drag(server, monkeypatch):
    """[E #374 P1] make_room 넛지·밀기(_press_move) 도 같음 — 끌기·되돌아오기 명령 없이 올리고 SENSOR_INVALID."""
    t = _seg(ERASER_FREE)
    t["pose"]["yaw"] = 0.0
    ham = {"id": "toy_hammer#1", "class": "toy_hammer", "top_z": 0.025, "occluded_by": [],
           "pose": {"frame": "drawer_top", "position": [0.10, 0.15 + 0.011 + 0.0375 + 0.002, 0.0], "yaw": 0.0, "yaw_valid": True}}
    contact = _no_drag_baseline(server, monkeypatch)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": t, "make_room": True, "scan": _scan_with(t, ham)})
    stages = [s[0] for s in contact["stages"]]
    assert out.error_code == "SENSOR_INVALID" and not {"drag", "drag_back"} & set(stages) and stages[-1] == "lift", (out, stages)


def test_pick_does_not_close_when_tcp_reread_fails(server, monkeypatch):
    """[E #374 P1] 목표 위로 내려온 뒤 TCP 를 한 번 읽고 그다음부터 못 읽으면 예전 좌표로 대신하지 않음 — 닫지 않고 STATE_UNKNOWN(위치 모름, 잠금 — C #374 P3)."""
    srv = server.srv
    real_over = server.ss.SkillServer._over_then_down
    real_posx = srv.robot.posx
    state = {"after": False, "reads": 0}

    def over(self, *a, **k):
        r = real_over(self, *a, **k)
        state["after"] = True
        return r

    def posx():
        if state["after"]:
            state["reads"] += 1
            if state["reads"] > 1:
                return None
        return real_posx()
    monkeypatch.setattr(server.ss.SkillServer, "_over_then_down", over)
    srv.robot.posx = posx
    grips = []
    real_grip = srv._grip
    srv._grip = lambda w, f: (grips.append(w), real_grip(w, f))[1]
    out, _ = server.run("pick_object", {"target": json.loads(json.dumps(ERASER_FREE)), "approach_offset": [0, 0, 0.1]})
    assert state["after"] and out.error_code == "STATE_UNKNOWN", out
    assert grips and 0 not in grips[grips.index(max(grips)):]                 # 벌린 뒤 닫기(0) 없음
