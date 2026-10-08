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
    assert nudged["push_vector_m"] == [0.0, -0.04]                                        # run_report "40.0 mm 끌기"
    assert mock.respond("nudge_object", {"target": target, "check_only": True}).output == {
        "pushed": False, "push_vector_m": [0.0, 0.0], "target_after": target}


def test_reinspect_after_nudge_sees_moved_object_and_pick_resets():
    """영상용 실물처럼: 끌기 뒤 다시 인식하면 끌린 자리, 집기 성공 뒤(다음 회차)는 처음 자리."""
    mock = MockSkills()
    first = mock.inspect("drawer_top", "eraser").output["target"]
    assert first["pose"]["position"] == [0.025, 0.292, 0.0]                                 # P1 벽 배치 (10/07 PC2)
    after = mock.respond("nudge_object", {"target": first, "drawer_id": "drawer_top"}).output["target_after"]
    again = mock.inspect("drawer_top", "eraser").output["target"]
    assert again["pose"] == after["pose"] and again["pose"]["position"][1] == 0.252
    assert mock.inspect("drawer_top", "car_key").output["target"]["pose"]["position"] == [0.025, 0.292, 0.0]   # 다른 물품은 그대로
    mock.respond("pick_object", {"target": again})
    assert mock.inspect("drawer_top", "eraser").output["target"]["pose"]["position"] == [0.025, 0.292, 0.0]


def test_failed_nudge_or_pick_keeps_position_as_is():
    mock = MockSkills(parse_failures("nudge_object=NO_PUSH_ACCESS*1,pick_object=GRASP_FAILED*1"))
    first = mock.inspect("drawer_top", "eraser").output["target"]
    assert not mock.respond("nudge_object", {"target": first}).success
    assert mock.inspect("drawer_top", "eraser").output["target"]["pose"]["position"][1] == 0.292   # 안 끌렸음
    mock.respond("nudge_object", {"target": first})
    assert not mock.respond("pick_object", {"target": first}).success                              # 집기 실패
    assert mock.inspect("drawer_top", "eraser").output["target"]["pose"]["position"][1] == 0.252   # 끌린 자리 그대로


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
