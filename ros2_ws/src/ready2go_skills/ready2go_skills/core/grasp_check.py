"""`pick_object`의 `grasp_ok` 판정과 옮기는 중 놓침 감지 (#15, ROS 비의존·pytest 대상).

온톨로지 `pick_object.verify`: `gripper_width > min_width AND grasp_detected`.
RG2는 빈 상태로 끝까지 닫아도 `grip_detected=True`가 나오므로 [실측 B 10/03, 닫힘 0.9 mm]
폭 조건 없이 `grasp_detected`만 보면 빈손을 성공으로 판정한다.

`min_width_m`·`expected_width_m`·`width_tolerance_m` 값은 노드가 `config/`에서 읽어 넘긴다 [팀 확정 필요].
TODO(B): 물품별 집는 방향 폭은 #8 실측표(온톨로지 `size_m`) 확정 후 연결.

놓침 감지(`check_hold`)는 들어 올린 뒤·옮기는 중·놓기 직전에 쓴다. 물체가 빠지면 RG2가 계속 닫혀
폭이 빈손 닫힘(0.9 mm)까지 줄어든다 [실측 B 10/03]. 처리 순서는 docs/domain.md 8.6.
"""
import math
from dataclasses import dataclass
from typing import Optional

OK = "OK"
NOT_DETECTED = "NOT_DETECTED"        # RG2가 물체를 감지하지 못함 (끝까지 열림·중간에 멈춤 없음)
EMPTY_CLOSE = "EMPTY_CLOSE"          # 감지는 됐지만 폭이 최소 폭 이하 — 빈손으로 닫힘
WIDTH_MISMATCH = "WIDTH_MISMATCH"    # 기대 폭과 다름 — 다른 물체를 집었거나 비스듬히 잡음

HELD = "HELD"                        # 잡았을 때와 같은 폭으로 계속 잡고 있음
SLIPPED = "SLIPPED"                  # 아직 잡고 있지만 폭이 변함 — 손가락 안에서 돌거나 미끄러짐 (놓을 위치·방향 오차 주의)
DROPPED = "DROPPED"                  # 폭이 최소 폭 이하로 줄어듦 — 물체가 빠짐
SENSOR_INVALID = "SENSOR_INVALID"    # 폭이 NaN·inf·숫자 아님·RG2 범위 밖 — 잡았는지 알 수 없으니 실패로 보고 멈춤 (#72 D 리뷰)

RG2_MAX_WIDTH_M = 0.110              # [문서] RG2 손가락 사이 최대 110 mm. 읽은 폭이 [0, 최대 + 여유] 밖이면 센서 이상
_WIDTH_MARGIN_M = 0.002


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def _width_ok(w) -> bool:
    return _finite(w) and -_WIDTH_MARGIN_M <= w <= RG2_MAX_WIDTH_M + _WIDTH_MARGIN_M

# 놓침을 알아챈 시점 → 원자 동작이 돌려줄 에러 코드 (docs/domain.md 8.6)
#   close: 닫은 직후(check_grasp) / lift: 안전 높이로 들어 올린 직후 → 물체는 집으려던 자리 근처
#   transport: 옮기는 중·놓기 직전 → 물체가 어디로 떨어졌는지 모름
FAILURE_CODE = {"close": "GRASP_FAILED", "lift": "GRASP_FAILED", "transport": "OBJECT_DROPPED"}


@dataclass(frozen=True)
class GraspCheck:
    ok: bool
    reason: str
    width_m: float


def check_grasp(*, width_m: float, grasp_detected: bool, min_width_m: float,
                expected_width_m: Optional[float] = None,
                width_tolerance_m: Optional[float] = None) -> GraspCheck:
    """`/gripper/state`의 `width`(m)·`grasp_detected`로 파지 성공 여부를 판정한다.

    `expected_width_m`를 주면 |width − expected| ≤ `width_tolerance_m`도 확인한다(선택).
    """
    if not _finite(min_width_m) or min_width_m <= 0:
        raise ValueError(f"min_width_m는 0보다 큰 유한한 값: {min_width_m!r}")
    if expected_width_m is not None and not _finite(expected_width_m, width_tolerance_m):
        raise ValueError(f"expected_width_m·width_tolerance_m는 유한한 값: {expected_width_m!r}, {width_tolerance_m!r}")
    if not _width_ok(width_m) or not isinstance(grasp_detected, bool):
        return GraspCheck(False, SENSOR_INVALID, width_m)
    if not grasp_detected:
        return GraspCheck(False, NOT_DETECTED, width_m)
    if width_m <= min_width_m:
        return GraspCheck(False, EMPTY_CLOSE, width_m)
    if expected_width_m is not None:
        if width_tolerance_m is None or width_tolerance_m < 0:
            raise ValueError("expected_width_m를 쓰려면 width_tolerance_m(≥ 0)가 필요함")
        if abs(width_m - expected_width_m) > width_tolerance_m:
            return GraspCheck(False, WIDTH_MISMATCH, width_m)
    return GraspCheck(True, OK, width_m)


@dataclass(frozen=True)
class HoldCheck:
    held: bool
    reason: str
    width_m: float
    change_m: float          # 잡았을 때 대비 폭 변화 (음수 = 줄어듦)


def check_hold(*, width_m: float, width_at_grasp_m: float, min_width_m: float, slip_tolerance_m: float) -> HoldCheck:
    """잡은 뒤 지금도 들고 있는지. `width_at_grasp_m` = `check_grasp`가 OK일 때의 폭.

    고무 물체는 잡는 힘에 조금 눌리므로(지우개 22 → 21.4 mm [실측 B 10/04]) `slip_tolerance_m`만큼의 변화는 HELD.
    """
    if not _finite(min_width_m, slip_tolerance_m) or min_width_m <= 0 or slip_tolerance_m < 0:
        raise ValueError(f"min_width_m > 0, slip_tolerance_m ≥ 0 인 유한한 값: {min_width_m!r}, {slip_tolerance_m!r}")
    if not (_width_ok(width_m) and _width_ok(width_at_grasp_m)):
        return HoldCheck(False, SENSOR_INVALID, width_m, math.nan)
    if width_at_grasp_m <= min_width_m:
        raise ValueError(f"width_at_grasp_m({width_at_grasp_m})가 최소 폭 이하 — 잡지 못한 상태에서 부를 수 없음")
    change = width_m - width_at_grasp_m
    if width_m <= min_width_m:
        return HoldCheck(False, DROPPED, width_m, change)
    if abs(change) > slip_tolerance_m:
        return HoldCheck(True, SLIPPED, width_m, change)
    return HoldCheck(True, HELD, width_m, change)
