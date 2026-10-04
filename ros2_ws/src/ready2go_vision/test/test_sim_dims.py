"""sim/scripts/_dims.py — 서랍장을 씬에 만들 수 있는지 판단하는 규칙 (build_scene.py 와 verify_scene.py 가 공유). Isaac Sim 없이 검사."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sim/scripts"))
from _dims import cabinet_missing  # noqa: E402

DIM = {
    "drawer_unit": {"tiers": 2, "width_cm": 38.5, "depth_cm": 26.5, "total_height_cm": 29.5, "seat_top_vs_table_surface_cm": -0.3, "riser_cm": 0.5, "top_board_cm": 1.8,
                    "tiers_detail": {"upper": {}, "lower": {}}, "drawer_box": {"side_wall_cm": 1.1, "cabinet_board_cm": 1.9},
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


# ---- 서랍 tf (#6 3점 터치) ----
import math  # noqa: E402

import pytest  # noqa: E402
from _dims import cabinet_pose_from_tf, drawer_pose_from_tray, drawer_tf  # noqa: E402

Q_NEG90Z = [0, 0, -math.sqrt(0.5), math.sqrt(0.5)]   # 서랍 x = base -y, 서랍 y = base +x


def _places(tf=None, at=None):
    return {"drawer_top": {"tf": {"translation_m": tf, "quaternion_xyzw": Q_NEG90Z if tf else None}, "tf_at_travel_m": at}}


def test_tf_null_means_not_measured_yet():
    assert drawer_tf(_places()) is None


def test_tf_without_travel_distance_is_an_error():
    with pytest.raises(ValueError):
        drawer_tf(_places([0.5, -0.1, 0.2], None))


def test_tf_half_filled_is_an_error():
    p = _places([0.5, -0.1, 0.2], 0.225); p["drawer_top"]["tf"]["quaternion_xyzw"] = None
    with pytest.raises(ValueError):
        drawer_tf(p)


def test_round_trip_tf_to_scene_and_back_at_full_travel():
    t, at = [0.5, -0.1, 0.2], 0.225
    in_w, in_d, y_c, z_ref = 0.295, 0.205, 0.0585, 0.1
    R, o = cabinet_pose_from_tf(t, Q_NEG90Z, at, in_w, in_d, y_c, z_ref)
    # 최대 인출: 상자가 서랍장 +y 로 at 만큼 나온 위치
    tray = [o[i] + sum(R[i][k] * v for k, v in enumerate([0.0, y_c + at, z_ref])) for i in range(3)]
    Rd, od = drawer_pose_from_tray(R, tray, in_w, in_d)
    assert od == pytest.approx(t, abs=1e-9)
    assert Rd[0][0] == pytest.approx(0, abs=1e-9) and Rd[1][0] == pytest.approx(-1)   # 서랍 x = base -y


def test_closed_position_is_origin_plus_travel_along_x():
    # 서랍 x = base -y 이므로 닫힘 원점은 열린 원점보다 base -y 쪽(안쪽)
    R, o = cabinet_pose_from_tf([0.5, -0.1, 0.2], Q_NEG90Z, 0.225, 0.295, 0.205, 0.0, 0.0)
    closed_origin_in_base = [o[i] + R[i][0] * 0.295 / -2 + R[i][1] * 0.205 / 2 for i in range(3)]
    assert closed_origin_in_base[1] == pytest.approx(-0.1 - 0.225)
