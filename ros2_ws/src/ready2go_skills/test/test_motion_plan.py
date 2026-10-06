"""core/motion_plan.py — 실측 그리퍼 기하·서랍 값으로 확인 (10/05~06)."""
import math
from pathlib import Path

import pytest
import yaml

from ready2go_skills.core import motion_plan as mp
from ready2go_skills.core import pose_math as pm

PKG = Path(__file__).resolve().parents[1]
PRM = yaml.safe_load((PKG / "params" / "skills.yaml").read_text(encoding="utf-8"))
G, DRAG = PRM["gripper"], PRM["drag"]
INTERIOR = [0.1997, 0.2937, 0.0681]          # config/places.yaml drawer_top
ERASER = [0.0525, 0.022, 0.0115]


def tgt(x, y, yaw):
    return {"pose": {"position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True}}


def test_interp_clamps_outside_table():
    assert mp.interp(0.0, [1, 2], [10, 20]) == 10
    assert mp.interp(1.5, [1, 2], [10, 20]) == pytest.approx(15)
    assert mp.interp(9, [1, 2], [10, 20]) == 20


def test_tip_rises_when_opened():
    assert mp.tip_below_tcp_mm(0.9, G) == pytest.approx(10.0)
    assert mp.tip_below_tcp_mm(35.0, G) == pytest.approx(2.5)


def test_wall_extent_across_vs_along():
    assert mp.wall_extent_mm(35.0, 0.0, G) == pytest.approx(39.9)          # 닫힘 축이 벽과 직각
    assert mp.wall_extent_mm(35.0, math.pi / 2, G) == pytest.approx(9.0)   # 나란히


def test_vertical_eraser_in_corner_drags_sideways_35mm():
    """세로 지우개를 서동권 쪽-오른쪽 모서리에 (시연 1차) → 서랍 y 로 가운데 쪽 약 35 mm."""
    p = mp.plan_drag(target=tgt(0.1735, 0.2827, 0.0), size_m=ERASER, interior_m=INTERIOR, g=G, drag=DRAG)
    assert p.needed and p.error_code is None
    assert p.shift_y_m == pytest.approx(-0.0349, abs=5e-4)
    assert p.wall_normal_y == 1.0
    # 누르는 점은 지우개 위(중심에서 벽 반대쪽으로 옮김, 지우개 폭 안)
    assert 0.2827 - 0.011 < p.press_xy_m[1] < 0.2827


def test_horizontal_eraser_against_back_wall_not_solved_by_sideways():
    p = mp.plan_drag(target=tgt(0.1887, 0.2675, math.pi / 2), size_m=ERASER, interior_m=INTERIOR, g=G, drag=DRAG)
    assert p.error_code == mp.NO_PUSH_ACCESS


def test_free_object_needs_no_drag():
    p = mp.plan_drag(target=tgt(0.10, 0.15, 0.3), size_m=ERASER, interior_m=INTERIOR, g=G, drag=DRAG)
    assert not p.needed and p.error_code is None


def test_gripper_posx_down_and_closing_axis():
    px = mp.gripper_posx([400, -200, 250], (1.0, 0.0, 0.0), [155.4, 179.95, 155.4])
    r = pm.rot(*px[3:])
    assert [r[i][2] for i in range(3)] == pytest.approx([0, 0, -1], abs=1e-6)
    assert abs(r[0][0]) == pytest.approx(1.0, abs=1e-6)                     # 툴 x = base ±x
    assert px[:3] == [400, -200, 250]
    assert pm.rotation_angle(pm.rot(155.4, 179.95, 155.4), r) < 1.0       # 지금 자세 그대로 (손목 안 돎)


def test_gripper_posx_tilt_puts_tip_toward_wall():
    px = mp.gripper_posx([500, -280, 240], (0.0, 1.0, 0.0), [155.4, 179.95, 155.4], tilt_toward=(1, 0, 0), tilt_deg=30)
    r = pm.rot(*px[3:])
    z = [r[i][2] for i in range(3)]
    assert z == pytest.approx([0.5, 0.0, -math.cos(math.radians(30))], abs=1e-6)
    assert abs(r[1][0]) == pytest.approx(1.0, abs=1e-6)                     # 닫힘 축은 그대로 y


def test_handle_and_travel():
    closed = [382.695, -292.476, 268.505, 90, -90, 180]
    h = mp.handle_posx(closed, (0.0, 1.0, 0.0), 0.226)
    assert h[1] == pytest.approx(-66.476)
    assert mp.travel_mm(closed, h, (0.0, 1.0, 0.0)) == pytest.approx(226.0)


def test_from_base_inverts_to_base():
    from ready2go_skills.core.pick_plan import to_base
    tf = {"translation_m": [0.23193, -0.11241, 0.19584], "quaternion_xyzw": [0.001314, -0.007931, -0.704605, 0.709555]}
    p = (0.1, 0.2, 0.01)
    assert mp.from_base(tf, to_base(tf, p)) == pytest.approx(p, abs=1e-6)


def test_measured_eraser_10_06_vertical_press_ok_but_30deg_tilt_misses():
    """10/06 터치 위치(벽에 딱 붙음): 기울이지 않으면 41.7 mm 끌기, 30° 기울이면 가장 낮은 점이 지우개 밖 → 거부."""
    t = tgt(0.1769, 0.2895, 0.0)
    p0 = mp.plan_drag(target=t, size_m=ERASER, interior_m=INTERIOR, g=G, drag=dict(DRAG, tilt_deg=0.0))
    assert p0.needed and p0.shift_y_m == pytest.approx(-0.0417, abs=5e-4)
    p30 = mp.plan_drag(target=t, size_m=ERASER, interior_m=INTERIOR, g=G, drag=dict(DRAG, tilt_deg=30.0))
    assert p30.error_code == mp.NO_PUSH_ACCESS
