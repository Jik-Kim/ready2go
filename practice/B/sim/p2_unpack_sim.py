"""P2 시연 배치 무작위 — unpack 흐름 전체(치우기 → 목표 → 원복)를 스킬 서버 실제 판단(DryOracle·check_only)으로 [사용자 10/14 PC2 통합
"물건들 랜덤 배치하면서 잘못된 거 있으면 말해줘 — 몽키·캐러멜·차키 올린 상태, 지우개·립밤 위 커버 플레이트"].
  S1(위 칸): 몽키 위 캐러멜 위 차키 — 목표 몽키(치우기 2개) / 차키(맨 위, 바로)
  S2(아래 칸): 덮개 판이 지우개·립밤을 덮음 — 목표 지우개 / 립밤. LIP_YAW=0 이면 판 밑 립밤 각도 모름(10/14 덤프처럼)
흐름(b_sk unpack·C find_with_unpack 과 같은 순서): 맨 위부터 치울 물체 → place_object free check_only(object) → 놓음(예정 자리)
→ 다시 → 목표 집기(WALL_TOO_CLOSE 면 벽 넛지 → 다시, 2번까지) → 트레이 → 역순 원복: 원래 자리 check_only(object, pose=origin)
→ WALL_TOO_CLOSE 면 벽 넛지 → 다시(2번까지). 로봇·비전은 가짜 — 판단만 [추정]. 결과는 실패 단계·코드별.
실행 (저장소 루트):  NSIM=200 SEED=1 python3 -m pytest -q -s -p no:cacheprovider practice/B/sim/p2_unpack_sim.py
설정 비교: MODE=main 이면 10/14 main(pick.axis_swap 끔·place.free_repickable_only 켬) 값으로."""
import collections, json, math, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "ros2_ws", "src", "ready2go_skills", "test"))
from test_skill_server_node import server  # noqa
from ready2go_skills.core import clear_plan as clp
from ready2go_skills.core import place_plan as plp

NSIM, SEED = int(os.environ.get("NSIM", "200")), int(os.environ.get("SEED", "1"))
MODE = os.environ.get("MODE", "now")
LIP_YAW = os.environ.get("LIP_YAW", "1") == "1"
WRENCH_YAW = os.environ.get("WRENCH_YAW", "1") == "1"   # 0 = 캐러멜이 가운데를 덮어 몽키 각도 모름 (#344 전 비전)
WALL = "WALL_TOO_CLOSE"
OBST_NUDGE = os.environ.get("OBST_NUDGE") == "1"   # 치울 물체 집기도 벽이면 넛지 → 다시 (지금 흐름 s7.1 은 pick_object 만)
MAKE_ROOM = os.environ.get("MAKE_ROOM") == "1"     # 목표 집기 NEIGHBOR_TOO_CLOSE 면 B make_room(clear_plan.plan_next) 반복 (지금 흐름엔 없음)


def norm(yaw):
    """비전 출력 범위 (−π/2, π/2]."""
    yaw = (yaw + math.pi / 2) % math.pi - math.pi / 2
    return yaw + math.pi if yaw <= -math.pi / 2 + 1e-9 else yaw


def obj(i, c, x, y, top, yaw, d, occ=(), yaw_valid=True):
    yaw = norm(yaw)
    return {"id": i, "class": c, "pose": {"frame": d, "position": [round(x, 4), round(y, 4), 0.0], "yaw": round(yaw, 4),
                                          "yaw_valid": yaw_valid}, "top_z": round(top, 4), "occluded_by": list(occ), "visible_area_m2": 0.002}


def inside(o, size_of, interior, m=0.004):
    return clp.inside(o, size_of, interior, m * 1000.0)


def center_in(o, base, size_of, shrink=0.006):
    """o 가운데가 base footprint 안(가장자리 shrink 안쪽)."""
    sz = size_of(base["class"])
    bx, by, by_ = base["pose"]["position"][0], base["pose"]["position"][1], base["pose"]["yaw"]
    dx, dy = o["pose"]["position"][0] - bx, o["pose"]["position"][1] - by
    u, v = dx * math.cos(by_) + dy * math.sin(by_), -dx * math.sin(by_) + dy * math.cos(by_)
    return abs(u) <= sz[0] / 2 - shrink and abs(v) <= sz[1] / 2 - shrink


def overlaps(a, b, size_of, gap=0.0):
    return clp.overlaps(a, b, size_of, gap * 1000.0)


def scene_s1(rng, size_of, interior, d="drawer_top"):
    """몽키 아무 자리·각도, 그 손잡이·머리 쪽 위에 캐러멜, 캐러멜 위에 차키 (가운데가 받침 안)."""
    for _ in range(2000):
        wy = rng.uniform(0, math.pi)
        w = obj("toy_wrench#1", "toy_wrench", rng.uniform(0.02, interior[0] - 0.02), rng.uniform(0.02, interior[1] - 0.02),
                0.0185, wy, d)
        if not inside(w, size_of, interior):
            continue
        t = rng.uniform(-0.05, 0.05)
        cx, cy = w["pose"]["position"][0] + t * math.cos(wy), w["pose"]["position"][1] + t * math.sin(wy)
        c = obj("caramel_box#1", "caramel_box", cx, cy, 0.0185 + 0.021, rng.uniform(0, math.pi), d)
        k = obj("car_key#1", "car_key", cx + rng.uniform(-0.012, 0.012), cy + rng.uniform(-0.012, 0.012), 0.0185 + 0.021 + 0.0158,
                rng.uniform(0, math.pi), d)
        if not (center_in(c, w, size_of, 0.0) and center_in(k, c, size_of, 0.0) and inside(c, size_of, interior) and inside(k, size_of, interior)):
            continue
        w["occluded_by"] = ["caramel_box#1"] + (["car_key#1"] if overlaps(k, w, size_of) else [])
        w["pose"]["yaw_valid"] = WRENCH_YAW
        c["occluded_by"] = ["car_key#1"]
        return [w, c, k]
    raise RuntimeError("S1 배치 실패")


PLATE_ANY = os.environ.get("PLATE_ANY") == "1"


def legs_clear(u, p, size_of, gap_mm):
    """u 가 판 다리 자리(네 모서리)와 안 겹침 — 판 밑으로 들어간 물체는 다리 사이에만 있을 수 있음."""
    legs = plp.leg_rects_mm(p["pose"], size_of(p["class"]), gap_mm)
    sz = size_of(u["class"])
    ru = plp.corners(u["pose"]["position"][0] * 1000, u["pose"]["position"][1] * 1000, u["pose"]["yaw"], sz[0] * 500, sz[1] * 500)
    return not any(plp.rects_overlap(ru, leg) for leg in legs)


def scene_s2(rng, size_of, interior, reach_x, gap_mm, d="drawer_bottom"):
    """덮개 판 밑에 지우개·립밤 — 둘 다 가운데가 판 footprint 안·다리 사이, 서로 안 겹침. 배치 규칙(C #273): 판 긴 변 = 서랍 x(±0.2 rad),
    가운데 x ≤ 120 mm. PLATE_ANY=1 이면 판 가로·x 제한 없음(규칙 밖 배치에서 어디가 막히는지)."""
    for _ in range(4000):
        py = (rng.choice([0.0, math.pi / 2]) if PLATE_ANY else 0.0) + rng.uniform(-0.2, 0.2)
        p = obj("cover_plate#1", "cover_plate", rng.uniform(0.04, reach_x if PLATE_ANY else 0.120), rng.uniform(0.04, interior[1] - 0.04),
                0.0351, py, d)
        if not inside(p, size_of, interior):
            continue
        under = []
        for i, c, h in (("eraser#1", "eraser", 0.0133), ("lip_balm#1", "lip_balm", 0.0204)):
            for _ in range(100):
                u = obj(i, c, p["pose"]["position"][0] + rng.uniform(-0.04, 0.04), p["pose"]["position"][1] + rng.uniform(-0.03, 0.03), h,
                        rng.uniform(0, math.pi), d, occ=["cover_plate#1"], yaw_valid=(LIP_YAW or c != "lip_balm"))
                if (center_in(u, p, size_of, 0.004) and inside(u, size_of, interior) and legs_clear(u, p, size_of, gap_mm)
                        and not any(overlaps(u, v, size_of, 0.003) for v in under)):
                    under.append(u)
                    break
        if len(under) == 2:
            return [p] + under
    raise RuntimeError("S2 배치 실패")


def scan_of(objs, tid):
    t = next(o for o in objs if o["id"] == tid)
    return {"target_found": True, "target": t, "candidates": [o for o in objs if o["id"] != tid], "visible_count": len(objs)}


def unocclude(objs, oid):
    return [dict(o, occluded_by=[x for x in o["occluded_by"] if x != oid]) for o in objs if o["id"] != oid]


def run_unpack(server, objs, tid, d):
    """→ (단계, 코드, 이유) — 단계 "ok" 면 원복까지 성공."""
    srv = server.srv
    orc = server.ss.DryOracle(srv, d)
    size_of = srv._size_cached()
    by = lambda os_, i: next(o for o in os_ if o["id"] == i)
    stack = []
    for n in range(3):                                           # 맨 위부터 치우기 (최대 2개)
        t = by(objs, tid)
        if not t["occluded_by"]:
            break
        tops = [r for r in t["occluded_by"] if not by(objs, r)["occluded_by"]]
        if not tops or n == 2:
            return "select", "OCCLUDED", "치울 물체 고르기 실패"
        ob = max((by(objs, r) for r in tops), key=lambda o: o["top_z"])
        orig = ob                                                # 원복은 넛지 전 처음 자리로
        for k in range(3):
            out, data = server.run("place_object", {"location": d, "slot": "free", "scan": scan_of(objs, tid), "object": ob, "check_only": True})
            if out.success or not (OBST_NUDGE and out.error_code == WALL and k < 2):
                break
            after, c2, r2 = orc.wall_nudge(objs, ob["id"])
            if after is None:
                return f"치우기 {ob['class']} 넛지", c2 or out.error_code, r2 or out.reason
            ob = dict(after, occluded_by=ob["occluded_by"])
            objs = [ob if o["id"] == ob["id"] else o for o in objs]
        if not out.success:
            return f"치우기 {ob['class']} free", out.error_code, out.reason
        pose = data["planned_pose"]
        h = size_of(ob["class"])[2]
        moved = dict(ob, pose=dict(pose, yaw_valid=True), top_z=h, occluded_by=[])
        stack.append({"id": ob["id"], "origin": orig})
        objs = [moved if o["id"] == ob["id"] else dict(o, occluded_by=[x for x in o["occluded_by"] if x != ob["id"]]) for o in objs]
    t = by(objs, tid)
    for k in range(3):                                           # 목표 집기 (공통 pick: 벽이면 넛지 → 다시)
        ok, code, why = orc.pick(objs, tid)
        if ok:
            break
        if MAKE_ROOM and code == "NEIGHBOR_TOO_CLOSE":
            cfg = srv._room_cfg(d)
            for _ in range(6):
                a = clp.plan_next(objs, tid, orc, cfg)
                if a.kind in ("pick", "fail"):
                    break
                objs = clp.apply(objs, a, cfg)
            if a.kind == "pick":
                break
            return f"목표 {t['class']} 공간 만들기", a.code or code, a.reason
        if code != WALL or k == 2:
            return f"목표 {t['class']} 집기", code, why
        after, c2, r2 = orc.wall_nudge(objs, tid)
        if after is None:
            return f"목표 {t['class']} 넛지", c2 or code, r2 or why
        objs = [after if o["id"] == tid else o for o in objs]
    objs = [o for o in objs if o["id"] != tid]                   # 트레이로
    for item in reversed(stack):                                 # 역순 원복
        oid = item["id"]
        for k in range(3):
            cur = by(objs, oid)
            out, _ = server.run("place_object", {"location": d, "pose": item["origin"]["pose"], "scan": scan_of(objs, oid),
                                                 "object": cur, "check_only": True})
            if out.success:
                break
            if out.error_code != WALL or k == 2:
                return f"원복 {cur['class']}", out.error_code, out.reason
            after, c2, r2 = orc.wall_nudge(objs, oid)
            if after is None:
                return f"원복 {cur['class']} 넛지", c2 or out.error_code, r2 or out.reason
            objs = [after if o["id"] == oid else o for o in objs]
        org = item["origin"]
        objs = [dict(org, occluded_by=[]) if o["id"] == oid else o for o in objs]
    return "ok", "", ""


def _settings(server, monkeypatch):
    if MODE != "main":
        return
    real = server.ss._yaml_cached

    def cached(path, **kw):
        dd = real(path, **kw)
        if path.name == "skills.yaml":
            dd = {**dd, "pick": {**dd["pick"], "axis_swap": False}, "place": {**dd["place"], "free_repickable_only": True}}
        return dd
    monkeypatch.setattr(server.ss, "_yaml_cached", cached)


def _report(name, res, examples):
    n = len(res)
    c = collections.Counter((s, code) for s, code, _ in res)
    ok = c.get(("ok", ""), 0)
    print(f"\n=== {name} [{MODE}{'' if LIP_YAW else ', 판 밑 립밤 각도 모름'}] {n}회: 원복까지 성공 {ok} ({100.0 * ok / max(1, n):.0f}%)")
    for (s, code), v in c.most_common():
        if s != "ok":
            print(f"  {v:4d}  {s} — {code}   예: {examples[(s, code)][:110]}")


def test_s1(server, monkeypatch):
    _settings(server, monkeypatch)
    srv = server.srv
    d = "drawer_top"
    srv.disp[d] = srv.places()[d]["tf_at_travel_m"]
    interior, size_of = srv.places()[d]["interior_m"], srv._size_cached()
    rng = random.Random(SEED)
    for tid, label in (("toy_wrench#1", "S1 몽키 찾기 (캐러멜·차키 치우기)"), ("car_key#1", "S1 차키 찾기 (맨 위)")):
        res, ex = [], {}
        for _ in range(NSIM):
            objs = scene_s1(rng, size_of, interior)
            r = run_unpack(server, json.loads(json.dumps(objs)), tid, d)
            res.append(r)
            ex.setdefault((r[0], r[1]), f"{r[2]} | " + ", ".join(f"{o['class']}({o['pose']['position'][0]*1000:.0f},{o['pose']['position'][1]*1000:.0f},{math.degrees(o['pose']['yaw']):.0f}°)" for o in objs))
        _report(label, res, ex)


def test_s2(server, monkeypatch):
    _settings(server, monkeypatch)
    srv = server.srv
    d = "drawer_bottom"
    srv.disp[d] = srv.places()[d]["tf_at_travel_m"]
    interior, size_of = srv.places()[d]["interior_m"], srv._size_cached()
    reach = ((srv.prm().get("drawer_reach_x_mm") or {}).get(d) or 129.0) / 1000.0
    gap_mm = srv.prm()["pick"]["under_gap_by_class_mm"]["cover_plate"]
    rng = random.Random(SEED + 100)
    for tid, label in (("eraser#1", "S2 지우개 찾기 (판 치우기)"), ("lip_balm#1", "S2 립밤 찾기 (판 치우기)")):
        res, ex = [], {}
        for _ in range(NSIM):
            objs = scene_s2(rng, size_of, interior, reach, gap_mm)
            r = run_unpack(server, json.loads(json.dumps(objs)), tid, d)
            res.append(r)
            ex.setdefault((r[0], r[1]), f"{r[2]} | " + ", ".join(f"{o['class']}({o['pose']['position'][0]*1000:.0f},{o['pose']['position'][1]*1000:.0f},{math.degrees(o['pose']['yaw']):.0f}°)" for o in objs))
        _report(label, res, ex)
