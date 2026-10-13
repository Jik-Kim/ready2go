"""복구(recover) 판단 — B 상태 조회(W1)가 모두 충족일 때만 C 잠금 해제, 모름은 허가 아님 (#152·#271, FR-SAF-03)."""
from ready2go_runner.core.recovery import B_CHECK_UNAVAILABLE, mock_check, recover_blockers

EMPTY = {"gripper": {"robot": "empty"}}
HOLDING = {"gripper": {"robot": "eraser"}}


def ok(**over):
    return {"stopped": True, "estop_active": False, "controller_ready": True, "b_locked": False,
            "gripper": {"state": "empty", "held_id": None}, **over}


def test_all_good_unlocks_and_mock_matches_memory():
    assert recover_blockers(ok(), EMPTY) == []
    assert recover_blockers(mock_check(EMPTY), EMPTY) == [] and recover_blockers(mock_check(HOLDING), HOLDING) == []


def test_unavailable_unknown_or_bad_values_keep_the_lock():
    assert recover_blockers(None, EMPTY) == [B_CHECK_UNAVAILABLE]
    assert recover_blockers(ok(stopped=None), EMPTY) == ["STOPPED_UNKNOWN"]          # 모름은 허가 아님
    assert recover_blockers(ok(estop_active=True), EMPTY) == ["ESTOP_ACTIVE"]
    assert recover_blockers(ok(controller_ready=False, b_locked=True), EMPTY) == ["CONTROLLER_NOT_READY", "B_LOCKED"]
    assert recover_blockers(ok(gripper={}), EMPTY) == ["GRIPPER_UNKNOWN"]


def test_gripper_must_match_runner_memory():
    holding = ok(gripper={"state": "holding", "held_id": "eraser#1"})
    assert recover_blockers(holding, EMPTY) == ["STATE_MISMATCH"]                   # 빈손 기억인데 쥐고 있음
    assert recover_blockers(ok(), HOLDING) == ["STATE_MISMATCH"]                     # 쥔 기억인데 빈손
    assert recover_blockers(holding, HOLDING) == []
    assert recover_blockers(ok(gripper={"state": "holding", "held_id": "car_key#1"}), HOLDING) == ["STATE_MISMATCH"]
