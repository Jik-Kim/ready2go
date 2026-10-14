"""무작위 배치에서 난제 찾기 — clear_sim 배치·스킬 서버 판단(make_room 포함)으로 꺼내기를 돌리고,
실패한 장면의 관계(벽 틈·이웃·쌓임·판 밑·깊이)를 뽑아 layout_cases.json 의 난제에 맞는지 보고, 안 맞는 것을 묶어 새 난제 후보로.

  python3 practice/B/ontology/hunt_cases.py <배치 수> <seed> [none|rules|rules2]
결과: practice/B/ontology/hunt/hunt_<mode>_<seed>.json (git 에 넣지 않음)
"""
import sys, json, math, time, random, collections, dataclasses
from pathlib import Path

HERE = Path(__file__).resolve().parent
N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 1
MODE = sys.argv[3] if len(sys.argv) > 3 else "none"
sys.argv = [sys.argv[0], "0", str(SEED)] + ([MODE] if MODE != "none" else [])
sys.path.insert(0, str(HERE.parent / "sim"))
import clear_sim as cs  # noqa: E402  (모듈 import 때 스킬 서버 판단 코드를 올림)

cs.rnd = random.Random(SEED)
cp, srv = cs.cp, cs.srv
TOUCH_MM = 10.0          # 벽에 '붙음'
NEAR_MM = 15.0           # 이웃 '가까움'
WIDE = {"toy_wrench", "toy_hammer", "cover_plate"}
TRAITS = {"lip_balm": "cylinder", "caramel_box": "hollow_flexible", "masking_tape": "has_hole", "toy_wrench": "uneven_top"}


def feats(objs, oid, drawer):
    """한 물체의 관계 — layout_cases.json relations 이름으로."""
    by = {o["id"]: o for o in objs}
    o = by[oid]
    I = [v * 1000.0 for v in cs.PLACES[drawer]["interior_m"]]
    fp = cp.footprint_mm(o, cs.cp_size)
    xs, ys = [p[0] for p in fp], [p[1] for p in fp]
    gaps = {"front_handle": min(xs), "back": I[0] - max(xs), "side_y0": min(ys), "side_y1": I[1] - max(ys)}
    walls = sorted(k for k, g in gaps.items() if g < TOUCH_MM)
    floor = [x for x in objs if x["id"] != oid and cp.on_floor(objs, x["id"]) and oid not in (x.get("occluded_by") or [])
             and x["id"] not in (o.get("occluded_by") or [])]
    near = sorted(x["class"] for x in floor if cp.overlaps(o, x, cs.cp_size, NEAR_MM))
    reach = (srv.prm().get("drawer_reach_x_mm") or {}).get(drawer)
    yaw = o["pose"]["yaw"]
    return {
        "class": o["class"],
        "walls": walls,
        "gaps_mm": {k: round(v, 1) for k, v in gaps.items()},
        "near": near,
        "on_top_of": not cp.on_floor(objs, oid),
        "has_riders": bool(cp.riders(objs, oid)) and o["class"] != "cover_plate",
        "under_cover": any(by.get(c, {}).get("class") == "cover_plate" for c in (o.get("occluded_by") or [])),
        "beyond_reach": reach is not None and max(xs) > reach,
        "across": abs(math.sin(yaw)) > math.sin(math.radians(45)),   # 긴 변이 손잡이 벽과 나란히
    }


def match(code, f, steps):
    """layout_cases.json 의 난제 id (못 찾으면 None)."""
    if code == "NO_FREE_SPACE":
        return "no_free_space"
    if f["beyond_reach"]:
        return "beyond_reach"
    if code == "OCCLUSION_UNKNOWN":
        return "relation_unknown"
    if "front_handle" in f["walls"] and len(f["near"]) + len(f["walls"]) >= 3:
        return "cluster_front_wall"
    if "front_handle" in f["walls"] and f["class"] in WIDE and f["across"]:
        return "handle_wall_wide"
    if f["under_cover"] and code == "PLACE_BLOCKED":
        return "under_cover_crossing"
    return None


def sig(code, f, drawer, steps):
    """안 맞는 실패를 묶는 열쇠 — 관계 모양만 (자리 숫자 빼고)."""
    nb = "이웃0" if not f["near"] else ("이웃1" if len(f["near"]) == 1 else "이웃2+")
    st = "쌓임위" if f["on_top_of"] else ("판밑" if f["under_cover"] else ("위에얹힘" if f["has_riders"] else "바닥"))
    walls = "+".join(f["walls"]) or "벽없음"
    return f"{code} | {f['class']} | {st} | {walls} | {nb} | {'가로' if f['across'] else '세로'}"


PATS = (("끄는 길에", "drag_path_blocked"), ("뒤에서 밀 손가락 자리에", "push_spot_blocked"), ("벌린 손가락 자리에", "finger_zone_blocked"),
        ("손잡이 쪽 벽에 붙음", "handle_wall_no_inward"))


def pattern(code, reason, steps, objs):
    """B 거부 이유 문장 → 짧은 이름 + 막는 물체 class."""
    by = {o["id"]: o["class"] for o in objs}
    for key, name in PATS:
        if key in (reason or ""):
            rest = reason.split(key, 1)[1].strip()
            oid = rest.split()[0].strip(" —,") if rest else ""
            return name, by.get(oid, "")
    if code == "STEP_LIMIT":
        top = collections.Counter(steps).most_common(1)
        return (f"loop_{top[0][0]}" if top else "loop"), ""
    return ((reason or "").split(" ")[0][:20] or "-"), ""


def retrieve(objs, tid, drawer):
    oracle = cs.Oracle(drawer)
    cfg = dataclasses.replace(srv._room_cfg(drawer), size_of=cs.cp_size)
    steps = []
    for _ in range(10):
        a = cp.plan_next(objs, tid, oracle, cfg)
        if a.kind == "pick":
            return True, steps, None, None, objs
        if a.kind == "fail":
            return False, steps, a.code or "?", a, objs
        steps.append(a.kind)
        objs = cp.apply(objs, a, cfg)
    return False, steps, "STEP_LIMIT", None, objs


def main():
    t0 = time.time()
    tot, ok_n = 0, 0
    matched, unmatched, examples = collections.Counter(), collections.Counter(), {}
    records = []
    for i in range(N):
        L = cs.layouts()
        for drawer in cs.DRAWERS:
            objs0 = L[drawer]
            for o in objs0:
                tot += 1
                objs = [dict(x, occluded_by=list(x["occluded_by"])) for x in objs0]
                ok, steps, code, act, end = retrieve(objs, o["id"], drawer)
                if ok:
                    ok_n += 1
                    continue
                who = (act.target if act and act.target in {x["id"] for x in end} else o["id"])
                f = feats(end, who, drawer)
                cid = match(code, f, steps)
                key = cid or sig(code, f, drawer, steps)
                (matched if cid else unmatched)[key] += 1
                pat, blk = pattern(code, act.reason if act else "", steps, end)
                records.append({"layout": i, "drawer": drawer, "target": o["class"], "fail_on": f["class"], "code": code, "pat": pat,
                                "blocker": blk, "case": cid, "walls": f["walls"], "front_mm": f["gaps_mm"]["front_handle"],
                                "on_top_of": f["on_top_of"], "under_cover": f["under_cover"], "near_n": len(f["near"]),
                                "steps": steps})
                if key not in examples or len(examples[key]) < 3:
                    examples.setdefault(key, []).append({
                        "seed": SEED, "mode": MODE, "layout": i, "drawer": drawer, "target": o["id"], "fail_on": who,
                        "code": code, "reason": (act.reason if act else "")[:120], "steps": steps, "feats": f,
                        "scene": [{"id": x["id"], "class": x["class"], "xy_mm": [round(v * 1000, 1) for v in x["pose"]["position"][:2]],
                                   "yaw_deg": round(math.degrees(x["pose"]["yaw"]), 1), "top_z_mm": round(x["top_z"] * 1000, 1),
                                   "occluded_by": x["occluded_by"]} for x in end]})
        if (i + 1) % 10 == 0:
            print(f"  [{MODE} {SEED}] 배치 {i + 1}/{N} ({time.time() - t0:.0f} s)", flush=True)
    out = HERE / "hunt" / f"hunt_{MODE}_{SEED}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"mode": MODE, "seed": SEED, "layouts": N, "targets": tot, "ok": ok_n,
                               "matched": dict(matched), "unmatched": dict(unmatched), "examples": examples, "records": records,
                               "sec": round(time.time() - t0)}, ensure_ascii=False, indent=1))
    print(f"[{MODE} {SEED}] 꺼내기 {tot} · 성공 {ok_n} ({ok_n / max(tot, 1) * 100:.1f}%) · 기존 난제 {sum(matched.values())} · 새 후보 {sum(unmatched.values())} · {time.time() - t0:.0f} s → {out}")


if __name__ == "__main__":
    main()
