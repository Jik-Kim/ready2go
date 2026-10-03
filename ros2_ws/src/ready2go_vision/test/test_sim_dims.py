"""sim/scripts/_dims.py — 서랍장을 씬에 만들 수 있는지 판단하는 규칙 (build_scene.py 와 verify_scene.py 가 공유). Isaac Sim 없이 검사."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sim/scripts"))
from _dims import cabinet_missing  # noqa: E402

DIM = {
    "drawer_unit": {"tiers": 2, "width_cm": 38.5, "depth_cm": 26.5, "total_height_cm": 29.5, "seat_top_vs_table_surface_cm": -0.3, "riser_cm": 0.5, "top_board_cm": 1.8,
                    "tiers_detail": {"upper": {}, "lower": {}}, "drawer_box": {"inner_width_cm": 29.5, "side_wall_cm": 1.1, "cabinet_board_cm": 1.9},
                    "handle": {"width_cm": 11, "thickness_vertical_cm": 0.7, "protrusion_cm": 1.8, "height_from_bottom_cm": {"upper": 26.4, "lower": 11.8}}},
    "drawer_top": {"front_bottom_height_above_seat_cm": 14.8, "front_panel_cm": {"width": 38.5, "thickness": 1.8, "height": 14.7}},
    "plan_view_cm": {"drawer_right_edge_to_table_right": 35.1, "drawer_left_edge_to_table_left": 46.4, "drawer_front_to_table_edge_gap": 0},
}
PLACES = {"drawer_top": {"interior_m": [0.205, 0.295, 0.07], "max_travel_m": 0.225}}


def test_complete_values_allow_cabinet():
    assert cabinet_missing(DIM, PLACES) == []


def test_null_seat_offset_is_missing_not_defaulted():
    d = copy.deepcopy(DIM); d["drawer_unit"]["seat_top_vs_table_surface_cm"] = None
    assert cabinet_missing(d, PLACES) == ["drawer_unit.seat_top_vs_table_surface_cm"]


def test_max_travel_comes_from_places_yaml_only():
    p = copy.deepcopy(PLACES); p["drawer_top"]["max_travel_m"] = None
    assert cabinet_missing(DIM, p) == ["places.yaml drawer_top.max_travel_m"]
    d = copy.deepcopy(DIM); d["drawer_top"]["max_travel_cm"] = 17   # drawer_dimensions.yaml 의 값은 더 이상 쓰지 않는다
    assert cabinet_missing(d, p) == ["places.yaml drawer_top.max_travel_m"]


def test_unsupported_tier_count_blocks_cabinet():
    d = copy.deepcopy(DIM); d["drawer_unit"]["tiers"] = 3
    missing = cabinet_missing(d, PLACES)
    assert len(missing) == 1 and "3단" in missing[0]


def test_empty_skeleton_lists_every_item():
    assert len(cabinet_missing({"drawer_unit": {}, "drawer_top": {}, "plan_view_cm": {}}, {"drawer_top": {}})) == 16
