"""무동작 안전 상태 조회(W1 `/skills/check_state`)·B 복구(W2 `/skills/recover`) 판단 — ROS 비의존 [#152·#271 C 계약 W1·W2, 제안 10/13 B].

로봇·그리퍼를 움직이지 않고 지금 읽을 수 있는 값만 모아 C 가 잠금 해제 판단(C `ready2go_runner/core/recovery.py` recover_blockers)에 쓰게 한다.
**모르는 값은 None(JSON null)** — C 는 자기가 보는 칸의 null 을 허가로 보지 않는다. 읽기 실패를 "괜찮음"으로 바꾸지 않는다.
응답 계약(계약안 #297): contracts/skills_safe_state.schema.json · contracts/examples/skills_check_state.json·skills_recover.json.
B 복구(W2)는 B 서버 잠금(이동 확인 실패 `LOCKING_CODES`)과 쥐었는지 모름(`hold_unknown`)만 푼다. C 잠금 해제와는 별개.
"""
from __future__ import annotations

import math
from typing import Mapping, Optional

from . import grasp_check as gc
from .skill_flow import ESTOP_STATES, STATE_MOVING

STANDBY = 1                                   # DSR GetRobotState 대기 (jog_gui STATE 표) — 명령을 받을 준비
EMPTY_CLOSED_M = 0.002                        # 빈손 닫힘 폭 상한 — B 실측 빈손 닫힘 0.9 mm (gripper.min_width_m 과 같은 뜻)


def gripper_view(*, width_m: Optional[float], grasp_detected: Optional[bool], safety_error: Optional[bool],
                 held: Optional[Mapping], hold_unknown: Optional[Mapping], min_width_m: float, slip_tolerance_m: float) -> dict:
    """그리퍼 상태 {state: holding|empty|None, held_id, width_m, grasp_detected, reason}.
    - 쥐었는지 모름(hold_unknown, 재시작 때 폭 못 읽음) → state None (B 복구 W2 로 다시 읽어야 함)
    - 폭을 못 읽음·폭 이상·RG2 안전 오류 → None
    - 쥔 기억이 있으면 그때 폭과 비교(check_hold): HELD·SLIPPED → holding, DROPPED → empty(떨어짐 — 기억과 다름)
    - 쥔 기억이 없으면: 물체 감지 + 빈손 닫힘보다 넓음 → holding(무엇인지 모름, held_id None), 아니면 empty"""
    out = {"state": None, "held_id": (held or {}).get("id") if held else None, "width_m": width_m,
           "grasp_detected": grasp_detected, "reason": ""}
    if hold_unknown:
        out.update(held_id=hold_unknown.get("id"), reason="쥐었는지 모름 — 재시작 때 그리퍼 폭 못 읽음 (B 복구 필요)")
        return out
    if width_m is None or grasp_detected is None:
        out["reason"] = "그리퍼 읽기 실패"
        return out
    if not gc._width_ok(width_m):                           # 음수·RG2 범위 밖·NaN/inf — 쥔 기록과 무관하게 모름 [E #297 리뷰 P1]
        out["reason"] = "그리퍼 폭 이상"
        return out
    if safety_error:
        out["reason"] = "RG2 안전 오류"
        return out
    if held:
        try:
            h = gc.check_hold(width_m=width_m, width_at_grasp_m=float(held["width_m"]), min_width_m=min_width_m,
                              slip_tolerance_m=slip_tolerance_m)
        except (ValueError, KeyError, TypeError) as e:
            out["reason"] = f"쥔 기록 이상: {e}"
            return out
        if h.reason == gc.SENSOR_INVALID:
            out["reason"] = "그리퍼 폭 이상"
            return out
        if h.reason == gc.DROPPED:
            out.update(state="empty", reason=f"쥔 기억({held.get('class')})과 다름 — 폭 {width_m * 1000:.1f} mm 빈손")
            return out
        out.update(state="holding", reason=h.reason)
        return out
    if grasp_detected and width_m > max(min_width_m, EMPTY_CLOSED_M):
        out.update(state="holding", reason="쥔 기억 없는데 물체 감지 — 무엇인지 모름")
        return out
    out.update(state="empty", reason="")
    return out


def unknown_hold_decision(*, width_m: Optional[float], record: Mapping, min_width_m: float, slip_tolerance_m: float) -> Optional[str]:
    """W2 에서 쥐었는지 모름(hold_unknown) 기록을 어떻게 풀지 — 재시작 복원(_restore_held)과 같은 기준.
    "restore" = 저장 폭과 허용 오차 안(HELD) → 쥔 기억 복원 / "empty" = 빈손 닫힘(폭 ≤ 최소, DROPPED) → 기록 지움 /
    None = 불확실(폭이 저장값과 크게 다름·활짝 열림·다른 물체·못 읽음) → 기록·잠금 유지 [E #297 재리뷰 P1: 21 mm 기록인데 100 mm 열림을 복원]."""
    if width_m is None or not gc._width_ok(width_m):
        return None
    try:
        h = gc.check_hold(width_m=width_m, width_at_grasp_m=float(record["width_m"]), min_width_m=min_width_m,
                          slip_tolerance_m=slip_tolerance_m)
    except (ValueError, KeyError, TypeError):
        return None
    return {gc.HELD: "restore", gc.DROPPED: "empty"}.get(h.reason)


def external_force_view(samples, threshold_n: float, need: int):
    """지속 외력 판정 [B 실측 10/13 일지 32: 정지 중 |F| ≤ 약 2.8 N, 손으로 지그시 밀기 10~24 N] → (external_force, 창 안 |F| 최소 N).
    samples = 판정 창(external_force_hold_s) 동안 읽은 툴 힘 [fx, fy, fz, …] 목록. 하나라도 못 읽었거나(None·NaN·3축 미만) need 개보다 적으면
    (None, None) — 모름. 모두 |F| > threshold_n 이면 True(지속 외력), 아니면 False. |F| = 힘 3축 크기 (모멘트 안 봄)."""
    if samples is None or len(samples) < max(1, int(need)):
        return None, None
    mags = []
    for f in samples:
        try:
            axes = [float(v) for v in list(f)[:3]]
        except (TypeError, ValueError):
            return None, None
        if len(axes) < 3:                                   # 축이 빠진 응답을 0 으로 보지 않음 [E #335 리뷰 P2]
            return None, None
        m = math.sqrt(sum(v * v for v in axes))
        if not math.isfinite(m):
            return None, None
        mags.append(m)
    low = min(mags)
    return bool(low > float(threshold_n)), round(low, 2)


def build_state(*, robot_state: Optional[int], motion_state: Optional[int], busy: bool, tool_ok: Optional[bool],
                gripper: dict, gripper_read: bool, locked: Optional[str], disp: Mapping, stamp: str,
                external_force: Optional[bool] = None, external_force_n: Optional[float] = None) -> dict:
    """W1 결과 (#271 칸): stopped·external_force·sensors_ok·comm_ok·controller_ready·estop_active·tcp_tool_ok·gripper·drawers·
    b_locked·stamp + 참고(robot_state·b_lock_reason·busy).
    robot_state: DSR GetRobotState 원값(None = 조회 실패). motion_state: 관절 변화까지 본 값(skill_flow.MotionState).
    busy: 스킬 동작 실행 중(MotionGate). external_force: external_force_view 판정(멈춤이 아니거나 못 읽으면 None)."""
    known = robot_state is not None and motion_state is not None
    stopped = (not busy and motion_state != STATE_MOVING and robot_state != STATE_MOVING) if known else None
    return {
        "stopped": stopped,
        "external_force": external_force if stopped else None,      # 멈춘 상태에서만 판정 (움직이면 관성·가감속이 섞임)
        "external_force_n": external_force_n if stopped else None,
        "sensors_ok": gripper_read and gripper.get("reason") not in ("RG2 안전 오류", "그리퍼 폭 이상"),
        "comm_ok": robot_state is not None and gripper_read,
        "controller_ready": (robot_state == STANDBY) if robot_state is not None else None,
        "estop_active": (robot_state in ESTOP_STATES) if robot_state is not None else None,
        "tcp_tool_ok": tool_ok,
        "gripper": {k: gripper.get(k) for k in ("state", "held_id", "width_m", "grasp_detected", "reason")},
        "drawers": {k: (None if v is None else round(float(v), 4)) for k, v in dict(disp).items()},
        "b_locked": bool(locked),
        "b_lock_reason": locked or None,
        "robot_state": robot_state,
        "busy": busy,
        "stamp": stamp,
    }


def recover_blockers(state: Mapping) -> list:
    """B 복구(W2)로 잠금을 풀기 전 조건 — 로봇이 멈춰 있고 비상정지 아니고 제어기 준비·툴 일치·통신·센서 정상·지속 외력 없음,
    그리퍼 상태를 앎(holding|empty). 모르는 값(None)은 통과로 보지 않음. 빈 목록이면 복구 가능.
    센서 오류·그리퍼 모름이면 쥔 기록 유무와 무관하게 막음 [E #297 리뷰 P1: RG2 safety_error 인데 MOVE_UNCONFIRMED 잠금을 풂]."""
    out = []
    for key, want, code in (("stopped", True, "NOT_STOPPED"), ("estop_active", False, "ESTOP_ACTIVE"),
                            ("controller_ready", True, "CONTROLLER_NOT_READY"), ("tcp_tool_ok", True, "TOOL_MISMATCH"),
                            ("comm_ok", True, "COMM_FAILED"), ("sensors_ok", True, "SENSOR_INVALID"),
                            ("external_force", False, "EXTERNAL_FORCE")):
        v = state.get(key)
        if v is None:
            out.append(f"{key.upper()}_UNKNOWN")
        elif v is not want:
            out.append(code)
    if (state.get("gripper") or {}).get("state") not in ("holding", "empty"):
        out.append("GRIPPER_UNKNOWN")
    return out


def response_errors(service: str, success: bool, message: Mapping) -> list:
    """W1·W2 응답 규칙 중 JSON 스키마(contracts/skills_safe_state.schema.json)로 못 쓰는 칸 사이 규칙 → 어긋난 것 목록 (빈 목록 = 맞음).
    W1: success = 조회 끝남 — true 면 상태 칸, false 면 error 만. W2: success = recovered — 복구면 code ""·blockers []·B 잠금 없음·
    그리퍼 앎, 거절이면 code = blockers[0]·푼 것 없음, 서버 예외면 SKILL_EXCEPTION 에 state 없음 [E #297 재리뷰]."""
    errs = []
    if service == "/skills/check_state":
        if success is ("error" in message):
            errs.append("W1 success 는 조회 끝남 — true 면 상태 칸, false 면 error 만")
        return errs
    if service != "/skills/recover":
        return [f"모르는 서비스 {service}"]
    if success is not message.get("recovered"):
        errs.append("W2 success 는 recovered 와 같아야 함")
    if "error" in message:
        if message.get("code") != "SKILL_EXCEPTION" or "state" in message or message.get("recovered") is not False:
            errs.append("W2 서버 예외는 recovered false·SKILL_EXCEPTION·state 없음")
        return errs
    st = message.get("state") or {}
    if message.get("recovered"):
        if message.get("code") != "" or message.get("blockers"):
            errs.append("W2 복구면 code \"\"·blockers []")
        if st.get("b_locked") or (st.get("gripper") or {}).get("state") not in ("holding", "empty"):
            errs.append("W2 복구 뒤 state 는 B 잠금 없음·그리퍼 앎")
        if st.get("external_force") is not False:
            errs.append("W2 복구 뒤 state 는 지속 외력 없음(false)")
    else:
        b = message.get("blockers") or []
        if not b or message.get("code") != b[0]:
            errs.append("W2 거절이면 code = blockers[0]")
        if message.get("cleared"):
            errs.append("W2 거절이면 푼 것 없음(cleared [])")
    return errs
