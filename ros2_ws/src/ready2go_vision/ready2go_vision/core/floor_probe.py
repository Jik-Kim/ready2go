"""진단용: 카메라 뎁스로 본 서랍 바닥의 서랍 좌표 z (ROS 비의존, numpy 만 사용).

결과(result_json)에는 쓰지 않고 로그·덤프에만 남긴다. 목적은 #83 원점 보정(손끝 터치) 뒤 카메라 기준 바닥이
약 3 mm 높게 보이는 차이(#83 코멘트)의 원인을 실물 데이터로 가리는 것. 바닥을 요청마다 재서 높이 기준으로 쓰는
방식은 계약 검토 전이라 여기서 하지 않는다(#80 E 코멘트).

순서: 이미지를 stride_px 간격으로 표본 → 유효 뎁스 → 서랍 좌표로 변환 → 벽에서 wall_margin_m 이상 떨어진 안쪽,
|z| <= max_abs_z_m, 검출 박스(+box_margin_px) 밖인 점만 → z 의 중앙값·10/90 백분위.
"""
from __future__ import annotations

import numpy as np

from .geometry import Intrinsics, backproject


def floor_probe(depth_m: np.ndarray, K: Intrinsics, T_drawer_cam: np.ndarray, interior, boxes, params: dict) -> dict:
    """{"n": 표본 수, "z_median_m", "z_p10_m", "z_p90_m"} (n == 0 이면 z 키 없음)."""
    s = int(params["stride_px"])
    h, w = depth_m.shape
    vs, us = np.mgrid[0:h:s, 0:w:s]
    us, vs = us.ravel(), vs.ravel()
    keep = np.ones(us.shape, bool)
    m = int(params["box_margin_px"])
    for b in boxes:
        keep &= ~((us >= b[0] - m) & (us <= b[2] + m) & (vs >= b[1] - m) & (vs <= b[3] + m))
    d = depth_m[vs, us]
    keep &= np.isfinite(d) & (d >= params["min_depth_m"]) & (d <= params["max_depth_m"])
    if not keep.any():
        return {"n": 0}
    pts = backproject(us[keep].astype(float), vs[keep].astype(float), d[keep].astype(float), K, T_drawer_cam)
    wm = params["wall_margin_m"]
    inside = ((pts[:, 0] >= wm) & (pts[:, 0] <= interior[0] - wm) & (pts[:, 1] >= wm) & (pts[:, 1] <= interior[1] - wm)
              & (np.abs(pts[:, 2]) <= params["max_abs_z_m"]))
    z = pts[inside, 2]
    if z.size == 0:
        return {"n": 0}
    p10, p50, p90 = np.percentile(z, [10, 50, 90])
    return {"n": int(z.size), "z_median_m": round(float(p50), 4), "z_p10_m": round(float(p10), 4), "z_p90_m": round(float(p90), 4)}
