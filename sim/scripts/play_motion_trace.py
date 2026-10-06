"""B 스킬 흐름의 로봇 궤적을 트윈에서 재생한다 (담당 A, 트윈 사전 검증). 씬 파일은 저장하지 않는다.

먼저 궤적을 만든다 (로봇·Isaac 없이, B 코드가 있는 저장소에서):
  python3 sim/motion_check/trace_skill_flow.py --repo <B 저장소> --out /tmp/trace.json
재생 (GUI, Isaac Sim 이 떠 있으면 먼저 끈다):
  ISAAC_SIM_CMD=$HOME/isaac-sim-5.1.0/python.sh bash sim/run_isaac.sh sim/scripts/play_motion_trace.py --trace /tmp/trace.json
옵션: --speed 배속(기본 1.0 = 스킬 파라미터 속도, 관절 이동 20°/s) / --segments "8-10,15-22"(trace 표의 # 열) /
      --flag-slow 2 (◀ 구간만 2배 느리게) / --loop / --headless --quit (시험용)
- 관절은 매 스텝 위치를 그대로 설정(텔레포트) + 구동 목표도 같은 값 → 물리 처짐·떨림 없이 궤적 그대로 보인다 (mirror_joint_states.py 와 같은 방식).
- 그리퍼: 궤적에 기록된 RG2 폭(mm)을 finger_joint 각도로 바꿔 0.5 초 동안 움직인다. 폭↔각도는 트윈에서 잰 손가락 간격 표로 근사 [추정].
- ◀ 구간(손끝 10 mm당 관절 변화 > 4° 등) 동안 손끝에 빨간 공, 터미널에 구간 이름·지표 출력.
- 궤적은 기하(IK) 계산이라 두산 제어기의 실제 보간·특이점 처리와 다를 수 있다 [추정]. 서랍·지우개 움직임은 흉내다.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from isaacsim import SimulationApp

ROOT = Path(__file__).resolve().parents[2]
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--trace", required=True)
ap.add_argument("--scene", default=str(ROOT / "sim/scenes/ready2go_t1.usd"))
ap.add_argument("--speed", type=float, default=1.0)
ap.add_argument("--segments", default="")
ap.add_argument("--flag-slow", type=float, default=1.0)
ap.add_argument("--loop", action="store_true")
ap.add_argument("--headless", action="store_true")
ap.add_argument("--quit", action="store_true", help="끝나면 종료(시험용)")
args = ap.parse_args()

app = SimulationApp({"headless": args.headless})

import omni.usd  # noqa: E402
import yaml  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import SingleArticulation  # noqa: E402
from isaacsim.core.utils.types import ArticulationAction  # noqa: E402
from pxr import Gf, UsdGeom, UsdPhysics  # noqa: E402

sys.path.insert(0, str(ROOT / "sim/motion_check"))
import m0609_kin as kin  # noqa: E402

TRACE = json.loads(Path(args.trace).read_text(encoding="utf-8"))
JOINT_VEL, PHYS_DT = 20.0, 1.0 / 60.0
# RG2 폭(mm) ↔ finger_joint(도): 트윈에서 잰 inner_finger 원점 간격(0° 137.3 mm … 67.6° 38.7 mm)을 폭 110…0 mm 로 선형 대응 [추정, 실측 10/06]
_DEG = [0, 10, 20, 30, 40, 50, 60, 67.6]
_GAP = [137.3, 129.2, 118.2, 104.7, 89.0, 71.7, 53.2, 38.7]
_W = [(g - 38.7) / (137.3 - 38.7) * 110.0 for g in _GAP]


def finger_deg(width_mm):
    return float(np.interp(width_mm, _W[::-1], _DEG[::-1]))


def wanted(i):
    if not args.segments.strip():
        return True
    for part in args.segments.split(","):
        a, _, b = part.partition("-")
        if int(a) <= i <= int(b or a):
            return True
    return False


def quat_to_R(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def duration(s):
    if s["kind"] == "movej":
        t = max(s["joint_travel_deg"]) / JOINT_VEL
    else:
        t = max(s.get("dist_mm", 0) / max(s.get("vel", 50), 1e-6), s.get("rot_deg", 0) / max(s.get("rot_vel", 30), 1e-6))
    return max(t, 0.2) / args.speed * (args.flag_slow if s.get("flag") else 1.0)


def gf_to_np(m):
    return np.array([[m[r][c] for c in range(4)] for r in range(4)]).T


def np_to_gf(T):
    return Gf.Matrix4d(*[float(T[c][r]) for r in range(4) for c in range(4)])


omni.usd.get_context().open_stage(args.scene)
for _ in range(10):
    app.update()
stage = omni.usd.get_context().get_stage()
roots = [str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
robot_root = next(r for r in roots if r.startswith("/World/m0609"))
cab_root = next((r for r in roots if r.startswith("/World/workspace")), None)

repo = Path(TRACE["repo"])
places = yaml.safe_load(((repo / "config/places.yaml") if (repo / "config/places.yaml").exists()
                         else ROOT / "config/places.yaml").read_text(encoding="utf-8"))
size = json.loads((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))["world"]["items"]["eraser"]["size_m"]
tf = places["drawer_top"]["tf"]
T_bd = np.eye(4)
T_bd[:3, :3], T_bd[:3, 3] = quat_to_R(tf["quaternion_xyzw"]), tf["translation_m"]
max_travel = float(places["drawer_top"]["max_travel_m"])
base_prim = stage.GetPrimAtPath("/World/m0609/base_link")
W = gf_to_np(UsdGeom.Xformable(base_prim if base_prim.IsValid() else stage.GetPrimAtPath("/World/m0609"))
             .ComputeLocalToWorldTransform(0))

cube = UsdGeom.Cube.Define(stage, "/World/eraser_trace")
cube.CreateSizeAttr(1.0)
cube.GetDisplayColorAttr().Set([Gf.Vec3f(0.95, 0.85, 0.2)])
c_xf = UsdGeom.Xformable(cube.GetPrim())
c_xf.ClearXformOpOrder()
c_op = c_xf.AddTransformOp()
marker = UsdGeom.Sphere.Define(stage, "/World/singularity_marker")
marker.CreateRadiusAttr(0.03)
marker.GetDisplayColorAttr().Set([Gf.Vec3f(1.0, 0.1, 0.1)])
m_xf = UsdGeom.Xformable(marker.GetPrim())
m_xf.ClearXformOpOrder()
m_op = m_xf.AddTranslateOp()

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
    d_idx = next((i for i, n in enumerate(cab.dof_names) if n == "drawer_top_joint"), None)
drawer_attr = stage.GetPrimAtPath("/World/workspace/cabinet/drawer_top_joint").GetAttribute("drive:linear:physics:targetPosition")
print(f"[play] 로봇 {robot_root} DOF {len(dofs)}, 서랍 {'관절 직접 설정' if d_idx is not None else '구동 목표'}, "
      f"B 코드 {TRACE.get('repo_sha') or TRACE['repo']}", flush=True)


def eraser_world(pose, travel):
    x, y = pose["position"][:2]
    T = np.eye(4)
    T[:3, :3] = T_bd[:3, :3] @ kin._rz(pose["yaw"])
    T[:3, 3] = (T_bd @ np.array([x, y, size[2] / 2, 1.0]))[:3] + T_bd[:3, 0] * (max_travel - travel)
    return W @ T


def set_cube(T):
    c_op.Set(np_to_gf(T @ np.diag([size[0], size[1], size[2], 1.0])))


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


_b1 = stage.GetPrimAtPath("/World/workspace/cabinet/drawer_top_joint").GetRelationship("physics:body1").GetTargets()[0]
DRAWER0 = np.array(gf_to_np(UsdGeom.Xformable(stage.GetPrimAtPath(_b1)).ComputeLocalToWorldTransform(0))[:3, 3])
segs = [s for s in TRACE["segments"] if wanted(s["i"])]
grips = {}
for g in TRACE.get("grip_events", []):
    grips.setdefault(g["before_segment"], []).append(g["width_mm"])
ers0 = TRACE["eraser"]["pose"]
ers1 = (TRACE.get("eraser_after") or TRACE["eraser"])["pose"]
print(f"[play] {len(TRACE['segments'])}구간 중 {len(segs)}구간, 배속 {args.speed}, ◀ 구간 ×{args.flag_slow} 느리게", flush=True)
while app.is_running():
    first = segs[0]["i"]
    travel, width, held, rel = 0.0, 110.0, False, None
    for s in TRACE["segments"][:first]:                                  # 건너뛴 앞 구간의 서랍·그리퍼 상태
        travel = max_travel if s["stage"] == "pull" else (0.0 if s["stage"] == "push" else travel)
    for b, ws in grips.items():
        if b <= first:
            width = ws[-1]
    ers = ers1 if any(s["stage"] == "drag" for s in TRACE["segments"][:first]) else ers0
    set_cube(eraser_world(ers, travel))
    for _ in range(30):
        apply(TRACE["segments"][first]["joints"][0], finger_deg(width), travel)
    for s in segs:
        for w_new in grips.get(s["i"], []):                              # 이 구간 전에 그리퍼가 움직였으면 0.5 초 동안
            print(f"[play]     그리퍼 {width:.0f} → {w_new:.0f} mm", flush=True)
            for k in range(1, 31):
                apply(s["joints"][0], finger_deg(width + (w_new - width) * k / 30), travel)
            width = w_new
            if s["step"] == "pick" and w_new < 50 and not held:            # 지우개를 잡음
                held = True
                rel = np.linalg.inv(W @ kin.fk(s["joints"][0])) @ eraser_world(ers1, travel)
            if s["step"] == "place" and w_new > 30 and held:
                held = False
        flag = s.get("flag")
        info = (f"{s.get('dist_mm', 0):5.0f} mm {s.get('rot_deg', 0):4.0f}° 10mm당 관절 {s.get('amp_deg_per_10mm', 0):4.1f}° "
                f"J3 최소 {s['min_abs_j3']:4.1f}°") if s["kind"] == "movel" else f"관절 이동 최대 {max(s['joint_travel_deg']):5.1f}°"
        print(f"[play] #{s['i']:2d} {s['step']:6s} {s['kind']} {s['stage']:22s} {info}{'  ◀ 특이점 근처' if flag else ''}", flush=True)
        vis = UsdGeom.Imageable(marker.GetPrim())
        vis.MakeVisible() if flag else vis.MakeInvisible()
        q_all = np.array(s["joints"])
        n = max(1, int(duration(s) / PHYS_DT))
        for k in range(n + 1):
            f = k / n
            qf = f * (len(q_all) - 1)
            a = int(math.floor(qf))
            b = min(a + 1, len(q_all) - 1)
            q = q_all[a] + (q_all[b] - q_all[a]) * (qf - a)
            T_tcp = W @ kin.fk(q)
            m_op.Set(Gf.Vec3d(*[float(v) for v in T_tcp[:3, 3]]))
            if s["stage"] == "pull":
                travel = min(max_travel, f * s.get("dist_mm", 0) / 1000.0)
            elif s["stage"] == "push":
                d = s.get("dist_mm", 0) / 1000.0
                travel = min(max_travel, max(0.0, max_travel - max(0.0, f * d - (d - max_travel))))
            if s["stage"] == "drag":
                set_cube(eraser_world({"position": [ers0["position"][i] + (ers1["position"][i] - ers0["position"][i]) * f
                                                    for i in range(3)], "yaw": ers1["yaw"]}, travel))
            elif held:
                set_cube(T_tcp @ rel)
            elif s["step"] in ("open", "close"):
                set_cube(eraser_world(ers1 if s["step"] == "close" else ers0, travel))
            apply(q, finger_deg(width), travel)
            if not app.is_running():
                break
        UsdGeom.Imageable(marker.GetPrim()).MakeInvisible()
    if args.headless:
        from isaacsim.core.prims import SingleRigidPrim
        body = stage.GetPrimAtPath("/World/workspace/cabinet/drawer_top_joint").GetRelationship("physics:body1").GetTargets()[0]
        rp = SingleRigidPrim(str(body))
        rp.initialize()
        print(f"[play] 시험: 서랍 몸체 {body} 월드 위치 {np.round(rp.get_world_pose()[0], 4)} (목표 인출 {travel:.3f} m, "
              f"시작 위치 {np.round(DRAWER0, 4)})", flush=True)
    print("[play] 끝" + (" — 처음부터 반복" if args.loop else " (창을 닫으면 종료)"), flush=True)
    if args.quit:
        break
    if not args.loop:
        while app.is_running():
            world.step(render=not args.headless)
        break
app.close()
