"""#10-3 mock 백엔드 응답 규칙 (ROS 비의존)."""
import pytest

from ready2go_runner.core.mock_skills import MockSkills, parse_failures


def test_parse_failures():
    assert parse_failures("pick_object=GRASP_FAILED*1, drawer_control=DRAWER_STUCK") == {
        "pick_object": ["GRASP_FAILED", 1], "drawer_control": ["DRAWER_STUCK", None]}
    assert parse_failures("") == {}
    with pytest.raises(ValueError):
        parse_failures("pick_object")


def test_outputs_follow_runner_md():
    mock = MockSkills()
    assert mock.respond("drawer_control", {"drawer_id": "drawer_top", "state": "open"}).output == {
        "drawer_displacement": 0.2, "close_confirmed": False}
    assert mock.respond("pick_object", {"object_id": "car_key#1"}).output["class"] == "car_key"   # 트레이·이전 형식
    picked = mock.respond("pick_object", {"target": {"id": "eraser#2", "class": "eraser"}}).output   # 서랍 (PR #70)
    assert (picked["object_id"], picked["class"]) == ("eraser#2", "eraser")
    assert mock.respond("place_object", {"location": "handover_zone"}).output["slot"] == "handover_zone"
    assert mock.respond("move_to_named_pose", {"pose_name": "home"}).output is None
    target = {"id": "eraser#1", "pose": {"frame": "drawer_top", "position": [0.1769, 0.2895, 0.0]}}
    nudged = mock.respond("nudge_object", {"target": target, "drawer_id": "drawer_top"}).output
    assert nudged["pushed"] and nudged["target_after"]["pose"]["position"][1] == 0.2495     # 옆(y)으로 끔
    assert target["pose"]["position"][1] == 0.2895                                          # 입력은 그대로
    assert mock.respond("nudge_object", {"target": target, "check_only": True}).output == {"pushed": False, "target_after": target}


def test_failure_first_n_times_then_success():
    mock = MockSkills(parse_failures("pick_object=GRASP_FAILED*1"))
    first, second = mock.respond("pick_object", {}), mock.respond("pick_object", {})
    assert (first.success, first.error_code) == (False, "GRASP_FAILED")
    assert second.success


def test_failure_always():
    mock = MockSkills(parse_failures("drawer_control=DRAWER_STUCK"))
    assert all(not mock.respond("drawer_control", {}).success for _ in range(3))


def test_inspect_found_and_not_visible():
    mock = MockSkills(not_visible={"eraser"})
    found = mock.inspect("drawer_top", "car_key").output
    assert found["target_found"] and found["target"]["id"] == "car_key#1"
    assert found["target"]["pose"]["frame"] == "drawer_top" and found["target"]["pose"]["yaw_valid"] is True
    assert mock.inspect("drawer_top", "eraser").output == {"target_found": False, "target": None,
                                                           "candidates": [], "visible_count": 0}
