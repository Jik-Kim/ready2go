"""단계 ② — 관계 → 난제 예측 vs B 사전 판단 vs sim 결과 비교표.

무작위 배치(clear_sim)에서 물건마다, 움직이기 전 장면 하나로
  (가) 관계만 보고 난제 예측 (layout_cases.json 의 when 을 코드로 옮긴 predict)
  (나) 관계 + B 사전 검사(집기 검사 한 번, 지금 스킬 서버 판단) — 집히면 바로 집기, 아니면 (가)
를 내고, 실제 sim 꺼내기(공간 만들기 포함, hunt_cases.retrieve)의 결과와 비교한다.
실제 결과 = 실패면 impossible, 성공이면 첫 동작 종류(pick → direct, nudge·wall_nudge → nudge, sweep·remove → make_room,
unstack → remove_top).

  python3 practice/B/ontology/compare_cases.py <배치 수> <seed> [none|rules|rules2]   → hunt/compare_<mode>_<seed>.json
  python3 practice/B/ontology/compare_cases.py --sum                                  → compare_summary.json + 표 출력
[추정 — 2D sim, 로봇·물체 가짜]
"""
import sys, json, glob, time, collections
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARGS = sys.argv[1:]
if ARGS[:1] != ["--sum"]:
    sys.argv = [sys.argv[0]] + ARGS                    # hunt_cases 가 배치 수·seed·mode 를 읽고 clear_sim 을 올림
    sys.path.insert(0, str(HERE))
    import hunt_cases as hc  # noqa: E402

CASES = {c["id"]: c for c in json.loads((HERE / "layout_cases.json").read_text())["cases"]}
WIDE = {"toy_wrench", "toy_hammer", "cover_plate"}
SIDE = {"side_y0", "side_y1"}
KIND = {"pick": "direct", "nudge": "nudge", "wall_nudge": "nudge", "sweep": "make_room", "remove": "make_room",
        "unstack": "remove_top"}
STRATS = ("direct", "axis_swap", "nudge", "make_room", "remove_top", "reobserve", "impossible")


def predict(f):
    """관계(hunt_cases.feats)만으로 난제 id — 없으면 None(바로 집기). 순서 = 못 함·쌓임 먼저, 그다음 벽·이웃."""
    w, near, cls = set(f["walls"]), f["near"], f["class"]
    if f["beyond_reach"]:
        return "beyond_reach"
    if f["under_cover"]:
        return "under_cover_between_legs"          # 다리 사이(direct)·가로지름(못 함) 구분은 판 손가락 띠 검사가 있어야 함
    if f["has_riders"]:
        return "stacked_under"
    if f["on_top_of"]:
        return "stacked_top"
    if "front_handle" in w:
        if len(near) + len(w) >= 3:
            return "cluster_front_wall"
        if cls == "lip_balm":
            return "cylinder_handle_wall"
        if cls in WIDE:
            return "handle_wall_wide" if f["across"] else "handle_wall_across"
    if len(w) >= 2:
        return "corner"
    if "back" in w:
        return "back_wall"
    if w & SIDE:
        return "wall_side_short"
    if near:
        return "cluster_open_side"
    return None


def strat(cid):
    return CASES[cid]["strategy"] if cid else "direct"


def run():
    t0 = time.time()
    rows = []
    for i in range(hc.N):
        L = hc.cs.layouts()
        for drawer in hc.cs.DRAWERS:
            objs0 = L[drawer]
            for o in objs0:
                objs = [dict(x, occluded_by=list(x["occluded_by"])) for x in objs0]
                f = hc.feats(objs, o["id"], drawer)
                reach = (hc.srv.prm().get("drawer_reach_x_mm") or {}).get(drawer)   # 스킬 서버와 같게 물체 가운데 x 로 (hunt 는 끝 x)
                f["beyond_reach"] = reach is not None and o["pose"]["position"][0] * 1000.0 > reach
                cid = predict(f)
                ok0, code0, _ = hc.cs.Oracle(drawer).pick(objs, o["id"])
                ok, steps, code, act, _ = hc.retrieve(objs, o["id"], drawer)
                actual = "impossible" if not ok else KIND[steps[0] if steps else "pick"]
                rows.append({"layout": i, "drawer": drawer, "target": o["class"], "case": cid, "rel": strat(cid),
                             "b_ok": bool(ok0), "b_code": code0 or "", "both": "direct" if ok0 else strat(cid),
                             "actual": actual, "fail_code": code if not ok else "", "steps": steps})
        if (i + 1) % 10 == 0:
            print(f"  [{hc.MODE} {hc.SEED}] 배치 {i + 1}/{hc.N} ({time.time() - t0:.0f} s)", flush=True)
    out = HERE / "hunt" / f"compare_{hc.MODE}_{hc.SEED}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"mode": hc.MODE, "seed": hc.SEED, "layouts": hc.N, "rows": rows, "sec": round(time.time() - t0)},
                              ensure_ascii=False))
    print(f"[{hc.MODE} {hc.SEED}] 물건 {len(rows)} · {time.time() - t0:.0f} s → {out}")


def pr(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r


def summarize():
    rows, runs = [], []
    for f in sorted(glob.glob(str(HERE / "hunt" / "compare_*.json"))):
        d = json.load(open(f))
        runs.append({"mode": d["mode"], "seed": d["seed"], "layouts": d["layouts"], "targets": len(d["rows"])})
        rows += [dict(r, mode=d["mode"]) for r in d["rows"]]
    n = len(rows)
    out = {"targets": n, "runs": runs, "by_predictor": {}, "by_case": {}}
    print(f"\n물건 {n}개 (실제 성공 {sum(r['actual'] != 'impossible' for r in rows)} · 실패 {sum(r['actual'] == 'impossible' for r in rows)})")
    for key, title in (("rel", "(가) 관계만"), ("both", "(나) 관계 + B 사전 검사")):
        conf = collections.Counter((r[key], r["actual"]) for r in rows)
        agree = sum(v for (p, a), v in conf.items() if p == a or (p == "axis_swap" and a in ("direct", "nudge")))
        tp = conf[("impossible", "impossible")]
        fp = sum(v for (p, a), v in conf.items() if p == "impossible" and a != "impossible")
        fn = sum(v for (p, a), v in conf.items() if p != "impossible" and a == "impossible")
        prec, rec = pr(tp, fp, fn)
        out["by_predictor"][key] = {"agree": agree, "agree_ratio": round(agree / max(n, 1), 4),
                                    "impossible": {"tp": tp, "fp": fp, "fn": fn, "precision": round(prec, 4), "recall": round(rec, 4)},
                                    "confusion": {f"{p}->{a}": v for (p, a), v in sorted(conf.items())}}
        print(f"\n{title}: 전략 일치 {agree}/{n} ({agree / max(n, 1) * 100:.1f}%) · '못 함' 예측 정밀도 {prec * 100:.1f}% · 재현율 {rec * 100:.1f}%")
        acts = ("direct", "nudge", "make_room", "remove_top", "impossible")
        print("| 예측 \\ 실제 | " + " | ".join(acts) + " |")
        print("| :--- |" + " ---: |" * len(acts))
        for p in STRATS:
            if any(conf[(p, a)] for a in acts):
                print(f"| {p} | " + " | ".join(str(conf[(p, a)]) for a in acts) + " |")
    cases = collections.defaultdict(collections.Counter)
    for r in rows:
        cases[r["case"] or "(없음)"][r["actual"]] += 1
    print("\n난제별 (관계만 예측) → 실제")
    print("| 난제 | 예측 전략 | 수 | direct | nudge | make_room | remove_top | 실패 |")
    print("| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for cid, c in sorted(cases.items(), key=lambda kv: -sum(kv[1].values())):
        s = strat(None if cid == "(없음)" else cid)
        out["by_case"][cid] = {"strategy": s, **dict(c)}
        print(f"| {cid} | {s} | {sum(c.values())} | " + " | ".join(str(c[a]) for a in ("direct", "nudge", "make_room", "remove_top", "impossible")) + " |")
    (HERE / "compare_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    summarize() if ARGS[:1] == ["--sum"] else run()
