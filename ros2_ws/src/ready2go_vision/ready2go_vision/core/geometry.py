"""픽셀·뎁스 ↔ 서랍 좌표계 변환 (ROS 비의존, numpy 만 사용).

- 카메라 광학 프레임: z 앞, x 오른쪽, y 아래 (RealSense/OpenCV 규약). 뎁스 값은 z 방향 거리(m).
- 서랍 좌표계: config/places.yaml 첫 부분 (원점 = 상자 안쪽 바닥 앞쪽 오른쪽 모서리, x 안쪽·y 왼쪽·z 위).
- T_drawer_cam = inv(T_base_drawer) @ T_base_cam : 광학 프레임 점을 서랍 좌표로 옮기는 4x4 (열벡터 규약).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Intrinsics:
    fx: float
    fy: float
    cx: float
    cy: float


def quat_to_R(q) -> np.ndarray:
    x, y, z, w = (float(v) for v in q)
    n = np.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def make_T(translation, quaternion_xyzw) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = quat_to_R(quaternion_xyzw)
    T[:3, 3] = translation
    return T


def drawer_from_camera(T_base_drawer: np.ndarray, T_base_cam: np.ndarray) -> np.ndarray:
    return np.linalg.inv(T_base_drawer) @ T_base_cam


def backproject(us: np.ndarray, vs: np.ndarray, depth_m: np.ndarray, K: Intrinsics, T_drawer_cam: np.ndarray) -> np.ndarray:
    """픽셀 (u, v)·뎁스(m) → 서랍 좌표 (N, 3). 입력은 같은 길이의 1차원 배열."""
    x = (us - K.cx) / K.fx * depth_m
    y = (vs - K.cy) / K.fy * depth_m
    pts = np.stack([x, y, depth_m, np.ones_like(depth_m)], axis=0)
    return (T_drawer_cam @ pts)[:3].T


def ray_plane_xy(u: float, v: float, K: Intrinsics, T_drawer_cam: np.ndarray, z_plane: float):
    """픽셀을 지나는 광선과 서랍 좌표 z = z_plane 평면의 교점 (x, y). 광선이 평면과 만나지 않으면 None."""
    d_cam = np.array([(u - K.cx) / K.fx, (v - K.cy) / K.fy, 1.0])
    R, o = T_drawer_cam[:3, :3], T_drawer_cam[:3, 3]
    d = R @ d_cam
    if abs(d[2]) < 1e-9:
        return None
    t = (z_plane - o[2]) / d[2]
    if t <= 0:
        return None
    p = o + t * d
    return float(p[0]), float(p[1])
