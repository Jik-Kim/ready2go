"""GUI 에서 B 스킬 흐름의 로봇 궤적을 재생한다 (담당 A, 트윈 사전 검증). 씬 파일은 저장하지 않는다.

먼저 궤적을 만든다 (로봇·Isaac 없이, B 코드가 있는 저장소에서):
  python3 sim/motion_check/trace_skill_flow.py --repo <B 저장소> --out /tmp/trace.json
재생 (Isaac Sim 이 떠 있으면 먼저 끈다):
  READY2GO_TRACE=/tmp/trace.json bash sim/run_isaac.sh --exec sim/scripts/play_motion_trace.py
환경변수
  READY2GO_TRACE     궤적 파일 (필수)
  READY2GO_SPEED     재생 배속 (기본 1.0 = 스킬 파라미터 속도, 관절 이동은 20°/s)
  READY2GO_SEGMENTS  재생할 구간 번호 (예: "8-10,15-22", 기본 전부). 구간 번호는 trace_skill_flow.py 표의 # 열
  READY2GO_FLAG_SLOW 특이점 근처(◀) 구간만 이만큼 느리게 (기본 1.0 = 같은 속도)
  READY2GO_LOOP      1 이면 끝나면 처음부터 반복
화면: ◀ 구간 동안 손끝에 빨간 공이 뜨고, 터미널에 구간 이름·손끝 10 mm당 관절 변화·J3 를 출력한다.
궤적은 기하(IK)로 계산한 것이라 두산 제어기의 실제 보간·특이점 처리와 다를 수 있다 [추정]. 서랍·지우개 움직임은 흉내다.
"""
import asyncio
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import omni.kit.app
import omni.timeline
import omni.usd
import yaml
from pxr import Gf, UsdGeom

ROOT = Path(os.environ.get("READY2GO_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / "sim/motion_check"))
import m0609_kin as kin  # noqa: E402

SCENE = Path(os.environ.get("READY2GO_SCENE", ROOT / "sim/scenes/ready2go_t1.usd"))
TRACE = json.loads(Path(os.environ["READY2GO_TRACE"]).read_text(encoding="utf-8"))
SPEED = float(os.environ.get("READY2GO_SPEED", "1.0"))
FLAG_SLOW = float(os.environ.get("READY2GO_FLAG_SLOW", "1.0"))
JOINT_VEL = 20.0
DT = 1.0 / 60.0


def wanted(i):
    spec = os.environ.get("READY2GO_SEGMENTS", "").strip()
    if not spec:
        return True
    for part in spec.split(","):
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
    t = max(t, 0.2) / SPEED
    return t * (FLAG_SLOW if s.get("flag") else 1.0)


def gf_to_np(m):
    return np.array([[m[r][c] for c in range(4)] for r in range(4)]).T          # Gf 는 행벡터 규약


def np_to_gf(T):
    return Gf.Matrix4d(*[float(T[c][r]) for r in range(4) for c in range(4)])


async def main():
    app = omni.kit.app.get_app()
    ctx = omni.usd.get_context()
    await ctx.open_stage_async(str(SCENE))
    for _ in range(10):
        await app.next_update_async()
    stage = ctx.get_stage()
    repo = Path(TRACE["repo"])
    places = yaml.safe_load(((repo / "config/places.yaml") if (repo / "config/places.yaml").exists()
                             else ROOT / "config/places.yaml").read_text(encoding="utf-8"))
    world = json.loads((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))
    size = world.get("world", world)["items"]["eraser"]["size_m"]
    tf = places["drawer_top"]["tf"]
    T_bd = np.eye(4)
    T_bd[:3, :3], T_bd[:3, 3] = quat_to_R(tf["quaternion_xyzw"]), tf["translation_m"]
    max_travel = float(places["drawer_top"]["max_travel_m"])
    base_prim = stage.GetPrimAtPath("/World/m0609/base_link")
    if not base_prim.IsValid():
        base_prim = stage.GetPrimAtPath("/World/m0609")
    W = gf_to_np(UsdGeom.Xformable(base_prim).ComputeLocalToWorldTransform(0))
    joints = [stage.GetPrimAtPath(f"/World/m0609/joints/joint_{i}") for i in range(1, 7)]
    drawer = stage.GetPrimAtPath("/World/workspace/cabinet/drawer_top_joint").GetAttribute("drive:linear:physics:targetPosition")

    def eraser_world(pose, travel):                                      # 서랍 좌표 → 월드, 서랍이 덜 열렸으면 안쪽으로
        x, y = pose["position"][:2]
        T = np.eye(4)
        T[:3, :3] = quat_to_R(tf["quaternion_xyzw"]) @ kin._rz(pose["yaw"])
        T[:3, 3] = (T_bd @ np.array([x, y, size[2] / 2, 1.0]))[:3] + T_bd[:3, 0] * (max_travel - travel)
        return W @ T

    cube = UsdGeom.Cube.Define(stage, "/World/eraser_trace")
    cube.CreateSizeAttr(1.0)
    cube.GetDisplayColorAttr().Set([Gf.Vec3f(0.95, 0.85, 0.2)])
    cxf = UsdGeom.Xformable(cube.GetPrim())
    cxf.ClearXformOpOrder()
    c_op = cxf.AddTransformOp()
    marker = UsdGeom.Sphere.Define(stage, "/World/singularity_marker")
    marker.CreateRadiusAttr(0.03)
    marker.GetDisplayColorAttr().Set([Gf.Vec3f(1.0, 0.1, 0.1)])
    mxf = UsdGeom.Xformable(marker.GetPrim())
    mxf.ClearXformOpOrder()
    m_op = mxf.AddTranslateOp()
    UsdGeom.Imageable(marker.GetPrim()).MakeInvisible()

    def set_q(q, snap=False):
        for p, v in zip(joints, q):
            p.GetAttribute("drive:angular:physics:targetPosition").Set(float(v))
            if snap:
                p.GetAttribute("state:angular:physics:position").Set(float(v))

    def set_cube(T):
        S = np.diag([size[0], size[1], size[2], 1.0])
        c_op.Set(np_to_gf(T @ S))

    segs = [s for s in TRACE["segments"] if wanted(s["i"])]
    print(f"[play] 궤적 {len(TRACE['segments'])}구간 중 {len(segs)}구간 재생, B 코드 {TRACE.get('repo_sha') or TRACE['repo']}, "
          f"배속 {SPEED}, ◀ 구간 느리게 ×{FLAG_SLOW}", flush=True)
    ers0, ers1 = TRACE["eraser"]["pose"], (TRACE.get("eraser_after") or TRACE["eraser"])["pose"]
    omni.timeline.get_timeline_interface().play()
    while True:
        travel, held, rel = 0.0, False, None
        first = TRACE["segments"][segs[0]["i"]]
        for s in TRACE["segments"][: segs[0]["i"]]:                      # 앞 구간을 건너뛰면 서랍·지우개 상태를 맞춰 둠
            if s["stage"] == "pull":
                travel = max_travel
            if s["stage"] == "push":
                travel = 0.0
        set_q(first["joints"][0], snap=True)
        drawer.Set(float(travel))
        ers_pose = ers1 if any(s["stage"] == "drag" for s in TRACE["segments"][: segs[0]["i"]]) else ers0
        set_cube(eraser_world(ers_pose, travel))
        for _ in range(30):
            await app.next_update_async()
        for s in segs:
            flag = s.get("flag")
            print(f"[play] #{s['i']:2d} {s['step']:6s} {s['kind']} {s['stage']:22s} "
                  + (f"{s.get('dist_mm', 0):5.0f} mm {s.get('rot_deg', 0):4.0f}° 10mm당 관절 {s.get('amp_deg_per_10mm', 0):4.1f}° "
                     f"J3 최소 {s['min_abs_j3']:4.1f}°" if s["kind"] == "movel" else f"관절 이동 최대 {max(s['joint_travel_deg']):5.1f}°")
                  + ("  ◀ 특이점 근처" if flag else ""), flush=True)
            if flag:
                UsdGeom.Imageable(marker.GetPrim()).MakeVisible()
            q_all = s["joints"]
            n = max(1, int(duration(s) / DT))
            for k in range(n + 1):
                f = k / n
                qf = f * (len(q_all) - 1)
                a = int(math.floor(qf))
                b = min(a + 1, len(q_all) - 1)
                q = np.array(q_all[a]) + (np.array(q_all[b]) - np.array(q_all[a])) * (qf - a)
                set_q(q)
                T_tcp = W @ kin.fk(q)
                m_op.Set(Gf.Vec3d(*[float(v) for v in T_tcp[:3, 3]]))
                if s["stage"] == "pull":
                    travel = min(max_travel, f * s.get("dist_mm", 0) / 1000.0)
                elif s["stage"] == "push":
                    d = s.get("dist_mm", 0) / 1000.0
                    travel = min(max_travel, max(0.0, max_travel - max(0.0, f * d - (d - max_travel))))
                drawer.Set(float(travel))
                if s["stage"] == "drag":
                    pose = {"position": [ers0["position"][i] + (ers1["position"][i] - ers0["position"][i]) * f for i in range(3)],
                            "yaw": ers1["yaw"]}
                    set_cube(eraser_world(pose, travel))
                if s["step"] == "pick" and s["stage"] == "lift" and not held:  # 집기 뒤 들어 올릴 때부터 손에 붙임
                    held = True
                    rel = np.linalg.inv(T_tcp) @ eraser_world(ers1, travel)
                if held:
                    set_cube(T_tcp @ rel)
                await app.next_update_async()
            if s["step"] == "place" and s["stage"] == "lower":
                held = False
            UsdGeom.Imageable(marker.GetPrim()).MakeInvisible()
        print("[play] 끝" + (" — 처음부터 반복" if os.environ.get("READY2GO_LOOP") == "1" else " (Stop ■ 으로 멈춤)"), flush=True)
        if os.environ.get("READY2GO_LOOP") != "1":
            break
    if os.environ.get("READY2GO_TEST_QUIT"):
        app.post_quit()


asyncio.ensure_future(main())
