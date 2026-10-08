"""Unpacking 판단 원자 동작 (ROS 비의존, 로봇 동작 없음) — #120 C 치울 순서안, #109 C 재식별 수락.

Runner 안(LOCAL)에서 처리한다. 둘 다 직전 inspect_region 결과($scan)와 치운 기록(restore_stack)만 보고 답한다.
- select_obstacle: 목표를 꺼내려면 무엇을 먼저 치울지 1개 고름. 이미 옮긴 물체는 다시 치우지 않음.
- find_moved: 치운 기록 1건(class·origin·placed)과 같은 물체를 지금 촬영 결과에서 찾음 (재식별).
판단만 하고 "집을 수 있나·놓을 수 있나"는 B 가 동작 직전에 거부한다(#120 역할 분리). 사용자 답(prefer)은
순서만 바꾸고 안전 판단을 넘지 않는다(A 제안 10/08).

치울 순서 (#120 C 회신 표, A 동의):
1. 목표 occluded_by 에 물체가 있음 → 그 물체를 덮은 물체를 따라 올라가 맨 위(occluded_by == [])부터
2. 목표 occluded_by == [] → 치울 것 없음 (target_clear)
3. 목표 occluded_by 모름(null·필드 없음) → yaw_valid 가 true 이고 필드 자체가 없으면(박스 모델) 치울 것 없음,
   아니면 A 대안: 목표 footprint 와 겹치고 top_z 가 더 높은 후보 중 가장 높은 것 (없으면 치울 것 없음)
4. 목표 못 찾음 → occluded_by == [] 후보 중 visible_area_m2 큰 것(domain.md 8.2). 가림 필드가 아예 없는 박스 모델만
   top_z 높은 것, 필드가 있는데 null(모름)이면 고르지 않음(occlusion_unknown)
재식별 (#109): 같은 class 후보가 정확히 1개이고 placed_pose 와 tol_m 안이면 found. 같은 class 가 2개 이상이면
ambiguous(첫 시연은 class 당 1개), 1개인데 tol_m 밖이면 ambiguous, 없으면 missing. 모호하면 이동을 확정하지 않는다.
tol_m 은 비전 오차 + 놓기 오차 실측 + 여유 [팀 확정 필요] — 태스크가 넘긴다.
"""
from __future__ import annotations

import math

from .interpreter import ActionResult

BAD_PARAMS = "BAD_PARAMS"               # scan·record·tol_m 형식 오류


def select_obstacle(params: dict, world: dict) -> ActionResult:
    scan, moved = params.get("scan"), params.get("moved") or []
    if not isinstance(scan, dict) or not isinstance(moved, list) or not all(isinstance(r, dict) for r in moved):
        return ActionResult(False, error_code=BAD_PARAMS)
    tol = params.get("tol_m")
    if moved and not _valid_tol(tol):       # 옮긴 기록을 대조하려면 tol_m 필수 (#176 D 리뷰: 없거나 음수·무한대면
        return ActionResult(False, error_code=BAD_PARAMS)   # 옮긴 물체를 다시 고르거나 엉뚱하게 제외함)
    seen = _objects(scan)
    excluded, held_back = [], []
    for record in moved:                    # 이미 옮긴 물체(찾음)와 확정 못 한 같은 class(모호)는 고르지 않음
        status, obj, _ = _match(record, seen, tol)
        if status == "found":
            excluded.append(obj["id"])
        elif status == "ambiguous":
            held_back += [o["id"] for o in seen if o.get("class") == record.get("class")]
    skip = set(excluded) | set(held_back)
    target = scan.get("target") if scan.get("target_found") else None
    pool = [c for c in scan.get("candidates") or [] if isinstance(c, dict) and c.get("id") not in skip]
    chosen, reason = _choose(target, pool, world)
    prefer = params.get("prefer")
    if prefer and chosen is not None:       # 사용자가 고른 class 가 같은 규칙의 후보에 있을 때만 순서를 바꿈
        options = [c for c in _choices(target, pool, world) if c.get("class") == prefer]
        if options:
            chosen, reason = options[0], "prefer"
    return ActionResult(True, {"obstacle": chosen, "reason": reason, "excluded": excluded,
                               "held_back": sorted(set(held_back))})


def find_moved(params: dict, world: dict) -> ActionResult:
    scan, record = params.get("scan"), params.get("record")
    if not isinstance(scan, dict) or not isinstance(record, dict) or not record.get("class"):
        return ActionResult(False, error_code=BAD_PARAMS)
    status, obj, distance = _match(record, _objects(scan), params.get("tol_m"))
    if status is None:
        return ActionResult(False, error_code=BAD_PARAMS)
    return ActionResult(True, {"status": status, "object": obj if status == "found" else None,
                               "distance_m": None if distance is None else round(distance, 4)})


def _objects(scan: dict) -> list[dict]:
    """촬영 결과의 물체 전체 (target 도 포함 — target 은 candidates 에서 빠져 있음, #166 D 리뷰)."""
    target = [scan["target"]] if scan.get("target_found") and isinstance(scan.get("target"), dict) else []
    return target + [c for c in scan.get("candidates") or [] if isinstance(c, dict)]


def _match(record: dict, seen: list[dict], tol) -> tuple[str | None, dict | None, float | None]:
    if not _valid_tol(tol):
        return None, None, None
    same = [o for o in seen if o.get("class") == record.get("class")]
    if not same:
        return "missing", None, None
    if len(same) > 1:
        return "ambiguous", None, None
    placed = _xy(record.get("placed"))
    here = _xy(same[0].get("pose"))
    if placed is None or here is None:
        return "ambiguous", None, None
    distance = math.dist(placed, here)
    return ("found" if distance <= tol else "ambiguous"), same[0], distance


def _valid_tol(tol) -> bool:
    """tol_m: 0보다 큰 유한한 숫자 (NaN·무한대·bool 제외)."""
    return isinstance(tol, (int, float)) and not isinstance(tol, bool) and math.isfinite(tol) and tol > 0


def _choose(target: dict | None, pool: list[dict], world: dict) -> tuple[dict | None, str]:
    options = _choices(target, pool, world)
    if options:
        return options[0], _reason(target, pool)
    if target is not None and target.get("occluded_by"):   # 덮은 물체가 후보에 없음(옮김·확정 못 함) → 진행 안 함
        return None, "occluder_unavailable"
    if target is None and pool:             # 후보는 있는데 위에 아무것도 없다고 확인된 것이 없음 → 짐작 안 함
        return None, "occlusion_unknown"
    return None, "target_clear" if target is not None else "none"


def _choices(target: dict | None, pool: list[dict], world: dict) -> list[dict]:
    """규칙대로 고를 수 있는 후보를 앞에서부터 (맨 앞 = 기본 선택)."""
    by_id = {c["id"]: c for c in pool if c.get("id")}
    if target is None:                      # 4. 목표 안 보임: 위에 얹힌 것 없는 후보, 보이는 면적 큰 것부터
        free = [c for c in pool if c.get("occluded_by") == []]
        if free:
            return sorted(free, key=lambda c: (-(c.get("visible_area_m2") or 0.0), -(c.get("top_z") or 0.0)))
        if all("occluded_by" not in c for c in pool):   # 가림 필드가 아예 없는 박스 모델만 높이 순 (domain.md 8.2)
            return sorted(pool, key=lambda c: -(c.get("top_z") or 0.0))
        return []                           # 필드가 있는데 null(모름)·덮임 → 고르지 않음 (#176 D 리뷰)
    occ = target.get("occluded_by")
    if isinstance(occ, list) and occ:       # 1. 덮은 물체를 따라 맨 위까지 — 사슬이 하나라도 끊기면 고르지 않음
        tops = _tops(occ, by_id, set())
        return sorted(tops, key=lambda c: -(c.get("top_z") or 0.0)) if tops is not None else []
    if occ == []:                           # 2. 다 보이고 위에 아무것도 없음
        return []
    if "occluded_by" not in target and (target.get("pose") or {}).get("yaw_valid") is True:   # 3. 박스 모델, 의심 없음
        return []
    base = target.get("top_z") or 0.0       # 3. A 대안: 겹치고 더 높은 것
    over = [c for c in pool if (c.get("top_z") or 0.0) > base and _overlap(target, c, world)]
    return sorted(over, key=lambda c: -(c.get("top_z") or 0.0))


def _reason(target: dict | None, pool: list[dict]) -> str:
    if target is None:
        return "largest_visible" if any(c.get("occluded_by") == [] for c in pool) else "highest"
    return "occluded_by" if target.get("occluded_by") else "overlap_higher"


def _tops(ids: list, by_id: dict, path: set) -> list[dict] | None:
    """ids 를 덮은 물체를 따라 올라가 위에 아무것도 없는(occluded_by == []) 물체들. 사슬 중간에 결과에 없는 물체
    (옮김·미검출·보류), 판정 모름(null), 고리가 하나라도 있으면 None — 아직 덮인 물체를 맨 위로 오인하지 않음
    (#176 D 리뷰 P1). 호출 쪽은 None 이면 occluder_unavailable 로 멈춤."""
    tops: list[dict] = []
    for oid in ids:
        obj = by_id.get(oid)
        if obj is None or oid in path:
            return None
        above = obj.get("occluded_by")
        if above == []:
            found = [obj]
        elif isinstance(above, list):
            found = _tops(above, by_id, path | {oid})
        else:                               # 모름(null·필드 없음)
            return None
        if found is None:
            return None
        tops += [t for t in found if t not in tops]
    return tops


def _xy(pose) -> tuple[float, float] | None:
    try:
        x, y = pose["position"][:2]
        return float(x), float(y)
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _overlap(a: dict, b: dict, world: dict) -> bool:
    """두 물체 footprint(온톨로지 size_m 긴 변·짧은 변, pose.yaw 방향)가 겹치는지 — 분리축 검사.
    치수를 모르는 물체는 겹친다고 봄(치우기 후보로 남김, 실제 집기 가능 여부는 B 가 판단)."""
    ra, rb = _rect(a, world), _rect(b, world)
    if ra is None or rb is None:
        return True
    for rect in (ra, rb):
        for k in range(2):
            p, q = rect[k], rect[(k + 1) % 4]
            axis = (q[1] - p[1], p[0] - q[0])
            pa = [axis[0] * x + axis[1] * y for x, y in ra]
            pb = [axis[0] * x + axis[1] * y for x, y in rb]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True


def _rect(obj: dict, world: dict) -> list[tuple[float, float]] | None:
    size = ((world.get("items") or {}).get(obj.get("class")) or {}).get("size_m")
    center = _xy(obj.get("pose"))
    if not size or center is None:
        return None
    yaw = float((obj.get("pose") or {}).get("yaw") or 0.0)
    hl, hw = size[0] / 2, size[1] / 2
    c, s = math.cos(yaw), math.sin(yaw)
    return [(center[0] + dx * c - dy * s, center[1] + dx * s + dy * c)
            for dx, dy in ((hl, hw), (-hl, hw), (-hl, -hw), (hl, -hw))]
