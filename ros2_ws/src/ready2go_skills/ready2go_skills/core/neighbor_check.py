"""집기·끌기 전 옆 물체 확인 (ROS 비의존·pytest 대상) [사용자 10/09 — 서랍 안 랜덤 배치].

집기(`pick_object`)·끌기(`nudge_object`)는 원래 벽만 봤다 → 두 물체가 붙어 있으면 벌린 손가락이 옆 물체를 치거나,
끌다가 옆 물체를 민다. 입력 `scan`(직전 inspect_region 결과 전체, 서랍 안 놓기와 같은 형식)이 있으면 움직이기 전에
  - 집기: 목표 footprint(서랍 안 놓기와 같은 계산 — 물체 + 벌린 손가락 바깥면 + 여유)와 겹치는 이웃
  - 끌기: 끌린 물체가 지나가는 자리(끄는 쪽 앞, 시작 위치 제외)와 겹치는 이웃
이 있으면 `NEIGHBOR_TOO_CLOSE`. 목표 받침보다 낮은 이웃(top_z ≤ 받침 + `below_tol_m`)은 손가락보다 아래라 무시
(쌓인 물체를 집을 때 받침이 되는 물체). top_z 를 모르면 막는 쪽으로 본다. `scan`이 없으면 확인하지 않는다(예전과 같음).
"""
import math
from typing import Callable, Mapping, Optional, Sequence

from ready2go_skills.core import place_plan as plp

NEIGHBOR_TOO_CLOSE = "NEIGHBOR_TOO_CLOSE"


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def _below(obj: Mapping, support_m: float, below_tol_m: float) -> bool:
    top = obj.get("top_z")
    return _finite(top) and top <= support_m + below_tol_m


def _others(objects, target_id, support_m, below_tol_m):
    return [o for o in objects if o.get("id") != target_id and not _below(o, support_m, below_tol_m)]


def pick_blocker(*, target: Mapping, size_m: Sequence[float], open_mm: float, objects: Sequence[Mapping],
                 size_of: Callable[[str], Optional[Sequence[float]]], default_size_m: Sequence[float],
                 finger_mm: float, margin_mm: float, support_m: float, below_tol_m: float) -> Optional[str]:
    """집을 때 벌린 손가락 footprint 와 겹치는 이웃 id (없으면 None)."""
    x, y = target["pose"]["position"][0] * 1000.0, target["pose"]["position"][1] * 1000.0
    yaw = target["pose"]["yaw"]
    if not _finite(x, y, yaw, open_mm, finger_mm, margin_mm, support_m, below_tol_m, *size_m[:2]):
        raise ValueError(f"옆 물체 확인 입력 비정상: {x, y, yaw, open_mm, size_m}")   # 로봇 목표로 보내지 않음
    mine = plp.corners(x, y, yaw, *plp.place_half_mm(size_m, open_mm, finger_mm, margin_mm))
    for o in _others(objects, target.get("id"), support_m, below_tol_m):
        if plp.rects_overlap(mine, plp.neighbor_rect_mm(o, size_of(o.get("class")) or default_size_m)):
            return o["id"]
    return None


def drag_blocker(*, target: Mapping, size_m: Sequence[float], shift_y_m: float, objects: Sequence[Mapping],
                 size_of: Callable[[str], Optional[Sequence[float]]], default_size_m: Sequence[float],
                 margin_mm: float, support_m: float, below_tol_m: float, step_mm: float = 5.0) -> Optional[str]:
    """서랍 y 로 shift_y_m 끄는 동안 물체(+ 여유)가 지나가는 자리와 겹치는, 끄는 쪽 앞의 이웃 id (없으면 None)."""
    x, y = target["pose"]["position"][0] * 1000.0, target["pose"]["position"][1] * 1000.0
    yaw, shift = target["pose"]["yaw"], shift_y_m * 1000.0
    if not _finite(x, y, yaw, shift, margin_mm, support_m, below_tol_m, step_mm, *size_m[:2]) or step_mm <= 0:
        raise ValueError(f"끌기 옆 물체 확인 입력 비정상: {x, y, yaw, shift, size_m}")
    half = (size_m[0] * 500.0 + margin_mm, size_m[1] * 500.0 + margin_mm)
    n = max(1, math.ceil(abs(shift) / step_mm))
    path = [plp.corners(x, y + shift * i / n, yaw, *half) for i in range(1, n + 1)]
    for o in _others(objects, target.get("id"), support_m, below_tol_m):
        if (o["pose"]["position"][1] * 1000.0 - y) * shift <= 0:      # 끄는 쪽 뒤(반대편)는 멀어지므로 안 막음
            continue
        rect = plp.neighbor_rect_mm(o, size_of(o.get("class")) or default_size_m)
        if any(plp.rects_overlap(p, rect) for p in path):
            return o["id"]
    return None
