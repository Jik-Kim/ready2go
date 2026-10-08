"""같은 물체 중복 검출 병합 (#109 4단계 선행, 분할 모델 전용)."""
import pytest

np = pytest.importorskip("numpy")
from ready2go_vision.core.dedup import merge_duplicates  # noqa: E402


def rect(y0, x0, y1, x1, shape=(100, 200)):
    m = np.zeros(shape, bool)
    m[y0:y1, x0:x1] = True
    return m


def det(cls, conf, m):
    ys, xs = np.nonzero(m)
    return {"class": cls, "conf": conf, "box": (float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)), "mask": m}


def test_part_inside_whole_keeps_higher_conf_as_is():
    whole, handle = rect(10, 10, 40, 150), rect(15, 60, 35, 150)     # 망치 전체 0.94 + 손잡이만 0.68 (10/06 061042)
    kept, dropped = merge_duplicates([det("toy_hammer", 0.68, handle), det("toy_hammer", 0.94, whole)], 0.6)
    assert len(kept) == 1 and kept[0]["conf"] == 0.94 and (kept[0]["mask"] == whole).all()
    assert kept[0]["box"] == (10.0, 10.0, 150.0, 40.0)
    assert kept[0]["merged_from"] == [{"conf": 0.68, "box": [60.0, 15.0, 150.0, 35.0]}]
    assert [d["conf"] for d in dropped] == [0.68] and dropped[0]["merged_into_conf"] == 0.94


def test_spilled_low_conf_mask_is_dropped_not_unioned():
    """낮은 쪽이 옆 물체까지 번진 마스크(10/06 립밤 0.41 = 지우개+립밤)면 합집합하지 않고 버린다 — 높은 쪽 박스·위치 그대로."""
    good, spilled = rect(50, 10, 90, 40), rect(10, 10, 90, 40)        # 립밤만 0.42 / 지우개(위)+립밤 0.41, 겹침 / 작은 쪽 = 1.0
    kept, dropped = merge_duplicates([det("lip_balm", 0.42, good), det("lip_balm", 0.41, spilled)], 0.6)
    assert len(kept) == 1 and (kept[0]["mask"] == good).all() and kept[0]["box"] == (10.0, 50.0, 40.0, 90.0)
    assert dropped[0]["conf"] == 0.41


@pytest.mark.parametrize("cls_b, mb, n", [
    ("eraser", rect(10, 10, 40, 100), 2),          # 다른 클래스는 겹쳐도 그대로 (위에 얹힘일 수 있음)
    ("toy_wrench", rect(60, 10, 90, 100), 2),      # 같은 클래스라도 떨어져 있으면 그대로
    ("toy_wrench", rect(10, 80, 40, 170), 2),      # 겹침 20/90 = 0.22 < 0.6
])
def test_not_merged(cls_b, mb, n):
    kept, dropped = merge_duplicates([det("toy_wrench", 0.9, rect(10, 10, 40, 100)), det(cls_b, 0.8, mb)], 0.6)
    assert len(kept) == n and dropped == []


def test_three_detections_chain_into_one_and_input_not_modified():
    a, b, c = rect(10, 10, 40, 100), rect(12, 20, 38, 90), rect(15, 30, 35, 80)
    dets = [det("toy_hammer", 0.5, c), det("toy_hammer", 0.9, a), det("toy_hammer", 0.7, b)]
    before = [d["mask"].copy() for d in dets]
    kept, dropped = merge_duplicates(dets, 0.6)
    assert len(kept) == 1 and len(dropped) == 2 and [m["conf"] for m in kept[0]["merged_from"]] == [0.7, 0.5]
    assert all((d["mask"] == m).all() for d, m in zip(dets, before)) and "merged_from" not in dets[1]
