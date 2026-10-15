"""배치 난제 이름 붙이기 [제안 10/15 B, 계약 ④ 승인 전 — #364].

공간 만들기 계획(core/clear_plan.plan_next)이 고른 다음 동작과 장면 관계(벽 틈·이웃·쌓임·깊이)로
practice/B/ontology/layout_cases.json 의 난제 id(case_id)와 전략(strategy)을 붙인다. 새 물리 판단은 없음 —
strategy 는 계획이 고른 동작 종류 그대로, case_id 는 이름만 (정해지지 않으면 None).
Runner 는 (error_code, strategy == "impossible") 로만 분기하고, 모르는 case_id 는 지금 동작 그대로 [C #364 의견]."""
import math
from typing import Callable, Mapping, Optional, Sequence

from ready2go_skills.core import clear_plan as clp

STRATEGY = {"pick": "direct", "unstack": "remove_top", "nudge": "nudge", "wall_nudge": "nudge", "sweep": "make_room",
            "remove": "make_room", "fail": "impossible"}
STRATEGIES = ("direct", "axis_swap", "nudge", "make_room", "remove_top", "reobserve", "impossible")
TOUCH_MM = 10.0                     # 벽에 '붙음' — hunt_cases.py 와 같은 값
NEAR_MM = 15.0                      # 이웃 '가까움'
WIDE = ("toy_wrench", "toy_hammer", "cover_plate")
ROUND = ("lip_balm",)
LEG = ("cover_plate",)


def relations(objs: Sequence[Mapping], tid: str, size_of: Callable, interior_m: Sequence[float],
              reach_x_m: Optional[float] = None) -> dict:
    """목표 하나의 관계 — layout_cases.json relations 이름으로 (벽 틈은 서랍 안쪽 기준 mm)."""
    by = {o["id"]: o for o in objs}
    t = by[tid]
    fp = clp.footprint_mm(t, size_of)
    xs, ys = [p[0] for p in fp], [p[1] for p in fp]
    ix, iy = interior_m[0] * 1000.0, interior_m[1] * 1000.0
    gaps = {"front_handle": min(xs), "back": ix - max(xs), "side_y0": min(ys), "side_y1": iy - max(ys)}
    walls = sorted(k for k, g in gaps.items() if g < TOUCH_MM)
    near = [o["id"] for o in objs if o["id"] != tid and clp.on_floor(objs, o["id"])
            and tid not in (o.get("occluded_by") or []) and o["id"] not in (t.get("occluded_by") or [])
            and clp.overlaps(t, o, size_of, NEAR_MM)]
    return {"walls": walls, "near": near, "class": t.get("class"),
            "on_top_of": not clp.on_floor(objs, tid),
            "beyond_reach": reach_x_m is not None and t["pose"]["position"][0] > reach_x_m,
            "across": abs(math.sin(t["pose"]["yaw"])) > math.sin(math.radians(45.0))}


def classify(objs: Sequence[Mapping], tid: str, action, size_of: Callable, interior_m: Sequence[float],
             reach_x_m: Optional[float] = None, can_pick: Optional[Callable] = None) -> dict:
    """{case_id, strategy} — action = clear_plan.Action (kind·target·code·reason). can_pick(id) → bool (막는 물체를 지금 집을 수 있나)."""
    kind = action.kind
    strategy = STRATEGY.get(kind, "make_room")
    rel = relations(objs, tid, size_of, interior_m, reach_x_m)
    w, cls = set(rel["walls"]), rel["class"]
    by = {o["id"]: o for o in objs}
    case = None
    if kind == "fail":
        blk = next((i for i in by if i != tid and i in (action.reason or "")), None)
        if action.code == "NO_FREE_SPACE":
            case = "no_free_space"
        elif rel["beyond_reach"]:
            case = "beyond_reach"
        elif "front_handle" in w and len(rel["near"]) + len(w) >= 3:
            case = "cluster_front_wall"
        elif "front_handle" in w and cls in ROUND:
            case = "cylinder_handle_wall"
        elif "front_handle" in w and cls in WIDE and rel["across"]:
            case = "handle_wall_wide"
        elif blk and by[blk].get("class") in LEG and not (can_pick and can_pick(blk)):
            case = "chain_blocker_plate_pinned"
    elif kind == "pick":
        case = "stacked_top" if rel["on_top_of"] else None
    elif kind == "unstack":
        case = "stacked_under" if action.target in clp.riders(objs, tid) else "chain_blocker_stacked"
    elif kind == "wall_nudge" or (kind == "nudge" and action.target == tid and w):
        case = "corner" if len(w) >= 2 else ("back_wall" if "back" in w else "wall_side_short")
    elif action.target and action.target != tid and kind in ("nudge", "wall_nudge", "sweep"):
        case = "chain_blocker_blocked"
    elif kind in ("sweep", "remove", "nudge"):
        case = "cluster_open_side"
    return {"case_id": case, "strategy": strategy}
