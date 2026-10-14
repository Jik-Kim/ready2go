"""실패 원인 안내 문장 (core/failure_speech.py, E #196 10/14)."""
from ready2go_runner.core import failure_speech as fs


def test_vision_codes_say_cause_regardless_of_action():
    assert fs.text("CAMERA_TIMEOUT", "inspect_region") == "카메라 영상이 제때 오지 않아서 멈췄어요"
    assert fs.text("REGION_NOT_VISIBLE", "inspect_region") == "서랍 안이 카메라에 보이지 않아서 멈췄어요"


def test_timeout_names_the_failed_action_not_camera():
    assert fs.text("TIMEOUT", "pick_object") == "물건 집기가 제한 시간 안에 끝나지 않아서 멈췄어요"
    assert fs.text("TIMEOUT", "move_to_named_pose") == "로봇 자세 이동이 제한 시간 안에 끝나지 않아서 멈췄어요"
    assert "카메라" not in fs.text("TIMEOUT", "pick_object")


def test_refusals_by_action_and_generic():
    assert fs.text("WALL_TOO_CLOSE", "pick_object") == "물건 집기에 실패해서 멈췄어요"
    assert fs.text("NOT_REACHED", "nudge_object") == "물건 끌어오기에 실패해서 멈췄어요"
    assert fs.text("PRE_UNMET", "open_drawer") == "서랍 열기에 실패해서 멈췄어요"
    assert fs.text("LOOP_LIMIT", "while") == fs.GENERIC


def test_speak_failure_is_not_spoken_again():
    assert fs.text("TTS_FAILED", "speak") is None
