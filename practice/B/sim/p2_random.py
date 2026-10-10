"""P2 시연 배치 무작위 — 가림막 시나리오·쌓기 시나리오를 위치·각도·순서를 바꿔 돌리고 실패를 이유별로 모음.
  python3 practice/B/sim/p2_random.py [횟수=40] [seed=1]"""
import sys, math, random, collections, io, contextlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ros2_ws/src/ready2go_skills"))
import p2_demo as d
import demo_sim

import os
GUIDE = os.environ.get("GUIDE") == "1"          # 시연 배치 가이드: 가림막 벽에서 3 cm↑, 밑의 둘은 나란히 2 cm↑ 간격
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
rnd = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
SZ = {"cover_plate": (0.0985, 0.0742), "eraser": (0.0525, 0.022), "lip_balm": (0.0718, 0.02), "toy_wrench": (0.17, 0.061)}

def fits(x, y, yaw, sz, I, m=0.0):
    c, s = abs(math.cos(yaw)), abs(math.sin(yaw))
    hx, hy = (sz[0]*c + sz[1]*s)/2, (sz[0]*s + sz[1]*c)/2
    return m <= x - hx and x + hx <= I[0] - m and m <= y - hy and y + hy <= I[1] - m

def rect_in(x, y, yaw, sz, px, py, pyaw, psz):
    c, s = math.cos(pyaw), math.sin(pyaw)
    for a in (-1, 1):
        for b in (-1, 1):
            cx = x + a * sz[0]/2 * math.cos(yaw) - b * sz[1]/2 * math.sin(yaw)
            cy = y + a * sz[0]/2 * math.sin(yaw) + b * sz[1]/2 * math.cos(yaw)
            dx, dy = cx - px, cy - py
            if abs(dx*c + dy*s) > psz[0]/2 - 0.002 or abs(-dx*s + dy*c) > psz[1]/2 - 0.002:
                return False
    return True

def apart(a, b, gap=0.004):
    import ready2go_skills.core.place_plan as plp
    ra = plp.corners(a[0]*1000, a[1]*1000, a[2], a[3][0]*500 + gap*1000, a[3][1]*500 + gap*1000)
    rb = plp.corners(b[0]*1000, b[1]*1000, b[2], b[3][0]*500, b[3][1]*500)
    return not plp.rects_overlap(ra, rb)

def cover_layout(I):
    while True:
        if GUIDE:                                                        # 가림막 세로(긴 변 = 서랍 깊이), 오른쪽 [가이드]
            pyaw = rnd.uniform(-0.15, 0.15)
            px, py = rnd.uniform(0.04, I[0]-0.04), rnd.uniform(0.15, I[1]-0.04)
        else:
            pyaw = rnd.choice([0.0, math.pi/2]) + rnd.uniform(-0.2, 0.2)
            px, py = rnd.uniform(0.04, I[0]-0.04), rnd.uniform(0.14, I[1]-0.04)   # 물건은 오른쪽(y 큰 쪽), aside 는 왼쪽 [사용자 10/10 배치]
        if not fits(px, py, pyaw, SZ["cover_plate"], I, 0.030 if GUIDE else 0.003):
            continue
        for _ in range(200):
            items = []
            base = pyaw + rnd.uniform(-0.15, 0.15)
            for cls in ("eraser", "lip_balm"):
                yaw = (base + rnd.uniform(-0.08, 0.08)) if GUIDE else (pyaw + rnd.uniform(-0.3, 0.3))
                yaw = (yaw + math.pi/2) % math.pi - math.pi/2
                x, y = px + rnd.uniform(-0.03, 0.03), py + rnd.uniform(-0.03, 0.03)
                items.append((x, y, yaw, SZ[cls]))
            if all(rect_in(*it, px, py, pyaw, SZ["cover_plate"]) for it in items) and apart(items[0], items[1], 0.020 if GUIDE else 0.004):
                return (px, py, (pyaw + math.pi/2) % math.pi - math.pi/2), items[0][:3], items[1][:3]

def stack_layout(I):
    while True:
        yw = rnd.uniform(-0.35, 0.35)                                     # 몽키는 세로로 [사용자 10/10]
        x, y = rnd.uniform(0.09, I[0]-0.09), rnd.uniform(0.15 if GUIDE else 0.13, I[1]-0.04)
        if fits(x, y, yw, SZ["toy_wrench"], I, 0.003) and (not GUIDE or I[1] - y > 0.06):   # 가이드: 쌓기 오른쪽, 옆벽에서 차키·캐러멜 손가락 자리
            return (x, y), yw, rnd.uniform(-1.5, 1.5), rnd.uniform(-1.5, 1.5)

fails, counts = collections.Counter(), collections.Counter()
examples = {}
for drawer in ("drawer_top", "drawer_bottom"):
    I = d.PL[drawer]["interior_m"]
    for k in range(N):
        cp, er, lb = cover_layout(I)
        lip_first = rnd.random() < 0.5
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok, robot, srv = d.cover_scenario(drawer, cp=cp, er=er, lb=lb, lip_first=lip_first)
        counts[(drawer, "가림막")] += 1
        if not ok:
            line = [l for l in buf.getvalue().splitlines() if "FAIL" in l][0].strip()
            key = (drawer, "가림막", line.split("FAIL")[0].strip(), line.split("FAIL")[1].strip()[:70])
            fails[key] += 1
            examples.setdefault(key, (cp, er, lb, lip_first))
            print("FAIL", key, (cp, er, lb, lip_first), flush=True)
        warn = [l for l in buf.getvalue().splitlines() if "⚠" in l]
        if warn:
            fails[(drawer, "가림막", "기구학", warn[0].strip()[:70])] += 1
        at, yw, yc, yk = stack_layout(I)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok, robot, srv = d.stack_scenario(drawer, at=at, yaw_w=yw, yaw_c=yc, yaw_k=yk)
        counts[(drawer, "쌓기")] += 1
        print(f"{drawer} {k + 1}/{N} done", flush=True)
        if not ok:
            line = [l for l in buf.getvalue().splitlines() if "FAIL" in l][0].strip()
            key = (drawer, "쌓기", line.split("FAIL")[0].strip(), line.split("FAIL")[1].strip()[:70])
            fails[key] += 1
            examples.setdefault(key, (at, yw, yc, yk))
            print("FAIL", key, (at, yw, yc, yk), flush=True)
        warn = [l for l in buf.getvalue().splitlines() if "⚠" in l]
        if warn:
            fails[(drawer, "쌓기", "기구학", warn[0].strip()[:70])] += 1
for k, v in counts.items():
    f = sum(n for kk, n in fails.items() if kk[:2] == k and kk[2] != "기구학")
    print(f"{k[0]:13s} {k[1]:4s}: {v - f}/{v} 성공")
for k, v in fails.most_common():
    print(f"  {v:3d}× {k[0]} {k[1]} [{k[2]}] {k[3]}  예: {examples.get(k)}")
