"""YOLO 박스 안의 뎁스 덩어리로 top_z 와 yaw 를 구한다 (V2 기준선, docs/vision.md V2). ROS 비의존, numpy + OpenCV.

분할 모델이면 박스 안에서도 그 물체 마스크(경계 mask_erode_px 만큼 깎음) 안의 픽셀만 쓴다 — 옆 물체·벽 뎁스가 섞이지 않게 (P2, #109).
순서: 박스(또는 마스크) 안 유효 뎁스 픽셀 → 서랍 좌표로 변환 → 서랍 바닥(z = 0)보다 floor_margin_m 이상 높은 픽셀만 덩어리 후보
→ 가장 큰 연결 덩어리 → top_z = 덩어리 높이의 top_percentile 백분위 → 덩어리 xy 의 minAreaRect 긴 변 방향 = yaw.
임계값은 전부 params(config/vision_params.yaml)에서 받는다. 코드에 상수로 두지 않는다 [팀 확정 필요].
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .geometry import Intrinsics, backproject
from .pose_rules import normalize_yaw


@dataclass
class BlobResult:
    depth_ok: bool                 # False 면 박스 안 뎁스가 쓸 수 없음 → 호출자가 DEPTH_INVALID 처리
    top_z: float | None            # 서랍 바닥 위 윗면 높이(m). 덩어리가 없으면 None
    yaw: float                     # (-pi/2, pi/2]. yaw_ok 가 False 면 0 자리표시
    yaw_ok: bool                   # 덩어리 기준으로 yaw 를 믿어도 되는가 (대칭 물체 처리는 호출자)
    reason: str = ""               # 사람이 읽는 사유 (로그용)
    n_valid: int = 0
    n_blob: int = 0
    invalid_ratio: float = 0.0
    blob_long_m: float = 0.0
    blob_short_m: float = 0.0


def _cv2():
    import cv2   # 지연 import: 이 모듈의 다른 부분과 테스트에서 OpenCV 없이도 import 가능
    return cv2


def _long_axis_yaw(xy: np.ndarray):
    """덩어리 xy(m)의 minAreaRect 긴 변 방향(rad, 서랍 x축 기준)과 긴·짧은 변 길이."""
    cv2 = _cv2()
    rect = cv2.minAreaRect(xy.astype(np.float32))
    box = cv2.boxPoints(rect)                       # 4 꼭짓점. 각도 규약이 OpenCV 버전마다 달라 꼭짓점에서 직접 구한다
    e1, e2 = box[1] - box[0], box[2] - box[1]
    long_e = e1 if np.linalg.norm(e1) >= np.linalg.norm(e2) else e2
    long_m, short_m = float(max(np.linalg.norm(e1), np.linalg.norm(e2))), float(min(np.linalg.norm(e1), np.linalg.norm(e2)))
    return normalize_yaw(math.atan2(long_e[1], long_e[0])), long_m, short_m


def analyze_box(depth_m: np.ndarray, box, K: Intrinsics, T_drawer_cam: np.ndarray, params: dict,
                nominal_long_m: float | None = None, mask: np.ndarray | None = None) -> BlobResult:
    """box = (x1, y1, x2, y2) 픽셀. depth_m = 컬러에 정렬된 뎁스(m), 0·NaN·범위 밖은 결손.
    mask = 이미지 크기 bool (분할 모델 출력). 주면 그 안만 보고 결손 비율도 마스크 넓이 기준. 깎아서 비면 깎기 전 마스크."""
    cv2 = _cv2()
    h, w = depth_m.shape
    m = int(params["roi_margin_px"])
    x1, y1 = max(int(math.floor(box[0])) - m, 0), max(int(math.floor(box[1])) - m, 0)
    x2, y2 = min(int(math.ceil(box[2])) + m, w), min(int(math.ceil(box[3])) + m, h)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return BlobResult(False, None, 0.0, False, "박스가 이미지 밖이거나 너무 작음")
    roi = depth_m[y1:y2, x1:x2]
    valid = np.isfinite(roi) & (roi >= params["min_depth_m"]) & (roi <= params["max_depth_m"])
    area = roi.size
    if mask is not None:
        region = mask[y1:y2, x1:x2].astype(bool)
        k = int(params.get("mask_erode_px", 0))
        if k > 0:
            eroded = cv2.erode(region.astype(np.uint8), np.ones((2 * k + 1, 2 * k + 1), np.uint8)) > 0
            region = eroded if eroded.any() else region
        if not region.any():
            return BlobResult(False, None, 0.0, False, "마스크가 박스 안에 없음")
        valid &= region
        area = int(region.sum())
    n_valid = int(valid.sum())
    invalid_ratio = 1.0 - n_valid / area
    if n_valid < params["min_valid_px"] or invalid_ratio > params["max_invalid_ratio"]:
        return BlobResult(False, None, 0.0, False, f"유효 뎁스 부족 (유효 {n_valid}px, 결손 비율 {invalid_ratio:.2f})",
                          n_valid=n_valid, invalid_ratio=invalid_ratio)
    vs, us = np.nonzero(valid)
    pts = backproject((us + x1).astype(float), (vs + y1).astype(float), roi[vs, us].astype(float), K, T_drawer_cam)
    above = pts[:, 2] > params["floor_margin_m"]
    if not above.any():
        return BlobResult(True, None, 0.0, False, "서랍 바닥 위로 올라온 뎁스 없음", n_valid=n_valid, invalid_ratio=invalid_ratio)
    mask = np.zeros(roi.shape, np.uint8)
    mask[vs[above], us[above]] = 1
    n_lab, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n_lab <= 1:
        return BlobResult(True, None, 0.0, False, "덩어리 없음", n_valid=n_valid, invalid_ratio=invalid_ratio)
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    in_blob = labels[vs, us] == best
    blob = pts[in_blob]
    n_blob = int(in_blob.sum())
    top_z = float(np.percentile(blob[:, 2], params["top_percentile"]))
    base = dict(depth_ok=True, top_z=top_z, n_valid=n_valid, n_blob=n_blob, invalid_ratio=invalid_ratio)
    if n_blob < params["min_blob_px"]:
        return BlobResult(yaw=0.0, yaw_ok=False, reason=f"덩어리가 작음 ({n_blob}px)", **base)
    yaw, long_m, short_m = _long_axis_yaw(blob[:, :2])
    base.update(blob_long_m=long_m, blob_short_m=short_m)
    if short_m < params["min_short_side_m"]:
        return BlobResult(yaw=0.0, yaw_ok=False, reason=f"덩어리가 너무 얇음 (짧은 변 {short_m * 1000:.1f} mm)", **base)
    if nominal_long_m is not None:
        tol = params["size_tolerance"]
        if not (nominal_long_m * (1 - tol) <= long_m <= nominal_long_m * (1 + tol)):
            return BlobResult(yaw=0.0, yaw_ok=False,
                              reason=f"덩어리 긴 변 {long_m * 1000:.0f} mm 가 명목 {nominal_long_m * 1000:.0f} mm 와 크게 다름 (겹침·병합 의심)", **base)
    return BlobResult(yaw=yaw, yaw_ok=True, **base)
