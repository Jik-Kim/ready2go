"""실물 동작 자세·거리 계산 (ROS 비의존·pytest 대상, #13·#15·#37). 값은 params/skills.yaml (10/05~06 로봇 실측).

posx = [x, y, z, Rz, Ry, Rz'] mm·deg (ZYZ). 손가락은 툴 x축 방향으로 닫힌다 [실측 B 10/05].
그리퍼 기하 (practice/B/2026-10-06_practice.md 트러블슈팅 1):
  - 벌릴수록 손끝이 올라감 → `tip_below_tcp_mm` 표
  - 손가락 바깥 관절이 닫힘 방향으로 튀어나옴 → 벽 간섭 거리 `wall_clearance_mm` (across = 닫힘 축이 벽과 직각, along = 나란히)
끌기(nudge, 트러블슈팅 2): 그리퍼를 기울여 손끝으로 위에서 눌러, 서랍 옆으로만(서랍 좌표 y, base ≈ x) 끈다.
  손가락 방향: drag.close_axis "wall"(닫힘 축 = 옆벽 법선, 10/06 실측으로 확인한 자세) / "object"(닫힘 축 = 물체 긴 변, 계산만).
  서랍이 닫히는 방향으로는 끌지 않는다 (2 N에서도 서랍이 같이 밀림 [실측 B 10/06]).
"""
import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from ready2go_skills.core import pose_math as pm
from ready2go_skills.core.pick_plan import rotate

NO_PUSH_ACCESS = "NO_PUSH_ACCESS"      # 옆으로 끌어도 잡을 수 없음 (앞뒤 벽 때문) — docs/runner.md nudge_object 표


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def interp(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    """선형 보간, 표 밖은 끝값 (외삽하지 않음)."""
    if x <= xs[0]:
        return float(ys[0])
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return float(ys[i - 1] + t * (ys[i] - ys[i - 1]))
    return float(ys[-1])


def tip_below_tcp_mm(open_mm: float, g: Mapping) -> float:
    """벌림 폭에서 손끝이 TCP보다 아래인 거리 (음수 = TCP 위)."""
    t = g["tip_below_tcp_mm"]
    return interp(open_mm, t["open_mm"], t["below_mm"])


def wall_extent_mm(open_mm: float, close_angle_to_wall_normal_rad: float, g: Mapping) -> float:
    """그리퍼가 벽 쪽으로 차지하는 거리(TCP 기준). 닫힘 축과 벽 법선 사이 각에 따라 across·along을 섞는다(보수적으로 합)."""
    w = g["wall_clearance_mm"]
    across = interp(open_mm, w["across"]["open_mm"], w["across"]["dist_mm"])
    c, s = abs(math.cos(close_angle_to_wall_normal_rad)), abs(math.sin(close_angle_to_wall_normal_rad))
    return c * across + s * w["along_mm"]


def from_base(tf: Mapping, p_m: Sequence[float]) -> tuple:
    """base 점(m) → 자식 좌표계(m)."""
    t = tf["translation_m"]
    x, y, z, w = tf["quaternion_xyzw"]
    d = [p_m[i] - t[i] for i in range(3)]
    return rotate((-x, -y, -z, w), d)


def dir_to_base(tf: Mapping, v: Sequence[float]) -> tuple:
    return rotate(tf["quaternion_xyzw"], v)


# ---------- 자세 ----------
def gripper_posx(pos_mm: Sequence[float], close_dir: Sequence[float], cur_angles: Sequence[float],
                 tilt_toward: Optional[Sequence[float]] = None, tilt_deg: float = 0.0) -> list:
    """TCP를 pos_mm에, 툴 z = 아래(tilt_toward 쪽으로 tilt_deg 기울임 — 손끝이 그쪽으로 감), 손가락 닫힘(툴 x) = close_dir.
    닫힘 방향 ±는 손목이 덜 도는 쪽. 각도는 지금 각도(cur_angles)에 가까운 ZYZ 표현."""
    z = [0.0, 0.0, -1.0]
    if tilt_toward is not None and tilt_deg:
        n = pm.unit([tilt_toward[0], tilt_toward[1], 0.0])
        t = math.radians(tilt_deg)
        z = [n[0] * math.sin(t), n[1] * math.sin(t), -math.cos(t)]
    d = sum(close_dir[i] * z[i] for i in range(3))
    x = pm.unit([close_dir[i] - d * z[i] for i in range(3)])
    if x is None:
        raise ValueError(f"닫힘 방향이 그리퍼 축과 평행: {close_dir}")
    cur = pm.rot(*cur_angles)
    best = None
    for sgn in (1.0, -1.0):
        r = pm.frame([sgn * c for c in x], z)
        ang = pm.rotation_angle(cur, r)
        if best is None or ang < best[0]:
            best = (ang, r)
    return [float(v) for v in pos_mm] + pm.zyz_near(best[1], list(cur_angles))


def horizontal_angle_dir(deg: float) -> tuple:
    a = math.radians(deg)
    return (math.cos(a), math.sin(a), 0.0)


def offset_posx(posx: Sequence[float], direction: Sequence[float], dist_mm: float) -> list:
    return [posx[i] + dist_mm * direction[i] for i in range(3)] + list(posx[3:])


def with_z(posx: Sequence[float], z_mm: float) -> list:
    return list(posx[:2]) + [float(z_mm)] + list(posx[3:])


# ---------- 서랍 손잡이 ----------
BLEND_RATIO = 0.9   # 블렌딩 반지름 = 앞뒤 구간 절반의 이 비율까지. 절반 그대로면 제어기 반올림으로 거부 [실측 PC2 10/08: Input-Rad 41.724 > max_dist 41.723 → moveb 출발 안 함]


def safe_blend_radii(start: Sequence[float], points: Sequence[Sequence[float]], radii: Sequence[float],
                     ratio: float = BLEND_RATIO) -> list:
    """moveb 반지름을 각 경유점 앞뒤 구간 길이 절반 × ratio 이하로 줄임 (마지막 점은 0). start = 지금 TCP posx."""
    seq = [list(start)] + [list(p) for p in points]
    out = []
    for k, r in enumerate(radii):
        if k + 2 >= len(seq):
            out.append(0.0)
            continue
        half = min(math.dist(seq[k][:3], seq[k + 1][:3]), math.dist(seq[k + 1][:3], seq[k + 2][:3])) / 2.0
        out.append(max(0.0, min(float(r), ratio * half)))
    return out


def handle_posx(closed_posx: Sequence[float], pull_dir: Sequence[float], displacement_m: float) -> list:
    """닫힌 상태 손잡이 파지 posx → 인출 거리 displacement_m 에서의 손잡이 파지 posx (방향 그대로)."""
    return offset_posx(closed_posx, pull_dir, displacement_m * 1000.0)


def travel_mm(start_posx: Sequence[float], now_posx: Sequence[float], direction: Sequence[float]) -> float:
    return sum((now_posx[i] - start_posx[i]) * direction[i] for i in range(3))


# ---------- 끌기 ----------
def tip_contact(tilt_rad: float, g: Mapping) -> tuple:
    """닫은 손끝을 벽 쪽으로 tilt 만큼 기울였을 때 가장 낮은 점: (TCP보다 벽 쪽 수평 거리 mm, TCP 아래 깊이 mm).
    손끝 끝은 반지름 R 반원, 수직일 때 바닥점이 TCP 아래 tip mm → 반원 중심은 TCP 아래 (tip − R)."""
    tip, r = tip_below_tcp_mm(0.9, g), g["tip_radius_mm"]
    return (tip - r) * math.sin(tilt_rad), (tip - r) * math.cos(tilt_rad) + r



@dataclass(frozen=True)
class DragPlan:
    needed: bool
    error_code: Optional[str]
    shift_y_m: float              # 서랍 좌표 y 방향 이동 (부호 포함)
    press_xy_m: Optional[tuple]   # 누를 TCP 위치 (서랍 좌표)
    wall_normal_y: float          # 가까운 옆벽 쪽 (+1 = y 최대 벽, −1 = y 0 벽)
    clearance_before_m: float
    reason: str


def _grasp_blocked(cx, cy, yaw, size_m, interior_m, g, margin_mm):
    """짧은 변 잡기(닫힘 축 = 긴 변에 수직)가 벽에 걸리는지. (x벽 걸림, y벽 부족량 mm(양수면 부족), 가까운 y벽 부호)"""
    width = size_m[1]
    open_mm = width * 1000.0 + g["open_margin_mm"]
    close_ang = yaw + math.pi / 2                   # 서랍 좌표에서 닫힘 축 각도
    ext_x = wall_extent_mm(open_mm, close_ang, g)                # x 벽(법선 x)
    ext_y = wall_extent_mm(open_mm, close_ang - math.pi / 2, g)  # y 벽(법선 y)
    d, wd = interior_m[0] * 1000.0, interior_m[1] * 1000.0
    x_mm, y_mm = cx * 1000.0, cy * 1000.0
    x_ok = min(x_mm, d - x_mm) >= ext_x + margin_mm
    sign = 1.0 if y_mm > wd / 2 else -1.0
    gap = (wd - y_mm) if sign > 0 else y_mm
    gap += (g.get("wall_offset_mm") or {}).get("y_max" if sign > 0 else "y_min", 0.0)   # 실제 옆벽이 서랍 경계보다 바깥인 만큼 [실측 B 10/07]
    return (not x_ok), (ext_y + margin_mm) - gap, sign


def wall_blocks_grasp(*, target: Mapping, size_m: Sequence[float], interior_m: Sequence[float], g: Mapping) -> Optional[str]:
    """바로 집기 전 확인: 짧은 변으로 잡으면 손가락·관절이 서랍 벽에 닿는 자리면 이유 문자열, 아니면 None.
    plan_drag 와 같은 판단(_grasp_blocked) — 끌기 뒤 target_after 는 부족량 + extra_mm 만큼 옮겨져 통과 (#83 A 요청)."""
    cx, cy = target["pose"]["position"][:2]
    yaw = target["pose"]["yaw"]
    if not _finite(cx, cy, yaw, *size_m[:2], *interior_m[:2]):
        return f"위치·크기 값 비정상: {cx, cy, yaw, size_m, interior_m}"
    x_blocked, lack_mm, _ = _grasp_blocked(cx, cy, yaw, size_m, interior_m, g, g["wall_margin_mm"])
    if x_blocked:
        return "앞뒤 벽에 걸려 짧은 변으로 못 잡음"
    if lack_mm > 0:
        return f"옆벽 쪽 여유 {lack_mm:.1f} mm 부족 — nudge_object 먼저"
    return None


def plan_drag(*, target: Mapping, size_m: Sequence[float], interior_m: Sequence[float], g: Mapping,
              drag: Mapping) -> DragPlan:
    """옆벽에 붙어 짧은 변으로 못 잡는 물체를 서랍 y 방향(옆)으로만 끌 거리와 누를 점. 이미 잡을 수 있으면 needed False."""
    cx, cy = target["pose"]["position"][:2]
    yaw = target["pose"]["yaw"]
    if not _finite(cx, cy, yaw, *size_m[:3], *interior_m[:2]):
        raise ValueError(f"끌기 입력 비정상: {cx, cy, yaw, size_m, interior_m}")
    margin = g["wall_margin_mm"]
    x_blocked, lack_mm, sign = _grasp_blocked(cx, cy, yaw, size_m, interior_m, g, margin)
    wd = interior_m[1] * 1000.0
    gap_m = ((wd - cy * 1000.0) if sign > 0 else cy * 1000.0) / 1000.0
    if lack_mm <= 0 and not x_blocked:
        return DragPlan(False, None, 0.0, None, sign, gap_m, "끌지 않아도 잡을 수 있음")
    if x_blocked:
        return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, sign, gap_m,
                        "앞뒤 벽 때문에 짧은 변으로 못 잡음 — 옆으로 끌어도 해결 안 됨 (길이 방향 잡기·P2)")
    shift = -sign * (lack_mm + drag["extra_mm"]) / 1000.0     # 벽 반대쪽(가운데)으로
    if not abs(shift) <= drag["max_shift_mm"] / 1000.0:
        return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, sign, gap_m, f"끌 거리 {abs(shift) * 1000:.0f} mm가 최대보다 큼")
    # 누르는 점 (닫은 손가락, 닫힘 축 = 물체 긴 변 → 얇은 쪽이 옆벽). 거리는 모두 '옆벽(서랍 좌표 경계)에서' mm.
    # 손끝은 옆에서 보면 반원(U) [사진 B 10/06] → 기울여도 가장 낮은 점은 반원 중심 바로 아래 (tip_contact).
    if drag.get("close_axis", "object") == "wall":
        # 닫힘 축 = 옆벽 법선(서랍 y), 옆벽 쪽으로 30° [실측 B 10/06]: 모서리에 최대로 넣어 TCP–옆벽 경계 5.0 mm,
        # 지우개 윗면을 눌러 옆으로 잘 끌림. 접촉점은 TCP 바로 아래로 봄 [추정 — 손끝 가운데로 눌림, 사용자 확인]
        low_off = 0.0
        wall_min = (g.get("wall_tcp_min_mm") or {}).get("y_max" if sign > 0 else "y_min", drag["wall_tcp_min_mm"])   # 서랍·옆벽마다 [실측 B 10/10]
        need_mm = wall_min + drag.get("wall_press_margin_mm", margin)   # 10/06: 여유 0 — 덜 붙으면 지우개 끝만 눌려 덜덜 끌림
    else:
        t = math.radians(drag.get("tilt_deg", 0.0))
        along = g["wall_clearance_mm"]["along_mm"]
        low_off, _ = tip_contact(t, g)                      # 접촉점이 TCP보다 벽 쪽(+)으로 간 거리
        need_mm = along + low_off + margin                  # 벽 쪽 끝 = 반원 중심 + 반지름 → 수직일 때보다 low_off 만큼 이동
    half_w = size_m[1] * 1000.0 / 2
    center = (wd - cy * 1000.0) if sign > 0 else cy * 1000.0
    tcp = max(need_mm, center + low_off)                    # 가능하면 가장 낮은 점이 물체 중심에
    contact = tcp - low_off
    if not (center - half_w + drag["press_inset_mm"] <= contact <= center + half_w - drag["press_inset_mm"]):
        return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, sign, gap_m,
                        f"누를 점이 물체 밖 (벽에서 TCP {tcp:.1f}, 접촉 {contact:.1f}, 물체 {center - half_w:.1f}~{center + half_w:.1f} mm)"
                        " — 기울기를 줄이거나 0으로")
    press = (cx, cy + sign * (center - tcp) / 1000.0)
    return DragPlan(True, None, shift, press, sign, gap_m,
                    f"옆벽 쪽 부족 {lack_mm:.1f} mm → y {shift * 1000:+.1f} mm 끌기")


# ---------- 놓기 ----------
def place_tcp_above_floor_m(grasp_tcp_above_floor_m: float, drop_m: float) -> float:
    """집을 때 TCP 높이 그대로 + drop_m 위에서 놓음 → 물체 바닥이 drop_m 만큼 떠서 놓임."""
    return grasp_tcp_above_floor_m + drop_m
