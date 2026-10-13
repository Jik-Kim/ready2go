"""복구(recover) 판단 (ROS 비의존) — 계약 W3·W1 (#152·#271, FR-SAF-03·AC-SAF-04).

C 잠금 해제는 B 상태 조회(W1)가 **모든 조건을 충족**할 때만. 모르는 값(null·칸 없음)은 허가로 보지 않는다.
B 복구 결과(W2)와 C 잠금 해제는 분리 — 여기서는 조회 결과만 판단하고, 잠금 해제는 노드가 Runner.resume() 으로.
B 조회 인터페이스(/skills/check_state)는 B PR 전이라 노드는 mock 백엔드에서 mock_check 를, 실물에서는 조회 불가
(None → B_CHECK_UNAVAILABLE) 로 거절한다.
"""
from __future__ import annotations

B_CHECK_UNAVAILABLE = "B_CHECK_UNAVAILABLE"   # B 상태 조회를 할 수 없음 (W1 미연결·응답 없음) → 잠금 유지
# (칸, 필요한 값, 불충족 코드) — B 답 #152 ④: stopped·estop_active·controller_ready 는 robot_state, b_locked 는 B 잠금 사유
REQUIRED = (("stopped", True, "NOT_STOPPED"), ("estop_active", False, "ESTOP_ACTIVE"),
            ("controller_ready", True, "CONTROLLER_NOT_READY"), ("b_locked", False, "B_LOCKED"))


def recover_blockers(check: dict | None, runner_state: dict) -> list[str]:
    """B 조회 결과로 잠금 해제를 막는 이유 목록. 빈 목록이면 해제 가능.
    그리퍼: B 가 본 상태가 Runner 기억(gripper.robot)과 다르면 STATE_MISMATCH (빈손이라 기억하는데 쥐고 있음 등)."""
    if not isinstance(check, dict):
        return [B_CHECK_UNAVAILABLE]
    blockers = []
    for key, want, code in REQUIRED:
        value = check.get(key)
        if value is None:
            blockers.append(f"{key.upper()}_UNKNOWN")
        elif value is not want:
            blockers.append(code)
    gripper = check.get("gripper") if isinstance(check.get("gripper"), dict) else {}
    seen, held = gripper.get("state"), gripper.get("held_id")
    remembered = (runner_state.get("gripper") or {}).get("robot", "empty")
    if seen is None:
        blockers.append("GRIPPER_UNKNOWN")
    elif (seen == "empty") != (remembered == "empty") or (seen != "empty" and held and held.split("#")[0] != remembered):
        blockers.append("STATE_MISMATCH")
    return blockers


def mock_check(runner_state: dict) -> dict:
    """mock 백엔드용 B 조회 흉내 — 로봇은 멈춰 있고 그리퍼는 Runner 기억과 같다고 봄 (시험·로봇 없는 통합용)."""
    remembered = (runner_state.get("gripper") or {}).get("robot", "empty")
    return {"stopped": True, "estop_active": False, "controller_ready": True, "b_locked": False,
            "external_force": None, "gripper": {"state": "empty" if remembered == "empty" else "holding",
                                                "held_id": None if remembered == "empty" else f"{remembered}#1"},
            "mock": True}
