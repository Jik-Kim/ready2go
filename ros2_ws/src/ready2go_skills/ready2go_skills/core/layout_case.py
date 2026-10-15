"""배치 난제 이름 붙이기 [제안 10/15 B, 계약 ④ 승인 전 — #364].

공간 만들기 계획(core/clear_plan.plan_next)이 고른 다음 동작 → strategy(동작 종류 그대로), 장면 관계(벽 틈·이웃·쌓임·깊이)
→ case_id(practice/B/ontology/layout_cases.json 의 난제 id, 모르면 None). 새 물리 판단은 없음.
Runner 는 (error_code, strategy == "impossible") 로만 분기하고, 모르는 case_id 는 지금 동작 그대로 [C #364 의견]."""
import math

from ready2go_skills.core import clear_plan as clp

STRATEGY = {"pick": "direct", "unstack": "remove_top", "nudge": "nudge", "wall_nudge": "nudge", "sweep": "make_room",
            "remove": "make_room", "fail": "impossible"}
TOUCH_MM = 10.0                     # 벽에 '붙음' — hunt_cases.py 와 같은 값
NEAR_MM = 15.0                      # 이웃 '가까움'
WIDE = ("toy_wrench", "toy_hammer", "cover_plate")


def relations(objs, tid, size_of, interior_m, reach_x_m=None) -> dict:
    """목표 하나의 관계 — 붙은 벽(front_handle·back·side_y0·side_y1), 바닥 이웃 수, 쌓임, 깊이 밖, 가로 놓임."""
    t = next(o for o in objs if o["id"] == tid)
    fp = clp.footprint_mm(t, size_of)
    xs, ys = [p[0] for p in fp], [p[1] for p in fp]
    gaps = {"front_handle": min(xs), "back": interior_m[0] * 1000.0 - max(xs),
            "side_y0": min(ys), "side_y1": interior_m[1] * 1000.0 - max(ys)}
    near = [o for o in objs if o["id"] != tid and clp.on_floor(objs, o["id"]) and clp.overlaps(t, o, size_of, NEAR_MM)
            and tid not in (o.get("occluded_by") or []) and o["id"] not in (t.get("occluded_by") or [])]
    return {"walls": {k for k, g in gaps.items() if g < TOUCH_MM}, "near": len(near),
            "on_top_of": not clp.on_floor(objs, tid),
            "beyond_reach": reach_x_m is not None and t["pose"]["position"][0] > reach_x_m,
            "across": abs(math.sin(t["pose"]["yaw"])) > math.sin(math.radians(45.0))}


def _impossible(objs, tid, action, rel, can_pick):
    w, cls = rel["walls"], next(o["class"] for o in objs if o["id"] == tid)
    if action.code == "NO_FREE_SPACE":
        return "no_free_space"
    if rel["beyond_reach"]:
        return "beyond_reach"
    if "front_handle" in w:
        if rel["near"] + len(w) >= 3:
            return "cluster_front_wall"
        if cls == "lip_balm":
            return "cylinder_handle_wall"
        if cls in WIDE and rel["across"]:
            return "handle_wall_wide"
    blk = next((o for o in objs if o["id"] != tid and o["id"] in (action.reason or "")), None)
    if blk and blk["class"] == "cover_plate" and not can_pick(blk["id"]):
        return "chain_blocker_plate_pinned"
    return None


def classify(objs, tid, action, size_of, interior_m, reach_x_m=None, can_pick=lambda i: True) -> dict:
    """action = clear_plan.Action → {case_id, strategy}. can_pick(id): 막는 물체를 지금 집을 수 있나."""
    rel = relations(objs, tid, size_of, interior_m, reach_x_m)
    kind, mover = action.kind, action.target
    if kind == "fail":
        case = _impossible(objs, tid, action, rel, can_pick)
    elif kind == "pick":
        case = "stacked_top" if rel["on_top_of"] else None
    elif kind == "unstack":
        case = "stacked_under" if mover in clp.riders(objs, tid) else "chain_blocker_stacked"
    elif mover != tid and kind != "remove":                  # 막는 물체를 넛지·밀기
        case = "chain_blocker_blocked"
    elif rel["walls"] and kind in ("nudge", "wall_nudge"):
        w = rel["walls"]
        case = "corner" if len(w) >= 2 else "back_wall" if "back" in w else "wall_side_short"
    else:
        case = "cluster_open_side"
    return {"case_id": case, "strategy": STRATEGY[kind]}
