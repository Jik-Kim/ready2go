"""부딪힘 검사 [추정] — 시나리오 궤적 전체(IK 경로 점)를 서랍 좌표로 바꿔 다음을 셈:
  ① 손가락(수직 자세만) ↔ 서랍 벽: 손끝이 테두리 아래일 때 TCP–벽 거리 ≥ wall_clearance(벌림·닫힘 각, 실측 표) − 1 mm
  ② 손가락 ↔ 다른 물체: 손가락 사각형(닫힘 축 ±(벌림/2 … +12.5), 폭 ±tip_radius)이 물체 footprint(1 mm 줄임)와 겹치고 손끝이 윗면 −1 mm 아래
     (넛지 대상은 누르는 게 목적이라 뺌, 집는 대상은 닫기 전까지만)
  ③ 쥔 물체 ↔ 벽: 쥔 물체 바닥이 테두리 아래면 footprint 가 서랍 안
  ④ 쥔 물체 ↔ 다른 물체: footprint 겹치고 바닥이 윗면 −1 mm 아래
  ⑤ 아래 칸 깊이: TCP x 가 실측 닿음 한계(바닥 TCP 10 mm 에서 149, 테두리 TCP 72.7 mm 에서 176 [실측 10/10], 사이 직선) 넘음 — 위 서랍장
손가락 두께 12.5 mm(fingertip_outer 13 − 닫힘 반 0.45), 기울인 자세(넛지·기울여 잡기)는 교시 자세라 ①② 손가락 검사에서 뺌.
그리퍼 몸통·손목 카메라 ↔ 위 서랍장은 형상 실측이 없어 ⑤로만 봄.
  python3 practice/B/sim/collide_sim.py [무작위 배치 수=6]"""
import sys, math, io, contextlib, collections, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_sim
import p2_demo as d
import p2_random as pr
kin = demo_sim.kin
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ros2_ws/src/ready2go_skills"))
from ready2go_skills.core import motion_plan as mp, place_plan as plp, pick_plan as pp
import yaml
REPO = Path(__file__).resolve().parents[3]
PRM = yaml.safe_load((REPO / "ros2_ws/src/ready2go_skills/params/skills.yaml").read_text(encoding="utf-8"))
G = PRM["gripper"]
FT = G["fingertip_outer_mm"] - 0.45
SIZES = None


def size_of(cls):
    global SIZES
    if SIZES is None:
        import rand_sim2
        SIZES = rand_sim2.SIZES
    return SIZES.get(cls)


def _local(px, py, cx, cy, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return (px - cx) * c + (py - cy) * s, -(px - cx) * s + (py - cy) * c


def rect(cx, cy, ang, hx, hy):
    return plp.corners(cx, cy, ang, hx, hy)


def overlap(a, b):
    return plp.rects_overlap(a, b)


def check(robot, drawer, tag):
    place = d.PL[drawer]
    tf, I = place["tf"], [v * 1000 for v in place["interior_m"]]
    rim = I[2]
    q_tf = tf["quaternion_xyzw"]
    inv = (-q_tf[0], -q_tf[1], -q_tf[2], q_tf[3])
    hits = collections.Counter()
    first = {}
    holding = None                                       # (obj, long_side, tcp_above_floor_mm) — 닫힌 뒤부터
    deep_max = (-1e9, None)
    cur_lab, released = None, set()
    for seg in robot.segments:
        lab, w = seg.get("step_label", "").replace("복구: ", "").lstrip("!"), seg.get("grip_w")
        held = seg.get("held")
        scene = list(seg.get("scene") or ())
        if lab != cur_lab:
            cur_lab, released, descended = lab, set(), False
        descended = descended or str(seg.get("stage", "")).startswith("descend")
        if not held and holding and lab.startswith("place"):
            released.add(holding[0])                        # 방금 놓은 물체 — 장면의 옛 자리(집기 전 촬영)는 이제 아님
        if held:
            holding = (held["id"], bool(held.get("long_side")), held["tcp_above_floor_m"] * 1000, held["class"])
        elif lab.startswith("pick") and holding is None and w is not None and w > 2.0 and scene:
            tgt = scene[0]                                      # 닫음 → 집는 대상(입력 target)을 쥠
            sz = size_of(tgt["class"])
            if sz and descended and str(seg.get("stage", "")).startswith("lift"):   # 내려가 닫은 뒤 들어 올림부터
                c0 = [v * 1000 for v in mp.from_base(tf, [x / 1000 for x in seg["start_posx"][:3]])]
                holding = (tgt["id"], abs(w - sz[0] * 1000) < abs(w - sz[1] * 1000), c0[2] - (tgt["top_z"] - sz[2]) * 1000, tgt["class"])
        elif holding and not lab.startswith("pick"):
            holding = None
        if not (lab.startswith("pick") or lab.startswith("place")):
            continue                                        # 서랍 열기·닫기 중은 서랍 좌표가 움직임 → 검사 안 함
        idx = range(0, len(seg["joints"]), max(1, len(seg["joints"]) // 40))
        for k in list(idx) + [len(seg["joints"]) - 1]:
            q = seg["joints"][k]
            p = kin.fk_posx(q)
            T = kin.posx_to_T(p)
            c = [v * 1000 for v in mp.from_base(tf, [p[0] / 1000, p[1] / 1000, p[2] / 1000])]
            if not (-80 < c[0] < I[0] + 80 and -80 < c[1] < I[1] + 80 and c[2] < rim + 80):
                continue
            tx = pp.rotate(inv, list(T[:3, 0]))              # 툴 x(닫힘 축) → 서랍 좌표
            tz = pp.rotate(inv, list(T[:3, 2]))
            tilt = math.degrees(math.acos(max(-1.0, min(1.0, -tz[2]))))
            ang = math.atan2(tx[1], tx[0])
            where = f"{lab}/{seg['stage']}"
            # ⑤ 아래 칸 깊이
            if drawer == "drawer_bottom" and c[2] < rim + 30:
                lim = 149 + 27 * (min(max(c[2], 10), 72.7) - 10) / 62.7
                if c[0] - lim > deep_max[0]:
                    deep_max = (c[0] - lim, where, round(c[0], 1), round(c[2], 1))
            # 쥔 물체
            hid = None
            if holding:
                hid, long_, above, cls = holding
                sz = size_of(cls)
                if sz:
                    bottom = c[2] - above
                    la = ang if long_ else ang + math.pi / 2
                    hr = rect(c[0], c[1], la, sz[0] * 500, sz[1] * 500)
                    if bottom < rim - 0.5:
                        out_ = max(max(-x, x - I[0], 0) for x, _ in hr), max(max(-y, y - I[1], 0) for _, y in hr)
                        if max(out_) > 0.5:
                            hits["③ 쥔 물체-벽"] += 1; first.setdefault("③ 쥔 물체-벽", (where, round(max(out_), 1), round(bottom, 1)))
                    for o in scene:
                        if o["id"] in (hid,) or not size_of(o["class"]):
                            continue
                        osz = size_of(o["class"])
                        orr = rect(o["pose"]["position"][0] * 1000, o["pose"]["position"][1] * 1000, o["pose"]["yaw"], osz[0] * 500 - 1, osz[1] * 500 - 1)
                        inside = all(abs(a_) <= sz[0] * 500 + 0.5 and abs(b_) <= sz[1] * 500 + 0.5 for a_, b_ in
                                     (_local(px, py, c[0], c[1], la) for px, py in orr))
                        if inside and o["top_z"] * 1000 < bottom + sz[2] * 1000:
                            continue                                # 덮개(가림막) 밑에 있던 물체 — 덮개 안 (neighbor_check._under 와 같음)
                        if overlap(hr, orr) and bottom < o["top_z"] * 1000 - 1:
                            key = "④ 쥔 물체-물체"
                            hits[key] += 1; first.setdefault(key, (where, o["id"], round(bottom, 1), round(o["top_z"] * 1000, 1)))
            # 손가락 (수직만)
            if tilt > 3 or w is None:
                continue
            tip = c[2] - mp.tip_below_tcp_mm(w, G)
            if tip < rim:
                ext_x = mp.wall_extent_mm(w, ang, G)
                ext_y = mp.wall_extent_mm(w, ang - math.pi / 2, G)
                dx, dy = min(c[0], I[0] - c[0]) - ext_x, min(c[1], I[1] - c[1]) - ext_y
                if min(dx, dy) < -1.0:
                    hits["① 손가락-벽"] += 1; first.setdefault("① 손가락-벽", (where, round(min(dx, dy), 1), round(tip, 1), round(w, 1)))
            fr = []
            for sgn in (-1, 1):
                off = sgn * (w / 2 + FT / 2)
                fr.append(rect(c[0] + off * math.cos(ang), c[1] + off * math.sin(ang), ang, FT / 2, G["tip_radius_mm"]))
            for o in scene:
                if o["id"] == hid or o["id"] in seg.get("skip", ()) or not size_of(o["class"]):
                    continue
                if (held and o["id"] == held["id"]) or o["id"] in released:
                    continue
                osz = size_of(o["class"])
                orr = rect(o["pose"]["position"][0] * 1000, o["pose"]["position"][1] * 1000, o["pose"]["yaw"], osz[0] * 500 - 1, osz[1] * 500 - 1)
                if tip < o["top_z"] * 1000 - 1 and any(overlap(f, orr) for f in fr):
                    hits["② 손가락-물체"] += 1; first.setdefault("② 손가락-물체", (where, o["id"], round(tip, 1), round(o["top_z"] * 1000, 1), round(w, 1)))
    return hits, first, deep_max


def run(tag, fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        ok, robot, srv = fn(*a, **k)
    drawer = a[0]
    hits, first, deep = check(robot, drawer, tag)
    fail = "" if ok else " [시나리오 실패: " + next((l.strip() for l in buf.getvalue().splitlines() if "FAIL" in l), "") + "]"
    print(f"{tag:34s} {drawer[7:]:6s} {'부딪힘 없음' if not hits else dict(hits)}{fail}")
    for kk, v in first.items():
        print(f"      첫 {kk}: {v}")
    if drawer == "drawer_bottom" and deep[1]:
        print(f"      ⑤ 깊이 여유 {-deep[0]:.1f} mm (가장 깊은 곳 {deep[1]} x {deep[2]} z {deep[3]})")
    return hits


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    demo_sim.PRM_PATCH.update({"place": {"allow_stack_place": True}})
    for dr in ("drawer_top", "drawer_bottom"):
        run("가림막 (지우개 먼저)", d.cover_scenario, dr)
        run("가림막 (립밤 먼저)", d.cover_scenario, dr, lip_first=True)
        run("쌓기 → 몽키", d.stack_scenario, dr)
        run("쌓기 → 몽키 → 복구(위에 놓기 켬)", d.stack_restore_scenario, dr)
    pr.GUIDE = True
    pr.rnd = random.Random(11)
    for dr in ("drawer_top", "drawer_bottom"):
        I = d.PL[dr]["interior_m"]
        for i in range(n):
            cp, er, lb = pr.cover_layout(I)
            run(f"무작위 가림막 {i + 1}", d.cover_scenario, dr, cp=cp, er=er, lb=lb, lip_first=bool(i % 2))
            at, yw, yc, yk = pr.stack_layout(I)
            run(f"무작위 쌓기 {i + 1}", d.stack_scenario, dr, at=at, yaw_w=yw, yaw_c=yc, yaw_k=yk)
