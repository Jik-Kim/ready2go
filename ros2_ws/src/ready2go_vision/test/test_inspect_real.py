"""core/inspect_real.py 시험: 합성 장면(서랍 바닥 + 회전한 직육면체)에서 위치·높이·yaw 가 규칙대로 나오는가. numpy·OpenCV·PyYAML 중 하나라도 없으면(CI) 건너뜀."""
import json
import math
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
yaml = pytest.importorskip("yaml")
from ready2go_vision.core.geometry import Intrinsics, backproject  # noqa: E402
from ready2go_vision.core.inspect_real import inspect_scene  # noqa: E402

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
    assert len(debug) == 2 and "skip" not in debug[0] and debug[0]["top_z"] == pytest.approx(0.0115, abs=0.002)
    assert "conf_min" in debug[1]["skip"]


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
