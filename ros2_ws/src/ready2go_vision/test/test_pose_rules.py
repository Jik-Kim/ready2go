import json
import math
from pathlib import Path

import pytest

from ready2go_vision.core.pose_rules import is_symmetric, normalize_yaw, pose_errors, result_errors

PI = math.pi


@pytest.mark.parametrize("raw,expected", [
    (0.0, 0.0), (0.52, 0.52), (-0.7, -0.7),
    (PI / 2, PI / 2),          # 경계: 위쪽 끝은 포함
    (-PI / 2, PI / 2),         # 경계: 아래쪽 끝은 제외, 같은 직선인 +pi/2 로
    (PI, 0.0), (-PI, 0.0), (2 * PI + 0.3, 0.3),
    (-PI / 2 + 1e-6, -PI / 2 + 1e-6),   # 경계 바로 안쪽은 음수 그대로
    (PI / 2 + 1e-6, -PI / 2 + 1e-6),    # 경계 바로 바깥은 반대편으로 넘어감
])
def test_normalize_yaw(raw, expected):
    assert normalize_yaw(raw) == pytest.approx(expected, abs=1e-9)


def test_normalized_value_is_always_in_range_and_same_line():
    for k in range(-400, 401):
        raw = k * 0.0137
        y = normalize_yaw(raw)
        assert -PI / 2 < y <= PI / 2 + 1e-12
        assert math.sin(raw - y) == pytest.approx(0, abs=1e-9)   # 차이가 pi 의 정수배


def test_pose_errors():
    ok = {"frame": "drawer_top", "position": [0.1, 0.2, 0.0], "yaw": 0.5, "yaw_valid": True}
    assert pose_errors(ok) == []
    assert pose_errors({**ok, "position": [0.1, 0.2, 0.03]})                  # z 는 0
    assert pose_errors({**ok, "yaw": PI / 2 + 0.01})                            # 범위 밖
    assert pose_errors({**ok, "yaw": -PI / 2})                                  # 아래쪽 경계는 제외
    assert pose_errors({**ok, "yaw": PI / 2}) == []                             # 위쪽 경계는 포함
    assert pose_errors({**ok, "yaw": None})


def test_example_result_follows_rules_and_has_nonzero_yaw():
    r = json.loads((Path(__file__).resolve().parents[4] / "contracts/examples/inspect_region_result.json").read_text(encoding="utf-8"))
    assert result_errors(r) == []
    yaws = [r["target"]["pose"]["yaw"]] + [c["pose"]["yaw"] for c in r["candidates"]]
    assert any(abs(y) > 0.1 for y in yaws), "범위 검사가 의미 있도록 0이 아닌 yaw 예시가 있어야 함"


@pytest.mark.parametrize("size,expected", [
    ([0.119, 0.100, 0.03], True),      # 비 1.19 → 대칭
    ([0.120, 0.100, 0.03], False),     # 비 1.2 → 비대칭 (< 1.2 만 대칭)
    ([0.0200, 0.0200, 0.0], True),     # masking_tape 처럼 비 1.0
    ([0.0905, 0.0680, 0.0], False),    # cover_plate 류 비 1.33
    ([0.0535, 0.0400, 0.0], False),    # airpods_case 류 비 1.34
])
def test_is_symmetric_boundaries(size, expected):
    assert is_symmetric(size) is expected


def test_is_symmetric_ignores_order_and_height():
    assert is_symmetric([0.10, 0.119, 0.5]) == is_symmetric([0.119, 0.10, 0.001]) is True
    assert is_symmetric([0.10, 0.2, 0.03]) == is_symmetric([0.2, 0.10, 0.03]) is False


def test_is_symmetric_rejects_nonpositive():
    with pytest.raises(ValueError):
        is_symmetric([0.0, 0.1, 0.1])


def test_yaw_valid_rules():
    base = {"frame": "drawer_top", "position": [0.1, 0.2, 0.0]}
    assert pose_errors({**base, "yaw": 0.0, "yaw_valid": False}) == []        # 모름: yaw 0 자리표시
    assert pose_errors({**base, "yaw": 0.0, "yaw_valid": True}) == []         # 진짜 0° 또는 대칭 물체
    assert pose_errors({**base, "yaw": 0.4, "yaw_valid": False})              # false 인데 yaw != 0
    assert pose_errors({**base, "yaw": 0.4})                                  # 필드 없음
    assert pose_errors({**base, "yaw": 0.4, "yaw_valid": 1})                  # bool 아님


def test_example_has_a_false_yaw_valid_case():
    r = json.loads((Path(__file__).resolve().parents[4] / "contracts/examples/inspect_region_result.json").read_text(encoding="utf-8"))
    flags = [r["target"]["pose"]["yaw_valid"]] + [c["pose"]["yaw_valid"] for c in r["candidates"]]
    assert False in flags and True in flags
