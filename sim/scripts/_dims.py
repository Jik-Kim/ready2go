"""서랍장을 씬에 만들 수 있는지 판단 (build_scene.py 와 verify_scene.py 가 같은 규칙을 쓴다). Isaac Sim 에 의존하지 않는다.

값이 하나라도 비어 있으면(null) 서랍장은 만들지 않고, 그 이유를 목록으로 돌려준다.
- 형상 치수: sim/drawer_dimensions.yaml
- 서랍 내부 치수·최대 인출 거리: config/places.yaml (정본)
"""

# build_scene.py 의 서랍장 형상 코드가 지원하는 단 수 (원목 2단 서랍장).
SUPPORTED_TIERS = 2


def cabinet_missing(dim: dict, places: dict) -> list[str]:
    """서랍장을 만들기 위해 아직 필요한 항목(사람이 읽는 이름)의 목록. 비어 있으면 만들 수 있다."""
    u = dim.get("drawer_unit") or {}
    top = dim.get("drawer_top") or {}
    pv = dim.get("plan_view_cm") or {}
    pt = places.get("drawer_top") or {}
    need = {
        "drawer_unit.width_cm": u.get("width_cm"),
        "drawer_unit.depth_cm": u.get("depth_cm"),
        "drawer_unit.total_height_cm": u.get("total_height_cm"),
        "drawer_unit.seat_top_vs_table_surface_cm": u.get("seat_top_vs_table_surface_cm"),
        "drawer_top.front_bottom_height_above_seat_cm": top.get("front_bottom_height_above_seat_cm"),
        "plan_view_cm.drawer_right_edge_to_table_right": pv.get("drawer_right_edge_to_table_right"),
        "plan_view_cm.drawer_left_edge_to_table_left": pv.get("drawer_left_edge_to_table_left"),
        "plan_view_cm.drawer_front_to_table_edge_gap": pv.get("drawer_front_to_table_edge_gap"),
        "places.yaml drawer_top.interior_m": pt.get("interior_m"),
        "places.yaml drawer_top.max_travel_m": pt.get("max_travel_m"),
        "drawer_unit.riser_cm": u.get("riser_cm"),
        "drawer_unit.top_board_cm": u.get("top_board_cm"),
        "drawer_unit.tiers_detail": u.get("tiers_detail"),
        "drawer_unit.drawer_box (side_wall_cm, cabinet_board_cm)": all((u.get("drawer_box") or {}).get(k) is not None for k in ("side_wall_cm", "cabinet_board_cm")) or None,
        "drawer_unit.handle (width, thickness, protrusion, heights)": all((u.get("handle") or {}).get(k) is not None for k in ("width_cm", "thickness_vertical_cm", "protrusion_cm", "height_from_bottom_cm")) or None,
        "drawer_top.front_panel_cm (width, thickness)": all((top.get("front_panel_cm") or {}).get(k) is not None for k in ("width", "thickness")) or None,
    }
    missing = [k for k, v in need.items() if v is None]
    tiers = u.get("tiers")
    if tiers is not None and tiers != SUPPORTED_TIERS:
        missing.append(f"build_scene.py 의 서랍장 형상 코드가 {tiers}단 서랍장을 아직 지원하지 않음 ({SUPPORTED_TIERS}단만 지원)")
    return missing


# ---------------------------------------------------------------------------------------------------------------------
# 서랍 좌표계 (#6 3점 터치, B 확정) ↔ 서랍장 배치. 순수 파이썬(numpy 불필요).
#   서랍 좌표계: 원점 = drawer_top 상자 안쪽 바닥 앞쪽 오른쪽 모서리(손잡이 정면에서 볼 때), x = 안쪽(뒤), y = 왼쪽, z = 위, 인출 방향 = 서랍 -x.
#   config/places.yaml drawer_top.tf = 최대 인출(tf_at_travel_m) 상태의 이 좌표계, parent base_link.
#   씬의 서랍장 로컬 축은 base_link 와 같다(x = base +x, y = base +y 로봇 쪽 = 앞, z 위). 서랍 상자는 서랍장 +y 쪽으로 열린다.
# ---------------------------------------------------------------------------------------------------------------------
import math  # noqa: E402

# 서랍장 로컬 축을 서랍 좌표계로 본 열벡터: 서랍장 x = 서랍 +y(왼쪽), 서랍장 y = 서랍 -x(앞), z 같음
_R_DRAWER_FROM_CAB_COLS = ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))


def _matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _matvec(a, v):
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def _transpose(a):
    return [[a[j][i] for j in range(3)] for i in range(3)]


def quat_to_R(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]


def drawer_tf(places: dict):
    """places.yaml drawer_top.tf 를 (translation_m, quaternion_xyzw, tf_at_travel_m) 로. 아직 측정 전(null)이면 None.
    값이 일부만 있거나(번역만, 인출 거리 없음 등) 형식이 틀리면 조용히 넘어가지 않고 ValueError."""
    pt = places.get("drawer_top") or {}
    tf = pt.get("tf") or {}
    t, q = tf.get("translation_m"), tf.get("quaternion_xyzw")
    at = pt.get("tf_at_travel_m")
    if t is None and q is None:
        return None
    if t is None or q is None:
        raise ValueError("drawer_top.tf: translation_m 과 quaternion_xyzw 는 둘 다 있거나 둘 다 null 이어야 함")
    if len(t) != 3 or len(q) != 4:
        raise ValueError("drawer_top.tf: translation_m 은 3개, quaternion_xyzw 는 4개 값")
    if at is None:
        raise ValueError("drawer_top.tf 가 있으면 어느 인출 거리에서 쟀는지 drawer_top.tf_at_travel_m 도 필요")
    return [float(v) for v in t], [float(v) for v in q], float(at)


def cabinet_pose_from_tf(t, q, at_travel, in_w, in_d, y_c, z_ref):
    """서랍 tf → 서랍장 로컬 원점의 base_link 기준 (R 3x3, 원점 3).
    in_w·in_d = 상자 안쪽 폭·깊이, y_c = 닫힘 상태 상자 중심의 서랍장 로컬 y, z_ref = 상자 안쪽 바닥면의 서랍장 로컬 z."""
    R_bd = quat_to_R(q)
    x_axis = [R_bd[i][0] for i in range(3)]
    closed = [t[i] + at_travel * x_axis[i] for i in range(3)]          # 닫힘 = 원점 + 인출 거리 x 서랍 x축(안쪽)
    R_dc = _transpose([list(c) for c in _R_DRAWER_FROM_CAB_COLS])      # 열이 서랍장 축이 되도록
    R_bc = _matmul(R_bd, R_dc)
    p_c = [-in_w / 2, y_c + in_d / 2, z_ref]                           # 서랍 원점(안쪽 앞 오른쪽 바닥)을 서랍장 로컬로 본 위치
    off = _matvec(R_bc, p_c)
    return R_bc, [closed[i] - off[i] for i in range(3)]


def drawer_pose_from_tray(R_wt, t_wt, in_w, in_d):
    """씬의 서랍 상자(트레이) 월드 자세 → 서랍 좌표계 (R, 원점). 트레이 로컬: x = 서랍 +y, y = 서랍 -x(앞), 원점은 상자 중심·바닥면.
    verify_scene.py 가 최대 인출 상태에서 places.yaml tf 와 비교한다."""
    R_wd = _matmul(R_wt, [list(c) for c in _R_DRAWER_FROM_CAB_COLS])   # 서랍 축 = 트레이 축을 서랍 좌표로 바꾼 것의 역
    off = _matvec(R_wt, [-in_w / 2, in_d / 2, 0.0])
    return R_wd, [t_wt[i] + off[i] for i in range(3)]


def drawer_frame_tf(places: dict, key: str):
    """places.yaml <key>.tf 를 (translation_m, quaternion_xyzw, 잰 인출 거리). drawer_top 은 drawer_tf 와 같은 규칙(tf_at_travel_m 필수).
    drawer_bottom 은 tf_at_travel_m 이 없고 B 주석이 "끝까지 연 상태"(10/07)라 max_travel_m 을 쓴다. 없으면 None, 일부만 있으면 ValueError."""
    if key == "drawer_top":
        return drawer_tf(places)
    pt = places.get(key) or {}
    tf = pt.get("tf") or {}
    t, q = tf.get("translation_m"), tf.get("quaternion_xyzw")
    if t is None and q is None:
        return None
    if t is None or q is None or len(t) != 3 or len(q) != 4:
        raise ValueError(f"{key}.tf: translation_m 3개와 quaternion_xyzw 4개가 둘 다 있어야 함")
    at = pt.get("tf_at_travel_m", pt.get("max_travel_m"))
    if at is None:
        raise ValueError(f"{key}.tf 가 있으면 잰 인출 거리(tf_at_travel_m 또는 max_travel_m)도 필요")
    return [float(v) for v in t], [float(v) for v in q], float(at)


def tray_pose_from_drawer(R_wd, o_d, in_w, in_d):
    """drawer_pose_from_tray 의 역: 서랍 좌표계 (R, 원점) → 트레이(상자 중심·바닥면) 월드 (R, 위치)."""
    R_wt = _matmul(R_wd, _transpose([list(c) for c in _R_DRAWER_FROM_CAB_COLS]))
    off = _matvec(R_wt, [-in_w / 2, in_d / 2, 0.0])
    return R_wt, [o_d[i] - off[i] for i in range(3)]

