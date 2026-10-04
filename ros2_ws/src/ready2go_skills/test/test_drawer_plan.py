import math
from pathlib import Path

import pytest
import yaml

from ready2go_skills.core import drawer_plan as dp

ROOT = Path(__file__).resolve().parents[4]
PLACES = yaml.safe_load((ROOT / "config/places.yaml").read_text(encoding="utf-8"))
P = yaml.safe_load((ROOT / "ros2_ws/src/ready2go_skills/params/skills.yaml").read_text(encoding="utf-8"))["drawer_control"]
TOP = PLACES["drawer_top"]

# [실측 B 10/04, poses.yaml drawer_approach 주석] 손잡이 파지 TCP (mm): 닫힘 → 최대 인출
HANDLE_CLOSED = (382.695, -292.476, 268.505)
HANDLE_OPEN = (382.918, -66.2, 268.44)


def test_pull_direction_matches_measured_opening():
    d = dp.pull_direction(TOP["tf"]["quaternion_xyzw"])
    assert math.isclose(math.hypot(*d), 1.0) and d[2] == 0.0
    measured = dp._unit([o - c for o, c in zip(HANDLE_OPEN, HANDLE_CLOSED)])
    angle = math.degrees(math.acos(sum(a * b for a, b in zip(d, measured))))
    assert angle < 1.0                                   # 3점 터치 tf 방향 = 로봇으로 끌어 연 방향 (≈ base +y)


def test_displacement_from_measured_pull_is_max_travel():
    d = dp.pull_direction(TOP["tf"]["quaternion_xyzw"])
    moved = dp.displacement_m([v / 1000 for v in HANDLE_CLOSED], [v / 1000 for v in HANDLE_OPEN], d)
    assert moved == pytest.approx(TOP["max_travel_m"], abs=0.002)


def test_resist_force_uses_direction():
    d = (0.0, 1.0, 0.0)
    assert dp.resist_force_n([0, -20, 0], d) == pytest.approx(20)      # 당기는 쪽 반대로 막음
    assert dp.resist_force_n([20, 0, 0], d) == pytest.approx(0)        # 옆으로 걸린 힘은 저항이 아님
    assert dp.resist_force_n([0, -20, 0], d, force_sign=-1) == pytest.approx(-20)


@pytest.mark.parametrize("dist,ok", [(0.10, True), (0.226, True), (0.0, False), (0.25, False)])
def test_open_distance_limits(dist, ok):
    v = dp.check_open_distance(dist, TOP["max_travel_m"])
    assert (v is None) == ok
    if not ok:
        assert v.error_code == dp.BAD_DISTANCE


def test_judge_opening():
    t, tol, stuck = TOP["max_travel_m"], P["pos_tol_m"], P["stuck_force_n"]
    assert dp.judge_opening(0.10, t, 5.0, stuck, tol) == dp.Verdict(False, None, "인출 중")
    assert dp.judge_opening(t, t, 5.0, stuck, tol).done and dp.judge_opening(t, t, 5.0, stuck, tol).error_code is None
    jam = dp.judge_opening(0.08, t, stuck + 1, stuck, tol)
    assert jam.done and jam.error_code == dp.DRAWER_STUCK


def test_judge_closing_needs_both_position_and_force():
    f, tol = P["close_force_n"], P["pos_tol_m"]
    assert dp.judge_closing(0.0005, f + 1, f, tol).error_code is None and dp.judge_closing(0.0005, f + 1, f, tol).done
    assert not dp.judge_closing(0.0005, 1.0, f, tol).done             # 위치만 도달: 아직 (힘 확인 전)
    early = dp.judge_closing(0.04, f + 1, f, tol)                      # 4 cm 전에 막힘: 튀어나온 물품
    assert early.done and early.error_code == dp.CLOSE_NOT_CONFIRMED
    assert not dp.judge_closing(0.04, 2.0, f, tol).done


NAN, INF = float("nan"), float("inf")


@pytest.mark.parametrize("moved,resist", [(NAN, 5.0), (0.1, NAN), (0.1, INF), (INF, 5.0)])
def test_opening_stops_on_non_finite(moved, resist):
    v = dp.judge_opening(moved, TOP["max_travel_m"], resist, P["stuck_force_n"], P["pos_tol_m"])
    assert v.done and v.error_code == dp.SENSOR_INVALID


@pytest.mark.parametrize("remaining,resist", [(NAN, 5.0), (0.0, NAN), (-INF, 20.0)])
def test_closing_stops_on_non_finite(remaining, resist):
    v = dp.judge_closing(remaining, resist, P["close_force_n"], P["pos_tol_m"])
    assert v.done and v.error_code == dp.SENSOR_INVALID


@pytest.mark.parametrize("dist", [NAN, INF, True])
def test_open_distance_non_finite(dist):
    assert dp.check_open_distance(dist, TOP["max_travel_m"]).error_code == dp.BAD_DISTANCE
