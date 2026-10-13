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


def _passes_under(obj: Mapping, target: Mapping, obj_size_m: Sequence[float], under_clear_m: Optional[float],
                  under_smear_m: float, under_gap_mm: Optional[Sequence[float]],
                  width_of: Optional[Callable[[str], Optional[float]]] = None) -> bool:
    """분할 모델이 목표(다리 있는 판) 밑이라고 한 이웃이 다리 사이로 지나갈 수 있는 폭인지 (pick_blocker under_gap_mm 설명).
    폭 = 외접 박스 짧은 변, 잡는 부위 폭(width_of — item_grasp grasp_width_m, 몽키·망치 손잡이)이 있으면 그것 —
    머리는 판 밖으로 삐져나오고 손잡이가 다리 사이로 지나감 (망치 외접 75 mm > 65, 손잡이 15.5)."""
    if under_clear_m is None or not under_gap_mm or target.get("id") not in (obj.get("occluded_by") or []):
        return False
    top = obj.get("top_z")
    if not _finite(top) or len(obj_size_m) < 3 or top > max(under_clear_m, float(obj_size_m[2])) + under_smear_m:
        return False
    width = float(obj_size_m[1]) * 1000.0
    narrow = width_of(obj.get("class")) if width_of else None
    if _finite(narrow) and narrow > 0:
        width = min(width, narrow * 1000.0)
    pose = obj.get("pose") or {}
    if pose.get("yaw_valid") is True:
        rel = pose["yaw"] - target["pose"]["yaw"]                        # 이웃 긴 변과 판 긴 변 사이 각
        limit = under_gap_mm[1] if abs(math.cos(rel)) >= abs(math.sin(rel)) else under_gap_mm[0]   # 판 긴 변과 나란하면 짧은 변 쪽 다리 사이(35)
    else:
        limit = max(under_gap_mm)
    return width <= float(limit)


def pick_blocker(*, target: Mapping, size_m: Sequence[float], open_mm: float, objects: Sequence[Mapping],
                 size_of: Callable[[str], Optional[Sequence[float]]], default_size_m: Sequence[float],
                 finger_mm: float, margin_mm: float, support_m: float, below_tol_m: float,
                 finger_half_width_mm: Optional[float] = None, fingertip_floor_m: Optional[float] = None,
                 fingertip_clear_m: float = 0.002, under_clear_m: Optional[float] = None,
                 under_smear_m: float = 0.005, under_gap_mm: Optional[Sequence[float]] = None,
                 width_of: Optional[Callable[[str], Optional[float]]] = None) -> Optional[str]:
    """집을 때 벌린 손가락 footprint 와 겹치는 이웃 id (없으면 None).
    fingertip_floor_m: 손끝이 내려가는 가장 낮은 높이(서랍 바닥 기준) — 주면 그보다 fingertip_clear_m 넘게 낮은 이웃은 안 닿으므로 무시.
    이웃 높이는 비전 top_z 와 온톨로지 높이 중 큰 값 (덮개 판 손끝 25 mm 옆 지우개·립밤 [사용자 10/12 PC2]).
    under_clear_m: 목표 밑 여유 높이(덮개 판 아랫면 21 mm) — 목표 footprint 와 겹치고 온톨로지 높이가 이 이하인 이웃은 목표 밑에 있다고
    보고 온톨로지 높이로 (밑에 깔린 물체 비전 top_z 번짐, 가림 관계 null 이어도) [사용자 10/12 "커버플레이트는 겹쳐도 집을 수 있게"].
    단 관측 top_z 가 under_clear_m + under_smear_m 이하일 때만 — 그보다 높으면 판 밑일 수 없음(다른 물체 위에 쌓였거나 세워짐) → 관측 값으로
    막음 [#235 리뷰 P1: top_z 35 mm 이웃을 단품 11.5 mm 로 보고 통과시킴]. 번짐 실측 23.4·23.5·25.5 mm(지우개 11.5) [PC2 10/12].
    under_gap_mm: 목표 다리 안쪽 간격 [긴 변 방향, 짧은 변 방향] mm (덮개 판 65 × 35, #8) — 분할 모델이 목표 밑이라고 한 이웃
    (occluded_by 에 목표)이 다리 사이로 지나갈 폭이면(긴 변이 판 짧은 변 쪽이면 폭 ≤ 65, 판 긴 변 쪽이면 ≤ 35, 방향 모르면 ≤ 65)
    손가락 확인에서 뺌 — 손가락은 판 몸통(아랫면 위)을 잡고, 밑으로 지나간 물체는 판 아랫면보다 낮음. 몽키·망치처럼 판보다 길어
    양쪽으로 삐져나와도(폭은 width_of 잡는 부위 폭 — 손잡이) [사용자 10/13 "모든 물건은 넓이가 다리 사이보다 작으면 들어갈 수 있어"]. 관측 top_z 가
    max(판 밑 여유, 온톨로지 높이) + under_smear_m 을 넘으면(판 위에 얹힘 등) 빼지 않음.
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
        if _under(o, target, size_m, osz, margin_mm) or _passes_under(o, target, osz, under_clear_m, under_smear_m, under_gap_mm, width_of):
            continue
        if fingertip_floor_m is not None and _finite(o.get("top_z")) and len(osz) > 2:
            # 목표(덮개 판) 밑에 깔린 이웃은 비전 윗면이 위로 번짐 → 온톨로지 높이 [사용자 10/12 PC2: 판 밑 지우개 top_z 23.4~25.5(실제 11.5)].
            # 판 밑 여유(under_clear_m)가 있는 목표만, 관측이 그 + 번짐 범위 안일 때만. 그 밖은 비전·온톨로지 중 큰 값
            under = (under_clear_m is not None and float(osz[2]) <= under_clear_m
                     and float(o["top_z"]) <= under_clear_m + under_smear_m          # 관측이 판 밑 + 번짐 범위 안일 때만
                     and (target.get("id") in (o.get("occluded_by") or [])
                          or plp.rects_overlap(plp.corners(x, y, yaw, size_m[0] * 500.0, size_m[1] * 500.0), plp.neighbor_rect_mm(o, osz))))
            h = float(osz[2]) if under else max(float(o["top_z"]), float(osz[2]))
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
