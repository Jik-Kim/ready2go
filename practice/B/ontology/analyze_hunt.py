"""hunt_cases.py 결과(hunt/hunt_*.json) 묶기 — 실패를 ① 기존 난제 ② 새 물리 난제 후보 ③ B 계획 빈틈(코드로 풀 수 있음)으로.

같은 seed·mode 로 배치를 다시 만들어 실패 순간을 재생하고, 막는 물체를 따로 집을 수 있는지 B 판단으로 확인.
  python3 practice/B/ontology/analyze_hunt.py            → hunt/summary.json + 표 출력
"""
import sys, json, glob, random, dataclasses, collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.argv = [sys.argv[0], "0", "1"]
sys.path.insert(0, str(HERE.parent / "sim"))
import clear_sim as cs  # noqa: E402

cp, srv = cs.cp, cs.srv
BIG = {"toy_wrench", "toy_hammer", "cover_plate"}
BLOCK_PATS = {"drag_path_blocked", "finger_zone_blocked", "push_spot_blocked"}


def replay(mode, seed, want):
    """want: {layout: [(drawer, target_class), ...]} → {(layout, drawer, target_class): 실패 순간 상세}."""
    cs.RULES = mode in ("rules", "rules2")
    cs.BIG = {"toy_hammer", "cover_plate"} if mode == "rules2" else {"toy_hammer", "toy_wrench", "cover_plate"}
    sys.argv = [sys.argv[0], "0", str(seed)] + ([mode] if mode != "none" else [])
    cs.rnd = random.Random(seed)
    out = {}
    for i in range(max(want) + 1):
        L = cs.layouts()
        for drawer, tcls in want.get(i, []):
            objs = [dict(x, occluded_by=list(x["occluded_by"])) for x in L[drawer]]
            for o in [x for x in objs if x["class"] == tcls]:
                oracle = cs.Oracle(drawer)
                cfg = dataclasses.replace(srv._room_cfg(drawer), size_of=cs.cp_size)
                cur, steps, seen, a = [dict(x, occluded_by=list(x["occluded_by"])) for x in objs], [], [], None
                for _ in range(10):
                    a = cp.plan_next(cur, o["id"], oracle, cfg)
                    if a.kind in ("pick", "fail"):
                        break
                    key = (a.kind, a.target, tuple(round(v, 3) for v in (a.to_pose or {}).get("position", [])[:2]))
                    seen.append(key)
                    steps.append(a.kind)
                    cur = cp.apply(cur, a, cfg)
                if a is None or a.kind == "pick":
                    continue
                by = {x["id"]: x for x in cur}
                reach = (srv.prm().get("drawer_reach_x_mm") or {}).get(drawer)
                far = reach is not None and o["pose"]["position"][0] * 1000.0 > reach
                blk = next((w for w in (a.reason or "").replace("—", " ").split() if w in by and w != a.target), None)
                bpick = oracle.pick(cur, blk) if blk else None
                repeat = len(seen) != len(set(seen))
                out.setdefault((i, drawer, tcls), {"far": far, "repeat": repeat, "fail": a.kind, "reason": a.reason, "on": a.target,
                                                  "blocker": blk, "blocker_class": by[blk]["class"] if blk else None,
                                                  "blocker_pick": list(bpick) if bpick else None, "steps": steps})
    return out


def bucket(r, rp):
    """한 실패 → (분류, 이름)."""
    code, pat = r["code"], r["pat"]
    if code == "NO_FREE_SPACE":
        return "known", "no_free_space"
    if rp and rp["far"]:
        return "known", "beyond_reach" + ("+계획 반복" if rp["repeat"] else "")
    if r["case"] in ("cluster_front_wall", "handle_wall_wide"):
        return "known", r["case"]
    if pat == "handle_wall_no_inward":
        if r["fail_on"] in BIG:
            return "known", "handle_wall_wide"
        return "new", f"손잡이 벽 근처 {r['fail_on']} — 안쪽 넛지 금지로 할 동작 없음"
    if rp and rp["repeat"]:
        return "gap", "같은 치우기 반복 (치운 자리가 그대로 막음)"
    if pat in BLOCK_PATS and rp and rp["blocker"]:
        ok = rp["blocker_pick"] and rp["blocker_pick"][0]
        if ok:
            return "gap", f"{pat}: 막는 {rp['blocker_class']} 은 집을 수 있는데 안 치움"
        return "new", f"{pat}: 막는 {rp['blocker_class']} 도 막힘 ({(rp['blocker_pick'] or ['', '?'])[1]})"
    if code == "STEP_LIMIT":
        return "gap", "10동작 안에 못 끝냄"
    return "other", f"{code} {pat}"


def main():
    files = sorted(glob.glob(str(HERE / "hunt" / "hunt_*.json")))
    total = ok = 0
    groups = collections.Counter()
    by_mode = collections.defaultdict(collections.Counter)
    examples = {}
    for f in files:
        d = json.load(open(f))
        if "records" not in d:
            continue
        total += d["targets"]
        ok += d["ok"]
        want = collections.defaultdict(list)
        for r in d["records"]:
            want[r["layout"]].append((r["drawer"], r["target"]))
        rp = replay(d["mode"], d["seed"], want)
        for r in d["records"]:
            kind, name = bucket(r, rp.get((r["layout"], r["drawer"], r["target"])))
            groups[(kind, name)] += 1
            by_mode[d["mode"]][(kind, name)] += 1
            examples.setdefault(f"{kind}|{name}", []).append({"mode": d["mode"], "seed": d["seed"], **r,
                                                              "replay": rp.get((r["layout"], r["drawer"], r["target"]))}) \
                if len(examples.get(f"{kind}|{name}", [])) < 5 else None
        print(f"  {Path(f).name} 재생 끝", flush=True)
    fails = total - ok
    print(f"\n꺼내기 {total} · 성공 {ok} ({ok / max(total, 1) * 100:.1f}%) · 실패 {fails}")
    for kind, title in (("known", "① 기존 난제"), ("new", "② 새 물리 난제 후보"), ("gap", "③ B 계획 빈틈"), ("other", "기타")):
        rows = [(k[1], v) for k, v in groups.most_common() if k[0] == kind]
        print(f"\n{title} — {sum(v for _, v in rows)}")
        for name, v in rows[:15]:
            print(f"  {v:5d}  {name}")
    (HERE / "hunt" / "summary.json").write_text(json.dumps({
        "targets": total, "ok": ok, "groups": {f"{k[0]}|{k[1]}": v for k, v in groups.most_common()},
        "by_mode": {m: {f"{k[0]}|{k[1]}": v for k, v in c.most_common()} for m, c in by_mode.items()},
        "examples": examples}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
