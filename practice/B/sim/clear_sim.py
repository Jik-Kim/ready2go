"""파지 공간 만들기 시뮬레이션 [사용자 10/11] — 물건을 위·아래 서랍에 반씩 무작위로 넣고(쌓기·가림막 밑 포함) 물건마다 "꺼내기"를
지금 방식(고정 aside 자리·벽 넛지)과 새 방식(core/clear_plan: 빈 곳에 치우기·목표 넛지·좌우 밀기·막는 물체 치우기)으로 비교.

판단(집을 수 있나·놓을 수 있나)은 스킬 서버의 실제 사전 검사(움직이기 직전까지)를 그대로 씀. 로봇 기구학(IK)·충돌은 안 봄 —
그건 practice/B/sim/p2_demo.py 몫. 밀었을 때 물체는 2D 미끄러짐만(회전·넘어짐 없음) [추정].
  python3 practice/B/sim/clear_sim.py [배치 수=40] [seed=1]
"""
import sys, math, random, json, types, collections, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "ros2_ws/src/ready2go_skills"))
import demo_sim
import trace_skill_flow as tsf

N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 1
rnd = random.Random(SEED)

robot = demo_sim.Robot(tsf.HOME_J)
robot.sleep_s = 0.0
ss, sf, srv = demo_sim.load(robot)
from ready2go_skills.core import clear_plan as cp, motion_plan as mp, place_plan as plp

WORLD = json.loads((REPO / "knowledge/world.jsonld").read_text(encoding="utf-8"))["world"]["items"]
SIZE = {k: v["size_m"] for k, v in WORLD.items()}
ITEMS = ["eraser", "eraser", "lip_balm", "caramel_box", "car_key", "toy_wrench", "toy_hammer", "cover_plate",
         "airpods_case", "masking_tape", "toy_car"]                      # 당근 펜 실물 없음 [사용자 10/11]
PLACES = srv.places()
BASES = {"caramel_box", "toy_wrench"}                            # 윗면이 평평해 쌓을 수 있는 것 (P2 시연: 몽키 위 캐러멜 위 차키)
RIDERS = {"caramel_box", "car_key", "eraser", "masking_tape"}     # 위에 얹을 만한 납작한 것
UNDER_COVER = {"eraser", "car_key", "lip_balm", "masking_tape"}  # 가림막 다리 안쪽·판 밑(21 mm)에 들어가는 것
DRAWERS = ("drawer_top", "drawer_bottom")


class _Go(Exception):
    """사전 검사를 다 통과하고 처음으로 움직이려 함 = 가능."""


def _go(*a, **k):
    raise _Go()


for name in ("_to_drawer_view", "_line", "_blend", "_named", "_movej", "_grip", "_over_then_down", "_line_slow", "_exit_drawer"):
    if hasattr(srv, name) or hasattr(type(srv), name):
        setattr(srv, name, _go)
GOAL = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)


def scan(objs, tid):
    t = next(o for o in objs if o["id"] == tid)
    return {"target_found": True, "target": t, "candidates": [o for o in objs if o["id"] != tid], "visible_count": len(objs)}


def _call(fn):
    try:
        out = fn()
    except _Go:
        return True, "", ""
    except Exception as e:                                       # 설정·계산 예외 = 못 함
        return False, "SKILL_EXCEPTION", repr(e)[:120]
    o = out[0] if isinstance(out, tuple) else out
    return (bool(o.success), o.error_code or "", o.reason or "")


class Oracle:
    def __init__(self, drawer, old=False):
        self.drawer, self.old = drawer, old
        self.calls = 0

    def pick(self, objs, oid):
        self.calls += 1
        t = next(o for o in objs if o["id"] == oid)
        if t.get("occluded_by"):
            return False, "COVERED", "위에 다른 물체"
        srv.held, srv.disp = None, {self.drawer: PLACES[self.drawer]["tf_at_travel_m"]}
        return _call(lambda: srv._do_pick_object(GOAL, {"target": t, "approach_offset": [0, 0, 0.1], "scan": scan(objs, oid)}))

    def place(self, objs, held_id, pose_or_slot):
        self.calls += 1
        h = next(o for o in objs if o["id"] == held_id)
        gw = (ss._yaml_cached(REPO / "config/item_grasp.yaml").get(h["class"]) or {}).get("grasp_width_m") or SIZE[h["class"]][1]
        srv.held = {"class": h["class"], "id": held_id, "width_m": gw, "drawer_id": self.drawer,
                    "tcp_above_floor_m": SIZE[h["class"]][2] * 0.5, "long_side": False}
        srv.disp = {self.drawer: PLACES[self.drawer]["tf_at_travel_m"]}
        p = {"location": self.drawer, "scan": scan(objs, held_id)}
        p.update({"slot": pose_or_slot} if isinstance(pose_or_slot, str) else {"pose": pose_or_slot})
        r = _call(lambda: srv._place_in_drawer(GOAL, p, self.drawer))
        srv.held = None
        return r

    def wall_nudge(self, objs, oid):
        """기존 벽 넛지 계획(mp.plan_drag)과 끄는 길 이웃 검사(지금 방식) → 예상 위치. 새 방식은 길에 물체가 있으면 밀기로 넘김."""
        self.calls += 1
        t = next(o for o in objs if o["id"] == oid)
        prm, place = srv.prm(), PLACES[self.drawer]
        size, _ = srv.item(t["class"])
        g = dict(prm["gripper"], wall_offset_mm=(prm.get("drawer_wall_offset_mm") or {}).get(self.drawer),
                 wall_tcp_min_mm=(prm["drag"].get("wall_tcp_min_by_drawer_mm") or {}).get(self.drawer),
                 reach_x_max_mm=(prm.get("drawer_reach_x_mm") or {}).get(self.drawer),
                 max_open_mm=prm["pick"]["max_open_width_m"] * 1000.0, tilt_align_deg=prm["pick"]["tilt_align_deg"],
                 axis_grasp=bool(prm["pick"].get("axis_grasp")), front_tilt_within_mm=prm["pick"].get("front_tilt_within_mm"),
                 round=t["class"] in (prm["pick"].get("round_classes") or []) and bool(prm["pick"].get("round_wall")))
        try:
            plan = mp.plan_drag(target=t, size_m=size, interior_m=place["interior_m"], g=g, drag=prm["drag"])
        except Exception as e:
            return None, "SKILL_EXCEPTION", repr(e)[:100]
        if plan.error_code:
            return None, plan.error_code, plan.reason
        if not plan.needed:
            return None, "NOT_NEEDED", plan.reason
        if plan.push_to_xy_m is not None:                        # 뒤에서 밀어 벽에 눕힘 → 벽에 붙어 축에 맞춤 [예상]
            px, py = plan.push_dir
            yaw = math.pi / 2 if px else 0.0
            half = (size[1] if px else size[1]) / 2.0
            p = list(t["pose"]["position"])
            if px:
                p[0] = half + 0.0005 if px < 0 else place["interior_m"][0] - half - 0.0005
            else:
                p[1] = half + 0.0005 if py < 0 else place["interior_m"][1] - half - 0.0005
            after = dict(t, pose=dict(t["pose"], position=p, yaw=yaw))
        else:
            after = cp.moved(t, plan.shift_x_m, plan.shift_y_m)
        group = {oid} | cp.riders(objs, oid)
        others = [o for o in objs if o["id"] not in group]
        steps = 20
        for k in range(1, steps + 1):                            # 끄는 길에 물체 (높이가 겹치는 것만) → 지금 방식은 거부 NEIGHBOR_TOO_CLOSE
            f = k / steps
            mid = cp.moved(t, (after["pose"]["position"][0] - t["pose"]["position"][0]) * f,
                           (after["pose"]["position"][1] - t["pose"]["position"][1]) * f)
            hit = next((o["id"] for o in others if cp.collide(mid, o, cp_size)), None)
            if hit:
                return None, "NEIGHBOR_TOO_CLOSE", f"끄는 길에 {hit}"
        return after, "", plan.reason


def cp_size(cls):
    return SIZE[cls]


# ---------------------------------------------------------------- 무작위 배치
def mk(oid, cls, x, y, yaw, drawer, z0=0.0):
    return {"id": oid, "class": cls, "top_z": round(z0 + SIZE[cls][2], 4), "occluded_by": [],
            "pose": {"frame": drawer, "position": [x, y, 0.0], "yaw": (yaw + math.pi / 2) % math.pi - math.pi / 2, "yaw_valid": True}}


def layout(drawer, classes):
    I = PLACES[drawer]["interior_m"]
    objs, n = [], collections.Counter()
    order = sorted(classes, key=lambda c: -SIZE[c][0] * SIZE[c][1])
    cover = None
    stack_h = I[2] - 0.020                                       # 쌓인 윗면 상한(테두리 − 여유)
    for cls in order:
        n[cls] += 1
        oid = f"{cls}#{n[cls]}"
        placed = False
        floor = [o for o in objs if cp.on_floor(objs, o["id"])]
        # 가림막 밑 (다리 안쪽 65×35, 판 아래 21 mm) — 얇은 물체 [P2 시연 배치]
        if cover and cls in UNDER_COVER and rnd.random() < 0.5:
            cx, cy = cover["pose"]["position"][:2]
            for _ in range(60):
                yaw = cover["pose"]["yaw"] + rnd.uniform(-0.3, 0.3)
                o = mk(oid, cls, cx + rnd.uniform(-0.015, 0.015), cy + rnd.uniform(-0.01, 0.01), yaw, drawer)
                unders = [x for x in objs if x["id"] in cover["occluded_by"]]
                if len(unders) >= 2:
                    break
                if cp.inside(o, cp_size, I, 1.0) and not any(cp.overlaps(o, f, cp_size, 2.0) for f in floor + unders if f["id"] != cover["id"]):
                    objs.append(o)
                    cover["occluded_by"].append(oid)
                    placed = True
                    break
        # 쌓기: 더 큰 바닥 물체 위 (덮개 판 제외)
        if not placed and cls in RIDERS and rnd.random() < 0.35:
            bases = [b for b in floor if b["class"] in BASES and not b["occluded_by"]
                     and SIZE[b["class"]][0] * SIZE[b["class"]][1] > SIZE[cls][0] * SIZE[cls][1]
                     and b["top_z"] + SIZE[cls][2] <= stack_h]
            if bases:
                b = rnd.choice(bases)
                bx, by_ = b["pose"]["position"][:2]
                bs = SIZE[b["class"]]
                for _ in range(40):
                    a, s_ = rnd.uniform(-0.35, 0.35) * bs[0], rnd.uniform(-0.3, 0.3) * bs[1]
                    c, s = math.cos(b["pose"]["yaw"]), math.sin(b["pose"]["yaw"])
                    o = mk(oid, cls, bx + a * c - s_ * s, by_ + a * s + s_ * c, rnd.uniform(-math.pi / 2, math.pi / 2), drawer, b["top_z"])
                    if cp.inside(o, cp_size, I, 1.0):
                        objs.append(o)
                        b["occluded_by"].append(oid)
                        placed = True
                        break
        if not placed:
            for _ in range(500):
                yaw = (rnd.choice((0.0, math.pi / 2)) + rnd.uniform(-0.35, 0.35)) if rnd.random() < 0.7 else rnd.uniform(-math.pi / 2, math.pi / 2)
                o = mk(oid, cls, rnd.uniform(0, I[0]), rnd.uniform(0, I[1]), yaw, drawer)
                if cp.inside(o, cp_size, I, 1.0) and not any(cp.overlaps(o, f, cp_size, 1.0) for f in floor):
                    objs.append(o)
                    placed = True
                    if cls == "cover_plate":
                        cover = o
                    break
        if not placed:
            return None
    # 가림막 밑 물체: 가림막 top_z 는 그대로(다리), 밑 물체 occluded_by 에 가림막
    if cover:
        for oid in list(cover["occluded_by"]):
            o = next(x for x in objs if x["id"] == oid)
            o["occluded_by"] = []
        under = list(cover["occluded_by"])
        cover["occluded_by"] = []
        for oid in under:
            next(x for x in objs if x["id"] == oid)["occluded_by"] = [cover["id"]]
    return objs


def layouts():
    while True:
        cls = ITEMS[:]
        rnd.shuffle(cls)
        k = rnd.choice((5, 6))
        top, bot = layout("drawer_top", cls[:k]), layout("drawer_bottom", cls[k:])
        if top is not None and bot is not None:
            return {"drawer_top": top, "drawer_bottom": bot}


# ---------------------------------------------------------------- 지금 방식 (고정 aside 자리·벽 넛지만)
def plan_old(objs, tid, oracle, cfg, used_slots):
    by = {o["id"]: o for o in objs}
    tops = [r for r in cp.riders(objs, tid) if not cp.riders(objs, r)]
    if tops:
        top = max(tops, key=lambda r: by[r]["top_z"])
        ok, code, reason = oracle.pick(objs, top)
        if not ok:
            if code == "WALL_TOO_CLOSE":
                after, c2, r2 = oracle.wall_nudge(objs, top)
                if after is not None:
                    return cp.Action("wall_nudge", top, r2, extra={"after": after})
            return cp.Action("fail", top, f"위 물체 {top}: {reason}", code=code)
        for slot in ("aside_1", "aside_2"):
            if slot in used_slots:
                continue
            ok2, c2, r2 = oracle.place(objs, top, slot)
            if ok2:
                used_slots.add(slot)
                sl = PLACES[cfg.frame]["place_slots"][slot]
                return cp.Action("unstack", top, slot, to_pose={"frame": cfg.frame, "position": list(sl["position"]), "yaw": sl["yaw"]})
        return cp.Action("fail", top, "aside 자리 없음/막힘", code="ASIDE_BLOCKED")
    ok, code, reason = oracle.pick(objs, tid)
    if ok:
        return cp.Action("pick", tid)
    if code == "WALL_TOO_CLOSE":
        after, c2, r2 = oracle.wall_nudge(objs, tid)
        if after is not None:
            return cp.Action("wall_nudge", tid, r2, extra={"after": after})
        code, reason = c2 or code, r2 or reason
    return cp.Action("fail", tid, reason, code=code)


def retrieve(objs, tid, drawer, old):
    oracle = Oracle(drawer, old)
    cfg = cp.Config(interior_m=PLACES[drawer]["interior_m"], frame=drawer, size_of=cp_size)
    used, steps, last = set(), [], None
    for _ in range(10):
        a = plan_old(objs, tid, oracle, cfg, used) if old else cp.plan_next(objs, tid, oracle, cfg)
        if a.kind == "pick":
            return True, steps, None, oracle.calls
        if a.kind == "fail":
            return False, steps, (a.code or "?") + " " + (a.reason or "")[:70], oracle.calls
        steps.append(a.kind)
        objs = cp.apply(objs, a, cfg)
        last = a
    return False, steps, "STEP_LIMIT", oracle.calls


def main():
    res = {m: collections.Counter() for m in ("old", "new")}
    fails = {m: collections.Counter() for m in ("old", "new")}
    acts = {m: collections.Counter() for m in ("old", "new")}
    per_kind = collections.Counter()
    examples = {}
    t0 = time.time()
    total_targets = 0
    for i in range(N):
        L = layouts()
        for drawer in DRAWERS:
            objs = L[drawer]
            stacked = {o["id"] for o in objs if o.get("occluded_by")}
            for o in objs:
                total_targets += 1
                kind = "쌓임 밑" if o["id"] in stacked else ("위에 얹힘" if not cp.on_floor(objs, o["id"]) else "바닥")
                per_kind[(drawer, kind)] += 1
                for m in ("old", "new"):
                    ok, steps, why, calls = retrieve([dict(x, occluded_by=list(x["occluded_by"])) for x in objs], o["id"], drawer, m == "old")
                    res[m][(drawer, kind, ok)] += 1
                    for s in steps:
                        acts[m][s] += 1
                    if not ok:
                        key = why.split(" ")[0]
                        fails[m][(drawer, key)] += 1
                        examples.setdefault((m, drawer, key), (o["id"], why, [(x["id"], [round(v, 3) for v in x["pose"]["position"][:2]], round(x["pose"]["yaw"], 2), x["occluded_by"]) for x in objs]))
        if (i + 1) % 5 == 0:
            print(f"  ... 배치 {i + 1}/{N} ({time.time() - t0:.0f} s)", flush=True)
    print(f"\n===== 파지 공간 만들기 시뮬레이션 — 배치 {N}개 × 위·아래, 물건 {total_targets}번 꺼내기 (seed {SEED}) =====")
    for drawer in DRAWERS:
        print(f"\n[{drawer}]")
        for kind in ("바닥", "위에 얹힘", "쌓임 밑"):
            tot = per_kind[(drawer, kind)]
            if not tot:
                continue
            o_ok, n_ok = res["old"][(drawer, kind, True)], res["new"][(drawer, kind, True)]
            print(f"  {kind:6s} {tot:4d}번: 지금 {o_ok / tot * 100:5.1f}%  →  새 방식 {n_ok / tot * 100:5.1f}%")
        for m in ("old", "new"):
            top = [(k[1], v) for k, v in fails[m].most_common() if k[0] == drawer][:6]
            print(f"  {'지금' if m == 'old' else '새 방식'} 실패: " + ", ".join(f"{k} {v}" for k, v in top))
    for m in ("old", "new"):
        tot = sum(v for k, v in res[m].items() if k[2])
        print(f"\n{'지금' if m == 'old' else '새 방식'} 전체 성공 {tot}/{total_targets} = {tot / total_targets * 100:.1f}%  동작: {dict(acts[m])}")
    print(f"\n걸린 시간 {time.time() - t0:.0f} s")
    out = HERE / f"clear_sim_examples_{SEED}.json"
    out.write_text(json.dumps({f"{k[0]}|{k[1]}|{k[2]}": v for k, v in examples.items()}, ensure_ascii=False, indent=1))
    print(f"실패 예시: {out}")


if __name__ == "__main__":
    main()
