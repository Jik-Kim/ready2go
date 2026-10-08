"""core/inspect_real.py 시험: 합성 장면(서랍 바닥 + 회전한 직육면체)에서 위치·높이·yaw 가 규칙대로 나오는가. numpy·OpenCV·PyYAML 중 하나라도 없으면(CI) 건너뜀."""
import json
import math
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
yaml = pytest.importorskip("yaml")
from ready2go_vision.core.geometry import Intrinsics, backproject  # noqa: E402
from ready2go_vision.core.inspect_real import inspect_scene, region_frames  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
PARAMS = yaml.safe_load((ROOT / "config/vision_params.yaml").read_text(encoding="utf-8"))
K = Intrinsics(fx=900.0, fy=900.0, cx=640.0, cy=360.0)
H = 0.37                                                    # 카메라 높이 (서랍 바닥 위)
CAM_XY = (0.10, 0.15)
R_DOWN = np.diag([1.0, -1.0, -1.0])                         # 광학 z 가 아래, x 는 서랍 x, y 는 서랍 -y
T = np.eye(4); T[:3, :3] = R_DOWN; T[:3, 3] = [*CAM_XY, H]  # T_drawer_cam
ITEMS = {"eraser": {"size_m": [0.0525, 0.022, 0.0115]}, "masking_tape": {"size_m": [0.045, 0.045, 0.02]}}


def scene(cx, cy, yaw, size, height, extra=None):
    """바닥 뎁스 + (cx, cy) 중심·yaw 회전한 직육면체(위에서 본 크기 size, 높이 height)의 뎁스(m)."""
    h, w = 720, 1280
    us, vs = np.meshgrid(np.arange(w, dtype=float), np.arange(h, dtype=float))
    depth = np.full((h, w), H)
    for (px, py, pyaw, psize, pheight) in [(cx, cy, yaw, size, height)] + (extra or []):
        x = CAM_XY[0] + (us - K.cx) / K.fx * (H - pheight)
        y = CAM_XY[1] - (vs - K.cy) / K.fy * (H - pheight)
        c, s = math.cos(pyaw), math.sin(pyaw)
        a = (x - px) * c + (y - py) * s
        b = -(x - px) * s + (y - py) * c
        depth[(abs(a) <= psize[0] / 2) & (abs(b) <= psize[1] / 2)] = H - pheight
    return depth


def box_of(cx, cy, size, yaw, margin=0.003):
    half = max(size) / 2 * 1.2 + margin
    u0 = K.cx + (cx - CAM_XY[0]) / H * K.fx
    v0 = K.cy - (cy - CAM_XY[1]) / H * K.fy
    return (u0 - half / H * K.fx, v0 - half / H * K.fy, u0 + half / H * K.fx, v0 + half / H * K.fy)


INTERIOR = [0.1997, 0.2937]


def run(depth, dets, target="eraser"):
    return inspect_scene(dets, depth, K, T, PARAMS, ITEMS, "drawer_top", target, INTERIOR)


def test_eraser_pose_matches_ground_truth():
    gt = (0.06, 0.18, 0.5)
    depth = scene(gt[0], gt[1], gt[2], (0.0525, 0.022), 0.0115)
    ok, err, js = run(depth, [{"class": "eraser", "conf": 0.9, "box": box_of(gt[0], gt[1], (0.0525, 0.022), gt[2])}])
    assert ok and err == ""
    t = json.loads(js)["target"]
    assert t["id"] == "eraser#1" and t["pose"]["frame"] == "drawer_top"
    assert t["pose"]["position"][0] == pytest.approx(gt[0], abs=0.003) and t["pose"]["position"][1] == pytest.approx(gt[1], abs=0.003)
    assert t["pose"]["position"][2] == 0.0
    assert t["pose"]["yaw"] == pytest.approx(gt[2], abs=0.05) and t["pose"]["yaw_valid"] is True
    assert t["top_z"] == pytest.approx(0.0115, abs=0.002)


def test_yaw_is_a_line_not_an_arrow():
    for yaw_in, yaw_out in [(2.0, 2.0 - math.pi), (-1.4, -1.4)]:
        depth = scene(0.08, 0.16, yaw_in, (0.0525, 0.022), 0.0115)
        _, _, js = run(depth, [{"class": "eraser", "conf": 0.9, "box": box_of(0.08, 0.16, (0.0525, 0.022), yaw_in)}])
        assert json.loads(js)["target"]["pose"]["yaw"] == pytest.approx(yaw_out, abs=0.06)


def test_symmetric_object_gets_yaw_zero_and_valid():
    depth = scene(0.10, 0.10, 0.7, (0.045, 0.045), 0.02)
    _, _, js = run(depth, [{"class": "masking_tape", "conf": 0.8, "box": box_of(0.10, 0.10, (0.045, 0.045), 0.7)}], "masking_tape")
    p = json.loads(js)["target"]["pose"]
    assert p["yaw"] == 0.0 and p["yaw_valid"] is True


def test_not_visible_is_success_not_error():
    ok, err, js = run(scene(0.1, 0.1, 0, (0.05, 0.02), 0.0115), [])
    r = json.loads(js)
    assert ok and err == "" and r["target_found"] is False and r["visible_count"] == 0


def test_depth_hole_fails_whole_request():
    depth = scene(0.08, 0.16, 0.3, (0.0525, 0.022), 0.0115)
    b = box_of(0.08, 0.16, (0.0525, 0.022), 0.3)
    depth[int(b[1]) - 10:int(b[3]) + 10, int(b[0]) - 10:int(b[2]) + 10] = 0.0          # 박스 안 뎁스 전부 결손
    ok, err, _ = run(depth, [{"class": "eraser", "conf": 0.9, "box": b}])
    assert not ok and err == "DEPTH_INVALID"


def test_unknown_region_and_low_confidence_and_unknown_class():
    depth = scene(0.1, 0.1, 0, (0.05, 0.02), 0.0115)
    assert inspect_scene([], depth, K, T, PARAMS, ITEMS, "handover_zone", "eraser")[:2] == (False, "UNKNOWN_REGION")
    b = box_of(0.1, 0.1, (0.0525, 0.022), 0)
    ok, _, js = run(depth, [{"class": "eraser", "conf": 0.1, "box": b}, {"class": "not_an_item", "conf": 0.9, "box": b}])
    assert ok and json.loads(js)["visible_count"] == 0


def test_two_objects_sorted_by_height_and_ids():
    e1 = (0.05, 0.10, 0.0, (0.0525, 0.022), 0.0115)
    tape = (0.15, 0.22, 0.0, (0.045, 0.045), 0.02)
    depth = scene(*e1[:2], e1[2], e1[3], e1[4], extra=[tape])
    dets = [{"class": "eraser", "conf": 0.9, "box": box_of(0.05, 0.10, (0.0525, 0.022), 0)},
            {"class": "masking_tape", "conf": 0.9, "box": box_of(0.15, 0.22, (0.045, 0.045), 0)}]
    ok, _, js = run(depth, dets)
    r = json.loads(js)
    assert ok and r["target"]["id"] == "eraser#1" and r["candidates"][0]["id"] == "masking_tape#1" and r["visible_count"] == 2


def test_object_outside_drawer_is_excluded_not_returned():
    """D 검수 P1: 서랍 밖(x<0)에 있는 물체는 정상 target 으로 나가면 안 된다."""
    for cx, cy in [(-0.03, 0.15), (0.23, 0.15)]:                          # 시야 안에서 서랍 앞쪽·안쪽 밖. y 방향은 아래 단위 시험
        depth = scene(cx, cy, 0.0, (0.0525, 0.022), 0.0115)
        ok, err, js = run(depth, [{"class": "eraser", "conf": 0.9, "box": box_of(cx, cy, (0.0525, 0.022), 0.0)}])
        r = json.loads(js)
        assert ok and r["target_found"] is False and r["visible_count"] == 0, (cx, cy, r)


def test_object_near_wall_inside_is_kept_and_edge_tolerance_applies():
    inside = scene(0.04, 0.15, 0.0, (0.0525, 0.022), 0.0115)             # 긴 변 절반 26 mm 가 벽(0)에서 4 mm 안쪽 → 안
    ok, _, js = run(inside, [{"class": "eraser", "conf": 0.9, "box": box_of(0.04, 0.15, (0.0525, 0.022), 0.0)}])
    assert json.loads(js)["target_found"] is True
    edge = scene(0.020, 0.15, 0.0, (0.0525, 0.022), 0.0115)              # footprint 가 벽을 6 mm 넘음 → 여유 10 mm 안이라 유지
    ok, _, js = run(edge, [{"class": "eraser", "conf": 0.9, "box": box_of(0.020, 0.15, (0.0525, 0.022), 0.0)}])
    assert json.loads(js)["target_found"] is True
    far = scene(0.005, 0.15, 0.0, (0.0525, 0.022), 0.0115)               # 21 mm 넘음 → 제외
    ok, _, js = run(far, [{"class": "eraser", "conf": 0.9, "box": box_of(0.005, 0.15, (0.0525, 0.022), 0.0)}])
    assert json.loads(js)["target_found"] is False


def test_unknown_yaw_uses_circumscribed_footprint():
    from ready2go_vision.core.inspect_real import footprint_inside
    size = [0.0525, 0.022, 0.0115]
    assert footprint_inside(0.027, 0.15, 0.0, True, size, INTERIOR, 0.0) is True       # yaw 알면 긴 변 절반 26.3 mm → 안
    assert footprint_inside(0.027, 0.15, 0.0, False, size, INTERIOR, 0.0) is False     # 모르면 외접원 28.5 mm → 밖
    for x, y in [(0.10, -0.01), (0.10, 0.30), (-0.01, 0.15), (0.21, 0.15)]:             # 네 방향 바깥(오차 여유 0)
        assert footprint_inside(x, y, 0.3, True, size, INTERIOR, 0.0) is False


def test_debug_notes_each_detection_without_changing_result():
    depth = scene(0.06, 0.18, 0.5, (0.0525, 0.022), 0.0115)
    dets = [{"class": "eraser", "conf": 0.9, "box": box_of(0.06, 0.18, (0.0525, 0.022), 0.5)},
            {"class": "eraser", "conf": 0.1, "box": box_of(0.06, 0.18, (0.0525, 0.022), 0.5)}]
    debug = []
    with_debug = inspect_scene(dets, depth, K, T, PARAMS, ITEMS, "drawer_top", "eraser", INTERIOR, debug)
    assert with_debug == run(depth, dets)
    hi, lo = (next(d for d in debug if d["conf"] == c) for c in (0.9, 0.1))   # 순서: 거르기 기록이 먼저(중복 병합 단계 분리)
    assert len(debug) == 2 and "skip" not in hi and hi["top_z"] == pytest.approx(0.0115, abs=0.002)
    assert "conf_min" in lo["skip"]


def test_floor_probe_reports_floor_height_and_ignores_objects():
    from ready2go_vision.core.floor_probe import floor_probe
    fp = PARAMS["floor_probe"]
    depth = scene(0.10, 0.15, 0.0, (0.0525, 0.022), 0.0115)
    box = box_of(0.10, 0.15, (0.0525, 0.022), 0.0)
    r = floor_probe(depth, K, T, INTERIOR, [box], fp)
    assert r["n"] > 100 and r["z_median_m"] == pytest.approx(0.0, abs=0.0005)
    raised = depth - 0.003                                              # 바닥(과 물체)이 카메라 쪽으로 3 mm → 서랍 z +3 mm
    assert floor_probe(raised, K, T, INTERIOR, [box], fp)["z_median_m"] == pytest.approx(0.003, abs=0.0005)
    assert floor_probe(np.zeros_like(depth), K, T, INTERIOR, [], fp) == {"n": 0}


def test_edge_tolerance_boundary_keeps_14mm_and_drops_16mm_overrun():
    """경계 여유(vision_params region.edge_tolerance_m)가 footprint 초과량 14 mm 는 허용, 16 mm 는 제외하는가 (0.015 기준)."""
    from ready2go_vision.core.inspect_real import footprint_inside
    tol = PARAMS["region"]["edge_tolerance_m"]
    assert tol == pytest.approx(0.015)
    size = [0.0525, 0.022, 0.0115]
    hx, hy = size[0] / 2, size[1] / 2
    for over, inside in [(0.014, True), (0.016, False)]:
        assert footprint_inside(hx - over, 0.15, 0.0, True, size, INTERIOR, tol) is inside                  # x = 0 벽 밖
        assert footprint_inside(INTERIOR[0] - hx + over, 0.15, 0.0, True, size, INTERIOR, tol) is inside    # x = 안쪽 벽 밖
        assert footprint_inside(0.10, hy - over, 0.0, True, size, INTERIOR, tol) is inside                  # y = 0 벽 밖
        assert footprint_inside(0.10, INTERIOR[1] - hy + over, 0.0, True, size, INTERIOR, tol) is inside    # y = 왼쪽 벽 밖
    # 합성 장면 전체 경로: 이 장면에서 x 가 약 1.4 mm 안쪽으로 측정돼(투영 근사) 경계 ±1 mm 는 가르지 못한다 → 12 mm 허용·18 mm 제외로 본다
    for cx, keep in [(hx - 0.012, True), (hx - 0.018, False)]:
        depth = scene(cx, 0.15, 0.0, (0.0525, 0.022), 0.0115)
        ok, _, js = run(depth, [{"class": "eraser", "conf": 0.9, "box": box_of(cx, 0.15, (0.0525, 0.022), 0.0)}])
        assert ok and json.loads(js)["target_found"] is keep, (cx, keep)


def test_detection_outside_drawer_roi_is_skipped_before_depth():
    """PC2 10/07: 서랍 밖(바닥보다 낮은 책상 위) 오검출이 뎁스 실패로 호출 전체를 DEPTH_INVALID 로 만들지 않는다."""
    depth = scene(0.08, 0.16, 0.0, (0.0525, 0.022), 0.0115)
    out = box_of(-0.12, 0.15, (0.05, 0.03), 0.0)                       # 서랍 앞쪽 밖 12 cm
    depth[int(out[1]):int(out[3]), int(out[0]):int(out[2])] = H + 0.05   # 서랍 바닥보다 5 cm 낮은 면 → 뎁스 덩어리 없음
    dets = [{"class": "eraser", "conf": 0.95, "box": box_of(0.08, 0.16, (0.0525, 0.022), 0.0)},
            {"class": "masking_tape", "conf": 0.38, "box": out}]
    dbg = []
    ok, err, js = inspect_scene(dets, depth, K, T, PARAMS, ITEMS, "drawer_top", "eraser", INTERIOR, dbg)
    assert ok and json.loads(js)["target_found"] is True, err
    assert any(d["class"] == "masking_tape" and d.get("skip", "").startswith("서랍 영역 밖") for d in dbg)
    no_roi = {**PARAMS, "region": {k: v for k, v in PARAMS["region"].items() if k != "detect_roi_margin_m"}}
    assert inspect_scene(dets, depth, K, T, no_roi, ITEMS, "drawer_top", "eraser", INTERIOR)[:2] == (False, "DEPTH_INVALID")


def test_roi_keeps_wall_touching_object_and_depth_hole_inside_still_fails():
    m = PARAMS["region"]["detect_roi_margin_m"]
    assert 0.02 <= m <= 0.035                                           # 서랍 안 물체 투영 초과 최대 3.3 mm, 그리퍼 손끝 자리 36 mm 이상 [실측 10/07]
    inside = scene(0.04, 0.15, 0.0, (0.0525, 0.022), 0.0115)            # 벽(x=0) 4 mm 안쪽까지 붙은 지우개 → 그대로 target
    ok, _, js = run(inside, [{"class": "eraser", "conf": 0.9, "box": box_of(0.04, 0.15, (0.0525, 0.022), 0.0)}])
    assert ok and json.loads(js)["target_found"] is True
    hole = scene(0.08, 0.16, 0.0, (0.0525, 0.022), 0.0115)              # 서랍 안 뎁스 결손(렌즈 가림 등)은 여전히 오류로 알린다
    b = box_of(0.08, 0.16, (0.0525, 0.022), 0.0)
    hole[int(b[1]) - 10:int(b[3]) + 10, int(b[0]) - 10:int(b[2]) + 10] = 0.0
    assert run(hole, [{"class": "eraser", "conf": 0.9, "box": b}])[:2] == (False, "DEPTH_INVALID")


def test_gripper_fingertip_like_detection_beyond_back_wall_is_skipped():
    """PC2 10/07: 화면 아래 그리퍼 손끝을 목표와 같은 eraser 로 오검출(0.39). 바닥 투영이 서랍 안쪽 끝보다 36 mm 이상 밖 → ROI 로 제외."""
    depth = scene(0.10, 0.15, 0.0, (0.0525, 0.022), 0.0115)
    ghost = box_of(INTERIOR[0] + 0.036, 0.15, (0.03, 0.02), 0.0)
    dbg = []
    ok, _, js = inspect_scene([{"class": "eraser", "conf": 0.39, "box": ghost},
                               {"class": "eraser", "conf": 0.95, "box": box_of(0.10, 0.15, (0.0525, 0.022), 0.0)}],
                              depth, K, T, PARAMS, ITEMS, "drawer_top", "eraser", INTERIOR, dbg)
    r = json.loads(js)
    assert ok and r["visible_count"] == 1 and abs(r["target"]["pose"]["position"][0] - 0.10) < 0.005
    assert any(d["conf"] == 0.39 and d.get("skip", "").startswith("서랍 영역 밖") for d in dbg)


def test_drawer_bottom_region_uses_requested_frame():
    """아래 칸(#155): 같은 계산, pose.frame 은 요청 지역. 지원 밖 지역은 그대로 UNKNOWN_REGION."""
    gt = (0.06, 0.18, 0.5)
    depth = scene(gt[0], gt[1], gt[2], (0.0525, 0.022), 0.0115)
    dets = [{"class": "eraser", "conf": 0.9, "box": box_of(gt[0], gt[1], (0.0525, 0.022), gt[2])}]
    top = json.loads(run(depth, dets)[2])["target"]
    ok, err, js = inspect_scene(dets, depth, K, T, PARAMS, ITEMS, "drawer_bottom", "eraser", INTERIOR)
    bottom = json.loads(js)["target"]
    assert ok and err == "" and bottom["pose"]["frame"] == "drawer_bottom"
    assert bottom["pose"]["position"] == top["pose"]["position"] and bottom["top_z"] == top["top_z"]
    assert inspect_scene(dets, depth, K, T, PARAMS, ITEMS, "drawer_middle", "eraser", INTERIOR)[:2] == (False, "UNKNOWN_REGION")


def test_region_frames_skips_unmeasured_tf_and_keeps_each_interior():
    places = yaml.safe_load((ROOT / "config/places.yaml").read_text(encoding="utf-8"))
    places["drawer_bottom"]["tf"] = {"parent": "base_link", "child": "drawer_bottom", "translation_m": None, "quaternion_xyzw": None}
    assert set(region_frames(places)) == {"drawer_top"}
    places["drawer_bottom"]["tf"] = {"parent": "base_link", "child": "drawer_bottom",
                                     "translation_m": [0.24, -0.11, 0.047], "quaternion_xyzw": [0.0, 0.0, -0.7071068, 0.7071068]}
    places["drawer_bottom"]["interior_m"] = [0.19, 0.28, 0.06]
    fr = region_frames(places)
    assert set(fr) == {"drawer_top", "drawer_bottom"}
    assert fr["drawer_bottom"]["interior_m"] == [0.19, 0.28] and fr["drawer_top"]["interior_m"] == places["drawer_top"]["interior_m"][:2]
    assert fr["drawer_bottom"]["T_base_drawer"][:3, 3] == pytest.approx([0.24, -0.11, 0.047])
    assert fr["drawer_bottom"]["T_base_drawer"][:3, :3] @ [1, 0, 0] == pytest.approx([0, -1, 0], abs=1e-6)


def mask_of(cx, cy, yaw, size, height, shape=(720, 1280)):
    """scene() 과 같은 투영으로 물체 윗면 픽셀 마스크 (분할 모델 마스크 대신)."""
    h, w = shape
    us, vs = np.meshgrid(np.arange(w, dtype=float), np.arange(h, dtype=float))
    x = CAM_XY[0] + (us - K.cx) / K.fx * (H - height)
    y = CAM_XY[1] - (vs - K.cy) / K.fy * (H - height)
    c, s = math.cos(yaw), math.sin(yaw)
    a, b = (x - cx) * c + (y - cy) * s, -(x - cx) * s + (y - cy) * c
    return (abs(a) <= size[0] / 2) & (abs(b) <= size[1] / 2)


def test_mask_depth_ignores_taller_neighbor_inside_box():
    """P2 분할(#109): 상자 안에 높은 이웃이 들어오면 상자 뎁스는 이웃 높이가 섞이고, 마스크 안 뎁스는 자기 높이."""
    er = (0.08, 0.15, 0.0, (0.0525, 0.022), 0.0115)
    tall = (0.08, 0.15 + 0.011 + 0.010, 0.0, (0.06, 0.02), 0.040)        # 지우개 긴 변에 붙은 높이 40 mm 물체
    depth = scene(*er, extra=[tall])
    box = box_of(er[0], er[1], er[3], er[2])
    det = {"class": "eraser", "conf": 0.9, "box": box}
    _, _, js_box = run(depth, [det])
    ok, err, js = run(depth, [{**det, "mask": mask_of(*er)}])
    assert ok and err == ""
    t_box, t = json.loads(js_box)["target"], json.loads(js)["target"]
    assert t_box["top_z"] > 0.03                                           # 상자: 이웃 40 mm 가 섞임
    assert t["top_z"] == pytest.approx(0.0115, abs=0.002)                  # 마스크: 지우개 11.5 mm
    assert t["pose"]["yaw_valid"] is True and t["pose"]["yaw"] == pytest.approx(0.0, abs=0.05)
    assert t["pose"]["position"] == pytest.approx(t_box["pose"]["position"], abs=0.003)


def test_mask_debug_reports_depth_source_and_empty_eroded_mask_falls_back():
    from ready2go_vision.core.depth_blob import analyze_box
    er = (0.10, 0.15, 0.0, (0.0525, 0.022), 0.0115)
    depth = scene(*er)
    box = box_of(er[0], er[1], er[3], er[2])
    dbg = []
    inspect_scene([{"class": "eraser", "conf": 0.9, "box": box, "mask": mask_of(*er)}], depth, K, T, PARAMS, ITEMS, "drawer_top", "eraser", INTERIOR, dbg)
    assert dbg[0]["depth_src"] == "mask"
    tiny = np.zeros(depth.shape, bool)
    u, v = int((box[0] + box[2]) / 2), int((box[1] + box[3]) / 2)
    tiny[v - 1:v + 2, u - 1:u + 2] = True                                  # 3x3: 깎으면 사라짐 → 깎기 전 마스크로
    r = analyze_box(depth, box, K, T, {**PARAMS["depth_blob"], "min_valid_px": 5}, mask=tiny)
    assert r.depth_ok and r.top_z == pytest.approx(0.0115, abs=0.002)


def test_duplicate_mask_detections_become_one_object():
    """분할 모델이 같은 지우개를 두 번 잡으면(전체 + 일부) 결과는 하나, 디버그에 병합 기록 (#109 4단계 선행)."""
    er = (0.10, 0.15, 0.0, (0.0525, 0.022), 0.0115)
    depth = scene(*er)
    full = mask_of(*er)
    part = full & mask_of(er[0] + 0.01, er[1], 0.0, (0.03, 0.022), er[4])
    box = box_of(er[0], er[1], er[3], er[2])
    dbg = []
    ok, err, js = inspect_scene([{"class": "eraser", "conf": 0.6, "box": box, "mask": part},
                                 {"class": "eraser", "conf": 0.9, "box": box, "mask": full}],
                                depth, K, T, PARAMS, ITEMS, "drawer_top", "eraser", INTERIOR, dbg)
    r = json.loads(js)
    assert ok and r["visible_count"] == 1 and r["target"]["id"] == "eraser#1"
    assert any(d.get("skip", "").startswith("중복") for d in dbg) and any(d.get("merged_from") for d in dbg)


def test_box_model_duplicates_are_not_merged():
    """박스 모델(마스크 없음)은 지금처럼 병합하지 않는다 — P1 결과 그대로."""
    er = (0.10, 0.15, 0.0, (0.0525, 0.022), 0.0115)
    depth = scene(*er)
    box = box_of(er[0], er[1], er[3], er[2])
    _, _, js = run(depth, [{"class": "eraser", "conf": 0.9, "box": box}, {"class": "eraser", "conf": 0.6, "box": box}])
    assert json.loads(js)["visible_count"] == 2
