"""B unpack 궤적(sim/motion_check/trace_unpack.py 결과)을 트윈에서 재생한다 — 로봇 + 서랍 + 서랍 안 물체 여러 개 (담당 A, 트윈 사전 검증).

  ISAAC_SIM_CMD=$HOME/isaac-sim-5.1.0/python.sh bash sim/run_isaac.sh sim/scripts/play_unpack_trace.py --trace /tmp/unpack.json
옵션: --speed 배속 / --flag-slow 2 (◀ 구간 느리게) / --loop / --headless --quit (시험용) / --allow-mismatch (play_motion_trace 와 같음)
- 물체는 sim/assets/objects/<class>.usda 외형(build_object_meshes.py), 없으면 온톨로지 외접 박스(색은 클래스별). 첫 장면 = 덤프를 다시 계산한 인식 결과, 그 뒤는 trace 의 scene_events.
- 집기에서 그리퍼가 닫히는 순간 그 물체를 손끝에 붙이고, 놓기에서 벌리는 순간 뗀다(물리 아님 — 위치만 따라감).
- 서랍 안에 있는 물체는 서랍 인출을 따라간다. 트레이에 놓은 물체는 놓은 자리에 남는다.
- 로봇 관절·서랍·그리퍼 그리기는 play_motion_trace.py 와 같은 방식(텔레포트 + 구동 목표, 씬·궤적 설정 대조).
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from isaacsim import SimulationApp

ROOT = Path(__file__).resolve().parents[2]
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--trace", required=True)
ap.add_argument("--scene", default=str(ROOT / "sim/scenes/ready2go_t1.usd"))
ap.add_argument("--speed", type=float, default=1.0)
ap.add_argument("--flag-slow", type=float, default=1.0)
ap.add_argument("--loop", action="store_true")
ap.add_argument("--headless", action="store_true")
ap.add_argument("--quit", action="store_true")
ap.add_argument("--allow-mismatch", action="store_true")
args = ap.parse_args()
app = SimulationApp({"headless": args.headless})

import omni.usd  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import SingleArticulation  # noqa: E402
from isaacsim.core.utils.types import ArticulationAction  # noqa: E402
from pxr import Gf, UsdGeom, UsdPhysics  # noqa: E402

sys.path.insert(0, str(ROOT / "sim/motion_check"))
sys.path.insert(0, str(ROOT / "sim/scripts"))
import m0609_kin as kin  # noqa: E402
import scene_record  # noqa: E402

TRACE = json.loads(Path(args.trace).read_text(encoding="utf-8"))
ITEMS = json.loads((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))["world"]["items"]
JOINT_VEL, PHYS_DT = 20.0, 1.0 / 60.0
_DEG = [0, 5, 10, 20, 30, 40, 50, 60, 67.6]                             # RG2 폭 ↔ finger_joint: 트윈 손가락 충돌 형상 사이 틈 [실측 트윈 10/13]
_W = [99.1, 95.4, 91.0, 80.0, 66.4, 50.6, 33.2, 14.7, 0.2]
COLORS = {"eraser": (0.95, 0.85, 0.2), "lip_balm": (0.1, 0.1, 0.1), "caramel_box": (0.85, 0.55, 0.2), "car_key": (0.3, 0.3, 0.35),
          "cover_plate": (0.75, 0.75, 0.8), "toy_wrench": (0.1, 0.6, 0.6), "toy_hammer": (0.8, 0.2, 0.2)}


def finger_deg(width_mm):
    return float(np.interp(width_mm, _W[::-1], _DEG[::-1]))


def quat_to_R(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def gf_to_np(m):
    return np.array([[m[r][c] for c in range(4)] for r in range(4)]).T


def np_to_gf(T):
    return Gf.Matrix4d(*[float(T[c][r]) for r in range(4) for c in range(4)])


def duration(s):
    if s["kind"] in ("movej", "movesj"):
        q = np.array(s["joints"])
        t = float(np.abs(np.diff(q, axis=0)).max(axis=1).sum()) / float(s.get("vel") or JOINT_VEL)
    else:
        t = max(s.get("dist_mm", 0) / max(s.get("vel", 50), 1e-6), s.get("rot_deg", 0) / max(s.get("rot_vel", 30), 1e-6))
    return max(t, 0.2) / args.speed * (args.flag_slow if s.get("flag") else 1.0)


omni.usd.get_context().open_stage(args.scene)
for _ in range(10):
    app.update()
stage = omni.usd.get_context().get_stage()
roots = [str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
robot_root = next(r for r in roots if r.startswith("/World/m0609"))
cab_root = next((r for r in roots if r.startswith("/World/workspace")), None)

cfg = TRACE.get("config")
chk = scene_record.compare(scene_record.loads(stage.GetRootLayer().customLayerData.get(scene_record.RECORD_KEY)), cfg)
if chk["status"] != "ok":
    print(f"[unpack] 씬·궤적 대조 실패 ({chk['status']}):\n  " + "\n  ".join(chk["diffs"]), flush=True)
    if not args.allow_mismatch:
        print("[unpack] 거부 — build_scene.py 로 씬을 다시 만들거나 --allow-mismatch", flush=True)
        app.close()
        sys.exit(2)
    print("[unpack] **우회(--allow-mismatch)** — 이 재생으로 정합성을 판단하지 말 것", flush=True)
places = cfg["places"]
EVENTS = TRACE["scene_events"]
DKEY = EVENTS[0]["objects"][0]["pose"]["frame"]
tf = places[DKEY]["tf"]
T_bd = np.eye(4)
T_bd[:3, :3], T_bd[:3, 3] = quat_to_R(tf["quaternion_xyzw"]), tf["translation_m"]
max_travel = float(places[DKEY]["max_travel_m"])
base_prim = stage.GetPrimAtPath("/World/m0609/base_link")
W = gf_to_np(UsdGeom.Xformable(base_prim if base_prim.IsValid() else stage.GetPrimAtPath("/World/m0609")).ComputeLocalToWorldTransform(0))

ops = {}


MESH_DIR = ROOT / "sim/assets/objects"                                   # build_object_meshes.py 결과 — 있으면 상자 대신 외형


def cube_for(oid, cls):
    if oid not in ops:
        path = f"/World/unpack_objs/{oid.replace('#', '_')}"
        usd = MESH_DIR / f"{cls}.usda"
        if usd.exists():                                                  # 외형 메시: 원점 = 바닥 가운데, x 긴 변 (온톨로지 size_m 과 같음)
            prim = stage.DefinePrim(path, "Xform")
            prim.GetReferences().AddReference(str(usd))
            S = np.eye(4)
        else:                                                             # 없으면 외접 상자 (가운데 원점 → 바닥으로 h/2 올림)
            c = UsdGeom.Cube.Define(stage, path)
            c.CreateSizeAttr(1.0)
            c.GetDisplayColorAttr().Set([Gf.Vec3f(*COLORS.get(cls, (0.5, 0.5, 0.9)))])
            prim = c.GetPrim()
            sz = ITEMS[cls]["size_m"]
            S = np.diag(list(sz) + [1.0])
            S[2, 3] = sz[2] / 2
        xf = UsdGeom.Xformable(prim)
        xf.ClearXformOpOrder()
        ops[oid] = (xf.AddTransformOp(), S)
    return ops[oid]


def obj_world(o, travel):
    """물체 o(서랍 좌표 pose·top_z) → 월드 변환(물체 바닥 가운데). 바닥 높이 = top_z − 온톨로지 높이(받침 위면 그 높이)."""
    x, y = o["pose"]["position"][:2]
    h = ITEMS[o["class"]]["size_m"][2]
    T = np.eye(4)
    T[:3, :3] = T_bd[:3, :3] @ kin._rz(o["pose"]["yaw"])
    T[:3, 3] = (T_bd @ np.array([x, y, max(o["top_z"] - h, 0.0), 1.0]))[:3] + T_bd[:3, 0] * (max_travel - travel)
    return W @ T


def set_obj(oid, cls, T):
    op, S = cube_for(oid, cls)
    op.Set(np_to_gf(T @ S))


world = World(stage_units_in_meters=1.0, physics_dt=PHYS_DT, rendering_dt=PHYS_DT)
world.reset()
robot = SingleArticulation(prim_path=robot_root, name="m0609")
robot.initialize()
dofs = list(robot.dof_names)
arm_idx = np.array([dofs.index(f"joint_{i}") for i in range(1, 7)])
fi = dofs.index("finger_joint")
cab, d_idx = None, None
if cab_root:
    cab = SingleArticulation(prim_path=cab_root, name="cabinet")
    cab.initialize()
    d_idx = next((i for i, n in enumerate(cab.dof_names) if n == f"{DKEY}_joint"), None)
_jp = stage.GetPrimAtPath(f"/World/workspace/cabinet/{DKEY}_joint")
for _a, _v in (("drive:linear:physics:stiffness", 1e7), ("drive:linear:physics:damping", 1e5), ("drive:linear:physics:maxForce", 1e7)):
    _jp.GetAttribute(_a).Set(_v)
drawer_attr = _jp.GetAttribute("drive:linear:physics:targetPosition")
marker = UsdGeom.Sphere.Define(stage, "/World/singularity_marker")
marker.CreateRadiusAttr(0.03)
marker.GetDisplayColorAttr().Set([Gf.Vec3f(1.0, 0.1, 0.1)])
m_xf = UsdGeom.Xformable(marker.GetPrim())
m_xf.ClearXformOpOrder()
m_op = m_xf.AddTranslateOp()
_clock = [None]


def pace():
    now = time.monotonic()
    if _clock[0] is not None and not args.headless and now < _clock[0] + PHYS_DT:
        time.sleep(_clock[0] + PHYS_DT - now)
        now = _clock[0] + PHYS_DT
    _clock[0] = now


def apply(q_arm, f_deg, travel):
    pos = np.radians(np.append(q_arm, f_deg))
    idx = np.append(arm_idx, fi)
    robot.set_joint_positions(pos, joint_indices=idx)
    robot.set_joint_velocities(np.zeros(len(idx)), joint_indices=idx)
    robot.apply_action(ArticulationAction(joint_positions=pos, joint_indices=idx))
    if d_idx is not None:
        cab.set_joint_positions(np.array([travel]), joint_indices=np.array([d_idx]))
        cab.set_joint_velocities(np.zeros(1), joint_indices=np.array([d_idx]))
        cab.apply_action(ArticulationAction(joint_positions=np.array([travel]), joint_indices=np.array([d_idx])))
    else:
        drawer_attr.Set(float(travel))
    world.step(render=not args.headless)
    pace()


# 동작별 구간 범위 → 집기에서 닫는 순간 / 놓기에서 벌리는 순간
grips = {}
for g in TRACE.get("grip_events", []):
    grips.setdefault(g["before_segment"], []).append(g["width_mm"])
acts = [r for r in TRACE["results"] if r.get("success") and r["action"] in ("pick_object", "place_object")]
ev_after, rescans = {}, {}                                                # 놓기 뒤 장면(그 동작이 끝난 구간 번호) / 실물 덤프로 다시 인식한 장면
for e in EVENTS[1:]:
    (rescans if e["why"].startswith("인식") else ev_after)[e["before_segment"]] = e


def act_at(seg_i):
    return next((r for r in acts if r["first_segment"] <= seg_i <= r["first_segment"] + r["segments"]), None)


PUSH, _run = {}, []
for _s in TRACE["segments"] + [{"stage": ""}]:
    if _s["stage"] in ("push", "push_slow"):
        _run.append(_s)
        continue
    _tot, _before = sum(x.get("dist_mm", 0) for x in _run) / 1000.0, 0.0
    for x in _run:
        PUSH[x["i"]] = (_before, _tot)
        _before += x.get("dist_mm", 0) / 1000.0
    _run = []
print(f"[unpack] {DKEY}, 구간 {len(TRACE['segments'])}개, 물체 {len(EVENTS[0]['objects'])}개, 장면 기록 {len(EVENTS)}개, "
      f"B 코드 {TRACE.get('repo_sha')}, 덤프 {Path((TRACE.get('dump') or [''])[0] if isinstance(TRACE.get('dump'), list) else TRACE.get('dump', '')).name}", flush=True)
for r in TRACE["results"]:
    print(f"[unpack]   {r['step']:8s} {r['action']:18s} {'OK ' if r['success'] else 'NG '} {r.get('error') or ''} {r.get('target') or ''} "
          f"{r.get('slot') or ''} 구간 {r['first_segment']}~{r['first_segment'] + r['segments'] - 1}", flush=True)
if TRACE.get("stopped"):
    print(f"[unpack] b_sk 중단: {TRACE['stopped']}", flush=True)

while app.is_running():
    objs = {o["id"]: dict(o) for o in EVENTS[0]["objects"]}
    loose = {}                                                            # 서랍 밖(트레이)에 놓인 물체: 월드 변환 고정
    travel, width, held, rel = 0.0, 110.0, None, None
    for oid, o in objs.items():
        set_obj(oid, o["class"], obj_world(o, travel))
    for _ in range(30):
        apply(TRACE["segments"][0]["joints"][0], finger_deg(width), travel)
    for s in TRACE["segments"]:
        e = rescans.get(s["i"])
        if e is not None:                                                  # 다시 찍은 실물 인식으로 서랍 안 물체를 바꿈 (쥔 것은 그대로)
            for oid in [k for k in objs if k != held]:
                objs.pop(oid)
                ops[oid][0].Set(np_to_gf(np.diag([1e-6, 1e-6, 1e-6, 1.0])))
            for o in e["objects"]:
                if o["id"] != held:
                    objs[o["id"]] = dict(o)
                    set_obj(o["id"], o["class"], obj_world(o, travel))
            print(f"[unpack]     {e['why']} — 물체 {[o['id'] for o in e['objects']]}", flush=True)
        a = act_at(s["i"])
        for w_new in grips.get(s["i"], []):
            for k in range(1, 31):
                apply(s["joints"][0], finger_deg(width + (w_new - width) * k / 30), travel)
            closing, width = w_new < width, w_new
            if a and a["action"] == "pick_object" and closing and held is None and w_new > 3.0 and a.get("target") in objs:
                held = a["target"]
                rel = np.linalg.inv(W @ kin.fk(s["joints"][0])) @ obj_world(objs[held], travel)
                print(f"[unpack]     잡음 {held}", flush=True)
            elif a and a["action"] == "place_object" and not closing and held is not None:
                T_rel = W @ kin.fk(s["joints"][0]) @ rel
                after = ev_after.get(a["first_segment"] + a["segments"])
                placed = next((o for o in (after or {}).get("objects", []) if o["id"] == held), None)
                if placed is not None:
                    objs[held] = dict(placed)
                    set_obj(held, placed["class"], obj_world(placed, travel))
                else:
                    loose[held] = T_rel
                    objs.pop(held, None)
                print(f"[unpack]     놓음 {held} → {'서랍 ' + str([round(v * 1000) for v in placed['pose']['position'][:2]]) + ' mm' if placed else '트레이'}", flush=True)
                held, rel = None, None
        flag = s.get("flag")
        print(f"[unpack] #{s['i']:3d} {s['step']:8s} {s['kind']} {s['stage']:22s}{'  ◀ 특이점 근처' if flag else ''}", flush=True)
        vis = UsdGeom.Imageable(marker.GetPrim())
        vis.MakeVisible() if flag else vis.MakeInvisible()
        q_all = np.array(s["joints"])
        n = max(1, int(duration(s) / PHYS_DT))
        for k in range(n + 1):
            f = k / n
            qf = f * (len(q_all) - 1)
            i0 = int(math.floor(qf))
            i1 = min(i0 + 1, len(q_all) - 1)
            q = q_all[i0] + (q_all[i1] - q_all[i0]) * (qf - i0)
            T_tcp = W @ kin.fk(q)
            m_op.Set(Gf.Vec3d(*[float(v) for v in T_tcp[:3, 3]]))
            if s["stage"] == "pull":
                travel = min(max_travel, f * s.get("dist_mm", 0) / 1000.0)
            elif s["stage"] in ("push", "push_slow"):
                before, tot = PUSH[s["i"]]
                pushed = before + f * s.get("dist_mm", 0) / 1000.0
                travel = min(max_travel, max(0.0, max_travel - max(0.0, pushed - (tot - max_travel))))
            if s["step"] in ("open", "close"):
                for oid, o in objs.items():
                    if oid != held:
                        set_obj(oid, o["class"], obj_world(o, travel))
            if held is not None:
                set_obj(held, objs[held]["class"], T_tcp @ rel)
            apply(q, finger_deg(width), travel)
            if not app.is_running():
                break
        UsdGeom.Imageable(marker.GetPrim()).MakeInvisible()
    print("[unpack] 끝" + (" — 처음부터 반복" if args.loop else " (창을 닫으면 종료)"), flush=True)
    if args.quit:
        break
    if not args.loop:
        while app.is_running():
            world.step(render=not args.headless)
        break
app.close()
