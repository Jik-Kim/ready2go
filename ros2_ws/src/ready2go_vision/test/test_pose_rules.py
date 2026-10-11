import json
import math
from pathlib import Path

import pytest

from ready2go_vision.core.pose_rules import is_symmetric, normalize_yaw, pose_errors, result_errors, round_yaw

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


def _occ_result(target_occ, cand_occ, area=0.0012):
    def it(i, occ, top):
        return {"id": i, "class": i.split("#")[0], "pose": {"frame": "drawer_top", "position": [0.1, 0.1, 0.0], "yaw": 0.0, "yaw_valid": True},
                "top_z": top, "occluded_by": occ, "visible_area_m2": area}
    return {"target_found": True, "target": it("eraser#1", target_occ, 0.0115), "candidates": [it("lip_balm#1", cand_occ, 0.02)], "visible_count": 2}


def test_occlusion_fields_are_optional_and_null_means_unknown():
    """가림 필드: null 이면 '모름', 결과 전체에 없으면 박스 모델 — 기존 결과·박스 모델은 그대로 통과."""
    assert result_errors(_occ_result(["lip_balm#1"], [])) == []
    assert result_errors(_occ_result(None, None, area=None)) == []
    r = _occ_result([], [])
    for it in [r["target"], *r["candidates"]]:
        del it["occluded_by"], it["visible_area_m2"]
    assert result_errors(r) == []


@pytest.mark.parametrize("drop", [("occluded_by", "visible_area_m2"), ("visible_area_m2",), ("occluded_by",)])
def test_partial_occlusion_fields_are_rejected(drop):
    """분할 모델은 모든 물체에 두 필드, 박스 모델은 결과 전체에 없음 (#120 A 제안 (가)·C 동의) — 일부 물체만 빠지면 거부.
    C select_obstacle 은 한 물체라도 필드가 있으면 분할 모델로 보고 빠진 물체를 '모름'으로 다룬다."""
    r = _occ_result([], [])
    for k in drop:
        del r["candidates"][0][k]
    errs = result_errors(r)
    assert len(errs) == 1 and "candidates[0] 에 가림 필드" in errs[0] and all(k in errs[0] for k in drop)


@pytest.mark.parametrize("target_occ, cand_occ, area, msg", [
    (["toy_hammer#1"], [], 0.001, "결과에 없는 id"),            # 같은 결과 안의 id 만
    (["eraser#1"], [], 0.001, "자기 자신"),
    ("lip_balm#1", [], 0.001, "목록 또는 null"),
    ([3], [], 0.001, "목록 또는 null"),
    ([], [], -0.1, "visible_area_m2"),
    ([], [], "0.1", "visible_area_m2"),
    ([], [], float("nan"), "visible_area_m2"),
    ([], [], float("inf"), "visible_area_m2"),
    (["lip_balm#1"], ["eraser#1"], 0.001, "순환"),             # 서로 덮음 (#169 D 리뷰)
])
def test_occlusion_field_errors(target_occ, cand_occ, area, msg):
    assert any(msg in e for e in result_errors(_occ_result(target_occ, cand_occ, area)))


def test_example_shows_occluded_unknown_and_free():
    ex = json.loads((Path(__file__).resolve().parents[4] / "contracts/examples/inspect_region_result.json").read_text(encoding="utf-8"))
    occ = [ex["target"]["occluded_by"]] + [c["occluded_by"] for c in ex["candidates"]]
    assert any(isinstance(o, list) and o for o in occ) and [] in occ and None in occ


def test_occlusion_three_way_cycle_is_rejected_and_chain_is_ok():
    def it(i, occ, top):
        return {"id": i, "class": i.split("#")[0], "pose": {"frame": "drawer_top", "position": [0.1, 0.1, 0.0], "yaw": 0.0, "yaw_valid": True},
                "top_z": top, "occluded_by": occ, "visible_area_m2": 0.002}
    chain = {"target_found": True, "target": it("eraser#1", ["car_key#1"], 0.0115),
             "candidates": [it("toy_hammer#1", [], 0.04), it("car_key#1", ["toy_hammer#1"], 0.03)], "visible_count": 3}
    assert result_errors(chain) == []                             # 망치 → 차키 → 지우개: 맨 위 = 망치
    chain["candidates"][0]["occluded_by"] = ["eraser#1"]          # 지우개 → 망치 를 더하면 3-순환
    assert any("순환" in e for e in result_errors(chain))


def test_duplicate_ids_are_rejected():
    """같은 결과 안 id 중복 거부 — occluded_by 끝점이 어느 물체인지 구분 못 함 (#169 D 리뷰)."""
    r = _occ_result([], [])
    r["candidates"][0]["id"] = "eraser#1"
    assert any("두 번 이상" in e for e in result_errors(r))


def test_occluder_with_lower_top_z_is_valid():
    """경계 높이로 판정하므로 덮는 물체 top_z 가 덮인 물체보다 낮아도 정상 (#169 E 결정): 차키(16 mm)가 렌치 손잡이 끝에, 렌치 top_z 는 머리 쪽 25 mm."""
    def it(i, occ, top):
        return {"id": i, "class": i.split("#")[0], "pose": {"frame": "drawer_top", "position": [0.1, 0.1, 0.0], "yaw": 0.0, "yaw_valid": True},
                "top_z": top, "occluded_by": occ, "visible_area_m2": 0.002}
    r = {"target_found": True, "target": it("toy_wrench#1", ["car_key#1"], 0.025), "candidates": [it("car_key#1", [], 0.022)], "visible_count": 2}
    assert result_errors(r) == []


@pytest.mark.parametrize("raw", [math.pi / 2 - 1e-6, -math.pi / 2 + 1e-6, 0.123456, -1.2])
def test_round_yaw_stays_in_range(raw):
    y = round_yaw(raw)
    assert pose_errors({"position": [0.1, 0.1, 0.0], "yaw": y, "yaw_valid": True}) == []
    assert y == pytest.approx(raw, abs=1e-4) or abs(abs(raw) - math.pi / 2) < 1e-4
