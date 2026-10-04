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
