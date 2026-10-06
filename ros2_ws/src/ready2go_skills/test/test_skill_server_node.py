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
                 "pose": {"frame": "drawer_top", "position": [0.1735, 0.2827, 0.0], "yaw": 0.0, "yaw_valid": True}}
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
        "MoveJoint MoveLine MoveStop SetRobotMode").split()})
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

        def movel_async(self, p, vel, acc, rot_vel=30.0, rot_acc=60.0):
            self.log.append(("movel", p))
            s0 = list(self.p)
            self.path = [[s0[i] + (p[i] - s0[i]) * (k + 1) / 5 for i in range(6)] for k in range(5)]
            return True

        def movej_async(self, j, vel, acc):
            self.log.append(("movej", j))
            self.j = list(j)
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
        return [0.0, 0.0, 3.0 if contact_z is not None and p[2] <= contact_z else 0.0, 0.0, 0.0, 0.0]
    server.srv.robot.force = force
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None):
        nonlocal contact_z
        if stage == "press":
            contact_z = (self.robot.p[2] + posx[2]) / 2          # 내려가는 중간에서 접촉
        if stage == "lift":
            return sf.Outcome(False, sf.STOP_UNCONFIRMED, reason="주입")
        return real_line(self, goal, posx, vel, stage, watch)
    monkeypatch.setattr(server.ss.SkillServer, "_line", line)
    out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER})
    assert out.error_code == sf.STOP_UNCONFIRMED and data["target_after"] is None


def test_drag_success_gives_target_after_and_pick_accepts_list_approach_offset(server):
    contact = {}

    def force(p):
        return [0.0, 0.0, 3.0 if contact.get("z") is not None and p[2] <= contact["z"] else 0.0, 0.0, 0.0, 0.0]
    server.srv.robot.force = force
    real_line = server.ss.SkillServer._line

    def line(self, goal, posx, vel, stage, watch=None):
        if stage == "press":
            contact["z"] = (self.robot.p[2] + posx[2]) / 2
        return real_line(self, goal, posx, vel, stage, watch)
    server.ss.SkillServer._line = line
    try:
        out, data = server.run("nudge_object", {"drawer_id": "drawer_top", "target": ERASER_CORNER})
    finally:
        server.ss.SkillServer._line = real_line
    assert out.success and data["pushed"] is True
    assert data["target_after"]["pose"]["position"][1] == pytest.approx(0.2827 - 0.0349, abs=1e-3)
    server.srv.robot.force = lambda p: [0.0] * 6
    server.Gripper.holding = True
    out, data = server.run("pick_object", {"target": data["target_after"], "approach_offset": [0, 0, 0.1]})
    server.Gripper.holding = False
    assert out.success and data["grasp_ok"] is True


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


@pytest.mark.parametrize("y", [0.2925, 0.2895, 0.2827])
def test_pick_next_to_side_wall_refused_without_motion(server, y):
    """#83 A 요청(#80 D P1 후속): 끌기 없이 벽에 붙은 지우개를 바로 집으면 움직이기 전에 WALL_TOO_CLOSE."""
    t = json.loads(json.dumps(ERASER_CORNER))
    t["pose"]["position"] = [0.1769, y, 0.0]
    out, _ = server.run("pick_object", {"target": t, "approach_offset": [0, 0, 0.1]})
    assert not out.success and out.error_code == server.ss.WALL_TOO_CLOSE
    assert server.srv.robot.log == []
