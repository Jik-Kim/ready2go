"""비전 오차 시뮬레이션 — 물체 하나, 실제 자리(truth)는 그대로 두고 볼 때마다 위치 ±E mm·각도 ±A° (균일) 틀리게 봄.
판단(rand_sim2.decide)은 틀린 값으로, 결과 확인은 실제 자리로:
  - 집기: 벌린 손가락(틀린 가운데 ± 벌림/2, 손가락 반폭 tip_radius 띠)이 실제 물체 위에 내려앉으면 FINGER_ON (집기 실패)
  - 넛지: 누르는 TCP(접촉점 = TCP 바로 아래, close_axis wall)가 실제 물체 밖이면 PRESS_MISS (접촉 높이 틀림 → 끌기 거부)
  - 넛지 뒤 실제 물체는 같은 거리만큼 움직임 (벽에서 멈춤, '벽까지' 끌기는 벽에 맞춰 눕힘), 다시 봄 (새 오차)
  - 넛지 5번 넘으면 LOOP
오차 없는 같은 자리 결과와 비교해 오차 때문에 바뀐 것만 셈.
  python3 practice/B/sim/noise_sim.py [자리 수=1500] [E mm=3] [A deg=5] [seed=1]"""
import sys, math, random, collections
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rand_sim2 as rs
mp = rs.mp

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
E = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
A = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
rnd = random.Random(int(sys.argv[4]) if len(sys.argv) > 4 else 1)
G = rs.prm["gripper"]
W = G["tip_radius_mm"]                      # 손가락 반폭 (닫힘 축에 수직) [계산 10/06]
INSET = rs.prm["drag"]["press_inset_mm"]


def local(px, py, cx, cy, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    dx, dy = px - cx, py - cy
    return dx * c + dy * s, -dx * s + dy * c


def finger_on(truth, seen, S, close_ang, open_mm):
    """실제 물체 중 손가락 띠(닫힘 축에 수직 ±W) 안 점의 닫힘 축 좌표가 ±벌림/2 밖이면 손가락이 물체 위 → 남는 여유(mm, 음수면 닿음)."""
    (tx, ty, tyaw), (sx, sy) = truth, seen[:2]
    a = np.linspace(-S[0] * 500, S[0] * 500, 120)
    b = np.linspace(-S[1] * 500, S[1] * 500, 60)
    A_, B_ = np.meshgrid(a, b)
    c, s = math.cos(tyaw), math.sin(tyaw)
    X = tx * 1000 + A_ * c - B_ * s - sx * 1000
    Y = ty * 1000 + A_ * s + B_ * c - sy * 1000
    cc, ss = math.cos(close_ang), math.sin(close_ang)
    u = X * cc + Y * ss                     # 닫힘 축
    v = -X * ss + Y * cc                    # 손가락 폭 방향
    band = np.abs(v) <= W
    if not band.any():
        return -99.0                        # 손가락 사이에 물체 없음
    return open_mm / 2 - float(np.abs(u[band]).max())


def press_inset(truth, S, press):
    """누르는 점이 실제 물체 가장자리에서 안쪽으로 얼마나 (mm, 음수면 밖)."""
    a, b = local(press[0] * 1000, press[1] * 1000, truth[0] * 1000, truth[1] * 1000, truth[2])
    return min(S[0] * 500 - abs(a), S[1] * 500 - abs(b))


def clamp_in(x, y, yaw, S, I):
    c, s = abs(math.cos(yaw)), abs(math.sin(yaw))
    hx, hy = (S[0] * c + S[1] * s) / 2, (S[0] * s + S[1] * c) / 2
    return min(max(x, hx), I[0] - hx), min(max(y, hy), I[1] - hy)


def snap(yaw, axis_deg):
    """가장 가까운 서랍 축(0·90°) — 기울여 잡기는 손가락을 서랍 축에 맞춤 [사용자 10/10]."""
    return round((yaw - math.radians(axis_deg)) / (math.pi / 2)) * (math.pi / 2) + math.radians(axis_deg)


def episode(truth, S, I, gw, gd, cls, e_mm, a_deg):
    t = list(truth)
    for n in range(6):
        seen = (t[0] + rnd.uniform(-e_mm, e_mm) / 1000, t[1] + rnd.uniform(-e_mm, e_mm) / 1000,
                t[2] + math.radians(rnd.uniform(-a_deg, a_deg)))
        tg = {"pose": {"position": [seen[0], seen[1], 0.0], "yaw": seen[2]}}
        kind, info = rs.decide(tg, S, I, gw, gd)
        if kind == "STOP":
            return "STOP", n, str(info)[:50], None
        if kind != "NUDGE":
            long_ = kind.startswith("LONG")
            close = seen[2] if long_ else seen[2] + math.pi / 2
            if kind.startswith("LONG_TILT"):
                close = snap(close, 0)
            open_mm = (S[0] if long_ else S[1]) * 1000 + G["open_margin_mm"]
            m = finger_on(t, seen, S, close, open_mm)
            return ("OK" if m >= 0 else "FINGER_ON"), n, kind, m
        if n == 5:
            return "LOOP", n, info.reason[:50], None
        ins = press_inset(t, S, info.press_xy_m)
        if ins < 0:
            return "PRESS_MISS", n, info.reason[:40], ins
        ny = t[2]
        if "벽까지" in info.reason or "원통형이" in info.reason:
            ny = snap(t[2], 0)
        nx, nyy = clamp_in(t[0] + info.shift_x_m, t[1] + info.shift_y_m, ny, S, I)
        t = [nx, nyy, ny]


def run(drawer, cls):
    S, I = rs.SIZES[cls], rs.pl[drawer]["interior_m"]
    gw, gd = rs.gws(drawer, cls)
    res, changed, why, margins = collections.Counter(), collections.Counter(), collections.defaultdict(list), []
    k = 0
    while k < N:
        yaw = rnd.uniform(-math.pi / 2, math.pi / 2)
        x, y = rnd.uniform(0, I[0]), rnd.uniform(0, I[1])
        if not rs.inside(x, y, yaw, S, I):
            continue
        k += 1
        base = episode((x, y, yaw), S, I, gw, gd, cls, 0.0, 0.0)
        got = episode((x, y, yaw), S, I, gw, gd, cls, E, A)
        res[got[0]] += 1
        if got[3] is not None and got[0] in ("OK", "FINGER_ON"):
            margins.append(got[3])
        if got[0] != base[0]:
            changed[(base[0], got[0])] += 1
            why[(base[0], got[0], got[2])].append((round(x * 1000), round(y * 1000), round(math.degrees(yaw))))
    m = np.array(margins) if margins else np.array([0.0])
    print(f"{cls:12s} {drawer[7:]:6s} | " + " ".join(f"{k_} {100 * v / N:.1f}%" for k_, v in res.most_common())
          + f" | 손가락 여유 최소 {m.min():.1f} mm, 5% {np.percentile(m, 5):.1f} mm")
    for (b, g_, r), lst in sorted(why.items(), key=lambda kv: -len(kv[1]))[:4]:
        print(f"     오차로 {b}→{g_} {len(lst):4d} ({100 * len(lst) / N:.1f}%) [{r}] 예 {lst[:3]}")


if __name__ == "__main__":
    print(f"비전 오차 ±{E} mm · ±{A}° (균일), 자리 {N}곳씩")
    for cls in ["eraser", "lip_balm", "caramel_box", "car_key", "toy_wrench", "cover_plate"]:
        for d in ("drawer_top", "drawer_bottom"):
            run(d, cls)
