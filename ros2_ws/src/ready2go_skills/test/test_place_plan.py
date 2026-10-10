"""core/place_plan.py — 서랍 안 놓기 움직이기 전 확인 (#120 ②·#166)."""
import math
from pathlib import Path

import pytest
import yaml

from ready2go_skills.core import place_plan as plp

PKG = Path(__file__).resolve().parents[1]
PRM = yaml.safe_load((PKG / "params" / "skills.yaml").read_text(encoding="utf-8"))
G, PL = PRM["gripper"], PRM["place"]
INTERIOR = [0.1997, 0.2937, 0.0711]          # config/places.yaml drawer_top
LIP = [0.0718, 0.02, 0.02]                    # knowledge/world.jsonld lip_balm
SIZES = {"eraser": [0.0525, 0.022, 0.0115], "lip_balm": LIP}
OPEN = 19.5 + PL["release_extra_mm"]          # 쥔 폭 + 놓을 때 더 벌림


def pose(x, y, yaw=0.0):
    return {"frame": "drawer_top", "position": [x, y, 0.0], "yaw": yaw}


def obj(i, cls, x, y, yaw=0.0, valid=True):
    return {"id": i, "class": cls, "top_z": 0.01,
            "pose": {"frame": "drawer_top", "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": valid}}


def check(p, objects=(), held="lip_balm#1", g=G):
    return plp.check_place(pose=p, held_id=held, held_size_m=LIP, open_mm=OPEN, objects=list(objects),
                           size_of=SIZES.get, interior_m=INTERIOR, g=g, place=PL)


def test_free_spot_passes():
    assert check(pose(0.06, 0.22, 1.5707), [obj("eraser#1", "eraser", 0.1769, 0.2895)]) is None


def test_neighbor_overlap_blocks_with_its_id():
    r = check(pose(0.12, 0.15), [obj("eraser#1", "eraser", 0.12, 0.18)])
    assert r.error_code == plp.PLACE_BLOCKED and r.blocked_by == "eraser#1"


def test_held_id_is_ignored():
    """쥔 물체의 집기 전 자리(scan 에 그대로 있음)와 겹쳐도 거부하지 않음."""
    assert check(pose(0.12, 0.15), [obj("lip_balm#1", "lip_balm", 0.12, 0.15)]) is None


def test_target_checked_like_candidates():
    """scan_objects 는 target 도 이웃으로 넣음 (#166 D 리뷰 P1: candidates 에는 target 이 빠져 있음)."""
    scan = {"target_found": True, "target": obj("eraser#1", "eraser", 0.1769, 0.2895),
            "candidates": [obj("lip_balm#1", "lip_balm", 0.17, 0.25)], "visible_count": 2}
    objs, err = plp.scan_objects(scan, "drawer_top")
    assert err is None and [o["id"] for o in objs] == ["eraser#1", "lip_balm#1"]
    r = check(pose(0.17, 0.28), objs)
    assert r.error_code == plp.PLACE_BLOCKED and r.blocked_by == "eraser#1"


def test_yaw_rotates_footprint():
    """긴 변(71.8 mm)이 x 방향이면 옆(x) 이웃에 닿고, 90° 돌리면 비켜 감."""
    near = [obj("eraser#1", "eraser", 0.12 + 0.045, 0.15, math.pi / 2)]
    assert check(pose(0.12, 0.15, 0.0), near).error_code == plp.PLACE_BLOCKED
    assert check(pose(0.12, 0.15, math.pi / 2), near) is None


def test_unknown_yaw_neighbor_covers_all_directions():
    """이웃 yaw_valid 아님 → 어느 방향이든 덮게 (대각선 반). 같은 자리라도 방향을 믿으면 통과하는 거리."""
    p = pose(0.12, 0.15, math.pi / 2)
    assert check(p, [obj("eraser#1", "eraser", 0.12 + 0.050, 0.15, math.pi / 2, valid=True)]) is None
    assert check(p, [obj("eraser#1", "eraser", 0.12 + 0.050, 0.15, math.pi / 2, valid=False)]).error_code == plp.PLACE_BLOCKED


def test_unknown_class_uses_default_size():
    far = obj("x#1", "mystery", 0.12, 0.15 + 0.0409 + 0.030)   # 놓을 footprint 끝 + 30 mm: 기본 100 mm 정사각형이면 닿음, 지우개면 안 닿음
    assert check(pose(0.12, 0.15, math.pi / 2), [far]).blocked_by == "x#1"
    far["class"] = "eraser"
    assert check(pose(0.12, 0.15, math.pi / 2), [far]) is None


@pytest.mark.parametrize("x,y,yaw", [(0.10, 0.005, 0.0), (0.02, 0.15, 0.0), (0.19, 0.15, 1.5707), (0.10, 0.285, 0.0)])
def test_wall_too_close(x, y, yaw):
    r = check(pose(x, y, yaw))
    assert r.error_code == plp.WALL_TOO_CLOSE and r.blocked_by == "wall"


def test_finger_wall_clearance_like_pick():
    """footprint 는 들어가도 손가락 닫힘 축이 벽 쪽(across)이면 집기와 같은 간섭 거리 필요."""
    half = plp.place_half_mm(LIP, OPEN, G["fingertip_outer_mm"], PL["footprint_margin_mm"])
    x = half[1] + 1.0                                       # 짧은 변 쪽이 앞 벽(x=0) — footprint 는 안
    assert plp.wall_reason(x, 150.0, math.pi / 2, half, OPEN, INTERIOR, G) is not None   # across 간섭 약 38 mm
    assert plp.wall_reason(40.0, 150.0, math.pi / 2, half, OPEN, INTERIOR, G) is None


def test_side_wall_offset_widens_y_max():
    p = pose(0.10, 0.2937 - 0.034)
    assert check(p).error_code == plp.WALL_TOO_CLOSE
    assert check(p, g=dict(G, wall_offset_mm={"y_max": 7.1})) is None   # 실제 옆벽이 경계보다 바깥 [실측 B 10/07]


def test_neighbor_checked_before_wall():
    r = check(pose(0.16, 0.27), [obj("eraser#1", "eraser", 0.1769, 0.2895)])
    assert r.error_code == plp.PLACE_BLOCKED


@pytest.mark.parametrize("params,code", [
    ({}, plp.BAD_PARAMS),
    ({"pose": pose(0.1, 0.1), "slot": "aside_1"}, plp.BAD_PARAMS),
    ({"pose": dict(pose(0.1, 0.1), frame="drawer_bottom")}, plp.BAD_PARAMS),
    ({"pose": {"frame": "drawer_top", "position": [float("nan"), 0.1, 0.0], "yaw": 0.0}}, plp.BAD_PARAMS),
    ({"pose": {"frame": "drawer_top", "position": [0.1, 0.1, 0.01], "yaw": 0.0}}, plp.BAD_PARAMS),
    ({"pose": pose(0.1, 0.1, -math.pi / 2)}, plp.BAD_PARAMS),
    ({"slot": "aside_1"}, plp.PLACE_NOT_CONFIGURED),
    ({"slot": "nowhere"}, plp.PLACE_NOT_CONFIGURED),
    ({"slot": 3}, plp.BAD_PARAMS),
])
def test_resolve_pose_refusals(params, code):
    _, _, r = plp.resolve_pose(params, "drawer_top", {"aside_1": None})
    assert r.error_code == code


def test_resolve_taught_slot():
    p, slot, r = plp.resolve_pose({"slot": "aside_1"}, "drawer_top", {"aside_1": {"position": [0.05, 0.05, 0.0], "yaw": 0.0}})
    assert r is None and slot == "aside_1" and p == pose(0.05, 0.05)


@pytest.mark.parametrize("scan", [None, {"candidates": "x"}, {"target": None, "candidates": [{"id": "a"}]},
                                  {"target": None, "candidates": [dict(obj("a", "eraser", 0.1, 0.1), pose={
                                      "frame": "drawer_bottom", "position": [0.1, 0.1, 0.0], "yaw": 0.0})]}])
def test_scan_format_errors(scan):
    objs, err = plp.scan_objects(scan, "drawer_top")
    assert objs is None and err


def test_place_tcp_matches_pick_frame_conversion():
    """놓는 TCP·긴 변 각도는 집기(plan_drawer_grasp)와 같은 변환 — 같은 자리에서 집고 놓으면 같은 TCP."""
    from ready2go_skills.core import pick_plan as pp
    places = yaml.safe_load((PKG.parents[2] / "config" / "places.yaml").read_text(encoding="utf-8"))
    tf = places["drawer_top"]["tf"]
    target = {"pose": {"position": [0.1, 0.15, 0.0], "yaw": 0.3, "yaw_valid": True}}
    g = pp.plan_drawer_grasp(target=target, size_m=LIP, tf=tf, params=PRM["pick"])
    floor = pp.to_base(tf, (0.1, 0.15, 0.0))[2]
    pos, long_deg = plp.place_tcp_m(tf, pose(0.1, 0.15, 0.3), g.position_m[2] - floor)
    assert pos == pytest.approx(g.position_m, abs=1e-5) and long_deg == pytest.approx(g.long_axis_deg)


def test_fit_slot_moves_big_object_least_inside():
    """[P2 시뮬레이션 10/10] 고정 자리에 안 들어가는 큰 물체(가림막)는 자리 가운데에서 가장 적게 옮김. 다 막히면 원래 거부 그대로."""
    def check(p):
        x = p["position"][0] * 1000.0
        return None if x >= 55.0 else plp.Refusal(plp.WALL_TOO_CLOSE, "벽")
    pose = {"frame": "drawer_top", "position": [0.0514, 0.0614, 0.0], "yaw": 0.0}
    got, bad = plp.fit_slot(pose=pose, check=check, max_shift_mm=40.0)
    assert bad is None and got["position"][0] * 1000.0 == pytest.approx(55.4, abs=0.01) and got["position"][1] == pose["position"][1]
    got, bad = plp.fit_slot(pose=pose, check=lambda p: plp.Refusal(plp.WALL_TOO_CLOSE, "벽"), max_shift_mm=40.0)
    assert got == pose and bad.error_code == plp.WALL_TOO_CLOSE
    got, bad = plp.fit_slot(pose=pose, check=check, max_shift_mm=0.0)                       # 0 = 안 옮김
    assert got == pose and bad is not None


def test_bottom_drawer_has_travel_reference():
    """[P2 시뮬레이션 10/10] 아래 칸 tf_at_travel_m 이 없어 집기·넛지·서랍 안 놓기가 모두 DRAWER_NOT_AT_TRAVEL 이었음."""
    places = yaml.safe_load((Path(__file__).resolve().parents[4] / "config" / "places.yaml").read_text(encoding="utf-8"))
    for d in ("drawer_top", "drawer_bottom"):
        assert places[d]["tf_at_travel_m"] == pytest.approx(places[d]["max_travel_m"])
