"""`drawer_control` 판단 (#13, docs/domain.md 8.4, ROS 비의존·pytest 대상).

노드는 이 함수들로 방향·거리·열기 판정을 구하고, 실제 이동·힘 읽기는 DSR 서비스로 한다.
닫기는 손잡이를 잡지 않고 45° 자세(params `drawer_open_close.close_push`)로 앞판을 밀어 닫힘 위치 도달로 판정한다(노드).
방향: 서랍 좌표계 x축은 안쪽(places.yaml 첫 부분)이라 인출 = −x. 수평 성분만 쓴다(tf 기울기 약 0.9°).
임계값·거리는 params/skills.yaml `drawer_control` [팀 확정 필요].
"""
import math
from dataclasses import dataclass
from typing import Optional, Sequence
from ready2go_skills.core.pose_math import finite as _finite

DRAWER_STUCK = "DRAWER_STUCK"
SENSOR_INVALID = "SENSOR_INVALID"   # 위치·힘 값이 NaN·inf — 판정할 수 없으니 즉시 정지 (fail-safe, #70 D 리뷰와 같은 문제)
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


@dataclass(frozen=True)
class Verdict:
    done: bool                     # 이 구간을 끝내야 함 (성공이든 실패든)
    error_code: Optional[str]      # None = 정상
    reason: str


def check_open_distance(distance_m: float, max_travel_m: float) -> Optional[Verdict]:
    """요청 인출 거리가 (0, max_travel] 안인지. 넘으면 스토퍼에 걸리므로 시작 전에 거부."""
    if not _finite(distance_m, max_travel_m):
        return Verdict(True, BAD_DISTANCE, f"인출 거리 값 없음·비정상 ({distance_m!r}, 최대 {max_travel_m!r})")
    if not (0.0 < distance_m <= max_travel_m + 1e-9):
        return Verdict(True, BAD_DISTANCE, f"인출 거리 {distance_m * 1000:.1f} mm, 허용 (0, {max_travel_m * 1000:.1f}] mm")
    return None


def judge_opening(moved_m: float, target_m: float, resist_n: float, stuck_force_n: float,
                  pos_tol_m: float) -> Verdict:
    """인출 중 주기적으로 호출. 목표 도달 → 끝, 저항력이 임계 초과 → DRAWER_STUCK(즉시 정지), 값 비정상 → SENSOR_INVALID."""
    if not _finite(moved_m, target_m, resist_n, stuck_force_n, pos_tol_m):
        return Verdict(True, SENSOR_INVALID, f"값 비정상 (이동 {moved_m!r}, 저항 {resist_n!r})")
    if resist_n > stuck_force_n:
        return Verdict(True, DRAWER_STUCK, f"인출 {moved_m * 1000:.1f} mm에서 저항 {resist_n:.1f} N > {stuck_force_n:g} N")
    if moved_m >= target_m - pos_tol_m:
        return Verdict(True, None, f"인출 {moved_m * 1000:.1f} mm 도달")
    return Verdict(False, None, "인출 중")
