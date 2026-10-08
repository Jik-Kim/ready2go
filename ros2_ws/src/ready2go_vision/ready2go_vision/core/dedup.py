"""같은 물체를 두 번 잡은 분할 검출을 하나로 합친다 (#109 4단계 선행, docs/vision.md 9장).

분할 모델이 한 물체를 전체 + 일부(망치 전체 0.94 + 손잡이만 0.68, 10/06 덤프)로 두 번 내면 Runner 가 물체를 둘로 보고
가림 판정도 꼬인다. 같은 클래스 두 검출의 마스크가 `겹친 넓이 / 작은 쪽 넓이 >= min_overlap` 이면 같은 물체로 보고
**신뢰도 높은 쪽만 그대로 남기고 낮은 쪽은 버린다.** 합집합은 하지 않는다 — 낮은 쪽은 대개 옆 물체까지 번진 마스크라
(실물 10/06: 립밤 0.41 이 지우개+립밤, 지우개 0.43 이 지우개+딱풀 끝) 합치면 박스가 커져 위치가 옆 물체 쪽으로 밀린다.
다른 클래스는 겹쳐도 합치지 않는다(위에 얹힘일 수 있음).
겹침은 연결로 본다: A-B, B-C 가 기준 이상이면 A-C 가 기준 미만이어도 A·B·C 를 한 물체로 보고 그중 가장 높은 신뢰도 하나만 남긴다(#174 리뷰).
전제: 첫 P2 시연은 한 배치에 같은 클래스 하나(#109) — 같은 클래스 실물 둘이 겹치거나, 번진 마스크 하나가 둘을 이으면 하나로 합쳐진다.
"""
from __future__ import annotations

import numpy as np


def _boxes_touch(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def merge_duplicates(dets: list[dict], min_overlap: float) -> tuple[list[dict], list[dict]]:
    """검출(각각 mask 필수) → (남은 검출, 빠진 중복 검출). 입력은 바꾸지 않는다. 남은 검출의 mask·box 는 그대로.
    같은 클래스끼리 `겹친 넓이 / 작은 쪽 넓이 >= min_overlap` 인 쌍을 이어 연결된 묶음마다 신뢰도 가장 높은 하나만 남긴다.
    남은 검출에 버린 중복이 있으면 merged_from = [{conf, box}](신뢰도 내림차순), 빠진 검출에는 merged_into_conf."""
    order = sorted(range(len(dets)), key=lambda i: -dets[i]["conf"])
    parent = {i: i for i in order}

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    areas = {i: int(dets[i]["mask"].sum()) for i in order}
    for x, i in enumerate(order):
        for j in order[x + 1:]:
            a, b = dets[i], dets[j]
            if a["class"] != b["class"] or not _boxes_touch(a["box"], b["box"]):
                continue
            small = min(areas[i], areas[j])
            if small and int((a["mask"] & b["mask"]).sum()) / small >= min_overlap:
                ri, rj = root(i), root(j)
                if ri != rj:                                   # 묶음 대표 = 신뢰도 높은 쪽(order 앞쪽)
                    if order.index(ri) > order.index(rj):
                        ri, rj = rj, ri
                    parent[rj] = ri
    kept: list[dict] = []
    dropped: list[dict] = []
    host_of = {}
    for i in order:                                            # 신뢰도 내림차순이라 대표가 먼저 나옴
        r = root(i)
        if r == i:
            host_of[i] = dict(dets[i])
            kept.append(host_of[i])
            continue
        host = host_of[r]
        host.setdefault("merged_from", []).append({"conf": dets[i]["conf"], "box": [float(v) for v in dets[i]["box"]]})
        dropped.append({**{k: v for k, v in dets[i].items() if k != "mask"}, "merged_into_conf": host["conf"]})
    return kept, dropped
