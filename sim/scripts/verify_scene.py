"""T1 씬 검증 (담당 A). build_scene.py 로 만든 sim/scenes/ready2go_t1.usd 를 헤드리스로 열어 확인한다.

실행: ~/isaac-sim-5.1.0/python.sh sim/scripts/verify_scene.py
확인: ① 구조(로봇·카메라·서랍·관절) ② 카메라 변환이 npy·TCP로 직접 계산한 값과 일치(USD 행렬·쿼터니언 규약 검증)
      ③ 서랍 Prismatic Joint 가동 범위 0~max_travel, 한계 초과 목표는 한계에서 멈춤, 다른 축 이동 없음 (서랍 치수가 비어 서랍장이 없으면 건너뜀) ④ 로봇이 중력에 무너지지 않음
판정은 마지막 줄 `[verify] 결과: 전부 통과` / `실패 [...]` 로 한다. (SimulationApp.close() 가 프로세스를 그 자리에서 끝내서 뒤의 sys.exit 이 실행되지 않으므로
프로세스 종료 코드는 항상 0 이다 [실측 10/03]. 자동 검사는 로그의 결과 줄을 찾아 판정할 것.)
"""
import os
import sys
from pathlib import Path

import numpy as np
import yaml
from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

import omni.usd  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from pxr import Gf, Usd, UsdGeom, UsdPhysics  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCENE = Path(os.environ.get("READY2GO_SCENE", ROOT / "sim/scenes/ready2go_t1.usd"))
CAL = yaml.safe_load((ROOT / "config/calibration/calibration_meta.yaml").read_text(encoding="utf-8"))
DIM = yaml.safe_load((ROOT / "sim/drawer_dimensions.yaml").read_text(encoding="utf-8"))
PLACES = yaml.safe_load(Path(os.environ.get("READY2GO_PLACES", ROOT / "config/places.yaml")).read_text(encoding="utf-8"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dims import cabinet_missing, drawer_frame_tf, drawer_pose_from_tray, quat_to_R  # noqa: E402
fails = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)
    if not ok:
        fails.append(name)


def world_T(stage, path):
    m = UsdGeom.Xformable(stage.GetPrimAtPath(path)).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    return np.array(m).T   # USD 행벡터 규약 → 열벡터 규약


omni.usd.get_context().open_stage(str(SCENE))
for _ in range(10):
    app.update()
stage = omni.usd.get_context().get_stage()

# ① 구조
missing = cabinet_missing(DIM, PLACES)     # build_scene.py 와 같은 규칙: 값이 비어 있으면 서랍장 없이 생성된다
has_cabinet = stage.GetPrimAtPath("/World/workspace/cabinet").IsValid()
need = ["/World/m0609/base_link", "/World/m0609/link_6", "/World/m0609/onrobot_rg2ft/gripper_body",
        "/World/m0609/link_6/wrist_cam_link/color_optical_frame/color_camera",
        "/World/workspace/table", "/World/physicsScene"]
if has_cabinet:
    if (PLACES.get("handover_zone") or {}).get("tf"):
        need += ["/World/workspace/handover_tray/floor"]
    need += ["/World/workspace/cabinet/shelf", "/World/workspace/cabinet/drawer_top_tray/handle", "/World/workspace/cabinet/drawer_top_joint",
             "/World/workspace/cabinet/drawer_bottom_tray/handle", "/World/workspace/cabinet/drawer_bottom_joint"]
elif missing:
    print("[SKIP] 서랍장 없음 — 서랍 값이 아직 비어 있어 의도적으로 생략된 상태입니다. 필요한 항목: " + "; ".join(missing), flush=True)
else:
    check("설정상 서랍장이 있어야 하는데 씬에 없음", False, "(서랍 값은 모두 채워져 있음 → build_scene.py 생성 오류, 씬을 다시 생성하세요)")
for p in need:
    check(f"prim 존재 {p}", stage.GetPrimAtPath(p).IsValid())
if has_cabinet:
    jt = UsdPhysics.PrismaticJoint(stage.GetPrimAtPath("/World/workspace/cabinet/drawer_top_joint"))
    travel = PLACES["drawer_top"]["max_travel_m"]   # 정본은 config/places.yaml
    # USD는 float32로 저장하므로 허용 오차를 1e-6 으로 둔다
    check("위 서랍 관절 한계 0~max_travel", abs(jt.GetUpperLimitAttr().Get() - travel) < 1e-6 and abs(jt.GetLowerLimitAttr().Get()) < 1e-9,
          f"(상한 {jt.GetUpperLimitAttr().Get():.3f} m, 실측 {travel:.3f} m)")

ho = (PLACES.get("handover_zone") or {}).get("tf")
if ho and stage.GetPrimAtPath("/World/workspace/handover_tray").IsValid():
    d_ho = float(np.linalg.norm(world_T(stage, "/World/workspace/handover_tray")[:3, 3] - np.array(ho["translation_m"])))
    check("전달 트레이 원점 = places.yaml handover_zone.tf", d_ho < 1e-3, f"(차이 {d_ho * 1000:.2f} mm)")

# ② 카메라 변환 검증: link_6 기준 color_optical = T_link6→TCP × T_gripper2camera (npy, mm→m)
N = np.load(ROOT / "config/calibration/T_gripper2camera.npy").copy()
N[:3, 3] /= 1000.0
tcp = CAL["tcp"]["offset_from_pendant"]
T_l6_tcp = np.eye(4)
T_l6_tcp[:3, 3] = [tcp["x"] / 1000, tcp["y"] / 1000, tcp["z"] / 1000]
expected = T_l6_tcp @ N
actual = np.linalg.inv(world_T(stage, "/World/m0609/link_6")) @ world_T(stage, "/World/m0609/link_6/wrist_cam_link/color_optical_frame")
dt = float(np.abs(actual[:3, 3] - expected[:3, 3]).max())
dr = float(np.degrees(np.arccos(np.clip((np.trace(actual[:3, :3].T @ expected[:3, :3]) - 1) / 2, -1, 1))))
check("카메라 광학 프레임 = npy×TCP 직접 계산", dt < 2e-5 and dr < 0.01, f"(평행이동 차이 {dt:.2e} m, 회전 차이 {dr:.4f}°)")
cam_w = world_T(stage, "/World/m0609/link_6/wrist_cam_link/color_optical_frame/color_camera")
opt_w = world_T(stage, "/World/m0609/link_6/wrist_cam_link/color_optical_frame")
rel = np.linalg.inv(opt_w) @ cam_w
check("USD 카메라 = 광학 프레임을 x축 180° 회전", np.allclose(rel[:3, :3], np.diag([1, -1, -1]), atol=1e-6))

# 작업대 배치 요약
for nm, path in ((("서랍장", "/World/workspace/cabinet"), ("트레이 손잡이", "/World/workspace/cabinet/drawer_top_tray/handle")) if has_cabinet else ()):
    print(f"[info] {nm} 월드 위치 (m): {np.round(world_T(stage, path)[:3, 3], 4)}", flush=True)

# ③④ 물리
world = World(stage_units_in_meters=1.0, physics_dt=1 / 120.0, rendering_dt=1 / 60.0)
world.reset()
l6 = "/World/m0609/link_6"
l6_0 = world_T(stage, l6)[:3, 3].copy()
if has_cabinet:
    in_d, in_w = PLACES["drawer_top"]["interior_m"][0], PLACES["drawer_top"]["interior_m"][1]
    for tag in ("top", "bottom"):                                  # 위·아래 서랍 각각: 가동 범위 + 최대 인출 상태 좌표계 = places.yaml tf
        key = f"drawer_{tag}"
        drive = stage.GetPrimAtPath(f"/World/workspace/cabinet/{key}_joint").GetAttribute("drive:linear:physics:targetPosition")
        tray = f"/World/workspace/cabinet/{key}_tray"
        t0 = world_T(stage, tray)[:3, 3].copy()
        axis = world_T(stage, tray)[:3, 1]                         # 서랍이 열리는 방향 = 상자 로컬 +y 의 월드 방향
        along = lambda d: float(d @ axis)                              # noqa: E731
        across = lambda d: float(np.linalg.norm(d - along(d) * axis))  # noqa: E731

        def run(target, steps=360):
            drive.Set(float(target))
            for _ in range(steps):
                world.step(render=False)
            return world_T(stage, tray)[:3, 3] - t0

        d0 = run(0.0, 120)
        check(f"[{tag}] 닫힘 유지 (목표 0)", np.abs(d0).max() < 1e-3, f"(이동 {np.round(d0 * 1000, 2)} mm)")
        d1 = run(travel)
        check(f"[{tag}] 목표 최대 인출 → 최대 거리만큼 인출", abs(along(d1) - travel) < 2e-3, f"(인출 방향 {along(d1) * 100:.2f} cm)")
        check(f"[{tag}] 다른 축 이동 없음", across(d1) < 1.5e-3, f"(인출 방향 밖으로 {across(d1) * 1000:.2f} mm)")
        tf = drawer_frame_tf(PLACES, key)
        if tf is None:
            print(f"[SKIP] [{tag}] 서랍 tf 일치 검사 — places.yaml {key}.tf 가 아직 null", flush=True)
        else:
            Tw = world_T(stage, tray)
            R_d, o_d = drawer_pose_from_tray(Tw[:3, :3].tolist(), Tw[:3, 3].tolist(), in_w, in_d)
            R_tf = np.array(quat_to_R(tf[1]))
            dp = float(np.linalg.norm(np.array(o_d) - np.array(tf[0])))
            dang = float(np.degrees(np.arccos(np.clip((np.trace(np.array(R_d).T @ R_tf) - 1) / 2, -1, 1))))
            check(f"[{tag}] 최대 인출 상태 서랍 좌표계 = places.yaml {key}.tf", dp < 1e-3 and dang < 0.1, f"(원점 차이 {dp * 1000:.3f} mm, 회전 차이 {dang:.4f}°)")
        d2 = run(travel + 0.10)
        check(f"[{tag}] 한계 초과 목표(최대 인출 + 10 cm)는 최대 인출에서 멈춤", abs(along(d2) - travel) < 2e-3, f"(인출 방향 {along(d2) * 100:.2f} cm)")
        d3 = run(0.0)
        check(f"[{tag}] 다시 닫힘", np.abs(d3).max() < 1.5e-3, f"(이동 {np.round(d3 * 1000, 2)} mm)")
else:
    for _ in range(360):   # 서랍이 없어도 로봇이 중력에 무너지지 않는지는 확인
        world.step(render=False)
l6_1 = world_T(stage, l6)[:3, 3]
check("로봇이 중력에 무너지지 않음 (link_6 위치 유지)", float(np.linalg.norm(l6_1 - l6_0)) < 5e-3,
      f"(변화 {np.linalg.norm(l6_1 - l6_0) * 1000:.2f} mm, 시작 {np.round(l6_0, 3)})")

print(f"[verify] 결과: {'전부 통과' if not fails else '실패 ' + str(fails)}", flush=True)
app.close()
sys.exit(1 if fails else 0)
