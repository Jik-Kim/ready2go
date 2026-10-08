"""tools/yolo/seg_merge.py 테스트: 가려져 조각난 분할 라벨을 상자 라벨 기준으로 물체 하나로 합친다(#109). 표준 라이브러리만 사용."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/yolo"))
from seg_merge import merge_image, merge_polygons  # noqa: E402

SQ = lambda x, y, s=0.05: [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]   # noqa: E731


def test_two_pieces_inside_one_box_become_one_object():
    pieces = [(9, SQ(0.10, 0.10)), (9, SQ(0.30, 0.10)), (2, SQ(0.20, 0.10))]   # 망치 두 조각 사이에 차키
    boxes = [(9, (0.09, 0.09, 0.36, 0.16)), (2, (0.19, 0.09, 0.26, 0.16))]
    objs, rep = merge_image(pieces, boxes)
    assert sorted(c for c, _ in objs) == [2, 9]
    assert rep == {"merged": 1, "new": [], "no_poly": [], "outside": []}
    hammer = next(p for c, p in objs if c == 9)
    assert len(hammer) == 4 + 4 + 2            # 두 조각 꼭짓점 + 통로 왕복 2점


def test_same_class_two_boxes_stay_separate():
    pieces = [(3, SQ(0.10, 0.10)), (3, SQ(0.60, 0.60))]                       # 지우개 2개
    boxes = [(3, (0.09, 0.09, 0.16, 0.16)), (3, (0.59, 0.59, 0.66, 0.66))]
    objs, rep = merge_image(pieces, boxes)
    assert len(objs) == 2 and rep["merged"] == 0


def test_piece_outside_single_box_is_attached_and_reported():
    pieces = [(9, SQ(0.10, 0.10)), (9, SQ(0.50, 0.50))]                       # 상자가 위 조각만 감쌈
    objs, rep = merge_image(pieces, [(9, (0.09, 0.09, 0.16, 0.16))])
    assert len(objs) == 1 and rep["outside"] == [9] and rep["merged"] == 1


def test_piece_without_box_is_new_and_box_without_polygon_reported():
    pieces = [(2, SQ(0.10, 0.10)), (2, SQ(0.20, 0.10))]                       # 상자 라벨에 없던 차키(두 조각)
    objs, rep = merge_image(pieces, [(10, (0.0, 0.0, 0.1, 0.6))])             # 윤곽 없는 판 상자
    assert len(objs) == 1 and rep["new"] == [2] and rep["no_poly"] == [10]


def test_merge_single_polygon_unchanged():
    assert merge_polygons([SQ(0.1, 0.1)]) == SQ(0.1, 0.1)
    assert merge_polygons([[(0, 0), (1, 1)]]) == []                           # 꼭짓점 2개는 버림
