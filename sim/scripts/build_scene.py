"""T1 씬 생성 (담당 A): 작업대 + (서랍 치수가 채워졌을 때만) 받침 선반 + 2단 서랍장(상자 2개 각각 Prismatic Joint) + M0609/RG2 + 손목 카메라.

실행: ~/isaac-sim-5.1.0/python.sh sim/scripts/build_scene.py  →  sim/scenes/ready2go_t1.usd
검증: ~/isaac-sim-5.1.0/python.sh sim/scripts/verify_scene.py

- 형상 치수는 sim/drawer_dimensions.yaml 에서 읽는다 (값은 그 파일에만 둔다). 서랍 내부 치수만 config/places.yaml 의 drawer_top.interior_m 에서 읽는다
  (아래 서랍 상자 테두리 높이만 drawer_bottom.interior_m[2]).
- 서랍장 위치는 drawer_top.tf, 아래 서랍 상자는 drawer_bottom.tf(B 실측 10/07)가 있으면 그 자리에 둔다(서랍장 형상에서 계산한 자리와 몇 mm 다름).
  실측 서랍 좌표계는 /World/workspace/markers 에 축 표시(빨강 x·초록 y·파랑 z, 충돌 없음)로 남겨 GUI 에서 눈으로 대조한다.
- 카메라 변환은 config/calibration/calibration_meta.yaml 의 derived_tf·driver_tf_used 에서 읽는다 (잠정 채택 값).
- 월드 = 로봇 base_link. 로봇은 원점에 두고(루트 고정 관절의 기준점이 월드에 고정되어 있어 옮기면 어긋남),
  작업대·서랍장은 /World/workspace 아래에 둔다. 로봇 base_link와 작업대 변의 각도는 미확인이라 WORKSPACE_YAW_DEG 로 둔다.
- 서랍의 로봇 기준 정확한 위치는 #6(3점 터치) 결과로 교체한다. 여기 값은 평면도 기준 초기 배치다.
"""
import math
import os
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
# 시험용: 가짜 tf 로 확인할 때 READY2GO_PLACES(대체 places.yaml), READY2GO_SCENE(출력 경로)를 지정한다. 지정하지 않으면 정본 파일.
PLACES_PATH = Path(os.environ.get("READY2GO_PLACES", ROOT / "config/places.yaml"))
PLACES_BYTES = PLACES_PATH.read_bytes()
PLACES = yaml.safe_load(PLACES_BYTES)
OUT = Path(os.environ.get("READY2GO_SCENE", ROOT / "sim/scenes/ready2go_t1.usd"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene_record  # noqa: E402
from _dims import cabinet_missing, cabinet_pose_from_tf, drawer_frame_tf, drawer_tf, quat_to_R, tray_pose_from_drawer  # noqa: E402
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


def quat_wxyz(R):
    """3x3 회전 → (w, x, y, z)"""
    R = np.asarray(R, dtype=float)
    w = math.sqrt(max(0.0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    x = math.copysign(math.sqrt(max(0.0, 1 + R[0, 0] - R[1, 1] - R[2, 2])) / 2, R[2, 1] - R[1, 2])
    y = math.copysign(math.sqrt(max(0.0, 1 - R[0, 0] + R[1, 1] - R[2, 2])) / 2, R[0, 2] - R[2, 0])
    z = math.copysign(math.sqrt(max(0.0, 1 - R[0, 0] - R[1, 1] + R[2, 2])) / 2, R[1, 0] - R[0, 1])
    return w, x, y, z


def frame_marker(stage, path, T, length=0.04, t=0.002):
    """좌표계 축 표시(빨강 x·초록 y·파랑 z, 충돌 없음) — GUI 에서 실측 좌표계와 씬 형상을 눈으로 대조."""
    xform(stage, path, T)
    for i, (nm, col) in enumerate((("x", (1, 0.1, 0.1)), ("y", (0.1, 0.8, 0.1)), ("z", (0.1, 0.3, 1)))):
        size, center = [t, t, t], [0.0, 0.0, 0.0]
        size[i], center[i] = length, length / 2
        box(stage, f"{path}/{nm}", size, center, col, collide=False)
    box(stage, f"{path}/origin", (2.5 * t, 2.5 * t, 2.5 * t), (0, 0, 0), (1, 1, 0.1), collide=False)


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


HANDOVER_CORNER_R = 0.003    # 벽 직각 트레이 모서리 둥글기 반경 (안쪽 면). 보이는 형상에만 씀


def _round_rect(d, w, e, r, z, k=10):
    """손끝 범위 사각형(0~d, 0~w)을 바깥으로 e 만큼 넓히고 모서리를 반경 r 로 둥글린 고리 점들 (반시계)."""
    pts = []
    for cx, cy, a0 in ((d + e - r, -e + r, -90), (d + e - r, w + e - r, 0), (-e + r, w + e - r, 90), (-e + r, -e + r, 180)):
        for i in range(k + 1):
            a = math.radians(a0 + 90 * i / k)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
    return pts


def rounded_tray_visual(stage, path, d, w, h, lo, hi, t, r, col):
    """보이는 트레이: 둥근 모서리 사다리꼴 벽(안쪽 면·윗면·바깥 면·밑면)과 둥근 바닥판을 메시 둘로. 충돌 없음."""
    rings = [_round_rect(d, w, lo, r, 0.0), _round_rect(d, w, hi, r, h), _round_rect(d, w, hi + t, r + t, h), _round_rect(d, w, lo + t, r + t, 0.0)]
    n = len(rings[0])
    pts = [Gf.Vec3f(*q) for ring in rings for q in ring]
    counts, idx = [], []
    for a in range(4):                                                   # 안쪽 면 → 윗면 → 바깥 면 → 밑면 → 다시 안쪽
        b = (a + 1) % 4
        for i in range(n):
            j = (i + 1) % n
            counts.append(4)
            idx += [a * n + i, a * n + j, b * n + j, b * n + i]
    shell = UsdGeom.Mesh.Define(stage, f"{path}_walls")
    shell.CreatePointsAttr(pts)
    shell.CreateFaceVertexCountsAttr(counts)
    shell.CreateFaceVertexIndicesAttr(idx)
    shell.CreateSubdivisionSchemeAttr("none")
    shell.CreateDoubleSidedAttr(True)
    shell.CreateDisplayColorAttr([Gf.Vec3f(*col)])
    top, bot = _round_rect(d, w, lo, r, 0.0), _round_rect(d, w, lo, r, -t)
    fpts = [Gf.Vec3f(*q) for q in top + bot]
    fc, fi = [len(top), len(bot)], list(range(len(top))) + list(range(2 * len(top) - 1, len(top) - 1, -1))
    for i in range(len(top)):
        j = (i + 1) % len(top)
        fc.append(4)
        fi += [i, len(top) + i, len(top) + j, j]
    floor = UsdGeom.Mesh.Define(stage, f"{path}_floor")
    floor.CreatePointsAttr(fpts)
    floor.CreateFaceVertexCountsAttr(fc)
    floor.CreateFaceVertexIndicesAttr(fi)
    floor.CreateSubdivisionSchemeAttr("none")
    floor.CreateDoubleSidedAttr(True)
    floor.CreateDisplayColorAttr([Gf.Vec3f(*col)])


def handover_tray(stage):
    """전달 트레이. 위치는 places.yaml handover_zone.tf, 안쪽 바닥 범위는 같은 곳의 floor_m(비전 inspect_region 과 같은 값 — 한 곳),
    높이는 interior_m[2](바닥→테두리 윗면), 벽·바닥 두께만 sim/drawer_dimensions.yaml trays.handover_zone.wall_cm (벽 직각 [사용자 실측 10/11]).
    벽 안쪽 면 = floor_m 경계, 바깥 면 = 거기서 벽 두께 바깥. interior_m x·y 는 놓기 범위라 형상에 쓰지 않는다. 고정 물체(충돌만)."""
    hz_ = PLACES.get("handover_zone") or {}
    tf, fl, inner = hz_.get("tf"), hz_.get("floor_m"), hz_.get("interior_m")
    shape = (DIM.get("trays") or {}).get("handover_zone") or {}
    if not tf or not tf.get("translation_m"):
        return "만들지 않음 (places.yaml handover_zone tf 없음)"
    if not fl or not inner or inner[2] is None or not shape.get("wall_cm"):
        return "만들지 않음 (places.yaml handover_zone floor_m·interior_m[2] 또는 sim/drawer_dimensions.yaml trays.handover_zone.wall_cm 없음)"
    (x0, x1), (y0, y1) = fl["x"], fl["y"]
    t, r, h = float(shape["wall_cm"]) * CM, HANDOVER_CORNER_R, float(inner[2])
    d, w = x1 - x0, y1 - y0
    root = "/World/workspace/handover_tray"
    xform(stage, root, pose(tf["translation_m"], tf["quaternion_xyzw"]))
    col = (0.35, 0.45, 0.7)
    hidden = [box(stage, f"{root}/floor", (d + 2 * t, w + 2 * t, t), ((x0 + x1) / 2, (y0 + y1) / 2, -t / 2), col)]   # 충돌용 (보이는 건 아래 메시)
    walls = {                                                           # 안쪽 면 4점 + 바깥 법선 방향으로 두께 t
        "wall_near": ([(x0, y0, 0), (x0, y1, 0), (x0, y1, h), (x0, y0, h)], (-1, 0)),
        "wall_far": ([(x1, y0, 0), (x1, y1, 0), (x1, y1, h), (x1, y0, h)], (1, 0)),
        "wall_right": ([(x0, y0, 0), (x1, y0, 0), (x1, y0, h), (x0, y0, h)], (0, -1)),
        "wall_left": ([(x0, y1, 0), (x1, y1, 0), (x1, y1, h), (x0, y1, h)], (0, 1)),
    }
    for nm, (inner_pts, (nx, ny)) in walls.items():
        pts = [Gf.Vec3f(*q) for q in inner_pts] + [Gf.Vec3f(q[0] + nx * t, q[1] + ny * t, q[2]) for q in inner_pts]
        mesh = UsdGeom.Mesh.Define(stage, f"{root}/{nm}")
        mesh.CreatePointsAttr(pts)
        mesh.CreateFaceVertexCountsAttr([4] * 6)
        mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3, 7, 6, 5, 4, 0, 4, 5, 1, 1, 5, 6, 2, 2, 6, 7, 3, 3, 7, 4, 0])
        mesh.CreateDisplayColorAttr([Gf.Vec3f(*col)])
        mesh.CreateDoubleSidedAttr(True)
        UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
        UsdPhysics.MeshCollisionAPI.Apply(mesh.GetPrim()).CreateApproximationAttr("convexHull")
        hidden.append(mesh.GetPrim())
    for prim in hidden:                                                  # 충돌만 하고 화면에는 안 보임
        UsdGeom.Imageable(prim).MakeInvisible()
    xform(stage, f"{root}/visual_frame", pose([x0, y0, 0.0], [0.0, 0.0, 0.0, 1.0]))   # 보이는 메시는 0~d·0~w 기준이라 floor_m 시작점으로 옮김
    rounded_tray_visual(stage, f"{root}/visual_frame/visual", d, w, h, 0.0, 0.0, t, r, col)
    return (f"{root} 안쪽 바닥(floor_m) {d * 1000:.0f}×{w * 1000:.0f} mm, 바깥 {(d + 2 * t) * 1000:.0f}×{(w + 2 * t) * 1000:.0f}×{(h + t) * 1000:.0f} mm, "
            f"벽 {t * 1000:.0f} mm, 놓기 범위(interior_m) {inner[0]}×{inner[1]} m, 원점 {tf['translation_m']}")


def _code_sha() -> str:
    """씬을 만든 저장소 코드 SHA(짧게). 커밋 안 된 변경이 있으면 +dirty. git 이 없으면 unknown."""
    import subprocess
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "sim", "config"], capture_output=True, text=True).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


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
        z_base = z_seat + u["riser_cm"] * CM
        tf = drawer_tf(PLACES)                                # #6 3점 터치 결과(서랍 좌표계). 아직 null 이면 None → 평면도 기반 임시 배치                  # 서랍장 바닥 = 선반 위 우드락 위. 아래 높이(cm)들은 우드락 추가 전 기준이라 +riser

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

        y_c = cab_d / 2 - out_d / 2                             # 닫힌 상자 중심의 서랍장 로컬 y (상자 앞벽이 서랍장 본체 앞면과 같은 선)
        z_floor = hz(det["upper"]["floor_surface"])             # 위 단 상자 안쪽 바닥면의 서랍장 로컬 z
        if tf is None:
            T_cab = pose([cab_xc, cab_yc, 0])
            placement = f"임시 배치(평면도: 작업대 오른쪽 끝 {pv['drawer_right_edge_to_table_right']} cm). places.yaml drawer_top.tf 가 null"
        else:
            R_cab, o_cab = cabinet_pose_from_tf(tf[0], tf[1], tf[2], in_w, in_d, y_c, z_floor)
            T_cab = pose(o_cab, R=np.array(R_cab))
            placement = f"places.yaml drawer_top.tf (인출 {tf[2]:.3f} m 기준) → 서랍장 원점 {np.round(o_cab, 4).tolist()}"
        xform(stage, "/World/workspace/cabinet", T_cab)
        box(stage, "/World/workspace/cabinet/shelf", (cab_w + 2 * SHELF_MARGIN, cab_d + 2 * SHELF_MARGIN, SHELF_THICKNESS),
            (0, 0, z_seat - SHELF_THICKNESS / 2), (0.92, 0.92, 0.92))    # 받침 선반은 서랍장과 함께 움직인다
        shell = xform(stage, "/World/workspace/cabinet/shell", pose([0, 0, 0]))
        UsdPhysics.RigidBodyAPI.Apply(shell).CreateKinematicEnabledAttr(True)
        sp = "/World/workspace/cabinet/shell"
        box(stage, f"{sp}/bottom_board", (cab_w, cab_d, top_board), (0, 0, hz(0) + top_board / 2), wood)
        box(stage, f"{sp}/top_board", (cab_w, cab_d, top_board), (0, 0, hz(0) + total_h - top_board / 2), wood)
        for sgn, nm in ((-1, "side_left"), (1, "side_right")):
            box(stage, f"{sp}/{nm}", (side_t, cab_d, total_h), (sgn * (cab_w / 2 - side_t / 2), 0, hz(0) + total_h / 2), wood)
        box(stage, f"{sp}/back_board", (cab_w - 2 * side_t, side_t, total_h), (0, -cab_d / 2 + side_t / 2, hz(0) + total_h / 2), wood)
        shell_parts = [Sdf.Path(sp)] + [Sdf.Path(f"{sp}/{n}") for n in ("bottom_board", "top_board", "side_left", "side_right", "back_board")]

        def drawer(tag, tier, handle_cm, closed=None, rim=rim_h):
            """closed = (R 3x3, 위치) 닫힌 상자의 서랍장 로컬 자세(실측 tf 에서 계산). None 이면 서랍장 형상으로 계산한 자리."""
            d = det[tier]
            z_ref = hz(d["floor_surface"])                      # 상자 안쪽 바닥면 높이 (서랍장 형상 기준 — 앞판·손잡이 높이 계산용)
            R_ct, p_ct = closed if closed else (np.eye(3), np.array([0.0, y_c, z_ref]))
            p = f"/World/workspace/cabinet/drawer_{tag}_tray"
            tray = xform(stage, p, pose(p_ct, R=R_ct))
            rim_h = rim
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
            fp_api = UsdPhysics.FilteredPairsAPI.Apply(tray)       # 상자와 서랍장 본체·다른 상자·받침 선반·작업대 사이 충돌은 끈다(레일이 잡고 있음).
            # 아래 서랍은 실측 tf 회전(바닥 기울기 0.6° 포함)으로 앞판 아래 모서리가 선반·작업대 면에 닿아 16 cm에서 멈췄음 [실측 verify 10/08]
            for t in shell_parts + [Sdf.Path("/World/workspace/cabinet/shelf"), Sdf.Path("/World/workspace/table")]:
                fp_api.CreateFilteredPairsRel().AddTarget(t)
            jt = UsdPhysics.PrismaticJoint.Define(stage, f"/World/workspace/cabinet/drawer_{tag}_joint")
            jt.CreateBody0Rel().AddTarget(Sdf.Path(sp))
            jt.CreateBody1Rel().AddTarget(Sdf.Path(p))
            jt.CreateAxisAttr("Y")                                 # +y = 앞(로봇·작업대 쪽)으로 당김, 닫힘 = 0
            jt.CreateLocalPos0Attr(Gf.Vec3f(*[float(v) for v in p_ct]))
            jt.CreateLocalPos1Attr(Gf.Vec3f(0, 0, 0))
            jt.CreateLocalRot0Attr(Gf.Quatf(*[float(v) for v in quat_wxyz(R_ct)]))
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
        # 아래 서랍: drawer_bottom.tf(B 실측 10/07, 끝까지 연 상태)가 있고 서랍장이 실측 tf 로 놓였으면 그 자리에 둔다
        tfb = drawer_frame_tf(PLACES, "drawer_bottom")
        bottom_closed, bottom_note = None, "서랍장 형상으로 계산한 자리 (drawer_bottom.tf 없음 또는 서랍장 임시 배치)"
        if tfb is not None and tf is not None:
            R_wt, t_wt = tray_pose_from_drawer(quat_to_R(tfb[1]), tfb[0], in_w, in_d)
            R_wt, t_wt = np.array(R_wt), np.array(t_wt)
            closed_w = t_wt - tfb[2] * R_wt[:, 1]                 # 트레이 로컬 +y = 여는 방향 → 닫힘 = 연 자리 − 인출 거리
            R_c, o_c = T_cab[:3, :3], T_cab[:3, 3]
            bottom_closed = (R_c.T @ R_wt, R_c.T @ (closed_w - o_c))
            shape = np.array([0.0, y_c, hz(det["lower"]["floor_surface"])])
            dd = bottom_closed[1] - shape
            ang = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(bottom_closed[0]) - 1) / 2))))
            bottom_note = (f"places.yaml drawer_bottom.tf (인출 {tfb[2]:.3f} m) — 서랍장 형상 자리 대비 서랍장 x {dd[0] * 1000:+.1f}·y {dd[1] * 1000:+.1f}·"
                           f"z {dd[2] * 1000:+.1f} mm, 회전 {ang:.2f}°")
        rim_b = (PLACES.get("drawer_bottom") or {}).get("interior_m") or [None, None, rim_h]
        tray_bottom = drawer("bottom", "lower", hd["height_from_bottom_cm"]["lower"], bottom_closed, rim_b[2] if rim_b[2] else rim_h)
        for pa, pb in ((tray_top, tray_bottom), (tray_bottom, tray_top)):   # 두 상자끼리도 충돌 끔
            UsdPhysics.FilteredPairsAPI(stage.GetPrimAtPath(pa)).GetFilteredPairsRel().AddTarget(Sdf.Path(pb))

    handover = handover_tray(stage)
    markers = []
    for key in ("drawer_top", "drawer_bottom"):                  # 실측 서랍 좌표계(최대 인출 상태) 축 표시 — 서랍을 끝까지 열면 상자 안쪽 바닥 모서리와 겹쳐야 함
        ft = drawer_frame_tf(PLACES, key)
        if ft is not None:
            frame_marker(stage, f"/World/workspace/markers/{key}", pose(ft[0], ft[1]))
            markers.append(key)

    rec = scene_record.build_record(PLACES, PLACES_BYTES, _code_sha(), str(PLACES_PATH))   # 생성 설정 — 재생기가 연 USD 의 이 기록과 궤적을 대조 (#215)
    stage.GetRootLayer().customLayerData = {scene_record.RECORD_KEY: scene_record.dumps(rec)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    stage.GetRootLayer().Export(str(OUT))
    print(f"[build] 생성 설정 기록: 코드 {rec['code_sha']}, places sha256 {rec['places_sha256'][:12]} ({PLACES_PATH})", flush=True)
    print(f"[build] 저장: {OUT}", flush=True)
    print(f"[build] 작업대 x[{x_left:.3f},{x_right:.3f}] y[{y_bottom:.3f},{y_top:.3f}]", flush=True)
    if cabinet:
        print(f"[build] 서랍장 배치: {placement}", flush=True)
        print(f"[build] 서랍장 x[{cab_x0:.3f},{cab_x1:.3f}] 앞면 y={y_front:.3f}  인출 한계 {travel:.3f} m  2단 상자 안쪽 바닥 z={hz(det['upper']['floor_surface']):.4f}", flush=True)
    else:
        print("[build] 서랍장은 만들지 않았습니다 (작업대·로봇·카메라만). 아직 필요한 항목:", flush=True)
        for m in missing:
            print(f"[build]   - {m}", flush=True)
    print(f"[build] 전달 트레이: {handover}", flush=True)
    if cabinet:
        print(f"[build] 아래 서랍 상자: {bottom_note}", flush=True)
    print(f"[build] 실측 서랍 좌표계 축 표시: {', '.join(markers) or '없음'} (/World/workspace/markers, 빨강 x 안쪽·초록 y·파랑 z 위)", flush=True)


build()
app.close()
