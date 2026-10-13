"""core/clear_plan.py — 파지 공간 만들기 (쌓인 것 빈 곳에 치우기·넛지·좌우 밀기) [사용자 10/11 제안, 미연결]."""
from ready2go_skills.core import clear_plan as cp

INTERIOR = [0.21, 0.29, 0.07]
SIZES = {"eraser": [0.0525, 0.022, 0.0115], "caramel_box": [0.075, 0.049, 0.0185],
         "airpods_case": [0.0605, 0.045, 0.0216], "car_key": [0.0695, 0.039, 0.0158],
         "cover_plate": [0.0985, 0.0742, 0.0405]}
CFG = cp.Config(interior_m=INTERIOR, frame="drawer_top", size_of=SIZES.get)


def obj(i, cls, x, y, yaw=0.0, top=None, under=()):
    return {"id": i, "class": cls, "top_z": top if top is not None else SIZES[cls][2], "occluded_by": list(under),
            "pose": {"frame": "drawer_top", "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True}}


class Oracle:
    """가짜 사전 검사: 목표 짧은 변(y) 양쪽 clear_mm 안에 다른 바닥 물체가 있으면 거부, 벽은 wall_mm."""

    def __init__(self, clear_mm=20.0, wall_mm=15.0):
        self.clear, self.wall = clear_mm, wall_mm

    def pick(self, objs, oid):
        t = next(o for o in objs if o["id"] == oid)
        if t["occluded_by"]:
            return False, "COVERED", "위"
        if not cp.inside(t, SIZES.get, INTERIOR, self.wall):
            return False, "WALL_TOO_CLOSE", "벽"
        sx, sy = SIZES[t["class"]][:2]
        zone = dict(t, **{"class": "_zone"})                           # 짧은 변 양쪽으로 손가락 자리만큼 넓힌 사각형
        sizes = dict(SIZES, _zone=[sx, sy + 2 * self.clear / 1000.0, 0.05])
        for o in objs:
            if o["id"] == oid or not cp.on_floor(objs, o["id"]) or o["id"] in cp.riders(objs, oid) or oid in o["occluded_by"]:
                continue
            if cp.overlaps(zone, o, sizes.get):
                return False, "NEIGHBOR_TOO_CLOSE", f"손가락 자리에 {o['id']}"
        return True, "", ""

    def place(self, objs, held_id, pose):
        h = dict(next(o for o in objs if o["id"] == held_id), pose=pose)
        if not cp.inside(h, SIZES.get, INTERIOR, 5.0):
            return False, "WALL_TOO_CLOSE", "벽"
        return True, "", ""

    def wall_nudge(self, objs, oid):
        return None, "NOT_NEEDED", ""


def test_pick_when_free():
    objs = [obj("eraser#1", "eraser", 0.1, 0.15)]
    assert cp.plan_next(objs, "eraser#1", Oracle(), CFG).kind == "pick"


def test_stacked_top_goes_to_free_space_not_on_target():
    base = obj("caramel_box#1", "caramel_box", 0.1, 0.15, under=["car_key#1"])
    top = obj("car_key#1", "car_key", 0.1, 0.15, top=0.0185 + 0.0158)
    objs = [base, top]
    a = cp.plan_next(objs, "caramel_box#1", Oracle(), CFG)
    assert a.kind == "unstack" and a.target == "car_key#1"
    after = cp.apply(objs, a, CFG)
    key = next(o for o in after if o["id"] == "car_key#1")
    assert key["occluded_by"] == [] and abs(key["top_z"] - 0.0158) < 1e-6
    assert not cp.overlaps(key, base, SIZES.get, 20.0)             # 목표 둘레는 비워 둠
    assert next(o for o in after if o["id"] == "caramel_box#1")["occluded_by"] == []
    assert cp.plan_next(after, "caramel_box#1", Oracle(), CFG).kind == "pick"


def test_nudge_toward_empty_side():
    t = obj("airpods_case#1", "airpods_case", 0.1, 0.15)
    right = obj("caramel_box#1", "caramel_box", 0.1, 0.15 - 0.0225 - 0.0245 - 0.008)    # 한쪽(−y)에 붙은 물체
    objs = [t, right]
    a = cp.plan_next(objs, "airpods_case#1", Oracle(), CFG)
    assert a.kind == "nudge" and a.dir == (0.0, 1.0)                   # 빈 쪽(+y)으로
    assert cp.plan_next(cp.apply(objs, a, CFG), "airpods_case#1", Oracle(), CFG).kind == "pick"


def test_sweep_when_both_sides_blocked():
    """remove_first 끔(밀기를 치우기보다 먼저): 사방이 막히면 한쪽으로 쭉 밀고 일부 되돌아옴 [사용자 10/11]."""
    import dataclasses
    cfg = dataclasses.replace(CFG, remove_first=False)
    t = obj("airpods_case#1", "airpods_case", 0.1, 0.145)
    gap = 0.0225 + 0.011 + 0.008
    objs = [t, obj("eraser#1", "eraser", 0.1, 0.145 - gap), obj("eraser#2", "eraser", 0.1, 0.145 + gap)]
    a = cp.plan_next(objs, "airpods_case#1", Oracle(), cfg)
    assert a.kind == "sweep" and a.pushed and 0 < a.back_m < a.dist_m  # 한쪽으로 밀고 일부 되돌아옴
    after = cp.apply(objs, a, cfg)
    assert cp.plan_next(after, "airpods_case#1", Oracle(), cfg).kind == "pick"


def test_remove_first_moves_blockers_without_pushing_chain():
    """[사용자 10/12] 목표 말고는 다 방해물: 기본(remove_first)은 옆 물체를 같이 미는 밀기 대신 막는 물체를 먼저 —
    집을 수 있으면 집어 빈 자리로, 못 집으면 그 물체만 다른 것을 안 건드리고 넛지. 몇 단계 안에 목표를 집음."""
    t = obj("airpods_case#1", "airpods_case", 0.1, 0.145)
    gap = 0.0225 + 0.011 + 0.008
    objs = [t, obj("eraser#1", "eraser", 0.1, 0.145 - gap), obj("eraser#2", "eraser", 0.1, 0.145 + gap)]
    kinds = []
    for _ in range(4):
        a = cp.plan_next(objs, "airpods_case#1", Oracle(), CFG)
        kinds.append((a.kind, a.target))
        if a.kind in ("pick", "fail"):
            break
        assert not a.pushed                                            # 줄줄이 밀기 없음
        assert a.target != "airpods_case#1"                             # 목표는 안 건드리고 방해물만
        objs = cp.apply(objs, a, CFG)
    assert kinds[-1] == ("pick", "airpods_case#1") and len(kinds) >= 2


def test_push_stops_at_wall_and_unpushable():
    t = obj("eraser#1", "eraser", 0.1, 0.1)
    cover = obj("cover_plate#1", "cover_plate", 0.1, 0.1 + 0.011 + 0.0371 + 0.005)
    objs, done, pushed = cp.push_move([t, cover], "eraser#1", (0.0, 1.0), 0.05, INTERIOR, SIZES.get, cp.pushable)
    assert pushed == [] and done < 0.006                               # 덮개 판은 안 밂
    objs, done, _ = cp.push_move([t], "eraser#1", (0.0, -1.0), 0.2, INTERIOR, SIZES.get, cp.pushable)
    assert abs(done - (0.1 - 0.011)) < 0.0015                          # 벽까지만


def test_rider_passes_over_base_without_collision():
    base = obj("caramel_box#1", "caramel_box", 0.1, 0.15, under=["eraser#1"])
    top = obj("eraser#1", "eraser", 0.1, 0.15, top=0.0185 + 0.0115)
    other = obj("car_key#1", "car_key", 0.1, 0.22)
    assert not cp.collide(base, top, SIZES.get)
    lifted = obj("x", "eraser", 0.1, 0.22, top=0.05)                   # 높이가 안 겹치면 안 부딪힘
    assert not cp.collide(lifted, other, SIZES.get)
    assert cp.riders([base, top, other], "caramel_box#1") == {"eraser#1"}


def test_as_pose_yaw_stays_in_range():
    o = obj("e", "eraser", 0.05, 0.05, yaw=1.5707963)
    assert cp.as_pose(o)["yaw"] <= 1.5707963267948966


def test_relocated_rider_height_from_ontology_not_smeared_vision_top_z():
    """[A·PM #226 리뷰] 쌓인 물체 비전 top_z 는 마스크 번짐으로 틀림(캐러멜 54.6 vs 37 mm) → 바닥에 내린 뒤 높이는 온톨로지."""
    base = obj("caramel_box#1", "caramel_box", 0.1, 0.15, top=0.0546, under=["car_key#1"])
    key = obj("car_key#1", "car_key", 0.1, 0.15, top=0.0700)
    after = cp._relocated([base, key], "car_key#1", {"frame": "drawer_top", "position": [0.05, 0.05, 0.0], "yaw": 0.0}, SIZES.get)
    k = next(o for o in after if o["id"] == "car_key#1")
    assert k["top_z"] == SIZES["car_key"][2] and next(o for o in after if o["id"] == "caramel_box#1")["occluded_by"] == []


class NoRoomOracle(Oracle):
    """놓을 빈 자리가 하나도 없음 (aside·free 다 막힘). 집기는 밑에 깔린 받침을 이웃으로 안 봄 (서버 집기와 같음)."""

    def pick(self, objs, oid):
        under = {o["id"] for o in cp.below(objs, oid)}
        return super().pick([o for o in objs if o["id"] not in under], oid)

    def place(self, objs, held_id, pose):
        return False, "PLACE_BLOCKED", "자리 없음"


def _key_on_caramel(x=0.1, y=0.15):
    base = obj("caramel_box#1", "caramel_box", x, y, under=["car_key#1"])
    top = obj("car_key#1", "car_key", x, y, top=0.0185 + 0.0158)
    return [base, top]


def test_no_free_space_topples_top_off_its_base():
    """[사용자 10/13] 위 물체를 놓을 데가 없으면 포기하지 않고 윗면을 눌러 받침 밖 바닥으로 끌어 떨어뜨림 → 다시 보고 집기."""
    objs = _key_on_caramel()
    a = cp.plan_next(objs, "caramel_box#1", NoRoomOracle(), CFG)
    assert a.kind == "topple" and a.target == "car_key#1", a
    assert 0.0 < a.dist_m <= CFG.max_shift_m and a.extra["press_xy_m"]
    after = cp.apply(objs, a, CFG)
    key = next(o for o in after if o["id"] == "car_key#1")
    base = next(o for o in after if o["id"] == "caramel_box#1")
    assert not cp.overlaps(key, base, SIZES.get) and cp.inside(key, SIZES.get, INTERIOR)   # 받침 밖 바닥, 서랍 안
    assert key["top_z"] == SIZES["car_key"][2] and base["occluded_by"] == [] and cp.below(after, "car_key#1") == []


def test_topple_prefers_side_that_keeps_target_graspable():
    """떨어뜨릴 쪽이 여럿이면 찾는 목표(받침)의 손가락 자리를 막지 않는 쪽 먼저 — 더 멀어도. 다음 계획은 바로 집기."""
    objs = _key_on_caramel(0.13, 0.15)
    a = cp.plan_next(objs, "caramel_box#1", NoRoomOracle(), CFG)
    assert a.kind == "topple" and a.dir == (-1.0, 0.0), a                     # ±y 는 더 짧지만 캐러멜 짧은 변 손가락 자리에 떨어짐
    assert cp.plan_next(cp.apply(objs, a, CFG), "caramel_box#1", NoRoomOracle(), CFG).kind == "pick"


def test_topple_three_stack_lands_on_floor_clear_of_all_layers():
    """세 개 쌓임(에어팟 케이스 ← 캐러멜 ← 차키): 맨 위 차키를 밑 두 층 모두 밖으로 — 가운데 캐러멜 위에 다시 얹히지 않게."""
    air = obj("airpods_case#1", "airpods_case", 0.1, 0.15, under=["caramel_box#1"])
    car = obj("caramel_box#1", "caramel_box", 0.1, 0.15, top=0.0216 + 0.0185, under=["car_key#1"])
    key = obj("car_key#1", "car_key", 0.1, 0.15, top=0.0216 + 0.0185 + 0.0158)
    objs = [air, car, key]
    a = cp.plan_next(objs, "airpods_case#1", NoRoomOracle(), CFG)
    assert a.kind == "topple" and a.target == "car_key#1"
    landed = next(o for o in cp.apply(objs, a, CFG) if o["id"] == "car_key#1")
    assert not any(cp.overlaps(landed, o, SIZES.get) for o in (air, car))
    assert {b["id"] for b in cp.below(objs, "car_key#1")} == {"airpods_case#1", "caramel_box#1"}


def test_topple_avoids_neighbors_and_walls_or_gives_up():
    """떨어질 자리에 다른 물체가 있는 쪽은 안 고름. 서랍이 꽉 차 사방이 막히면 그대로 실패 — 움직이지 않음."""
    objs = _key_on_caramel()
    first = cp.topple_move(objs, "car_key#1", CFG)
    p = first.to_pose["position"]
    blocker = obj("eraser#1", "eraser", p[0], p[1])                           # 처음 고른 자리에 지우개
    second = cp.topple_move(objs + [blocker], "car_key#1", CFG)
    assert second is not None and second.dir != first.dir
    tight = cp.Config(interior_m=[0.08, 0.055, 0.07], frame="drawer_top", size_of=SIZES.get)
    objs_t = _key_on_caramel(0.04, 0.0275)
    assert cp.topple_move(objs_t, "car_key#1", tight) is None
    assert cp.plan_next(objs_t, "caramel_box#1", NoRoomOracle(), tight).kind == "fail"


def test_topple_needs_top_object_on_a_base():
    """바닥 물체·위에 뭐가 얹힌 물체는 무너뜨리기 대상이 아님."""
    objs = _key_on_caramel()
    assert cp.topple_move(objs, "caramel_box#1", CFG) is None
    assert cp.topple_move([obj("eraser#1", "eraser", 0.1, 0.15)], "eraser#1", CFG) is None
