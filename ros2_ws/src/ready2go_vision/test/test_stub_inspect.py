import json
from pathlib import Path

import pytest

from ready2go_vision.core.stub_inspect import inspect

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
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load((Path(__file__).resolve().parents[4] / "config/vision_stub.yaml").read_text(encoding="utf-8"))
    assert cfg["ready"] is False, "자리표시자 좌표 상태에서는 ready 가 false 여야 합니다 (실측 반영 시 이 검사를 갱신)"
    cfg["ready"] = True
    for region in cfg["regions"]:
        ok, _, js = inspect(cfg, region)
        assert ok and json.loads(js)["visible_count"] == len(cfg["regions"][region]["objects"])


def test_stub_normalizes_yaw_to_range():
    cfg = {"ready": True, "regions": {"r": {"objects": [{"class": "a", "position": [0, 0, 0], "yaw": 3.0, "top_z": 0.01}]}}}
    _, _, js = inspect(cfg, "r", "a")
    assert -1.5708 < json.loads(js)["target"]["pose"]["yaw"] <= 1.5708   # 3.0 rad → 3.0 - pi
