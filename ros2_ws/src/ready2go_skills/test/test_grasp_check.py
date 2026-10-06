import pytest

from ready2go_skills.core import grasp_check as gc
from ready2go_skills.core import rg2_protocol as proto


def _from_registers(width_raw, status_raw):
    """RG2 레지스터 → /gripper/state 본문 → 판정 입력 (실제 데이터 경로와 같게)."""
    payload = proto.gripper_state_payload(proto.decode_status(width_raw, status_raw))
    return payload["width"], payload["grasp_detected"]


def test_empty_close_is_not_a_grasp():
    # [실측 10/03] 빈 상태로 닫으면 0.9 mm + grip_detected=True
    width, detected = _from_registers(9, proto.STATUS_GRIP_DETECTED)
    r = gc.check_grasp(width_m=width, grasp_detected=detected, min_width_m=0.005)
    assert (r.ok, r.reason) == (False, gc.EMPTY_CLOSE)


def test_object_held():
    width, detected = _from_registers(221, proto.STATUS_GRIP_DETECTED)   # 지우개 22.1 mm
    r = gc.check_grasp(width_m=width, grasp_detected=detected, min_width_m=0.005)
    assert (r.ok, r.reason) == (True, gc.OK)
    assert r.width_m == pytest.approx(0.0221)


def test_not_detected():
    r = gc.check_grasp(width_m=0.0999, grasp_detected=False, min_width_m=0.005)
    assert (r.ok, r.reason) == (False, gc.NOT_DETECTED)


def test_width_equal_to_min_fails():
    r = gc.check_grasp(width_m=0.005, grasp_detected=True, min_width_m=0.005)
    assert r.reason == gc.EMPTY_CLOSE


@pytest.mark.parametrize("width, ok", [(0.022, True), (0.0249, True), (0.0255, False), (0.039, False)])
def test_expected_width(width, ok):
    r = gc.check_grasp(width_m=width, grasp_detected=True, min_width_m=0.005,
                       expected_width_m=0.022, width_tolerance_m=0.003)
    assert r.ok is ok
    assert r.reason == (gc.OK if ok else gc.WIDTH_MISMATCH)


def test_bad_parameters():
    with pytest.raises(ValueError):
        gc.check_grasp(width_m=0.02, grasp_detected=True, min_width_m=0)
    with pytest.raises(ValueError):
        gc.check_grasp(width_m=0.02, grasp_detected=True, min_width_m=0.005, expected_width_m=0.02)


@pytest.mark.parametrize("width, held, reason", [
    (0.0214, True, gc.HELD),          # 지우개 좁은 쪽 21.4 mm 그대로 [실측 B 10/04]
    (0.0200, True, gc.HELD),          # 고무가 조금 더 눌림 (허용 범위 안)
    (0.0150, True, gc.SLIPPED),       # 손가락 안에서 돌아감
    (0.0009, False, gc.DROPPED),      # 빈손 닫힘 0.9 mm까지 줄어듦 [실측 B 10/03]
    (0.0050, False, gc.DROPPED),      # 최소 폭과 같으면 놓친 것으로 본다
])
def test_check_hold(width, held, reason):
    r = gc.check_hold(width_m=width, width_at_grasp_m=0.0214, min_width_m=0.005, slip_tolerance_m=0.002)
    assert (r.held, r.reason) == (held, reason)
    assert r.change_m == pytest.approx(width - 0.0214)


def test_check_hold_bad_parameters():
    with pytest.raises(ValueError):
        gc.check_hold(width_m=0.02, width_at_grasp_m=0.0214, min_width_m=0, slip_tolerance_m=0.002)
    with pytest.raises(ValueError):
        gc.check_hold(width_m=0.02, width_at_grasp_m=0.0214, min_width_m=0.005, slip_tolerance_m=-1)
    with pytest.raises(ValueError):                 # 잡지 못한 상태(폭이 최소 이하)를 기준으로 쓰면 안 됨
        gc.check_hold(width_m=0.02, width_at_grasp_m=0.004, min_width_m=0.005, slip_tolerance_m=0.002)


def test_failure_code_by_stage():
    assert gc.FAILURE_CODE == {"close": "GRASP_FAILED", "lift": "GRASP_FAILED", "transport": "OBJECT_DROPPED"}


# ---- 비정상 폭은 잡은 것으로 보지 않음 (#72 D 리뷰)
NAN, INF = float("nan"), float("inf")


@pytest.mark.parametrize("width", [NAN, INF, -INF, 0.2, -0.01, None, True])
def test_check_grasp_invalid_width_is_sensor_invalid(width):
    r = gc.check_grasp(width_m=width, grasp_detected=True, min_width_m=0.005)
    assert (r.ok, r.reason) == (False, gc.SENSOR_INVALID)


def test_check_grasp_non_bool_detected_is_sensor_invalid():
    assert gc.check_grasp(width_m=0.02, grasp_detected=1, min_width_m=0.005).reason == gc.SENSOR_INVALID


@pytest.mark.parametrize("kw", [{"min_width_m": NAN}, {"min_width_m": INF},
                                {"expected_width_m": NAN, "width_tolerance_m": 0.003},
                                {"expected_width_m": 0.02, "width_tolerance_m": NAN}])
def test_check_grasp_non_finite_params_raise(kw):
    with pytest.raises(ValueError):
        gc.check_grasp(**{"width_m": 0.02, "grasp_detected": True, "min_width_m": 0.005, **kw})


@pytest.mark.parametrize("width,at_grasp", [(NAN, 0.0214), (INF, 0.0214), (0.2, 0.0214), (0.02, NAN), (0.02, -INF)])
def test_check_hold_invalid_width_is_sensor_invalid(width, at_grasp):
    r = gc.check_hold(width_m=width, width_at_grasp_m=at_grasp, min_width_m=0.005, slip_tolerance_m=0.002)
    assert (r.held, r.reason) == (False, gc.SENSOR_INVALID)


@pytest.mark.parametrize("kw", [{"min_width_m": NAN}, {"slip_tolerance_m": NAN}, {"slip_tolerance_m": INF}])
def test_check_hold_non_finite_params_raise(kw):
    with pytest.raises(ValueError):
        gc.check_hold(**{"width_m": 0.02, "width_at_grasp_m": 0.0214, "min_width_m": 0.005, "slip_tolerance_m": 0.002, **kw})
