from pathlib import Path

import pytest
import yaml

from ready2go_skills.core import skill_flow as sf

ROOT = Path(__file__).resolve().parents[4]
POSES = yaml.safe_load((ROOT / "config/poses.yaml").read_text(encoding="utf-8"))


# ---- poses.yaml 읽기
def test_home_and_drawer_poses_from_real_config():
    j, err = sf.pose_joints(POSES, "home")
    assert err is None and len(j) == 6
    j, err = sf.pose_joints(POSES, "drawer_approach", "drawer_top")
    assert err is None and len(j) == 6


SAMPLE = {"home": {"joints_deg": [0, 0, 90, 0, 90, 0]}, "tray_view": {"joints_deg": None},
          "drawer_approach": {"drawer_top": [1, 2, 3, 4, 5, 6]}, "drawer_top_view": {"drawer_top": None}}


@pytest.mark.parametrize("name,drawer,code", [
    ("nope", None, sf.UNKNOWN_POSE),
    ("drawer_approach", None, sf.UNKNOWN_POSE),            # 서랍 포즈인데 drawer_id 없음
    ("drawer_approach", "drawer_bottom", sf.UNKNOWN_POSE), # 그 서랍 값 없음
    ("tray_view", None, sf.POSE_NOT_TAUGHT),               # null = 교시 전
    ("drawer_top_view", "drawer_top", sf.POSE_NOT_TAUGHT),
])
def test_pose_errors(name, drawer, code):
    j, err = sf.pose_joints(SAMPLE, name, drawer)
    assert j is None and err.error_code == code


@pytest.mark.parametrize("bad", [[0, 0, 0], [0, 0, 0, 0, 0, float("nan")], [0, 0, 0, 0, 0, True], "x"])
def test_bad_joint_values(bad):
    j, err = sf.pose_joints({"p": {"joints_deg": bad}}, "p")
    assert j is None and err.error_code == sf.BAD_PARAMS


# ---- wait_motion: 가짜 시계·상태로
class Fake:
    def __init__(self, states, cancel_at=None, stop_ok=True, after_stop=(1,)):
        self.states, self.i, self.t, self.cancel_at, self.stopped = list(states), 0, 0.0, cancel_at, 0
        self.stop_ok, self.after_stop = stop_ok, list(after_stop)

    def state(self):
        s = self.states[min(self.i, len(self.states) - 1)]
        self.i += 1
        return s

    def clock(self):
        return self.t

    def sleep(self, dt):
        self.t += dt

    def cancel(self):
        return self.cancel_at is not None and self.t >= self.cancel_at

    def stop(self):
        self.stopped += 1
        self.states, self.i = self.after_stop, 0     # 정지 명령 뒤 읽히는 상태
        return self.stop_ok


def _wait(f, timeout=5.0):
    return sf.wait_motion(get_state=f.state, cancel_requested=f.cancel, stop=f.stop, timeout_s=timeout,
                          clock=f.clock, sleep=f.sleep)


def test_normal_motion_ends_when_not_moving():
    o = _wait(Fake([1, 2, 2, 2, 1]))
    assert o.success and o.error_code == ""


def test_not_done_before_motion_starts():
    f = Fake([1, 1, 2, 1])                   # 명령 직후 잠깐 대기 상태 → 끝난 것으로 보지 않음
    o = _wait(f)
    assert o.success and f.i == 4


def test_cancel_stops_and_reports_canceled_only_when_confirmed():
    f = Fake([2] * 1000, cancel_at=0.2)
    o = _wait(f)
    assert (o.success, o.error_code, o.canceled) == (False, sf.CANCELED, True) and f.stopped == 1


# 정지를 확인하지 못하면 canceled·MOTION_TIMEOUT 로 끝내지 않음 (#73 D 리뷰)
@pytest.mark.parametrize("stop_ok,after_stop", [
    (False, [1]),                 # 정지 명령 실패 (상태는 멈춘 것처럼 보여도 명령이 안 받아들여짐)
    (True, [None]),               # 정지 뒤 상태 조회 실패
    (True, [2]),                  # 정지 명령 뒤에도 계속 이동 중
    (True, [1, None, 1, None]),   # 연속 두 번 확인이 안 됨
])
def test_cancel_without_confirmed_stop_is_stop_unconfirmed(stop_ok, after_stop):
    f = Fake([2] * 1000, cancel_at=0.2, stop_ok=stop_ok, after_stop=after_stop)
    o = _wait(f)
    assert (o.success, o.error_code, o.canceled) == (False, sf.STOP_UNCONFIRMED, False)


def test_timeout_without_confirmed_stop_is_stop_unconfirmed():
    f = Fake([2] * 100000, stop_ok=True, after_stop=[2])
    assert _wait(f, timeout=1.0).error_code == sf.STOP_UNCONFIRMED


def test_state_none_during_motion_is_not_finished():
    f = Fake([2, 2, None, None, 2, 2, 1])     # 잠깐 조회 실패 → 끝난 것으로 보지 않고 계속 기다림
    o = _wait(f)
    assert o.success and f.i == 7


def test_state_none_too_long_stops_with_state_unknown():
    f = Fake([2, 2] + [None] * 100000)
    o = _wait(f)
    assert o.error_code == sf.STATE_UNKNOWN and f.stopped == 1


def test_state_none_too_long_and_stop_unconfirmed():
    f = Fake([2, 2] + [None] * 100000, after_stop=[None])
    assert _wait(f).error_code == sf.STOP_UNCONFIRMED


@pytest.mark.parametrize("estop_state", sorted(sf.ESTOP_STATES))
def test_estop_state_reports_estop(estop_state):
    o = _wait(Fake([2, 2, estop_state]))
    assert (o.success, o.error_code, o.canceled) == (False, sf.ESTOP, False)


def test_estop_while_confirming_stop_reports_estop():
    f = Fake([2] * 1000, cancel_at=0.2, after_stop=[6])
    assert _wait(f).error_code == sf.ESTOP


def test_timeout_stops():
    f = Fake([2] * 10000)
    o = _wait(f, timeout=1.0)
    assert o.error_code == sf.MOTION_TIMEOUT and f.stopped == 1


# ---- 도착 확인
def test_check_reached():
    t = [0, 0, 90, 0, 90, 0]
    assert sf.check_reached(t, [0.1, 0, 90, 0, 90.2, 0], 0.5).success
    assert sf.check_reached(t, [3, 0, 90, 0, 90, 0], 0.5).error_code == sf.NOT_REACHED
    assert sf.check_reached(t, None, 0.5).error_code == sf.NOT_REACHED
    assert sf.check_reached(t, [float("nan")] * 6, 0.5).error_code == sf.NOT_REACHED


# ---- 예외 경로도 정지를 확인 (#73 D 재검수)
def _boom():
    raise RuntimeError("동작 중 예외")


def _guarded(f):
    return sf.run_guarded(_boom, stop=f.stop, get_state=f.state, clock=f.clock, sleep=f.sleep)


def test_handler_result_passes_through():
    f = Fake([1])
    ok = (sf.Outcome(True, reason="끝"), {"x": 1})
    assert sf.run_guarded(lambda: ok, stop=f.stop, get_state=f.state, clock=f.clock, sleep=f.sleep) == ok
    assert f.stopped == 0


def test_exception_with_confirmed_stop_is_skill_exception():
    f = Fake([2], after_stop=[1])
    o, out = _guarded(f)
    assert (o.success, o.error_code, out) == (False, sf.SKILL_EXCEPTION, None) and f.stopped == 1


@pytest.mark.parametrize("stop_ok,after_stop", [(True, [2]), (True, [None]), (False, [1])])
def test_exception_without_confirmed_stop_is_stop_unconfirmed(stop_ok, after_stop):
    o, _ = _guarded(Fake([2], stop_ok=stop_ok, after_stop=after_stop))
    assert o.error_code == sf.STOP_UNCONFIRMED


def test_exception_during_estop_reports_estop():
    o, _ = _guarded(Fake([2], after_stop=[6]))
    assert o.error_code == sf.ESTOP


# ---- 이동 명령 응답: 수락 / 거부 / 응답 없음 (#73 E 리뷰)
def _after(accepted, f):
    return sf.after_command(accepted, what="movej", stop=f.stop, get_state=f.state, clock=f.clock, sleep=f.sleep)


def test_accepted_command_proceeds():
    f = Fake([1])
    assert _after(True, f) is None and f.stopped == 0


@pytest.mark.parametrize("after_stop,code", [([1], sf.MOVE_UNCONFIRMED), ([2], sf.STOP_UNCONFIRMED), ([None], sf.STOP_UNCONFIRMED)])
def test_no_response_stops_and_locks(after_stop, code):
    f = Fake([2], after_stop=after_stop)          # 응답은 없었지만 실제로는 이동 중
    o = _after(None, f)
    assert o.error_code == code and f.stopped == 1
    assert o.error_code in sf.LOCKING_CODES


def test_explicit_reject_idle_is_move_rejected_without_stop():
    f = Fake([1])
    o = _after(False, f)
    assert o.error_code == sf.MOVE_REJECTED and f.stopped == 0


@pytest.mark.parametrize("state", [2, None])
def test_explicit_reject_but_moving_or_unknown_stops_first(state):
    f = Fake([state], after_stop=[1])
    o = _after(False, f)
    assert o.error_code == sf.MOVE_REJECTED and f.stopped == 1


def test_explicit_reject_in_estop():
    assert _after(False, Fake([6])).error_code == sf.ESTOP


# ---- 한 번에 한 동작 (#73 E 리뷰)
def test_motion_gate_allows_one_at_a_time():
    g = sf.MotionGate()
    assert not g.busy() and g.try_enter()
    assert g.busy() and not g.try_enter()      # 두 번째 요청은 바로 거절
    g.exit()
    assert not g.busy() and g.try_enter()


def test_motion_gate_threads():
    import threading
    g, entered, start = sf.MotionGate(), [], threading.Barrier(8)

    def worker():
        start.wait()
        if g.try_enter():
            entered.append(1)
    ts = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(entered) == 1


# ---- 도착 확인: 개수·NaN (#73 E 리뷰)
@pytest.mark.parametrize("actual", [[0, 0, 0, 0, 0], [0, float("nan"), 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0],
                                    [0, 0, 0, 0, 0, True]])
def test_check_reached_rejects_bad_joint_lists(actual):
    assert sf.check_reached([0] * 6, actual, 0.5).error_code == sf.NOT_REACHED
