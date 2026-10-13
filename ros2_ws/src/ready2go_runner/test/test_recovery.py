"""복구(recover) 판단 — B 상태 조회(W1)의 모든 필수 칸이 충족일 때만 C 잠금 해제, 모름은 허가 아님 (#152·#271, FR-SAF-03).
#289 D·E 리뷰 P1: 센서·통신·툴·외력·신선도·서랍·그리퍼 enum 까지 fail-closed, mock 조회는 mock 백엔드에서만."""
from datetime import datetime, timedelta, timezone

import pytest

from ready2go_runner.core.recovery import (B_CHECK_UNAVAILABLE, MOCK_LIMITS, STATE_MISMATCH, STATE_STALE,
                                            choose_check, mock_check, recover_blockers)

NOW = datetime(2026, 10, 13, 7, 0, tzinfo=timezone.utc)
EMPTY = {"gripper": {"robot": "empty"}, "open": {"drawer_top": False, "drawer_bottom": False, "handover_zone": True}}
HOLDING = {**EMPTY, "gripper": {"robot": "eraser"}}


def ok(**over):
    return {"stopped": True, "estop_active": False, "controller_ready": True, "b_locked": False,
            "sensors_ok": True, "comm_ok": True, "tcp_tool_ok": True, "external_force": 0.5,
            "gripper": {"state": "empty", "held_id": None},
            "drawers": {"drawer_top": False, "drawer_bottom": False},
            "stamp": (NOW - timedelta(seconds=0.3)).isoformat().replace("+00:00", "Z"), **over}


def blockers(check, state=EMPTY, limits=MOCK_LIMITS):
    return recover_blockers(check, state, limits, now=NOW)


def test_all_good_unlocks_and_mock_matches_memory():
    assert blockers(ok()) == []
    assert blockers(mock_check(EMPTY, now=NOW)) == [] and blockers(mock_check(HOLDING, now=NOW), HOLDING) == []


@pytest.mark.parametrize("key, bad, code", [
    ("stopped", False, "NOT_STOPPED"), ("estop_active", True, "ESTOP_ACTIVE"),
    ("controller_ready", False, "CONTROLLER_NOT_READY"), ("b_locked", True, "B_LOCKED"),
    ("sensors_ok", False, "SENSORS_NOT_OK"), ("comm_ok", False, "COMM_NOT_OK"), ("tcp_tool_ok", False, "TCP_TOOL_NOT_OK"),
    ("sensors_ok", None, "SENSORS_OK_UNKNOWN"), ("stopped", "yes", "STOPPED_UNKNOWN"),
    ("external_force", 99.0, "EXTERNAL_FORCE"), ("external_force", None, "EXTERNAL_FORCE_UNKNOWN"),
    ("stamp", None, "STAMP_UNKNOWN"), ("stamp", "어제", "STAMP_UNKNOWN"),
    ("stamp", (NOW - timedelta(seconds=5)).isoformat(), STATE_STALE),
    ("drawers", None, "DRAWERS_UNKNOWN"), ("drawers", {"drawer_top": False}, "DRAWERS_UNKNOWN"),
    ("drawers", {"drawer_top": True, "drawer_bottom": False}, STATE_MISMATCH),
    ("gripper", {"state": "unknown", "held_id": None}, "GRIPPER_UNKNOWN"),
    ("gripper", {}, "GRIPPER_UNKNOWN"),
])
def test_each_required_field_false_null_stale_or_bad_keeps_the_lock(key, bad, code):
    assert blockers(ok(**{key: bad})) == [code]


def test_reviewer_counterexample_is_blocked():
    """#289 D·E 재현 입력: 센서·통신·툴 불량, 서랍·시각 없음, 외력 99 → 모두 차단."""
    bad = ok(external_force=99.0, sensors_ok=False, comm_ok=False, tcp_tool_ok=False, drawers=None, stamp=None)
    assert set(blockers(bad)) == {"SENSORS_NOT_OK", "COMM_NOT_OK", "TCP_TOOL_NOT_OK", "EXTERNAL_FORCE",
                                  "STAMP_UNKNOWN", "DRAWERS_UNKNOWN"}


def test_unavailable_or_limits_not_agreed_keep_the_lock():
    assert blockers(None) == [B_CHECK_UNAVAILABLE]
    assert blockers(ok(), limits=None) == ["EXTERNAL_FORCE_LIMIT_UNSET", "STAMP_LIMIT_UNSET"]   # 실물 기준 미확정


def test_gripper_must_match_runner_memory():
    holding = ok(gripper={"state": "holding", "held_id": "eraser#1"})
    assert blockers(holding) == [STATE_MISMATCH]                           # 빈손 기억인데 쥐고 있음
    assert blockers(ok(), HOLDING) == [STATE_MISMATCH]                     # 쥔 기억인데 빈손
    assert blockers(holding, HOLDING) == []
    assert blockers(ok(gripper={"state": "holding", "held_id": "car_key#1"}), HOLDING) == [STATE_MISMATCH]
    assert blockers(ok(gripper={"state": "holding", "held_id": None}), HOLDING) == ["GRIPPER_UNKNOWN"]   # ID 없음


def test_mock_check_only_on_mock_backend():
    assert choose_check("mock", "mock") == ("mock", None)
    mode, warning = choose_check("mock", "real")
    assert mode == "none" and "mock 백엔드에서만" in warning                 # real 에서 mock 지정 → 쓰지 않음
    assert choose_check("none", "real") == ("none", None)
    assert choose_check("anything", "mock")[0] == "none"
