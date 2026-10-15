"""아래 칸 지우개·립밤 붙여 무작위 배치 → 지우개 꺼내기 공간 만들기(make_room) — 벽 여유·가운데 우선 전/후 비교 [사용자 10/15 PC2 통합
"판 치운 뒤 지우개를 벽 쪽으로 붙여 밀어 로봇이 벽에 부딪힘", "지우개·립밤 붙여서 랜덤 배치해서 아래 칸에서 테스트"].
  A: 판 없이 지우개·립밤을 맞붙여(틈 0~4 mm) 아무 자리·각도에
  B: S2 처럼 덮개 판이 둘을 덮음 → 판을 빈 자리(place_object slot free check_only 예정 자리)로 치운 뒤 지우개
판단은 스킬 서버 실제 코드(DryOracle·clear_plan.plan_next, skills.yaml make_room) 그대로, 로봇·비전은 가짜 — 판단만 [추정, 2D sim].
각 make_room 넛지·밀기에서 끝난 자리의 '지우개 벽 거리'와 '누르는 손가락(반지름 press_finger_r_mm) 벽 거리'를 잼:
  손가락 닿음 = 누르는 점 벽 거리 < press_finger_r_mm (손가락 원이 벽을 넘음) — 10/15 PC2 충돌과 같은 경우
  벽에 붙임   = 옮긴 지우개가 벽에서 2 mm 안
실행 (저장소 루트):  NSIM=300 SEED=1 python3 -m pytest -q -s -p no:cacheprovider practice/B/sim/wall_keep_sim.py"""
import collections, json, math, os, random, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "ros2_ws", "src", "ready2go_skills", "test"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_skill_server_node import server, _with_prm  # noqa
from ready2go_skills.core import clear_plan as clp
import p2_unpack_sim as pus

NSIM, SEED = int(os.environ.get("NSIM", "300")), int(os.environ.get("SEED", "1"))
D = "drawer_bottom"
CONFIGS = (("예전 (벽 여유 0·가운데 우선 없음)", {"wall_keep_mm": 0.0, "center_weight": 0.0}),
           ("지금 (벽 여유 10 mm·가운데 우선 1)", {}))


def scene_pair(rng, size_of, interior, reach_x):
    """지우개·립밤 맞붙여(틈 0~4 mm) — 지우개 아무 각도, 립밤은 지우개 옆(긴 변 또는 짧은 변 쪽)."""
    for _ in range(4000):
        ey = rng.uniform(0, math.pi)
        e = pus.obj("eraser#1", "eraser", rng.uniform(0.03, reach_x), rng.uniform(0.03, interior[1] - 0.03), 0.0133, ey, D)
        if not pus.inside(e, size_of, interior, 0.002):
            continue
        se, sl = size_of("eraser"), size_of("lip_balm")
        side = rng.choice((0, 1, 2, 3))                       # 지우개 기준 +짧은변·−짧은변·+긴변·−긴변 쪽
        gap = rng.uniform(0.0, 0.004)
        ly = ey + rng.choice((0.0, math.pi / 2)) + rng.uniform(-0.3, 0.3)
        reach = (se[1] / 2 + sl[1] / 2 + gap) if side < 2 else (se[0] / 2 + sl[0] / 2 + gap)
        ang = ey + (math.pi / 2 if side < 2 else 0.0) + (math.pi if side % 2 else 0.0)
        slide = rng.uniform(-0.015, 0.015)
        lx = e["pose"]["position"][0] + reach * math.cos(ang) - slide * math.sin(ang)
        lyy = e["pose"]["position"][1] + reach * math.sin(ang) + slide * math.cos(ang)
        lb = pus.obj("lip_balm#1", "lip_balm", lx, lyy, 0.0204, ly, D)
        if pus.inside(lb, size_of, interior, 0.002) and not pus.overlaps(e, lb, size_of, -0.0005):
            return [e, lb]
    raise RuntimeError("배치 실패")


def remove_plate(server, objs):
    """S2: 판을 free 예정 자리로 (치우기 s7) — 실패면 None."""
    plate = next(o for o in objs if o["class"] == "cover_plate")
    out, data = server.run("place_object", {"location": D, "slot": "free", "scan": pus.scan_of(objs, "eraser#1"), "object": plate,
                                            "check_only": True})
    if not out.success:
        return None
    moved = dict(plate, pose=dict(data["planned_pose"], yaw_valid=True), occluded_by=[])
    return [moved if o["id"] == plate["id"] else dict(o, occluded_by=[x for x in o["occluded_by"] if x != plate["id"]]) for o in objs]


def press_after(objs, a, cfg):
    t = next(o for o in objs if o["id"] == a.target)
    px, py = (a.extra or {}).get("press_xy_m") or t["pose"]["position"][:2]
    return px + a.dir[0] * a.dist_m, py + a.dir[1] * a.dist_m          # 가장 멀리 간 점 (sweep 은 되돌아오기 전)


def run_pick(server, objs, cfg, orc, stat):
    """공통 pick + make_room 반복(최대 6) — 넛지·밀기마다 벽 거리 기록. → 결과 문자열."""
    tid = "eraser#1"
    ok, code, why = orc.pick(objs, tid)
    if ok:
        return "바로 집힘"
    if code == "WALL_TOO_CLOSE":
        return "벽 넛지 (make_room 아님)"
    for _ in range(6):
        a = clp.plan_next(objs, tid, orc, cfg)
        if a.kind == "pick":
            return "공간 만들기 뒤 집힘"
        if a.kind == "fail":
            return f"공간 만들기 실패 {a.code}"
        if a.kind in ("nudge", "sweep"):
            g0 = clp.wall_gap_mm(next(o for o in objs if o["id"] == a.target), cfg.size_of, cfg.interior_m)
            px, py = press_after(objs, a, cfg)
            pg = clp._point_gap_mm(px, py, cfg.interior_m)
            after = clp.apply(objs, a, cfg)
            g1 = clp.wall_gap_mm(next(o for o in after if o["id"] == a.target), cfg.size_of, cfg.interior_m)
            stat["moves"] += 1
            stat["toward_wall"] += g1 < g0 - 0.5
            stat["finger_hits_wall"] += pg < cfg.press_finger_r_mm
            stat["flush"] += g1 < 2.0
            stat["min_press_gap"] = min(stat["min_press_gap"], pg)
            objs = after
        else:
            objs = clp.apply(objs, a, cfg)
    return "6번 넘게 반복"


def _run(server, monkeypatch, label, plate):
    srv = server.srv
    srv.disp[D] = srv.places()[D]["tf_at_travel_m"]
    interior, size_of = srv.places()[D]["interior_m"], srv._size_cached()
    reach_x = ((srv.prm().get("drawer_reach_x_mm") or {}).get(D) or 129.0) / 1000.0
    print(f"\n##### {label} — {NSIM} 배치, seed {SEED} [sim 추정]")
    for name, over in CONFIGS:
        with pytest.MonkeyPatch.context() as mp:
            if over:
                _with_prm(server, mp, make_room=over)
            cfg = srv._room_cfg(D)
        cfg = cfg if not over else cfg
        orc = server.ss.DryOracle(srv, D)
        rng = random.Random(SEED)
        res, stat = collections.Counter(), collections.Counter(min_press_gap=1e9)
        for _ in range(NSIM):
            if plate:
                objs = remove_plate(server, pus.scene_s2(rng, size_of, interior, reach_x, srv.prm()["pick"]["under_gap_by_class_mm"]["cover_plate"]))
                if objs is None:
                    res["판 치울 자리 없음"] += 1
                    continue
            else:
                objs = scene_pair(rng, size_of, interior, reach_x)
            res[run_pick(server, json.loads(json.dumps(objs)), cfg, orc, stat)] += 1
        n = stat["moves"]
        print(f"--- {name}  (wall_keep_mm {cfg.wall_keep_mm:g}, center_weight {cfg.center_weight:g})")
        for k, v in res.most_common():
            print(f"   {v:4d}  {k}")
        print(f"   넛지·밀기 {n}번: 벽 쪽으로 {stat['toward_wall']} · 손가락이 벽에 닿음 {stat['finger_hits_wall']} · "
              f"지우개 벽에 붙임 {stat['flush']} · 누르는 점 벽 거리 최소 {stat['min_press_gap'] if n else float('nan'):.1f} mm")


def test_pair_no_plate(server, monkeypatch):
    _run(server, monkeypatch, "A. 아래 칸 지우개·립밤 맞붙임 (판 없음) → 지우개", plate=False)


def test_s2_after_plate(server, monkeypatch):
    _run(server, monkeypatch, "B. S2 판이 지우개·립밤 덮음 → 판 치운 뒤 지우개", plate=True)
