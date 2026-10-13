"""뭉친 물체 공간 만들기 sim [10/13 일지 14~28번] — 스킬 서버 실제 판단(DryOracle)으로 plan_next → apply 를 집힐 때까지 반복.
  test_real: 덤프 inspect_20261013_060416_812Z(오른쪽 벽 에어팟) 장면
  test_rand: 무작위 뭉침(목표 + 이웃 2~4개, 28~55 mm 둘레) NSIM 개 — 성공·실패 이유·판단 시간
실행 (저장소 루트):  NSIM=400 SEED=3 python3 -m pytest -q -s -p no:cacheprovider practice/B/sim/cluster_sim.py -k rand
"""
import sys, os, math, random, collections, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "ros2_ws", "src", "ready2go_skills", "test"))
from test_skill_server_node import server  # noqa
from ready2go_skills.core import clear_plan as clp

D = "drawer_top"
def o(i, c, x, y, top, yaw):
    return {"id": i, "class": c, "pose": {"frame": D, "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True},
            "top_z": top, "occluded_by": [], "visible_area_m2": 0.002}

def run_loop(srv, ss, objs0, tid, steps=8, verbose=False):
    cfg = srv._room_cfg(D); orc = ss.DryOracle(srv, D)
    objs = objs0; seen = []; hist = []
    for n in range(steps):
        a = clp.plan_next(objs, tid, orc, cfg)
        hist.append(f"{a.kind} {a.target} {a.reason}"[:110])
        if verbose: print("  ", n, hist[-1])
        if a.kind == "pick": return "ok", hist
        if a.kind == "fail": return "fail", hist
        objs = clp.apply(objs, a, cfg)
        key = tuple((x["id"], round(x["pose"]["position"][0], 3), round(x["pose"]["position"][1], 3)) for x in objs)
        if key in seen: return "loop", hist
        seen.append(key)
    return "cap", hist

def test_real(server):
    srv = server.srv; srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    air = o("airpods_case#1", "airpods_case", 0.1079, 0.0219, 0.0229, 0.0061)
    objs = [air, o("caramel_box#1", "caramel_box", 0.0361, 0.0221, 0.0228, -0.0083),
            o("toy_wrench#1", "toy_wrench", 0.1135, 0.0524, 0.016, -0.1916),
            o("eraser#1", "eraser", 0.1732, 0.0103, 0.0138, 0.0208)]
    objs, _ = srv._room_objs({"scan": {"target_found": True, "target": air, "candidates": objs[1:]}, "target": air}, D, air["id"], "make_room")
    print("\nREAL", run_loop(srv, server.ss, objs, air["id"], verbose=True)[0])

def test_dbg(server):
    srv = server.srv; srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    air = o("airpods_case#1", "airpods_case", 0.1079, 0.0219, 0.0229, 0.0061)
    objs = [air, o("caramel_box#1", "caramel_box", 0.0361, 0.0221, 0.0228, -0.0083),
            o("toy_wrench#1", "toy_wrench", 0.1135, 0.0524, 0.016, -0.1916),
            o("eraser#1", "eraser", 0.1732, 0.0103, 0.0138, 0.0208)]
    objs, _ = srv._room_objs({"scan": {"target_found": True, "target": air, "candidates": objs[1:]}, "target": air}, D, air["id"], "make_room")
    cfg = srv._room_cfg(D); orc = server.ss.DryOracle(srv, D)
    print("\nPRESS", clp.press_point(objs, "toy_wrench#1", cfg.size_of, **clp._pkw(cfg)), cfg.narrow_of("toy_wrench"))
    return
    for u in cfg.axes:
        for d in (0.02, 0.04, 0.06, 0.08):
            o2, done, pushed = clp.push_move(objs, air["id"], u, d, cfg.interior_m, cfg.size_of, clp.pushable, cfg.max_chain)
            print(u, d, round(done*1000), pushed)
    for cost, a, after in sorted(clp._self_moves(objs, air["id"], cfg, fine=True), key=lambda c: c[0]):
        if a.kind == "sweep" and a.dist_m > 0.075:
            print(round(cost*1000), a.reason, orc.pick(after, air["id"]))

CLS = ["airpods_case", "caramel_box", "toy_wrench", "eraser", "lip_balm", "toy_hammer"]

def scene(rng, srv, interior):
    size_of = srv._size_cached()
    objs = []
    tcls = rng.choice([c for c in CLS if c not in ("toy_wrench", "toy_hammer")])
    n = rng.randint(2, 4)
    others = rng.sample([c for c in CLS if c != tcls], n)
    tries = 0
    for i, c in enumerate([tcls] + others):
        sz = size_of(c)
        while tries < 400:
            tries += 1
            yaw = rng.choice([0.0, math.pi / 2]) + rng.uniform(-0.2, 0.2)
            if i == 0:
                x = rng.uniform(0.04, interior[0] - 0.04); y = rng.choice([sz[1] / 2 + 0.002, rng.uniform(0.04, interior[1] - 0.04)])
                yaw = rng.uniform(-0.05, 0.05)
            else:
                t = objs[0]["pose"]["position"]
                ang = rng.uniform(0, 2 * math.pi); r = rng.uniform(0.028, 0.055)
                x, y = t[0] + r * math.cos(ang), t[1] + r * math.sin(ang)
            ob = o(f"{c}#1", c, round(x, 4), round(y, 4), sz[2] + 0.001, yaw)
            if not clp.inside(ob, size_of, interior, -1.0):
                continue
            if any(clp.overlaps(ob, p, size_of, -2.0) for p in objs):
                continue
            objs.append(ob); break
    return objs

def test_rand(server):
    srv = server.srv; srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    interior = srv.places()[D]["interior_m"]
    rng = random.Random(int(os.environ.get("SEED", "7")))
    res = collections.Counter(); bad = []
    t0 = time.time()
    for k in range(int(os.environ.get("NSIM", "120"))):
        objs = scene(rng, srv, interior)
        if len(objs) < 3: continue
        tid = objs[0]["id"]
        objs, err = srv._room_objs({"scan": {"target_found": True, "target": objs[0], "candidates": objs[1:]}, "target": objs[0]}, D, tid, "make_room")
        if err: res["badscan"] += 1; continue
        r, hist = run_loop(srv, server.ss, objs, tid)
        res[r] += 1
        res[(r, len(hist))] += 1
        if r != "ok":
            bad.append((k, r, [(x["id"], x["pose"]["position"][:2], round(x["pose"]["yaw"], 2)) for x in objs], hist))
    print("\n", dict(res), round(time.time() - t0, 1), "s")
    for b in bad[:25]:
        print(b[0], b[1], b[2]); [print("     ", h) for h in b[3][-3:]]
