"""T1 씬 생성 (담당 A): 작업대 + (서랍 치수가 채워졌을 때만) 받침 선반 + 2단 서랍장(상자 2개 각각 Prismatic Joint) + M0609/RG2 + 손목 카메라.

실행: ~/isaac-sim-5.1.0/python.sh sim/scripts/build_scene.py  →  sim/scenes/ready2go_t1.usd
검증: ~/isaac-sim-5.1.0/python.sh sim/scripts/verify_scene.py

- 형상 치수는 sim/drawer_dimensions.yaml 에서 읽는다 (값은 그 파일에만 둔다). 서랍 내부 치수만 config/places.yaml 의 drawer_top.interior_m 에서 읽는다.
- 카메라 변환은 config/calibration/calibration_meta.yaml 의 derived_tf·driver_tf_used 에서 읽는다 (잠정 채택 값).
- 월드 = 로봇 base_link. 로봇은 원점에 두고(루트 고정 관절의 기준점이 월드에 고정되어 있어 옮기면 어긋남),
  작업대·서랍장은 /World/workspace 아래에 둔다. 로봇 base_link와 작업대 변의 각도는 미확인이라 WORKSPACE_YAW_DEG 로 둔다.
- 서랍의 로봇 기준 정확한 위치는 #6(3점 터치) 결과로 교체한다. 여기 값은 평면도 기준 초기 배치다.
"""
import math
import sys
from pathlib import Path

import numpy as np
import yaml
from isaacsim import SimulationApp

app = SimulationApp({"headless": True})

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DIM = yaml.safe_load((ROOT / "sim/drawer_dimensions.yaml").read_text(encoding="utf-8"))
CAL = yaml.safe_load((ROOT / "config/calibration/calibration_meta.yaml").read_text(encoding="utf-8"))
PLACES = yaml.safe_load((ROOT / "config/places.yaml").read_text(encoding="utf-8"))
OUT = ROOT / "sim/scenes/ready2go_t1.usd"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dims import cabinet_missing  # noqa: E402
ROBOT_REL = "../assets/m0609_camera_cube/m0609_camera_cube.usd"

CM = 0.01
# ---- 미측정 값(전부 [추정]). 측정되면 sim/drawer_dimensions.yaml 로 옮긴다 -------------------------------------------
WORKSPACE_YAW_DEG = 0.0      # [미확인] 로봇 base_link x축과 작업대 긴 변의 각도. #6 결과로 교체
TABLE_THICKNESS = 0.03       # [추정]
SHELF_MARGIN = 0.02          # [추정] 받침 선반이 서랍장보다 사방으로 더 나온 길이
SHELF_THICKNESS = 0.01       # [추정]
FLOOR_T = 0.01               # [추정] 서랍 상자 바닥판 두께 (안쪽 바닥면 아래)
TRAY_MASS = 1.5              # [추정] kg. 원목 상자 + 앞판 (무거워 고정 불필요하다고 함)


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
    missing = cabinet_missing(DIM, PLACES)
    cabinet = not missing

    # ---------- 평면도 → 작업대 좌표계 W (원점 = 로봇 베이스 철판 중심, 작업대 윗면 z=0, +x 긴 변 오른쪽, +y 서랍 반대쪽) ----------
    plate_w, plate_d = pv["robot_base_plate_cm"]["width"], pv["robot_base_plate_cm"]["depth"]
    x_left = -(pv["robot_base_left_gap_to_table_left"] + plate_w / 2) * CM
    x_right = x_left + tb["width_cm"] * CM
    y_top = (pv["robot_base_gap_to_table_top_edge"] + plate_d / 2) * CM
    y_bottom = -(pv["robot_base_gap_to_table_bottom_edge"] + plate_d / 2) * CM
    assert abs((y_top - y_bottom) - tb["depth_cm"] * CM) < 1e-6, "도면의 21+23+21 이 작업대 깊이와 맞지 않음"

    if cabinet:
        cab_w, cab_d = u["width_cm"] * CM, u["depth_cm"] * CM
        cab_x0 = x_left + pv["drawer_left_edge_to_table_left"] * CM
        cab_x1 = cab_x0 + cab_w
        assert abs((x_right - cab_x1) - pv["drawer_right_edge_to_table_right"] * CM) < 1e-6, "도면의 서랍 좌우 치수가 맞지 않음"
        cab_xc = (cab_x0 + cab_x1) / 2
        y_front = y_bottom - pv["drawer_front_to_table_edge_gap"] * CM   # 앞면(로봇 쪽) y. 0.4cm는 간격으로 가정 [확인 필요]
        cab_yc = y_front - cab_d / 2

        z_seat = u["seat_top_vs_table_surface_cm"] * CM      # 받침 선반 윗면 (작업대 윗면 기준)
        z_base = z_seat + u["riser_cm"] * CM                  # 서랍장 바닥 = 선반 위 우드락 위. 아래 높이(cm)들은 우드락 추가 전 기준이라 +riser

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
    if cabinet:
        box(stage, "/World/workspace/shelf", (cab_w + 2 * SHELF_MARGIN, cab_d + 2 * SHELF_MARGIN, SHELF_THICKNESS),
            (cab_xc, cab_yc, z_seat - SHELF_THICKNESS / 2), (0.92, 0.92, 0.92))

    if cabinet:
        # ---------- 서랍장: 원목 2단, 중간 가로막 없음(철제 레일). 서랍 상자 2개가 각각 Prismatic Joint ----------
        det, bx, hd = u["tiers_detail"], u["drawer_box"], u["handle"]
        fpn = top["front_panel_cm"]
        top_board, panel_t = u["top_board_cm"] * CM, fpn["thickness"] * CM
        side_t = bx["cabinet_board_cm"] * CM
        in_d, in_w, rim_h = PLACES["drawer_top"]["interior_m"][0], PLACES["drawer_top"]["interior_m"][1], PLACES["drawer_top"]["interior_m"][2]
        wall = bx["side_wall_cm"] * CM                          # 상자(수납장) 벽 두께 (앞·뒤벽도 같다고 가정 [추정])
        out_w = in_w + 2 * wall                                # 안쪽 폭 기준으로 만든다 (측정한 바깥 폭 32.0 과 0.3 cm 차이)
        out_d = in_d + 2 * wall
        travel = PLACES["drawer_top"]["max_travel_m"]          # 정본은 config/places.yaml
        total_h = u["total_height_cm"] * CM
        wood, gray, handle_c = (0.80, 0.62, 0.40), (0.62, 0.58, 0.52), (0.58, 0.55, 0.50)

        def hz(cm):
            return z_base + cm * CM

        xform(stage, "/World/workspace/cabinet", pose([cab_xc, cab_yc, 0]))
        shell = xform(stage, "/World/workspace/cabinet/shell", pose([0, 0, 0]))
        UsdPhysics.RigidBodyAPI.Apply(shell).CreateKinematicEnabledAttr(True)
        sp = "/World/workspace/cabinet/shell"
        box(stage, f"{sp}/bottom_board", (cab_w, cab_d, top_board), (0, 0, hz(0) + top_board / 2), wood)
        box(stage, f"{sp}/top_board", (cab_w, cab_d, top_board), (0, 0, hz(0) + total_h - top_board / 2), wood)
        for sgn, nm in ((-1, "side_left"), (1, "side_right")):
            box(stage, f"{sp}/{nm}", (side_t, cab_d, total_h), (sgn * (cab_w / 2 - side_t / 2), 0, hz(0) + total_h / 2), wood)
        box(stage, f"{sp}/back_board", (cab_w - 2 * side_t, side_t, total_h), (0, -cab_d / 2 + side_t / 2, hz(0) + total_h / 2), wood)
        shell_parts = [Sdf.Path(sp)] + [Sdf.Path(f"{sp}/{n}") for n in ("bottom_board", "top_board", "side_left", "side_right", "back_board")]

        def drawer(tag, tier, handle_cm):
            d = det[tier]
            z_ref = hz(d["floor_surface"])                      # 상자 안쪽 바닥면 높이
            y_c = cab_d / 2 - out_d / 2                         # 상자 앞벽이 서랍장 본체 앞면과 같은 선
            p = f"/World/workspace/cabinet/drawer_{tag}_tray"
            tray = xform(stage, p, pose([0, y_c, z_ref]))
            UsdPhysics.RigidBodyAPI.Apply(tray)
            UsdPhysics.MassAPI.Apply(tray).CreateMassAttr(TRAY_MASS)
            box(stage, f"{p}/floor", (out_w, out_d, FLOOR_T), (0, 0, -FLOOR_T / 2), wood)
            for sgn, nm in ((-1, "wall_left"), (1, "wall_right")):
                box(stage, f"{p}/{nm}", (wall, out_d, rim_h), (sgn * (in_w / 2 + wall / 2), 0, rim_h / 2), wood)
            box(stage, f"{p}/wall_back", (in_w, wall, rim_h), (0, -out_d / 2 + wall / 2, rim_h / 2), wood)
            box(stage, f"{p}/wall_front", (in_w, wall, rim_h), (0, out_d / 2 - wall / 2, rim_h / 2), wood)
            fb, ft = d["front_bottom_height"] + (0.1 if tier == "upper" else 0.0), d["front_top_height"] - (0.1 if tier == "lower" else 0.0)
            box(stage, f"{p}/front_panel", (fpn["width"] * CM, panel_t, (ft - fb) * CM),
                (0, out_d / 2 + panel_t / 2, hz((fb + ft) / 2) - z_ref), gray)
            box(stage, f"{p}/handle", (hd["width_cm"] * CM, hd["protrusion_cm"] * CM, hd["thickness_vertical_cm"] * CM),
                (0, out_d / 2 + panel_t + hd["protrusion_cm"] * CM / 2, hz(handle_cm) - z_ref), handle_c)
            fp_api = UsdPhysics.FilteredPairsAPI.Apply(tray)       # 상자와 서랍장 본체·다른 상자 사이 충돌은 끈다(레일이 잡고 있음)
            for t in shell_parts:
                fp_api.CreateFilteredPairsRel().AddTarget(t)
            jt = UsdPhysics.PrismaticJoint.Define(stage, f"/World/workspace/cabinet/drawer_{tag}_joint")
            jt.CreateBody0Rel().AddTarget(Sdf.Path(sp))
            jt.CreateBody1Rel().AddTarget(Sdf.Path(p))
            jt.CreateAxisAttr("Y")                                 # +y = 앞(로봇·작업대 쪽)으로 당김, 닫힘 = 0
            jt.CreateLocalPos0Attr(Gf.Vec3f(0, y_c, z_ref - 0.0))
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
            jt.GetPrim().SetCustomDataByKey("note", "max_travel은 config/places.yaml 의 max_travel_m. 닫힘=0")
            return p

        tray_top = drawer("top", "upper", hd["height_from_bottom_cm"]["upper"])
        tray_bottom = drawer("bottom", "lower", hd["height_from_bottom_cm"]["lower"])
        for pa, pb in ((tray_top, tray_bottom), (tray_bottom, tray_top)):   # 두 상자끼리도 충돌 끔
            UsdPhysics.FilteredPairsAPI(stage.GetPrimAtPath(pa)).GetFilteredPairsRel().AddTarget(Sdf.Path(pb))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    stage.GetRootLayer().Export(str(OUT))
    print(f"[build] 저장: {OUT}", flush=True)
    print(f"[build] 작업대 x[{x_left:.3f},{x_right:.3f}] y[{y_bottom:.3f},{y_top:.3f}]", flush=True)
    if cabinet:
        print(f"[build] 서랍장 x[{cab_x0:.3f},{cab_x1:.3f}] 앞면 y={y_front:.3f}  인출 한계 {travel:.3f} m  2단 상자 안쪽 바닥 z={hz(det['upper']['floor_surface']):.4f}", flush=True)
    else:
        print("[build] 서랍장은 만들지 않았습니다 (작업대·로봇·카메라만). 아직 필요한 항목:", flush=True)
        for m in missing:
            print(f"[build]   - {m}", flush=True)


build()
app.close()
