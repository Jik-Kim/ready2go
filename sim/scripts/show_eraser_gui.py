"""GUI 에서 직접 확인하기 (담당 A): 씬을 열고, 로봇을 drawer_top_view 자세로 보내고, 서랍을 최대 인출로 열고,
서랍 안에 지우개 크기 직육면체를 임의 위치·방향으로 놓은 뒤 뷰포트를 손목 카메라로 바꾼다. 씬 파일은 저장하지 않는다.

실행 (Isaac Sim 이 떠 있으면 먼저 끈다):
  cd <저장소> && bash sim/run_isaac.sh --/isaac/startup/ros_bridge_extension=isaacsim.ros2.bridge --exec sim/scripts/show_eraser_gui.py
환경변수: READY2GO_SEED(기본 0, 바꾸면 다른 위치), READY2GO_MARGIN(벽에서 최소 거리 m, 기본 0.04), READY2GO_SCENE(씬 파일)
창이 뜨면 자동으로 재생(Play)된다. 다른 위치를 보려면 Stop(■) 후 이 스크립트를 SEED만 바꿔 다시 실행한다.
콘솔(터미널)에 정답(서랍 좌표 x, y, yaw)이 출력된다. 뷰포트 카메라는 위쪽 `Perspective` 메뉴에서 다시 바꿀 수 있다.
"""
import asyncio
import math
import os
from pathlib import Path

import numpy as np
import omni.kit.app
import omni.timeline
import omni.usd
import yaml
from pxr import Gf, UsdGeom

ROOT = Path(os.environ.get("READY2GO_ROOT", Path(__file__).resolve().parents[2]))
SCENE = Path(os.environ.get("READY2GO_SCENE", ROOT / "sim/scenes/ready2go_t1.usd"))
PLACES = yaml.safe_load((ROOT / "config/places.yaml").read_text(encoding="utf-8"))
POSES = yaml.safe_load((ROOT / "config/poses.yaml").read_text(encoding="utf-8"))
WORLD = yaml.safe_load((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))
CAM = "/World/m0609/link_6/wrist_cam_link/color_optical_frame/color_camera"


def quat_to_R(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


async def main():
    app = omni.kit.app.get_app()
    ctx = omni.usd.get_context()
    await ctx.open_stage_async(str(SCENE))
    for _ in range(10):
        await app.next_update_async()
    stage = ctx.get_stage()
    q_view = POSES["drawer_top_view"]["drawer_top"]
    for i, q in enumerate(q_view, 1):                                    # 구동 목표(도)와 초기 상태를 같은 값으로
        prim = stage.GetPrimAtPath(f"/World/m0609/joints/joint_{i}")
        prim.GetAttribute("drive:angular:physics:targetPosition").Set(float(q))
        prim.GetAttribute("state:angular:physics:position").Set(float(q))
    travel = PLACES["drawer_top"]["max_travel_m"]
    stage.GetPrimAtPath("/World/workspace/cabinet/drawer_top_joint").GetAttribute("drive:linear:physics:targetPosition").Set(float(travel))

    tf = PLACES["drawer_top"]["tf"]
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = quat_to_R(tf["quaternion_xyzw"]), tf["translation_m"]
    interior = PLACES["drawer_top"]["interior_m"]
    size = WORLD.get("world", WORLD)["items"]["eraser"]["size_m"]
    rng = np.random.default_rng(int(os.environ.get("READY2GO_SEED", "0")))
    margin = float(os.environ.get("READY2GO_MARGIN", "0.04"))
    cx, cy = rng.uniform(margin, interior[0] - margin), rng.uniform(margin, interior[1] - margin)
    yaw = float(rng.uniform(-math.pi, math.pi))
    pw = (T @ np.array([cx, cy, size[2] / 2, 1.0]))[:3]
    cube = UsdGeom.Cube.Define(stage, "/World/eraser_test")
    cube.CreateSizeAttr(1.0)
    cube.GetDisplayColorAttr().Set([Gf.Vec3f(0.92, 0.92, 0.95)])
    xf = UsdGeom.Xformable(cube.GetPrim())
    xf.ClearXformOpOrder()
    xf.AddTranslateOp().Set(Gf.Vec3d(*[float(v) for v in pw]))
    xf.AddRotateZOp().Set(float(math.degrees(math.atan2(T[1, 0], T[0, 0]) + yaw)))
    xf.AddScaleOp().Set(Gf.Vec3f(*size))
    ny = ((yaw + math.pi / 2) % math.pi) - math.pi / 2
    print(f"[show] 지우개 정답(서랍 좌표): x {cx:.3f} m, y {cy:.3f} m, yaw {ny:+.3f} rad ({math.degrees(ny):+.0f}°), 높이 {size[2] * 1000:.1f} mm "
          f"(서랍 내부 {interior[0]:.3f} × {interior[1]:.3f} m, seed {os.environ.get('READY2GO_SEED', '0')})", flush=True)
    try:
        from omni.kit.viewport.utility import get_active_viewport
        vp = get_active_viewport()
        if vp:
            vp.camera_path = CAM
            print("[show] 뷰포트를 손목 카메라로 바꿨습니다", flush=True)
    except Exception as e:                                               # 헤드리스·창 없음이면 건너뜀
        print(f"[show] 뷰포트 카메라 전환 건너뜀: {e}", flush=True)
    if not os.environ.get("READY2GO_NO_PLAY"):
        omni.timeline.get_timeline_interface().play()
    if os.environ.get("READY2GO_TEST_QUIT"):                              # 자동 시험용: 몇 프레임 뒤 종료
        for _ in range(240):
            await app.next_update_async()
        got = [stage.GetPrimAtPath(f"/World/m0609/joints/joint_{i}").GetAttribute("state:angular:physics:position").Get() for i in range(1, 7)]
        print(f"[show] 시험: 재생 후 관절(도) {np.round(got, 2)}", flush=True)
        app.post_quit()


asyncio.ensure_future(main())
