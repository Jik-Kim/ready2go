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


def test_partly_covered_long_object_near_wall_is_kept():
    """10/12 PC2 3단 쌓기(inspect_20261012_021411): 손잡이가 덮인 긴 물체는 보이는 중심이 머리 쪽으로 치우친다.
    명목 크기를 그 중심에 놓으면 벽 밖으로 계산돼 결과에서 빠졌다 → 분할 모델은 보이는 마스크로 서랍 안을 본다."""
    objs = [("carrot_pen", 0.11, 0.15, (0.1512, 0.0154), 0.0154),                 # x 0.034~0.186 (벽 0.1997 안)
            ("caramel_box", 0.06, 0.15, (0.075, 0.049), 0.0154 + 0.0185)]          # 펜 앞쪽 절반을 덮음 → 보이는 펜 중심 x ≈ 0.142
    dbg = []
    it, r = run(objs, target="carrot_pen", debug=dbg)
    assert r["target_found"] and "carrot_pen#1" in it
    assert not any(d.get("skip", "").startswith("footprint") for d in dbg if "class" in d)


def test_floating_object_above_wall_height_is_excluded():
    """분할 모델: 윗면이 지역 벽 높이보다 높은 검출(트레이 안 손을 carrot_pen 으로 오검출, 10/11 top_z 67.6 mm)은 결과에서 뺀다."""
    objs = [("eraser", 0.10, 0.15, (0.0525, 0.022), 0.0115), ("lip_balm", 0.10, 0.20, (0.0718, 0.02), 0.09)]
    depth, masks = scene(objs)
    dbg = []
    ok, _, js = inspect_scene(dets_of(objs, masks), depth, K, T, PARAMS, ITEMS, "drawer_top", "eraser", INTERIOR, dbg, region_height_m=0.0684)
    r = json.loads(js)
    assert ok and r["visible_count"] == 1 and r["target"]["id"] == "eraser#1"
    assert any(d.get("class") == "lip_balm" and "벽 높이" in d.get("skip", "") for d in dbg)


def test_split_but_fully_visible_object_is_not_unknown():
    """마스크에 떨어진 작은 조각이 붙어 '조각남'이어도 보이는 넓이가 기준 이상이면 가려진 게 아니다 → [] (10/12 맨 위 차키가 null 이던 것)."""
    objs = [("eraser", 0.10, 0.15, (0.0525, 0.022), 0.0115)]
    depth, masks = scene(objs)
    m = masks[0].copy(); m[250:280, 800:830] = True                                 # 떨어진 900 px 조각(서랍 안 바닥 위)
    ok, _, js = inspect_scene(dets_of(objs, [m]), depth, K, T, PARAMS, ITEMS, "drawer_top", "eraser", INTERIOR)
    assert ok and json.loads(js)["target"]["occluded_by"] == []


def test_lower_object_is_not_over_higher_one_when_edge_depth_mixes():
    """10/12 PC2 024941: 캐러멜 가장자리 띠 뎁스가 바닥과 섞여(6.5 mm, 윗면 37) 몽키(띠 10.6)가 '캐러멜 위'로 나왔다.
    위 물체의 전체 윗면이 아래 물체 윗면보다 max_over_lower_m 넘게 낮으면 그 관계는 버린다."""
    objs = [("eraser", 0.07, 0.15, (0.0525, 0.022), 0.0115), ("caramel_box", 0.12, 0.15, (0.075, 0.049), 0.0185 + 0.0185)]
    depth, masks = scene(objs)
    import cv2
    near = cv2.dilate(masks[0].astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
    depth[masks[1] & near] = H                                                     # 캐러멜 쪽 맞닿은 띠 = 바닥 뎁스 (가장자리 섞임)
    m1 = masks[1].copy(); m1[:, 700:] = False                                      # 캐러멜은 덜 보임(다른 물체에 일부 가림)
    dbg = []
    ok, _, js = inspect_scene(dets_of(objs, [masks[0], m1]), depth, K, T, PARAMS, ITEMS, "drawer_top", "caramel_box", INTERIOR, dbg)
    t = json.loads(js)["target"]
    assert ok and (t["occluded_by"] is None or "eraser#1" not in t["occluded_by"])
    assert any(d.get("occlusion", {}).get("judge", "").startswith("버림") for d in dbg)


def test_thin_deck_over_object_falls_back_to_clearly_higher_neighbor():
    """10/12 PC2 아래 칸 031339: 덮개 판이 립밤 끝을 얇게 덮어 맞닿은 띠 높이 차 2 mm(기준 4 mm 미만) → 립밤 null 이었다.
    덜 보이는데 덮은 물체를 못 찾으면, 맞닿은 이웃 중 전체 윗면이 fallback_cover_min_m 이상 높은 것이 하나뿐이면 그것이 덮은 물체."""
    objs = [("lip_balm", 0.10, 0.15, (0.0718, 0.02), 0.020),
            ("cover_plate", 0.13, 0.15, (0.06, 0.06), 0.022),                      # 판(립밤 위 2 mm)
            ("cover_plate", 0.15, 0.15, (0.02, 0.02), 0.034)]                      # 판 위 손잡이(전체 윗면 34 mm)
    depth, masks = scene(objs)
    dets = dets_of(objs[:2], [masks[0], masks[1] | masks[2]])
    items = {**ITEMS, "cover_plate": {"size_m": [0.0985, 0.0742, 0.0405]}}
    ok, _, js = inspect_scene(dets, depth, K, T, PARAMS, items, "drawer_top", "lip_balm", INTERIOR)
    assert ok and json.loads(js)["target"]["occluded_by"] == ["cover_plate#1"]


def test_fallback_needs_clearly_higher_neighbor():
    """보조 규칙은 이웃 전체 윗면이 fallback_cover_min_m(10 mm) 이상 높을 때만 — 판 손잡이가 8 mm 높으면(지우개 옆 립밤 8.5 mm 같은 키 차이) 모름 그대로."""
    objs = [("lip_balm", 0.10, 0.15, (0.0718, 0.02), 0.020),
            ("cover_plate", 0.13, 0.15, (0.06, 0.06), 0.022),
            ("cover_plate", 0.15, 0.15, (0.02, 0.02), 0.028)]                      # 전체 윗면 28 mm (립밤 + 8)
    depth, masks = scene(objs)
    dets = dets_of(objs[:2], [masks[0], masks[1] | masks[2]])
    items = {**ITEMS, "cover_plate": {"size_m": [0.0985, 0.0742, 0.0405]}}
    ok, _, js = inspect_scene(dets, depth, K, T, PARAMS, items, "drawer_top", "lip_balm", INTERIOR)
    assert ok and json.loads(js)["target"]["occluded_by"] is None


def test_dropped_relation_leaves_under_object_unknown_not_clear():
    """PM #236 검토: 얇은 물체가 키 큰 물체의 낮은 부분에 얹혀 경계로는 '위'인데 전체 윗면이 낮아 관계를 버리면(max_over_lower_m),
    아래 물체가 대부분 보여도 [](안 가려짐)이 아니라 null(모름) — 낮은 부분 위 물체를 못 보고 집지 않게 (runner.md 7.1)."""
    objs = [("lip_balm", 0.08, 0.15, (0.06, 0.02), 0.010),                       # 키 큰 물체의 낮은 부분(손잡이)
            ("lip_balm", 0.125, 0.15, (0.03, 0.02), 0.030),                      # 높은 부분(머리)
            ("eraser", 0.08, 0.15, (0.012, 0.05), 0.015)]                         # 낮은 부분을 가로지른 얇은 물체 → 조각냄
    depth, masks = scene(objs)
    dets = dets_of([objs[0], objs[2]], [masks[0] | masks[1], masks[2]])
    dbg = []
    ok, _, js = inspect_scene(dets, depth, K, T, PARAMS, ITEMS, "drawer_top", "lip_balm", INTERIOR, dbg)
    assert ok and json.loads(js)["target"]["occluded_by"] is None
    assert any(d.get("occlusion", {}).get("judge", "").startswith("버림") for d in dbg)


def _bled(eraser_top, near_px=None):
    """바닥 지우개 옆에 높은 물체(윗면 35 mm). 지우개 마스크가 이웃 쪽으로 10 px 번짐(10/12 판 밑 지우개)."""
    objs = [("eraser", 0.10, 0.15, (0.0525, 0.022), eraser_top), ("caramel_box", 0.10, 0.15 + 0.011 + 0.0245 - 0.003, (0.075, 0.049), 0.035)]   # 3 mm 겹쳐 맞닿음
    depth, masks = scene(objs)
    vv, uu = np.nonzero(masks[0])
    m = masks[0].copy(); m[vv.min() - 10:vv.min(), uu.min():uu.max() + 1] = True    # 이미지 위쪽(+y) = 이웃 쪽
    params = {**PARAMS, "depth_blob": {**PARAMS["depth_blob"], **({} if near_px is None else {"top_exclude_near_px": near_px})}}
    dbg = []
    ok, _, js = inspect_scene(dets_of(objs, [m, masks[1]]), depth, K, T, params, ITEMS, "drawer_top", "eraser", INTERIOR, dbg)
    assert ok
    return json.loads(js)["target"], next(d for d in dbg if d.get("class") == "eraser")


def test_top_z_ignores_mask_bleed_onto_higher_neighbor():
    """분할 마스크가 높은 이웃에 걸치면 p95 윗면이 이웃 높이로 튄다 → 높은 이웃 근처 픽셀을 빼고 잰다. 0 이면 끔(이전과 같음)."""
    off, _ = _bled(0.0115, near_px=0)
    on, note = _bled(0.0115)
    assert off["top_z"] > 0.03
    assert on["top_z"] == pytest.approx(0.0115, abs=0.0015) and note["top_z_near_higher"]["before"] == off["top_z"]


def test_top_z_not_lowered_below_nominal():
    """번짐을 덜어도 명목 높이보다 낮추지 않는다(검은 물체 뎁스가 낮게 잡히는 경우)."""
    on, _ = _bled(0.009)
    assert on["top_z"] == pytest.approx(ITEMS["eraser"]["size_m"][2])
