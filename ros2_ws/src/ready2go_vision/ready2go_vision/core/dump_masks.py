"""inspect_region 덤프(.npz)의 분할 마스크 저장·복원 (노드 _save 와 tools/dev/replay_inspect_dump.py 가 같이 쓴다).

meta.detections 에는 JSON 으로 쓸 수 있는 값만 두고, 마스크는 npz 의 masks(N, H, ceil(W/8)) packbits 로 같은 순서로 저장한다.
모든 검출에 마스크가 있을 때만 저장한다(박스 모델이면 masks 없음).
"""
from __future__ import annotations

import numpy as np


def split_masks(dets: list[dict]) -> tuple[list[dict], dict]:
    """검출 목록 → (마스크를 뺀 검출 목록, npz 에 추가할 배열 dict)."""
    plain = [{k: v for k, v in d.items() if k != "mask"} for d in dets]
    masks = [d["mask"] for d in dets if "mask" in d]
    extra = {"masks": np.packbits(np.stack(masks).astype(bool), axis=-1)} if masks and len(masks) == len(dets) else {}
    return plain, extra


def restore_masks(dets: list[dict], packed: np.ndarray | None, width: int) -> list[dict]:
    """split_masks 로 저장한 masks 를 검출 순서대로 다시 붙인다. packed 가 없으면 그대로."""
    if packed is None:
        return dets
    if len(packed) != len(dets):
        raise ValueError(f"덤프 masks {len(packed)}개와 검출 {len(dets)}개 수가 다름")
    for d, m in zip(dets, np.unpackbits(packed, axis=-1)[..., :width].astype(bool)):
        d["mask"] = m
    return dets
