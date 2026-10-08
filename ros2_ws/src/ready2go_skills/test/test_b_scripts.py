"""b_demo·b_route(시연·점검 스크립트) 정지 확인 회귀 테스트 — ROS·로봇 없이 가짜 제어기·가짜 시계로. #83 E 검토 P1.

정지 명령 응답 없음/거절/정지 미확인이면 정상 접촉으로 반환하지 않고, b_demo 는 이후 이동·그리퍼 명령을 막는다.
감시 중 힘·좌표 조회가 끊기면 정지·확인 후 실패한다.
"""
import importlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ns = types.SimpleNamespace


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


def _load(monkeypatch, name):
    _stub(monkeypatch, "rclpy")
    _stub(monkeypatch, "rclpy.signals", SignalHandlerOptions=ns(NO=0))
    _stub(monkeypatch, "std_msgs")
    _stub(monkeypatch, "std_msgs.msg", Float64MultiArray=object)
    _stub(monkeypatch, "dsr_msgs2")
    _stub(monkeypatch, "dsr_msgs2.srv", **{n: object for n in (
        "GetCurrentPosj GetCurrentPosx GetCurrentTcp GetCurrentTool GetToolForce "
        "MoveBlending MoveJoint MoveLine MoveSplineJoint MoveStop SetRobotMode").split()})
    _stub(monkeypatch, "pymodbus")
    _stub(monkeypatch, "pymodbus.client", ModbusTcpClient=object)
    spec = importlib.util.spec_from_file_location(f"_test_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += s


class Ctl:
    """가짜 제어기: 비동기 직선 이동은 z 로만 일정 속도. stop = ok | ignored(수락하고 확인 시간 넘게 계속 움직임) | none | rejected."""

    def __init__(self, clock, stop="ok", contact_z=None):
        self.c, self.stop, self.contact_z = clock, stop, contact_z
        self.z, self.target, self.log = 200.0, None, []
        self.force_ok_calls = None               # 이 횟수 뒤부터 힘 조회 실패
        self.move_resp = ns(success=True)

    def z_now(self):
        if self.target is None:
            return self.z
        z = self.z0 - self.v * (self.c.t - self.t0)
        if z <= self.target:
            self.z, self.target = self.target, None
            return self.z
        return z

    def call(self, name, kw):
        self.log.append(name.split("/")[-1])
        if name.endswith("move_line"):
            self.z = self.z_now()
            self.z0, self.t0, self.target, self.v = self.z, self.c.t, kw["pos"][2], kw["vel"][0]
            return self.move_resp
        if name.endswith("move_stop"):
            if self.stop == "ok":
                self.z, self.target = self.z_now(), None
            elif self.stop == "ignored" and self.target is not None:   # 수락했지만 멈추지 않고 계속 내려감
                self.z0, self.t0, self.target = self.z_now(), self.c.t, -1000.0
            return {"ok": ns(success=True), "ignored": ns(success=True), "none": None,
                    "rejected": ns(success=False)}[self.stop]
        if name.endswith("get_current_posx"):
            return ns(task_pos_info=[ns(data=[400.0, 0.0, self.z_now(), 0.0, 180.0, 0.0])])
        if name.endswith("get_tool_force"):
            if self.force_ok_calls is not None:
                if self.force_ok_calls <= 0:
                    return None
                self.force_ok_calls -= 1
            hit = self.contact_z is not None and self.z_now() <= self.contact_z
            return ns(tool_force=[0.0, 0.0, 3.0 if hit else 0.0, 0.0, 0.0, 0.0])
        raise AssertionError(name)


# ---------------- b_demo ----------------

@pytest.fixture
def demo(monkeypatch):
    mod = _load(monkeypatch, "b_demo")
    clock = Clock()
    monkeypatch.setattr(mod, "time", clock)
    grips = []

    class Rg2:
        def __init__(self, ip):
            pass

        def move(self, w, f):
            grips.append((w, f))
            return ns(width_mm=w)

        def close(self):
            pass
    monkeypatch.setattr(mod, "Rg2", Rg2)

    def make(**kw):
        ctl = Ctl(clock, **kw)
        r = object.__new__(mod.Robot)
        r.call = lambda typ, name, timeout=5.0, req=None, **k: ctl.call(name, k)
        return r, ctl
    return ns(mod=mod, make=make, grips=grips)


def _press(demo, r):
    """b_demo 누르기처럼: 9 mm 아래 목표, 3 mm 내려가면 접촉으로 봄."""
    z0 = r.posx()[2]
    return r.movel_watch([400.0, 0.0, z0 - 9.0, 0.0, 180.0, 0.0], 5.0,
                         lambda p, d: "접촉" if p[2] <= z0 - 3.0 else None, 10)


def _assert_locked(demo, r, ctl):
    sent = len(ctl.log)
    for fn in (lambda: r.movel([400.0, 0.0, 250.0, 0.0, 180.0, 0.0]), lambda: r.movej([0.0, 0.0, 90.0, 0.0, 90.0, 0.0]),
               lambda: r.movel_watch([400.0, 0.0, 150.0, 0.0, 180.0, 0.0], 5.0, lambda p, d: None, 10),
               lambda: r.grip(30.0, 20.0)):
        with pytest.raises(demo.mod.Stop, match="잠김"):
            fn()
    assert ctl.log[sent:] == [] and demo.grips == []


def test_demo_contact_with_confirmed_stop_returns_hit(demo):
    r, ctl = demo.make()
    assert _press(demo, r) == "접촉"
    assert "move_stop" in ctl.log and not r.locked
    assert ctl.z == pytest.approx(197.0, abs=0.2)


@pytest.mark.parametrize("stop", ["none", "rejected", "ignored"])
def test_demo_contact_without_confirmed_stop_raises_and_locks(demo, stop):
    r, ctl = demo.make(stop=stop)
    with pytest.raises(demo.mod.Stop):
        _press(demo, r)
    assert "move_stop" in ctl.log and r.locked
    _assert_locked(demo, r, ctl)


def test_demo_force_query_failure_while_moving_stops_and_confirms(demo):
    r, ctl = demo.make()
    ctl.force_ok_calls = 11                      # tare 10 번 + 감시 1 번 뒤 끊김
    with pytest.raises(demo.mod.Stop, match="힘 조회 실패 — 정지 확인"):
        _press(demo, r)
    assert ctl.log.count("move_stop") == 1 and ctl.target is None and ctl.z > 191.0


def test_demo_force_query_failure_with_unconfirmed_stop_locks(demo):
    r, ctl = demo.make(stop="ignored")
    ctl.force_ok_calls = 11
    with pytest.raises(demo.mod.Stop):
        _press(demo, r)
    assert r.locked
    _assert_locked(demo, r, ctl)


@pytest.mark.parametrize("resp", [None, ns(success=False)])
def test_demo_async_move_not_accepted_stops_and_fails(demo, resp):
    r, ctl = demo.make()
    ctl.move_resp = resp
    with pytest.raises(demo.mod.Stop, match="시작 실패"):
        _press(demo, r)
    assert ctl.log[-1] != "move_line" and "move_stop" in ctl.log


# ---------------- b_route press ----------------

@pytest.fixture
def route(monkeypatch):
    mod = _load(monkeypatch, "b_route")
    clock = Clock()
    monkeypatch.setattr(mod, "time", clock)

    def make(**kw):
        ctl = Ctl(clock, **kw)
        r = object.__new__(mod.Robot)
        r.call = lambda typ, name, timeout=5.0, **k: ctl.call(name, k)
        return r, ctl
    return make


def test_route_press_contact_with_confirmed_stop(route):
    r, ctl = route(contact_z=197.0)
    out = r.press(9.0, 2.0, 5.0)
    assert out.startswith("접촉") and "정지 확인" in out and ctl.target is None


@pytest.mark.parametrize("stop", ["none", "rejected", "ignored"])
def test_route_press_contact_without_confirmed_stop_fails(route, stop):
    r, ctl = route(contact_z=197.0, stop=stop)
    out = r.press(9.0, 2.0, 5.0)
    assert out.startswith("실패") and "move_stop" in ctl.log


def test_route_press_force_lost_while_moving_stops_instead_of_no_contact(route):
    """E 재현: 처음 힘 정상 → 다음 힘 None → 예전엔 정지 없이 '9 mm 내려가도 2 N 안 됨'."""
    r, ctl = route()
    ctl.force_ok_calls = 1
    out = r.press(9.0, 2.0, 5.0)
    assert out.startswith("실패") and "조회 실패" in out and "정지 확인" in out
    assert ctl.log.count("move_stop") == 1 and ctl.z > 199.0


@pytest.mark.parametrize("resp", [None, ns(success=False)])
def test_route_press_move_not_accepted_fails(route, resp):
    r, ctl = route()
    ctl.move_resp = resp
    out = r.press(9.0, 2.0, 5.0)
    assert out.startswith("실패") and "시작 실패" in out and "move_stop" in ctl.log


def _load_sk(monkeypatch):
    _stub(monkeypatch, "rclpy")
    _stub(monkeypatch, "rclpy.action", ActionClient=object)
    _stub(monkeypatch, "rclpy.signals", SignalHandlerOptions=ns(NO=0))
    _stub(monkeypatch, "ready2go_interfaces")
    _stub(monkeypatch, "ready2go_interfaces.action", Skill=object)
    spec = importlib.util.spec_from_file_location("b_sk", SCRIPTS / "b_sk.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("codes, want_calls, ok", [
    ({"nudge": ["NO_OBJECT_CONTACT", ""]},                             # 끌기 성공 뒤엔 늘 탑뷰 → 다시 인식 → 집기 [사용자 10/07]
     ["home", "ready", "open", "view", "scan", "nudge", "view", "scan", "nudge", "view", "scan", "pick", "place"], True),
    ({"nudge": [""], "pick": ["GRASP_FAILED", ""]},                    # 집기 실패 → 탑뷰 → 집기부터 (다시 끌지 않음)
     ["home", "ready", "open", "view", "scan", "nudge", "view", "scan", "pick", "view", "scan", "pick", "place"], True),
    ({"nudge": ["NOT_REACHED", "JOINT_LIMIT", "PUSH_BLOCKED"]},         # 무엇이든 다시, 최대 2번
     ["home", "ready", "open", "view", "scan", "nudge", "view", "scan", "nudge", "view", "scan", "nudge"], False),
    ({"nudge": ["ESTOP"]}, ["home", "ready", "open", "view", "scan", "nudge"], False),
    ({"nudge": ["STOP_UNCONFIRMED"]}, ["home", "ready", "open", "view", "scan", "nudge"], False),
])
def test_dragtest_goes_back_to_top_view_on_any_failure(monkeypatch, codes, want_calls, ok):
    """끌기·집기에서 무엇이든 이상하면 탑뷰 → 인식 → 다시 [사용자 10/07]. 비상정지·잠김·취소만 멈춤."""
    sk = _load_sk(monkeypatch)
    calls, seq = [], {k: iter(v) for k, v in codes.items()}

    def run(node, cmd):
        calls.append(cmd)
        sk.last["code"] = next(seq[cmd]) if cmd in seq else ""
        return sk.last["code"] == ""
    monkeypatch.setattr(sk, "run", run)
    monkeypatch.setattr(sk, "scan", lambda node, for_pick=False: calls.append("scan") or True)
    if ok:
        sk.drag_test(None)
    else:
        with pytest.raises(SystemExit):
            sk.drag_test(None)
    assert calls == want_calls


def test_report_sums_pick_window_from_first_view_to_last_pick(monkeypatch, capsys):
    """구간별 시간표 (C 요청 10/07): pick 구간 = 첫 탑뷰 ~ 마지막 집기 (열기·놓기는 빼고)."""
    sk = _load_sk(monkeypatch)
    clock = Clock()
    monkeypatch.setattr(sk, "time", clock)
    for label, sec in [("open", 9.0), ("view", 3.0), ("scan", 1.0), ("nudge", 20.0), ("view", 3.0),
                       ("rescan", 1.0), ("pick", 12.0), ("place", 8.0)]:
        sk.timed(label, lambda sec=sec: clock.sleep(sec) or True)
    sk.report()
    out = capsys.readouterr().out
    assert "pick 구간 합계 (첫 탑뷰 ~ 집기): 40.0 s" in out and "전체 합계: 57.0 s" in out


def test_b_sk_drawer_argument_and_ready(monkeypatch):
    """[사용자 10/08] B <동작> [drawer_top|drawer_bottom] — 팀 공통 서랍 이름 그대로, 기본 위 칸. ready = 손잡이 앞(열기 노드 시작 자세)."""
    sk = _load_sk(monkeypatch)
    assert sk.goal_for("ready") == ("move_to_named_pose", {"pose_name": "drawer_approach", "drawer_id": "drawer_top"})
    monkeypatch.setattr(sk, "DRAWER", "drawer_bottom")
    assert sk.goal_for("open") == ("drawer_control", {"drawer_id": "drawer_bottom", "state": "open"})
    assert sk.goal_for("close") == ("drawer_control", {"drawer_id": "drawer_bottom", "state": "close"})
    assert sk.goal_for("view") == ("move_to_named_pose", {"pose_name": "drawer_top_view", "drawer_id": "drawer_bottom"})
    assert sk.STEPS[:2] == ("ready", "open") and sk.DRAG_TEST[:3] == ("home", "ready", "open")



def test_b_sk_drawer_required_with_short_names(monkeypatch):
    """[사용자 10/08] 서랍이 필요한 동작은 서랍 필수, top/bottom 짧은 이름도 받음. 빼먹거나 서랍 없는 동작에 주면 움직이기 전에 멈춤."""
    sk = _load_sk(monkeypatch)
    assert sk.parse_drawer("open", "top") == "drawer_top" and sk.parse_drawer("open", "bottom") == "drawer_bottom"
    assert sk.parse_drawer("view", "drawer_bottom") == "drawer_bottom"
    assert sk.parse_drawer("home", None) == "drawer_top"
    assert sk.parse_drawer("rescan", "top") == "drawer_top"                    # 끌기 뒤 다시 인식도 서랍 필수 (#181 E 재리뷰)
    for cmd, arg in (("open", None), ("close", "middle"), ("all", None), ("home", "top"), ("place", "bottom"), ("rescan", None)):
        with pytest.raises(SystemExit):
            sk.parse_drawer(cmd, arg)


TOP_T = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
         "pose": {"frame": "drawer_top", "position": [0.12, 0.2, 0.0], "yaw": 0.0, "yaw_valid": True}}


def _no_vision(monkeypatch):
    _stub(monkeypatch, "ready2go_interfaces.srv", InspectRegion=object)
    return ns(create_client=lambda *a: ns(wait_for_service=lambda timeout_sec: False))


def test_b_sk_scan_file_per_drawer(monkeypatch):
    """#181 E 리뷰: 인식 결과 파일은 서랍마다 따로."""
    sk = _load_sk(monkeypatch)
    top = sk.scan_file()
    monkeypatch.setattr(sk, "DRAWER", "drawer_bottom")
    assert top != sk.scan_file() and "drawer_bottom" in sk.scan_file()


def test_b_sk_scan_without_vision_ignores_other_drawer_target(monkeypatch, tmp_path):
    """#181 E 리뷰: 위 칸 인식 결과가 남아 있어도 비전 없이 B scan bottom 은 실패 (예전엔 위 칸 좌표로 성공 → nudge 칸 불일치)."""
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "TMP", str(tmp_path))
    node = _no_vision(monkeypatch)
    (tmp_path / "b_target_scan_drawer_top.json").write_text(json.dumps(TOP_T))
    assert sk.scan(node) is True                                        # 위 칸은 저장된 결과 사용
    monkeypatch.setattr(sk, "DRAWER", "drawer_bottom")
    assert sk.scan(node) is False
    (tmp_path / "b_target_scan_drawer_bottom.json").write_text(json.dumps(TOP_T))   # 아래 칸 파일에 위 칸 frame 이 들어 있어도
    assert sk.scan(node) is False


def test_b_sk_target_never_sends_other_drawer_target(monkeypatch, tmp_path):
    """#181 E 리뷰: nudge 의 target 은 frame 이 지금 서랍인 것만 — 아래 칸에 위 칸 좌표·고정값(stub)을 보내지 않고 멈춤."""
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "TMP", str(tmp_path))
    (tmp_path / "b_target_scan_drawer_top.json").write_text(json.dumps(TOP_T))
    assert sk.goal_for("nudge")[1]["target"] == TOP_T
    monkeypatch.setattr(sk, "DRAWER", "drawer_bottom")
    with pytest.raises(SystemExit, match="B scan bottom"):
        sk.goal_for("nudge")
    (tmp_path / "b_target_scan_drawer_bottom.json").write_text(json.dumps(TOP_T))
    with pytest.raises(SystemExit):
        sk.goal_for("nudge")
    bottom = json.loads(json.dumps(TOP_T))
    bottom["pose"]["frame"] = "drawer_bottom"
    (tmp_path / "b_target_scan_drawer_bottom.json").write_text(json.dumps(bottom))
    assert sk.goal_for("nudge") == ("nudge_object", {"drawer_id": "drawer_bottom", "target": bottom})


def test_b_sk_rescan_without_vision_needs_same_drawer_after(monkeypatch, tmp_path):
    """#181 E 리뷰: 비전 없이 다시 보기(for_pick)는 지금 서랍 끌기 결과(target_after)가 있을 때만 그대로 집기."""
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "AFTER", str(tmp_path / "after.json"))
    node = _no_vision(monkeypatch)
    (tmp_path / "after.json").write_text(json.dumps(TOP_T))
    assert sk.scan(node, for_pick=True) is True
    monkeypatch.setattr(sk, "DRAWER", "drawer_bottom")
    assert sk.scan(node, for_pick=True) is False
