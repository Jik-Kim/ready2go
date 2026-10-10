"""skill_server 노드 동작 경로 회귀 테스트 (ROS·로봇 없이 가짜 로봇으로). #83 D·E 리뷰.

ROS 패키지가 없으면(CI의 코어 단계) 필요한 모듈만 이 테스트 안에서 가짜로 넣었다가 끝나면 되돌린다.
"""
import importlib
import json
import math
import sys
import types
from pathlib import Path

import pytest
import yaml

from ready2go_skills.core import skill_flow as sf
from ready2go_skills.core.rg2_protocol import Rg2Status

REPO = Path(__file__).resolve().parents[4]
# 옆벽(y_max)에 붙은 지우개: 10/07 실측 0.2904 = 그때 폭 0.2937 − 3.3 mm. 서랍 좌표계를 다시 재면 폭이 바뀌므로 저장소 places.yaml 폭 기준으로 둔다 (10/10 다시 교시)
WALL_Y = round(yaml.safe_load((REPO / "config" / "places.yaml").read_text(encoding="utf-8"))["drawer_top"]["interior_m"][1] - 0.0033, 4)
ERASER_CORNER = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
                 "pose": {"frame": "drawer_top", "position": [0.0275, WALL_Y, 0.0], "yaw": 0.0, "yaw_valid": True}}   # 10/07 실측 (벽에서 3.3 mm)
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
        "MoveBlending MoveJoint MoveLine MoveSplineJoint MoveStop SetRobotMode").split()})
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
    srv.get_logger = lambda: types.SimpleNamespace(info=lambda *a: None, warn=lambda *a: None, error=lambda *a: None)
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)

    def run(action, params):
        return sf.run_guarded(lambda: getattr(srv, f"_do_{action}")(goal, json.loads(json.dumps(params))),
                              stop=srv.robot.stop, get_state=srv.state)
    return types.SimpleNamespace(ss=ss, srv=srv, run=run, Gripper=Gripper)


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
        out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER})
    finally:
        server.ss.SkillServer._line = real_line
    assert out.success and data["pushed"] is True
    assert data["target_after"]["pose"]["position"][1] == pytest.approx(WALL_Y - 0.040, abs=1e-3)   # 누른 z 그대로 40 mm 만 (10/07 저녁 33 → 40) → 옆벽 보정(7.1 mm)으로 바로 집힘
    start, end = contact["drag"]
    assert end[2] == pytest.approx(start[2], abs=0.06)                   # 수평으로만 끔 (z 섞이면 더 눌려 15 N 초과, 10/06 저녁). 0.1 mm 올리기 도착 판정 0.05 mm
    assert contact["z"] - 2.5 / 8.0 <= start[2] <= contact["z"] - 1.0 / 8.0   # 5 N 에서 멈춰 확인 → 0.1 mm 씩 올려 1.5~2.5 N 근처에서 끔 [사용자 10/07]
    assert "N 으로 눌러" in out.reason
    server.srv.robot.force = lambda p: [0.0] * 6
    server.Gripper.holding = True
    route = server.srv.poses()["carry_line"]["drawer_top"]
    server.srv.robot.log.clear()
    out, data = server.run("pick_object", {"target": data["target_after"], "approach_offset": [0, 0, 0.1]})
    server.Gripper.holding = False
    assert out.success and data["grasp_ok"] is True
    kind, pts, radii = server.srv.robot.log[-1]                         # 집고 수직으로 테두리 위 → 경유점 1(서랍 중앙)로 수평, 블렌딩 한 번 [사용자 10/08]
    top = server.srv.places()["drawer_top"]
    travel = 1000.0 * (top["tf"]["translation_m"][2] + top["interior_m"][2]) + server.srv.prm()["transit"]["in_drawer_clear_mm"]
    assert kind == "moveb" and pts[-1] == route[0] and pts[0][2] == pytest.approx(max(travel, route[0][2]))
    assert travel - 0.5 <= route[0][2] <= travel + 5.0                  # 경유점 1 = 테두리 위 조금 (z 300 안 올림) — 교시값이 테두리 + 5 mm 보다 조금 높을 수 있음 [실측 10/10 +6.6 mm]
    server.srv.robot.log.clear()
    out, data = server.run("place_object", {"location": "handover_zone"})
    log = server.srv.robot.log
    assert out.success and data["slot"] == "handover_zone_1"
    kind, pts, radii = log[0]                                           # 2·3·4 → 칸 위(4번 높이), 직선 블렌딩 한 번
    assert kind == "moveb" and pts[:3] == route[1:] and len(pts) == 4
    seq = [route[0]] + pts                                              # 반지름 100 mm [사용자 10/08], 구간이 짧으면 앞뒤 구간 절반의 90% — 절반 그대로면 제어기 거부 [실측 PC2 10/08]
    half = [min(math.dist(seq[k][:3], seq[k + 1][:3]), math.dist(seq[k + 1][:3], seq[k + 2][:3])) / 2.0 for k in range(3)]
    assert radii == pytest.approx([min(100.0, 0.9 * h) for h in half] + [0.0]) and radii[0] < 100.0   # 1→2 짧은 구간은 절반의 90%
    assert pts[3][2] == pytest.approx(route[-1][2])
    assert log[1][0] == "movel" and log[1][1][:2] == pytest.approx(pts[3][:2]) and log[1][1][2] < pts[3][2]   # 살포시 내려놓기
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
    server.run("drawer_control", {"drawer_id": "drawer_top", "state": "open"})
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
    server.srv._tare = lambda: [0.0] * 6
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
    assert out.error_code == server.ss.PUSH_BLOCKED and "20.0 N > 2.5 N" in out.reason
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
    forces = iter([[0, 0, 4.0, 0, 0, 0], [0, 0, 4.0, 0, 0, 0], [0, 0, 2.0, 0, 0, 0]])
    srv._force_still = lambda s: next(forces)
    steps = []

    def step(goal, posx, stage):
        steps.append(round(posx[2], 2))
        return sf.Outcome(False, sf.NOT_REACHED, reason=f"[{stage}] 멈춤") if len(steps) == 1 else None
    srv._step = step
    pressed = [522.3, -135.6, 216.5, 0.4, 160.0, 0.0]
    bad, p, n = srv._relax(types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None),
                           pressed, [0.0] * 6, d)
    assert bad is None and n == 2.0 and len(warns) == 1
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
    forces = iter([[0, 0, 4.0, 0, 0, 0], [0, 0, 2.0, 0, 0, 0]])     # 첫 칸 뒤 힘이 범위 안 (실물: 멈춘 사이 힘이 풀림)
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
    blend = moves[i + 1]
    assert blend[0] == "moveb" and len(blend[1]) == 2                   # y 맞추기 → 목표 위, 한 번에
    assert blend[1][0][1] == pytest.approx(blend[1][1][1])              # 첫 점 = 목표 y
    assert blend[1][1][2] < 300.0                                       # safe_z(300) 로 올리지 않음


HAMMER = {"id": "toy_hammer#1", "class": "toy_hammer", "top_z": 0.025,
          "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}


@pytest.mark.parametrize("width, ok", [(12.4, True), (9.6, False), (21.0, False)])
def test_hammer_grasp_judged_by_handle_width_not_bbox(server, width, ok):
    """#43: 망치 외접박스 짧은 변은 75 mm(머리)라 손잡이(12.5 mm)를 잡으면 WIDTH_MISMATCH 였음 → pick.grasp_width_m 으로 판정.
    벌림은 짧은 변 기준 그대로 (75 + 13 mm). 10 mm 이하는 성공 아님 [사용자 결정 10/08]."""
    server.Gripper.holding, server.Gripper.held_width = True, width
    try:
        srv = server.srv
        real_grip, grips = srv._grip, []
        srv._grip = lambda w, f: grips.append(w) or real_grip(w, f)
        out, res = server.run("pick_object", {"target": json.loads(json.dumps(HAMMER)), "approach_offset": [0, 0, 0.1]})
    finally:
        server.Gripper.holding, server.Gripper.held_width = False, 21.0
    assert out.success is ok and res["grasp_ok"] is ok
    assert 88.0 in [round(w, 1) for w in grips]                         # 벌림 = 75 + 13 mm
    if not ok:
        assert out.error_code == server.ss.GRASP_FAILED and "기대 12.5 mm" in out.reason


def test_pick_floor_10mm_even_if_bbox_short_side_matches(server):
    """[사용자 결정 10/08, #43] 집기 성공 하한 10 mm — 빈손·놓침 2 mm 와 별개 값."""
    g = server.srv.prm()["gripper"]
    assert g["pick_min_width_m"] == pytest.approx(0.010) and g["min_width_m"] == pytest.approx(0.002)


def test_bad_grasp_width_refused_before_motion(server, monkeypatch):
    """짧은 변(75 mm)보다 큰 잡는 폭은 설정 오류 — 움직이기 전에 거부."""
    srv, real = server.srv, server.srv.prm

    def prm():
        p = real()
        p["pick"]["grasp_width_m"] = {"toy_hammer": 0.2}
        return p
    monkeypatch.setattr(srv, "prm", prm)
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
        z_floor, floor_held = dict(seen)["descend"], dict(srv.held)
        seen[:], srv.held = [], None                                    # 놓았다고 치고 다시 집기
        out, data = server.run("pick_object", {"target": _stacked_eraser(0.0115 + 0.0435), "approach_offset": [0, 0, 0.1]})
    finally:
        server.Gripper.holding = False
    assert floor.success and out.success and "받침 43.5 mm" in out.reason and data["grasp_ok"]
    assert dict(seen)["descend"] - z_floor == pytest.approx(43.5, abs=0.05)
    assert srv.held["tcp_above_floor_m"] == pytest.approx(floor_held["tcp_above_floor_m"], abs=1e-4)   # 서랍 tf 기울기만큼


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
    """[사용자 10/09 랜덤 배치] 캐러멜이 지우개 옆 6 cm(중심) — 벌린 손가락 자리와 겹침 → 움직이기 전 NEIGHBOR_TOO_CLOSE."""
    t = json.loads(json.dumps(ERASER_FREE))
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1], "scan": _scan_with(t, CARAMEL_NEXT)})
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
    t["pose"]["position"][1] = WALL_Y - 0.033
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
    sp = server.srv.prm()["speed"]                                      # 서랍 안 내려가기는 in_drawer_mm_s [사용자 10/07 밤], 트레이는 line_mm_s
    assert st["descend_fast"][0] == sp["in_drawer_mm_s"] and st["descend"][0] == 15.0 and st["descend_fast"][1] - st["descend"][1] == pytest.approx(10.0)
    assert out2.success and st["lower_fast"][0] == 150.0 and st["lower"][0] == 15.0
    assert st["lower_fast"][1] - st["lower"][1] == pytest.approx(10.0)


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
    출발조차 안 한 블렌딩은 멈춘 걸 확인하고 한 번만 다시 보냄. 두 번째도 안 가면 NOT_REACHED."""
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
    out = server.srv._blend(goal, pts, [20.0, 0.0], 150.0, "to_object:over")
    assert out.error_code == sf.NOT_REACHED and len(calls) == 2


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
    assert ("retreat", prm["drawer_open_close"]["home_blend_mm"]) in radii       # 빼기 끝에서 멈추지 않음
    log = [e for e in srv.robot.log if e != "stop"]
    assert log[-1] == ("movej", srv.poses()["home"]["joints_deg"])


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


def test_vertical_close_cancel_after_home_sends_no_grip(server):
    """#181 E 리뷰: 수직 닫기도 같음 — 서랍 위에서 홈 이동 뒤 취소면 그리퍼·밀기 명령 없이 CANCELED."""
    srv = server.srv
    prm = srv.prm()
    prm["drawer_open_close"]["close_push"] = {"drawer_top": None, "drawer_bottom": None}   # 위 칸 = 수직 방식
    srv.prm = lambda: prm
    srv.robot.p = [424.181, -294.601, 363.507, 0.0, 180.0, 0.0]        # 탑뷰 (서랍 위) → 홈부터
    server.Gripper.width = 0.9                                          # 닫힌 채 → 원래라면 벌리는 명령을 보냄
    grips = _cancel_after_home(server)
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_top", "state": "close"})
    assert not out.success and out.error_code == sf.CANCELED
    log = [e for e in srv.robot.log if e != "stop"]
    home = ("movej", srv.poses()["home"]["joints_deg"])
    assert log[-1] == home and grips == []


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
    """#181 E 재리뷰 P1: 닫기(위 = 수직, 아래 = 45°)에서 홈 이동 직후 안전정지(5)·비상정지(6)·안전정지2(9)·상태 조회 실패면
    그리퍼·다음 이동 명령 0건 — ESTOP / STATE_UNKNOWN."""
    srv = server.srv
    prm = srv.prm()
    start = [21.9, 39.2, 115.7, 110.1, -99.3, -23.6]
    end = [381.9, -283.0, 100.0, 90.0, -135.0, 90.0]
    prm["drawer_open_close"]["close_push"] = {"drawer_top": None, "drawer_bottom": {"start_posj": start, "start_posx": [381.9, -27.0, 100.0, 90.0, -135.0, 90.0], "end_posx": end}}
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
    out, _ = server.run("move_to_named_pose", {"pose_name": "home"})
    assert out.success and speeds[-1] == (srv.joint_vel, srv.joint_acc)


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
    assert all(e[0] in ("movel", "moveb") for e in log[1:])
    lines = [p for e in log[1:] for p in ([e[1]] if e[0] == "movel" else e[1])]   # 블렌딩 경유점까지 펼침
    prev = list(waypoint)
    for p in lines:
        assert math.dist(prev[:2], p[:2]) < 0.01 or min(prev[2], p[2]) >= travel_z - 0.01, (prev, p)
        prev = p
    pos_m, _ = plp.place_tcp_m(place["tf"], ASIDE_POSE, 0.02 + pl["drop_m"])
    low = min(lines, key=lambda p: p[2])
    assert low[:3] == pytest.approx([1000.0 * v for v in pos_m], abs=1e-6)   # 쥔 높이 + drop 에서 놓음
    tz = max(travel_z, waypoint[2])                                     # 경유점이 travel_z 보다 높으면 그 높이로 옆 이동 (_travel_z)
    assert lines[0][2] == pytest.approx(tz, abs=1e-6) and lines[-1] == pytest.approx(mp.with_z(waypoint, tz), abs=1e-6)   # 먼저 수직으로, 끝은 경유점 위


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
