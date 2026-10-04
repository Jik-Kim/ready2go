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
