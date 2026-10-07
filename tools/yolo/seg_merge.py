"""분할(폴리곤) 라벨에서 한 물체의 여러 조각을 하나로 합친다 (담당 A, #109). 표준 라이브러리만 사용 — CI 에서 cv2 없이 시험한다.

Roboflow 에서는 다른 물체에 가려 조각난 물체를 같은 클래스 다각형 여러 개로 그린다. YOLO 분할 형식은 물체 하나 = 줄 하나라서,
사람이 확인한 상자 라벨(data/labeled)을 기준으로 조각을 물체에 배정하고, 같은 물체 조각은 가장 가까운 점끼리 폭 0 통로로 이어
다각형 하나로 만든다(Ultralytics merge_multi_segment 와 같은 생각: 칠하면 조각들만 칠해진다).
- 조각 배정: 같은 클래스 상자 중 조각 꼭짓점이 가장 많이 들어가는(여유 margin) 상자. 절반 이상 들어가는 상자가 없으면 "상자 없음".
- 상자 밖 조각: 그 장에 같은 클래스 상자가 하나뿐이면 그 물체의 조각으로 본다(상자가 물체 일부만 감싼 경우, "outside" 로 보고 → 상자 보정).
  같은 클래스 상자가 없으면 상자 라벨에 빠진 물체(윤곽 라벨링 중 새로 찾은 것 등) → 같은 클래스끼리 한 물체로 합치고 "new" 로 보고한다.
좌표는 모두 0~1 정규화.
"""
from __future__ import annotations

Point = tuple[float, float]


def frac_inside(poly: list[Point], box: tuple[float, float, float, float], margin: float) -> float:
    x1, y1, x2, y2 = box
    n = sum(1 for x, y in poly if x1 - margin <= x <= x2 + margin and y1 - margin <= y <= y2 + margin)
    return n / len(poly) if poly else 0.0


def assign_pieces(pieces: list[tuple[int, list[Point]]], boxes: list[tuple[int, tuple[float, float, float, float]]],
                  margin: float = 0.01, min_frac: float = 0.5) -> list[int | None]:
    """조각마다 배정된 상자 번호(없으면 None)."""
    out = []
    for c, poly in pieces:
        best, best_f = None, min_frac
        for j, (bc, box) in enumerate(boxes):
            if bc != c:
                continue
            f = frac_inside(poly, box, margin)
            if f > best_f or (best is None and f >= best_f):
                best, best_f = j, f
        out.append(best)
    return out


def _d2(a: Point, b: Point) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def merge_polygons(polys: list[list[Point]]) -> list[Point]:
    """여러 조각을 폭 0 통로로 이어 다각형 하나로. 조각 하나면 그대로."""
    polys = [p for p in polys if len(p) >= 3]
    if not polys:
        return []
    path = list(polys[0])
    for p in polys[1:]:
        ia, ib = min(((i, j) for i in range(len(path)) for j in range(len(p))), key=lambda ij: _d2(path[ij[0]], p[ij[1]]))
        loop = p[ib:] + p[:ib] + [p[ib]]                    # 조각을 b 에서 시작해 한 바퀴 돌고 b 로 돌아옴
        path = path[:ia + 1] + loop + [path[ia]] + path[ia + 1:]
    return path


def merge_image(pieces: list[tuple[int, list[Point]]], boxes: list[tuple[int, tuple[float, float, float, float]]],
                margin: float = 0.01) -> tuple[list[tuple[int, list[Point]]], dict]:
    """한 장의 조각들 → 물체별 다각형. 반환 (물체 목록, 보고 {merged: 합친 물체 수, new: 상자 없는 클래스들, no_poly: 윤곽 없는 상자 클래스들, outside: 상자 밖 조각 클래스들})."""
    owner = assign_pieces(pieces, boxes, margin)
    outside = []
    for k, j in enumerate(owner):
        if j is None:
            same = [b for b in range(len(boxes)) if boxes[b][0] == pieces[k][0]]
            if len(same) == 1:
                owner[k] = same[0]
                outside.append(pieces[k][0])
    groups: dict[object, list[int]] = {}
    for k, j in enumerate(owner):
        key = ("box", j) if j is not None else ("new", pieces[k][0])
        groups.setdefault(key, []).append(k)
    objs, merged, new = [], 0, []
    for key in sorted(groups, key=lambda g: (g[0], g[1])):
        ks = groups[key]
        c = pieces[ks[0]][0]
        objs.append((c, merge_polygons([pieces[k][1] for k in ks])))
        merged += len(ks) > 1
        if key[0] == "new":
            new.append(c)
    no_poly = [boxes[j][0] for j in range(len(boxes)) if ("box", j) not in groups]
    return objs, {"merged": merged, "new": new, "no_poly": no_poly, "outside": outside}
