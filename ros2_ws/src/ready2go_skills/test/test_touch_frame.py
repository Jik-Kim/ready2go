import math

import pytest

from ready2go_skills.core import touch_frame as tf


def _rotate(q, v):
    """쿼터니언 [x, y, z, w]로 벡터 회전 (검증용)."""
    x, y, z, w = q
    m = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    return [sum(m[r][c] * v[c] for c in range(3)) for r in range(3)]


def test_axis_aligned_frame_is_identity():
    f = tf.frame_from_touch([400, -100, 150], [600, -100, 150], [400, 100, 150])
    assert f.translation_m == pytest.approx([0.4, -0.1, 0.15])
    assert f.quaternion_xyzw == pytest.approx([0, 0, 0, 1])
    assert f.plane_angle_deg == pytest.approx(90.0)
    assert f.warnings == []


def test_yaw_90_frame():
    # x축 = base +y, y축 = base −x → z축 = base +z, yaw 90°
    f = tf.frame_from_touch([0, 0, 0], [0, 200, 0], [-200, 0, 0])
    s = math.sqrt(0.5)
    assert f.quaternion_xyzw == pytest.approx([0, 0, s, s])
    assert _rotate(f.quaternion_xyzw, [1, 0, 0]) == pytest.approx([0, 1, 0], abs=1e-9)


def test_quaternion_maps_axes_and_w_nonnegative():
    # 기울어진 평면 + 직각이 아닌 P3 — 쿼터니언이 계산한 축을 그대로 재현하는지
    f = tf.frame_from_touch([350, 20, 140], [560, 80, 145], [300, 230, 138])
    assert f.quaternion_xyzw[3] >= 0
    assert sum(v * v for v in f.quaternion_xyzw) == pytest.approx(1.0)
    for basis, axis in (([1, 0, 0], f.x_axis), ([0, 1, 0], f.y_axis), ([0, 0, 1], f.z_axis)):
        assert _rotate(f.quaternion_xyzw, basis) == pytest.approx(axis, abs=1e-9)


def test_y_axis_is_orthogonalized_from_skewed_p3():
    f = tf.frame_from_touch([0, 0, 0], [200, 0, 0], [30, 200, 0])
    assert f.y_axis == pytest.approx([0, 1, 0], abs=1e-12)
    assert any("각" in w for w in f.warnings)       # 81.5° → 경고


def test_downward_z_warns():
    f = tf.frame_from_touch([0, 0, 0], [200, 0, 0], [0, -200, 0])
    assert f.z_axis == pytest.approx([0, 0, -1])
    assert any("아래" in w for w in f.warnings)


@pytest.mark.parametrize("p2, p3", [
    ([10, 0, 0], [0, 200, 0]),       # P2가 너무 가까움
    ([200, 0, 0], [400, 5, 0]),      # 거의 한 직선
])
def test_rejects_bad_points(p2, p3):
    with pytest.raises(ValueError):
        tf.frame_from_touch([0, 0, 0], p2, p3)


def test_places_tf_line_format():
    f = tf.frame_from_touch([400, -100, 150], [600, -100, 150], [400, 100, 150])
    line = tf.places_tf_line("drawer_top", f)
    assert line.startswith("tf: {parent: base_link, child: drawer_top, translation_m: [0.40000")
    assert "quaternion_xyzw: [0.000000, 0.000000, 0.000000, 1.000000]" in line


def test_tip_offset_lowers_origin_only():
    pts = ([400, -100, 150], [600, -100, 150], [400, 100, 150])
    base = tf.frame_from_touch(*pts)
    f = tf.frame_from_touch(*pts, tip_offset_mm=10)
    assert f.translation_m == pytest.approx([0.4, -0.1, 0.14])     # 손끝 10 mm → 원점 z 10 mm 아래
    assert f.quaternion_xyzw == pytest.approx(base.quaternion_xyzw)
    assert pts[0] == [400, -100, 150]                                # 입력 리스트를 바꾸지 않음


def test_negative_tip_offset_rejected():
    with pytest.raises(ValueError):
        tf.frame_from_touch([0, 0, 0], [200, 0, 0], [0, 200, 0], tip_offset_mm=-1)


def test_floor_point_lowers_origin_along_z():
    # 테두리 윗면 z=220, 바닥 z=150 (깊이 70), 손끝 10 mm 보정
    rim = ([400, -100, 220], [605, -100, 220], [400, 195, 220])
    f = tf.frame_from_touch(*rim, tip_offset_mm=10, floor_point_mm=[450, 0, 150])
    assert f.translation_m == pytest.approx([0.4, -0.1, 0.14])
    assert f.quaternion_xyzw == pytest.approx([0, 0, 0, 1])
    assert (f.span_x_mm, f.span_y_mm, f.floor_depth_mm) == pytest.approx((205, 295, 70))


def test_floor_point_on_tilted_plane_moves_along_frame_z():
    rim = ([0, 0, 0], [200, 0, 20], [0, 200, 0])     # x 방향으로 기울어진 평면
    f = tf.frame_from_touch(*rim, floor_point_mm=[100, 100, -60])
    z = f.z_axis
    # 원점은 P1에서 z축 방향으로만 움직인다 (x·y가 축과 무관하게 튀지 않음)
    d = [f.translation_m[i] * 1000 for i in range(3)]
    cross = [d[1] * z[2] - d[2] * z[1], d[2] * z[0] - d[0] * z[2], d[0] * z[1] - d[1] * z[0]]
    assert cross == pytest.approx([0, 0, 0], abs=1e-9)
    assert sum(d[i] * z[i] for i in range(3)) < 0


def test_floor_point_above_plane_rejected():
    with pytest.raises(ValueError):
        tf.frame_from_touch([0, 0, 0], [200, 0, 0], [0, 200, 0], floor_point_mm=[50, 50, 30])
