import math

import pytest

from ready2go_skills.core import pose_math as pm

POSES = [
    [382.695, -292.476, 268.505, 89.981, -89.969, 179.943],     # 손잡이 파지 (그리퍼 수평 -y) [실측 10/04]
    [389.641, -147.742, 304.826, 111.881, -121.783, 158.197],   # 비스듬한 자세 [실측 10/04]
    [424.181, -294.601, 363.507, 144.131, 179.995, 144.131],    # 수직 아래 근처 (b ≈ 180) [실측 10/04]
    [300.0, 50.0, 300.0, 10.0, 60.0, 30.0],
    [0.0, 0.0, 0.0, 30.0, 0.0, 40.0],                           # b = 0 특이 표현
]


def _close(m1, m2, tol=1e-9):
    return all(abs(m1[i][j] - m2[i][j]) < tol for i in range(3) for j in range(3))


@pytest.mark.parametrize("pose", POSES)
def test_zyz_near_roundtrip_same_rotation(pose):
    back = pm.zyz_near(pm.rot(*pose[3:]), pose[3:])
    assert _close(pm.rot(*back), pm.rot(*pose[3:]))
    assert all(abs(v) <= 180.0 for v in back)


def test_step_target_translation_only_changes_one_axis():
    p = POSES[0]
    assert pm.step_target(p, 1, -5.0) == [p[0], p[1] - 5.0] + p[2:]


@pytest.mark.parametrize("idx,axis", [(3, "x"), (4, "y"), (5, "z")])
def test_step_target_rotates_about_base_axis_keeping_tcp(idx, axis):
    p = POSES[1]
    t = pm.step_target(p, idx, 7.0)
    assert t[:3] == p[:3]
    assert _close(pm.rot(*t[3:]), pm.matmul(pm.base_rot(axis, 7.0), pm.rot(*p[3:])))


@pytest.mark.parametrize("pose", POSES)
def test_align_z_points_down_and_y_points_minus_y(pose):
    tz = pm.align_target(pose, "z")
    ty = pm.align_target(pose, "y")
    assert tz[:3] == pose[:3] and ty[:3] == pose[:3]
    assert max(abs(a - b) for a, b in zip(pm.col(pm.rot(*tz[3:]), 2), [0, 0, -1])) < 1e-9
    assert max(abs(a - b) for a, b in zip(pm.col(pm.rot(*ty[3:]), 2), [0, -1, 0])) < 1e-9


def test_align_x_points_outward_from_body():
    p = POSES[0]                                         # x = +382 → +x 쪽이 바깥
    zx = pm.col(pm.rot(*pm.align_target(p, "x")[3:]), 2)
    assert max(abs(a - b) for a, b in zip(zx, [1, 0, 0])) < 1e-9


@pytest.mark.parametrize("pose", POSES)
def test_align_r_keeps_tool_axis_and_snaps_fingers_to_90(pose):
    r0, r1 = pm.rot(*pose[3:]), pm.rot(*pm.align_target(pose, "r")[3:])
    assert max(abs(a - b) for a, b in zip(pm.col(r0, 2), pm.col(r1, 2))) < 1e-9
    again = pm.rot(*pm.align_target(pm.align_target(pose, "r"), "r")[3:])
    assert _close(again, r1, 1e-7)                       # 이미 칸에 맞으면 그대로


@pytest.mark.parametrize("pose", POSES)
@pytest.mark.parametrize("mode", ["x", "y", "z", "r"])
def test_waypoints_small_steps_end_at_target(pose, mode):
    target = pm.align_target(pose, mode)
    w = pm.waypoints(pose, target, max_step=20.0)
    prev = pm.rot(*pose[3:])
    for q in w:
        assert q[:3] == pose[:3]
        cur = pm.rot(*q[3:])
        assert pm.rotation_angle(prev, cur) <= 20.0 + 1e-6
        prev = cur
    assert _close(prev, pm.rot(*target[3:]), 1e-7)


def test_waypoints_empty_when_already_aligned():
    p = pm.align_target(POSES[1], "z")
    assert pm.waypoints(p, pm.align_target(p, "z")) == []


def test_align_rejects_unknown_mode():
    with pytest.raises(ValueError):
        pm.align_target(POSES[0], "w")


def test_rotation_angle_of_base_rotation():
    r = pm.rot(*POSES[3][3:])
    assert math.isclose(pm.rotation_angle(r, pm.matmul(pm.base_rot("z", 35.0), r)), 35.0, abs_tol=1e-6)


def test_tilt_target_keeps_tcp_and_tilts_tip_toward_direction():
    """jog_gui 기울이기: 수직 아래 자세에서 +x 쪽 30° → 툴 z = (sin30, 0, −cos30), 위치 그대로, 손가락 방향 유지."""
    p = [517.21, -286.93, 240.49, 0.0, 180.0, 90.0]
    t = pm.tilt_target(p, (1.0, 0.0), 30.0)
    assert t[:3] == p[:3]
    z = pm.col(pm.rot(*t[3:]), 2)
    assert z == pytest.approx([0.5, 0.0, -math.sqrt(3) / 2], abs=1e-9)
    assert pm.rotation_angle(pm.rot(*p[3:]), pm.rot(*t[3:])) == pytest.approx(30.0, abs=1e-6)
    x0, x1 = pm.col(pm.rot(*p[3:]), 0), pm.col(pm.rot(*t[3:]), 0)
    assert sum(a * b for a, b in zip(x0, x1)) == pytest.approx(1.0, abs=1e-6)   # 닫힘 축이 기울기 축과 같으면 그대로


def test_tilt_target_is_absolute_and_zero_is_vertical():
    p = [400.0, -200.0, 300.0, 0.0, 180.0, 0.0]
    once = pm.tilt_target(p, (0.0, -1.0), 30.0)
    again = pm.tilt_target(once, (0.0, -1.0), 30.0)           # 다시 눌러도 60°가 되지 않음
    assert pm.rotation_angle(pm.rot(*once[3:]), pm.rot(*again[3:])) == pytest.approx(0.0, abs=1e-6)
    back = pm.tilt_target(once, (1.0, 0.0), 0.0)
    assert pm.col(pm.rot(*back[3:]), 2) == pytest.approx([0.0, 0.0, -1.0], abs=1e-9)


def test_tilt_target_matches_nudge_pose():
    """motion_plan.gripper_posx(기울임)와 같은 툴 z — 끌기 때 쓸 자세를 창으로 미리 볼 수 있다."""
    from ready2go_skills.core import motion_plan as mp
    p = [517.21, -286.93, 240.49, 0.4, 180.0, 89.74]
    a = mp.gripper_posx(p[:3], (0.0, 1.0, 0.0), p[3:], tilt_toward=(1.0, 0.0, 0.0), tilt_deg=30.0)
    b = pm.tilt_target(p, (1.0, 0.0), 30.0)
    assert pm.col(pm.rot(*a[3:]), 2) == pytest.approx(pm.col(pm.rot(*b[3:]), 2), abs=1e-9)


def test_roll_target_turns_fingers_about_gripper_axis():
    """jog_gui 그리퍼 회전: 툴 z 고정, 손가락(툴 x) 90° 회전, 위치 그대로. 수직 아래면 + = 위에서 볼 때 시계 방향."""
    p = [400.0, -200.0, 300.0, 0.0, 180.0, 0.0]
    t = pm.roll_target(p, 90.0)
    r0, r1 = pm.rot(*p[3:]), pm.rot(*t[3:])
    assert t[:3] == p[:3]
    assert pm.col(r1, 2) == pytest.approx(pm.col(r0, 2), abs=1e-9)
    assert pm.rotation_angle(r0, r1) == pytest.approx(90.0, abs=1e-6)
    x0, x1 = pm.col(r0, 0), pm.col(r1, 0)
    assert pm.cross(x0, x1)[2] == pytest.approx(-1.0, abs=1e-9)    # base z 기준 −90° = 위에서 볼 때 시계
    back = pm.roll_target(t, -90.0)
    assert pm.rotation_angle(r0, pm.rot(*back[3:])) == pytest.approx(0.0, abs=1e-6)
    assert len(pm.waypoints(p, t, 20.0)) == 5
