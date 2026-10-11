"""P2 시연 배치만으로 파지 공간 만들기 시뮬레이션 [사용자 10/11] — 한 칸에 몽키·캐러멜·차키 쌓기(몽키 위 캐러멜 위 차키),
다른 칸에 가림막·에어팟·립밤만 (다른 물건 없음). 위치·각도는 무작위, 구석에 박지 않음(벽에서 WALL_MM 이상), 아래 칸은 손 닿는 깊이 안.
에어팟(높이 21.6 mm·폭 45)·립밤(길이 71.8)은 가림막 밑(판 아래 21 mm·다리 안쪽 65×35 [hardware.md])에 안 들어가 바닥에 따로 둠.
물건마다 꺼내기를 지금 방식(aside 고정 자리·벽 넛지)과 새 방식(core/clear_plan, 스킬 서버 DryOracle)으로 비교.
  python3 practice/B/sim/p2_clear_sim.py [배치 수=50] [seed=1] [벽 여유 mm=15] [rule]
rule: 몽키·가림막을 손잡이 쪽 벽에 가로로 두지 않음 (앞판에서 S.FRONT_KEEP_MM 이상) [사용자 10/11 제안 규칙]
"""
import collections
import math
import sys
import time

N = int(sys.argv[1]) if len(sys.argv) > 1 else 50
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 1
WALL_MM = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0
RULE = len(sys.argv) > 4 and sys.argv[4] == "rule"
sys.argv = [sys.argv[0], "1", str(SEED)]
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import clear_sim as S                                            # noqa: E402  (서버·oracle·배치 도구 재사용)
from ready2go_skills.core import clear_plan as cp                 # noqa: E402

rnd = S.random.Random(SEED)
STACK = ("toy_wrench", "caramel_box", "car_key")                 # 아래부터 [P2 시연]
COVER_SET = ("cover_plate", "airpods_case", "lip_balm")


def ok_pose(o, drawer, floor):
    I = S.PLACES[drawer]["interior_m"]
    if not cp.inside(o, S.cp_size, I, WALL_MM):
        return False
    reach = (S.srv.prm().get("drawer_reach_x_mm") or {}).get(drawer)
    if reach is not None and o["pose"]["position"][0] * 1000.0 > reach:
        return False
    if RULE and o["class"] in ("toy_wrench", "cover_plate") and abs(math.sin(o["pose"]["yaw"])) > math.sin(math.radians(45)):
        if min(x for x, _ in cp.footprint_mm(o, S.cp_size)) < S.FRONT_KEEP_MM:
            return False
    return not any(cp.overlaps(o, f, S.cp_size, 1.0) for f in floor)


def rand_floor(cls, oid, drawer, floor):
    I = S.PLACES[drawer]["interior_m"]
    for _ in range(2000):
        yaw = (rnd.choice((0.0, math.pi / 2)) + rnd.uniform(-0.35, 0.35)) if rnd.random() < 0.7 else rnd.uniform(-math.pi / 2, math.pi / 2)
        o = S.mk(oid, cls, rnd.uniform(0, I[0]), rnd.uniform(0, I[1]), yaw, drawer)
        if ok_pose(o, drawer, floor):
            return o
    return None


def stack_layout(drawer):
    w = rand_floor("toy_wrench", "toy_wrench#1", drawer, [])
    if w is None:
        return None
    objs = [w]
    base = w
    for cls in STACK[1:]:
        bs = S.SIZE[base["class"]]
        bx, by = base["pose"]["position"][:2]
        c, s = math.cos(base["pose"]["yaw"]), math.sin(base["pose"]["yaw"])
        a, b = rnd.uniform(-0.25, 0.25) * bs[0], rnd.uniform(-0.2, 0.2) * bs[1]
        o = S.mk(f"{cls}#1", cls, bx + a * c - b * s, by + a * s + b * c, base["pose"]["yaw"] + rnd.uniform(-0.4, 0.4), drawer, base["top_z"])
        if not cp.inside(o, S.cp_size, S.PLACES[drawer]["interior_m"], 1.0):
            return None
        base["occluded_by"].append(o["id"])
        objs.append(o)
        base = o
    return objs


def cover_layout(drawer):
    floor = []
    for cls in COVER_SET:
        o = rand_floor(cls, f"{cls}#1", drawer, floor)
        if o is None:
            return None
        floor.append(o)
    return floor


def make(fn, drawer):
    while True:
        objs = fn(drawer)
        if objs is not None:
            return objs


def main():
    res = collections.Counter()
    fails = collections.Counter()
    acts = collections.Counter()
    examples = {}
    t0 = time.time()
    cases = [(f"쌓기({d[7:]})", stack_layout, d) for d in S.DRAWERS] + [(f"가림막·에어팟·립밤({d[7:]})", cover_layout, d) for d in S.DRAWERS]
    for name, fn, drawer in cases:
        for i in range(N):
            objs = make(fn, drawer)
            for o in objs:
                for m in ("old", "new"):
                    ok, steps, why, _ = S.retrieve([dict(x, occluded_by=list(x["occluded_by"])) for x in objs], o["id"], drawer, m == "old")
                    res[(name, o["class"], m, ok)] += 1
                    if m == "new":
                        for st in steps:
                            acts[(name, st)] += 1
                    if not ok:
                        key = why.split(" ")[0]
                        fails[(name, m, key)] += 1
                        examples.setdefault((name, m, o["class"], key), (why, [(x["id"], [round(v, 4) for v in x["pose"]["position"][:2]],
                                                                               round(x["pose"]["yaw"], 3), x["occluded_by"]) for x in objs]))
        print(f"  ... {name} {N}배치 ({time.time() - t0:.0f} s)", flush=True)
    print(f"\n===== P2 시연 배치만 — 칸마다 {N}배치, 벽에서 {WALL_MM:g} mm 이상, 아래 칸은 손 닿는 깊이 안{', 손잡이 벽 가로 금지' if RULE else ''} (seed {SEED}) =====")
    for name, fn, drawer in cases:
        print(f"\n[{name}]")
        classes = STACK if fn is stack_layout else COVER_SET
        for cls in classes:
            o_ok, n_ok = res[(name, cls, "old", True)], res[(name, cls, "new", True)]
            tot = o_ok + res[(name, cls, "old", False)]
            print(f"  {cls:13s} 지금 {o_ok / tot * 100:5.1f}%  →  새 방식 {n_ok / tot * 100:5.1f}%")
        for m in ("old", "new"):
            top = [(k[2], v) for k, v in fails.most_common() if k[0] == name and k[1] == m]
            print(f"  {'지금' if m == 'old' else '새 방식'} 실패: " + (", ".join(f"{k} {v}" for k, v in top) or "없음"))
        print("  새 방식 동작: " + ", ".join(f"{k[1]} {v}" for k, v in acts.items() if k[0] == name))
    print(f"\n걸린 시간 {time.time() - t0:.0f} s")
    for k, v in examples.items():
        if k[1] == "new":
            print(f"예시 실패 {k}: {v[0][:90]}\n   {v[1]}")


if __name__ == "__main__":
    main()
