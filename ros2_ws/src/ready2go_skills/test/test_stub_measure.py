import math
from pathlib import Path

import pytest
import yaml

from ready2go_skills.core import pick_plan, stub_measure as sm

ROOT = Path(__file__).resolve().parents[4]
TF = yaml.safe_load((ROOT / "config/places.yaml").read_text(encoding="utf-8"))["drawer_top"]["tf"]
PI = math.pi


def _touch(x, y, z):
    """서랍 좌표 (m) → 그 점을 손끝으로 찍었을 때 펜던트 TCP (mm)."""
    b = pick_plan.to_base(TF, (x, y, z))
    return [b[0] * 1000, b[1] * 1000, b[2] * 1000 + 10.0]


# ready2go_vision test_pose_rules.py 와 같은 경계 사례 (같은 규칙)
@pytest.mark.parametrize("raw,expected", [
    (0.0, 0.0), (0.52, 0.52), (-0.7, -0.7), (PI / 2, PI / 2), (-PI / 2, PI / 2),
    (PI, 0.0), (-PI, 0.0), (2 * PI + 0.3, 0.3), (-PI / 2 + 1e-6, -PI / 2 + 1e-6), (PI / 2 + 1e-6, -PI / 2 + 1e-6),
])
def test_normalize_yaw_same_rule_as_vision(raw, expected):
    assert sm.normalize_yaw(raw) == pytest.approx(expected, abs=1e-9)


def test_base_to_frame_inverts_to_base():
    p = (0.12, 0.08, 0.03)
    assert sm.base_to_frame(TF, pick_plan.to_base(TF, p)) == pytest.approx(p, abs=1e-6)   # places.yaml 쿼터니언이 6자리 반올림이라 1 µm 안


@pytest.mark.parametrize("yaw", [0.0, 0.52, -0.7, 1.2])
def test_two_points_give_center_and_yaw(yaw):
    c, h, half = (0.10, 0.15), 0.0115, 0.0262            # 지우개 윗면, 긴 변 52.5 mm
    a = _touch(c[0] - half * math.cos(yaw), c[1] - half * math.sin(yaw), h)
    b = _touch(c[0] + half * math.cos(yaw), c[1] + half * math.sin(yaw), h)
    for pts in ([a, b], [b, a]):                          # 찍는 순서가 바뀌어도 같은 직선
        m = sm.measure(TF, pts)
        assert m["position"][:2] == pytest.approx(list(c), abs=1e-4) and m["position"][2] == 0.0
        assert m["yaw"] == pytest.approx(sm.normalize_yaw(yaw), abs=1e-4)
        assert m["floor_gap_m"] == pytest.approx(h, abs=1e-4)


def test_one_point_symmetric_yaw_zero():
    m = sm.measure(TF, [_touch(0.12, 0.20, 0.0152)])
    assert m["position"][:2] == pytest.approx([0.12, 0.20], abs=1e-4) and m["yaw"] == 0.0


def test_bad_point_counts():
    with pytest.raises(ValueError):
        sm.measure(TF, [])
    with pytest.raises(ValueError):
        sm.measure(TF, [_touch(0.1, 0.1, 0.01), _touch(0.101, 0.1, 0.01)])   # 5 mm 안


def test_cli_prints_stub_line(capsys):
    a, b = _touch(0.08, 0.15, 0.0115), _touch(0.12, 0.15, 0.0115)
    assert sm.main(["--class", "eraser", "--point", *map(str, a), "--point", *map(str, b)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("- {class: eraser, position: [0.1, 0.15, 0.0], yaw: 0.0, top_z: 0.0115}")
