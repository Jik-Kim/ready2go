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
G = dict(G, pick_wall_margin_mm=G["wall_margin_mm"])   # 아래 기하 시험은 10/06~07 여유(3 mm) 기준 — 집기 판단 여유 8 mm 는 따로 시험 [10/10]
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
    assert p.shift_y_m == pytest.approx(-0.0369, abs=5e-4)
    assert p.wall_normal_y == 1.0

    assert 0.2827 - 0.011 < p.press_xy_m[1] < 0.2827 + 0.011        # 누르는 TCP 는 지우개 폭 안


def test_eraser_against_back_wall_drags_toward_handle():
    """[사용자 10/10] 안쪽(손잡이 반대) 벽에 걸려 짧은 변으로 못 잡으면 안쪽 벽 쪽으로 기울여 눌러 손잡이 쪽(x −)으로 끎."""
    p = mp.plan_drag(target=tgt(0.1887, 0.2675, math.pi / 2), size_m=ERASER, interior_m=INTERIOR, g=G, drag=DRAG)
    assert p.needed and p.error_code is None and p.axis == "x" and p.wall_normal_x == 1.0 and p.shift_x_m < 0
    assert p.press_xy_m[1] == pytest.approx(0.2675) and p.press_xy_m[0] >= 0.1887 - 1e-9   # 안쪽 벽 쪽(물체 안)에서 누름


def test_eraser_against_handle_wall_pushed_inward_only_when_allowed():
    """[사용자 10/10] 손잡이 쪽 벽: 약한 힘으로 안쪽(x +)으로 끌기가 1순위(push_inward_ok). 끄면 서랍이 닫힐 수 있어 넛지 안 함."""
    t = tgt(0.012, 0.15, math.pi / 2)
    p = mp.plan_drag(target=t, size_m=ERASER, interior_m=INTERIOR, g=G, drag=dict(DRAG, push_inward_ok=True))
    assert p.needed and p.axis == "x" and p.wall_normal_x == -1.0 and p.shift_x_m > 0
    p = mp.plan_drag(target=t, size_m=ERASER, interior_m=INTERIOR, g=G, drag=dict(DRAG, push_inward_ok=False))
    assert p.error_code == mp.NO_PUSH_ACCESS and p.axis == "x" and "닫" in p.reason


def test_bottom_drawer_deep_object_pulled_inside_reach():
    """아래 칸: 그리퍼 수직으로 닿는 깊이(reach_x_max_mm) 너머면 벽에 안 걸려도 손잡이 쪽으로 — 끈 뒤 가운데가 한계 안."""
    g = dict(G, reach_x_max_mm=129.0)
    p = mp.plan_drag(target=tgt(0.150, 0.15, 0.0), size_m=ERASER, interior_m=INTERIOR, g=g, drag=DRAG)
    assert p.needed and p.axis == "x" and p.wall_normal_x == 1.0
    assert 150.0 + p.shift_x_m * 1000.0 <= 129.0
    assert mp.wall_blocks_grasp(target=tgt(0.150, 0.15, 0.0), size_m=ERASER, interior_m=INTERIOR, g=g)   # 넛지 전 집기는 거부


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


def test_measured_eraser_10_06_round_tip_tilt_still_lands_on_eraser():
    """10/06 터치 위치(벽에 딱 붙음): 손끝이 반원이라 30° 기울여도 가장 낮은 점이 지우개 위, 41.7 mm 끌기."""
    t = tgt(0.1769, 0.2895, 0.0)
    for tilt in (0.0, 30.0):
        p = mp.plan_drag(target=t, size_m=ERASER, interior_m=INTERIOR, g=G, drag=dict(DRAG, tilt_deg=tilt, close_axis="object"))
        assert p.needed and p.shift_y_m == pytest.approx(-0.0437, abs=5e-4)
    off, depth = mp.tip_contact(math.radians(30), G)
    assert off == pytest.approx(-2.9, abs=0.05) and depth == pytest.approx(10.78, abs=0.05)
    assert mp.tip_contact(0.0, G) == pytest.approx((0.0, 10.0))


def test_square_tip_would_miss_narrow_flush_object():
    """반지름이 작으면(사각에 가까운 끝) 기울였을 때 닿는 점이 벽 반대쪽으로 멀어져 좁은 물체를 못 누름 → 거부."""
    g = dict(G, tip_radius_mm=0.0)
    g["wall_clearance_mm"] = dict(G["wall_clearance_mm"], along_mm=15.0)
    p = mp.plan_drag(target=tgt(0.1769, 0.2895, 0.0), size_m=ERASER, interior_m=INTERIOR, g=g,
                     drag=dict(DRAG, tilt_deg=30.0))
    assert p.error_code is None or p.error_code == mp.NO_PUSH_ACCESS


def test_wall_close_axis_presses_measured_eraser_over_its_middle():
    """10/06 실측 자세(닫힘 축 = 옆벽 법선, 30°): TCP 는 옆벽 경계에서 5.0 + 여유 3 mm, 지우개 폭 안. 끌 거리는 같음."""
    d = dict(DRAG, close_axis="wall", wall_tcp_min_mm=5.0, wall_press_margin_mm=3.0, tilt_deg=30.0)
    p = mp.plan_drag(target=tgt(0.1769, 0.2895, 0.0), size_m=ERASER, interior_m=INTERIOR, g=G, drag=d)
    assert p.needed and p.error_code is None and p.shift_y_m == pytest.approx(-0.0437, abs=5e-4)
    assert (INTERIOR[1] - p.press_xy_m[1]) * 1000 == pytest.approx(8.0, abs=0.05)
    assert abs(p.press_xy_m[1] - 0.2895) < 0.011 - 0.003


def test_params_use_wall_close_axis():
    assert DRAG["close_axis"] == "wall" and DRAG["tilt_deg"] == 20.0                       # 30 → 20 [사용자 10/07]
    assert DRAG["wall_tcp_min_mm"] == 3.3 and DRAG["wall_tip_below_mm"] == 11.3             # 20° 지우개 위 [실측 B 10/10 손잡이 쪽 2점, 10/07 은 9.7]


def test_wall_press_margin_zero_presses_at_measured_reach():
    """10/07: 20°, 여유 0 → 옆벽 경계에서 TCP 3.3 mm = 4번 직접교시 자리(지우개 중심 위 y 290.44), 지우개 폭 안."""
    p = mp.plan_drag(target=tgt(0.0275, 0.2904, 0.0), size_m=ERASER, interior_m=INTERIOR, g=G, drag=DRAG)
    assert (INTERIOR[1] - p.press_xy_m[1]) * 1000 == pytest.approx(3.3, abs=0.05) and p.error_code is None


def test_safe_blend_radii_keeps_margin_below_half_segment():
    """[실측 PC2 10/08] 반지름 41.724 > 제어기 max_dist 41.723 → moveb 출발 안 함. 구간 절반의 90% 이하, 마지막 0."""
    start = [375.6, -217.0, 253.8]
    pts = [[373.8, -216.4, 337.2], [366.6, 174.5, 334.9], [365.1, 174.2, 100.4]]
    r = mp.safe_blend_radii(start, pts, [50.0, 50.0, 0.0])
    half01 = math.dist(start, pts[0]) / 2.0
    assert r[0] == pytest.approx(0.9 * half01) and r[0] < half01 - 1.0
    assert r[1] == 50.0 and r[2] == 0.0
    assert mp.safe_blend_radii(start, pts[:1], [20.0]) == [0.0]


LIP_BALM = [0.0718, 0.02, 0.02]


def test_lip_balm_along_left_wall_nudged_first_then_ends_if_nudge_impossible():
    """[사용자 10/10 우선순위] 가장자리: 넛지 먼저 → 넛지를 못 하면 긴 변 양끝으로 집기(needed False)."""
    g = dict(G, max_open_mm=PRM["pick"]["max_open_width_m"] * 1000.0)
    t = tgt(0.10, 0.014, 0.0)
    assert mp.wall_blocks_grasp(target=t, size_m=LIP_BALM, interior_m=INTERIOR, g=g)            # 짧은 변은 걸림
    assert mp.long_side_ok(target=t, size_m=LIP_BALM, interior_m=INTERIOR, g=g)                  # 긴 변은 됨
    p = mp.plan_drag(target=t, size_m=LIP_BALM, interior_m=INTERIOR, g=g, drag=DRAG)
    assert p.needed and p.axis == "y" and p.shift_y_m > 0                                      # 넛지 먼저
    p = mp.plan_drag(target=t, size_m=LIP_BALM, interior_m=INTERIOR, g=g, drag=dict(DRAG, max_shift_mm=5.0))   # 넛지 못 함
    assert not p.needed and p.error_code is None and "긴 변" in p.reason
    assert not mp.long_side_ok(target=t, size_m=[0.17, 0.061, 0.0185], interior_m=INTERIOR, g=g)   # 스패너 170 mm 는 벌림 밖
    assert not mp.long_side_ok(target=t, size_m=LIP_BALM, interior_m=INTERIOR, g=G)              # 최대 벌림 모르면 안 씀


def test_eraser_crosswise_on_handle_wall_near_left_wall_dragged_sideways_then_ends():
    """[사용자 10/10 PC2] 손잡이 쪽 벽에 가로로 붙고 왼쪽 벽 가까움: 짧은 변은 손잡이 쪽 벽, 긴 변은 왼쪽 벽에 걸림
    → 안쪽(x)으로는 못 끌고(서랍 닫힘), 옆(y)으로 끌어 긴 변 양끝으로 잡게."""
    g = dict(G, max_open_mm=PRM["pick"]["max_open_width_m"] * 1000.0)
    t = tgt(0.022, 0.030, math.pi / 2)
    assert mp.wall_blocks_grasp(target=t, size_m=ERASER, interior_m=INTERIOR, g=g)
    assert not mp.long_side_ok(target=t, size_m=ERASER, interior_m=INTERIOR, g=g)
    p = mp.plan_drag(target=t, size_m=ERASER, interior_m=INTERIOR, g=g, drag=dict(DRAG, push_inward_ok=False))   # 안쪽으로 못 끌 때
    assert p.needed and p.error_code is None and p.axis == "y" and p.shift_y_m > 0          # 왼쪽 벽에서 멀어지게
    after = tgt(0.022, 0.030 + p.shift_y_m, math.pi / 2)
    assert mp.long_side_ok(target=after, size_m=ERASER, interior_m=INTERIOR, g=g)            # 끈 뒤 긴 변으로 잡힘


def test_eraser_crosswise_on_handle_wall_grabbed_by_ends_tilted():
    """[사용자 10/10 PC2 "기울여서 긴 변으로"] 손잡이 쪽 벽에 가로로 붙은 지우개: 안쪽으로 못 끌어도(서랍 닫힘) 긴 변 양끝으로 잡음.
    집기 판단 여유 8 mm 를 긴 변 판단에도 쓰면 시도도 안 함(NO_PUSH_ACCESS) → 긴 변은 기본 여유. 앞판에 몸통이 닿아 벽 쪽으로 기울임."""
    g = dict(G, max_open_mm=PRM["pick"]["max_open_width_m"] * 1000.0, pick_wall_margin_mm=PRM["gripper"]["pick_wall_margin_mm"])
    t = tgt(0.011, 0.15, math.pi / 2)
    assert mp.wall_blocks_grasp(target=t, size_m=ERASER, interior_m=INTERIOR, g=g)
    assert mp.long_side_ok(target=t, size_m=ERASER, interior_m=INTERIOR, g=g)
    p = mp.plan_drag(target=t, size_m=ERASER, interior_m=INTERIOR, g=g, drag=dict(DRAG, push_inward_ok=False))
    assert not p.needed and p.error_code is None and "긴 변" in p.reason
    assert mp.front_tilt_x_mm(target=t, size_m=ERASER, interior_m=INTERIOR, g=g) == pytest.approx(11.0)   # 물체 가운데 그대로
    tx = mp.front_tilt_x_mm(target=tgt(0.004, 0.15, math.pi / 2), size_m=ERASER, interior_m=INTERIOR, g=g)
    assert tx == pytest.approx(g["wall_clearance_mm"]["along_mm"])                                      # 벽에 더 붙었으면 손가락 자리까지 안쪽
    assert mp.front_tilt_x_mm(target=tgt(0.10, 0.15, math.pi / 2), size_m=ERASER, interior_m=INTERIOR, g=g) is None      # 가운데
    assert mp.front_tilt_x_mm(target=tgt(0.188, 0.15, math.pi / 2), size_m=ERASER, interior_m=INTERIOR, g=g) is None     # 안쪽 벽


def test_round_object_on_side_wall_not_nudged():
    """[사용자 10/10 PC2 립밤] 원통형이 옆벽에 붙으면 넛지하면 굴러감 → 넛지 없이(needed False) 긴 변 양끝 + 그 벽 쪽 기울여 집기.
    원통형 표시(round)가 없거나, 긴 변이 벽과 비스듬하거나, 긴 변 양끝이 앞뒤 벽에 걸리면 예전대로."""
    g = dict(G, max_open_mm=PRM["pick"]["max_open_width_m"] * 1000.0, round=True)
    t = tgt(0.10, 0.010, 0.0)
    assert mp.round_wall_side(target=t, size_m=LIP_BALM, interior_m=INTERIOR, g=g) == -1.0
    assert mp.round_wall_side(target=tgt(0.10, INTERIOR[1] - 0.010, 0.0), size_m=LIP_BALM, interior_m=INTERIOR, g=g) == 1.0
    p = mp.plan_drag(target=t, size_m=LIP_BALM, interior_m=INTERIOR, g=g, drag=DRAG)
    assert not p.needed and p.error_code is None and p.wall_normal_y == -1.0 and "원통형" in p.reason
    assert mp.plan_drag(target=t, size_m=LIP_BALM, interior_m=INTERIOR, g=dict(g, round=False), drag=DRAG).needed
    assert mp.round_wall_side(target=tgt(0.10, 0.010, 1.2), size_m=LIP_BALM, interior_m=INTERIOR, g=g) is None   # 비스듬
    assert mp.round_wall_side(target=tgt(0.03, 0.010, 0.0), size_m=LIP_BALM, interior_m=INTERIOR, g=g) is None   # 앞 모서리
    # 모서리 [사용자 10/10 "구석이면 세로 방향으로 넛지, 짧은 변 쪽으로 밀면 굴러감"]: 안쪽 모서리 → 서랍 x 로만, 누르는 TCP 는 옆벽 손가락 자리 밖
    back = tgt(INTERIOR[0] - 0.036, 0.010, 0.0)
    p = mp.plan_drag(target=back, size_m=LIP_BALM, interior_m=INTERIOR, g=g, drag=DRAG)
    assert p.needed and p.axis == "x" and p.shift_x_m < 0 and p.shift_y_m == 0.0 and p.wall_normal_y == -1.0
    assert p.press_xy_m[1] * 1000.0 >= G["wall_clearance_mm"]["along_mm"] + G["wall_margin_mm"] - 1e-6
    after = tgt(INTERIOR[0] - 0.036 + p.shift_x_m, 0.010, 0.0)
    assert mp.round_wall_side(target=after, size_m=LIP_BALM, interior_m=INTERIOR, g=g) == -1.0   # 끈 뒤 옆벽 기울여 집기
    p = mp.plan_drag(target=tgt(0.036, 0.010, 0.0), size_m=LIP_BALM, interior_m=INTERIOR, g=g, drag=dict(DRAG, push_inward_ok=False))
    assert p.error_code == mp.NO_PUSH_ACCESS and p.axis == "x"                                 # 손잡이 쪽 모서리: 안쪽으로 못 끎 (서랍 닫힘)
    assert mp.round_wall_side(target=tgt(0.10, 0.08, 0.0), size_m=LIP_BALM, interior_m=INTERIOR, g=g) is None    # 벽에서 멂


def test_tilt_only_for_crosswise_on_handle_wall():
    """[사용자 10/10 PC2 "대각선 절대 안 됨"] 기울여 잡기는 손잡이 쪽 벽에 가로(긴 변이 벽과 나란, tilt_align_deg 안)일 때만.
    비스듬하면 기울이지 않고 멈춤(NO_PUSH_ACCESS). 가로로 손잡이 쪽 구석이면 옆으로 넛지 먼저 → 끈 뒤 기울여 긴 변."""
    g = dict(G, max_open_mm=PRM["pick"]["max_open_width_m"] * 1000.0, pick_wall_margin_mm=PRM["gripper"]["pick_wall_margin_mm"],
             tilt_align_deg=PRM["pick"]["tilt_align_deg"])
    drag = dict(DRAG, push_inward_ok=False)
    for yaw in (0.6, -0.8):
        t = tgt(0.0308, 0.06, yaw)
        assert mp.front_tilt_x_mm(target=t, size_m=ERASER, interior_m=INTERIOR, g=g) is None
        assert mp.plan_drag(target=t, size_m=ERASER, interior_m=INTERIOR, g=g, drag=dict(drag, square_to_handle_wall=False)).error_code == mp.NO_PUSH_ACCESS
    t = tgt(0.0308, 0.06, 1.2)                                                               # 거의 가로지만 15° 밖: 긴 변은 되는데 기울이진 않음
    assert mp.front_tilt_x_mm(target=t, size_m=ERASER, interior_m=INTERIOR, g=g) is None
    corner = tgt(0.012, 0.03, math.pi / 2)
    p = mp.plan_drag(target=corner, size_m=ERASER, interior_m=INTERIOR, g=g, drag=drag)
    assert p.needed and p.axis == "y" and p.shift_y_m > 0                                    # 구석은 넛지 먼저 (옆으로)
    after = tgt(0.012, 0.03 + p.shift_y_m, math.pi / 2)
    assert mp.front_tilt_x_mm(target=after, size_m=ERASER, interior_m=INTERIOR, g=g) is not None
    assert mp.long_side_ok(target=after, size_m=ERASER, interior_m=INTERIOR, g=g)


def test_pick_margin_makes_borderline_spots_nudge():
    """[사용자 10/10 "애매한 자리는 넛지로 확실히"] 집기 판단 여유(pick_wall_margin_mm 8)면 3 mm 일 때 바로 집던 경계 자리도 넛지."""
    g8 = dict(G, pick_wall_margin_mm=PRM["gripper"]["pick_wall_margin_mm"])
    assert g8["pick_wall_margin_mm"] == 8.0
    y = None
    for k in range(400):                                                 # 여유 3 mm 로 막 집히기 시작하는 y
        t = tgt(0.10, 0.2937 - k * 0.0005, 0.0)
        if mp.wall_blocks_grasp(target=t, size_m=ERASER, interior_m=INTERIOR, g=G) is None:
            y = t["pose"]["position"][1]
            break
    assert y is not None
    t = tgt(0.10, y, 0.0)
    assert mp.wall_blocks_grasp(target=t, size_m=ERASER, interior_m=INTERIOR, g=g8)              # 8 mm 면 거부
    assert mp.plan_drag(target=t, size_m=ERASER, interior_m=INTERIOR, g=g8, drag=DRAG).needed   # → 넛지



def _ag(x, y, yaw, size=ERASER):
    g = dict(G, max_open_mm=PRM["pick"]["max_open_width_m"] * 1000.0, pick_wall_margin_mm=PRM["gripper"]["pick_wall_margin_mm"],
             tilt_align_deg=PRM["pick"]["tilt_align_deg"], front_tilt_within_mm=PRM["pick"]["front_tilt_within_mm"], axis_grasp=True)
    return mp.plan_axis_grasp(target=tgt(x, y, yaw), size_m=size, interior_m=INTERIOR, g=g, drag=DRAG), g


def test_crosswise_long_side_vertical_short_side():
    """[사용자 10/10 PC2] 세로에 가까우면 짧은 변, 가로에 가까우면 긴 변 — 손가락은 물체 각도대로. 넛지는 서랍 x·y 로만(대각선 없음)."""
    assert mp.is_crosswise(1.2) and mp.is_crosswise(-1.0102) and not mp.is_crosswise(0.6)
    ag, g = _ag(0.10, 0.15, 1.2)
    assert ag.drag is None and ag.tilt_dir is None and ag.expected_mm == pytest.approx(52.5)
    assert ag.open_mm == pytest.approx(52.5 + g["open_margin_mm"])
    p = mp.plan_drag(target=tgt(0.10, 0.15, 0.3), size_m=ERASER, interior_m=INTERIOR, g=g, drag=DRAG)
    assert not p.needed and p.error_code is None                                         # 세로 가운데 → 짧은 변 바로
    assert not mp.axis_grasp_fits([0.17, 0.061, 0.0185], g)                               # 몽키는 짧은 변


def test_crosswise_nudged_only_along_x_or_y():
    """가로 물체: 옆벽 → y 넛지, 안쪽 벽 → x(손잡이 쪽) 넛지, 손잡이 쪽 가로 → 기울여 긴 변, 손잡이 쪽 비스듬 → 멈춤 [사용자 10/10]."""
    ag, _ = _ag(0.10, INTERIOR[1] - 0.005, math.pi / 2)
    assert ag.drag.needed and ag.drag.axis == "y" and ag.drag.shift_y_m < 0 and ag.drag.shift_x_m == 0.0
    ag, _ = _ag(INTERIOR[0] - 0.012, 0.15, math.pi / 2)
    assert ag.drag.needed and ag.drag.axis == "x" and ag.drag.shift_x_m < 0 and ag.drag.shift_y_m == 0.0
    ag, _ = _ag(0.012, 0.15, -1.5647)
    assert ag.drag is None and ag.tilt_dir == (-1.0, 0.0, 0.0)
    ag, _ = _ag(0.0308, 0.06, -1.0102)                                                    # 실측 PC2 10/10 비스듬 → 손잡이 쪽 벽까지 끌어 가로로
    assert ag.drag.needed and ag.drag.axis == "x" and ag.drag.shift_x_m < 0 and ag.drag.shift_y_m == 0.0 and ag.tilt_dir is None
    assert "가로로 붙이기" in ag.drag.reason and ag.drag.wall_normal_x == -1.0
    ag, _ = _ag(0.012, 0.03, math.pi / 2)                                                 # 손잡이 쪽-왼쪽 구석: y 넛지 먼저
    assert ag.drag.needed and ag.drag.axis == "y" and ag.drag.shift_y_m > 0
    for yaw in (0.6, -1.0102, 1.2):                                                       # 어떤 경우도 대각선 넛지 없음
        for x, y in ((0.0308, 0.06), (0.012, 0.15), (0.18, 0.02)):
            p = mp.plan_drag(target=tgt(x, y, yaw), size_m=ERASER, interior_m=INTERIOR, g=_ag(x, y, yaw)[1], drag=DRAG)
            assert p.shift_x_m == 0.0 or p.shift_y_m == 0.0


def test_diagonal_near_handle_wall_pushed_flat_against_it():
    """[사용자 10/10 제안] 손잡이 쪽 벽 근처 비스듬(넛지 방향 없던 자리) → 손잡이 쪽(서랍 여는 방향, 안 끌림)으로 벽까지 끌어 눕힘.
    가로에 가까우면 가로로(가운데 = 누르는 TCP 한계), 세로에 가까우면 세로로(가운데 = 긴 변 반). 눕힌 뒤 가로는 기울여 긴 변, 세로는 짧은 변."""
    g = dict(_ag(0.1, 0.1, 0.0)[1], wall_tcp_min_mm={"x_min": 15.9})
    for yaw, end, then in ((math.radians(55), 15.9, "tilt"), (math.radians(30), 26.25, "short")):
        p = mp.plan_drag(target=tgt(0.034, 0.15, yaw), size_m=ERASER, interior_m=INTERIOR, g=g, drag=DRAG)
        assert p.needed and p.axis == "x" and p.shift_y_m == 0.0 and 34.0 + p.shift_x_m * 1000.0 == pytest.approx(end)
        flat = tgt(end / 1000.0, 0.15, math.pi / 2 if then == "tilt" else 0.0)
        if then == "tilt":
            assert mp.plan_axis_grasp(target=flat, size_m=ERASER, interior_m=INTERIOR, g=g, drag=DRAG).tilt_dir == (-1.0, 0.0, 0.0)
        else:
            assert mp.wall_blocks_grasp(target=flat, size_m=ERASER, interior_m=INTERIOR, g=g) is None
    p = mp.plan_drag(target=tgt(0.0275, 0.15, math.radians(30)), size_m=ERASER, interior_m=INTERIOR, g=g, drag=DRAG)
    assert p.needed and p.shift_x_m == pytest.approx(-DRAG.get("square_min_push_mm", 2.0) / 1000.0)   # 모서리가 이미 벽에 닿음 → 최소 2 mm 밀어 돌림


def test_handle_corner_diagonal_pushes_to_handle_wall_before_side():
    """[사용자 10/10] 손잡이 쪽 구석에 비스듬하면 손잡이 쪽 벽까지 끌어 눕히기 먼저 → 그다음 옆벽에서 가운데(y). 가로·세로 같은 순서.
    이미 가로로 누운 건(벽과 나란) 바로 y."""
    g = dict(_ag(0.1, 0.1, 0.0)[1], wall_tcp_min_mm={"x_min": 15.9, "y_min": 14.2, "y_max": 5.5})
    for yaw in (math.radians(55), math.radians(-60), math.radians(35)):
        p = mp.plan_drag(target=tgt(0.032, 0.034, yaw), size_m=ERASER, interior_m=INTERIOR, g=g, drag=DRAG)
        assert p.needed and p.axis == "x" and p.shift_x_m < 0 and "벽까지" in p.reason
    p = mp.plan_drag(target=tgt(0.013, 0.030, math.pi / 2), size_m=ERASER, interior_m=INTERIOR, g=g, drag=DRAG)
    assert p.needed and p.axis == "y" and p.shift_y_m > 0
