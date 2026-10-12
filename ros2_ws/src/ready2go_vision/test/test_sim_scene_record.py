"""sim/scripts/scene_record.py — 연 USD 의 생성 기록과 궤적 설정 대조 (#215). Isaac Sim 없이 검사 (test_sim_dims.py 와 같은 자리)."""
import copy
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sim/scripts"))
import scene_record as sr  # noqa: E402

PLACES = {
    "drawer_top": {"tf": {"translation_m": [0.23629, -0.11208, 0.19685], "quaternion_xyzw": [-0.004584, -0.003381, -0.706977, 0.707213]}},
    "drawer_bottom": {"tf": {"translation_m": [0.23331, -0.11581, 0.04902], "quaternion_xyzw": [-0.006184, -0.004694, -0.703354, 0.710797]}},
    "handover_zone": {"tf": {"translation_m": [0.52023, 0.13831, 0.00536], "quaternion_xyzw": [-0.005362, 0.000387, -0.003999, 0.999978]},
                      "floor_m": {"x": [-0.010, 0.246], "y": [-0.010, 0.191]}},
}
# #192 생성 당시(#206 전) 값 — 이전 설정 USD
OLD = copy.deepcopy(PLACES)
OLD["drawer_top"]["tf"] = {"translation_m": [0.22837, -0.11581, 0.19740], "quaternion_xyzw": [-0.007006, -0.000951, -0.704391, 0.709778]}
OLD["handover_zone"]["tf"] = {"translation_m": [0.502, 0.132, 0.0035], "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0]}


def scene(places, raw=b"places"):
    """build_scene.py 가 USD 에 남기는 것과 같은 경로(직렬화 → 읽기)."""
    return sr.loads(sr.dumps(sr.build_record(places, raw, "abc1234")))


def trace(places, raw=b"places"):
    import hashlib
    return {"cfg_dir": "/repo/config", "assumed": False, "places_sha256": hashlib.sha256(raw).hexdigest(), "places": copy.deepcopy(places)}


def test_same_config_scene_is_accepted():
    r = sr.compare(scene(PLACES), trace(PLACES))
    assert r["status"] == "ok" and r["diffs"] == [] and r["notes"] == []


def test_old_config_scene_with_current_trace_is_refused():
    """#215 완료 조건: 현재 YAML·현재 궤적 + 이전 설정 USD → 거부. 저장소 YAML 은 보지 않으므로 YAML 만 고친 경우도 잡힘."""
    r = sr.compare(scene(OLD), trace(PLACES))
    assert r["status"] == "mismatch"
    assert any(d.startswith("drawer_top.translation_m") for d in r["diffs"]) and any(d.startswith("handover_zone.translation_m") for d in r["diffs"])


def test_scene_without_record_is_refused():
    assert sr.compare(None, trace(PLACES))["status"] == "no_scene_record"
    assert sr.loads(None) is None and sr.loads("") is None and sr.loads("not json") is None and sr.loads('{"version": 0}') is None


def test_trace_without_config_is_refused():
    assert sr.compare(scene(PLACES), None)["status"] == "no_trace_config"
    assert sr.compare(scene(PLACES), {"cfg_dir": "x"})["status"] == "no_trace_config"


def test_tray_floor_change_is_mismatch():
    t = trace(PLACES)
    t["places"]["handover_zone"]["floor_m"] = {"x": [-0.010, 0.300], "y": [-0.010, 0.191]}
    r = sr.compare(scene(PLACES), t)
    assert r["status"] == "mismatch" and any("floor_m" in d for d in r["diffs"])


def test_sub_tolerance_and_sha_only_difference_pass_with_note():
    t = trace(PLACES, raw=b"places with a new comment")
    t["places"]["drawer_top"]["tf"]["translation_m"][0] += 0.00005               # 0.05 mm < 0.1 mm
    r = sr.compare(scene(PLACES), t)
    assert r["status"] == "ok" and any("sha256" in n for n in r["notes"])


def test_old_trace_without_floor_m_compares_tf_only():
    t = trace(PLACES)
    del t["places"]["handover_zone"]["floor_m"]
    r = sr.compare(scene(PLACES), t)
    assert r["status"] == "ok" and any("floor_m 기록 없음" in n for n in r["notes"])


def test_pose_diff_identity_and_offset():
    tf = PLACES["handover_zone"]["tf"]
    x, y, z, w = tf["quaternion_xyzw"]
    n = math.sqrt(x * x + y * y + z * z + w * w); x, y, z, w = x / n, y / n, z / n, w / n
    R = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    T = [R[0] + [tf["translation_m"][0]], R[1] + [tf["translation_m"][1]], R[2] + [tf["translation_m"][2]], [0, 0, 0, 1]]
    dp, dr = sr.pose_diff(T, tf)
    assert dp == pytest.approx(0, abs=1e-9) and dr == pytest.approx(0, abs=1e-3)
    T[0][3] += 0.002
    assert sr.pose_diff(T, tf)[0] == pytest.approx(0.002, abs=1e-9)
