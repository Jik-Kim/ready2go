"""조그·축 정렬용 자세 계산 (DSR posx = [x, y, z, Rz, Ry, Rz'] mm·deg, ZYZ 오일러). ROS 비의존.

- 같은 자세를 나타내는 ZYZ 표현이 여러 개라, 목표는 항상 '지금 각도와 가장 가까운 표현'으로 고른다
  (제어기가 반대쪽으로 크게 돌아가지 않게).
- 큰 회전은 최단 회전 경로 위에서 max_step° 이하 조각으로 나눈다 (`waypoints`).
- 회전 조그·정렬은 그리퍼 끝(TCP) 위치를 고정하고 방향만 바꾼다.
"""
import math


def rot(a, b, c):
    """ZYZ 오일러(deg) → 회전 행렬 (3×3 리스트)."""
    a, b, c = (math.radians(v) for v in (a, b, c))
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return [[ca * cb * cc - sa * sc, -ca * cb * sc - sa * cc, ca * sb],
            [sa * cb * cc + ca * sc, -sa * cb * sc + ca * cc, sa * sb],
            [-sb * cc, sb * sc, cb]]


def wrap(deg):
    """각도를 [-180, 180)으로."""
    return (deg + 180.0) % 360.0 - 180.0


def zyz_near(r, cur):
    """회전 행렬 → ZYZ(deg). 같은 자세의 표현 중 지금 각도(cur)와 가장 가까운 것, 값은 ±180° 안."""
    a0, b0, c0 = cur
    b = math.degrees(math.acos(max(-1.0, min(1.0, r[2][2]))))
    if math.sin(math.radians(b)) > 1e-6:
        a = math.degrees(math.atan2(r[1][2], r[0][2]))
        c = math.degrees(math.atan2(r[2][1], -r[2][0]))
        cands = [(a, b, c), (a + 180.0, -b, c + 180.0)]
    elif r[2][2] > 0:                                   # b = 0: 자세는 a + c로만 정해짐
        cands = [(math.degrees(math.atan2(r[1][0], r[0][0])) - c0, 0.0, c0)]
    else:                                               # b = ±180: 자세는 a - c로만 정해짐
        bb = -180.0 if b0 < 0 else 180.0
        cands = [(math.degrees(math.atan2(-r[1][0], -r[0][0])) + c0, bb, c0)]
    best = []
    for a, b, c in cands:                               # 각 값을 지금 값에 이어 붙임 (튀는 큰 변화 방지)
        v = (a0 + wrap(a - a0), b0 + wrap(b - b0) if abs(b) < 179.9 else b, c0 + wrap(c - c0))
        out = sum(max(0.0, abs(x) - 180.0) for x in v)  # ±180 밖 표현은 되도록 피함
        best.append((out * 10.0 + sum(abs(v[i] - cur[i]) for i in range(3)), v))
    return [wrap(x) if abs(x) > 180.0 else x for x in min(best)[1]]


def matmul(p, q):
    return [[sum(p[i][k] * q[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def transpose(m):
    return [list(row) for row in zip(*m)]


def base_rot(axis, deg):
    """베이스 x·y·z축 하나를 도는 회전 행렬."""
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    return {"x": [[1, 0, 0], [0, c, -s], [0, s, c]],
            "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
            "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]


def axis_rot(u, th):
    """단위 벡터 u 둘레로 th(rad) 회전 (로드리게스)."""
    c, s, t = math.cos(th), math.sin(th), 1 - math.cos(th)
    x, y, z = u
    return [[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]


def rotation_angle(r0, r1):
    """두 자세 사이 회전량(deg)."""
    tr = sum(r0[i][j] * r1[i][j] for i in range(3) for j in range(3))
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1.0) / 2.0))))


def step_target(pose, idx, step):
    """지금 posx에서 한 칸. idx 0~2: x y z (mm), 3~5: 베이스 x y z축 회전 (deg, TCP 위치 고정)."""
    if idx < 3:
        out = list(pose)
        out[idx] += step
        return out
    return list(pose[:3]) + zyz_near(matmul(base_rot("xyz"[idx - 3], step), rot(*pose[3:])), pose[3:])


# ---- 축 정렬 ----
def col(r, i):
    return [r[0][i], r[1][i], r[2][i]]


def cross(u, v):
    return [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]


def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v] if n > 1e-9 else None


def frame(x, z):
    y = cross(z, x)
    return [[x[0], y[0], z[0]], [x[1], y[1], z[1]], [x[2], y[2], z[2]]]


def point_rot(r, z):
    """그리퍼 축(툴 z)을 z로 돌린다. 손가락 방향은 지금 방향을 새 축에 수직으로 투영해 최소로만 바꾼다."""
    x0 = col(r, 0)
    d = sum(x0[k] * z[k] for k in range(3))
    x = unit([x0[k] - d * z[k] for k in range(3)])
    if x is None:
        x = unit(cross(col(r, 1), z))
    return frame(x, z)


def roll_rot(r, step):
    """그리퍼 축 고정, 손가락 방향(툴 x)을 가장 가까운 step° 칸으로. 0° = 그리퍼 축과 가장 수직인 베이스 축의 투영."""
    z, x = col(r, 2), col(r, 0)
    k = min(range(3), key=lambda k: abs(z[k]))
    e = [1.0 if i == k else 0.0 for i in range(3)]
    d = sum(e[i] * z[i] for i in range(3))
    ref = unit([e[i] - d * z[i] for i in range(3)])
    ref2 = cross(z, ref)
    th = math.degrees(math.atan2(sum(x[i] * ref2[i] for i in range(3)), sum(x[i] * ref[i] for i in range(3))))
    delta = math.radians(round(th / step) * step - th)
    zx = cross(z, x)
    xn = [x[i] * math.cos(delta) + zx[i] * math.sin(delta) for i in range(3)]
    return frame(xn, z)


def align_target(pose, mode, snap=False):
    """축 정렬 목표 posx. TCP 위치는 그대로.

    mode: "z" 수직 아래(베이스 -z) / "y" 수평, 항상 베이스 -y / "x" 수평, 베이스 x축의 몸 바깥쪽 부호 /
          "r" 그리퍼 축 고정, 손가락을 가장 가까운 90° 칸에. snap=True면 방향 정렬 뒤 90° 칸 정렬까지.
    """
    r = rot(*pose[3:])
    if mode == "r":
        rt = roll_rot(r, 90.0)
    else:
        if mode == "z":
            z = [0.0, 0.0, -1.0]
        elif mode in ("x", "y"):
            i = 0 if mode == "x" else 1
            out = -1.0 if mode == "y" else (pose[i] if abs(pose[i]) > 50.0 else col(r, 2)[i])
            z = [0.0, 0.0, 0.0]
            z[i] = 1.0 if out >= 0 else -1.0
        else:
            raise ValueError(f"mode는 x y z r 중 하나: {mode}")
        rt = point_rot(r, z)
        if snap:
            rt = roll_rot(rt, 90.0)
    return list(pose[:3]) + zyz_near(rt, pose[3:])


def roll_target(pose, deg):
    """TCP 위치 고정, 그리퍼 축(툴 z) 둘레로 deg° 회전한 목표 posx. + = 툴 x → 툴 y 쪽
    (그리퍼가 수직 아래면 위에서 볼 때 시계 방향)."""
    r = matmul(rot(*pose[3:]), base_rot("z", deg))
    return list(pose[:3]) + zyz_near(r, pose[3:])


def tilt_target(pose, direction, deg):
    """TCP 위치 고정. 그리퍼 축(툴 z)을 수직 아래에서 수평 방향 direction 쪽으로 deg° 기울인 목표 posx — 손끝이 그쪽으로 감.
    지금 기울어져 있어도 수직 기준으로 다시 잡는다(누적 안 됨), deg 0 = 수직. 손가락 방향은 point_rot(최소 변화)."""
    n = unit([direction[0], direction[1], 0.0])
    if n is None:
        raise ValueError(f"기울일 방향은 수평 성분이 있어야 함: {direction}")
    t = math.radians(deg)
    z = [n[0] * math.sin(t), n[1] * math.sin(t), -math.cos(t)]
    return list(pose[:3]) + zyz_near(point_rot(rot(*pose[3:]), z), pose[3:])


def waypoints(pose, target, max_step=20.0):
    """지금 자세 → 목표 자세를 최단 회전 경로 위에서 max_step° 이하 조각으로 나눈 posx 목록 (TCP 위치 고정)."""
    r0, r1 = rot(*pose[3:]), rot(*target[3:])
    rel = matmul(transpose(r0), r1)
    th = math.radians(rotation_angle(r0, r1))
    if th < 1e-6:
        return []
    if th > math.radians(90.0):                        # 큰 회전: u uᵀ = (대칭부 - cosθ I) / (1 - cosθ)
        cth = math.cos(th)
        m = [[(rel[i][j] + rel[j][i]) / 2.0 - (cth if i == j else 0.0) for j in range(3)] for i in range(3)]
        k = max(range(3), key=lambda k: m[k][k])
        u = unit(m[k])
        w = [rel[2][1] - rel[1][2], rel[0][2] - rel[2][0], rel[1][0] - rel[0][1]]
        if sum(u[i] * w[i] for i in range(3)) < 0:
            u = [-v for v in u]
    else:
        u = unit([rel[2][1] - rel[1][2], rel[0][2] - rel[2][0], rel[1][0] - rel[0][1]])
    n = max(1, math.ceil(math.degrees(th) / max_step))
    out, cur = [], list(pose[3:])
    for i in range(1, n + 1):
        cur = zyz_near(matmul(r0, axis_rot(u, th * i / n)), cur)
        out.append(list(pose[:3]) + cur)
    return out
