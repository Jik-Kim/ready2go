"""`drawer_control` 판단 (#13, docs/domain.md 8.4, ROS 비의존·pytest 대상).

노드는 이 함수들로 방향·거리·판정을 구하고, 실제 이동(movel 상대 이동, 컴플라이언스, 힘 읽기)은 DSR 서비스로 한다.
  열기: drawer_approach → 손잡이까지 직선 접근(approach_mm) → 파지 → 인출 방향으로 distance 당김(걸림 감시) → 해제 → 후퇴
  닫기: 그리퍼 닫고 서랍 앞면을 미는 방향으로 이동, 닫힘 = 닫힘 위치 도달 AND 미는 축 저항력 ≥ 임계 (둘 다)
방향: 서랍 좌표계 x축은 안쪽(places.yaml 첫 부분)이라 인출 = −x. 수평 성분만 쓴다(tf 기울기 약 0.9°).
힘 부호 [추정, 10/06 실측으로 확인]: `get_tool_force(ref=BASE)`가 공구가 받는 외력이면, 움직이는 방향을 막는 힘은
  F·dir < 0 이다. 그래서 저항력 = −F·dir 로 쓴다. 실측에서 부호가 반대면 `force_sign`을 −1로 둔다(params).
임계값·거리는 params/skills.yaml `drawer_control` [팀 확정 필요].
"""
import math
from dataclasses import dataclass
from typing import Optional, Sequence

DRAWER_STUCK = "DRAWER_STUCK"
CLOSE_NOT_CONFIRMED = "CLOSE_NOT_CONFIRMED"
BAD_DISTANCE = "BAD_DISTANCE"


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-9:
        raise ValueError(f"길이 0 벡터: {v}")
    return tuple(c / n for c in v)


def x_axis_from_quat(q_xyzw: Sequence[float]) -> tuple:
    """쿼터니언(xyzw)의 회전 행렬 첫 열 = 자식 좌표계 x축을 부모(base) 기준으로."""
    x, y, z, w = q_xyzw
    return (1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w))


def pull_direction(q_xyzw: Sequence[float]) -> tuple:
    """서랍을 여는 방향(base, 단위벡터, 수평). 서랍 x축(안쪽)의 반대를 수평면에 투영."""
    ax = x_axis_from_quat(q_xyzw)
    return _unit((-ax[0], -ax[1], 0.0))


def displacement_m(start_tcp_m: Sequence[float], now_tcp_m: Sequence[float], direction: Sequence[float]) -> float:
    """시작 위치에서 direction 방향으로 실제 이동한 거리(m). `drawer_displacement` 계산용."""
    return sum((n - s) * d for s, n, d in zip(start_tcp_m, now_tcp_m, direction))


def resist_force_n(force_n: Sequence[float], direction: Sequence[float], force_sign: float = 1.0) -> float:
    """움직이는 방향을 막는 힘의 크기(N, 막으면 양수). 방향을 보므로 옆으로 걸린 힘과 구분된다."""
    return -force_sign * sum(f * d for f, d in zip(force_n[:3], direction))


@dataclass(frozen=True)
class Verdict:
    done: bool                     # 이 구간을 끝내야 함 (성공이든 실패든)
    error_code: Optional[str]      # None = 정상
    reason: str


def check_open_distance(distance_m: float, max_travel_m: float) -> Optional[Verdict]:
    """요청 인출 거리가 (0, max_travel] 안인지. 넘으면 스토퍼에 걸리므로 시작 전에 거부."""
    if not (0.0 < distance_m <= max_travel_m + 1e-9):
        return Verdict(True, BAD_DISTANCE, f"인출 거리 {distance_m * 1000:.1f} mm, 허용 (0, {max_travel_m * 1000:.1f}] mm")
    return None


def judge_opening(moved_m: float, target_m: float, resist_n: float, stuck_force_n: float,
                  pos_tol_m: float) -> Verdict:
    """인출 중 주기적으로 호출. 목표 도달 → 끝, 저항력이 임계 초과 → DRAWER_STUCK(즉시 정지)."""
    if resist_n > stuck_force_n:
        return Verdict(True, DRAWER_STUCK, f"인출 {moved_m * 1000:.1f} mm에서 저항 {resist_n:.1f} N > {stuck_force_n:g} N")
    if moved_m >= target_m - pos_tol_m:
        return Verdict(True, None, f"인출 {moved_m * 1000:.1f} mm 도달")
    return Verdict(False, None, "인출 중")


def judge_closing(remaining_m: float, resist_n: float, close_force_n: float, pos_tol_m: float) -> Verdict:
    """닫는 중 주기적으로 호출. `remaining_m` = 닫힘 위치까지 남은 거리.
    닫힘 = 위치 도달 AND 힘 임계. 위치 전에 힘 임계 → CLOSE_NOT_CONFIRMED(튀어나온 물품·레일 걸림, 8.4 복구 절차)."""
    reached = remaining_m <= pos_tol_m
    pushed = resist_n >= close_force_n
    if reached and pushed:
        return Verdict(True, None, f"닫힘 확인 (남은 {remaining_m * 1000:.1f} mm, 저항 {resist_n:.1f} N)")
    if pushed:
        return Verdict(True, CLOSE_NOT_CONFIRMED,
                       f"닫힘 위치 {remaining_m * 1000:.1f} mm 전에 저항 {resist_n:.1f} N ≥ {close_force_n:g} N")
    return Verdict(False, None, "닫는 중")
