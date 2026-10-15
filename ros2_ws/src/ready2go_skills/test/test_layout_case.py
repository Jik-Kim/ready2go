"""core/layout_case — 배치 난제 이름·전략 [제안 10/15 B, 계약 ④ 승인 전 — #364]. 로봇 없음."""
from ready2go_skills.core import clear_plan as clp
from ready2go_skills.core import layout_case as lc

SIZE = {"eraser": (0.05, 0.022, 0.012), "toy_hammer": (0.17, 0.04, 0.02), "lip_balm": (0.07, 0.018, 0.018),
        "caramel_box": (0.06, 0.04, 0.037), "cover_plate": (0.12, 0.08, 0.035), "car_key": (0.06, 0.03, 0.016)}
INTERIOR = (0.30, 0.40)


def size_of(c):
    return SIZE[c]


def obj(i, cls, x, y, yaw=0.0, occ=()):
    return {"id": i, "class": cls, "top_z": SIZE[cls][2], "occluded_by": list(occ),
            "pose": {"frame": "drawer_top", "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True}}


def cls_(objs, tid, kind, target="", code="", reason="", reach=None, can_pick=None):
    return lc.classify(objs, tid, clp.Action(kind, target or tid, reason, code=code), size_of, INTERIOR, reach, can_pick)


def test_strategy_is_plan_action_kind():
    objs = [obj("eraser#1", "eraser", 0.15, 0.2)]
    for kind, want in (("pick", "direct"), ("unstack", "remove_top"), ("nudge", "nudge"), ("wall_nudge", "nudge"),
                       ("sweep", "make_room"), ("remove", "make_room"), ("fail", "impossible")):
        assert cls_(objs, "eraser#1", kind)["strategy"] == want


def test_fail_names_front_wall_and_reach_cases():
    hammer_across = obj("toy_hammer#1", "toy_hammer", 0.022, 0.2, yaw=1.5708)   # 손잡이 쪽 벽에 가로(긴 변이 벽과 나란히)
    assert cls_([hammer_across], "toy_hammer#1", "fail")["case_id"] == "handle_wall_wide"
    lip = obj("lip_balm#1", "lip_balm", 0.012, 0.2, yaw=1.5708)
    assert cls_([lip], "lip_balm#1", "fail")["case_id"] == "cylinder_handle_wall"
    far = obj("eraser#1", "eraser", 0.20, 0.2)
    assert cls_([far], "eraser#1", "fail", reach=0.129)["case_id"] == "beyond_reach"
    assert cls_([far], "eraser#1", "fail", code="NO_FREE_SPACE")["case_id"] == "no_free_space"


def test_fail_front_wall_cluster_and_pinned_plate():
    t = obj("eraser#1", "eraser", 0.015, 0.2, yaw=1.5708)
    nbs = [obj("caramel_box#1", "caramel_box", 0.03, 0.17), obj("car_key#1", "car_key", 0.03, 0.235)]
    assert cls_([t] + nbs, "eraser#1", "fail", reason="벌린 손가락 자리에 caramel_box#1")["case_id"] == "cluster_front_wall"
    t2 = obj("eraser#1", "eraser", 0.15, 0.2)
    plate = obj("cover_plate#1", "cover_plate", 0.15, 0.27)
    got = cls_([t2, plate], "eraser#1", "fail", reason="끄는 길에 cover_plate#1", can_pick=lambda i: False)
    assert got["case_id"] == "chain_blocker_plate_pinned"
    assert cls_([t2, plate], "eraser#1", "fail", reason="끄는 길에 cover_plate#1", can_pick=lambda i: True)["case_id"] is None


def test_stack_and_chain_cases():
    base = obj("caramel_box#1", "caramel_box", 0.15, 0.2, occ=["car_key#1"])
    key = obj("car_key#1", "car_key", 0.15, 0.2)
    key["top_z"] = 0.037 + 0.016
    objs = [base, key]
    assert cls_(objs, "caramel_box#1", "unstack", target="car_key#1")["case_id"] == "stacked_under"
    t = obj("eraser#1", "eraser", 0.10, 0.1)
    assert cls_(objs + [t], "eraser#1", "unstack", target="car_key#1")["case_id"] == "chain_blocker_stacked"
    assert cls_(objs + [t], "eraser#1", "sweep", target="caramel_box#1")["case_id"] == "chain_blocker_blocked"
    assert cls_([key, base], "car_key#1", "pick")["case_id"] == "stacked_top"


def test_wall_nudge_names_wall_case():
    side = obj("eraser#1", "eraser", 0.15, 0.012)
    assert cls_([side], "eraser#1", "wall_nudge")["case_id"] == "wall_side_short"
    corner = obj("eraser#1", "eraser", 0.27, 0.012)
    assert cls_([corner], "eraser#1", "wall_nudge")["case_id"] == "corner"
    back = obj("eraser#1", "eraser", 0.27, 0.2)
    assert cls_([back], "eraser#1", "wall_nudge")["case_id"] == "back_wall"


def test_case_ids_exist_in_ontology_proposal():
    """case_id 는 layout_cases.json(#364) 의 id — 여기 쓰는 이름 목록이 바뀌면 같이 고침."""
    used = {"no_free_space", "beyond_reach", "cluster_front_wall", "cylinder_handle_wall", "handle_wall_wide",
            "chain_blocker_plate_pinned", "stacked_top", "stacked_under", "chain_blocker_stacked", "corner", "back_wall",
            "wall_side_short", "chain_blocker_blocked", "cluster_open_side"}
    import inspect
    src = inspect.getsource(lc)
    assert all(f'"{u}"' in src for u in used)
