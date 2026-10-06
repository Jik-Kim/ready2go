import json
from pathlib import Path

import pytest

from ready2go_vision.core.stub_inspect import inspect, validate_config

# CI 에는 PyYAML 이 없으므로 로직 테스트는 인라인 설정을 쓴다. 실제 설정 파일은 마지막 테스트에서 (PyYAML 이 있을 때만) 검사한다.
CFG = {"ready": True, "regions": {
    "drawer_top": {"objects": [
        {"class": "watch", "position": [0.10, 0.08, 0.0], "yaw": 0.0, "top_z": 0.04},
        {"class": "wallet", "position": [0.10, 0.18, 0.0], "yaw": 0.0, "top_z": 0.02},
        {"class": "car_key", "position": [0.18, 0.13, 0.0], "yaw": 0.0, "top_z": 0.03}]},
    "staging_tray": {"objects": []},
}}


def run(region, target=""):
    ok, code, js = inspect(CFG, region, target)
    return ok, code, (json.loads(js) if js else None)


def test_target_found_and_candidates_sorted():
    ok, code, r = run("drawer_top", "wallet")
    assert ok and code == "" and r["target_found"]
    assert r["target"]["id"] == "wallet#1" and r["target"]["pose"]["frame"] == "drawer_top"
    assert r["visible_count"] == 3 and len(r["candidates"]) == 2
    tz = [c["top_z"] for c in r["candidates"]]
    assert tz == sorted(tz, reverse=True)


def test_not_found_is_success():
    ok, code, r = run("drawer_top", "umbrella")
    assert ok and not r["target_found"] and r["target"] is None and r["visible_count"] == 3


def test_empty_region_and_no_target():
    ok, _, r = run("staging_tray", "watch")
    assert ok and not r["target_found"] and r["visible_count"] == 0
    ok, _, r = run("drawer_top")
    assert ok and r["target"] is None and len(r["candidates"]) == 3


def test_not_ready_blocks_output():
    for cfg in ({**CFG, "ready": False}, {k: v for k, v in CFG.items() if k != "ready"}):
        ok, code, js = inspect(cfg, "drawer_top", "watch")
        assert not ok and code == "STUB_NOT_READY" and js == ""


def test_unknown_region_is_error():
    ok, code, r = run("drawer_x", "watch")
    assert not ok and code == "UNKNOWN_REGION" and r is None


def test_duplicate_class_gets_numbered_ids():
    cfg = {"ready": True, "regions": {"r": {"objects": [{"class": "a", "position": [0, 0, 0], "top_z": 0.01},
                                         {"class": "a", "position": [0, 0, 0], "top_z": 0.03}]}}}
    ok, _, js = inspect(cfg, "r", "a")
    r = json.loads(js)
    assert r["target"]["id"] == "a#2" and r["candidates"][0]["id"] == "a#1"   # target = top_z 가 큰 쪽


def test_real_config_file_is_valid():
    """커밋된 설정 파일: ready 가 true 면 노드와 같은 실측 규칙(validate_config)을 통과해야 한다."""
    yaml = pytest.importorskip("yaml")
    root = Path(__file__).resolve().parents[4]
    cfg = yaml.safe_load((root / "config/vision_stub.yaml").read_text(encoding="utf-8"))
    places = yaml.safe_load((root / "config/places.yaml").read_text(encoding="utf-8"))
    interiors = {k: v["interior_m"][:2] for k, v in places.items() if isinstance(v, dict) and v.get("interior_m")}
    if cfg["ready"] is True:
        assert validate_config(cfg, interiors) == []
    else:
        assert cfg["ready"] is False
    cfg["ready"] = True
    for region in cfg["regions"]:
        ok, _, js = inspect(cfg, region)
        assert ok and json.loads(js)["visible_count"] == len(cfg["regions"][region]["objects"])


INTERIORS = {"drawer_top": [0.1997, 0.2937]}
GOOD = {"class": "eraser", "position": [0.1769, 0.2895, 0.0], "yaw": 0.0, "yaw_valid": True, "top_z": 0.0115}   # 1차 점검 값(#22)


def _cfg(*objs):
    return {"ready": True, "regions": {"drawer_top": {"objects": list(objs)}, "handover_zone": {"objects": []}}}


def test_runtime_accepts_measured_value():
    ok, code, js = inspect(_cfg(GOOD), "drawer_top", "eraser", INTERIORS)
    assert ok and code == "" and json.loads(js)["target"]["pose"]["position"] == [0.1769, 0.2895, 0.0]


@pytest.mark.parametrize("bad", [
    {"position": [-0.05, 0.15, 0.0]},          # D 재현: 서랍 밖 (앞쪽)
    {"position": [0.10, 0.30, 0.0]},           # 폭 밖
    {"position": [0.10, 0.15, 0.01]},          # z ≠ 0
    {"position": [0.10, float("nan"), 0.0]},   # 유한하지 않음
    {"position": [0.10, 0.15]},                # 값 2개
    {"yaw_valid": None},                       # yaw_valid 생략과 같음
    {"yaw": float("inf")},
    {"top_z": 0.0},
    {"class": ""},
])
def test_runtime_blocks_bad_values_with_config_invalid(bad):
    obj = dict(GOOD, **bad)
    if bad.get("yaw_valid", 1) is None:
        obj.pop("yaw_valid")
    ok, code, js = inspect(_cfg(obj), "drawer_top", "eraser", INTERIORS)
    assert (ok, code, js) == (False, "CONFIG_INVALID", "")


def test_runtime_blocks_ready_true_with_no_objects():
    assert inspect(_cfg(), "drawer_top", "eraser", INTERIORS)[:2] == (False, "CONFIG_INVALID")


def test_runtime_check_applies_to_external_yaml_file(tmp_path):
    """점검 당일처럼 저장소 밖 yaml 을 config_path 로 쓰는 경우에도 같은 규칙이 적용된다."""
    yaml = pytest.importorskip("yaml")
    f = tmp_path / "vision_stub.yaml"
    f.write_text("ready: true\nregions:\n  drawer_top:\n    objects:\n"
                 "      - {class: eraser, position: [-0.05, 0.15, 0.0], yaw: 0.0, yaw_valid: true, top_z: 0.0115}\n", encoding="utf-8")
    cfg = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert validate_config(cfg, INTERIORS)
    assert inspect(cfg, "drawer_top", "eraser", INTERIORS)[:2] == (False, "CONFIG_INVALID")


def test_region_without_known_interior_skips_only_the_bound_check():
    cfg = {"ready": True, "regions": {"handover_zone": {"objects": [dict(GOOD, position=[0.5, 0.5, 0.0])]}}}
    assert validate_config(cfg, INTERIORS) == []
    cfg["regions"]["handover_zone"]["objects"][0].pop("yaw_valid")
    assert validate_config(cfg, INTERIORS)


def test_stub_normalizes_yaw_to_range():
    cfg = {"ready": True, "regions": {"r": {"objects": [{"class": "a", "position": [0, 0, 0], "yaw": 3.0, "top_z": 0.01}]}}}
    _, _, js = inspect(cfg, "r", "a")
    assert -1.5708 < json.loads(js)["target"]["pose"]["yaw"] <= 1.5708   # 3.0 rad → 3.0 - pi


def test_stub_emits_yaw_valid_true_by_default_and_false_with_zero_yaw_when_set():
    cfg = {"ready": True, "regions": {"r": {"objects": [
        {"class": "a", "position": [0, 0, 0], "yaw": 0.4, "top_z": 0.02},
        {"class": "b", "position": [0, 0, 0], "yaw": 0.4, "yaw_valid": False, "top_z": 0.01}]}}}
    _, _, js = inspect(cfg, "r", "a")
    r = json.loads(js)
    assert r["target"]["pose"]["yaw_valid"] is True and r["target"]["pose"]["yaw"] == 0.4
    b = r["candidates"][0]["pose"]
    assert b["yaw_valid"] is False and b["yaw"] == 0.0


@pytest.mark.parametrize("bad", ["false", "true", 0, 1, None])
def test_non_bool_yaw_valid_is_a_config_error(bad):
    cfg = {"ready": True, "regions": {"r": {"objects": [{"class": "a", "position": [0, 0, 0], "yaw": 0.4, "yaw_valid": bad, "top_z": 0.02}]}}}
    ok, code, js = inspect(cfg, "r", "a")
    assert not ok and code == "CONFIG_INVALID" and js == ""
