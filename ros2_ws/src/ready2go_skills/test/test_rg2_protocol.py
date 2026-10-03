import pytest

from ready2go_skills.core import rg2_protocol as proto


def test_grip_command_units():
    assert proto.grip_command(50.0, 20.0) == [200, 500, proto.CONTROL_GRIP]
    assert proto.grip_command(0.0, 40.0) == [400, 0, proto.CONTROL_GRIP]


@pytest.mark.parametrize("width, force", [(-1, 20), (110.1, 20), (50, 0), (50, 40.1)])
def test_grip_command_rejects_out_of_range(width, force):
    with pytest.raises(ValueError):
        proto.grip_command(width, force)


def test_gripper_state_payload_matches_icd():
    st = proto.decode_status(523, proto.STATUS_GRIP_DETECTED)
    assert proto.gripper_state_payload(st) == {"width": 0.0523, "grasp_detected": True}


def test_decode_status_bits():
    st = proto.decode_status(523, proto.STATUS_BUSY | proto.STATUS_GRIP_DETECTED)
    assert st.width_mm == pytest.approx(52.3)
    assert st.busy and st.grip_detected and not st.safety_error
    assert proto.decode_status(0, proto.STATUS_SAFETY_ERROR).safety_error
