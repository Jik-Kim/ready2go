"""스킬 서버 공통 흐름 (ROS 비의존·pytest 대상, #10·#15·#19).

Runner와의 약속 (docs/runner.md 7.1 "백엔드 구현 약속", #10):
  - 취소 요청을 받으면 안전하게 멈추고 canceled 로 끝낸다 (Skill goal 에 제한 시간 칸이 없어 Runner 가 취소로 끊음)
  - 펜던트 비상정지·안전정지로 멈추면 error_code "ESTOP" (Runner ABORTED·잠김)
  - 움직이기 전에 펜던트 툴 설정 확인, 다르면 TOOL_NOT_SET (motion_guard, #70)
노드는 DSR 서비스를 감싼 함수만 넘기고, 언제 멈추고 무엇을 돌려줄지는 여기서 정한다.
"""
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

CANCELED = "CANCELED"
ESTOP = "ESTOP"
UNKNOWN_POSE = "UNKNOWN_POSE"            # poses.yaml 에 없는 이름, 또는 서랍 포즈인데 drawer_id 가 없음
POSE_NOT_TAUGHT = "POSE_NOT_TAUGHT"      # 이름은 있는데 값이 null (아직 교시 전)
MOVE_REJECTED = "MOVE_REJECTED"          # 제어기가 이동 명령을 거부 (모드·상태)
MOTION_TIMEOUT = "MOTION_TIMEOUT"        # 서버 쪽 안전 상한 시간 안에 끝나지 않음 → 정지
NOT_REACHED = "NOT_REACHED"              # 멈췄는데 목표 관절각과 다름
NOT_IMPLEMENTED = "NOT_IMPLEMENTED"      # 아직 실물 구현 전 (로봇 동작 없음)
BAD_PARAMS = "BAD_PARAMS"
STOP_UNCONFIRMED = "STOP_UNCONFIRMED"    # 정지 명령 뒤 멈춘 것을 확인 못 함 — 노드 잠금, Runner 는 ESTOP 처럼 ABORTED 권장 (#73 D 리뷰)
STATE_UNKNOWN = "STATE_UNKNOWN"          # 이동 중 상태 조회가 계속 실패 → 정지 후 이 코드
MOVE_UNCONFIRMED = "MOVE_UNCONFIRMED"    # 이동 명령 응답이 없어 수락 여부 모름 → 정지·확인 후 이 코드로 잠금 (#73 E 리뷰)
MOVE_NOT_STARTED = "MOVE_NOT_STARTED"    # 명령이 수락됐는데 start_timeout_s 안에 움직이지도, 목표에 있지도 않음 → 정지 확인 후 이 코드
BUSY = "BUSY"                            # 다른 동작이 실행 중 — 한 번에 하나만 (#73 E 리뷰). 로봇 동작 없음
LOCKED = "LOCKED"                        # 앞서 LOCKING_CODES 로 잠긴 서버 — 사람이 확인하고 서버를 다시 띄울 때까지 거부
SKILL_EXCEPTION = "SKILL_EXCEPTION"      # 서버 안 예외 — 움직인 뒤일 수 있음. Runner 의 BACKEND_ERROR(서버 없음·goal 거절, 동작 안 함)와 구분 (#73 C 리뷰)

# DSR GetRobotState 값 (jog_gui STATE 표와 같음 [문서 DRFL]). 2 = 이동 중
STATE_MOVING = 2
ESTOP_STATES = {5, 6, 9}                 # 안전 정지, 비상정지, 안전 정지2


@dataclass(frozen=True)
class Outcome:
    success: bool
    error_code: str = ""                 # 성공이면 ""
    canceled: bool = False               # True 면 노드가 goal.canceled() 로 끝냄
    reason: str = ""


def pose_joints(poses: Mapping, pose_name: str, drawer_id: Optional[str] = None):
    """config/poses.yaml 에서 관절각(deg) 6개. (joints, None) 또는 (None, Outcome 에러).
    두 형식: `home: {joints_deg: [...]}` / 서랍 포즈 `drawer_approach: {drawer_top: [...]}`."""
    entry = poses.get(pose_name)
    if not isinstance(entry, Mapping):
        return None, Outcome(False, UNKNOWN_POSE, reason=f"poses.yaml 에 {pose_name!r} 없음")
    if "joints_deg" in entry:
        joints = entry["joints_deg"]
    elif drawer_id is None:
        return None, Outcome(False, UNKNOWN_POSE, reason=f"{pose_name} 은 서랍별 포즈라 drawer_id 필요")
    elif drawer_id not in entry:
        return None, Outcome(False, UNKNOWN_POSE, reason=f"{pose_name}.{drawer_id} 없음")
    else:
        joints = entry[drawer_id]
    if joints is None:
        return None, Outcome(False, POSE_NOT_TAUGHT, reason=f"{pose_name} 아직 교시 전 (null)")
    if (not isinstance(joints, Sequence) or len(joints) != 6
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in joints)):
        return None, Outcome(False, BAD_PARAMS, reason=f"{pose_name} 관절각 형식 오류: {joints!r}")
    return [float(v) for v in joints], None


# 서버를 잠그는 결과 — 로봇이 아직 움직이거나 늦게 도착한 명령으로 움직일 수 있음. 사람 확인 후 서버 재시작으로 해제
LOCKING_CODES = frozenset({"STOP_UNCONFIRMED", "STATE_UNKNOWN", "MOVE_UNCONFIRMED"})


# 이 결과 뒤에는 로봇을 더 움직이지 않는다 (복귀·후퇴 이동도 보내지 않음, #37 E 검토 10/06)
SAFETY_CODES = frozenset({ESTOP, CANCELED}) | LOCKING_CODES
_SEVERITY = {**{c: 3 for c in LOCKING_CODES}, ESTOP: 2, CANCELED: 1}


def is_safety(outcome: Optional["Outcome"]) -> bool:
    return outcome is not None and not outcome.success and outcome.error_code in SAFETY_CODES


def worse(first: Optional["Outcome"], second: Optional["Outcome"]) -> Optional["Outcome"]:
    """두 결과(None = 성공) 중 더 심각한 쪽. 잠금 > ESTOP > 취소 > 일반 실패 > 성공, 같으면 first.
    동작 실패 뒤 복귀 이동까지 실패하면 안전 오류가 일반 오류에 가려지지 않게 (#37 E 검토 10/06)."""
    def rank(o):
        if o is None or o.success:
            return -1
        return _SEVERITY.get(o.error_code, 0)
    return second if rank(second) > rank(first) else (first if first is not None and not first.success else None)


def stopped_by_estop(robot_state: Optional[int]) -> bool:
    return robot_state in ESTOP_STATES


class MotionState:
    """로봇 상태 + 관절각 변화. 관절이 eps_deg 넘게 바뀐 뒤 hold_s 안이면 '이동 중'(STATE_MOVING)으로 돌려준다.
    실물에서 관절 이동 중에도 GetRobotState 가 3 s 넘게 '이동 중'이 아니었음 (10/06 C 연결 확인 재시험, 홈 가다가
    MOVE_NOT_STARTED 로 정지) → wait_motion·정지 확인(_halt)이 상태값만 믿지 않게 한다. 관절 조회 실패면 상태값 그대로."""

    def __init__(self, get_state: Callable[[], Optional[int]], get_joints: Callable[[], Optional[Sequence[float]]],
                 eps_deg: float = 0.02, hold_s: float = 0.3, clock: Callable[[], float] = time.monotonic):
        self._state, self._joints, self._clock = get_state, get_joints, clock
        self.eps, self.hold = eps_deg, hold_s
        self._last = None
        self._changed_at = None
        self._lock = threading.Lock()

    def __call__(self) -> Optional[int]:
        state = self._state()
        if state is None or stopped_by_estop(state):
            return state
        joints = self._joints()
        now = self._clock()
        with self._lock:
            if joints is not None and len(joints) == 6 and all(_finite(v) for v in joints):
                if self._last is not None and max(abs(a - b) for a, b in zip(joints, self._last)) > self.eps:
                    self._changed_at = now
                self._last = list(joints)
            if state != STATE_MOVING and self._changed_at is not None and now - self._changed_at < self.hold:
                return STATE_MOVING
        return state


class MotionGate:
    """로봇은 하나라 동작도 한 번에 하나만 (#73 E 리뷰: 5개 액션 전체 직렬화). 기다리지 않고 바로 판정한다."""

    def __init__(self):
        self._lock = threading.Lock()

    def busy(self) -> bool:
        return self._lock.locked()

    def try_enter(self) -> bool:
        return self._lock.acquire(blocking=False)

    def exit(self) -> None:
        self._lock.release()


def execute_skill(handler: Callable[[], tuple], *, gate: MotionGate, locked: Callable[[], Optional[str]],
                  set_locked: Callable[[str], None], cancel_requested: Callable[[], bool],
                  check_tool: Callable[[], Optional[Outcome]], stop: Callable[[], bool],
                  get_state: Callable[[], Optional[int]], **halt_kw):
    """노드 execute 의 실행 순서 → (Outcome, output). gate 안에서 잠금을 확인하고, 잠금 설정도 gate 를 놓기 전에 한다
    → 먼저 수락돼 기다리던 goal 이 앞 goal 의 잠금을 건너뛰지 못함 (#73 E 재검토 P1).
    gate 진입 → 잠금 확인(LOCKED) → 이미 취소됐으면 움직이지 않고 canceled → 툴 확인 → handler(예외 시 정지 확인)
    → 잠금 코드면 잠금 → gate 해제."""
    if not gate.try_enter():
        return Outcome(False, BUSY, reason="다른 동작 실행 중 (로봇 동작 없음)"), None
    try:
        why = locked()
        if why:
            return Outcome(False, LOCKED, reason=f"잠김: {why} — 로봇 확인 후 skill_server 재시작"), None
        early = canceled_before_motion(cancel_requested)
        if early:
            return early, None
        err = check_tool()
        if err:
            return err, None
        outcome, output = run_guarded(handler, stop=stop, get_state=get_state, **halt_kw)
        if outcome.error_code in LOCKING_CODES:
            set_locked(outcome.reason)
        return outcome, output
    finally:
        gate.exit()


def canceled_before_motion(cancel_requested: Callable[[], bool]) -> Optional[Outcome]:
    """이동 명령을 보내기 직전에 호출. 이미 취소됐으면 명령을 보내지 않고 canceled (#73 E 재검토 P1).
    이 goal 은 아직 로봇을 움직이지 않았으므로 정지 명령도 보내지 않는다 (다른 동작의 정지 책임을 건드리지 않음)."""
    if cancel_requested():
        return Outcome(False, CANCELED, canceled=True, reason="이동 명령 전 취소 — 로봇 동작 없음")
    return None


MAX_REACH_TOL_DEG = 5.0                  # 도착 판정 허용 오차 상한 — 이보다 크면 설정 오류로 본다


def check_server_params(*, joint_vel_deg_s, joint_acc_deg_s2, move_timeout_s, reach_tol_deg) -> None:
    """스킬 서버 파라미터가 유한하고 범위 안인지. 아니면 ValueError — 서버가 뜨지 않음 (#73 E 재검토 P2, NaN 허용)."""
    vals = {"joint_vel_deg_s": joint_vel_deg_s, "joint_acc_deg_s2": joint_acc_deg_s2,
            "move_timeout_s": move_timeout_s, "reach_tol_deg": reach_tol_deg}
    bad = [k for k, v in vals.items() if not _finite(v) or v <= 0]
    if not bad and reach_tol_deg > MAX_REACH_TOL_DEG:
        bad = ["reach_tol_deg"]
    if bad:
        raise ValueError(f"스킬 서버 파라미터 비정상 {bad}: {vals} (reach_tol_deg 는 (0, {MAX_REACH_TOL_DEG:g}])")


def after_command(accepted: Optional[bool], *, what: str, stop: Callable[[], bool],
                  get_state: Callable[[], Optional[int]], period_s: float = 0.05, stop_confirm_s: float = 3.0,
                  clock: Callable[[], float] = time.monotonic,
                  sleep: Callable[[float], None] = time.sleep) -> Optional[Outcome]:
    """이동 명령을 보낸 직후. accepted: True = 수락, False = 명시적 거부, None = 응답 없음(수락 여부 모름).
    - True → None (wait_motion 으로 진행)
    - None → 이미 움직이고 있을 수 있으므로 정지 + 정지 확인. 확인돼도 늦게 도착한 요청으로 움직일 수 있어 MOVE_UNCONFIRMED(잠금)
    - False → 비상정지 상태면 ESTOP, 이동 중이면 정지 + 확인 후 MOVE_REJECTED, 아니면 MOVE_REJECTED (#73 E 리뷰)"""
    def halt(o):
        return _halt(stop, get_state, clock, sleep, period_s, stop_confirm_s, o)

    if accepted is True:
        return None
    if accepted is None:
        return halt(Outcome(False, MOVE_UNCONFIRMED, reason=f"{what} 응답 없음 — 정지 확인했지만 늦은 요청 가능성, 사람 확인 필요"))
    state = get_state()
    if stopped_by_estop(state):
        return Outcome(False, ESTOP, reason=f"{what} 거부 — 로봇 상태 {state}")
    if state is None or state == STATE_MOVING:
        return halt(Outcome(False, MOVE_REJECTED, reason=f"{what} 거부 — 로봇 상태 {state}, 정지 확인"))
    return Outcome(False, MOVE_REJECTED, reason=f"{what} 거부 — 로봇 상태 {state}")


def wait_motion(*, get_state: Callable[[], Optional[int]], cancel_requested: Callable[[], bool],
                stop: Callable[[], bool], timeout_s: float, period_s: float = 0.05,
                settle_s: float = 0.3, unknown_limit_s: float = 1.0, stop_confirm_s: float = 3.0,
                clock: Callable[[], float] = time.monotonic,
                sleep: Callable[[float], None] = time.sleep,
                watch: Optional[Callable[[], Optional[Outcome]]] = None,
                arrived: Optional[Callable[[], bool]] = None, start_timeout_s: float = 3.0) -> Outcome:
    """비동기 이동 명령을 보낸 뒤 끝날 때까지 기다린다.
    - watch(): 주기마다 호출. Outcome 을 돌려주면 정지 → 정지가 확인되면 그 Outcome (접촉 감지 = 성공, 걸림 = 실패 등)
    - 취소 요청 → 정지 → **정지가 확인되면** canceled, 확인 못 하면 STOP_UNCONFIRMED (#73 D 리뷰)
    - 비상정지·안전정지 상태 → ESTOP
    - timeout_s 초과 → 정지 → 확인되면 MOTION_TIMEOUT, 아니면 STOP_UNCONFIRMED
    - 상태 조회 실패(None)는 '끝남'이 아니라 '모름'. unknown_limit_s 넘게 계속되면 정지 → STATE_UNKNOWN / STOP_UNCONFIRMED
    - 이동 시작 전 잠깐(settle_s)은 '이동 중'이 아니어도 끝난 것으로 보지 않는다 (명령 직후 상태가 늦게 바뀜).
    - arrived()(목표에 있는지)를 주면: 멈췄을 때 목표에 없으면 NOT_REACHED. '이동 중'을 한 번도 못 봤을 때는 목표에 있을 때만 끝. start_timeout_s 안에
      움직이지도 도착하지도 않으면 정지 → MOVE_NOT_STARTED. 실물 10°/s 에서 '이동 중'으로 바뀌는 데 0.3 s 넘게 걸려
      출발 전에 끝으로 판단한 사고 대응 (10/06 C 연결 확인, NOT_REACHED 195°)."""
    t0 = clock()
    seen_moving = False
    unknown_since = None

    def halt(outcome_if_stopped: Outcome) -> Outcome:
        return _halt(stop, get_state, clock, sleep, period_s, stop_confirm_s, outcome_if_stopped)

    while True:
        state = get_state()
        if stopped_by_estop(state):
            return Outcome(False, ESTOP, reason=f"로봇 상태 {state} (안전·비상정지)")
        if cancel_requested():
            return halt(Outcome(False, CANCELED, canceled=True, reason="취소 요청으로 정지"))
        if watch is not None:
            hit = watch()
            if hit is not None:
                return halt(hit)
        now = clock()
        elapsed = now - t0
        if state is None:
            unknown_since = now if unknown_since is None else unknown_since
            if now - unknown_since > unknown_limit_s:
                return halt(Outcome(False, STATE_UNKNOWN, reason=f"상태 조회 실패 {unknown_limit_s:g} s 넘음 — 정지"))
        else:
            unknown_since = None
            moving = state == STATE_MOVING
            seen_moving = seen_moving or moving
            if not moving:
                if seen_moving:
                    if arrived is not None and not arrived():      # 목표 전에 멈춤 → 다음 단계로 가지 않음 (#83 D 재검토 P1)
                        # 아주 느린 이동은 '멈춤'으로 잘못 볼 수 있음(10/07 누르기 1 mm/s: 정지 명령 없이 끝나 로봇이 감시 없이 계속 내려감)
                        # → 항상 정지 명령 + 정지 확인 뒤 NOT_REACHED
                        return halt(Outcome(False, NOT_REACHED, reason=f"이동이 멈췄지만 목표에 없음 ({elapsed:.1f} s)"))
                    return Outcome(True, reason=f"이동 끝 ({elapsed:.1f} s)")
                if arrived is None:
                    if elapsed >= settle_s:
                        return Outcome(True, reason=f"이동 끝 ({elapsed:.1f} s)")
                elif arrived():
                    return Outcome(True, reason=f"이미 목표에 있음 ({elapsed:.1f} s)")
                elif elapsed >= start_timeout_s:
                    return halt(Outcome(False, MOVE_NOT_STARTED,
                                        reason=f"{start_timeout_s:g} s 안에 움직이지 않고 목표에도 없음 — 정지"))
        if elapsed > timeout_s:
            return halt(Outcome(False, MOTION_TIMEOUT, reason=f"{timeout_s:g} s 안에 끝나지 않아 정지"))
        sleep(period_s)


def run_guarded(handler: Callable[[], tuple], *, stop: Callable[[], bool], get_state: Callable[[], Optional[int]],
                period_s: float = 0.05, stop_confirm_s: float = 3.0,
                clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
    """동작 handler() → (Outcome, output). 예외가 나면 움직인 뒤일 수 있으므로 정지하고 **정지를 확인**한다:
    확인되면 SKILL_EXCEPTION, 아니면 STOP_UNCONFIRMED (노드가 잠금). 취소·시간 초과와 같은 _halt 를 쓴다 (#73 D 리뷰)."""
    try:
        return handler()
    except Exception as e:
        out = _halt(stop, get_state, clock, sleep, period_s, stop_confirm_s,
                    Outcome(False, SKILL_EXCEPTION, reason=f"예외: {e!r}"))
        return out, None


def _halt(stop, get_state, clock, sleep, period_s, limit_s, outcome_if_stopped: Outcome) -> Outcome:
    """정지 명령 → 정지 확인. 명령이 받아들여지고 **움직이지 않는 상태를 두 번 연속 실제로 읽어야** 정지로 본다.
    아니면 STOP_UNCONFIRMED — 노드는 사람이 확인하기 전까지 다음 동작을 받지 않는다(잠금)."""
    sent = bool(stop())
    t0 = clock()
    still = 0
    while clock() - t0 < limit_s:
        state = get_state()
        if stopped_by_estop(state):
            return Outcome(False, ESTOP, reason=f"정지 중 로봇 상태 {state} (안전·비상정지)")
        still = still + 1 if state is not None and state != STATE_MOVING else 0
        if still >= 2:
            break
        sleep(period_s)
    if sent and still >= 2:
        return outcome_if_stopped
    why = "정지 명령 실패" if not sent else f"{limit_s:g} s 안에 정지 상태를 확인하지 못함"
    return Outcome(False, STOP_UNCONFIRMED, reason=f"{why} ({outcome_if_stopped.error_code} 처리 중) — 사람 확인 필요")


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check_reached(target_deg: Sequence[float], actual_deg: Optional[Sequence[float]], tol_deg: float) -> Outcome:
    """관절 6개가 모두 유한하고 목표와 tol 안인지. 개수가 다르거나 NaN 이 하나라도 있으면 실패 (#73 E 리뷰)."""
    if not _finite(tol_deg) or not 0 < tol_deg <= MAX_REACH_TOL_DEG:
        return Outcome(False, NOT_REACHED, reason=f"도착 허용 오차 비정상: {tol_deg!r} (설정 오류)")   # NaN 이면 모두 도착이 됨
    if actual_deg is None:
        return Outcome(False, NOT_REACHED, reason="현재 관절각 조회 실패")
    if (len(actual_deg) != 6 or len(target_deg) != 6
            or not all(_finite(v) for v in list(actual_deg) + list(target_deg))):
        return Outcome(False, NOT_REACHED, reason=f"관절각 개수·값 비정상: {list(actual_deg)!r}")
    err = max(abs(a - t) for a, t in zip(actual_deg, target_deg))
    if err > tol_deg:
        return Outcome(False, NOT_REACHED, reason=f"관절 오차 {err:.2f}° > {tol_deg:g}°")
    return Outcome(True, reason=f"도착 (관절 오차 {err:.2f}°)")
