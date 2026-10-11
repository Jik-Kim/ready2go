"""core/occlusion.py·inspect_scene 가림 필드 시험 (#109 4단계): 합성 탑뷰(서랍 바닥 + 직육면체)와 그 마스크로
얹힘 / 맞닿음 / 모름 / 박스 모델 필드 생략을 확인한다. numpy·OpenCV·PyYAML 중 하나라도 없으면(CI) 건너뜀."""
import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
yaml = pytest.importorskip("yaml")
from ready2go_vision.core.geometry import Intrinsics  # noqa: E402
from ready2go_vision.core.inspect_real import inspect_scene  # noqa: E402
from ready2go_vision.core.occlusion import occlusion_fields, visible_area_m2  # noqa: E402
from ready2go_vision.core.pose_rules import result_errors  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
PARAMS = yaml.safe_load((ROOT / "config/vision_params.yaml").read_text(encoding="utf-8"))
PARAMS["occlusion"] = OCC = {**PARAMS["occlusion"], "ref_visible_area_m2": {   # 합성 물체는 직육면체라 기준 넓이 = 명목 가로×세로
    **PARAMS["occlusion"]["ref_visible_area_m2"], "eraser": 0.0525 * 0.022, "caramel_box": 0.075 * 0.049, "lip_balm": 0.0718 * 0.02}}
K = Intrinsics(fx=900.0, fy=900.0, cx=640.0, cy=360.0)
H = 0.37
CAM_XY = (0.10, 0.15)
T = np.eye(4); T[:3, :3] = np.diag([1.0, -1.0, -1.0]); T[:3, 3] = [*CAM_XY, H]
INTERIOR = [0.1997, 0.2937]
ITEMS = {"eraser": {"size_m": [0.0525, 0.022, 0.0115]}, "caramel_box": {"size_m": [0.075, 0.049, 0.0185]},
         "lip_balm": {"size_m": [0.0718, 0.02, 0.02]}, "carrot_pen": {"size_m": [0.1512, 0.0154, 0.0154]}}


def scene(objs):
    """objs = [(class, cx, cy, size(가로·세로), 바닥에서 윗면 높이)] — 나중 것이 위에 놓인다(겹친 부분은 나중 것의 높이).
    → (뎁스, [보이는 마스크])"""
    h, w = 720, 1280
    us, vs = np.meshgrid(np.arange(w, dtype=float), np.arange(h, dtype=float))
    depth = np.full((h, w), H)
    owner = np.full((h, w), -1)
    for k, (_, cx, cy, size, top) in enumerate(objs):
        x = CAM_XY[0] + (us - K.cx) / K.fx * (H - top)
        y = CAM_XY[1] - (vs - K.cy) / K.fy * (H - top)
        foot = (abs(x - cx) <= size[0] / 2) & (abs(y - cy) <= size[1] / 2)
        depth[foot] = H - top
        owner[foot] = k
    return depth, [owner == k for k in range(len(objs))]


def dets_of(objs, masks, with_mask=True):
    out = []
    for (cls, *_), m in zip(objs, masks):
        vv, uu = np.nonzero(m)
        d = {"class": cls, "conf": 0.9, "box": (float(uu.min()), float(vv.min()), float(uu.max()), float(vv.max()))}
        if with_mask:
            d["mask"] = m
        out.append(d)
    return out


def run(objs, target="eraser", with_mask=True, debug=None):
    depth, masks = scene(objs)
    ok, err, js = inspect_scene(dets_of(objs, masks, with_mask), depth, K, T, PARAMS, ITEMS, "drawer_top", target, INTERIOR, debug)
    assert ok, err
    r = json.loads(js)
    assert result_errors(r) == []
    return {i["id"]: i for i in [r["target"], *r["candidates"]] if i}, r


ERASER_ON_BOX = [("caramel_box", 0.10, 0.15, (0.075, 0.049), 0.0185),
                 ("eraser", 0.12, 0.15, (0.0525, 0.022), 0.0185 + 0.0115)]


def test_visible_area_is_physical_footprint():
    depth, masks = scene([("eraser", 0.10, 0.15, (0.0525, 0.022), 0.0115)])
    assert visible_area_m2(masks[0], depth, K, 0.15, 1.0) == pytest.approx(0.0525 * 0.022, rel=0.03)


def test_eraser_on_box_gives_relation():
    it, _ = run(ERASER_ON_BOX)
    assert it["caramel_box#1"]["occluded_by"] == ["eraser#1"]
    assert it["eraser#1"]["occluded_by"] == []
    assert it["caramel_box#1"]["visible_area_m2"] < 0.075 * 0.049 * 0.85        # 지금 보이는 부분만 (전체 넓이 아님)


def test_side_by_side_same_height_is_not_occluded():
    it, _ = run([("eraser", 0.08, 0.15, (0.0525, 0.022), 0.0115), ("lip_balm", 0.08, 0.172, (0.0718, 0.02), 0.0115)])
    assert it["eraser#1"]["occluded_by"] == [] and it["lip_balm#1"]["occluded_by"] == []


def test_less_visible_without_cover_is_unknown():
    """덜 보이는데(마스크 절반) 덮은 물체가 결과에 없음 → null (빈 목록으로 내면 '안 가려짐'으로 읽힘)."""
    depth, masks = scene([("caramel_box", 0.10, 0.15, (0.075, 0.049), 0.0185)])
    m = masks[0].copy(); m[:, :640] = False
    dets = dets_of([("caramel_box",)], [m])
    ok, _, js = inspect_scene(dets, depth, K, T, PARAMS, ITEMS, "drawer_top", "caramel_box", INTERIOR)
    t = json.loads(js)["target"]
    assert ok and t["occluded_by"] is None and t["visible_area_m2"] > 0


def test_yaw_near_90_degrees_stays_in_range():
    """반올림 1.5708 이 pi/2 를 넘어 RESULT_INVALID 가 나던 문제 (가림 시험에서 발견)."""
    it, _ = run([("caramel_box", 0.10, 0.15, (0.049, 0.075), 0.0185)], target="caramel_box")
    assert it["caramel_box#1"]["pose"]["yaw"] == pytest.approx(1.5708, abs=1e-3)


def test_cover_missing_from_result_is_unknown():
    depth, masks = scene(ERASER_ON_BOX)
    out = occlusion_fields(dets_of(ERASER_ON_BOX, masks), ["caramel_box#1", None], depth, K, T, OCC, 0.15, 1.0)
    assert out["caramel_box#1"][0] is None


def test_class_without_reference_area_under_cover_is_unknown():
    objs = [("carrot_pen", 0.10, 0.15, (0.1512, 0.0154), 0.0154), ("eraser", 0.10, 0.15, (0.0525, 0.022), 0.0154 + 0.0115)]
    it, _ = run(objs)
    assert "carrot_pen" not in OCC["ref_visible_area_m2"]
    assert it["carrot_pen#1"]["occluded_by"] in (None, ["eraser#1"])           # 조각으로 나뉘면 관계, 아니면 모름 — 빈 목록은 안 됨
    assert it["eraser#1"]["occluded_by"] == []


def test_seg_detection_without_mask_gets_null_fields():
    depth, masks = scene(ERASER_ON_BOX)
    dets = dets_of(ERASER_ON_BOX, masks)
    dets[1].pop("mask")
    ok, _, js = inspect_scene(dets, depth, K, T, PARAMS, ITEMS, "drawer_top", "eraser", INTERIOR, seg_model=True)
    r = json.loads(js)
    assert ok and result_errors(r) == []
    assert r["target"]["occluded_by"] is None and r["target"]["visible_area_m2"] is None
    assert r["candidates"][0]["occluded_by"] is None                            # 덮은 물체의 마스크가 없어 덜 보임의 원인을 못 찾음


def test_box_model_has_no_occlusion_fields():
    _, r = run(ERASER_ON_BOX, with_mask=False)
    for it in [r["target"], *r["candidates"]]:
        assert "occluded_by" not in it and "visible_area_m2" not in it


def test_debug_has_relation_evidence():
    dbg = []
    run(ERASER_ON_BOX, debug=dbg)
    rel = [d["occlusion"] for d in dbg if "occlusion" in d]
    assert any(r.get("judge") == "얹힘" and r["over"] == "eraser#1" and r["under"] == "caramel_box#1" and r["dz_mm"] >= 4 for r in rel)
