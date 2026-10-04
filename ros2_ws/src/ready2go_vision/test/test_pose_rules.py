import json
import math
from pathlib import Path

import pytest

from ready2go_vision.core.pose_rules import normalize_yaw, pose_errors, result_errors

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
    ok = {"frame": "drawer_top", "position": [0.1, 0.2, 0.0], "yaw": 0.5}
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
