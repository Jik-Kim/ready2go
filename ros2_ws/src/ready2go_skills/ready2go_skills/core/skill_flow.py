"""스킬 서버 공통 흐름 (ROS 비의존·pytest 대상, #10·#15·#19).

Runner와의 약속 (docs/runner.md 7.1 "백엔드 구현 약속", #10):
  - 취소 요청을 받으면 안전하게 멈추고 canceled 로 끝낸다 (Skill goal 에 제한 시간 칸이 없어 Runner 가 취소로 끊음)
  - 펜던트 비상정지·안전정지로 멈추면 error_code "ESTOP" (Runner ABORTED·잠김)
  - 움직이기 전에 펜던트 툴 설정 확인, 다르면 TOOL_NOT_SET (motion_guard, #70)
노드는 DSR 서비스를 감싼 함수만 넘기고, 언제 멈추고 무엇을 돌려줄지는 여기서 정한다.
"""
import math
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


def stopped_by_estop(robot_state: Optional[int]) -> bool:
    return robot_state in ESTOP_STATES


def wait_motion(*, get_state: Callable[[], Optional[int]], cancel_requested: Callable[[], bool],
                stop: Callable[[], None], timeout_s: float, period_s: float = 0.05,
                settle_s: float = 0.3, clock: Callable[[], float] = time.monotonic,
                sleep: Callable[[float], None] = time.sleep) -> Outcome:
    """비동기 이동 명령을 보낸 뒤 끝날 때까지 기다린다.
    - 취소 요청 → stop() → 멈출 때까지 기다림 → canceled
    - 비상정지·안전정지 상태 → ESTOP
    - timeout_s 초과 → stop() → MOTION_TIMEOUT
    - 이동 시작 전 잠깐(settle_s)은 '이동 중'이 아니어도 끝난 것으로 보지 않는다 (명령 직후 상태가 늦게 바뀜)."""
    t0 = clock()
    seen_moving = False
    while True:
        state = get_state()
        if stopped_by_estop(state):
            return Outcome(False, ESTOP, reason=f"로봇 상태 {state} (안전·비상정지)")
        if cancel_requested():
            stop()
            _wait_still(get_state, clock, sleep, period_s, limit_s=3.0)
            return Outcome(False, CANCELED, canceled=True, reason="취소 요청으로 정지")
        moving = state == STATE_MOVING
        seen_moving = seen_moving or moving
        elapsed = clock() - t0
        if not moving and (seen_moving or elapsed >= settle_s):
            return Outcome(True, reason=f"이동 끝 ({elapsed:.1f} s)")
        if elapsed > timeout_s:
            stop()
            _wait_still(get_state, clock, sleep, period_s, limit_s=3.0)
            return Outcome(False, MOTION_TIMEOUT, reason=f"{timeout_s:g} s 안에 끝나지 않아 정지")
        sleep(period_s)


def _wait_still(get_state, clock, sleep, period_s, limit_s):
    t0 = clock()
    while get_state() == STATE_MOVING and clock() - t0 < limit_s:
        sleep(period_s)


def check_reached(target_deg: Sequence[float], actual_deg: Optional[Sequence[float]], tol_deg: float) -> Outcome:
    if actual_deg is None:
        return Outcome(False, NOT_REACHED, reason="현재 관절각 조회 실패")
    err = max(abs(a - t) for a, t in zip(actual_deg, target_deg))
    if not math.isfinite(err) or err > tol_deg:
        return Outcome(False, NOT_REACHED, reason=f"관절 오차 {err:.2f}° > {tol_deg:g}°")
    return Outcome(True, reason=f"도착 (관절 오차 {err:.2f}°)")
