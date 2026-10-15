"""core/overlay.py 시험 (#348): 합성 장면에서 결과 물체 → 검출 짝, 잘라내기·출력 크기, 실패 요청(검출만·TF 없음)에도 그림이 나오는가.
numpy·OpenCV·Pillow 중 하나라도 없으면(CI) 건너뜀."""
import json
import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")
pytest.importorskip("PIL")
from ready2go_vision.core.geometry import Intrinsics  # noqa: E402
from ready2go_vision.core.overlay import OUT_H, OUT_W, LatestSlot, _crop_box, _match, encode_jpeg, render_overlay  # noqa: E402

K = Intrinsics(fx=900.0, fy=900.0, cx=640.0, cy=360.0)
H = 0.37
T = np.eye(4); T[:3, :3] = np.diag([1.0, -1.0, -1.0]); T[:3, 3] = [0.10, 0.15, H]       # 서랍 (0.10, 0.15) 위 37 cm, 아래를 봄
INTERIOR = [0.20, 0.29]
ITEMS = {"eraser": {"name_ko": "지우개", "size_m": [0.0525, 0.022, 0.0115]}}


def px(x, y):
    return K.cx + (x - 0.10) / H * K.fx, K.cy - (y - 0.15) / H * K.fy


def det_at(x, y, conf=0.9, r=20):
    u, v = px(x, y)
    m = np.zeros((720, 1280), bool); m[int(v) - r:int(v) + r, int(u) - r:int(u) + r] = True
    return {"class": "eraser", "conf": conf, "box": (u - r, v - r, u + r, v + r), "mask": m}


def obj(i, x, y, yaw_valid=True, occ=None):
    return {"id": f"eraser#{i}", "pose": {"frame": "drawer_top", "position": [x, y, 0.0], "yaw": 0.3, "yaw_valid": yaw_valid},
            "top_z": 0.0115, "occluded_by": occ}


def test_match_uses_projected_position_not_order():
    """같은 클래스 두 개: 결과 순서가 검출 순서와 반대여도 위치로 짝지음 (라벨이 다른 물체에 붙지 않게)."""
    dets = [det_at(0.05, 0.10), det_at(0.15, 0.22)]
    m = _match(dets, [obj(1, 0.15, 0.22), obj(2, 0.05, 0.10)], K, T)
    assert m[0]["id"] == "eraser#2" and m[1]["id"] == "eraser#1"


def test_match_skips_detection_without_result():
    """서랍 밖으로 빠진 검출은 결과 물체가 없어 짝 없음."""
    m = _match([det_at(0.05, 0.10), det_at(0.15, 0.22)], [obj(1, 0.15, 0.22)], K, T)
    assert list(m) == [1]


def test_crop_box_is_16_9_and_contains_drawer():
    """잘라낼 상자는 16:9, 서랍 안쪽 네 모서리(화면 안 부분)를 포함."""
    x0, y0, x1, y1 = _crop_box(K, T, INTERIOR, 1280, 720)
    assert (x1 - x0) / (y1 - y0) == pytest.approx(16 / 9, abs=0.02)
    for x in (0, INTERIOR[0]):
        for y in (0, INTERIOR[1]):
            u, v = px(x, y)                            # 서랍이 화면 밖으로 나가면 화면 끝까지
            assert x0 <= min(max(u, 0), 1280) <= x1 and y0 <= min(max(v, 0), 720) <= y1


@pytest.mark.parametrize("dets,result,Tm", [
    ([det_at(0.05, 0.10), det_at(0.15, 0.22)], {"target": obj(1, 0.05, 0.10, occ=[]), "candidates": [obj(2, 0.15, 0.22, False, ["eraser#1"])]}, T),
    ([det_at(0.05, 0.10)], {}, T),                     # 실패 요청(REGION_NOT_VISIBLE 등): 결과 없이 검출만
    ([], {}, None),                                    # TF_UNAVAILABLE: 검출 없이 사진만
])
def test_render_gives_fixed_size_jpeg(dets, result, Tm):
    color = np.full((720, 1280, 3), 120, np.uint8)
    rgb = render_overlay(color, dets, result, K, Tm, INTERIOR, ITEMS, {"region": "drawer_top", "search_target": "eraser"}, "10:10:05",
                         error_code="" if result else "DEPTH_INVALID")
    assert rgb.shape == (OUT_H, OUT_W, 3) and rgb.dtype == np.uint8
    jpg = encode_jpeg(rgb, 85)
    assert jpg[:2] == b"\xff\xd8" and len(jpg) < 400_000


def test_render_without_korean_font_falls_back():
    """한글 글꼴이 없으면 영문 클래스 키로 — 예외 없이 그림."""
    rgb = render_overlay(np.zeros((720, 1280, 3), np.uint8), [det_at(0.05, 0.10)], {"target": obj(1, 0.05, 0.10)}, K, T, INTERIOR, ITEMS,
                         {"region": "drawer_top", "search_target": "eraser"}, "10:10:05", font_paths=("/nonexistent.ttf",))
    assert rgb.shape == (OUT_H, OUT_W, 3)


def test_label_skipped_when_center_outside_crop():
    """서랍 밖 오검출(중심이 잘라낸 사진 밖)은 라벨·연결선을 그리지 않음 — 10/11 덤프 에어팟 오검출 선이 화면 끝까지 그어지던 것."""
    far = det_at(0.40, 0.15)                                                    # 서랍(0~0.20) 훨씬 밖
    inside = render_overlay(np.zeros((720, 1280, 3), np.uint8), [det_at(0.05, 0.10)], {"target": obj(1, 0.05, 0.10)}, K, T, INTERIOR,
                            ITEMS, {"region": "drawer_top", "search_target": "eraser"}, "10:10:05")
    both = render_overlay(np.zeros((720, 1280, 3), np.uint8), [det_at(0.05, 0.10), far], {"target": obj(1, 0.05, 0.10)}, K, T, INTERIOR,
                          ITEMS, {"region": "drawer_top", "search_target": "eraser"}, "10:10:05")
    assert np.array_equal(inside, both)


def test_latest_slot_keeps_newest_and_drops_older_shots():
    """작업 대기: 안 그린 요청은 새 요청이 덮음, 발행한 촬영보다 오래된 촬영은 버림, 같은 촬영 시각은 발행(계약 '오래된 경우 생략')."""
    q = LatestSlot()
    assert q.take(timeout=0.01) is None
    q.put({"stamp_ns": 10}); q.put({"stamp_ns": 20})
    assert q.take(timeout=0.01)["stamp_ns"] == 20 and q.take(timeout=0.01) is None
    q.published(20)
    q.put({"stamp_ns": 15})
    assert q.take(timeout=0.01) is None                                        # 이미 발행한 것보다 오래됨
    q.put({"stamp_ns": 20})
    assert q.take(timeout=0.01)["stamp_ns"] == 20                              # 같은 촬영 시각은 발행
    q.put({"stamp_ns": 30}); q.put({"stamp_ns": 25})                           # [E #370 P2] 늦게 끝난 이전 촬영(25)이 대기 중 최신(30)을 덮지 않음
    assert q.take(timeout=0.01)["stamp_ns"] == 30
    q.put({"stamp_ns": 40, "v": 1}); q.put({"stamp_ns": 40, "v": 2})           # 같은 촬영 시각은 나중 것으로 덮음
    assert q.take(timeout=0.01)["v"] == 2
