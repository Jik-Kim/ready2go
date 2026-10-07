"""M0609 + GripperDA_v1 기구학 (numpy 만, ROS·Isaac 비의존). 담당 A, 트윈 사전 검증용.

- 관절 사슬: dsr_description2 `m0609.urdf` 의 joint_1~6 origin·axis 그대로. URDF 의 rpy 1.571 은 π/2 로 본다(제어기 기구학과 같게 [추정]).
- TCP: link_6(플랜지) 에서 +z 228 mm (calibration_meta.yaml `tool_offset.offset_from_pendant`, GripperDA_v1).
- posx: 두산 규약 [x, y, z (mm), A, B, C (deg, ZYZ 오일러)] — base_link 기준 TCP.
- IK: 시작 관절각에서 출발하는 감쇠 최소제곱(DLS) 수치 해. 직선 이동 경로를 잘게 나눠 이전 해에서 이어 풀면
  제어기 movel 이 지나는 관절 경로와 같은 가지(branch)를 따른다 [추정: 제어기 내부 보간·특이점 처리와는 다를 수 있음].
"""
from __future__ import annotations

import math

import numpy as np

H = math.pi / 2
# (xyz m, rpy rad) — m0609.urdf joint_1..6 origin
JOINTS = [
    ((0.0, 0.0, 0.1345), (0.0, 0.0, 0.0)),
    ((0.0, 0.0062, 0.0), (0.0, -H, -H)),
    ((0.411, 0.0, 0.0), (0.0, 0.0, H)),
    ((0.0, -0.368, 0.0), (H, 0.0, 0.0)),
    ((0.0, 0.0, 0.0), (-H, 0.0, 0.0)),
    ((0.0, -0.121, 0.0), (H, 0.0, 0.0)),
]
TCP_Z_M = 0.228


def _rpy(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def _rz(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


_ORIGINS = []
for xyz, rpy in JOINTS:
    T = np.eye(4)
    T[:3, :3] = _rpy(*rpy)
    T[:3, 3] = xyz
    _ORIGINS.append(T)
_TCP = np.eye(4)
_TCP[2, 3] = TCP_Z_M


def fk(q_deg, tcp=True) -> np.ndarray:
    """관절각(deg 6개) → base_link 기준 TCP(또는 플랜지) 4x4 (m)."""
    T = np.eye(4)
    for O, q in zip(_ORIGINS, q_deg):
        R = np.eye(4)
        R[:3, :3] = _rz(math.radians(q))
        T = T @ O @ R
    return T @ _TCP if tcp else T


def frames(q_deg):
    """각 관절 축 위치·방향 (자코비안·시각화용): [(origin m, z축)] 6개 + TCP."""
    T, out = np.eye(4), []
    for O, q in zip(_ORIGINS, q_deg):
        T = T @ O
        out.append((T[:3, 3].copy(), T[:3, 2].copy()))
        R = np.eye(4)
        R[:3, :3] = _rz(math.radians(q))
        T = T @ R
    return out, (T @ _TCP)


def zyz_to_R(a, b, c):
    a, b, c = (math.radians(v) for v in (a, b, c))
    return _rz(a) @ np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]]) @ _rz(c)


def R_to_zyz(R):
    b = math.atan2(math.hypot(R[0, 2], R[1, 2]), R[2, 2])
    if abs(math.sin(b)) < 1e-9:                                   # 짐벌: a + c 만 정해짐 → a = 0
        return 0.0, math.degrees(b), math.degrees(math.atan2(R[1, 0], R[0, 0]) if b < 1 else math.atan2(-R[1, 0], -R[0, 0]))
    return math.degrees(math.atan2(R[1, 2], R[0, 2])), math.degrees(b), math.degrees(math.atan2(R[2, 1], -R[2, 0]))


def posx_to_T(p):
    T = np.eye(4)
    T[:3, :3] = zyz_to_R(*p[3:6])
    T[:3, 3] = np.array(p[:3]) / 1000.0
    return T


def T_to_posx(T):
    return [*(T[:3, 3] * 1000.0).tolist(), *R_to_zyz(T[:3, :3])]


def fk_posx(q_deg):
    return T_to_posx(fk(q_deg))


def jacobian(q_deg):
    """기하 자코비안 6x6 (선속도 m/rad, 각속도), TCP 기준."""
    axes, Tt = frames(q_deg)
    p = Tt[:3, 3]
    J = np.zeros((6, 6))
    for i, (o, z) in enumerate(axes):
        J[:3, i] = np.cross(z, p - o)
        J[3:, i] = z
    return J


def manipulability(q_deg):
    """조작성 sqrt(det(J Jᵀ)) 와 최소 특이값 (0 에 가까울수록 특이점)."""
    J = jacobian(q_deg)
    s = np.linalg.svd(J, compute_uv=False)
    return float(np.prod(s)), float(s[-1])


def _err(T, Tg):
    dp = Tg[:3, 3] - T[:3, 3]
    Re = Tg[:3, :3] @ T[:3, :3].T
    ang = math.acos(max(-1.0, min(1.0, (np.trace(Re) - 1) / 2)))
    if ang < 1e-9:
        w = np.zeros(3)
    else:
        w = ang / (2 * math.sin(ang)) * np.array([Re[2, 1] - Re[1, 2], Re[0, 2] - Re[2, 0], Re[1, 0] - Re[0, 1]])
    return np.concatenate([dp, w])


def ik(Tg, q0_deg, iters=200, lam=0.02, tol=(1e-5, 1e-5)):
    """목표 TCP 4x4 → 관절각(deg). 시작값 q0 근처 해. (q, 수렴 여부)."""
    q = np.radians(np.array(q0_deg, float))
    for _ in range(iters):
        e = _err(fk(np.degrees(q)), Tg)
        if np.linalg.norm(e[:3]) < tol[0] and np.linalg.norm(e[3:]) < tol[1]:
            return np.degrees(q), True
        J = jacobian(np.degrees(q))
        dq = J.T @ np.linalg.solve(J @ J.T + lam ** 2 * np.eye(6), e)
        n = np.linalg.norm(dq)
        if n > 0.2:
            dq *= 0.2 / n
        q += dq
    return np.degrees(q), False


def interp_line(p0, p1, n):
    """두 posx 사이 직선(위치 선형 + 자세 slerp) n+1 점의 4x4."""
    T0, T1 = posx_to_T(p0), posx_to_T(p1)
    R0, R1 = T0[:3, :3], T1[:3, :3]
    Rd = R0.T @ R1
    ang = math.acos(max(-1.0, min(1.0, (np.trace(Rd) - 1) / 2)))
    if ang < 1e-9:
        ax = np.array([0.0, 0.0, 1.0])
    else:
        ax = np.array([Rd[2, 1] - Rd[1, 2], Rd[0, 2] - Rd[2, 0], Rd[1, 0] - Rd[0, 1]]) / (2 * math.sin(ang))
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    out = []
    for k in range(n + 1):
        s = k / n
        Rs = np.eye(3) + math.sin(s * ang) * K + (1 - math.cos(s * ang)) * K @ K
        T = np.eye(4)
        T[:3, :3] = R0 @ Rs
        T[:3, 3] = (1 - s) * T0[:3, 3] + s * T1[:3, 3]
        out.append(T)
    return out, math.degrees(ang)
