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


def _under(obj: Mapping, target: Mapping, size_m: Sequence[float], obj_size_m: Sequence[float], tol_mm: float) -> bool:
    """이웃이 목표 밑에 깔림: footprint 가 목표 footprint(+ tol_mm) 안에 다 들고 윗면이 목표 윗면보다 낮음 —
    가림막 밑 지우개·립밤 [P2 시연 시뮬레이션 10/10: 가림막 집기가 밑의 지우개 때문에 NEIGHBOR_TOO_CLOSE].
    손가락은 목표 바깥 둘레로 내려가므로 밑의 물체와 닿지 않음. top_z 를 모르면 깔렸다고 보지 않음(막는 쪽)."""
    top, ttop = obj.get("top_z"), target.get("top_z")
    if not (_finite(top, ttop) and top < ttop - 0.005):
        return False
    x, y, yaw = target["pose"]["position"][0] * 1000.0, target["pose"]["position"][1] * 1000.0, target["pose"]["yaw"]
    c, s = math.cos(yaw), math.sin(yaw)
    hl, hs = size_m[0] * 500.0 + tol_mm, size_m[1] * 500.0 + tol_mm
    for px, py in plp.neighbor_rect_mm(obj, obj_size_m):
        dx, dy = px - x, py - y
        if abs(dx * c + dy * s) > hl or abs(-dx * s + dy * c) > hs:
            return False
    return True


def pick_blocker(*, target: Mapping, size_m: Sequence[float], open_mm: float, objects: Sequence[Mapping],
                 size_of: Callable[[str], Optional[Sequence[float]]], default_size_m: Sequence[float],
                 finger_mm: float, margin_mm: float, support_m: float, below_tol_m: float,
                 finger_half_width_mm: Optional[float] = None, fingertip_floor_m: Optional[float] = None,
                 fingertip_clear_m: float = 0.002) -> Optional[str]:
    """집을 때 벌린 손가락 footprint 와 겹치는 이웃 id (없으면 None).
    fingertip_floor_m: 손끝이 내려가는 가장 낮은 높이(서랍 바닥 기준) — 주면 그보다 fingertip_clear_m 넘게 낮은 이웃은 안 닿으므로 무시.
    이웃 높이는 비전 top_z 와 온톨로지 높이 중 큰 값 (덮개 판 손끝 25 mm 옆 지우개·립밤 [사용자 10/12 PC2]).
    finger_half_width_mm: 손가락 반폭(닫힘 축에 수직) — 주면 손가락이 실제로 내려가는 띠(긴 변 방향으로 이 폭)만 봄.
    없으면 예전처럼 물체 길이 전체 [P2 시뮬레이션 10/10: 몽키 170 mm 끝 옆 aside 차키까지 막음]."""
    x, y = target["pose"]["position"][0] * 1000.0, target["pose"]["position"][1] * 1000.0
    yaw = target["pose"]["yaw"]
    if not _finite(x, y, yaw, open_mm, finger_mm, margin_mm, support_m, below_tol_m, *size_m[:2]):
        raise ValueError(f"옆 물체 확인 입력 비정상: {x, y, yaw, open_mm, size_m}")   # 로봇 목표로 보내지 않음
    hl, hs = plp.place_half_mm(size_m, open_mm, finger_mm, margin_mm)
    if finger_half_width_mm is not None:
        hl = min(hl, finger_half_width_mm + margin_mm)
    mine = plp.corners(x, y, yaw, hl, hs)
    for o in _others(objects, target.get("id"), support_m, below_tol_m):
        osz = size_of(o.get("class")) or default_size_m
        if _under(o, target, size_m, osz, margin_mm):
            continue
        if fingertip_floor_m is not None and _finite(o.get("top_z")) and len(osz) > 2:
            # 목표 밑에 깔린 이웃(그 이웃 occluded_by 에 목표)은 비전 윗면이 위로 번짐 → 온톨로지 높이 [사용자 10/12 PC2: 판 밑 지우개
            # top_z 23.4(실제 11.5)가 손끝 25 − 2 에 0.4 mm 걸려 NEIGHBOR_TOO_CLOSE]. 그 밖은 비전·온톨로지 중 큰 값
            covered = target.get("id") in (o.get("occluded_by") or [])
            h = float(osz[2]) if covered else max(float(o["top_z"]), float(osz[2]))
            if h <= fingertip_floor_m - fingertip_clear_m:
                continue                                     # 손끝보다 낮음 — 손가락 자리에 있어도 안 닿음
        if plp.rects_overlap(mine, plp.neighbor_rect_mm(o, osz)):
            return o["id"]
    return None


def drag_blocker(*, target: Mapping, size_m: Sequence[float], shift_y_m: float, objects: Sequence[Mapping],
                 size_of: Callable[[str], Optional[Sequence[float]]], default_size_m: Sequence[float],
                 margin_mm: float, support_m: float, below_tol_m: float, step_mm: float = 5.0,
                 shift_x_m: float = 0.0) -> Optional[str]:
    """서랍 (x, y) 로 (shift_x_m, shift_y_m) 끄는 동안 물체(+ 여유)가 지나가는 자리와 겹치는, 끄는 쪽 앞의 이웃 id (없으면 None).
    앞뒤로 끌기(shift_x_m)는 [사용자 10/10]."""
    x, y = target["pose"]["position"][0] * 1000.0, target["pose"]["position"][1] * 1000.0
    yaw, sy, sx = target["pose"]["yaw"], shift_y_m * 1000.0, shift_x_m * 1000.0
    if not _finite(x, y, yaw, sx, sy, margin_mm, support_m, below_tol_m, step_mm, *size_m[:2]) or step_mm <= 0:
        raise ValueError(f"끌기 옆 물체 확인 입력 비정상: {x, y, yaw, sx, sy, size_m}")
    half = (size_m[0] * 500.0 + margin_mm, size_m[1] * 500.0 + margin_mm)
    n = max(1, math.ceil(math.hypot(sx, sy) / step_mm))
    path = [plp.corners(x + sx * i / n, y + sy * i / n, yaw, *half) for i in range(1, n + 1)]
    for o in _others(objects, target.get("id"), support_m, below_tol_m):
        ox, oy = o["pose"]["position"][0] * 1000.0 - x, o["pose"]["position"][1] * 1000.0 - y
        if ox * sx + oy * sy <= 0:                                    # 끄는 쪽 뒤(반대편)는 멀어지므로 안 막음
            continue
        rect = plp.neighbor_rect_mm(o, size_of(o.get("class")) or default_size_m)
        if any(plp.rects_overlap(p, rect) for p in path):
            return o["id"]
    return None


def finger_spot_blocker(*, center_m: Sequence[float], push_dir: Sequence[float], target_id: Optional[str], objects: Sequence[Mapping],
                        size_of: Callable[[str], Optional[Sequence[float]]], default_size_m: Sequence[float],
                        half_along_mm: float, half_lat_mm: float, margin_mm: float) -> Optional[str]:
    """뒤에서 밀기: 닫은 손가락이 수직으로 내려갈 자리(시작 TCP, 미는 방향으로 반 half_along_mm·옆으로 반 half_lat_mm + margin)와
    겹치는 이웃 id (없으면 None). 손끝은 바닥 위 몇 mm 까지 내려가므로 높이와 상관없이 겹치면 막힘
    [사용자 10/12 PC2: 손잡이 쪽 비스듬한 지우개 바로 뒤 에어팟 — 그 위로 손가락이 내려갈 뻔함]."""
    x, y = center_m[0] * 1000.0, center_m[1] * 1000.0
    nx, ny = push_dir
    if not _finite(x, y, nx, ny, half_along_mm, half_lat_mm, margin_mm):
        raise ValueError(f"뒤에서 밀 손가락 자리 입력 비정상: {center_m, push_dir}")
    mine = plp.corners(x, y, math.atan2(ny, nx), half_along_mm + margin_mm, half_lat_mm + margin_mm)
    for o in objects:
        if o.get("id") == target_id:
            continue
        if plp.rects_overlap(mine, plp.neighbor_rect_mm(o, size_of(o.get("class")) or default_size_m)):
            return o["id"]
    return None
