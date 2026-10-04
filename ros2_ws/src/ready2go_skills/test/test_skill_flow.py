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
    def __init__(self, states, cancel_at=None):
        self.states, self.i, self.t, self.cancel_at, self.stopped = list(states), 0, 0.0, cancel_at, 0

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
        self.states = [1]                    # 정지 명령 후 대기 상태
        self.i = 0


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


def test_cancel_stops_and_reports_canceled():
    f = Fake([2] * 1000, cancel_at=0.2)
    o = _wait(f)
    assert (o.success, o.error_code, o.canceled) == (False, sf.CANCELED, True) and f.stopped == 1


@pytest.mark.parametrize("estop_state", sorted(sf.ESTOP_STATES))
def test_estop_state_reports_estop(estop_state):
    o = _wait(Fake([2, 2, estop_state]))
    assert (o.success, o.error_code, o.canceled) == (False, sf.ESTOP, False)


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
