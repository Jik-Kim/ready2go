"""B unpack 궤적을 **물리**로 재생한다 — 서랍 안 물체가 강체(중력·마찰·충돌), 로봇 손끝이 밀면 밀리고 굴러감 (담당 A, 트윈 사전 검증).

  ISAAC_SIM_CMD=$HOME/isaac-sim-5.1.0/python.sh bash sim/run_isaac.sh sim/scripts/play_unpack_physics.py --trace /tmp/unpack.json [--report r.json]
옵션: --speed / --headless --quit / --allow-mismatch (play_unpack_trace.py 와 같음)

- 로봇: 궤적 관절을 매 스텝 그대로 설정(텔레포트). 손가락 충돌 형상이 물체를 민다(접촉 힘은 실물과 다름 — 밀림 여부·방향만 봄).
- 넛지: 누르기는 손끝이 트윈 물체 윗면에 닿게 높이 보정(실물은 힘이 잡힐 때까지 내려감), 끌기 동안 그 물체는 손끝을 따라
  궤적대로 끌린다고 가정(미끄러짐 없음 — 위치 제어 로봇으로는 마찰 끌기가 재현 안 됨). 옆 물체가 밀리는지는 물리.
- 물체: sim/assets/objects 외형 + 충돌(볼록 분해·볼록 껍질), 질량은 [추정]. 바닥·벽은 씬 서랍 충돌 상자.
  잡는 동안과 서랍이 열리고 닫히는 동안만 운동학(손·서랍을 따라감), 나머지는 물리. 놓으면 물리로 떨어짐.
- 보고(--report): ① 구간마다 잡지 않은 물체가 3 mm·5° 넘게 움직인 것 ② 다시 인식(실물 덤프·가상) 때 물리 위치와 인식 위치 차이
  (다시 인식 뒤엔 인식 위치로 맞춰 궤적과 어긋나지 않게 함). 판정이 아니라 '여기를 실물로 확인하라'는 표시.
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
ap.add_argument("--report", default="")
ap.add_argument("--scene", default=str(ROOT / "sim/scenes/ready2go_t1.usd"))
ap.add_argument("--speed", type=float, default=1.0)
ap.add_argument("--headless", action="store_true")
ap.add_argument("--quit", action="store_true")
ap.add_argument("--allow-mismatch", action="store_true")
args = ap.parse_args()
app = SimulationApp({"headless": args.headless})

import omni.usd  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import SingleArticulation, SingleRigidPrim  # noqa: E402
from isaacsim.core.utils.types import ArticulationAction  # noqa: E402
from pxr import Gf, PhysxSchema, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade  # noqa: E402

sys.path.insert(0, str(ROOT / "sim/motion_check"))
sys.path.insert(0, str(ROOT / "sim/scripts"))
import m0609_kin as kin  # noqa: E402
import scene_record  # noqa: E402

TRACE = json.loads(Path(args.trace).read_text(encoding="utf-8"))
ITEMS = json.loads((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))["world"]["items"]
MESH_DIR = ROOT / "sim/assets/objects"
JOINT_VEL, PHYS_DT = 20.0, 1.0 / 120.0
MASS = {"eraser": 0.020, "lip_balm": 0.015, "caramel_box": 0.030, "car_key": 0.040, "cover_plate": 0.060, "toy_wrench": 0.050,
        "toy_hammer": 0.080, "airpods_case": 0.050, "masking_tape": 0.020, "toy_car": 0.050}       # [추정] — 무게 실측 없음
CONCAVE = {"toy_wrench", "toy_hammer", "cover_plate", "masking_tape", "toy_car"}                # 볼록 분해 (나머지는 볼록 껍질)
MOVE_MM, TURN_DEG = 3.0, 5.0
# RG2 손가락 사이 폭(mm) ↔ finger_joint(도): 트윈 안쪽 손가락 충돌 형상 사이 틈을 각도마다 잰 값 [실측 트윈 10/13].
# 예전 표(손가락 원점 간격 비례)는 같은 각도에서 최대 7 mm 넓게 봐서 긴 변 잡기(차키 69.5)에서 손가락이 물체를 파고들었음 [사용자 영상 10/13]
_DEG = [0, 5, 10, 20, 30, 40, 50, 60, 67.6]
_W = [99.1, 95.4, 91.0, 80.0, 66.4, 50.6, 33.2, 14.7, 0.2]


def finger_deg(width_mm):
    return float(np.interp(width_mm, _W[::-1], _DEG[::-1]))


def quat_to_R(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def R_to_wxyz(R):
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        return np.array([0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s])
    i = int(np.argmax(np.diag(R)))
    j, k = (i + 1) % 3, (i + 2) % 3
    s = math.sqrt(1.0 + R[i, i] - R[j, j] - R[k, k]) * 2
    q = np.zeros(4)
    q[0] = (R[k, j] - R[j, k]) / s
    q[1 + i] = 0.25 * s
    q[1 + j] = (R[j, i] + R[i, j]) / s
    q[1 + k] = (R[k, i] + R[i, k]) / s
    return q


def wxyz_to_R(q):
    w, x, y, z = q
    return quat_to_R((x, y, z, w))


def gf_to_np(m):
    return np.array([[m[r][c] for c in range(4)] for r in range(4)]).T


def duration(s):
    if s["kind"] in ("movej", "movesj"):
        q = np.array(s["joints"])
        t = float(np.abs(np.diff(q, axis=0)).max(axis=1).sum()) / float(s.get("vel") or JOINT_VEL)
    else:
        t = max(s.get("dist_mm", 0) / max(s.get("vel", 50), 1e-6), s.get("rot_deg", 0) / max(s.get("rot_vel", 30), 1e-6))
    return max(t, 0.2) / args.speed


omni.usd.get_context().open_stage(args.scene)
for _ in range(10):
    app.update()
stage = omni.usd.get_context().get_stage()
roots = [str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
robot_root = next(r for r in roots if r.startswith("/World/m0609"))
cab_root = next((r for r in roots if r.startswith("/World/workspace")), None)
cfg = TRACE.get("config")
chk = scene_record.compare(scene_record.loads(stage.GetRootLayer().customLayerData.get(scene_record.RECORD_KEY)), cfg)
if chk["status"] != "ok" and not args.allow_mismatch:
    print(f"[phys] 씬·궤적 대조 실패 ({chk['status']}): " + "; ".join(chk["diffs"]) + " — --allow-mismatch 로 우회", flush=True)
    app.close()
    sys.exit(2)
places = cfg["places"]
EVENTS = TRACE["scene_events"]
DKEY = EVENTS[0]["objects"][0]["pose"]["frame"]
tf = places[DKEY]["tf"]
T_bd = np.eye(4)
T_bd[:3, :3], T_bd[:3, 3] = quat_to_R(tf["quaternion_xyzw"]), tf["translation_m"]
max_travel = float(places[DKEY]["max_travel_m"])
base_prim = stage.GetPrimAtPath("/World/m0609/base_link")
W = gf_to_np(UsdGeom.Xformable(base_prim if base_prim.IsValid() else stage.GetPrimAtPath("/World/m0609")).ComputeLocalToWorldTransform(0))
robot_colliders = [str(p.GetPath()) for p in Usd.PrimRange(stage.GetPrimAtPath("/World/m0609"), Usd.TraverseInstanceProxies())
                   if p.HasAPI(UsdPhysics.CollisionAPI)]                   # 충돌 형상은 인스턴스 안에 있음 (stage.Traverse 로는 안 보임)
finger_col = [p for p in robot_colliders if "finger" in p.lower() or "rg2" in p.lower()]
TIP_PRIMS = [p for p in finger_col if "inner_finger" in p]                # 손끝 = 안쪽 손가락 충돌 형상 (누르기 접촉 높이 계산)
GRIP_LINKS = [str(p.GetPath()) for p in Usd.PrimRange(stage.GetPrimAtPath("/World/m0609"), Usd.TraverseInstanceProxies())
              if p.HasAPI(UsdPhysics.RigidBodyAPI) and any(k in str(p.GetPath()) for k in ("finger", "knuckle", "gripper_body"))]
print(f"[phys] 로봇 충돌 형상 {len(robot_colliders)}개, 그 중 그리퍼 {len(finger_col)}개", flush=True)
if not finger_col:
    print("[phys] **경고: 그리퍼 충돌 형상이 없어 손끝이 물체를 밀지 못함** — 결과의 '밀림'은 믿을 수 없음", flush=True)

# --- 물체: 모든 장면에 나오는 id 를 미리 만든다 (world.reset 전에 강체로)
mat = UsdShade.Material.Define(stage, "/World/phys_mat")
pm = UsdPhysics.MaterialAPI.Apply(mat.GetPrim())
pm.CreateStaticFrictionAttr(0.5)
pm.CreateDynamicFrictionAttr(0.4)
pm.CreateRestitutionAttr(0.0)
cls_of, XOPS = {}, {}
for e in EVENTS:
    for o in e["objects"]:
        cls_of[o["id"]] = o["class"]
for oid, cls in cls_of.items():
    path = f"/World/phys_objs/{oid.replace('#', '_')}"
    prim = stage.DefinePrim(path, "Xform")
    prim.GetReferences().AddReference(str(MESH_DIR / f"{cls}.usda"))
    xf = UsdGeom.Xformable(prim)
    xf.ClearXformOpOrder()
    XOPS[oid] = (xf.AddTranslateOp(), xf.AddOrientOp())
    XOPS[oid][0].Set(Gf.Vec3d(0, 0, -1.0))
    XOPS[oid][1].Set(Gf.Quatf(1, 0, 0, 0))
    UsdPhysics.RigidBodyAPI.Apply(prim)
    UsdPhysics.MassAPI.Apply(prim).CreateMassAttr(MASS.get(cls, 0.04))
    PhysxSchema.PhysxRigidBodyAPI.Apply(prim).CreateEnableCCDAttr(True)
    mesh = stage.GetPrimAtPath(f"{path}/mesh")
    UsdPhysics.CollisionAPI.Apply(mesh)
    UsdPhysics.MeshCollisionAPI.Apply(mesh).CreateApproximationAttr("convexDecomposition" if cls in CONCAVE else "convexHull")
    UsdShade.MaterialBindingAPI.Apply(mesh).Bind(mat, UsdShade.Tokens.weakerThanDescendants, "physics")
    UsdPhysics.FilteredPairsAPI.Apply(prim)                               # 집기·놓기 대상일 때만 손가락과 충돌 끔 (잡기는 흉내라 손가락이 물체 안에 들어감)

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
bodies = {}
for oid in cls_of:
    rp = SingleRigidPrim(f"/World/phys_objs/{oid.replace('#', '_')}", name=f"o_{oid.replace('#', '_')}")
    rp.initialize()
    bodies[oid] = rp
kin_attr = {oid: UsdPhysics.RigidBodyAPI(stage.GetPrimAtPath(f"/World/phys_objs/{oid.replace('#', '_')}")).GetKinematicEnabledAttr() or
            UsdPhysics.RigidBodyAPI(stage.GetPrimAtPath(f"/World/phys_objs/{oid.replace('#', '_')}")).CreateKinematicEnabledAttr(False)
            for oid in cls_of}


def set_kin(oid, on):
    kin_attr[oid].Set(bool(on))


_bbc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "proxy", "render", "guide"], useExtentsHint=False)   # 충돌 형상은 guide 일 수 있음


def tip_low_z():
    """손끝(안쪽 손가락 충돌 형상) 가장 낮은 점의 월드 z."""
    _bbc.Clear()
    rs = [_bbc.ComputeWorldBound(stage.GetPrimAtPath(p)).ComputeAlignedRange() for p in TIP_PRIMS]
    zs = [r.GetMin()[2] for r in rs if not r.IsEmpty()]
    return min(zs) if zs else None                                        # 못 구하면 None (TCP 기준으로)


def tcp_shift(q, dz):
    """관절각 q 의 TCP 를 월드 z 로 dz 만큼 옮긴 관절각 (IK, 같은 자세)."""
    T = kin.fk(q)
    Tw = W @ T
    Tw[2, 3] += dz
    return kin.ik(np.linalg.inv(W) @ Tw, q)[0]


TRAY_BODIES = [p for p in (f"/World/workspace/cabinet/{DKEY}_tray", "/World/workspace/handover_tray") if stage.GetPrimAtPath(p).IsValid()]


def grip_filter(oid, on, trays=False):
    """oid 와 그리퍼 링크(+ trays 면 서랍·트레이 몸체) 사이 충돌 끔(on)/켬. 넛지 대상·다른 물체는 그대로 부딪힘.
    쥔 물체(운동학)가 서랍 바닥을 파고들면 서랍 몸체를 밀어 서랍 안 물체가 다 같이 출렁임 → 쥔 동안 서랍·트레이와도 끔."""
    rel_ = UsdPhysics.FilteredPairsAPI(stage.GetPrimAtPath(f"/World/phys_objs/{oid.replace('#', '_')}")).GetFilteredPairsRel()
    rel_.SetTargets([Sdf.Path(p) for p in GRIP_LINKS + (TRAY_BODIES if trays else [])] if on else [])


def support_z(oid):
    """oid 를 놓을 때 받칠 면의 월드 z: 서랍 바닥(또는 트레이 바닥)과 그 밑 다른 물체 윗면 중 가장 높은 것 [근사: 물체 평평하게 놓임]."""
    T = pose_of(oid)
    x, y = T[0, 3], T[1, 3]
    floors = []
    for p in TRAY_BODIES:                                                  # 몸체 아래 floor 상자 윗면
        fp = stage.GetPrimAtPath(f"{p}/floor")
        if fp.IsValid():
            _bbc.Clear()
            r = _bbc.ComputeWorldBound(fp).ComputeAlignedRange()
            if not r.IsEmpty() and r.GetMin()[0] <= x <= r.GetMax()[0] and r.GetMin()[1] <= y <= r.GetMax()[1]:
                floors.append(r.GetMax()[2])
    z = max(floors) if floors else None
    bottom = T[2, 3]
    for o2 in present:
        if o2 == oid:
            continue
        T2 = pose_of(o2)
        sz = ITEMS[cls_of[o2]]["size_m"]
        d = np.linalg.inv(T2[:3, :3]) @ (T[:3, 3] - T2[:3, 3])
        top2 = T2[2, 3] + sz[2]
        if abs(d[0]) <= sz[0] / 2 and abs(d[1]) <= sz[1] / 2 and top2 <= bottom + 0.03:
            z = top2 if z is None else max(z, top2)
    return z


def obj_world(o, travel):
    x, y = o["pose"]["position"][:2]
    h = ITEMS[o["class"]]["size_m"][2]
    T = np.eye(4)
    T[:3, :3] = T_bd[:3, :3] @ kin._rz(o["pose"]["yaw"])
    T[:3, 3] = (T_bd @ np.array([x, y, max(o["top_z"] - h, 0.0) + 0.0005, 1.0]))[:3] + T_bd[:3, 0] * (max_travel - travel)
    return W @ T


def put(oid, T):
    """운동학(쥔 것·서랍 따라가는 것)은 USD 위치로 옮김(PhysX 가 운동학 목표로 따라감) — 물리 API 로 옮기면 무시되고 속도 설정은
    'Body must be non-kinematic' 오류 [사용자 영상 10/13: 그리퍼만 움직이고 물체는 제자리]. 물리 물체는 순간 이동 + 속도 0."""
    q = R_to_wxyz(T[:3, :3])
    if kin_attr[oid].Get():
        XOPS[oid][0].Set(Gf.Vec3d(*[float(v) for v in T[:3, 3]]))
        XOPS[oid][1].Set(Gf.Quatf(float(q[0]), float(q[1]), float(q[2]), float(q[3])))
        return
    bodies[oid].set_world_pose(position=T[:3, 3], orientation=q)
    bodies[oid].set_linear_velocity(np.zeros(3))
    bodies[oid].set_angular_velocity(np.zeros(3))


def pose_of(oid):
    p, q = bodies[oid].get_world_pose()
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = wxyz_to_R(q), p
    return T


def drawer_xy_yaw(T, travel):
    """월드 변환 → 서랍 좌표 (x, y m, yaw rad) — 인식과 비교용."""
    M = np.linalg.inv(W) @ T
    M[:3, 3] -= T_bd[:3, 0] * (max_travel - travel)
    Td = np.linalg.inv(T_bd) @ M
    return Td[0, 3], Td[1, 3], math.atan2(Td[1, 0], Td[0, 0])


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
    if not args.headless:
        time.sleep(max(0.0, PHYS_DT - 0.001))


grips = {}
for g in TRACE.get("grip_events", []):
    grips.setdefault(g["before_segment"], []).append(g["width_mm"])
acts = [r for r in TRACE["results"] if r.get("success") and r["action"] in ("pick_object", "place_object")]
rescans = {e["before_segment"]: e for e in EVENTS[1:] if e["why"].startswith("인식")}
scan_src = {s["segment"]: s["source"] for s in TRACE.get("scans", [])}


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

report = {"trace": args.trace, "robot_colliders": len(robot_colliders), "gripper_colliders": len(finger_col), "moves": [], "scan_drift": []}
present = {o["id"] for o in EVENTS[0]["objects"]}
objs = {o["id"]: dict(o) for o in EVENTS[0]["objects"]}
# 첫 장면에서 가려진 물체(occluded_by 있음)는 보이는 부분만으로 위치가 치우침(10/13: 3단 캐러멜 17 mm·90°) → 그 물체를 집기 전
# 실물 다시 인식에서 같은 id 가 다 보이면 그 자리로 바로잡음 (받침이 어긋나 위 물체가 떨어지는 것 방지). 바로잡은 것은 보고에 남김
_pick_seg = {r["target"]: r["first_segment"] for r in reversed(TRACE["results"]) if r["action"] == "pick_object" and r.get("success")}
report["refined"] = []
for oid, o in objs.items():
    if not o.get("occluded_by"):
        continue
    for e in sorted(rescans.values(), key=lambda e: e["before_segment"]):
        if e["before_segment"] > _pick_seg.get(oid, 10 ** 9):
            break
        o2 = next((x for x in e["objects"] if x["id"] == oid and not x.get("occluded_by")), None)
        if o2 is not None:
            dd = math.hypot(o2["pose"]["position"][0] - o["pose"]["position"][0], o2["pose"]["position"][1] - o["pose"]["position"][1]) * 1000
            report["refined"].append({"id": oid, "from": e["why"], "shift_mm": round(dd, 1),
                                      "dyaw_deg": round(math.degrees(o2["pose"]["yaw"] - o["pose"]["yaw"]), 1)})
            print(f"[phys]   첫 장면 {oid}: 가려진 자리 → {e['why']} 자리로 바로잡음 ({dd:.1f} mm)", flush=True)
            objs[oid] = dict(o, pose=o2["pose"])
            break
travel, width, held, rel = 0.0, 110.0, None, None
for oid in cls_of:
    set_kin(oid, oid not in present)
report["stack_lift"] = []
for oid in sorted(present, key=lambda k: objs[k]["top_z"]):              # 아래부터: 비전 top_z − 높이가 받침 윗면보다 낮으면(파묻힘) 받침 위로
    T = obj_world(objs[oid], travel)
    put(oid, T)
    sz_ = support_z(oid)
    if sz_ is not None and T[2, 3] < sz_ + 0.0005:
        report["stack_lift"].append({"id": oid, "lift_mm": round((sz_ + 0.0005 - T[2, 3]) * 1000, 1)})
        T[2, 3] = sz_ + 0.0005
        put(oid, T)
_T0 = {oid: pose_of(oid) for oid in present}
for _ in range(int(1.0 / PHYS_DT)):                                       # 내려앉기 1 s — 인식 위치끼리 겹치면 여기서 밀려남(보고에 따로)
    apply(TRACE["segments"][0]["joints"][0], finger_deg(width), travel)
report["settle"] = []
for oid, T0 in _T0.items():
    d = np.linalg.norm(pose_of(oid)[:3, 3] - T0[:3, 3]) * 1000
    report["settle"].append({"id": oid, "move_mm": round(d, 1)})
    if d > MOVE_MM:
        print(f"[phys]   첫 장면 내려앉기: {oid} {d:.1f} mm (인식 자리끼리 겹침·뜸 — 이후 움직임 판단에서 빼고 볼 것)", flush=True)
in_drawer = set(present)                                                  # 서랍과 같이 움직일 물체(트레이에 놓은 것 제외)
press_dz, press_step, press_obj = 0.0, None, None
for s in TRACE["segments"]:
    e = rescans.get(s["i"])
    if e is not None:                                                      # 다시 인식: 물리 위치와 인식 위치 차이를 적고, 인식 위치로 맞춤
        for o in e["objects"]:
            if o["id"] == held or o["id"] not in bodies:
                continue
            if o["id"] in present:
                x, y, yaw = drawer_xy_yaw(pose_of(o["id"]), travel)
                dx, dy = (o["pose"]["position"][0] - x) * 1000, (o["pose"]["position"][1] - y) * 1000
                dyaw = math.degrees((o["pose"]["yaw"] - yaw + math.pi / 2) % math.pi - math.pi / 2)
                report["scan_drift"].append({"segment": s["i"], "scan": e["why"], "id": o["id"], "dist_mm": round(math.hypot(dx, dy), 1),
                                             "dx_mm": round(dx, 1), "dy_mm": round(dy, 1), "dyaw_deg": round(dyaw, 1)})
                if math.hypot(dx, dy) > MOVE_MM or abs(dyaw) > TURN_DEG:
                    print(f"[phys]   {e['why']}: {o['id']} 물리 위치와 인식 차이 {math.hypot(dx, dy):.1f} mm, {dyaw:+.1f}°", flush=True)
                if o.get("occluded_by") or any(o["id"] in (x.get("occluded_by") or []) for x in e["objects"]):
                    # 가려진 물체·그 위 물체는 인식 자리로 옮기지 않음 — 가려진 자리는 치우침(10/13 인식 6: 캐러멜 18 mm·90°, 윗면 25.7)
                    # → 옮기면 위 차키가 받침을 잃고 떨어짐(서랍 나올 때 캐러멜 7.7·차키 14 mm). 물리 자리 유지
                    continue
            objs[o["id"]] = dict(o)
            present.add(o["id"])
            in_drawer.add(o["id"])
            set_kin(o["id"], False)
            put(o["id"], obj_world(o, travel))
    a = act_at(s["i"])
    tgt = (a or {}).get("target") if a and a["action"] == "pick_object" else (held if a and a["action"] == "place_object" else None)
    for oid in cls_of:
        grip_filter(oid, oid == tgt, trays=(oid == held))
    for w_new in grips.get(s["i"], []):
        for k in range(1, 31):
            apply(s["joints"][0], finger_deg(width + (w_new - width) * k / 30), travel)
        closing, width = w_new < width, w_new
        if a and a["action"] == "pick_object" and closing and held is None and w_new > 3.0 and a.get("target") in present:
            held = a["target"]
            tz, sup = tip_low_z(), support_z(held)                         # 닫은 순간 손끝 최저점 vs 물체 밑 받침(바닥·아래 물체) 윗면
            if tz is not None and sup is not None:
                clr = (tz - sup) * 1000
                report.setdefault("grasp_clearance", []).append({"segment": s["i"], "id": held, "tip_above_support_mm": round(clr, 1)})
                print(f"[phys]     집기 손끝-받침 여유 {held}: {clr:+.1f} mm{'  ◀ 손끝이 받침 윗면보다 낮음 (받침 옆으로 내려간 것인지 화면 확인)' if clr < 0 else ''}", flush=True)
            for tp in TIP_PRIMS + [p for p in GRIP_LINKS if "knuckle" in p]:   # 잡는 순간 손가락·마디가 다른 물체와 겹치는지 (축 정렬 상자)
                _bbc.Clear()
                rt = _bbc.ComputeWorldBound(stage.GetPrimAtPath(tp)).ComputeAlignedRange()
                for o2 in present:
                    if o2 == held:
                        continue
                    ro = _bbc.ComputeWorldBound(stage.GetPrimAtPath(f"/World/phys_objs/{o2.replace('#', '_')}")).ComputeAlignedRange()
                    ov = [min(rt.GetMax()[k], ro.GetMax()[k]) - max(rt.GetMin()[k], ro.GetMin()[k]) for k in range(3)]
                    if min(ov) > 0:
                        cw = (np.array(rt.GetMin()) + np.array(rt.GetMax())) / 2
                        Tf = np.eye(4); Tf[:3, 3] = cw
                        fx_, fy_, _ = drawer_xy_yaw(Tf, travel)
                        Tq = pose_of(o2)
                        ox_, oy_, oyaw_ = drawer_xy_yaw(Tq, travel)
                        c_, s_ = math.cos(oyaw_), math.sin(oyaw_)
                        lx, ly = (fx_ - ox_) * c_ + (fy_ - oy_) * s_, -(fx_ - ox_) * s_ + (fy_ - oy_) * c_
                        print(f"[phys]       손가락 가운데 서랍 ({fx_*1000:.1f}, {fy_*1000:.1f}) mm, 높이 {cw[2]*1000:.1f} / {o2} 가운데 ({ox_*1000:.1f}, {oy_*1000:.1f}) yaw {math.degrees(oyaw_):.1f}° "
                              f"→ 물체 좌표 (긴 {lx*1000:+.1f}, 짧은 {ly*1000:+.1f}) mm, 반폭 {ITEMS[cls_of[o2]]['size_m'][0]*500:.1f}/{ITEMS[cls_of[o2]]['size_m'][1]*500:.1f}; 물체 윗면 z {(Tq[2,3]+ITEMS[cls_of[o2]]['size_m'][2])*1000:.1f}", flush=True)
                        print(f"[phys]       {tp.split('/')[-1] if 'collisions' not in tp else tp.split('/collisions/')[1].split('/')[0]} ↔ {o2} 겹침 "
                              f"x {ov[0]*1000:.1f} y {ov[1]*1000:.1f} z {ov[2]*1000:.1f} mm (축 정렬 상자)", flush=True)
            set_kin(held, True)
            grip_filter(held, True, trays=True)
            rel = np.linalg.inv(W @ kin.fk(s["joints"][0])) @ pose_of(held)
            in_drawer.discard(held)
            print(f"[phys]     잡음 {held}", flush=True)
        elif a and a["action"] == "place_object" and not closing and held is not None:
            sz_ = support_z(held)                                          # 놓는 순간 바닥·아래 물체 속이면 그 위로 (흉내 잡기라 파묻힐 수 있음)
            Th = pose_of(held)
            tilt = math.degrees(math.acos(max(-1.0, min(1.0, Th[2, 2]))))
            gap = None if sz_ is None else round((Th[2, 3] - sz_) * 1000, 1)
            report.setdefault("release", []).append({"segment": s["i"], "id": held, "tilt_deg": round(tilt, 1), "above_support_mm": gap})
            print(f"[phys]     놓는 순간 {held}: 기울기 {tilt:.1f}°, 받침 위 {gap} mm", flush=True)
            if sz_ is not None and Th[2, 3] < sz_ + 0.0005:
                report.setdefault("release_lift", []).append({"segment": s["i"], "id": held, "lift_mm": round((sz_ + 0.001 - Th[2, 3]) * 1000, 1)})
                Th[2, 3] = sz_ + 0.001
                put(held, Th)
            grip_filter(held, True)                                        # 서랍·트레이와는 다시 부딪힘 (그리퍼와는 이번 동작 동안 끔)
            set_kin(held, False)                                           # 놓음 → 물리로 떨어짐
            if a.get("location") in (DKEY, None) and a.get("location") != "handover_zone":
                in_drawer.add(held)
            print(f"[phys]     놓음 {held}", flush=True)
            held, rel = None, None
    moving_drawer = s["step"] in ("open", "close") and s["stage"] in ("pull", "push", "push_slow")
    for oid in in_drawer:                                                  # 서랍이 움직이는 동안은 서랍을 따라감(운동학)
        if oid != held:
            set_kin(oid, moving_drawer)
    start = {oid: pose_of(oid) for oid in present if oid != held}
    if moving_drawer:
        T_in = {oid: np.linalg.inv(W @ T_bd) @ start[oid] for oid in in_drawer if oid != held}
        trav0 = travel
    q_all = np.array(s["joints"])
    # 누르기: 실물은 힘이 잡힐 때까지 내려감 — 궤적 접촉 높이(비전 top_z 기준) 대신 트윈 물체 윗면에 손끝이 닿게 내림.
    # 누르기 ~ 끌기(같은 동작, 들어 올리기 전)까지 같은 높이 보정
    if s["stage"] == "press":
        apply(q_all[-1], finger_deg(width), travel)
        tcp_w = (W @ kin.fk(q_all[-1]))[:3, 3]
        near = min((oid for oid in present if oid != held), key=lambda oid: np.linalg.norm(pose_of(oid)[:2, 3] - tcp_w[:2]), default=None)
        if near is not None:
            top = pose_of(near)[2, 3] + ITEMS[cls_of[near]]["size_m"][2]
            tz = tip_low_z()
            print(f"[phys]     손끝 최저 z {tz}, TCP z {tcp_w[2]:.4f}, 물체 윗면 z {top:.4f}", flush=True)
            press_dz = top - (tz if tz is not None else tcp_w[2]) - 0.0005   # 0.5 mm 눌림 (손끝을 못 재면 TCP 기준)
            press_step, press_obj = s["step"], near
            print(f"[phys]     누르기 높이 보정 {press_dz * 1000:+.1f} mm ({near} 윗면에 손끝)", flush=True)
            report.setdefault("press_adjust", []).append({"segment": s["i"], "id": near, "dz_mm": round(press_dz * 1000, 1)})
    elif s["stage"].startswith("lift") or s["step"] != globals().get("press_step"):
        press_dz, press_step, press_obj = 0.0, None, None
    if globals().get("press_dz"):
        q_all = np.array([tcp_shift(q, press_dz) for q in q_all])
    n = max(1, int(duration(s) / PHYS_DT))
    print(f"[phys] #{s['i']:3d} {s['step']:8s} {s['kind']} {s['stage']}", flush=True)
    # 끌기: 실물은 누른 힘의 마찰로 끌림 — 트윈 로봇은 위치만 따라가 마찰로 못 끎 → 끄는 물체는 손끝을 따라 궤적대로 끌린다고 가정
    # (미끄러짐 없음). 그 물체·손가락에 옆 물체가 밀리는지는 물리로 봄
    drag_obj = press_obj if (s["stage"].startswith("drag") or s["stage"].startswith("sweep") or s["stage"] == "push_back") and press_obj else None
    if drag_obj:
        set_kin(drag_obj, True)
        grip_filter(drag_obj, True)
        drag_rel = np.linalg.inv(W @ kin.fk(q_all[0])) @ pose_of(drag_obj)
        start.pop(drag_obj, None)
    for k in range(n + 1):
        f = k / n
        qf = f * (len(q_all) - 1)
        i0 = int(math.floor(qf))
        i1 = min(i0 + 1, len(q_all) - 1)
        q = q_all[i0] + (q_all[i1] - q_all[i0]) * (qf - i0)
        if s["stage"] == "pull":
            travel = min(max_travel, f * s.get("dist_mm", 0) / 1000.0)
        elif s["stage"] in ("push", "push_slow"):
            before, tot = PUSH[s["i"]]
            pushed = before + f * s.get("dist_mm", 0) / 1000.0
            travel = min(max_travel, max(0.0, max_travel - max(0.0, pushed - (tot - max_travel))))
        if moving_drawer:
            shift = np.eye(4)
            shift[0, 3] = trav0 - travel                                    # 서랍 좌표 x 로 (인출이 줄면 +x)
            for oid, Tr in T_in.items():
                put(oid, W @ T_bd @ shift @ Tr)
        if held is not None:
            Tc = W @ kin.fk(q) @ rel
            sup = support_z(held) if s["step"] in ("aside", "restore", "free", "place") else None
            if sup is not None and Tc[2, 3] < sup:                         # 내려가다 바닥·아래 물체에 먼저 닿음 → 손 안에서 위로 밀림
                d_mm = (sup - Tc[2, 3]) * 1000                              # (실물은 힘 감시가 멈추는 자리) — 얼마나 먼저 닿았는지 기록
                fl = report.setdefault("place_early_touch", {})
                key = f"{s['i']}:{held}"
                fl[key] = max(fl.get(key, 0.0), round(d_mm, 1))
                Tc[2, 3] = sup
                rel = np.linalg.inv(W @ kin.fk(q)) @ Tc
            put(held, Tc)
        if drag_obj:                                                       # 위치만 따라감(자세는 끌기 시작 자세 유지, 높이 그대로)
            Tn = W @ kin.fk(q) @ drag_rel
            T0d = pose_of(drag_obj)
            Tn[:3, :3], Tn[2, 3] = T0d[:3, :3], T0d[2, 3]
            put(drag_obj, Tn)
        apply(q, finger_deg(width), travel)
        if held is not None and k == n:                                    # 쥔 물체가 실제로(물리 엔진에서) 손을 따라왔는지 — 화면 없이도 확인
            err = np.linalg.norm(pose_of(held)[:3, 3] - Tc[:3, 3]) * 1000
            if err > 5.0:
                print(f"[phys]   **쥔 {held} 이 손을 안 따라옴: {err:.0f} mm** (구간 #{s['i']})", flush=True)
                report.setdefault("follow_error", []).append({"segment": s["i"], "id": held, "err_mm": round(err, 1)})
    if moving_drawer:
        for oid in T_in:
            Tk = W @ T_bd @ shift @ T_in[oid]
            set_kin(oid, False)
            put(oid, Tk)                                                    # 운동학 → 물리로 바꿀 때 마지막 자리 그대로 넘김
            x_, y_, _ = drawer_xy_yaw(pose_of(oid), travel)
            o0 = objs.get(oid)
            if o0 is not None:
                print(f"[phys]     서랍 {'열림' if s['stage'] == 'pull' else '닫힘'} 뒤 {oid} 서랍 좌표 ({x_ * 1000:.1f}, {y_ * 1000:.1f}) mm "
                      f"(처음 {o0['pose']['position'][0] * 1000:.1f}, {o0['pose']['position'][1] * 1000:.1f})", flush=True)
    if drag_obj:
        set_kin(drag_obj, False)
        grip_filter(drag_obj, False)
        report.setdefault("drags", []).append({"segment": s["i"], "id": drag_obj, "dist_mm": round(s.get("dist_mm", 0), 1)})
        print(f"[phys]     끌기 {drag_obj} {s.get('dist_mm', 0):.0f} mm (손끝 따라 — 가정)", flush=True)
    for _ in range(int(0.3 / PHYS_DT)):                                    # 멈춘 뒤 0.3 s (굴러가는 것까지)
        apply(q_all[-1], finger_deg(width), travel)
    for oid, T0 in start.items():
        if moving_drawer or oid == held:
            continue
        T1 = pose_of(oid)
        d = np.linalg.norm(T1[:3, 3] - T0[:3, 3]) * 1000
        ang = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(T0[:3, :3].T @ T1[:3, :3]) - 1) / 2))))
        if d > MOVE_MM or ang > TURN_DEG:
            rec = {"segment": s["i"], "step": s["step"], "stage": s["stage"], "id": oid, "move_mm": round(d, 1), "turn_deg": round(ang, 1),
                   "dz_mm": round((T1[2, 3] - T0[2, 3]) * 1000, 1), "acting": (a or {}).get("target")}
            report["moves"].append(rec)
            print(f"[phys]   ▶ {oid} 움직임 {d:.1f} mm, 회전 {ang:.1f}° (높이 {rec['dz_mm']:+.1f} mm) — 구간 #{s['i']} {s['step']}/{s['stage']}", flush=True)
print(f"[phys] 끝 — 잡지 않은 물체 움직임 {len(report['moves'])}건, 다시 인식 차이 기록 {len(report['scan_drift'])}건", flush=True)
if args.report:
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[phys] 보고 → {args.report}", flush=True)
if not args.quit:
    while app.is_running():
        world.step(render=not args.headless)
app.close()
