"""T1 씬 생성 (담당 A): 작업대 + 받침 선반 + 3단 서랍장(맨 위 단 Prismatic Joint) + M0609/RG2 + 손목 카메라.

실행: ~/isaac-sim-5.1.0/python.sh sim/scripts/build_scene.py  →  sim/scenes/ready2go_t1.usd
검증: ~/isaac-sim-5.1.0/python.sh sim/scripts/verify_scene.py

- 형상 치수는 sim/drawer_dimensions.yaml 에서 읽는다 (값은 그 파일에만 둔다).
- 카메라 변환은 config/calibration/calibration_meta.yaml 의 derived_tf·driver_tf_used 에서 읽는다 (잠정 채택 값).
- 월드 = 로봇 base_link. 로봇은 원점에 두고(루트 고정 관절의 기준점이 월드에 고정되어 있어 옮기면 어긋남),
  작업대·서랍장은 /World/workspace 아래에 둔다. 로봇 base_link와 작업대 변의 각도는 미확인이라 WORKSPACE_YAW_DEG 로 둔다.
- 서랍의 로봇 기준 정확한 위치는 #6(3점 터치) 결과로 교체한다. 여기 값은 평면도 기준 초기 배치다.
"""
import math
from pathlib import Path

import numpy as np
import yaml
from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DIM = yaml.safe_load((ROOT / "sim/drawer_dimensions.yaml").read_text(encoding="utf-8"))
CAL = yaml.safe_load((ROOT / "config/calibration/calibration_meta.yaml").read_text(encoding="utf-8"))
OUT = ROOT / "sim/scenes/ready2go_t1.usd"
ROBOT_REL = "../assets/m0609_camera_cube/m0609_camera_cube.usd"

CM = 0.01
# ---- 미측정 값(전부 [추정]). 측정되면 sim/drawer_dimensions.yaml 로 옮긴다 -------------------------------------------
WORKSPACE_YAW_DEG = 0.0      # [미확인] 로봇 base_link x축과 작업대 긴 변의 각도. #6 결과로 교체
TABLE_THICKNESS = 0.03       # [추정]
SHELF_MARGIN = 0.02          # [추정] 받침 선반이 서랍장보다 사방으로 더 나온 길이
SHELF_THICKNESS = 0.01       # [추정]
SIDE_WALL = 0.0025           # 서랍 트레이 옆벽: (외곽 폭 26.5 - 내부 폭 26) / 2  [계산]
FRONT_BACK_WALL = 0.0015     # 앞/뒤벽: (외곽 깊이 20.8 - 내부 깊이 20.5) / 2  [계산, 앞뒤를 같게 가정]
TRAY_FLOOR = 0.004           # [추정]
SHELL_FLOOR = 0.005          # [추정] 트레이 아래 바닥 판 (단 높이 7.5 = 0.5 + 6.1 + 0.9)
SHELL_CEIL = 0.009           # [추정]
HANDLE_PROTRUSION = 0.015    # [추정] 손잡이가 앞면에서 튀어나온 길이 (미측정)
TRAY_MASS = 0.3              # [추정] kg


def to_gf(T):
    """numpy 4x4(열벡터 규약) → Gf.Matrix4d(USD 행벡터 규약)"""
    return Gf.Matrix4d(np.asarray(T, dtype=float).T.tolist())


def pose(t, q_xyzw=None, R=None):
    T = np.eye(4)
    if q_xyzw is not None:
        x, y, z, w = q_xyzw
        n = math.sqrt(x * x + y * y + z * z + w * w)
        x, y, z, w = x / n, y / n, z / n, w / n
        R = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ])
    if R is not None:
        T[:3, :3] = R
    T[:3, 3] = t
    return T


def set_xform(prim, T):
    UsdGeom.Xformable(prim).ClearXformOpOrder()
    UsdGeom.Xformable(prim).AddTransformOp().Set(to_gf(T))


def xform(stage, path, T=None):
    p = UsdGeom.Xform.Define(stage, path).GetPrim()
    if T is not None:
        set_xform(p, T)
    return p


def box(stage, path, size, center, color, collide=True):
    """size=(x,y,z) m, center=(x,y,z) m (부모 기준)"""
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(1.0)
    prim = cube.GetPrim()
    xf = UsdGeom.Xformable(prim)
    xf.AddTranslateOp().Set(Gf.Vec3d(*center))
    xf.AddScaleOp().Set(Gf.Vec3f(*size))
    cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    if collide:
        UsdPhysics.CollisionAPI.Apply(prim)
    return prim


def build():
    u = DIM["drawer_unit"]
    top = DIM["drawer_top"]
    pv = DIM["plan_view_cm"]
    tb = DIM["table"]

    # ---------- 평면도 → 작업대 좌표계 W (원점 = 로봇 베이스 철판 중심, 작업대 윗면 z=0, +x 긴 변 오른쪽, +y 서랍 반대쪽) ----------
    plate_w, plate_d = pv["robot_base_plate_cm"]["width"], pv["robot_base_plate_cm"]["depth"]
    x_left = -(pv["robot_base_left_gap_to_table_left"] + plate_w / 2) * CM
    x_right = x_left + tb["width_cm"] * CM
    y_top = (pv["robot_base_gap_to_table_top_edge"] + plate_d / 2) * CM
    y_bottom = -(pv["robot_base_gap_to_table_bottom_edge"] + plate_d / 2) * CM
    assert abs((y_top - y_bottom) - tb["depth_cm"] * CM) < 1e-6, "도면의 21+23+21 이 작업대 깊이와 맞지 않음"

    cab_w, cab_d = u["width_cm"] * CM, u["depth_cm"] * CM
    cab_x0 = x_left + pv["drawer_left_edge_to_table_left"] * CM
    cab_x1 = cab_x0 + cab_w
    assert abs((x_right - cab_x1) - pv["drawer_right_edge_to_table_right"] * CM) < 1e-6, "도면의 서랍 좌우 치수가 맞지 않음"
    cab_xc = (cab_x0 + cab_x1) / 2
    y_front = y_bottom - pv["drawer_front_to_table_edge_gap"] * CM   # 앞면(로봇 쪽) y. 0.4cm는 간격으로 가정 [확인 필요]
    cab_yc = y_front - cab_d / 2

    z_seat = DIM["drawer_unit"].get("seat_top_vs_table_surface_cm", -0.3) * CM
    total_h = u["total_height_cm"] * CM
    z_t3_bottom = z_seat + top["front_bottom_height_above_seat_cm"] * CM
    t3_h = z_seat + total_h - z_t3_bottom
    lower_h = (z_t3_bottom - z_seat) / 2           # 아래 두 단은 같은 높이로 가정 [거친 추정]

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World").GetPrim()
    stage.SetDefaultPrim(world)
    stage.GetRootLayer().documentation = (
        "ready2go T1 씬. sim/scripts/build_scene.py 로 생성(수정하지 말고 스크립트를 고친다). "
        "치수: sim/drawer_dimensions.yaml, 카메라: config/calibration/calibration_meta.yaml. 월드=로봇 base_link."
    )

    # ---------- 물리 장면, 조명 ----------
    ps = UsdPhysics.Scene.Define(stage, "/World/physicsScene")
    ps.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
    ps.CreateGravityMagnitudeAttr(9.81)
    UsdLux.DistantLight.Define(stage, "/World/Lights/sun").CreateIntensityAttr(2500)
    UsdLux.DomeLight.Define(stage, "/World/Lights/dome").CreateIntensityAttr(600)

    # ---------- 로봇 (참조) ----------
    robot = stage.DefinePrim("/World/m0609")
    robot.GetReferences().AddReference(ROBOT_REL, "/World/m0609")

    # ---------- 손목 카메라: link_6 → wrist_cam_link → color_optical → USD 카메라 ----------
    d = CAL["derived_tf"]
    drv = CAL["driver_tf_used"]
    T_l6_cl = pose(d["translation_m"], q_xyzw=d["quaternion_xyzw"])
    T_cl_opt = pose(drv["translation_m"], q_xyzw=drv["quaternion_xyzw"])
    Rx180 = np.diag([1.0, -1.0, -1.0])                         # OpenCV 광학(z 앞, y 아래) → USD 카메라(-z 앞, y 위)
    l6 = stage.OverridePrim("/World/m0609/link_6")
    cl = xform(stage, "/World/m0609/link_6/wrist_cam_link", T_l6_cl)
    xform(stage, "/World/m0609/link_6/wrist_cam_link/color_optical_frame", T_cl_opt)
    cam = UsdGeom.Camera.Define(stage, "/World/m0609/link_6/wrist_cam_link/color_optical_frame/color_camera")
    set_xform(cam.GetPrim(), pose([0, 0, 0], R=Rx180))
    cam.GetHorizontalApertureAttr().Set(20.955)
    cam.GetVerticalApertureAttr().Set(20.955 * 720 / 1280)
    cam.GetFocalLengthAttr().Set(20.955 / (2 * math.tan(math.radians(69.4 / 2))))  # D435i 컬러 가로 FOV 약 69.4° [추정, 카탈로그]
    cam.GetClippingRangeAttr().Set(Gf.Vec2f(0.05, 5.0))
    cl.SetCustomDataByKey("source", "config/calibration/calibration_meta.yaml derived_tf (잠정 채택)")

    # ---------- 작업대 좌표계 ----------
    ws = xform(stage, "/World/workspace", pose([0, 0, 0], R=np.array([
        [math.cos(math.radians(WORKSPACE_YAW_DEG)), -math.sin(math.radians(WORKSPACE_YAW_DEG)), 0],
        [math.sin(math.radians(WORKSPACE_YAW_DEG)), math.cos(math.radians(WORKSPACE_YAW_DEG)), 0],
        [0, 0, 1]])))
    ws.SetCustomDataByKey("note", "WORKSPACE_YAW_DEG 미확인. 서랍 위치는 #6 결과로 교체")
    box(stage, "/World/workspace/table", (x_right - x_left, y_top - y_bottom, TABLE_THICKNESS),
        ((x_left + x_right) / 2, (y_top + y_bottom) / 2, -TABLE_THICKNESS / 2), (0.80, 0.68, 0.47))
    box(stage, "/World/workspace/robot_base_plate", (plate_w * CM, plate_d * CM, 0.005), (0, 0, 0.0025), (0.7, 0.7, 0.72))
    box(stage, "/World/workspace/shelf", (cab_w + 2 * SHELF_MARGIN, cab_d + 2 * SHELF_MARGIN, SHELF_THICKNESS),
        (cab_xc, cab_yc, z_seat - SHELF_THICKNESS / 2), (0.92, 0.92, 0.92))

    # ---------- 서랍장 ----------
    cab = xform(stage, "/World/workspace/cabinet", pose([cab_xc, cab_yc, 0]))
    white = (0.95, 0.95, 0.93)
    for name, z0 in (("tier1_base", z_seat), ("tier2_drawer_bottom", z_seat + lower_h)):
        box(stage, f"/World/workspace/cabinet/{name}", (cab_w, cab_d, lower_h), (0, 0, z0 + lower_h / 2), white)
    # tier2 앞면 손잡이(닫힌 채 고정, Phase 3)
    box(stage, "/World/workspace/cabinet/tier2_drawer_bottom_handle", (0.02, HANDLE_PROTRUSION, 0.02),
        (0, cab_d / 2 + HANDLE_PROTRUSION / 2, z_seat + lower_h + lower_h / 2), (0.85, 0.85, 0.83), collide=True)

    # 맨 위 단: shell(고정) + tray(Prismatic)
    z3c = z_t3_bottom + t3_h / 2                              # 단 중심 높이
    shell = xform(stage, "/World/workspace/cabinet/drawer_top_shell", pose([0, 0, z3c]))
    UsdPhysics.RigidBodyAPI.Apply(shell).CreateKinematicEnabledAttr(True)
    box(stage, "/World/workspace/cabinet/drawer_top_shell/floor_slab", (cab_w, cab_d, SHELL_FLOOR),
        (0, 0, -t3_h / 2 + SHELL_FLOOR / 2), white)
    box(stage, "/World/workspace/cabinet/drawer_top_shell/ceiling_slab", (cab_w, cab_d, SHELL_CEIL),
        (0, 0, t3_h / 2 - SHELL_CEIL / 2), white)

    int_w, int_d, int_h = top["interior_cm"]["width"] * CM, top["interior_cm"]["depth"] * CM, top["interior_cm"]["height"] * CM
    tray_h = TRAY_FLOOR + int_h
    tray_zc = -t3_h / 2 + SHELL_FLOOR + tray_h / 2           # shell 좌표계에서 트레이 중심 z
    tray = xform(stage, "/World/workspace/cabinet/drawer_top_tray", pose([0, 0, z3c + tray_zc]))
    UsdPhysics.RigidBodyAPI.Apply(tray)
    UsdPhysics.MassAPI.Apply(tray).CreateMassAttr(TRAY_MASS)
    p = "/World/workspace/cabinet/drawer_top_tray"
    out_w = int_w + 2 * SIDE_WALL
    box(stage, f"{p}/floor", (out_w, cab_d, TRAY_FLOOR), (0, 0, -tray_h / 2 + TRAY_FLOOR / 2), white)
    for sgn, nm in ((-1, "wall_left"), (1, "wall_right")):
        box(stage, f"{p}/{nm}", (SIDE_WALL, cab_d, tray_h), (sgn * (int_w / 2 + SIDE_WALL / 2), 0, 0), white)
    box(stage, f"{p}/wall_back", (int_w, FRONT_BACK_WALL, tray_h), (0, -cab_d / 2 + FRONT_BACK_WALL / 2, 0), white)
    panel_h = t3_h                                            # 앞 패널은 단 전체 높이 (측정: 맨 위 단 약 7.5 cm)
    panel_zc = (-t3_h / 2 + t3_h / 2) - tray_zc               # shell 중심 높이 - 트레이 중심 높이
    box(stage, f"{p}/front_panel", (cab_w, FRONT_BACK_WALL, panel_h), (0, cab_d / 2 - FRONT_BACK_WALL / 2, panel_zc), white)
    box(stage, f"{p}/handle", (0.02, HANDLE_PROTRUSION, 0.02),
        (0, cab_d / 2 + HANDLE_PROTRUSION / 2, panel_zc), (0.85, 0.85, 0.83))
    UsdGeom.Xformable(stage.GetPrimAtPath(f"{p}/handle")).GetPrim().SetCustomDataByKey(
        "note", "손잡이 크기 2cm·돌출 길이는 미측정 [추정]. 위아래로 잡는 곡면 탭을 박스로 단순화")

    # 트레이는 shell과 겹치므로 둘 사이 충돌은 끈다
    fp = UsdPhysics.FilteredPairsAPI.Apply(tray)
    for nm in ("floor_slab", "ceiling_slab"):
        fp.CreateFilteredPairsRel().AddTarget(Sdf.Path(f"/World/workspace/cabinet/drawer_top_shell/{nm}"))
    fp.CreateFilteredPairsRel().AddTarget(Sdf.Path("/World/workspace/cabinet/drawer_top_shell"))

    # Prismatic Joint: 축 = 트레이 로컬 +y(작업대 쪽으로 당김), 0 ~ max_travel
    travel = top["max_travel_cm"] * CM
    jt = UsdPhysics.PrismaticJoint.Define(stage, "/World/workspace/cabinet/drawer_top_joint")
    jt.CreateBody0Rel().AddTarget(Sdf.Path("/World/workspace/cabinet/drawer_top_shell"))
    jt.CreateBody1Rel().AddTarget(Sdf.Path(p))
    jt.CreateAxisAttr("Y")
    jt.CreateLocalPos0Attr(Gf.Vec3f(0, 0, tray_zc))
    jt.CreateLocalPos1Attr(Gf.Vec3f(0, 0, 0))
    jt.CreateLocalRot0Attr(Gf.Quatf(1, 0, 0, 0))
    jt.CreateLocalRot1Attr(Gf.Quatf(1, 0, 0, 0))
    jt.CreateLowerLimitAttr(0.0)
    jt.CreateUpperLimitAttr(travel)
    drv_api = UsdPhysics.DriveAPI.Apply(jt.GetPrim(), "linear")
    drv_api.CreateTypeAttr("force")
    drv_api.CreateStiffnessAttr(2000.0)
    drv_api.CreateDampingAttr(200.0)
    drv_api.CreateMaxForceAttr(100.0)
    drv_api.CreateTargetPositionAttr(0.0)
    jt.GetPrim().SetCustomDataByKey("note", "max_travel 17cm 실측(A, 10/02). 닫힘=0")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    stage.GetRootLayer().Export(str(OUT))
    print(f"[build] 저장: {OUT}")
    print(f"[build] 작업대 x[{x_left:.3f},{x_right:.3f}] y[{y_bottom:.3f},{y_top:.3f}]  서랍장 x[{cab_x0:.3f},{cab_x1:.3f}] 앞면 y={y_front:.3f}")
    print(f"[build] 맨 위 단: 바닥 z={z_t3_bottom:.4f} 높이 {t3_h:.4f}  인출 한계 {travel:.3f} m")


build()
app.close()
