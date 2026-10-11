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
    t = obj("airpods_case#1", "airpods_case", 0.1, 0.145)
    gap = 0.0225 + 0.011 + 0.008
    objs = [t, obj("eraser#1", "eraser", 0.1, 0.145 - gap), obj("eraser#2", "eraser", 0.1, 0.145 + gap)]
    a = cp.plan_next(objs, "airpods_case#1", Oracle(), CFG)
    assert a.kind == "sweep" and a.pushed and 0 < a.back_m < a.dist_m  # 한쪽으로 밀고 일부 되돌아옴
    after = cp.apply(objs, a, CFG)
    assert cp.plan_next(after, "airpods_case#1", Oracle(), CFG).kind == "pick"


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
