"""`pick_object`의 `grasp_ok` 판정 (#15, ROS 비의존·pytest 대상).

온톨로지 `pick_object.verify`: `gripper_width > min_width AND grasp_detected`.
RG2는 빈 상태로 끝까지 닫아도 `grip_detected=True`가 나오므로 [실측 B 10/03, 닫힘 0.9 mm]
폭 조건 없이 `grasp_detected`만 보면 빈손을 성공으로 판정한다.

`min_width_m`·`expected_width_m`·`width_tolerance_m` 값은 노드가 `config/`에서 읽어 넘긴다 [팀 확정 필요].
TODO(B): 물품별 집는 방향 폭은 #8 실측표(온톨로지 `size_m`) 확정 후 연결.
"""
from dataclasses import dataclass
from typing import Optional

OK = "OK"
NOT_DETECTED = "NOT_DETECTED"        # RG2가 물체를 감지하지 못함 (끝까지 열림·중간에 멈춤 없음)
EMPTY_CLOSE = "EMPTY_CLOSE"          # 감지는 됐지만 폭이 최소 폭 이하 — 빈손으로 닫힘
WIDTH_MISMATCH = "WIDTH_MISMATCH"    # 기대 폭과 다름 — 다른 물체를 집었거나 비스듬히 잡음


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
    if min_width_m <= 0:
        raise ValueError(f"min_width_m는 0보다 커야 함: {min_width_m}")
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
