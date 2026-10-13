"""복구(recover) 판단 (ROS 비의존) — 계약 W3·W1 (#152·#271, FR-SAF-03·AC-SAF-04).

C 잠금 해제는 B 상태 조회(W1)의 **모든 필수 칸이 충족**할 때만 (fail-closed, #289 D·E 리뷰 P1).
모르는 값(null·칸 없음·지원하지 않는 값)은 허가로 보지 않는다. 힘·신선도 기준이 팀에서 정해지지 않았으면
임의 수치로 허가하지 않고 그 칸을 미확인으로 거절한다(*_LIMIT_UNSET).
B 복구 결과(W2)와 C 잠금 해제는 분리 — 여기서는 조회 결과만 판단하고, 잠금 해제는 노드가 Runner.resume() 으로.
B 조회 인터페이스(/skills/check_state)는 B PR 전이라 노드는 mock 백엔드에서만 mock_check 를 쓰고,
real·sim 은 조회 불가(None → B_CHECK_UNAVAILABLE)로 거절한다 — 설정으로 real 에서 mock 을 골라도 쓰지 않음.
"""
from __future__ import annotations

from datetime import datetime, timezone

B_CHECK_UNAVAILABLE = "B_CHECK_UNAVAILABLE"   # B 상태 조회를 할 수 없음 (W1 미연결·응답 없음) → 잠금 유지
STATE_MISMATCH = "STATE_MISMATCH"             # B 가 본 그리퍼·서랍이 Runner 기억과 다름
STATE_STALE = "STATE_STALE"                   # 조회 시각(stamp)이 너무 오래됨
# (칸, 필요한 값, 불충족 코드) — runner.md W1. 값이 bool 이 아니면(null·없음·다른 형) <칸>_UNKNOWN
REQUIRED = (("stopped", True, "NOT_STOPPED"), ("estop_active", False, "ESTOP_ACTIVE"),
            ("controller_ready", True, "CONTROLLER_NOT_READY"), ("b_locked", False, "B_LOCKED"),
            ("sensors_ok", True, "SENSORS_NOT_OK"), ("comm_ok", True, "COMM_NOT_OK"),
            ("tcp_tool_ok", True, "TCP_TOOL_NOT_OK"))
GRIPPER_STATES = ("empty", "holding")
# mock 백엔드 시험용 기준 — 실물 기준 아님. real 기준(external_force_max_n·stamp_max_age_s)은 B·팀 확정 전 None
MOCK_LIMITS = {"external_force_max_n": 5.0, "stamp_max_age_s": 2.0}


def choose_check(requested: str, backend: str) -> tuple[str, str | None]:
    """recover_check 파라미터 → 실제로 쓸 조회 방식과 경고. mock 조회는 mock 백엔드에서만 (#289 E 리뷰 P1)."""
    if requested == "mock" and backend == "mock":
        return "mock", None
    if requested == "mock":
        return "none", f"recover_check=mock 은 mock 백엔드에서만 — BACKEND={backend} 라 조회 불가로 둠(복구 거절)"
    if requested != "none":
        return "none", f"recover_check={requested!r} 는 지원하지 않음 — 조회 불가로 둠(복구 거절)"
    return "none", None


def _age_s(stamp, now: datetime) -> float | None:
    if not isinstance(stamp, str):
        return None
    try:
        t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        return None
    return (now - t).total_seconds()


def recover_blockers(check: dict | None, runner_state: dict, limits: dict | None = None,
                     now: datetime | None = None) -> list[str]:
    """B 조회 결과로 잠금 해제를 막는 이유 목록. 빈 목록이면 해제 가능.
    limits: {"external_force_max_n", "stamp_max_age_s"} — None·없음이면 그 칸은 미확인으로 거절.
    그리퍼·서랍: B 가 본 상태가 Runner 기억(gripper.robot·open)과 다르면 STATE_MISMATCH."""
    if not isinstance(check, dict):
        return [B_CHECK_UNAVAILABLE]
    limits = limits or {}
    now = now or datetime.now(timezone.utc)
    blockers = []
    for key, want, code in REQUIRED:
        value = check.get(key)
        if not isinstance(value, bool):
            blockers.append(f"{key.upper()}_UNKNOWN")
        elif value is not want:
            blockers.append(code)

    force, force_max = check.get("external_force"), limits.get("external_force_max_n")
    if force_max is None:
        blockers.append("EXTERNAL_FORCE_LIMIT_UNSET")        # 힘 기준 미합의 → 임의 수치로 허가 안 함
    elif not isinstance(force, (int, float)) or isinstance(force, bool):
        blockers.append("EXTERNAL_FORCE_UNKNOWN")
    elif abs(force) > force_max:
        blockers.append("EXTERNAL_FORCE")

    age, age_max = _age_s(check.get("stamp"), now), limits.get("stamp_max_age_s")
    if age_max is None:
        blockers.append("STAMP_LIMIT_UNSET")
    elif age is None or age < -age_max:                      # 없음·형식 오류·미래 시각
        blockers.append("STAMP_UNKNOWN")
    elif age > age_max:
        blockers.append(STATE_STALE)

    gripper = check.get("gripper") if isinstance(check.get("gripper"), dict) else {}
    seen, held = gripper.get("state"), gripper.get("held_id")
    remembered = (runner_state.get("gripper") or {}).get("robot", "empty")
    if seen not in GRIPPER_STATES or (seen == "holding" and not (isinstance(held, str) and held)):
        blockers.append("GRIPPER_UNKNOWN")                   # unknown·임의 문자열·쥔 물품 ID 없음
    elif (seen == "empty") != (remembered == "empty") or (seen == "holding" and held.split("#")[0] != remembered):
        blockers.append(STATE_MISMATCH)

    drawers = check.get("drawers")
    remembered_open = {k: v for k, v in (runner_state.get("open") or {}).items() if k.startswith("drawer")}
    if not isinstance(drawers, dict) or any(not isinstance(drawers.get(k), bool) for k in remembered_open):
        blockers.append("DRAWERS_UNKNOWN")                   # {서랍: 열림 bool} — 기억하는 서랍마다 있어야 함
    elif any(drawers[k] != v for k, v in remembered_open.items()):
        if STATE_MISMATCH not in blockers:
            blockers.append(STATE_MISMATCH)
    return blockers


def mock_check(runner_state: dict, now: datetime | None = None) -> dict:
    """mock 백엔드용 B 조회 흉내 — 모든 필수 칸을 명시(로봇은 멈춰 있고 정상, 그리퍼·서랍은 Runner 기억과 같음).
    시험·로봇 없는 통합 전용. real·sim 에서는 노드가 쓰지 않는다(choose_check)."""
    remembered = (runner_state.get("gripper") or {}).get("robot", "empty")
    drawers = {k: v for k, v in (runner_state.get("open") or {}).items() if k.startswith("drawer")}
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {"stopped": True, "estop_active": False, "controller_ready": True, "b_locked": False,
            "sensors_ok": True, "comm_ok": True, "tcp_tool_ok": True, "external_force": 0.0,
            "gripper": {"state": "empty" if remembered == "empty" else "holding",
                        "held_id": None if remembered == "empty" else f"{remembered}#1"},
            "drawers": drawers, "stamp": stamp, "mock": True}
