"""트윈 씬에서 비전 시험 데이터를 만든다 (담당 A): 손목 카메라를 drawer_top_view 자세에 두고, 서랍(최대 인출) 안에
지우개 크기 직육면체를 임의 위치·방향으로 놓아 컬러·뎁스를 저장한다. 정답(서랍 좌표 위치·yaw·높이)과 카메라 정보를 함께 남긴다.

실행: ISAAC_SIM_CMD=$HOME/isaac-sim-5.1.0/python.sh bash sim/run_isaac.sh sim/scripts/render_eraser_test.py [--n 20] [--seed 0] [--out <폴더>]
  (GUI 가 아니라 headless 로 렌더링만 한다. Isaac 은 한 번에 한 프로세스만, 이 스크립트는 씬 파일을 바꾸지 않는다)
결과 <out>/ : NNNN_color.png, NNNN_depth.npy (z-거리 m, 이상적 센서 — 노이즈·결손 없음), truth.json (카메라·정답)
판정은 이 데이터를 tools/dev/eval_inspect_sim.py 가 inspect_region 코어에 넣어 정답과 비교한다.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import yaml
from isaacsim import SimulationApp

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=20)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--out", default="sim_render_out")
ap.add_argument("--margin", type=float, default=0.04, help="물체 중심이 서랍 벽에서 최소 이만큼(m) 떨어지게. 벽 가까이 시험은 0.03")
args, _ = ap.parse_known_args()
app = SimulationApp({"headless": True})

import omni.replicator.core as rep  # noqa: E402
import omni.usd  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import SingleArticulation  # noqa: E402
from isaacsim.core.utils.types import ArticulationAction  # noqa: E402
from pxr import Gf, Usd, UsdGeom, UsdPhysics  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCENE = Path(os.environ.get("READY2GO_SCENE", ROOT / "sim/scenes/ready2go_t1.usd"))
PLACES = yaml.safe_load(Path(os.environ.get("READY2GO_PLACES", ROOT / "config/places.yaml")).read_text(encoding="utf-8"))
POSES = yaml.safe_load((ROOT / "config/poses.yaml").read_text(encoding="utf-8"))
WORLD = yaml.safe_load((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dims import quat_to_R  # noqa: E402

CAM = "/World/m0609/link_6/wrist_cam_link/color_optical_frame/color_camera"
OUT = Path(args.out)
OUT.mkdir(parents=True, exist_ok=True)
omni.usd.get_context().open_stage(str(SCENE))
stage = omni.usd.get_context().get_stage()
for _ in range(10):
    app.update()


def world_T(path):
    m = UsdGeom.Xformable(stage.GetPrimAtPath(path)).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    return np.array(m).T


tf = PLACES["drawer_top"]["tf"]
T_base_drawer = np.eye(4)
T_base_drawer[:3, :3] = np.array(quat_to_R(tf["quaternion_xyzw"]))
T_base_drawer[:3, 3] = tf["translation_m"]
interior = PLACES["drawer_top"]["interior_m"]
travel = PLACES["drawer_top"]["max_travel_m"]
size = WORLD.get("world", WORLD)["items"]["eraser"]["size_m"]            # [긴 변, 짧은 변, 높이]
q_view = POSES["drawer_top_view"]["drawer_top"]

world = World(stage_units_in_meters=1.0, physics_dt=1 / 120.0, rendering_dt=1 / 60.0)
world.reset()
root_path = next(str(p.GetPath()) for p in stage.Traverse()
                 if str(p.GetPath()).startswith("/World/m0609") and p.HasAPI(UsdPhysics.ArticulationRootAPI))
robot = SingleArticulation(prim_path=root_path, name="m0609")
robot.initialize()
names = list(robot.dof_names)
idx = [names.index(f"joint_{i}") for i in range(1, 7)]
target = np.radians(q_view)
robot.set_joint_positions(target, joint_indices=idx)
robot.get_articulation_controller().apply_action(ArticulationAction(joint_positions=target, joint_indices=idx))
stage.GetPrimAtPath("/World/workspace/cabinet/drawer_top_joint").GetAttribute("drive:linear:physics:targetPosition").Set(float(travel))
for _ in range(480):
    world.step(render=False)
got = np.degrees(robot.get_joint_positions()[idx])
print(f"[render] 관절 목표 {np.round(q_view, 3)} → 실제 {np.round(got, 3)} (최대 차이 {np.abs(got - np.array(q_view)).max():.3f}°)", flush=True)

# 카메라: USD 카메라(-z 앞) → OpenCV 광학(z 앞, y 아래)
cam = UsdGeom.Camera(stage.GetPrimAtPath(CAM))
W, H = 1280, 720
fl, ha, va = cam.GetFocalLengthAttr().Get(), cam.GetHorizontalApertureAttr().Get(), cam.GetVerticalApertureAttr().Get()
K = dict(fx=fl / ha * W, fy=fl / va * H, cx=W / 2, cy=H / 2)
T_base_cam = world_T(CAM) @ np.diag([1.0, -1.0, -1.0, 1.0])              # 월드 = 로봇 base_link
print(f"[render] 카메라 서랍 좌표 위치 {np.round((np.linalg.inv(T_base_drawer) @ T_base_cam)[:3, 3], 4)} 내부 파라미터 {K}", flush=True)

cube = UsdGeom.Cube.Define(stage, "/World/eraser_test")
cube.CreateSizeAttr(1.0)
cube.GetDisplayColorAttr().Set([Gf.Vec3f(0.92, 0.92, 0.95)])
xf = UsdGeom.Xformable(cube.GetPrim())
xf.ClearXformOpOrder()
op_t, op_r, op_s = xf.AddTranslateOp(), xf.AddRotateZOp(), xf.AddScaleOp()      # 월드 좌표 직접 지정(부모 없음)
op_s.Set(Gf.Vec3f(size[0], size[1], size[2]))
rp = rep.create.render_product(CAM, (W, H))
rgb_a, dep_a = rep.AnnotatorRegistry.get_annotator("rgb"), rep.AnnotatorRegistry.get_annotator("distance_to_image_plane")
rgb_a.attach([rp]); dep_a.attach([rp])

rng = np.random.default_rng(args.seed)
margin = args.margin
truth = {"K": K, "T_base_cam": T_base_cam.tolist(), "T_base_drawer": T_base_drawer.tolist(), "size_m": size, "interior_m": interior, "samples": []}
for i in range(args.n):
    cx, cy = rng.uniform(margin, interior[0] - margin), rng.uniform(margin, interior[1] - margin)
    yaw = float(rng.uniform(-math.pi, math.pi))
    p = (T_base_drawer @ np.array([cx, cy, size[2] / 2, 1.0]))[:3]       # 서랍 좌표 → 월드(base_link)
    drawer_yaw = math.atan2(T_base_drawer[1, 0], T_base_drawer[0, 0])
    op_t.Set(Gf.Vec3d(*[float(v) for v in p]))
    op_r.Set(float(math.degrees(drawer_yaw + yaw)))                      # 서랍이 z축으로만 돌아 있다는 가정 [서랍 tf 의 기울기 0.5° 이하라 무시]
    for _ in range(6):
        app.update()
    rep.orchestrator.step(rt_subframes=4, delta_time=0.0)
    rgb, dep = rgb_a.get_data(), dep_a.get_data()
    import cv2  # noqa: E402
    cv2.imwrite(str(OUT / f"{i:04d}_color.png"), cv2.cvtColor(np.asarray(rgb)[:, :, :3], cv2.COLOR_RGB2BGR))
    np.save(OUT / f"{i:04d}_depth.npy", np.asarray(dep, dtype=np.float32))
    ny = ((yaw + math.pi / 2) % math.pi) - math.pi / 2                    # (-pi/2, pi/2]
    ny = math.pi / 2 if abs(ny + math.pi / 2) < 1e-9 else ny
    truth["samples"].append({"i": i, "position": [cx, cy, 0.0], "yaw": ny, "top_z": size[2]})
    print(f"[render] {i:04d} 정답 x {cx:.3f} y {cy:.3f} yaw {ny:+.3f}  뎁스 유효 {float(np.isfinite(dep).mean()):.2f}", flush=True)
(OUT / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"[render] 완료 {args.n}장 → {OUT.resolve()}", flush=True)
app.close()
