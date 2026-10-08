"""분할 마스크 덤프 저장·복원, 재계산 도구 왕복, 검출기 마스크 분기 (#163 리뷰 회귀 시험)."""
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
from ready2go_vision.core.dump_masks import restore_masks, split_masks  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]


def _dets(h, w, n):
    rng = np.random.default_rng(0)
    return [{"class": "eraser", "conf": 0.9 - i * 0.1, "box": (1.0, 2.0, 3.0, 4.0), "mask": rng.random((h, w)) > 0.5} for i in range(n)]


@pytest.mark.parametrize("width", [1280, 1279, 7])
def test_split_restore_round_trip_keeps_order_and_odd_width(width):
    dets = _dets(5, width, 3)
    plain, extra = split_masks(dets)
    json.dumps(plain)                                                  # 배열이 섞이지 않아 JSON 가능
    assert all("mask" not in d for d in plain) and extra["masks"].shape == (3, 5, (width + 7) // 8)
    back = restore_masks([dict(d) for d in plain], extra["masks"], width)
    for a, b in zip(dets, back):
        assert b["mask"].shape == (5, width) and (a["mask"] == b["mask"]).all() and a["conf"] == b["conf"]


def test_box_model_dump_has_no_masks_and_restore_is_noop():
    dets = [{"class": "eraser", "conf": 0.9, "box": (1.0, 2.0, 3.0, 4.0)}]
    plain, extra = split_masks(dets)
    assert extra == {} and restore_masks(plain, None, 1280) == plain and "mask" not in plain[0]
    with pytest.raises(ValueError):
        restore_masks(plain, split_masks(_dets(2, 8, 2))[1]["masks"], 8)       # 마스크 2개 vs 검출 1개


def test_replay_tool_restores_masks_from_node_format_dump(tmp_path):
    """노드 _save 와 같은 형식(split_masks)의 덤프를 replay_inspect_dump.py 가 마스크 뎁스로 다시 계산."""
    pytest.importorskip("cv2")
    pytest.importorskip("yaml")
    from test_inspect_real import INTERIOR, K, T, box_of, mask_of, scene
    er = (0.08, 0.15, 0.0, (0.0525, 0.022), 0.0115)
    tall = (0.08, 0.15 + 0.011 + 0.010, 0.0, (0.06, 0.02), 0.040)
    depth = scene(*er, extra=[tall])
    det = {"class": "eraser", "conf": 0.9, "box": box_of(er[0], er[1], er[3], er[2]), "mask": mask_of(*er)[:, :1279]}
    plain, extra = split_masks([det])
    meta = {"request": {"region": "drawer_top", "search_target": "eraser"}, "success": True, "error_code": "", "result_json": "",
            "detections": plain, "debug": [], "floor": {}, "K": [K.fx, K.fy, K.cx, K.cy], "versions": {}, "interior_m": INTERIOR}
    color = np.zeros((720, 1279, 3), np.uint8)
    np.savez_compressed(tmp_path / "inspect_x.npz", **extra, color=color, depth_m=depth[:, :1279].astype(np.float32),
                        T_base_cam=T, T_base_drawer=np.eye(4), T_drawer_cam=T, meta=np.array(json.dumps(meta, default=float)))
    out = subprocess.run([sys.executable, str(ROOT / "tools/dev/replay_inspect_dump.py"), str(tmp_path / "inspect_x.npz")],
                         capture_output=True, text=True, check=True).stdout
    assert '"depth_src": "mask"' in out
    top_z = json.loads(out.split("재계산 success=True  ", 1)[1].splitlines()[0])["target"]["top_z"]
    assert top_z == pytest.approx(0.0115, abs=0.002)                   # 박스였다면 이웃 40 mm 가 섞임


def test_detector_attaches_masks_only_for_segment_models(monkeypatch):
    """ultralytics 없이 가짜 YOLO 로 검출기 분기 확인: 분할 모델이면 retina_masks + 검출 순서대로 마스크."""
    calls = {}

    class Arr:
        def __init__(self, a): self.a = np.asarray(a)
        def tolist(self): return self.a.tolist()
        def cpu(self): return self
        def numpy(self): return self.a
        def __getitem__(self, i): return Arr(self.a[i]) if np.ndim(self.a[i]) else self.a[i]

    class Box:
        def __init__(self, xyxy, c, s): self.xyxy, self.cls, self.conf = Arr([xyxy]), Arr([c]), Arr([s])

    class FakeYOLO:
        def __init__(self, w): self.task = "segment" if "seg" in w else "detect"; self.names = {0: "eraser", 1: "car_key"}
        def predict(self, img, **kw):
            calls.update(kw)
            r = types.SimpleNamespace(boxes=[Box([1, 2, 3, 4], 1, 0.8), Box([5, 6, 7, 8], 0, 0.6)], masks=None)
            if self.task == "segment":
                m = np.zeros((2, 4, 6)); m[0, 0, 0] = 1; m[1, 3, 5] = 1
                r.masks = types.SimpleNamespace(data=Arr(m))
            return [r]

    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=FakeYOLO))
    from ready2go_vision.core.detector import YoloDetector
    seg = YoloDetector("x_seg.pt").detect(np.zeros((4, 6, 3), np.uint8))
    assert calls["retina_masks"] is True and [d["class"] for d in seg] == ["car_key", "eraser"]
    assert seg[0]["mask"][0, 0] and not seg[0]["mask"][3, 5] and seg[1]["mask"][3, 5]
    box = YoloDetector("x.pt").detect(np.zeros((4, 6, 3), np.uint8))
    assert calls["retina_masks"] is False and all("mask" not in d for d in box)
