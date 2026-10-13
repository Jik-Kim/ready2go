#!/usr/bin/env python3
"""들고 나오기(carry_line) moveb vs movesx(스플라인) 경로 비교 — 10/14 movesx 구현 전 사전 검토 [강사님 피드백 10/13, 작업표 1번].

지금 B: 경유점 1(서랍 가운데, 테두리 위) → 2(위로) → 3(트레이 쪽 옆으로) → 4(트레이 앞 아래로) → 칸 위(4번 높이) → 놓는 높이 + 10 mm
를 moveb(직선 + 모서리 반지름 carry.radius_mm 100, 짧은 구간은 앞뒤 절반까지)로 한 번에 (skill_server carry 블록과 같은 점·반지름).
movesx 는 같은 점을 지나는 작업 공간 스플라인 — 두산 내부 스플라인 식은 공개 안 됨 → 자연 3차 스플라인(C2, 현 길이 매개변수)과
centripetal Catmull-Rom(C1) 두 가지로 범위를 봄 [추정]. moveb 모서리는 진입·이탈점(모서리에서 반지름만큼) 사이 2차 베지어로 근사 [추정].

보는 것 (값은 config/poses.yaml carry_line·places.yaml):
  - 서랍 앞벽(손잡이 쪽, 서랍 x 0 = base y 약 −112) 지날 때 TCP 높이 − 테두리 높이 (쥔 물체가 TCP 아래로 늘어진 만큼 더 필요)
  - 서랍 위(앞·뒤벽 사이)에서 경유점 1 보다 내려가는지, 뒤쪽(서랍장 쪽, base y 작은 쪽)으로 튀는지
  - 트레이 벽(base x 약 520) 지날 때 TCP 높이 − 트레이 테두리
  - "guided" = 제안: moveb 둥근 경로 위 8점을 movesx 경유점으로, 마지막 내려가기는 movel
  - 경로 길이, 최소 곡률 반지름 → 300 mm/s 일정 속도에서 원심 가속 v²/R (moveb 모서리에서 속도 줄었다 늘던 것 대신)
  python3 practice/B/sim/movesx_carry_sim.py [--png out.png]
"""
import argparse
from pathlib import Path

import numpy as np
import yaml
from scipy.interpolate import CubicSpline

REPO = Path(__file__).resolve().parents[3]
V = 300.0                        # speed.free_mm_s (carry 블렌딩 속도)
RADIUS = 100.0                   # carry.radius_mm
SLOW_LAST = 10.0                 # place.slow_last_mm
TRAY_SLOT_X = (560.0, 600.0, 640.0)   # 트레이 칸 3개 대략 (handover_zone x 520 + 137 mm 안) [추정]
PLACE_Z = 25.0                   # 놓는 TCP 높이 대략 (트레이 바닥 5 + 물체) [추정]


def load():
    poses = yaml.safe_load((REPO / "config/poses.yaml").read_text(encoding="utf-8"))
    places = yaml.safe_load((REPO / "config/places.yaml").read_text(encoding="utf-8"))
    return poses["carry_line"], places


def rim_z(places, d):
    return 1000.0 * (places[d]["tf"]["translation_m"][2] + places[d]["interior_m"][2])


def route_points(line, d, slot_x):
    """skill_server carry 블록과 같은 점: here(=경유점 1) + 2·3·4 + 칸 위(4번 높이) + 놓는 높이 + slow_last."""
    r = [np.array(p[:3], float) for p in line[d]]
    tgt = np.array([slot_x, r[3][1] + 50.0, PLACE_Z])
    pts = [r[0], r[1], r[2], r[3], np.array([tgt[0], tgt[1], r[3][2]]), np.array([tgt[0], tgt[1], tgt[2] + SLOW_LAST])]
    return pts


def moveb_path(pts, n=4000):
    """직선 + 모서리 반지름 (skill_server: min(rad, 앞 구간/2, 뒤 구간/2), 마지막 0) — 모서리는 2차 베지어 근사."""
    radii = [min(RADIUS, np.linalg.norm(pts[k + 1] - pts[k]) / 2, np.linalg.norm(pts[k + 2] - pts[k + 1]) / 2)
             for k in range(len(pts) - 2)]
    out, cur = [pts[0]], pts[0]
    for k, r in enumerate(radii):
        c, nxt = pts[k + 1], pts[k + 2]
        a = c + (cur - c) / np.linalg.norm(cur - c) * r
        b = c + (nxt - c) / np.linalg.norm(nxt - c) * r
        out += list(np.linspace(cur, a, 200)[1:])
        t = np.linspace(0, 1, 200)[1:, None]
        out += list((1 - t) ** 2 * a + 2 * (1 - t) * t * c + t ** 2 * b)
        cur = b
    out += list(np.linspace(cur, pts[-1], 200)[1:])
    return np.array(out), radii


def natural_spline(pts, n=4000):
    P = np.array(pts)
    s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    cs = CubicSpline(s, P, bc_type="natural")
    return cs(np.linspace(0, s[-1], n))


def catmull_rom(pts, n_seg=600, alpha=0.5):
    P = [pts[0] * 2 - pts[1]] + list(pts) + [pts[-1] * 2 - pts[-2]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        t0 = 0.0
        t1 = t0 + np.linalg.norm(p1 - p0) ** alpha
        t2 = t1 + np.linalg.norm(p2 - p1) ** alpha
        t3 = t2 + np.linalg.norm(p3 - p2) ** alpha
        for t in np.linspace(t1, t2, n_seg, endpoint=False):
            a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
            a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
            a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
            b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
            b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
            out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    out.append(pts[-1])
    return np.array(out)


def guided_spline(pts, n_via=8, n=4000):
    """제안: moveb 둥근 경로(칸 위까지)를 길이 같은 간격 n_via 점으로 뽑아 그 점들로 스플라인 → 마지막 내려가기는 직선(movel) 그대로.
    교시 경유점(직각 모서리)을 그대로 스플라인에 넣으면 부풀어 오름 — 둥근 경로 위 점을 주면 그 곡선을 따라감."""
    mb, _ = moveb_path(pts[:-1])
    seg = np.linalg.norm(np.diff(mb, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    via = [mb[np.searchsorted(s, v)] for v in np.linspace(0, s[-1], n_via)]
    via[-1] = pts[-2]
    sp = natural_spline(via, n)
    return np.vstack([sp, np.linspace(pts[-2], pts[-1], 200)[1:]])


def min_radius(path):
    d1 = np.gradient(path, axis=0)
    d2 = np.gradient(d1, axis=0)
    sp = np.linalg.norm(d1, axis=1)
    k = np.linalg.norm(np.cross(d1, d2), axis=1) / np.maximum(sp ** 3, 1e-9)
    k[:5] = k[-5:] = 0
    return 1.0 / max(k.max(), 1e-9)


def z_at_cross(path, axis, value, after=0):
    """axis 좌표가 value 를 처음 지나는 곳의 z (after 인덱스 뒤)."""
    a = path[after:, axis] - value
    idx = np.where(np.sign(a[:-1]) != np.sign(a[1:]))[0]
    return None if len(idx) == 0 else float(path[after + idx[0], 2])


def analyse(name, path, places, d):
    front_y = 1000.0 * places[d]["tf"]["translation_m"][1]            # 서랍 x 0(손잡이 쪽 벽) ≈ base y
    back_y = front_y - 1000.0 * places[d]["interior_m"][0]
    rim = rim_z(places, d)
    tray_x = 1000.0 * places["handover_zone"]["tf"]["translation_m"][0]
    tray_rim = 1000.0 * (places["handover_zone"]["tf"]["translation_m"][2] + places["handover_zone"]["interior_m"][2])
    zf = z_at_cross(path, 1, front_y)
    zt = z_at_cross(path, 0, tray_x)
    over = (path[:, 1] < front_y) & (path[:, 1] > back_y)
    length = float(np.sum(np.linalg.norm(np.diff(path, axis=0), axis=1)))
    R = min_radius(path)
    return {"name": name, "len": length, "front_clear": None if zf is None else zf - rim,
            "min_z_over": float(path[over, 2].min()) if over.any() else None, "start_z": float(path[0, 2]),
            "min_y": float(path[:, 1].min()), "back_y": back_y, "tray_clear": None if zt is None else zt - tray_rim,
            "min_z_end": float(path[:, 2].min()), "R": R, "acc": V ** 2 / R, "t": length / V}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png")
    a = ap.parse_args()
    line, places = load()
    rows, curves = [], {}
    for d in ("drawer_top", "drawer_bottom"):
        for sx in TRAY_SLOT_X:
            pts = route_points(line, d, sx)
            mb, radii = moveb_path(pts)
            paths = {"moveb": mb, "spline(C2)": natural_spline(pts), "CatmullRom": catmull_rom(pts),
                     "guided": guided_spline(pts)}
            for k, p in paths.items():
                r = analyse(k, p, places, d)
                r.update(drawer=d, slot=sx)
                rows.append(r)
            if sx == TRAY_SLOT_X[1]:
                curves[d] = (pts, paths, radii)
    print("값 [계산, 근사] — TCP 기준. 쥔 물체가 TCP 아래로 늘어진 길이(손끝 약 10 mm + 물체)만큼 여유가 더 필요")
    print(f"{'서랍':13s}{'칸x':>5s} {'경로':11s}{'길이':>7s}{'시간@300':>9s}{'앞벽여유':>9s}{'서랍위최저':>10s}{'뒤로최소y':>10s}"
          f"{'트레이벽여유':>12s}{'최소R':>7s}{'원심가속':>9s}")
    for r in rows:
        f = lambda v, w=8, p=1: f"{v:{w}.{p}f}" if v is not None else f"{'-':>{w}s}"   # noqa: E731
        print(f"{r['drawer']:13s}{r['slot']:5.0f} {r['name']:11s}{f(r['len'], 7, 0)}{f(r['t'], 8, 2)}s{f(r['front_clear'])}"
              f"{f(r['min_z_over'], 10)}{f(r['min_y'], 10)}{f(r['tray_clear'], 11)}{f(r['R'], 7, 0)}{f(r['acc'], 8, 0)}")
    for d in curves:
        print(f"{d}: 테두리 z {rim_z(places, d):.1f}, 경유점 1 z {curves[d][0][0][2]:.1f}, 서랍 뒤벽 base y "
              f"{1000 * places[d]['tf']['translation_m'][1] - 1000 * places[d]['interior_m'][0]:.0f}, moveb 반지름 {[round(x) for x in curves[d][2]]}")
    if a.png:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axs = plt.subplots(2, 2, figsize=(12, 9))
        for row, d in enumerate(curves):
            pts, paths, _ = curves[d]
            front_y = 1000.0 * places[d]["tf"]["translation_m"][1]
            back_y = front_y - 1000.0 * places[d]["interior_m"][0]
            rim = rim_z(places, d)
            ax = axs[row][0]
            for k, p in paths.items():
                ax.plot(p[:, 1], p[:, 2], label=k)
            ax.plot([back_y, front_y], [rim, rim], "k-", lw=3, label="drawer rim")
            ax.axvline(front_y, color="k", ls=":")
            ax.scatter([p[1] for p in pts], [p[2] for p in pts], c="r", zorder=5, label="waypoints")
            ax.set_xlabel("base y (mm)  -> tray")
            ax.set_ylabel("z (mm)")
            ax.set_title(f"{d}: side view (y-z)")
            ax.legend(fontsize=8)
            ax.set_aspect("equal")
            ax = axs[row][1]
            tray_x = 1000.0 * places["handover_zone"]["tf"]["translation_m"][0]
            tray_rim = 1000.0 * (places["handover_zone"]["tf"]["translation_m"][2] + places["handover_zone"]["interior_m"][2])
            for k, p in paths.items():
                ax.plot(p[:, 0], p[:, 2], label=k)
            ax.plot([tray_x, tray_x + 137], [tray_rim, tray_rim], "k-", lw=3, label="tray rim")
            ax.scatter([p[0] for p in pts], [p[2] for p in pts], c="r", zorder=5)
            ax.set_xlabel("base x (mm)")
            ax.set_title(f"{d}: tray approach (x-z)")
            ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(a.png, dpi=110)
        print("그림", a.png)


if __name__ == "__main__":
    main()
