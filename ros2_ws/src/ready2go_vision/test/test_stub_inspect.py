import json
from pathlib import Path

import yaml

from ready2go_vision.core.stub_inspect import inspect

CFG = yaml.safe_load((Path(__file__).resolve().parents[4] / "config/vision_stub.yaml").read_text(encoding="utf-8"))


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


def test_unknown_region_is_error():
    ok, code, r = run("drawer_x", "watch")
    assert not ok and code == "UNKNOWN_REGION" and r is None


def test_duplicate_class_gets_numbered_ids():
    cfg = {"regions": {"r": {"objects": [{"class": "a", "position": [0, 0, 0], "top_z": 0.01},
                                         {"class": "a", "position": [0, 0, 0], "top_z": 0.03}]}}}
    ok, _, js = inspect(cfg, "r", "a")
    r = json.loads(js)
    assert r["target"]["id"] == "a#2" and r["candidates"][0]["id"] == "a#1"   # target = top_z 가 큰 쪽
