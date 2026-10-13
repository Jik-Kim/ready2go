#!/usr/bin/env python3
"""서랍 물품 외형 메시 만들기 (담당 A, 트윈 재생용). Isaac 없이 numpy·OpenCV 로 USD(ascii) 를 쓴다.

  python3 sim/scripts/build_object_meshes.py [--data data] [--out sim/assets/objects] [--classes toy_wrench,cover_plate,...]

- 단독 촬영 세션(data/raw/s01_single_v0: 컬러·정렬 뎁스, data/labeled_seg: 분할 다각형)으로 **2.5D 외형**: 마스크 밖 바닥 뎁스로
  바닥면을 맞추고, 마스크 안 픽셀의 바닥 위 높이를 2 mm 격자 높이 지도로 → 윗면 + 바닥까지 수직 옆면. 같은 물품 사진 6장의 중앙값.
  위에서만 찍어 아랫면은 모름(옆면은 수직). 윗면 색은 사진 색(면마다). 높이는 99 백분위가 온톨로지 높이가 되게 비례로 맞춤.
  벽 근처·뎁스 빈 사진(외접이 온톨로지와 15 %·25 % 넘게 다름)은 뺌, 뎁스 빈 마스크 픽셀은 물체 중앙 높이로 채움(검은 물체 윤곽).
- 립밤: 원통(온톨로지 길이·지름, 축 = x) — 사용자 10/13 "그냥 원통, 굴러다니는 걸로".
- 덮개 판: 치수로 만든 모양 [사용자 10/13 실측]: 판 98.5×74.2 두께 5, 구멍·볼트 25 mm 격자(3열×4줄, 모서리 4곳 볼트),
  볼트 중심 간격 50(가로)·75(세로), 와셔 지름 28, 육각 머리 폭 17·높이 10, 판 밑 21(B under_clear) — 와셔 두께 = 40.5 − 21 − 5 − 10 = 4.5 [계산].
  구멍 지름 17 mm·볼트 몸통(다리) 지름 8 mm 는 사진으로 본 [추정].
- 좌표: 온톨로지 size_m 과 같게 — x = 긴 변, y = 짧은 변, z = 위(바닥 0), 원점 = 외접 사각형 가운데 바닥.
- 결과: <out>/<class>.usda 와 <out>/README 표(외접 크기 vs 온톨로지). 재생기는 파일이 있으면 상자 대신 이걸 씀.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
K = (909.4756, 909.0836, 652.0347, 371.2673)        # 손목 D435 컬러 1280×720 (덤프 meta K, 10/12)
CELL = 0.002                                        # 높이 지도 격자 (m)
SESSION = "s01_single_v0"
SCANNED = ["airpods_case", "caramel_box", "car_key", "eraser", "masking_tape", "toy_car", "toy_wrench", "toy_hammer"]


# ---------- 메시 ----------
class Mesh:
    def __init__(self):
        self.v, self.f, self.c = [], [], []          # 점, 면(점 번호 목록), 면 색

    def quad(self, pts, color):
        i = len(self.v)
        self.v += [tuple(map(float, p)) for p in pts]
        self.f.append(list(range(i, i + len(pts))))
        self.c.append(tuple(map(float, color)))

    def extend(self, m):
        i = len(self.v)
        self.v += m.v
        self.f += [[k + i for k in f] for f in m.f]
        self.c += m.c

    def bounds(self):
        a = np.array(self.v)
        return a.min(0), a.max(0)

    def write_usda(self, path: Path, name: str, note: str):
        pts = ", ".join(f"({x:.5f}, {y:.5f}, {z:.5f})" for x, y, z in self.v)
        counts = ", ".join(str(len(f)) for f in self.f)
        idx = ", ".join(str(k) for f in self.f for k in f)
        cols = ", ".join(f"({r:.3f}, {g:.3f}, {b:.3f})" for r, g, b in self.c)
        path.write_text(f'''#usda 1.0
(
    defaultPrim = "{name}"
    metersPerUnit = 1
    upAxis = "Z"
    doc = "{note}"
)

def Xform "{name}"
{{
    def Mesh "mesh"
    {{
        int[] faceVertexCounts = [{counts}]
        int[] faceVertexIndices = [{idx}]
        point3f[] points = [{pts}]
        color3f[] primvars:displayColor = [{cols}] (
            interpolation = "uniform"
        )
        uniform token subdivisionScheme = "none"
        uniform bool doubleSided = 1
    }}
}}
''', encoding="utf-8")


def heightfield_mesh(top, bottom, mask, color, x0, y0, cell=CELL) -> Mesh:
    """격자 높이 지도(칸마다 bottom~top 사이를 채움) → 윗면·아랫면 + 이웃과 다른 곳의 옆면."""
    m = Mesh()
    H, W = mask.shape
    for r in range(H):
        for c in range(W):
            if not mask[r, c]:
                continue
            xa, xb, ya, yb = x0 + c * cell, x0 + (c + 1) * cell, y0 + r * cell, y0 + (r + 1) * cell
            t, b, col = top[r, c], bottom[r, c], color[r, c]
            m.quad([(xa, ya, t), (xb, ya, t), (xb, yb, t), (xa, yb, t)], col)
            if b > 1e-4:
                m.quad([(xa, ya, b), (xa, yb, b), (xb, yb, b), (xb, ya, b)], col * 0.7)
            for dr, dc, edge in ((0, -1, [(xa, yb), (xa, ya)]), (0, 1, [(xb, ya), (xb, yb)]),
                                 (-1, 0, [(xa, ya), (xb, ya)]), (1, 0, [(xb, yb), (xa, yb)])):
                rr, cc = r + dr, c + dc
                inside = 0 <= rr < H and 0 <= cc < W and mask[rr, cc]
                lo, hi = (b, t) if not inside else (max(b, top[rr, cc]), t)
                lo2, hi2 = (b, min(t, bottom[rr, cc])) if inside and bottom[rr, cc] > b else (None, None)
                for z0, z1 in ((lo, hi), (lo2, hi2)):
                    if z0 is not None and z1 - z0 > 1e-4:
                        (p, q) = edge
                        m.quad([(p[0], p[1], z0), (q[0], q[1], z0), (q[0], q[1], z1), (p[0], p[1], z1)], col * 0.85)
    return m


def prism(poly_mask_fn, z0, z1, color, half_x, half_y, cell=0.001) -> Mesh:
    """2D 모양(점 (x, y) → bool) 을 z0~z1 로 세운 기둥."""
    xs = np.arange(-half_x, half_x, cell) + cell / 2
    ys = np.arange(-half_y, half_y, cell) + cell / 2
    X, Y = np.meshgrid(xs, ys)
    mask = poly_mask_fn(X, Y)
    top = np.full(mask.shape, z1)
    bot = np.full(mask.shape, z0)
    col = np.broadcast_to(np.array(color, float), mask.shape + (3,))
    return heightfield_mesh(top, bot, mask, col, -half_x, -half_y, cell)


# ---------- 파라미터 모양 ----------
def lip_balm(size) -> Mesh:
    L, d = size[0], size[1]
    r, n = d / 2, 32
    m = Mesh()
    ang = [2 * math.pi * k / n for k in range(n)]
    ring = [(r * math.cos(a), r * math.sin(a) + 0.0) for a in ang]       # (y, z-r)
    col = (0.08, 0.08, 0.1)
    for k in range(n):
        (y0_, z0_), (y1_, z1_) = ring[k], ring[(k + 1) % n]
        m.quad([(-L / 2, y0_, z0_ + r), (L / 2, y0_, z0_ + r), (L / 2, y1_, z1_ + r), (-L / 2, y1_, z1_ + r)], col)
    for sx in (-1, 1):
        cap = [(sx * L / 2, y, z + r) for y, z in ring]
        m.quad(cap if sx > 0 else cap[::-1], (0.7, 0.1, 0.1) if sx > 0 else col)   # 한쪽 끝 빨간 띠(뚜껑 쪽 구분)
    return m


def cover_plate(size) -> Mesh:
    Lx, Ly, H = size                                  # x = 긴 변(세로 볼트 간격 75 방향), y = 짧은 변(50)
    leg_h, plate_t, head_h = 0.021, 0.005, 0.010
    washer_t = H - leg_h - plate_t - head_h           # 4.5 mm [계산]
    pitch, hole_d, washer_d, head_w, shank_d = 0.025, 0.017, 0.028, 0.017, 0.008
    rows = [(-1.5 + i) * pitch for i in range(4)]     # x 방향 4줄
    cols = [(-1 + j) * pitch for j in range(3)]       # y 방향 3열
    bolts = [(rows[0], cols[0]), (rows[0], cols[2]), (rows[3], cols[0]), (rows[3], cols[2])]
    holes = [(x, y) for x in rows for y in cols if (x, y) not in bolts]
    gray, black = (0.72, 0.74, 0.78), (0.12, 0.12, 0.13)
    m = Mesh()
    rc = 0.006                                         # 판 모서리 둥글기 [추정]

    def slab(X, Y):
        inside = (np.abs(X) <= Lx / 2) & (np.abs(Y) <= Ly / 2)
        cx, cy = np.clip(np.abs(X), 0, Lx / 2 - rc), np.clip(np.abs(Y), 0, Ly / 2 - rc)
        inside &= np.hypot(np.abs(X) - cx, np.abs(Y) - cy) <= rc
        for hx, hy in holes:
            inside &= np.hypot(X - hx, Y - hy) > hole_d / 2
        return inside
    m.extend(prism(slab, leg_h, leg_h + plate_t, gray, Lx / 2, Ly / 2))
    for bx, by in bolts:
        m.extend(prism(lambda X, Y: np.hypot(X - bx, Y - by) <= shank_d / 2, 0.0, leg_h, black, Lx / 2, Ly / 2))
        m.extend(prism(lambda X, Y: np.hypot(X - bx, Y - by) <= washer_d / 2, leg_h + plate_t, leg_h + plate_t + washer_t, black, Lx / 2, Ly / 2))

        def hexa(X, Y, bx=bx, by=by):
            u, v = X - bx, Y - by
            a = head_w / 2
            return (np.abs(v) <= a) & (np.abs(u * math.sqrt(3) / 2 + v / 2) <= a) & (np.abs(u * math.sqrt(3) / 2 - v / 2) <= a)
        m.extend(prism(hexa, H - head_h, H, (0.2, 0.2, 0.22), Lx / 2, Ly / 2))
    return m


# ---------- 사진으로 만든 2.5D ----------
def class_ids(data: Path) -> list:
    return [l.strip() for l in (ROOT / "config/yolo_classes.txt").read_text().splitlines() if l.strip()]


def frames_of(data: Path, cls: str) -> list:
    import yaml
    s = yaml.safe_load((data / "raw" / SESSION / "session.yaml").read_text(encoding="utf-8"))
    a, b = (int(x) for x in s["class_ranges"][cls].split("-"))
    return [f"{i:04d}" for i in range(a, b + 1)]


def scan_one(data: Path, fid: str, cid: int):
    """사진 한 장 → (점들 (x, y, h) 물체 좌표, 색) 또는 None."""
    img = cv2.imread(str(data / "raw" / SESSION / "images" / f"{fid}.png"))
    dep = cv2.imread(str(data / "raw" / SESSION / "depth" / f"{fid}.png"), -1).astype(float) / 1000.0
    H, W = dep.shape
    mask = np.zeros((H, W), np.uint8)
    lab = data / "labeled_seg" / SESSION / "labels" / f"{fid}.txt"
    for line in lab.read_text().splitlines():
        v = line.split()
        if v and int(v[0]) == cid:
            pts = (np.array(v[1:], float).reshape(-1, 2) * [W, H]).astype(np.int32)
            cv2.fillPoly(mask, [pts], 1)
    if mask.sum() < 200:
        return None
    fx, fy, cx, cy = K
    vs, us = np.mgrid[0:H, 0:W]
    P = np.stack([(us - cx) / fx * dep, (vs - cy) / fy * dep, dep], -1)
    ok = (dep > 0.15) & (dep < 1.0)
    ring = (cv2.dilate(mask, np.ones((121, 121), np.uint8)) > 0) & ~(cv2.dilate(mask, np.ones((31, 31), np.uint8)) > 0) & ok
    F = P[ring]
    keep_f = np.ones(len(F), bool)
    for _ in range(5):                                  # 바닥면: 잔차 3 mm 넘는 점(벽·다른 물체)을 빼며 다시 맞춤
        c0 = F[keep_f].mean(0)
        _, _, vt = np.linalg.svd(F[keep_f] - c0, full_matrices=False)
        n = vt[2] * (-1 if vt[2][2] > 0 else 1)          # 카메라 쪽(위)이 +
        res = (F - c0) @ n
        keep_f = np.abs(res - np.median(res[keep_f])) < 0.003
    inner = cv2.erode(mask, np.ones((5, 5), np.uint8)) > 0
    hv = (P[inner & ok] - c0) @ n
    if (hv > 0.003).sum() < 50:
        return None
    h_med = float(np.median(hv[hv > 0.003]))
    # 뎁스가 빈 마스크 픽셀(검은 물체 — 몽키 머리·차키)은 물체 중앙 높이로 채워 윤곽을 살림: 광선이 그 높이 평면과 만나는 점
    d_fill = np.zeros_like(dep)
    ray = np.stack([(us - cx) / fx, (vs - cy) / fy, np.ones_like(dep)], -1)
    denom = ray @ n
    d_fill = np.where(np.abs(denom) > 1e-6, ((c0 @ n) + h_med) / np.where(np.abs(denom) > 1e-6, denom, 1), 0)
    P = np.where(ok[..., None], P, ray * d_fill[..., None])
    Q = P[inner]
    h = (Q - c0) @ n
    keep = h > 0.003
    Q, h = Q[keep], h[keep]
    col = img[inner][keep][:, ::-1] / 255.0
    e1 = np.cross(n, [0, 1, 0]); e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    xy = np.stack([(Q - c0) @ e1, (Q - c0) @ e2], -1)
    mu = xy.mean(0)
    _, _, vt2 = np.linalg.svd(xy - mu, full_matrices=False)
    R = vt2                                            # 행 = 긴 축, 짧은 축
    xy = (xy - mu) @ R.T
    lo, hi = np.percentile(xy, 1, 0), np.percentile(xy, 99, 0)
    xy -= (lo + hi) / 2
    return np.column_stack([xy, h]), col


def grid_of(pts, col, half):
    nx, ny = int(round(2 * half[0] / CELL)), int(round(2 * half[1] / CELL))
    c = np.floor((pts[:, 0] + half[0]) / CELL).astype(int)
    r = np.floor((pts[:, 1] + half[1]) / CELL).astype(int)
    ok = (c >= 0) & (c < nx) & (r >= 0) & (r < ny)
    top = np.full((ny, nx), np.nan)
    cs = np.zeros((ny, nx, 3))
    key = r[ok] * nx + c[ok]
    order = np.argsort(key)
    k_s, h_s, c_s = key[order], pts[ok, 2][order], col[ok][order]
    starts = np.r_[0, np.flatnonzero(np.diff(k_s)) + 1]
    for a, b in zip(starts, np.r_[starts[1:], len(k_s)]):
        rr, cc = divmod(k_s[a], nx)
        top[rr, cc] = np.percentile(h_s[a:b], 80)
        cs[rr, cc] = np.median(c_s[a:b], 0)
    return top, cs


def scanned(data: Path, cls: str, size) -> tuple:
    cid = class_ids(data).index(cls)
    half = (size[0] / 2 + 0.01, size[1] / 2 + 0.01)
    tops, cols, n = [], [], 0
    for fid in frames_of(data, cls):
        s = scan_one(data, fid, cid)
        if s is None:
            continue
        pts, col = s
        ext = np.ptp(pts[:, :2], 0)
        if abs(ext[0] - size[0]) > 0.15 * size[0] or abs(ext[1] - size[1]) > 0.25 * size[1]:
            print(f"  {cls} {fid}: 외접 {ext[0]*1000:.0f}×{ext[1]*1000:.0f} mm — 온톨로지와 많이 달라 뺌 (벽 근처·뎁스 빔)")
            continue
        t, c = grid_of(pts, col, half)
        if tops:                                       # 긴 축 방향 180° 모호 — 첫 장과 더 비슷한 쪽으로
            ref = np.nan_to_num(tops[0])
            flip = np.nan_to_num(t[::-1, ::-1])
            if np.abs(flip - ref).mean() < np.abs(np.nan_to_num(t) - ref).mean():
                t, c = t[::-1, ::-1], c[::-1, ::-1]
        tops.append(t)
        cols.append(c)
        n += 1
    T = np.stack(tops)
    have = np.isfinite(T).sum(0) >= max(2, n // 2)
    top = np.where(have, np.nanmedian(np.where(np.isfinite(T), T, np.nan), 0), 0)
    mask = cv2.morphologyEx(have.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0
    top = np.where(mask & ~have, cv2.medianBlur(np.nan_to_num(top).astype(np.float32), 3), top)
    top = cv2.medianBlur(top.astype(np.float32), 3).astype(float)
    mask &= top > 0.003
    top = top * (size[2] / np.percentile(top[mask], 99))    # 높이는 온톨로지(버니어 실측)에 맞춤 — 뎁스는 가장자리가 번지고 칸 대표값이라 낮게 나옴
    col = np.nanmedian(np.stack(cols), 0)
    m = heightfield_mesh(top, np.zeros_like(top), mask, col, -half[0], -half[1])
    return m, n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "sim/assets/objects"))
    ap.add_argument("--classes", default="")
    a = ap.parse_args()
    data, out = Path(a.data), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    items = json.loads((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))["world"]["items"]
    want = [c for c in (a.classes.split(",") if a.classes else items) if c in items]
    rows = []
    for cls in want:
        size = items[cls]["size_m"]
        if cls == "lip_balm":
            m, how = lip_balm(size), "원통 (온톨로지 길이·지름)"
        elif cls == "cover_plate":
            m, how = cover_plate(size), "치수 모양 (사용자 실측 10/13)"
        else:
            m, n = scanned(data, cls, size)
            how = f"2.5D 사진 {n}장 ({SESSION})"
        lo, hi = m.bounds()
        ext = hi - lo
        m.write_usda(out / f"{cls}.usda", cls, f"{cls}: {how}. build_object_meshes.py")
        rows.append((cls, how, ext, size, len(m.f)))
        print(f"{cls:13s} {how:28s} 외접 {ext[0]*1000:6.1f} × {ext[1]*1000:5.1f} × {ext[2]*1000:5.1f} mm  "
              f"(온톨로지 {size[0]*1000:.1f} × {size[1]*1000:.1f} × {size[2]*1000:.1f})  면 {len(m.f)}")


if __name__ == "__main__":
    main()
