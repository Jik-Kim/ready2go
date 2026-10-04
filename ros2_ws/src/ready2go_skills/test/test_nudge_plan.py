import math

import pytest

from ready2go_skills.core import nudge_plan as np_

# 새 서랍 내부 [실측 A 10/03, places.yaml interior_m] 깊이 0.205 × 폭 0.295
INTERIOR = (0.205, 0.295)
# 손가락 치수는 실측 전 시험용 값 [추정]. 집을 때는 물체보다 한쪽 20 mm 넓게 벌린다고 가정 —
# 열린 손가락에 필요한 틈(10+20+3)이 닫은 손가락으로 밀 때 필요한 틈(15+3)보다 커야 밀기가 의미 있다.
GEO = np_.GripperGeometry(
    finger_thickness_m=0.010, finger_width_m=0.020, grasp_clearance_m=0.020,
    max_open_width_m=0.100, closed_thickness_m=0.015, wall_margin_m=0.003, push_margin_m=0.005,
)
ERASER = (0.0525, 0.022)          # #8 실측 22 × 52.5 mm, 로컬 x = 긴 변


def _plan(x, y, yaw=0.0, size=ERASER, yaw_valid=True, **kw):
    return np_.plan_nudge(center_xy=(x, y), yaw=yaw, yaw_valid=yaw_valid, size_xy=size,
                          interior_xy=INTERIOR, geo=GEO, **kw)


def test_center_is_graspable_without_push():
    p = _plan(0.10, 0.15)
    assert (p.pushed, p.error_code) == (False, None)
    assert p.push_vector_m == (0.0, 0.0)
    assert p.grasp_yaw is not None


def test_near_wall_but_other_axis_free_is_not_pushed():
    # y=0 벽 가까이: 짧은 변(22 mm)을 잡으면 손가락이 y로 벌어져 벽에 걸리지만,
    # 긴 변(52.5 + 40 ≤ 100 mm)을 잡으면 손가락이 x로 벌어져 여유 있음 → 밀지 않음
    p = _plan(0.10, 0.030)
    assert p.pushed is False and p.error_code is None
    assert p.grasp_yaw == pytest.approx(0.0)


CORNER = (0.050, 0.030)   # x=0·y=0 벽 모서리 근처: 긴 변은 x 벽에, 짧은 변은 y 벽에 걸림


def test_corner_object_is_pushed_away_from_wall():
    p = _plan(*CORNER)
    assert p.pushed is True and p.error_code is None
    dx, dy = p.push_vector_m
    assert (dx > 0 and dy == 0) or (dy > 0 and dx == 0)     # 벽에서 멀어지는 방향, 축 하나
    assert max(dx, dy) < 0.02                               # 필요한 만큼만 (약 14 mm)
    moved = _plan(CORNER[0] + dx, CORNER[1] + dy)
    assert moved.pushed is False and moved.error_code is None  # 민 뒤에는 잡힘
    assert moved.grasp_yaw == pytest.approx(p.grasp_yaw)


def test_push_start_is_between_wall_and_object():
    p = _plan(*CORNER)
    sx, sy = p.push_start_m
    assert 0 < sx < INTERIOR[0] and 0 < sy < INTERIOR[1]
    assert p.finger_travel_m >= abs(p.push_vector_m[0]) + abs(p.push_vector_m[1])


def test_touching_corner_is_no_push_access():
    p = _plan(0.0265, 0.0115)          # 두 벽에 거의 붙음: 닫은 손가락이 들어갈 틈이 없음
    assert (p.pushed, p.error_code) == (False, np_.NO_PUSH_ACCESS)
    assert "틈" in p.reason


def test_touching_wall_on_all_push_sides_is_no_push_access():
    # 크기가 서랍 폭에 가까운 물체를 x=0 벽에 붙임: 벽 쪽 틈 0, 반대쪽으로 밀 공간 없음
    big = (0.180, 0.022)
    p = _plan(0.090 + 0.0005, 0.011, size=big)
    assert (p.pushed, p.error_code) == (False, np_.NO_PUSH_ACCESS)


def test_check_only_reports_push_limit_without_moving():
    p = _plan(*CORNER, check_only=True)
    assert (p.pushed, p.error_code) == (False, np_.PUSH_LIMIT)
    assert p.push_vector_m == (0.0, 0.0)
    ok = _plan(0.10, 0.15, check_only=True)
    assert (ok.pushed, ok.error_code) == (False, None)


def test_too_wide_object_has_no_grasp_option():
    wide = (0.120, 0.110)               # 어느 쪽도 최대 벌림 100 mm를 넘음
    p = _plan(0.10, 0.15, size=wide)
    assert p.error_code == np_.NO_PUSH_ACCESS


def test_clearance_before_is_min_gap():
    p = _plan(0.10, 0.030, yaw=0.0)     # y 쪽 빈틈 = 0.030 − 0.011
    assert p.clearance_before_m == pytest.approx(0.019)


def test_center_outside_interior_raises():
    with pytest.raises(ValueError):
        _plan(0.30, 0.10)


# yaw_valid 차단 (#15 PM 요청, PR #65 선행). D 재현 사례: 차키 69.5 × 39 mm, 중심 (0.035, 0.040),
# yaw_valid false라 yaw 0이 자리표시인데 그대로 쓰면 밀기 계획(약 17.5 mm)이 나온다.
CAR_KEY = (0.0695, 0.039)
KEY_AT = (0.035, 0.040)


def test_d_case_would_push_if_yaw_trusted():
    p = _plan(*KEY_AT, size=CAR_KEY)
    assert p.pushed is True and p.error_code is None     # 차단이 없으면 이 계획으로 움직임


@pytest.mark.parametrize("yaw_valid", [False, None])     # false, 필드 없음
@pytest.mark.parametrize("check_only", [False, True])
def test_untrusted_yaw_returns_yaw_invalid_without_moving(yaw_valid, check_only):
    p = _plan(*KEY_AT, size=CAR_KEY, yaw_valid=yaw_valid, check_only=check_only)
    assert (p.pushed, p.error_code) == (False, np_.YAW_INVALID)
    assert p.push_vector_m == (0.0, 0.0) and p.push_start_m is None and p.finger_travel_m == 0.0


def test_yaw_valid_must_be_true_not_truthy():
    p = _plan(0.10, 0.15, yaw_valid=1)
    assert p.error_code == np_.YAW_INVALID


def test_valid_zero_yaw_and_symmetric_object_proceed():
    assert _plan(0.10, 0.15, yaw=0.0, yaw_valid=True).error_code is None
    tape = (0.0385, 0.0385)                              # masking_tape: 대칭, 비전이 yaw 0 + yaw_valid true
    p = _plan(0.10, 0.15, size=tape, yaw=0.0, yaw_valid=True)
    assert (p.pushed, p.error_code) == (False, None)
