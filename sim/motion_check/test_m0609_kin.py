"""m0609_kin 시험: 교시 자세 실측 TCP 와 FK 비교, IK 왕복, 손목 뒤집은 해. 실행: python3 -m pytest sim/motion_check -q (CI 대상 아님)."""
import numpy as np
import pytest

import m0609_kin as k

# 관절각(deg) → 펜던트 TCP mm [실측 B, config/poses.yaml 주석]
TAUGHT = {
    "drawer_top_view": ([-35.473, 36.888, 10.267, -0.191, 132.849, -35.490], [424.181, -294.601, 363.507]),
    "tray_view": ([9.825, 49.081, 33.632, -0.128, 97.300, 9.753], [663.515, 121.909, 100.147]),
    "handle_closed": ([7.151, 17.707, 116.751, 95.071, -95.287, -45.349], [382.695, -292.476, 268.505]),
    "handle_open": ([35.43, 27.553, 101.309, 114.113, -117.004, -45.309], [382.918, -66.2, 268.44]),
}


@pytest.mark.parametrize("name", list(TAUGHT))
def test_fk_matches_taught_tcp_within_3mm(name):
    q, tcp = TAUGHT[name]
    assert np.linalg.norm(np.array(k.fk_posx(q)[:3]) - tcp) < 3.0


def test_ik_roundtrip_and_posx_conversion():
    q0 = TAUGHT["drawer_top_view"][0]
    T = k.fk(q0)
    q, ok = k.ik(T, [v + 4 for v in q0])
    assert ok and np.abs(np.array(q) - q0).max() < 0.05
    assert np.abs(k.posx_to_T(k.T_to_posx(T)) - T).max() < 1e-9


def test_flipped_wrist_gives_same_tcp():
    q = [22.08, 20.928, 111.886, 105.463, -106.194, -45.033]
    f = [q[0], q[1], q[2], q[3] - 180, -q[4], q[5] + 180]
    assert np.abs(k.fk(q) - k.fk(f)).max() < 1e-9


def test_near_singular_view_pose_has_small_sigma():
    assert k.manipulability(TAUGHT["drawer_top_view"][0])[1] < 0.04 < k.manipulability(TAUGHT["tray_view"][0])[1]
