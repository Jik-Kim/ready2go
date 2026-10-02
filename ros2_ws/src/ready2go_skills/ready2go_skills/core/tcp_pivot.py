"""피벗(4점) 방식으로 플랜지 → 손끝 오프셋 계산 (ROS 비의존, pytest 대상).

손끝을 고정된 한 점에 댄 채 손목 자세만 바꿔 플랜지 포즈 (R_i, p_i)를 여러 개 기록하면
    R_i · t + p_i = c      (t: 플랜지 기준 손끝 오프셋, c: 고정점의 base 좌표)
를 최소제곱으로 푼다.
"""
from dataclasses import dataclass

import numpy as np

from ready2go_skills.core.frames import posx_to_rt, rotation_angle_deg

MIN_POSES = 4
MIN_SPREAD_DEG = 20.0   # 자세 간 최대 회전 차이가 이보다 작으면 z 해가 불안정 [추정]


@dataclass(frozen=True)
class PivotResult:
    tip_in_flange_mm: np.ndarray   # t
    pivot_in_base_mm: np.ndarray   # c
    residuals_mm: np.ndarray       # 자세별 |R_i t + p_i − c|
    max_spread_deg: float          # 자세 간 최대 회전 차이


def solve_pivot(flange_posx_list) -> PivotResult:
    if len(flange_posx_list) < MIN_POSES:
        raise ValueError(f"자세가 {MIN_POSES}개 이상 필요함: {len(flange_posx_list)}")
    poses = [posx_to_rt(p) for p in flange_posx_list]
    a = np.vstack([np.hstack([r, -np.eye(3)]) for r, _ in poses])
    b = np.concatenate([-p for _, p in poses])
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    t, c = sol[:3], sol[3:]
    residuals = np.array([np.linalg.norm(r @ t + p - c) for r, p in poses])
    spread = max(rotation_angle_deg(r1, r2) for r1, _ in poses for r2, _ in poses)
    return PivotResult(t, c, residuals, spread)
