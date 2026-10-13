"""b_demo·b_route(시연·점검 스크립트) 정지 확인 회귀 테스트 — ROS·로봇 없이 가짜 제어기·가짜 시계로. #83 E 검토 P1.

정지 명령 응답 없음/거절/정지 미확인이면 정상 접촉으로 반환하지 않고, b_demo 는 이후 이동·그리퍼 명령을 막는다.
감시 중 힘·좌표 조회가 끊기면 정지·확인 후 실패한다.
"""
import importlib
import importlib.util
import json
import math
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
    assert sk.goal_for("close") == ("drawer_control", {"drawer_id": "drawer_bottom", "state": "close", "then_home": True})
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


@pytest.mark.parametrize("codes, scans, want_calls, ok", [
    ({}, None,                                                          # 한 번에 성공: 탑뷰 → 인식 → 넛지 → 탑뷰 → 다시 인식 → 집기 → 놓기 → 홈
     ["view", "scan", "nudge", "view", "rescan", "pick", "place", "home"], True),
    ({"pick": ["WALL_TOO_CLOSE", "WALL_TOO_CLOSE", ""]}, None,          # 집기 전 "아직 못 잡음" → 다시 넛지, 잡을 때까지 [사용자 10/08]
     ["view", "scan", "nudge", "view", "rescan", "pick", "view", "scan", "nudge", "view", "rescan", "pick",
      "view", "scan", "nudge", "view", "rescan", "pick", "place", "home"], True),
    ({"pick": ["NOT_REACHED", ""]}, None,                               # 집기가 움직인 뒤 실패 → 다시 넛지 말고 다시 보고 집기
     ["view", "scan", "nudge", "view", "rescan", "pick", "view", "rescan", "pick", "place", "home"], True),
    ({"nudge": ["PUSH_BLOCKED", ""]}, None,                             # 넛지 실패 → 탑뷰 → 인식 → 다시 넛지
     ["view", "scan", "nudge", "view", "scan", "nudge", "view", "rescan", "pick", "place", "home"], True),
    ({"pick": ["ESTOP"]}, None, ["view", "scan", "nudge", "view", "rescan", "pick"], False),
    ({}, [True, False], ["view", "scan", "nudge", "view", "rescan"], False),   # 다시 인식에서 못 찾으면 멈춤
    ({"place": ["NOT_REACHED"]}, None, ["view", "scan", "nudge", "view", "rescan", "pick", "place"], False),
    ({"nudge": ["DRAWER_NOT_AT_TRAVEL"]}, None, ["view", "scan", "nudge"], False),   # 다시 봐도 안 풀림 → 반복 없이 멈춤 (#191 E 리뷰)
    ({"nudge": ["BAD_PARAMS"]}, None, ["view", "scan", "nudge"], False),
    ({"nudge": [""], "pick": ["DRAWER_NOT_CONFIGURED"]}, None, ["view", "scan", "nudge", "view", "rescan", "pick"], False),
    ({"nudge": [""], "pick": ["NOT_ON_FLOOR"]}, None, ["view", "scan", "nudge", "view", "rescan", "pick"], False),
])
def test_b_find_retries_until_grasped(monkeypatch, codes, scans, want_calls, ok):
    """[사용자 10/08] B find: 손으로 연 서랍에서 시작, 잡을 때까지 다시 넛지. 비상정지·잠김·못 찾음·놓기 실패만 멈춤."""
    sk = _load_sk(monkeypatch)
    calls, seq = [], {k: iter(v) for k, v in codes.items()}
    found = iter(scans) if scans else None

    def run(node, cmd):
        calls.append(cmd)
        sk.last["code"] = next(seq[cmd], "") if cmd in seq else ""
        return sk.last["code"] == ""

    def scan(node, for_pick=False):
        calls.append("rescan" if for_pick else "scan")
        return next(found) if found else True
    monkeypatch.setattr(sk, "run", run)
    monkeypatch.setattr(sk, "scan", scan)
    if ok:
        sk.find(None)
    else:
        with pytest.raises(SystemExit):
            sk.find(None)
    assert calls == want_calls
    assert sk.parse_drawer("find", "bottom") == "drawer_bottom"


def test_b_sk_sends_full_scan_for_neighbor_check_only_same_drawer(monkeypatch, tmp_path):
    """[사용자 10/09 랜덤 배치] 인식 결과 전체가 있으면 nudge·pick 에 scan 으로 붙임(옆 물체 확인). 다른 칸 결과는 안 붙임."""
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "TMP", str(tmp_path))
    monkeypatch.setattr(sk, "AFTER", str(tmp_path / "after.json"))
    cara = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.0185,
            "pose": {"frame": "drawer_top", "position": [0.1, 0.2, 0.0], "yaw": 0.0, "yaw_valid": True}}
    full = {"target_found": True, "target": TOP_T, "candidates": [cara], "visible_count": 2}
    (tmp_path / "b_target_scan_drawer_top.json").write_text(json.dumps(TOP_T))
    assert "scan" not in sk.goal_for("nudge")[1]                        # 전체 결과 없으면 예전과 같음
    (tmp_path / "b_target_fullscan_drawer_top.json").write_text(json.dumps(full))
    (tmp_path / "after.json").write_text(json.dumps(TOP_T))
    assert sk.goal_for("nudge")[1]["scan"] == full and sk.goal_for("pick")[1]["scan"] == full
    wrong = json.loads(json.dumps(full))
    wrong["candidates"][0]["pose"]["frame"] = "drawer_bottom"
    (tmp_path / "b_target_fullscan_drawer_top.json").write_text(json.dumps(wrong))
    assert "scan" not in sk.goal_for("pick")[1]


def test_b_sk_aside_places_held_object_in_drawer_slot_with_scan(monkeypatch, tmp_path):
    """[사용자 10/11] 캐러멜 위 지우개를 집어 aside 에 — B aside top = place_object(location 서랍, slot aside_1, 집을 때 본 scan).
    aside2 는 aside_2. 그 서랍 인식 결과가 없으면 보내지 않고 멈춤."""
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "TMP", str(tmp_path))
    with pytest.raises(SystemExit, match="B scan top"):
        sk.goal_for("aside")
    scan = {"target_found": True, "target": TOP_T, "candidates": [], "visible_count": 1}
    (tmp_path / "b_target_fullscan_drawer_top.json").write_text(json.dumps(scan))
    action, params = sk.goal_for("aside")
    assert action == "place_object" and params["location"] == "drawer_top" and params["slot"] == "aside_1" and params["scan"] == scan
    assert sk.goal_for("aside2")[1]["slot"] == "aside_2" and "aside" in sk.NEEDS_DRAWER


def test_b_sk_putback_returns_picked_object_to_its_pick_pose(monkeypatch, tmp_path):
    """[사용자 10/11] 파지만 시험: B pick → B putback = place_object(서랍, 집기 전 pose(yaw_valid 없음), 집을 때 본 scan).
    pick 뒤 다시 찍어 scan 이 바뀌어도 집을 때 scan 을 씀(쥔 물체가 scan 에 있어야 서랍 안 놓기가 받음). 집은 적 없으면 보내지 않음."""
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "TMP", str(tmp_path))
    monkeypatch.setattr(sk, "AFTER", str(tmp_path / "after.json"))
    with pytest.raises(SystemExit, match="B pick"):
        sk.goal_for("putback")
    scan = {"target_found": True, "target": TOP_T, "candidates": [], "visible_count": 1}
    (tmp_path / "b_target_fullscan_drawer_top.json").write_text(json.dumps(scan))
    (tmp_path / "b_target_scan_drawer_top.json").write_text(json.dumps(TOP_T))
    assert sk.goal_for("pick")[0] == "pick_object"
    (tmp_path / "b_target_fullscan_drawer_top.json").write_text(json.dumps(dict(scan, target=None, target_found=False)))   # 집은 뒤 다시 찍음
    action, params = sk.goal_for("putback")
    assert action == "place_object" and params["location"] == "drawer_top" and params["scan"] == scan
    assert params["pose"] == {k: TOP_T["pose"][k] for k in ("frame", "position", "yaw")} and "putback" not in sk.NEEDS_DRAWER


def test_b_sk_trayview_goes_to_taught_tray_view(monkeypatch):
    """[사용자 10/11] B trayview = 트레이 탑뷰(poses.yaml tray_view, 서랍 인자 없음)."""
    sk = _load_sk(monkeypatch)
    assert sk.goal_for("trayview") == ("move_to_named_pose", {"pose_name": "tray_view"}) and "trayview" not in sk.NEEDS_DRAWER


def test_b_sk_object_names_with_spaces_and_our_nicknames(monkeypatch, tmp_path):
    """[사용자 10/11] "장난감 스패너" 는 첫 단어(장난감)만 읽어 모르는 물체였음, "몽키스패너"·"가림막" 도 — 붙여서 찾고, 우리 부르는 이름도."""
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "TARGET_FILE", str(tmp_path / "t.txt"))
    for name, cls in (("장난감 스패너", "toy_wrench"), ("몽키스패너", "toy_wrench"), ("몽키", "toy_wrench"),
                      ("캐러멜 박스", "caramel_box"), ("가림막", "cover_plate"), ("차키", "car_key")):
        assert sk.parse_target(name) == cls, name


def test_b_sk_scan_prints_every_seen_object_with_relation(monkeypatch, capsys):
    """[사용자 10/11] B scan 은 보인 물체 전부를 한 줄씩 — 윗면 높이·yaw 믿음·위에 얹힌 물체(분할 모델)."""
    sk = _load_sk(monkeypatch)
    res = {"target": {"id": "car_key#1", "class": "car_key", "top_z": 0.0555, "occluded_by": [],
                      "pose": {"frame": "drawer_top", "position": [0.1119, 0.1961, 0.0], "yaw": 1.5679, "yaw_valid": True}},
           "candidates": [{"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.0546, "occluded_by": ["car_key#1"],
                           "pose": {"frame": "drawer_top", "position": [0.1397, 0.1741, 0.0], "yaw": -1.56, "yaw_valid": False}}]}
    sk.print_seen(res)
    out = capsys.readouterr().out
    assert "car_key#1" in out and "윗면 55.5 mm" in out and "caramel_box#1" in out and "위에 얹힘 ['car_key#1']" in out
    assert "(믿을 수 없음)" in out


@pytest.mark.parametrize("results, want_calls, ok", [
    ([("clear", "", {"action": "none", "ready_to_pick": True})],                       # 이미 잡을 수 있음 → 바로 집기
     ["view", "scan", "clear", "pick", "place", "home"], True),
    ([("clear", "", {"action": "unstack", "ready_to_pick": False}),                    # 위 물체 치우기 → 다시 보기 → 밀기 → 다시 보기 → 집기
      ("clear", "", {"action": "sweep", "ready_to_pick": False}),
      ("clear", "", {"action": "none", "ready_to_pick": True})],
     ["view", "scan", "clear", "view", "scan", "clear", "view", "scan", "clear", "pick", "place", "home"], True),
    ([("clear", "PUSH_BLOCKED", None), ("clear", "", {"action": "none", "ready_to_pick": True})],   # 밀다 걸림 → 다시 보고 다시
     ["view", "scan", "clear", "view", "scan", "clear", "pick", "place", "home"], True),
    ([("clear", "NO_FREE_SPACE", None)], ["view", "scan", "clear"], False),            # 빈 자리 없음 → 사람 할 일 출력하고 멈춤
    ([("clear", "", {"action": "none", "ready_to_pick": True}), ("pick", "NOT_REACHED", None),
      ("clear", "", {"action": "none", "ready_to_pick": True})],
     ["view", "scan", "clear", "pick", "view", "scan", "clear", "pick", "place", "home"], True),
])
def test_b_clear_makes_room_until_ready_then_picks(monkeypatch, results, want_calls, ok):
    """[사용자 10/11] B clear: 탑뷰 → 인식 → 공간 만들기 한 동작 → 다시 보기 … ready_to_pick 이면 집기 → 트레이 → 홈."""
    sk = _load_sk(monkeypatch)
    calls, queue = [], list(results)

    def run(node, cmd):
        calls.append(cmd)
        if queue and queue[0][0] == cmd:
            _, code, mr = queue.pop(0)
        else:
            code, mr = "", None
        sk.last["code"], sk.last["make_room"] = code, mr
        return code == ""

    def scan(node, for_pick=False):
        calls.append("scan")
        return True
    monkeypatch.setattr(sk, "run", run)
    monkeypatch.setattr(sk, "scan", scan)
    if ok:
        sk.clear(None)
    else:
        with pytest.raises(SystemExit):
            sk.clear(None)
    assert calls == want_calls and "clear" in sk.NEEDS_DRAWER


def test_b_sk_clear_goal_is_make_room_with_scan(monkeypatch, tmp_path):
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "TMP", str(tmp_path))
    (tmp_path / "b_target_scan_drawer_top.json").write_text(json.dumps(TOP_T))
    with pytest.raises(SystemExit, match="B scan top"):
        sk.goal_for("clear")
    full = {"target_found": True, "target": TOP_T, "candidates": [], "visible_count": 1}
    (tmp_path / "b_target_fullscan_drawer_top.json").write_text(json.dumps(full))
    action, params = sk.goal_for("clear")
    assert action == "nudge_object" and params["make_room"] is True and params["scan"] == full and params["target"] == TOP_T


def test_b_free_places_held_object_in_found_free_spot(monkeypatch, tmp_path):
    """[사용자 10/11] B free top: aside 고정 자리 대신 빈 자리 — 집을 때 본 scan 으로 후보를 골라 place_object(pose).
    움직이기 전 거부(PLACE_BLOCKED·WALL_TOO_CLOSE)면 다음 후보, 받침(캐러멜)과는 떨어진 곳, 다른 실패면 멈춤."""
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "TMP", str(tmp_path))
    monkeypatch.setattr(sk, "DRAWER", "drawer_top")
    with pytest.raises(SystemExit, match="B pick"):
        sk.free_poses("drawer_top")
    base = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.0185, "occluded_by": ["car_key#1"],
            "pose": {"frame": "drawer_top", "position": [0.1, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}
    key = {"id": "car_key#1", "class": "car_key", "top_z": 0.0343, "occluded_by": [],
           "pose": {"frame": "drawer_top", "position": [0.1, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}
    scan = {"target_found": True, "target": key, "candidates": [base], "visible_count": 2}
    (tmp_path / "b_picked.json").write_text(json.dumps({"target": key, "approach_offset": [0, 0, 0.1], "scan": scan}))
    cands, sc = sk.free_poses("drawer_top")
    assert cands and sc == scan
    for p in cands:                                                     # 받침(다음에 꺼낼 캐러멜)과 겹치지 않음
        assert abs(p["position"][0] - 0.1) > 0.05 or abs(p["position"][1] - 0.15) > 0.04
    sent = []

    def run(node, cmd, goal=None):
        sent.append(goal)
        sk.last["code"] = "PLACE_BLOCKED" if len(sent) < 3 else ""
        return sk.last["code"] == ""
    monkeypatch.setattr(sk, "run", run)
    assert sk.free(None) is True and len(sent) == 3
    assert all(g[0] == "place_object" and g[1]["location"] == "drawer_top" and g[1]["scan"] == scan for g in sent)
    assert sent[2][1]["pose"] == cands[2] and "free" in sk.NEEDS_DRAWER

    def run_moved(node, cmd, goal=None):
        sk.last["code"] = "NOT_REACHED"
        return False
    monkeypatch.setattr(sk, "run", run_moved)
    with pytest.raises(SystemExit, match="NOT_REACHED"):
        sk.free(None)


def test_b_free_uses_newer_rescan_adds_held_and_prefers_crosswise(monkeypatch, tmp_path):
    """[PC2 10/12] 집은 뒤 B view → B scan 으로 다시 봤으면 그 결과로 고름(예전 scan 의 옛 자리 물체에 막히지 않게).
    다시 본 결과엔 쥔 물체가 없으니 scan 에 넣어 보냄(서버 #166 요구). 가로(긴 변이 서랍 y) 후보 먼저 [사용자 10/12].
    서버가 기억하는 긴 변 쥠이면 90° 돌린 footprint 로 거름."""
    import os
    import time
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "TMP", str(tmp_path))
    monkeypatch.setattr(sk, "HELD_FILE", str(tmp_path / "held.json"))
    key = {"id": "car_key#1", "class": "car_key", "top_z": 0.0343, "occluded_by": [],
           "pose": {"frame": "drawer_top", "position": [0.1, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}
    stale = {"id": "car_key#2", "class": "car_key", "top_z": 0.0158, "occluded_by": [],
             "pose": {"frame": "drawer_top", "position": [0.05, 0.06, 0.0], "yaw": 0.0, "yaw_valid": True}}
    (tmp_path / "b_picked.json").write_text(json.dumps({"target": key, "scan": {"target": key, "candidates": [stale]}}))
    cara = {"id": "caramel_box#1", "class": "caramel_box", "top_z": 0.0185, "occluded_by": [],
            "pose": {"frame": "drawer_top", "position": [0.1, 0.15, 0.0], "yaw": 0.0, "yaw_valid": True}}
    fresh = {"target_found": True, "target": cara, "candidates": [], "visible_count": 1}
    f = tmp_path / "b_target_fullscan_drawer_top.json"
    f.write_text(json.dumps(fresh))
    later = time.time() + 5
    os.utime(f, (later, later))
    (tmp_path / "held.json").write_text(json.dumps({"id": "car_key#1", "class": "car_key", "width_m": 0.0701, "long_side": True}))
    cands, sc = sk.free_poses("drawer_top")
    ids = [o["id"] for o in [sc["target"]] + sc["candidates"]]
    assert ids == ["caramel_box#1", "car_key#1"]                      # 옛 scan 의 car_key#2 없음, 쥔 물체는 넣음
    assert cands and abs(math.sin(cands[0]["yaw"])) > 0.7                # 가로 먼저


def test_b_plan_is_make_room_check_only(monkeypatch, tmp_path):
    """[사용자 10/12] B plan top: 공간 만들기 다음 동작만 보기 — make_room + check_only (서버가 어떤 동작도 안 함)."""
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "TMP", str(tmp_path))
    (tmp_path / "b_target_scan_drawer_top.json").write_text(json.dumps(TOP_T))
    full = {"target_found": True, "target": TOP_T, "candidates": [], "visible_count": 1}
    (tmp_path / "b_target_fullscan_drawer_top.json").write_text(json.dumps(full))
    action, params = sk.goal_for("plan")
    assert action == "nudge_object" and params["make_room"] is True and params["check_only"] is True and "plan" in sk.NEEDS_DRAWER


def test_b_free_keeps_extra_wall_margin(monkeypatch, tmp_path):
    """[사용자 10/12 PC2] 아래 칸 립밤(긴 변 쥠 72.5 mm) B free 첫 후보 (20, 60) mm 90° 에서 손가락 바깥 관절이 왼벽에 닿음
    (표로는 4.3 mm 남음) → B free 후보만 place.free_wall_extra_mm 만큼 벽에서 더 띄움."""
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "TMP", str(tmp_path))
    monkeypatch.setattr(sk, "HELD_FILE", str(tmp_path / "held.json"))
    lip = {"id": "lip_balm#1", "class": "lip_balm", "top_z": 0.0227, "occluded_by": [],
           "pose": {"frame": "drawer_bottom", "position": [0.0097, 0.1539, 0.0], "yaw": 1.5625, "yaw_valid": True}}
    scan = {"target_found": True, "target": lip, "candidates": [], "visible_count": 1}
    (tmp_path / "b_picked.json").write_text(json.dumps({"target": lip, "scan": scan}))
    (tmp_path / "held.json").write_text(json.dumps({"id": "lip_balm#1", "class": "lip_balm", "width_m": 0.0725, "long_side": True}))
    cands, _ = sk.free_poses("drawer_bottom")
    assert cands
    cross = [p for p in cands if abs(math.sin(p["yaw"])) > 0.7]         # 립밤이 서랍 y 로 누움 = 손가락이 옆벽 쪽으로 벌어짐
    assert cross and cands[0] in cross
    for p in cross:
        assert p["position"][1] * 1000.0 >= 65.0                        # 닿은 (20, 60) 보다 y 0 벽에서 멀리


def _o(i, cls, x, y, under=(), yaw=0.0, frame="drawer_bottom"):
    return {"id": i, "class": cls, "top_z": 0.02, "occluded_by": list(under), "visible_area_m2": 0.002,
            "pose": {"frame": frame, "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True}}


def _scan(target, others):
    return {"target_found": target is not None, "target": target, "candidates": list(others), "visible_count": len(others) + (target is not None)}


def _unpack_run(monkeypatch, scans, codes=None):
    """B unpack 을 가짜 서버·가짜 인식으로: scans = inspect_all 이 차례로 돌려줄 결과, codes = {cmd: [실패 코드 …]}."""
    sk = _load_sk(monkeypatch)
    monkeypatch.setattr(sk, "DRAWER", scans[0]["candidates"][0]["pose"]["frame"])
    calls, sent, queue, codes = [], [], list(scans), {k: list(v) for k, v in (codes or {}).items()}

    def run(node, cmd, goal=None):
        calls.append(cmd)
        sent.append(goal)
        code = codes[cmd].pop(0) if codes.get(cmd) else ""
        sk.last["code"] = code
        out = None
        if goal and goal[0] == "place_object" and not code:
            p = goal[1]
            slots = {"aside_1": {"frame": sk.DRAWER, "position": [0.057, 0.067, 0.0], "yaw": 1.57},
                     "aside_2": {"frame": sk.DRAWER, "position": [0.12, 0.064, 0.0], "yaw": 0.0}}
            out = {"slot": p.get("slot"), "placed_pose": slots.get(p.get("slot")) or p.get("pose")}
        sk.last["out"] = out
        return code == ""

    def inspect_all(node, search):
        calls.append(f"inspect:{search}")
        sent.append(None)
        return queue.pop(0)
    monkeypatch.setattr(sk, "run", run)
    monkeypatch.setattr(sk, "inspect_all", inspect_all)
    return sk, calls, sent


def test_b_unpack_cover_moves_plate_delivers_and_restores(monkeypatch):
    """[사용자 10/12 "문서 그대로 풀로"] 가림막 밑 지우개 (C 진행표 S2): 판 → aside_1 → 지우개 트레이 → 판 원래 자리 → 복구 오차 → 닫기."""
    plate = _o("cover_plate#1", "cover_plate", 0.10, 0.18)
    er = _o("eraser#1", "eraser", 0.10, 0.18, under=["cover_plate#1"])
    lip = _o("lip_balm#1", "lip_balm", 0.15, 0.25)
    plate_aside = _o("cover_plate#1", "cover_plate", 0.057, 0.067, yaw=1.57)
    scans = [_scan(er, [plate, lip]),                                   # 처음: 지우개가 판 밑
             _scan(dict(er, occluded_by=[]), [plate_aside, lip]),        # 판 치운 뒤
             _scan(plate_aside, [lip]),                                  # 원위치 전 판 다시 찾기
             _scan(None, [plate, lip])]                                  # 마지막 확인
    sk, calls, sent = _unpack_run(monkeypatch, scans)
    sk.TARGET = "eraser"
    assert sk.unpack(None) is True
    assert calls == ["ready", "open", "inspect:eraser", "pick", "aside", "inspect:eraser", "pick", "place",
                     "inspect:cover_plate", "pick", "restore", "inspect:eraser", "close"]
    picks = [g[1]["target"]["id"] for c, g in zip(calls, sent) if c == "pick"]
    assert picks == ["cover_plate#1", "eraser#1", "cover_plate#1"]
    restore = sent[calls.index("restore")][1]
    assert restore["pose"] == {k: plate["pose"][k] for k in ("frame", "position", "yaw")} and restore["scan"] == scans[2]
    assert sent[calls.index("aside")][1]["slot"] == "aside_1" and "unpack" in sk.NEEDS_DRAWER


def test_b_unpack_stack_restores_in_reverse_and_leaves_blocked_one_aside(monkeypatch):
    """쌓기 (몽키 위 캐러멜 위 차키, C 진행표 S1): 차키 aside_1 → 캐러멜 aside_1 거부 → aside_2 → 몽키 트레이 →
    역순: 캐러멜 원래 자리, 차키는 원래 자리(캐러멜 위)가 거부되면 꺼냈던 aside_1 (A안: 빈 자리 + 안내)."""
    w = _o("toy_wrench#1", "toy_wrench", 0.10, 0.18, under=["caramel_box#1"], frame="drawer_top")
    c = _o("caramel_box#1", "caramel_box", 0.10, 0.18, under=["car_key#1"], frame="drawer_top")
    k = _o("car_key#1", "car_key", 0.10, 0.18, frame="drawer_top")
    k_a = _o("car_key#1", "car_key", 0.057, 0.067, yaw=1.57, frame="drawer_top")
    c_a = _o("caramel_box#1", "caramel_box", 0.12, 0.064, frame="drawer_top")
    scans = [_scan(w, [c, k]), _scan(w, [dict(c, occluded_by=[]), k_a]), _scan(dict(w, occluded_by=[]), [c_a, k_a]),
             _scan(c_a, [k_a]), _scan(k_a, [dict(c, occluded_by=[])]), _scan(None, [dict(c, occluded_by=[]), k_a])]
    sk, calls, sent = _unpack_run(monkeypatch, scans, codes={"aside": ["", "PLACE_BLOCKED", ""], "restore": ["", "PLACE_BLOCKED", ""]})
    sk.TARGET = "toy_wrench"
    assert sk.unpack(None) is True
    picks = [g[1]["target"]["id"] for cmd, g in zip(calls, sent) if cmd == "pick"]
    assert picks == ["car_key#1", "caramel_box#1", "toy_wrench#1", "caramel_box#1", "car_key#1"]
    asides = [g[1]["slot"] for cmd, g in zip(calls, sent) if cmd == "aside"]
    assert asides == ["aside_1", "aside_1", "aside_2"]
    restores = [g[1].get("pose", g[1].get("slot")) for cmd, g in zip(calls, sent) if cmd == "restore"]
    assert restores[0]["position"] == c["pose"]["position"] and restores[1]["position"] == k["pose"]["position"] and restores[2] == "aside_1"


def test_b_unpack_target_missing_still_restores(monkeypatch):
    """C 진행표 S3: 목표 없음 → 위에 아무것도 없는 것부터 최대 2개 치움 → 못 찾음 → 그래도 둘 다 원위치 → 닫기."""
    plate = _o("cover_plate#1", "cover_plate", 0.10, 0.18)
    lip = _o("lip_balm#1", "lip_balm", 0.15, 0.25)
    plate_a = _o("cover_plate#1", "cover_plate", 0.057, 0.067, yaw=1.57)
    lip_a = _o("lip_balm#1", "lip_balm", 0.12, 0.064)
    scans = [_scan(None, [plate, lip]), _scan(None, [plate_a, lip]), _scan(None, [plate_a, lip_a]),
             _scan(lip_a, [plate_a]), _scan(plate_a, [lip]), _scan(None, [plate, lip])]
    sk, calls, sent = _unpack_run(monkeypatch, scans, codes={"aside": ["", "PLACE_BLOCKED", ""]})
    sk.TARGET = "eraser"
    assert sk.unpack(None) is False
    assert "place" not in calls and calls[-1] == "close" and calls.count("restore") == 2


def test_b_unpack_follows_task_when_moved_object_still_listed_as_cover(monkeypatch):
    """[사용자 10/12 "unpack 은 스킬 짜깁기 — 태스크와 같게"] 차키 aside_1 뒤 캐러멜이 아직 '차키에 덮임'이면 Runner select_obstacle 은
    occluder_unavailable → 태스크처럼 더 치우지 않고(관계를 고치지도, 더 찍지도 않음) 목표 못 꺼냄 → 차키 원위치 → 닫기.
    (Runner 쪽 문제 — C 에 알림. B 명령이 더 잘해 주면 시연에서 다르게 나옴)"""
    w = _o("toy_wrench#1", "toy_wrench", 0.10, 0.18, under=["caramel_box#1"], frame="drawer_top")
    c = _o("caramel_box#1", "caramel_box", 0.10, 0.18, under=["car_key#1"], frame="drawer_top")
    k = _o("car_key#1", "car_key", 0.10, 0.18, frame="drawer_top")
    k_a = _o("car_key#1", "car_key", 0.057, 0.067, yaw=1.57, frame="drawer_top")
    scans = [_scan(w, [c, k]), _scan(w, [c, k_a]), _scan(k_a, [c]), _scan(None, [c, k_a])]
    sk, calls, sent = _unpack_run(monkeypatch, scans, codes={"restore": ["PLACE_BLOCKED", ""]})
    sk.TARGET = "toy_wrench"
    assert sk.unpack(None) is False
    picks = [g[1]["target"]["id"] for cmd, g in zip(calls, sent) if cmd == "pick"]
    assert picks == ["car_key#1", "car_key#1"] and calls.count("inspect:toy_wrench") == 3 and calls[-1] == "close"


def test_b_unpack_obstacle_pick_refused_goes_to_restore_like_task(monkeypatch):
    """태스크 s7.1 은 치울 물체를 pick_object 로만 — 움직이기 전 거부(WALL_TOO_CLOSE)면 넛지하지 않고 복구로 (B 명령도 같게).
    목표 집기는 공통 pick 스킬처럼 아직 못 잡는 자리면 넛지 → 다시 보기 → 다시 (retry 1)."""
    k = _o("car_key#1", "car_key", 0.10, 0.18, frame="drawer_top")
    w = _o("toy_wrench#1", "toy_wrench", 0.10, 0.18, under=["caramel_box#1"], frame="drawer_top")
    cs = _o("caramel_box#1", "caramel_box", 0.0605, 0.2139, under=["car_key#1"], frame="drawer_top")
    k_a = _o("car_key#1", "car_key", 0.057, 0.067, yaw=1.57, frame="drawer_top")
    scans = [_scan(w, [cs, k]), _scan(w, [dict(cs, occluded_by=[]), k_a]), _scan(k_a, [cs]), _scan(None, [cs, k_a])]
    sk, calls, sent = _unpack_run(monkeypatch, scans, codes={"pick": ["", "WALL_TOO_CLOSE"], "restore": ["PLACE_BLOCKED", ""]})
    sk.TARGET = "toy_wrench"
    assert sk.unpack(None) is False
    assert "nudge" not in calls and "place" not in calls and "restore" in calls and calls[-1] == "close"

    e = _o("eraser#1", "eraser", 0.02, 0.10)
    e2 = _o("eraser#1", "eraser", 0.03, 0.10)
    scans = [_scan(e, [_o("lip_balm#1", "lip_balm", 0.15, 0.25)]), _scan(e2, [])]
    sk, calls, sent = _unpack_run(monkeypatch, scans, codes={"pick": ["WALL_TOO_CLOSE"]})
    sk.TARGET = "eraser"
    assert sk.unpack(None) is True
    assert calls == ["ready", "open", "inspect:eraser", "pick", "nudge", "inspect:eraser", "pick", "place", "close"]

