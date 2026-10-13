"""core/clear_plan.py — 파지 공간 만들기 (쌓인 것 빈 곳에 치우기·넛지·좌우 밀기) [사용자 10/11 제안, 미연결]."""
import dataclasses

import pytest

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


def test_free_move_ignores_already_overlapping_object_behind():
    """처음부터 겹친(맞붙은) 물체에서 멀어지는 쪽은 막지 않고, 다가가는 쪽은 그대로 막음 [실측 PC2 10/13]."""
    a = obj("caramel_box#1", "caramel_box", 0.105, 0.135)
    b = obj("airpods_case#1", "airpods_case", 0.105, 0.135 + 0.0465)          # 0.5 mm 겹침 (+y 쪽)
    objs = [a, b]
    assert cp.free_move(objs, "caramel_box#1", (0.0, -1.0), 0.03, INTERIOR, SIZES.get) == pytest.approx(0.03)
    assert cp.free_move(objs, "caramel_box#1", (0.0, 1.0), 0.03, INTERIOR, SIZES.get) == 0.0
    _, done, pushed = cp.push_move(objs, "caramel_box#1", (0.0, -1.0), 0.02, INTERIOR, SIZES.get, cp.pushable)
    assert done == pytest.approx(0.02) and pushed == []                         # 뒤에 겹친 에어팟을 끌고 가지 않음


def test_ahead_cone_and_out_of_bounds_slack():
    """옆에 맞붙은 물체는 '앞'이 아님, 처음부터 경계 밖으로 그려진 물체는 그만큼 봐줌 [실측 PC2 10/13]."""
    assert cp.ahead(0.0, 40.0, (0.0, 1.0)) and not cp.ahead(-70.0, 2.0, (0.0, 1.0)) and not cp.ahead(0.0, -5.0, (0.0, 1.0))
    c = obj("caramel_box#1", "caramel_box", 0.040, 0.029, yaw=-0.25)            # 14° — 외접 박스가 y 0 벽 밖으로 약 4 mm
    assert cp.out_mm(c, SIZES.get, INTERIOR) > 3.0
    assert cp.free_move([c], "caramel_box#1", (0.0, 1.0), 0.02, INTERIOR, SIZES.get) == pytest.approx(0.02)   # 벽에서 멀어지는 쪽은 감


def test_with_slack_prefers_more_back_off_when_still_pickable():
    """밀기·넛지는 집기 검사가 딱 통과하는 거리보다 slack_mm 더 여유 있는 같은 후보 (없으면 그대로) [사용자 10/13]."""
    acts = [(0.05, cp.Action("sweep", "t", dir=(0.0, 1.0), dist_m=0.07, back_m=0.02), None),
            (0.06, cp.Action("sweep", "t", dir=(0.0, 1.0), dist_m=0.07, back_m=0.03), None),
            (0.07, cp.Action("sweep", "t", dir=(0.0, 1.0), dist_m=0.07, back_m=0.04), None)]

    class Ok:
        def pick(self, objs, tid):
            return True, "", ""
    assert cp._with_slack(acts, acts[0][1], "t", Ok(), 10.0).back_m == pytest.approx(0.03)
    assert cp._with_slack(acts, acts[0][1], "t", Ok(), 0.0).back_m == pytest.approx(0.02)
    assert cp._with_slack(acts[:1], acts[0][1], "t", Ok(), 10.0).back_m == pytest.approx(0.02)


def test_push_chain_ignores_pushed_objects_initial_overlap_behind():
    """[실측 PC2 10/13 inspect_20261013_060416_812Z] 에어팟을 +y 로 밀면 몽키가 같이 밀림 — 몽키 외접 박스(170 × 61)가 손잡이 쪽
    캐러멜과 처음부터 겹쳐도 캐러멜은 +y 쪽 뒤라 같이 밀지도 막지도 않음 (예전: 캐러멜까지 밀려다 0 mm)."""
    sizes = dict(SIZES, toy_wrench=[0.17, 0.061, 0.0185])
    objs = [obj("airpods_case#1", "airpods_case", 0.1079, 0.0219, yaw=0.0061),
            obj("caramel_box#1", "caramel_box", 0.0361, 0.0221, yaw=-0.0083),
            dict(obj("toy_wrench#1", "eraser", 0.1135, 0.0524, yaw=-0.1916), **{"class": "toy_wrench"}),
            obj("eraser#1", "eraser", 0.1732, 0.0103, yaw=0.0208)]
    assert cp.overlaps(objs[2], objs[1], sizes.get)
    _, done, pushed = cp.push_move(objs, "airpods_case#1", (0.0, 1.0), 0.06, [0.2099, 0.286, 0.0684], sizes.get, cp.pushable)
    assert done == pytest.approx(0.06) and pushed == ["toy_wrench#1"]


def test_press_point_center_only_class():
    """[실측 PC2 10/13] 더 높은 에어팟 옆 몽키: 가운데는 손가락이 에어팟에 걸림 → 예전엔 긴 변 따라 머리 쪽(윗면이 top_z 보다
    낮음)을 눌러 접촉 없음. center_only 종류는 가운데(폭 방향 비킴만)만 — 막히면 None. 에어팟에서 떨어지면 가운데 근처를 누름
    [사용자 10/13 "몽키 중앙 부분을 눌러야지"]."""
    sizes = dict(SIZES, toy_wrench=[0.17, 0.061, 0.0185])
    air = obj("airpods_case#1", "airpods_case", 0.1079, 0.0219, top=0.0229)
    w = dict(obj("w", "eraser", 0.1135, 0.0524, yaw=-0.1916, top=0.016), **{"class": "toy_wrench"})
    kw = {"finger_r_mm": 16.0, "narrow_of": lambda c: 0.0259}
    assert cp.press_point([air, w], "w", sizes.get, **kw) is not None                     # 아무 데나 → 머리 쪽
    assert cp.press_point([air, w], "w", sizes.get, center_only=("toy_wrench",), **kw) is None
    far = dict(w, pose=dict(w["pose"], position=[0.1135, 0.0574, 0.0]))                 # 5 mm 떨어지면 폭 방향으로 비켜 가운데
    p = cp.press_point([air, far], "w", sizes.get, center_only=("toy_wrench",), **kw)
    assert p is not None and abs((p[0] - 0.1135) * 0.9817 - (p[1] - 0.0574) * 0.1904) < 1e-6   # 긴 변 방향으로는 가운데
    assert cp.press_point([far], "w", sizes.get, center_only=("toy_wrench",), **kw) == pytest.approx((0.1135, 0.0574))


def test_opens_way_with_one_target_move_after_neighbor_moved():
    """[사용자 10/13 "sweep 해도 각이 안 나오면 다음 순서"] 이웃을 옮긴 뒤 목표를 바로는 못 집어도, 목표를 한 번 넛지하면 집히면
    cfg 를 줄 때만 '길이 열림' (막는 물체 치우기 → 목표 넛지·밀기)."""
    t = obj("eraser#1", "eraser", 0.10, 0.15)
    c = obj("caramel_box#1", "caramel_box", 0.10, 0.15 + 0.011 + 0.0245 + 0.010)     # +y 로 10 mm — 손가락 자리(20)에 걸림
    orc = Oracle()
    assert not orc.pick([t, c], "eraser#1")[0]
    assert not cp._opens_way([t, c], "eraser#1", orc)
    assert cp._opens_way([t, c], "eraser#1", orc, wall_steps=0, cfg=CFG)              # -y 로 넛지하면 집힘


class TiltOracle(Oracle):
    """다시 집을 때 손잡이 쪽 벽(x 작음) tilt_x_m 안이면 기울여 잡는다고 알림 (skill_server DryOracle.last_pick_tilted 흉내)."""

    def __init__(self, tilt_x_m, **kw):
        super().__init__(**kw)
        self.tilt_x_m, self.last_pick_tilted = tilt_x_m, False

    def pick(self, objs, oid):
        r = super().pick(objs, oid)
        x = next(o for o in objs if o["id"] == oid)["pose"]["position"][0]
        self.last_pick_tilted = bool(r[0]) and x < self.tilt_x_m
        return r


def test_free_pose_avoids_tilted_repick_zone_when_upright_spot_exists():
    """[트윈 재생 10/13 A] free 가 차키를 손잡이 쪽 벽 30 mm 에 둠 → 다시 집을 때 20° 기울임 → 다른 자리 복구 때 기울어진 채 놓임.
    수직으로 다시 집을 자리가 있으면 그쪽, 기울임 구역뿐이면 그래도 놓음."""
    objs = [obj("car_key#1", "car_key", 0.15, 0.15)]
    cfg = dataclasses.replace(CFG, free_try=100, allow_unpickable_place=False)   # 가짜 검사는 벽 자리 60개를 다 거부함
    first = cp.find_free_pose(objs, "car_key#1", [], Oracle(), cfg)
    tilt_x = first["position"][0] + 0.005                                  # 기울임 없을 때 처음 고르는 자리가 기울임 구역이 되게
    pose = cp.find_free_pose(objs, "car_key#1", [], TiltOracle(tilt_x), cfg)
    assert pose is not None and pose["position"][0] >= tilt_x, pose
    everywhere = cp.find_free_pose(objs, "car_key#1", [], TiltOracle(1.0), cfg)   # 전부 기울임 구역 — 놓을 수는 있음
    assert everywhere == first


def test_hole_class_is_not_pressed():
    """[사용자 10/13] 마스킹테이프는 가운데가 뚫려 누르면 손끝이 구멍으로 빠짐 → 공간 만들기에서 누를 점 없음(같이 밀리기·집기만)."""
    sizes = dict(SIZES, masking_tape=[0.0385, 0.0385, 0.0152])
    t = dict(obj("t", "eraser", 0.10, 0.15), **{"class": "masking_tape"})
    assert cp.press_point([t], "t", sizes.get, finger_r_mm=16.0) is not None
    assert cp.press_point([t], "t", sizes.get, finger_r_mm=16.0, hole=("masking_tape",)) is None


def test_front_wall_penalty_only_for_newly_touching_handle_wall():
    """[사용자 10/13 "sweep 할 때 손잡이 쪽 벽엔 최대한 붙이지 말기"] 손잡이 쪽 벽(x 0) front_keep_mm 안으로 새로 들어가는 동작만 벌점."""
    t = obj("eraser#1", "eraser", 0.045, 0.15)                                     # 손잡이 쪽 끝 x 18.75 mm
    near = [cp.moved(t, -0.015, 0.0)]                                              # 3.75 mm — 새로 붙음
    side = [cp.moved(t, 0.0, 0.02)]                                                # 옆으로 — x 그대로
    assert cp._front_cost([t], near, CFG) == pytest.approx(CFG.front_penalty_m)
    assert cp._front_cost([t], side, CFG) == 0.0
    already = obj("eraser#1", "eraser", 0.03, 0.15)                                # 이미 붙어 있던 물체를 옆으로
    assert cp._front_cost([already], [cp.moved(already, 0.0, 0.02)], CFG) == 0.0
