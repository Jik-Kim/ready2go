import math
from pathlib import Path

import pytest
import yaml

from ready2go_skills.core import pick_plan as pp

ROOT = Path(__file__).resolve().parents[4]
PLACES = yaml.safe_load((ROOT / "config/places.yaml").read_text(encoding="utf-8"))
P = yaml.safe_load((ROOT / "ros2_ws/src/ready2go_skills/params/skills.yaml").read_text(encoding="utf-8"))["pick"]
TF = PLACES["drawer_top"]["tf"]
ERASER = [0.0525, 0.022, 0.0115]          # 온톨로지 size_m [긴 변, 짧은 변, 높이] (#8)


def _target(x=0.10, y=0.15, yaw=0.0):
    return {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
            "pose": {"frame": "drawer_top", "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True}}


def test_origin_maps_to_translation():
    assert pp.to_base(TF, (0, 0, 0)) == pytest.approx(tuple(TF["translation_m"]))


def test_drawer_x_axis_is_base_minus_y():
    assert pp.frame_yaw_deg(TF) == pytest.approx(-90.0, abs=1.0)        # places.yaml 주석: x축 ≈ base −y


def test_eraser_plan_matches_measured_grasp():
    g = pp.plan_drawer_grasp(target=_target(), size_m=ERASER, tf=TF, params=P)
    floor = pp.to_base(TF, (0.10, 0.15, 0.0))
    assert g.position_m[2] - floor[2] == pytest.approx(0.0115, abs=0.0005)   # 바닥 위 10.0~11.4 mm에서 성공 [실측]
    assert g.open_width_m == pytest.approx(0.035)                           # 실측 벌림 35 mm
    assert g.expected_width_m == pytest.approx(0.022)


def test_thin_object_never_below_min_height():
    g = pp.plan_drawer_grasp(target=_target(), size_m=[0.05, 0.02, 0.004], tf=TF, params=P)
    floor = pp.to_base(TF, (0.10, 0.15, 0.0))
    assert g.position_m[2] - floor[2] == pytest.approx(P["min_tcp_above_floor_m"], abs=1e-4)


@pytest.mark.parametrize("yaw_deg", [0.0, 30.0, -60.0, 90.0])
def test_long_axis_in_base_and_range(yaw_deg):
    g = pp.plan_drawer_grasp(target=_target(yaw=math.radians(yaw_deg)), size_m=ERASER, tf=TF, params=P)
    assert -90.0 < g.long_axis_deg <= 90.0
    diff = (g.long_axis_deg - (pp.frame_yaw_deg(TF) + yaw_deg)) % 180.0
    assert min(diff, 180.0 - diff) == pytest.approx(0.0, abs=1e-6)       # 같은 직선


def test_too_wide_or_bad_size_rejected():
    with pytest.raises(ValueError):
        pp.plan_drawer_grasp(target=_target(), size_m=[0.12, 0.095, 0.02], tf=TF, params=P)   # 95 + 13 > 100 mm
    with pytest.raises(ValueError):
        pp.plan_drawer_grasp(target=_target(), size_m=[0.022, 0.0525, 0.0115], tf=TF, params=P)  # 순서 뒤바뀜


def test_wrap_line_deg():
    assert pp.wrap_line_deg(-90.0) == 90.0 and pp.wrap_line_deg(270.0) == 90.0 and pp.wrap_line_deg(100.0) == pytest.approx(-80.0)


def test_tray_slots_split_bottom_evenly():
    # 실측 트레이 바닥 [A 10/04, #6]. staging_tray 는 #6 확정(서랍 안에서 옆으로 치우기)으로 쓰지 않아 값은 places.yaml 에 두지 않음
    c = pp.slot_centers([0.166, 0.1165], 3, inset_m=(0.0055, 0.00675))   # 테두리 투영 원점이면 바닥 모서리까지 (#6 PM)
    assert len(c) == 3
    assert [round(p[0], 4) for p in c] == [round(0.0055 + 0.166 * k / 6, 4) for k in (1, 3, 5)]
    assert all(p[1] == pytest.approx(0.00675 + 0.1165 / 2) for p in c)


@pytest.mark.parametrize("x,yaw", [(float("nan"), 0.0), (0.1, float("inf")), (True, 0.0)])
def test_non_finite_target_rejected(x, yaw):
    with pytest.raises(ValueError):
        pp.plan_drawer_grasp(target=_target(x=x, yaw=yaw), size_m=ERASER, tf=TF, params=P)


# ---- tf·파라미터·결과도 fail-closed (#71 D 리뷰)
NAN = float("nan")


@pytest.mark.parametrize("key,val", [("tcp_above_top_m", NAN), ("open_margin_m", NAN), ("min_tcp_above_floor_m", 0.0),
                                     ("max_open_width_m", 0.5), ("open_margin_m", -0.01), ("tcp_above_top_m", None)])
def test_bad_pick_params_rejected(key, val):
    with pytest.raises(ValueError):
        pp.plan_drawer_grasp(target=_target(), size_m=ERASER, tf=TF, params={**P, key: val})


@pytest.mark.parametrize("tf", [
    {**TF, "translation_m": [NAN, 0.0, 0.2]},
    {**TF, "translation_m": [0.2, 0.0]},
    {**TF, "quaternion_xyzw": [0.0, 0.0, 0.0, 2.0]},     # 길이 1 아님
    {**TF, "quaternion_xyzw": None},
])
def test_bad_tf_rejected(tf):
    with pytest.raises(ValueError):
        pp.plan_drawer_grasp(target=_target(), size_m=ERASER, tf=tf, params=P)


@pytest.mark.parametrize("size", [[0.05, 0.02, -0.01], [0.05, 0.0, 0.01], [0.05, 0.02, NAN]])
def test_bad_size_rejected(size):
    with pytest.raises(ValueError):
        pp.plan_drawer_grasp(target=_target(), size_m=size, tf=TF, params=P)


@pytest.mark.parametrize("args", [([0.166, NAN], 3), ([0.166, 0.1165], 0), ([0.166, 0.1165], 2.5), ([-0.1, 0.1], 3)])
def test_bad_tray_rejected(args):
    with pytest.raises(ValueError):
        pp.slot_centers(*args)
