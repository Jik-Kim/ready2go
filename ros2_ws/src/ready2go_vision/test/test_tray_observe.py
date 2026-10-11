"""전달 트레이 관측(#43): handover_zone 지역(floor_m), 찾음 / 정상 미검출 / 관측 오류(REGION_NOT_VISIBLE) 구분.
합성 탑뷰(트레이 바닥 + 직육면체). numpy·OpenCV·PyYAML 중 하나라도 없으면(CI) 건너뜀."""
import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
yaml = pytest.importorskip("yaml")
from ready2go_vision.core.geometry import Intrinsics  # noqa: E402
from ready2go_vision.core.inspect_real import footprint_inside, inspect_scene, region_frames  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
PARAMS = yaml.safe_load((ROOT / "config/vision_params.yaml").read_text(encoding="utf-8"))
PLACES = yaml.safe_load((ROOT / "config/places.yaml").read_text(encoding="utf-8"))
K = Intrinsics(fx=909.5, fy=909.1, cx=652.0, cy=371.3)                 # 실물 D435i 컬러 [덤프 10/11]
H = 0.345                                                               # 새 tray_view 카메라 → 트레이 바닥 [계산 10/11]
CAM_XY = (0.118, 0.090)
T = np.eye(4); T[:3, :3] = np.diag([1.0, -1.0, -1.0]); T[:3, 3] = [*CAM_XY, H]
ITEMS = {"eraser": {"size_m": [0.0525, 0.022, 0.0115]}, "lip_balm": {"size_m": [0.0718, 0.02, 0.02]}}
REGION = region_frames(PLACES)["handover_zone"]
FLOOR = REGION["interior_m"]


def scene(objs=(), floor_z=0.0):
    h, w = 720, 1280
    us, vs = np.meshgrid(np.arange(w, dtype=float), np.arange(h, dtype=float))
    depth = np.full((h, w), H - floor_z)
    for cx, cy, size, top in objs:
        x = CAM_XY[0] + (us - K.cx) / K.fx * (H - top)
        y = CAM_XY[1] - (vs - K.cy) / K.fy * (H - top)
        depth[(abs(x - cx) <= size[0] / 2) & (abs(y - cy) <= size[1] / 2)] = H - top
    return depth


def box_of(cx, cy, size):
    half = max(size) / 2 + 0.003
    u0, v0 = K.cx + (cx - CAM_XY[0]) / H * K.fx, K.cy - (cy - CAM_XY[1]) / H * K.fy
    return (u0 - half / H * K.fx, v0 - half / H * K.fy, u0 + half / H * K.fx, v0 + half / H * K.fy)


def run(depth, dets, target="eraser"):
    info = {}
    out = inspect_scene(dets, depth, K, T, PARAMS, ITEMS, "handover_zone", target, FLOOR, region_height_m=REGION["height_m"], info=info)
    return out, info


def test_region_uses_physical_floor_not_reach_range():
    assert FLOOR == [[-0.010, 0.246], [-0.010, 0.191]]                 # places.yaml handover_zone.floor_m
    assert REGION["height_m"] == pytest.approx(0.060)
    assert PLACES["handover_zone"]["interior_m"][0] < FLOOR[0][1]      # 놓기 범위(interior_m)는 트레이보다 작음


def test_found_in_tray_has_handover_frame():
    (ok, err, js), info = run(scene([(0.05, 0.09, (0.0525, 0.022), 0.0115)]), [{"class": "eraser", "conf": 0.9, "box": box_of(0.05, 0.09, (0.0525, 0.022))}])
    r = json.loads(js)
    assert ok and err == "" and r["target_found"] and r["target"]["pose"]["frame"] == "handover_zone"
    assert r["target"]["pose"]["position"][:2] == pytest.approx([0.05, 0.09], abs=0.003)
    assert info["region_visible_ratio"] > 0.95


def test_object_beyond_reach_range_but_on_tray_floor_is_found():
    """놓기 범위(x ≤ 0.137) 밖이지만 트레이 바닥 위(x 0.20) — 사람이 놓은 물체도 '트레이 안'."""
    (ok, _, js), _ = run(scene([(0.20, 0.09, (0.0525, 0.022), 0.0115)]), [{"class": "eraser", "conf": 0.9, "box": box_of(0.20, 0.09, (0.0525, 0.022))}])
    assert ok and json.loads(js)["target_found"]


def test_empty_tray_is_normal_not_found():
    (ok, err, js), info = run(scene(), [])
    r = json.loads(js)
    assert ok and err == "" and r == {"target_found": False, "target": None, "candidates": [], "visible_count": 0}
    assert info["region_visible_ratio"] > 0.95


def test_blocked_view_is_error_not_not_found():
    """손끝·케이블처럼 카메라 가까이 있는 것이 화면 절반을 가리면 '없음'이 아니라 관측 오류."""
    depth = scene()
    depth[:, :700] = 0.12
    (ok, err, js), info = run(depth, [])
    assert (ok, err, js) == (False, "REGION_NOT_VISIBLE", "") and info["region_visible_ratio"] < PARAMS["region"]["visible_min_ratio"]


def test_depth_dropout_is_error():
    depth = scene()
    depth[200:600, :] = 0.0
    (ok, err, _), _ = run(depth, [])
    assert not ok and err == "REGION_NOT_VISIBLE"


def test_floor_not_where_expected_is_error():
    """다른 지역을 찍었거나(10/08 아래 칸을 drawer_top 으로 호출) 자세가 틀려 바닥 높이가 안 맞으면 관측 오류."""
    (ok, err, _), _ = run(scene(floor_z=-0.15), [])
    assert not ok and err == "REGION_NOT_VISIBLE"


def test_footprint_inside_accepts_negative_floor_bounds():
    assert footprint_inside(-0.005 + 0.011, 0.05, 0.0, True, (0.0525, 0.022), FLOOR, 0.0) is False   # x 쪽 반 길이 26 mm 가 벽 밖
    assert footprint_inside(0.017, 0.012, 0.0, True, (0.0525, 0.022), FLOOR, 0.0) is True             # 원점보다 −y·−x 쪽까지 바닥
    assert footprint_inside(0.10, 0.10, 0.0, True, (0.0525, 0.022), [0.2, 0.3], 0.0) is True          # 서랍 [깊이, 폭] 형식 그대로


@pytest.mark.parametrize("name,ok,code,found", [("found", True, "", True), ("not_found", True, "", False), ("error", False, "REGION_NOT_VISIBLE", None)])
def test_handover_examples_are_valid(name, ok, code, found):
    from ready2go_vision.core.pose_rules import result_errors
    ex = json.loads((ROOT / f"contracts/examples/inspect_region_handover_{name}.json").read_text(encoding="utf-8"))
    assert (ex["success"], ex["error_code"]) == (ok, code)
    if ok:
        assert result_errors(ex["result"]) == [] and ex["result"]["target_found"] is found
        assert all(i["pose"]["frame"] == "handover_zone" for i in [ex["result"]["target"], *ex["result"]["candidates"]] if i)
    else:
        assert ex["result"] is None
