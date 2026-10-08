"""같은 물체를 두 번 잡은 분할 검출을 하나로 합친다 (#109 4단계 선행, docs/vision.md 9장).

분할 모델이 한 물체를 전체 + 일부(망치 전체 0.94 + 손잡이만 0.68, 10/06 덤프)로 두 번 내면 Runner 가 물체를 둘로 보고
가림 판정도 꼬인다. 같은 클래스 두 검출의 마스크가 `겹친 넓이 / 작은 쪽 넓이 >= min_overlap` 이면 같은 물체로 보고
**신뢰도 높은 쪽만 그대로 남기고 낮은 쪽은 버린다.** 합집합은 하지 않는다 — 낮은 쪽은 대개 옆 물체까지 번진 마스크라
(실물 10/06: 립밤 0.41 이 지우개+립밤, 지우개 0.43 이 지우개+딱풀 끝) 합치면 박스가 커져 위치가 옆 물체 쪽으로 밀린다.
다른 클래스는 겹쳐도 합치지 않는다(위에 얹힘일 수 있음).
전제: 한 배치에 같은 클래스 두 개를 두지 않는다(P2 시연 조건, #120) — 같은 클래스 실물 둘이 겹쳐 있으면 하나로 합쳐진다.
"""
from __future__ import annotations

import numpy as np


def _boxes_touch(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def merge_duplicates(dets: list[dict], min_overlap: float) -> tuple[list[dict], list[dict]]:
    """검출(각각 mask 필수) → (남은 검출, 빠진 중복 검출). 입력은 바꾸지 않는다. 남은 검출의 mask·box 는 그대로.
    남은 검출에 버린 중복이 있으면 merged_from = [{conf, box}](신뢰도 내림차순), 빠진 검출에는 merged_into_conf."""
    kept: list[dict] = []
    dropped: list[dict] = []
    for d in sorted(dets, key=lambda x: -x["conf"]):
        m = d["mask"]
        area = int(m.sum())
        host = None
        for k in kept:
            if k["class"] != d["class"] or not _boxes_touch(k["box"], d["box"]):
                continue
            small = min(area, int(k["mask"].sum()))
            if small and int((k["mask"] & m).sum()) / small >= min_overlap:
                host = k
                break
        if host is None:
            kept.append(dict(d))
            continue
        host.setdefault("merged_from", []).append({"conf": d["conf"], "box": [float(v) for v in d["box"]]})
        dropped.append({**{k: v for k, v in d.items() if k != "mask"}, "merged_into_conf": host["conf"]})
    return kept, dropped
