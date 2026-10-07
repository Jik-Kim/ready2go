"""skill_server 노드 동작 경로 회귀 테스트 (ROS·로봇 없이 가짜 로봇으로). #83 D·E 리뷰.

ROS 패키지가 없으면(CI의 코어 단계) 필요한 모듈만 이 테스트 안에서 가짜로 넣었다가 끝나면 되돌린다.
"""
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

from ready2go_skills.core import skill_flow as sf
from ready2go_skills.core.rg2_protocol import Rg2Status

REPO = Path(__file__).resolve().parents[4]
ERASER_CORNER = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
                 "pose": {"frame": "drawer_top", "position": [0.0275, 0.2904, 0.0], "yaw": 0.0, "yaw_valid": True}}   # 10/07 실측
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
        width, holding = 99.0, False

        def __init__(self, ip):
            pass

        def move(self, w, f):
            Gripper.width = (21.0 if Gripper.holding else 0.9) if w == 0 else w
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
    assert data["target_after"]["pose"]["position"][1] == pytest.approx(0.2904 - 0.033, abs=1e-3)   # 누른 z 그대로 33 mm 만 → 옆벽 보정(7.1 mm)으로 바로 집힘 [사용자 10/07 안 가]
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
    assert server.srv.robot.log[-1] == ("movel", route[0])               # 집고 바로 경유점 1(서랍 중앙)로 — z 300 안 올림 (10/06 저녁)
    server.srv.robot.log.clear()
    out, data = server.run("place_object", {"location": "handover_zone"})
    log = server.srv.robot.log
    assert out.success and data["slot"] == "handover_zone_1"
    kind, pts, radii = log[0]                                           # 2·3·4 → 칸 위(4번 높이), 직선 블렌딩 한 번
    assert kind == "moveb" and pts[:3] == route[1:] and len(pts) == 4
    assert radii[1:] == [50.0, 50.0, 0.0] and radii[0] == pytest.approx(41.7, abs=0.1)   # 50 mm [사용자 10/07], 짧은 구간(1→2 83 mm)은 절반
    assert pts[3][2] == pytest.approx(route[-1][2])
    assert log[1][0] == "movel" and log[1][1][:2] == pytest.approx(pts[3][:2]) and log[1][1][2] < pts[3][2]   # 살포시 내려놓기
    assert log[2][0] == "movel"                                         # 놓은 뒤 위로
    log.clear()
    out, _ = server.run("drawer_control", {"drawer_id": "drawer_top", "state": "close"})
    assert log[0][0] == "movel" and log[0][1][1] == pytest.approx(-291.757 + 226.0 + 11.1 + 30.0, abs=1.0)   # 홈 안 거치고 손잡이 앞으로 바로
    assert not any(e[0] == "movej" for e in log)
    closed_y = -291.757 + 11.1 - 2.0                                    # 닫힘 TCP [실측 10/06 저녁] + 2 mm 더
    assert log[1][1][1] == pytest.approx(closed_y + 30.0, abs=0.5)      # 빠르게 → 마지막 30 mm 는 천천히 (두 번)
    assert log[2][1][1] == pytest.approx(closed_y, abs=0.5)


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
    assert log and log[0][0] == "movel" and log[0][1][1] == pytest.approx(-289.757, abs=0.5)   # 손잡이까지 한 번에 (1 cm 전 멈춤 없음, 10/07)
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
    relax = [e for e in server.srv.robot.log if e[0] == "movel"][-3:-1]   # 0.1 mm 씩 두 번 올리고 → 위로 빠짐
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


def test_side_wall_offset_lets_33mm_drag_be_picked_but_not_30mm(server):
    """10/07: 오른쪽 옆벽은 서랍 경계보다 7.1 mm 바깥 [실측] → 33 mm 끈 지우개는 집기 통과, 30 mm 는 거부 (움직이지 않음)."""
    t = json.loads(json.dumps(ERASER_CORNER))
    t["pose"]["position"][1] = 0.2904 - 0.030
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
    assert out.error_code == server.ss.WALL_TOO_CLOSE and server.srv.robot.log == []


def test_lift_then_joint_move_without_stop_and_fallback_when_rejected(server):
    """10/07 사용자 "z 올리고 탑뷰 가기 전 멈춤 없이": 올리기는 radius 20 으로 보내고 끝 20 mm 안에서 관절 이동.
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
    assert out.success and seen == [20.0] and r.log[-1] == ("movej", view)
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
    t["pose"]["position"][1] = 0.2904 - 0.033
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
    assert st["descend_fast"][0] == 150.0 and st["descend"][0] == 15.0 and st["descend_fast"][1] - st["descend"][1] == pytest.approx(10.0)
    assert out2.success and st["lower_fast"][0] == 150.0 and st["lower"][0] == 15.0
    assert st["lower_fast"][1] - st["lower"][1] == pytest.approx(10.0)
