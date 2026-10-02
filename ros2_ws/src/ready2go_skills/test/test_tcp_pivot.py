import numpy as np
import pytest

from ready2go_skills.core.frames import posx_to_rt
from ready2go_skills.core.tcp_pivot import solve_pivot


def _zyz_from_r(r):
    """테스트용 역변환 (B가 0·180이 아닌 경우)."""
    b = np.degrees(np.arccos(np.clip(r[2, 2], -1, 1)))
    a = np.degrees(np.arctan2(r[1, 2], r[0, 2]))
    c = np.degrees(np.arctan2(r[2, 1], -r[2, 0]))
    return a, b, c


def test_posx_flange_down():
    r, t = posx_to_rt([368, 6, 424, 0, 180, 0, 2])
    assert np.allclose(r, np.diag([-1, 1, -1]), atol=1e-9)
    assert np.allclose(t, [368, 6, 424])


def test_posx_measured_flange_axis_points_down():
    # 10/02 실측 플랜지 posx: z축이 base −z와 거의 평행 (#7 코멘트)
    r, _ = posx_to_rt([367.36, 7.23, 422.83, 142.43, 179.95, 142.29])
    assert r[:, 2] == pytest.approx([-0.0006, 0.0005, -1.0], abs=2e-4)


def test_zyz_roundtrip():
    r, _ = posx_to_rt([0, 0, 0, 30, 140, -60])
    assert np.allclose(posx_to_rt([0, 0, 0, *_zyz_from_r(r)])[0], r)


def test_solve_pivot_recovers_tip_offset():
    tip = np.array([1.5, -2.0, 248.0])
    pivot = np.array([450.0, 30.0, 80.0])
    rng = np.random.default_rng(0)
    posx_list = []
    for _ in range(6):
        a, b, c = rng.uniform(-60, 60), rng.uniform(140, 175), rng.uniform(-60, 60)
        r, _ = posx_to_rt([0, 0, 0, a, b, c])
        p = pivot - r @ tip
        posx_list.append([*p, a, b, c])
    res = solve_pivot(posx_list)
    assert res.tip_in_flange_mm == pytest.approx(tip, abs=1e-6)
    assert res.pivot_in_base_mm == pytest.approx(pivot, abs=1e-6)
    assert res.residuals_mm.max() < 1e-6
    assert res.max_spread_deg > 20


def test_solve_pivot_needs_four_poses():
    with pytest.raises(ValueError):
        solve_pivot([[0, 0, 0, 0, 180, 0]] * 3)
