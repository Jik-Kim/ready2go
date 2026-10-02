"""두산 posx(mm, deg, ZYZ 오일러각) ↔ 회전 행렬 변환 (ROS 비의존, pytest 대상).

posx = [x, y, z, A, B, C], 회전 R = Rz(A)·Ry(B)·Rz(C) [문서: 두산 매뉴얼, tools/calib_derive_tf.py와 동일 규약].
"""
import numpy as np


def _rz(deg: float) -> np.ndarray:
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _ry(deg: float) -> np.ndarray:
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def posx_to_rt(posx) -> tuple[np.ndarray, np.ndarray]:
    """posx(6개 이상, 7번째 sol 등은 무시) → (R 3x3, t mm)."""
    x, y, z, a, b, c = (float(v) for v in posx[:6])
    return _rz(a) @ _ry(b) @ _rz(c), np.array([x, y, z])


def rotation_angle_deg(r1: np.ndarray, r2: np.ndarray) -> float:
    """두 회전 사이 각도(deg)."""
    cos = (np.trace(r1.T @ r2) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))
