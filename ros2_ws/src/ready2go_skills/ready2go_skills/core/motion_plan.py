"""실물 동작 자세·거리 계산 (ROS 비의존·pytest 대상, #13·#15·#37). 값은 params/skills.yaml (10/05~06 로봇 실측).

posx = [x, y, z, Rz, Ry, Rz'] mm·deg (ZYZ). 손가락은 툴 x축 방향으로 닫힌다 [실측 B 10/05].
그리퍼 기하 (practice/B/2026-10-06_practice.md 트러블슈팅 1):
  - 벌릴수록 손끝이 올라감 → `tip_below_tcp_mm` 표
  - 손가락 바깥 관절이 닫힘 방향으로 튀어나옴 → 벽 간섭 거리 `wall_clearance_mm` (across = 닫힘 축이 벽과 직각, along = 나란히)
끌기(nudge, 트러블슈팅 2): 그리퍼를 기울여 손끝으로 위에서 눌러, 서랍 옆으로만(서랍 좌표 y, base ≈ x) 끈다.
  손가락 방향: drag.close_axis "wall"(닫힘 축 = 옆벽 법선, 10/06 실측으로 확인한 자세) / "object"(닫힘 축 = 물체 긴 변, 계산만).
  서랍이 닫히는 방향으로는 끌지 않는다 (2 N에서도 서랍이 같이 밀림 [실측 B 10/06]).
"""
import dataclasses
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
    axis: str = "y"               # 끄는 방향: "y" 옆벽에서 / "x" 앞뒤 벽(손잡이 쪽·안쪽)에서 [사용자 10/10]
    shift_x_m: float = 0.0        # axis x 일 때 서랍 x 방향 이동 (부호 포함)
    wall_normal_x: float = 0.0    # axis x 일 때 가까운 앞뒤 벽 (+1 = x 최대 벽(안쪽), −1 = x 0 벽(손잡이 쪽))
    push_to_xy_m: Optional[tuple] = None   # 뒤에서 밀기 [사용자 10/11]: press_xy_m(시작 TCP) → 여기(끝 TCP)까지 닫은 손가락 옆면으로 밂
    push_dir: tuple = (0.0, 0.0)           # 미는 방향 (서랍 좌표 단위 벡터, 벽 쪽)


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
    reach = g.get("reach_x_max_mm")                   # 그리퍼 수직으로 닿는 깊이 한계(물체 가운데) — 아래 칸은 위 서랍장에 막힘 [사용자 10/10]
    if reach is not None and x_mm > reach:
        x_ok = False
    sign = 1.0 if y_mm > wd / 2 else -1.0
    gap = (wd - y_mm) if sign > 0 else y_mm
    gap += (g.get("wall_offset_mm") or {}).get("y_max" if sign > 0 else "y_min", 0.0)   # 실제 옆벽이 서랍 경계보다 바깥인 만큼 [실측 B 10/07]
    return (not x_ok), (ext_y + margin_mm) - gap, sign


def long_side_ok(*, target: Mapping, size_m: Sequence[float], interior_m: Sequence[float], g: Mapping) -> bool:
    """긴 변 양끝 잡기(닫힘 축 = 긴 변)가 그리퍼 최대 벌림 안이고 벽에 안 걸리는지 [사용자 10/10 "벽에 붙으면 긴 쪽으로"].
    여유는 기본 wall_margin_mm — 넛지 판단용 pick_wall_margin_mm(8)을 쓰면 손잡이 쪽 벽에 붙은 지우개가 시도도 안 함 [사용자 10/10 PC2].
    손잡이 쪽 벽(x 최소)에만 걸리면 기울여 잡기(front_tilt_x_mm)로 됨. g max_open_mm 가 없으면 쓰지 않음(False)."""
    max_open = g.get("max_open_mm")
    if max_open is None or size_m[0] * 1000.0 + g["open_margin_mm"] > max_open:
        return False
    cx, cy = target["pose"]["position"][:2]
    yaw = target["pose"]["yaw"]
    if not _finite(cx, cy, yaw, *size_m[:2], *interior_m[:2]):
        return False
    x_blocked, lack_mm, _ = _grasp_blocked(cx, cy, yaw + math.pi / 2, [size_m[1], size_m[0]] + list(size_m[2:]),
                                           interior_m, g, g["wall_margin_mm"])
    if lack_mm > 0:
        return False
    return not x_blocked or front_tilt_x_mm(target=target, size_m=size_m, interior_m=interior_m, g=g) is not None


def front_tilt_x_mm(*, target: Mapping, size_m: Sequence[float], interior_m: Sequence[float], g: Mapping) -> Optional[float]:
    """긴 변 양끝 잡기가 손잡이 쪽 벽(서랍 x 최소) 가까이면 그리퍼를 그 벽 쪽으로 기울여 잡을 TCP x (서랍 mm), 아니면 None.
    앞판이 테두리보다 높아 수직 그리퍼 몸통이 닿음 → 손끝은 벽 쪽, 몸통은 서랍 안쪽으로 눕힘 [사용자 10/10 "앞쪽 벽은 기울여서 잡으라고, 본체 닿는다"].
    가까움 = 짧은 변 잡기가 앞벽에 걸리는 거리(wall_extent_mm + pick_wall_margin_mm) 안. 손끝 자리는 기울여도 바닥에서 같다고 봄(반원 손끝) —
    TCP 는 벽에서 wall_extent_mm 이상, 물체 가운데가 그보다 벽 쪽이면 안쪽으로 밀되 물체 폭 절반 안에서만(손가락이 양끝 면에 닿게)."""
    cx = target["pose"]["position"][0]
    yaw = target["pose"]["yaw"]
    if not _finite(cx, yaw, *size_m[:2], interior_m[0]):
        return None
    x_mm = cx * 1000.0
    if x_mm >= interior_m[0] * 500.0:                      # 안쪽 벽 쪽 절반 — 앞판 아님
        return None
    if abs(math.sin(yaw)) < math.cos(math.radians(g.get("tilt_align_deg", 15.0))):
        return None                                         # 가로(긴 변이 손잡이 쪽 벽과 나란)일 때만 — 비스듬하면 대각선으로 눕게 됨 [사용자 10/10 "대각선 절대 안 됨"]
    open_mm = size_m[0] * 1000.0 + g["open_margin_mm"]
    ext_x = wall_extent_mm(open_mm, yaw, g)                  # 닫힘 축 = 긴 변(yaw) vs x 벽 법선
    short_x = wall_extent_mm(size_m[1] * 1000.0 + g["open_margin_mm"], yaw + math.pi / 2, g)   # 짧은 변 잡기 자리
    if x_mm >= max(ext_x, short_x) + g.get("pick_wall_margin_mm", g["wall_margin_mm"]):   # 짧은 변으로 잡을 수 있는 거리면 기울일 일 없음
        return None
    tcp = max(x_mm, ext_x)
    across = 1000.0 * (abs(math.cos(yaw)) * size_m[0] + abs(math.sin(yaw)) * size_m[1])   # 물체의 x 방향 폭(외접)
    return tcp if tcp - x_mm <= across / 2 else None


def _round_at_side(target, size_m, interior_m, g):
    """원통형이 옆벽에 붙어 짧은 변으로 못 잡는 자리면 (벽 부호, 긴 변 양끝이 앞뒤 벽에 걸림), 아니면 None.
    긴 변이 옆벽과 나란(tilt_align_deg 안)하고 최대 벌림 안일 때만. g max_open_mm 가 없으면 None."""
    max_open = g.get("max_open_mm")
    cx, cy = target["pose"]["position"][:2]
    yaw = target["pose"]["yaw"]
    if max_open is None or not _finite(cx, cy, yaw, *size_m[:2], *interior_m[:2]):
        return None
    if size_m[0] * 1000.0 + g["open_margin_mm"] > max_open or abs(math.cos(yaw)) < math.cos(math.radians(g.get("tilt_align_deg", 15.0))):
        return None
    reach = g.get("reach_x_max_mm")
    if reach is not None and cx * 1000.0 > reach:
        return None                                         # 아래 칸 깊은 곳: 옆으로 기울여도 위 서랍장에 막힘 → 축(x) 방향으로 손잡이 쪽 넛지
    sx_blocked, lack_mm, sign = _grasp_blocked(cx, cy, yaw, size_m, interior_m, g, g.get("pick_wall_margin_mm", g["wall_margin_mm"]))
    if lack_mm <= 0:
        return None
    ends_x_blocked, _, _ = _grasp_blocked(cx, cy, yaw + math.pi / 2, [size_m[1], size_m[0]] + list(size_m[2:]),
                                          interior_m, g, g["wall_margin_mm"])
    if sx_blocked and not ends_x_blocked:
        return None                                         # 짧은 변이 앞뒤 벽에도 걸림 — 옆벽만의 문제가 아님
    return sign, ends_x_blocked


def _round_edge(target, size_m, interior_m, g):
    """원통형이 가장자리(벽과 나란히, 짧은 변이 그 벽에 걸림 / 아래 칸 깊이 한계 너머)면 (기울일 쪽 서랍 방향 (x, y), 긴 변 양끝이 막힘), 아니면 None
    [사용자 10/10 "립밤 같은 원통형은 아래쪽이든 어디든 가장자리에 있으면 기울여 잡기"]. 옆벽은 _round_at_side 그대로,
    앞뒤 벽은 가로로 놓였을 때(서랍 y 와 tilt_align_deg 안) — 깊이 한계 너머면 안쪽 벽 쪽으로 (뒤로 20° 숙이면 끝까지 닿음 [사용자 10/10])."""
    r = _round_at_side(target, size_m, interior_m, g)
    if r:
        return (0.0, r[0]), r[1]
    max_open = g.get("max_open_mm")
    cx, cy = target["pose"]["position"][:2]
    yaw = target["pose"]["yaw"]
    if max_open is None or not _finite(cx, cy, yaw, *size_m[:2], *interior_m[:2]):
        return None
    if size_m[0] * 1000.0 + g["open_margin_mm"] > max_open or abs(math.sin(yaw)) < math.cos(math.radians(g.get("tilt_align_deg", 15.0))):
        return None
    x_blocked, _, _ = _grasp_blocked(cx, cy, yaw, size_m, interior_m, g, g.get("pick_wall_margin_mm", g["wall_margin_mm"]))
    if not x_blocked:
        return None
    reach = g.get("reach_x_max_mm")
    x_mm, d = cx * 1000.0, interior_m[0] * 1000.0
    sx = 1.0 if (reach is not None and x_mm > reach) or x_mm > d / 2 else -1.0
    _, ends_lack, _ = _grasp_blocked(cx, cy, yaw + math.pi / 2, [size_m[1], size_m[0]] + list(size_m[2:]), interior_m, g, g["wall_margin_mm"])
    return (sx, 0.0), ends_lack > 0


def round_edge_dir(*, target: Mapping, size_m: Sequence[float], interior_m: Sequence[float], g: Mapping) -> Optional[tuple]:
    """원통형 가장자리 기울여 잡기 방향 (서랍 (x, y), 축 하나만 ±1) — 긴 변 양끝이 막혀 넛지가 먼저면 None."""
    r = _round_edge(target, size_m, interior_m, g)
    return r[0] if r and not r[1] else None


def round_wall_side(*, target: Mapping, size_m: Sequence[float], interior_m: Sequence[float], g: Mapping) -> Optional[float]:
    """원통형(굴러가는 물체)이 옆벽(가생이)에 붙어 짧은 변으로 못 잡으면 그 벽 쪽 부호(−1 = y 0 벽, +1 = y 최대 벽), 아니면 None.
    넛지하면 굴러감 → 넛지 없이 긴 변 양끝을 잡고 그 벽 쪽으로 기울임 [사용자 10/10 PC2 립밤 왼벽 직접교시].
    긴 변 양끝이 앞뒤 벽에 걸리면(모서리) None — 모서리는 긴 변 방향으로 넛지 (plan_drag)."""
    r = _round_at_side(target, size_m, interior_m, g)
    return r[0] if r and not r[1] else None


def wall_blocks_grasp(*, target: Mapping, size_m: Sequence[float], interior_m: Sequence[float], g: Mapping) -> Optional[str]:
    """바로 집기 전 확인: 짧은 변으로 잡으면 손가락·관절이 서랍 벽에 닿는 자리면 이유 문자열, 아니면 None.
    plan_drag 와 같은 판단(_grasp_blocked) — 끌기 뒤 target_after 는 부족량 + extra_mm 만큼 옮겨져 통과 (#83 A 요청)."""
    cx, cy = target["pose"]["position"][:2]
    yaw = target["pose"]["yaw"]
    if not _finite(cx, cy, yaw, *size_m[:2], *interior_m[:2]):
        return f"위치·크기 값 비정상: {cx, cy, yaw, size_m, interior_m}"
    x_blocked, lack_mm, _ = _grasp_blocked(cx, cy, yaw, size_m, interior_m, g, g.get("pick_wall_margin_mm", g["wall_margin_mm"]))
    if x_blocked:
        return "앞뒤 벽에 걸려 짧은 변으로 못 잡음"
    if lack_mm > 0:
        return f"옆벽 쪽 여유 {lack_mm:.1f} mm 부족 — nudge_object 먼저"
    return None


@dataclass(frozen=True)
class AxisGrasp:
    """가로에 가까운 물체: 긴 변 양끝을 물체 각도대로 돌려 잡음 [사용자 10/10 "세로에 가까우면 짧은 변, 가로에 가까우면 긴 변"]."""
    open_mm: float                # 벌림 = 긴 변 + open_margin_mm
    expected_mm: float            # 잡은 폭 기대 = 긴 변
    tcp_xy_m: tuple               # 서랍 좌표 TCP (x, y)
    tilt_dir: Optional[tuple]     # 손잡이 쪽 벽에 가로로 붙으면 (−1, 0, 0) — 교시한 방향, 이때만 손가락을 서랍 y 에 맞춤. None = 수직
    drag: Optional[DragPlan]      # 먼저 넛지(needed, x 또는 y 로만) 또는 못 함(error_code). None = 바로 잡음
    reason: str


def is_crosswise(yaw: float) -> bool:
    """긴 변이 서랍 y(가로, 손잡이 쪽 벽과 나란)에 더 가까운지. 아니면 세로(서랍 x)."""
    return abs(math.sin(yaw)) > abs(math.cos(yaw))


def axis_grasp_fits(size_m: Sequence[float], g: Mapping) -> bool:
    """긴 변 + 벌림 여유가 최대 벌림 안인 물체만 (지우개·캐러멜·차키·립밤 — 몽키·망치·가림막은 짧은 변) [사용자 10/10]."""
    mo = g.get("max_open_mm")
    return mo is not None and size_m[0] * 1000.0 + g["open_margin_mm"] <= mo


def plan_axis_grasp(*, target: Mapping, size_m: Sequence[float], interior_m: Sequence[float], g: Mapping,
                    drag: Mapping) -> AxisGrasp:
    """가로에 가까운 물체의 긴 변 잡기 판단 [사용자 10/10]. 넛지는 서랍 x·y 방향으로만(대각선 없음).
    - 긴 변 끝 쪽(옆벽)에 손가락 자리가 모자라면 y 넛지.
    - 안쪽 벽(·아래 칸 깊이 한계)에 걸리면 손잡이 쪽 x 넛지. 손잡이 쪽은 안쪽으로 밀면 서랍이 끌려 넛지 안 함.
    - 손잡이 쪽 벽 가까이(front_tilt_within_mm)면 손잡이 쪽으로 기울여 잡음 — 가로(tilt_align_deg 안)일 때만, 아니면 멈춤."""
    cx, cy = target["pose"]["position"][:2]
    yaw = target["pose"]["yaw"]
    if not _finite(cx, cy, yaw, *size_m[:3], *interior_m[:2]):
        raise ValueError(f"집기 입력 비정상: {cx, cy, yaw, size_m, interior_m}")
    length = size_m[0] * 1000.0
    open_mm = length + g["open_margin_mm"]
    d, wd = interior_m[0] * 1000.0, interior_m[1] * 1000.0
    x_mm, y_mm = cx * 1000.0, cy * 1000.0
    off = g.get("wall_offset_mm") or {}
    margin = g.get("pick_wall_margin_mm", g["wall_margin_mm"])          # 애매하면 넛지로 확실히 [사용자 10/10]
    need_x = wall_extent_mm(open_mm, yaw, g) + margin                   # 닫힘 축 = 긴 변(yaw) — 앞뒤 벽까지 필요한 거리
    need_y = wall_extent_mm(open_mm, yaw - math.pi / 2, g) + margin     # 옆벽까지
    gy = {"y_min": y_mm + off.get("y_min", 0.0), "y_max": wd - y_mm + off.get("y_max", 0.0)}
    near_y = min(gy, key=gy.get)
    reach = g.get("reach_x_max_mm")
    zone = max(need_x, g.get("front_tilt_within_mm") or 0.0)
    aligned = abs(math.cos(yaw)) <= math.sin(math.radians(g.get("tilt_align_deg", 15.0)))
    if x_mm < zone and not aligned:                                     # 손잡이 쪽 비스듬: 손잡이 쪽 벽까지 끌어 눕히기가 먼저, 옆벽(y)은 그 뒤
        dp = _push_to_handle_wall(cx, cy, yaw, size_m, interior_m, g, drag, x_mm / 1000.0)   # [사용자 10/10 "손잡이 벽 먼저 → 가운데"]
        if dp is not None and dp.needed:
            return AxisGrasp(open_mm, length, (cx, cy), None, dp, "가로 — " + dp.reason)
    if need_y > gy[near_y]:                                             # 옆벽 → y 로 넛지
        sign = 1.0 if near_y == "y_max" else -1.0
        dp = _plan_drag_y(cx, cy, yaw, size_m, interior_m, g, drag, margin, need_y - gy[near_y], sign,
                          press_x_lim_mm=_press_x_lim(g, drag))
        return AxisGrasp(open_mm, length, (cx, cy), None, dp, "가로 — " + dp.reason)
    if d - x_mm < need_x or (reach is not None and x_mm > reach):       # 안쪽 벽·깊이 한계 → 손잡이 쪽으로 x 넛지
        dp = _plan_drag_x(cx, cy, yaw, size_m, interior_m, g, drag, margin, ext_x_mm=need_x - margin)
        return AxisGrasp(open_mm, length, (cx, cy), None, dp, "가로 — " + dp.reason)
    if x_mm >= zone:
        return AxisGrasp(open_mm, length, (cx, cy), None, None, f"가로 — 긴 변 양끝 (벌림 {open_mm:.1f} mm)")
    along = g["wall_clearance_mm"]["along_mm"]
    ext_x = abs(math.cos(yaw)) * length + abs(math.sin(yaw)) * size_m[1] * 1000.0
    if not aligned:
        dp = _push_to_handle_wall(cx, cy, yaw, size_m, interior_m, g, drag, x_mm / 1000.0)
        if dp is not None:
            return AxisGrasp(open_mm, length, (cx, cy), None, dp, "가로 — " + dp.reason)
    if not aligned or along - x_mm > ext_x / 2:
        dp = DragPlan(False, NO_PUSH_ACCESS, 0.0, None, 0.0, x_mm / 1000.0,
                      "손잡이 쪽 벽에 " + ("비스듬히 붙음 — 기울여 잡기는 가로일 때만, 안쪽 넛지는 서랍이 끌려 안 함" if not aligned
                                         else "너무 붙음 — 기울여도 손가락 자리 없음"), axis="x", wall_normal_x=-1.0)
        return AxisGrasp(open_mm, length, (cx, cy), None, dp, dp.reason)
    tcp_x = max(x_mm, along)                                            # 손끝이 벽에 닿을 만큼 붙었으면 TCP 를 안쪽으로 (물체 폭 절반 안)
    return AxisGrasp(open_mm, length, (tcp_x / 1000.0, cy), (-1.0, 0.0, 0.0), None,
                     f"가로 — 손잡이 쪽 벽에 붙음, 손잡이 쪽으로 기울여 긴 변 양끝 (벌림 {open_mm:.1f} mm)")


def plan_drag(*, target: Mapping, size_m: Sequence[float], interior_m: Sequence[float], g: Mapping,
              drag: Mapping) -> DragPlan:
    """벽에 붙어 짧은 변으로 못 잡는 물체를 끌 거리와 누를 점. 이미 잡을 수 있으면 needed False.
    우선순위 [사용자 10/10, 지우개 기준]: 가운데 → 그냥 집기 / 가장자리·모서리 → 넛지(옆벽은 옆으로, 앞뒤 벽은 앞뒤로) →
    넛지를 못 하면 긴 변 양끝으로 집기(needed False 로 돌려 집기로 넘어감)."""
    if g.get("round"):
        return _plan_drag_round(target=target, size_m=size_m, interior_m=interior_m, g=g, drag=drag)
    r = None
    if r and not r[1]:
        return DragPlan(False, None, 0.0, None, r[0], 0.0, "원통형이 옆벽에 붙음 — 넛지하면 굴러감 → 긴 변 양끝을 벽 쪽으로 기울여 집기")
    if r:                                                   # 모서리: 긴 변 방향(서랍 x)으로만 끎 — 짧은 변 방향(y)으로 밀면 굴러감 [사용자 10/10]
        return _plan_drag_round_corner(target, size_m, interior_m, g, drag, r[0])
    if (g.get("axis_grasp") and not g.get("round") and axis_grasp_fits(size_m, g)
            and is_crosswise(target["pose"]["yaw"])):       # 가로에 가까우면 긴 변 [사용자 10/10]
        ag = plan_axis_grasp(target=target, size_m=size_m, interior_m=interior_m, g=g, drag=drag)
        return ag.drag or DragPlan(False, None, 0.0, None, 0.0, 0.0, "끌지 않아도 잡을 수 있음 — " + ag.reason)
    p = _plan_drag(target=target, size_m=size_m, interior_m=interior_m, g=g, drag=drag)
    if p.error_code and long_side_ok(target=target, size_m=size_m, interior_m=interior_m, g=g):
        return DragPlan(False, None, 0.0, None, p.wall_normal_y, p.clearance_before_m,
                        f"넛지 못 함({p.reason}) → 긴 변 양끝으로 집기", axis=p.axis, wall_normal_x=p.wall_normal_x)
    return p


def _round_push_to_wall(target, size_m, interior_m, g, drag):
    """원통형이 벽 근처에 비스듬히 있어 못 잡으면: 가장 가까운 벽(손잡이 쪽·옆벽 — 안쪽 벽은 서랍 닫히는 방향이라 안 씀) 쪽으로
    밀어 벽에 맞춰 눕힘 [사용자 10/10 "립밤도 애매하게 벽에 기울어져 있으면 벽 끝까지 닿게 만들어서 집기"]. 벽이 막아 더 안 구름.
    누르는 TCP 는 그 벽 쪽 기울인 교시 자세 한계(wall_tcp_min_mm) 밖 — 가운데가 거기까지 오면 벽과 약 10° 안으로 눕는다고 봄 → 다시 보고 가장자리 기울여 잡기."""
    if not drag.get("square_to_handle_wall"):
        return None
    cx, cy = target["pose"]["position"][:2]
    yaw = target["pose"]["yaw"]
    c, s = abs(math.cos(yaw)), abs(math.sin(yaw))
    length, width = size_m[0] * 1000.0, size_m[1] * 1000.0
    half_x, half_y = (length * c + width * s) / 2, (length * s + width * c) / 2
    x_mm, y_mm, wd = cx * 1000.0, cy * 1000.0, interior_m[1] * 1000.0
    off = g.get("wall_offset_mm") or {}
    tmin = g.get("wall_tcp_min_mm") or {}
    walls = {"x_min": x_mm - half_x, "y_min": y_mm + off.get("y_min", 0.0) - half_y, "y_max": wd - y_mm + off.get("y_max", 0.0) - half_y}
    reach = g.get("reach_x_max_mm")
    if reach is not None and x_mm > reach:
        walls.pop("y_min"), walls.pop("y_max")             # 깊은 곳은 옆벽에 붙여도 못 잡음
    w = min(walls, key=walls.get)
    if "x_min" in walls and walls["x_min"] < (g.get("front_tilt_within_mm") or 0.0):
        w = "x_min"                                         # 손잡이 쪽 가까우면 손잡이 쪽 벽 먼저 (구석이면 그 뒤 축 방향 y) [사용자 10/10 지우개와 같은 순서]
    gap_m = walls[w] / 1000.0
    radius = width / 2
    if drag.get("push_from_behind"):
        n = (-1.0, 0.0) if w == "x_min" else ((0.0, -1.0) if w == "y_min" else (0.0, 1.0))
        bp = _behind_push(cx, cy, yaw, size_m, interior_m, g, drag, n, radius - (0.0 if w == "x_min" else off.get(w, 0.0)), radius, gap_m,
                          "원통형을 " + ("손잡이 쪽 벽" if w == "x_min" else "옆벽") + "까지 굴려 눕히기")
        if bp is not None:
            return bp
    if w == "x_min":
        end = max(radius, tmin.get("x_min", drag["wall_tcp_min_mm"]))
        shift = min(end - x_mm, -drag.get("square_min_push_mm", 2.0)) / 1000.0
        press = (cx, cy)
        p = DragPlan(True, None, 0.0, press, 0.0, gap_m, f"원통형이 손잡이 쪽 벽에 비스듬히 → 벽까지 x {shift * 1000:+.1f} mm 밀어 눕히기",
                     axis="x", shift_x_m=shift, wall_normal_x=-1.0)
    else:
        sign = -1.0 if w == "y_min" else 1.0
        o = off.get(w, 0.0)
        end = max(radius - o, tmin.get(w, drag["wall_tcp_min_mm"]))     # 서랍 경계에서 가운데까지
        cur = y_mm if sign < 0 else wd - y_mm
        shift = sign * -min(end - cur, -drag.get("square_min_push_mm", 2.0)) / 1000.0
        p = DragPlan(True, None, shift, (cx, cy), sign, gap_m, f"원통형이 옆벽에 비스듬히 → 벽까지 y {shift * 1000:+.1f} mm 밀어 눕히기")
    n = math.hypot(p.shift_x_m, p.shift_y_m)
    lim = drag["max_shift_mm"] / 1000.0
    if n > lim:                                             # 멀면 최대 거리만 밀고 다시 보고 또 밂
        p = dataclasses.replace(p, shift_x_m=p.shift_x_m * lim / n, shift_y_m=p.shift_y_m * lim / n,
                                reason=p.reason + f" (최대 {drag['max_shift_mm']:.0f} mm 만, 다시 보고 이어서)")
    return p


def _plan_drag_round(*, target: Mapping, size_m: Sequence[float], interior_m: Sequence[float], g: Mapping,
                     drag: Mapping) -> DragPlan:
    """원통형(립밤): 굴러가서 축과 다른 방향으로는 넛지하지 않음 [사용자 10/10 "짧은 변 쪽으로 넛지하면 굴러다님"].
    ① 긴 변 양끝으로 바로 잡히면 넛지 없음 ② 옆벽에 나란히 붙음 → 넛지 없이 기울여 잡기 ③ 구석 → 축(서랍 x) 방향으로만
    ④ 그 밖에 넛지가 필요하면 축 방향(30° 안)일 때만, 아니면 멈춤."""
    e = _round_edge(target, size_m, interior_m, g)
    if e and not e[1]:
        return DragPlan(False, None, 0.0, None, e[0][1], 0.0, "원통형이 가장자리에 붙음 — 넛지하면 굴러감 → 긴 변 양끝을 벽 쪽으로 기울여 집기",
                        axis="y" if e[0][1] else "x", wall_normal_x=e[0][0])
    if e and e[0][1]:                                       # 옆벽 모서리: 긴 변 방향(서랍 x)으로만 끎 — 짧은 변 방향(y)으로 밀면 굴러감 [사용자 10/10]
        return _plan_drag_round_corner(target, size_m, interior_m, g, drag, e[0][1])
    if e:                                                   # 앞뒤 벽 모서리(가로): 긴 변 방향(서랍 y)으로만 — 옆벽에서 떼기
        cx, cy = target["pose"]["position"][:2]
        yaw = target["pose"]["yaw"]
        _, lack, sign = _grasp_blocked(cx, cy, yaw + math.pi / 2, [size_m[1], size_m[0]] + list(size_m[2:]), interior_m, g, g["wall_margin_mm"])
        return _plan_drag_y(cx, cy, yaw, size_m, interior_m, g, drag, g["wall_margin_mm"], lack, sign,
                            press_x_lim_mm=_press_x_lim(g, drag))
    if long_side_ok(target=target, size_m=size_m, interior_m=interior_m, g=g):
        return DragPlan(False, None, 0.0, None, 0.0, 0.0, "원통형 — 긴 변 양끝으로 바로")
    yaw = target["pose"]["yaw"]
    if min(abs(math.cos(yaw)), abs(math.sin(yaw))) > math.sin(math.radians(g.get("tilt_align_deg", 15.0))):
        sq = _round_push_to_wall(target, size_m, interior_m, g, drag)   # 비스듬 → 가까운 벽에 붙여 눕힌 뒤 가장자리 기울여 잡기
        if sq is not None:
            return sq
    p = _plan_drag(target=target, size_m=size_m, interior_m=interior_m, g=g, drag=dict(drag, square_to_handle_wall=False))
    if p.needed:
        yaw = target["pose"]["yaw"]
        v = (p.shift_x_m, p.shift_y_m)
        n = math.hypot(*v)
        if n and abs(math.cos(yaw) * v[0] + math.sin(yaw) * v[1]) / n < math.cos(math.radians(30.0)):
            return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, p.wall_normal_y, p.clearance_before_m,
                            f"원통형 — 넛지 방향이 축과 달라 굴러감, 넛지 안 함 ({p.reason})", axis=p.axis, wall_normal_x=p.wall_normal_x)
    return p


def _plan_drag(*, target: Mapping, size_m: Sequence[float], interior_m: Sequence[float], g: Mapping,
               drag: Mapping) -> DragPlan:
    cx, cy = target["pose"]["position"][:2]
    yaw = target["pose"]["yaw"]
    if not _finite(cx, cy, yaw, *size_m[:3], *interior_m[:2]):
        raise ValueError(f"끌기 입력 비정상: {cx, cy, yaw, size_m, interior_m}")
    margin = g.get("pick_wall_margin_mm", g["wall_margin_mm"])   # 집기 판단 여유 [사용자 10/10 "애매한 자리는 넛지로 확실히"]
    x_blocked, lack_mm, sign = _grasp_blocked(cx, cy, yaw, size_m, interior_m, g, margin)
    wd = interior_m[1] * 1000.0
    gap_m = ((wd - cy * 1000.0) if sign > 0 else cy * 1000.0) / 1000.0
    if lack_mm <= 0 and not x_blocked:
        return DragPlan(False, None, 0.0, None, sign, gap_m, "끌지 않아도 잡을 수 있음")
    if x_blocked:
        # 1순위: 앞뒤 벽(·깊이 한계) — 그 벽 쪽으로 기울여 눌러 가운데 쪽(x)으로 [사용자 10/10 "손잡이 쪽에서 안으로 끌기가 1순위"]
        px = _plan_drag_x(cx, cy, yaw, size_m, interior_m, g, drag, margin)
        if px.needed:
            return px
        # 안 되면: 긴 변이 옆벽에만 걸리면 옆으로 끌어 긴 변 양끝으로 잡게 [사용자 10/10 "가로로 끌고 와서 가로로 잡기"]
        lxb, llack, lsign = True, 0.0, sign
        if g.get("max_open_mm") is not None and size_m[0] * 1000.0 + g["open_margin_mm"] <= g["max_open_mm"]:
            lxb, llack, lsign = _grasp_blocked(cx, cy, yaw + math.pi / 2, [size_m[1], size_m[0]], interior_m, g, margin)
        if (lxb and front_tilt_x_mm(target=target, size_m=size_m, interior_m=interior_m, g=g) is None) or llack <= 0:
            return px                                       # 손잡이 쪽 벽에 가로로 붙은 건 끈 뒤 기울여 긴 변으로 잡음 (front_tilt_x_mm)
        lack_mm, sign = llack, lsign
        gap_m = ((wd - cy * 1000.0) if sign > 0 else cy * 1000.0) / 1000.0
    return _plan_drag_y(cx, cy, yaw, size_m, interior_m, g, drag, margin, lack_mm, sign)

def _press_x_lim(g, drag):
    """옆벽에서 y 로 끌 때 누르는 TCP 를 앞뒤 벽에서 떼는 거리. 손끝 실측(along 9 + 여유 3 = 12)이면 손잡이 쪽 벽에 가로로 붙은 지우개를
    누를 때 그리퍼 몸통이 손잡이 쪽 벽에 약 3 mm 닿음 [사용자 10/11 PC2] → drag.press_x_lim_mm (몸통이 손끝보다 두꺼움)."""
    return drag.get("press_x_lim_mm") or (g["wall_clearance_mm"]["along_mm"] + g["wall_margin_mm"])


def _plan_drag_y(cx, cy, yaw, size_m, interior_m, g, drag, margin, lack_mm, sign, press_x_lim_mm=None):
    """옆벽(sign 쪽)에서 가운데 쪽으로 lack_mm + extra_mm 만큼 서랍 y 로 끌 거리와 누를 점.
    press_x_lim_mm: 누르는 TCP 를 앞뒤 벽에서 이만큼 이상 떼어 놓음 (손잡이 쪽 구석 등) — 물체 안이어야 함."""
    wd = interior_m[1] * 1000.0
    gap_m = ((wd - cy * 1000.0) if sign > 0 else cy * 1000.0) / 1000.0
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
    half_w = abs(size_m[0] * 500.0 * math.sin(yaw)) + abs(size_m[1] * 500.0 * math.cos(yaw))   # 물체가 y 로 차지하는 반 (돌아간 물체 포함)
    center = (wd - cy * 1000.0) if sign > 0 else cy * 1000.0
    tcp = max(need_mm, center + low_off)                    # 가능하면 가장 낮은 점이 물체 중심에
    contact = tcp - low_off
    if not (center - half_w + drag["press_inset_mm"] <= contact <= center + half_w - drag["press_inset_mm"]):
        return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, sign, gap_m,
                        f"누를 점이 물체 밖 (벽에서 TCP {tcp:.1f}, 접촉 {contact:.1f}, 물체 {center - half_w:.1f}~{center + half_w:.1f} mm)"
                        " — 기울기를 줄이거나 0으로")
    px = cx * 1000.0
    if press_x_lim_mm is not None:
        px = min(max(px, press_x_lim_mm), interior_m[0] * 1000.0 - press_x_lim_mm)
        half_x = abs(size_m[0] * 500.0 * math.cos(yaw)) + abs(size_m[1] * 500.0 * math.sin(yaw))
        if abs(px - cx * 1000.0) > half_x - drag["press_inset_mm"]:
            return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, sign, gap_m,
                            f"구석: 앞뒤 벽에서 누를 자리가 물체 밖 (TCP x {px:.1f}, 물체 {cx * 1000 - half_x:.1f}~{cx * 1000 + half_x:.1f} mm)")
    press = (px / 1000.0, cy + sign * (center - tcp) / 1000.0)
    return DragPlan(True, None, shift, press, sign, gap_m,
                    f"옆벽 쪽 부족 {lack_mm:.1f} mm → y {shift * 1000:+.1f} mm 끌기")


def _behind_push(cx, cy, yaw, size_m, interior_m, g, drag, n, end_center_mm, end_half_mm, gap_m, reason):
    """벽까지 밀기를 위에서 눌러 끌기 대신 물체 뒤에서 닫은 손가락 옆면으로 밂 [사용자 10/11 PC2: 눌러 끌면 미끄러지고 벽에 잘 안 붙음 —
    손잡이 쪽 비스듬한 지우개 15.5 mm 끌었는데 13 mm·12° 만 돎]. 그리퍼 수직, 닫힘 축은 미는 방향에 수직(손가락 두 개가 나란히),
    손끝은 바닥 위 push_tip_above_floor_mm. n = 미는 방향(벽 쪽, 서랍 좌표 단위 벡터 — x 0 벽 (−1, 0) 또는 옆벽 (0, ±1)).
    시작 TCP = 물체 뒤 끝 + 손가락 옆면까지(along_mm) + push_start_gap_mm. 끝 TCP = 물체가 벽에 붙어 누운 자리(가운데 end_center_mm,
    미는 방향 반 end_half_mm) 뒤 + push_over_mm 더 (힘으로 끝을 찾지 않고 이 거리만 [사용자 10/11]). 물체 이동은 최대 max_shift_mm.
    손가락이 옆벽·뒤쪽 벽·깊이 한계에 걸리거나 미는 줄이 물체 밖이면 None (예전 방식)."""
    nx, ny = n
    L, W = interior_m[0] * 1000.0, interior_m[1] * 1000.0
    x, y = cx * 1000.0, cy * 1000.0
    c, s = math.cos(yaw), math.sin(yaw)
    half_n = abs(size_m[0] * 500.0 * (c * nx + s * ny)) + abs(size_m[1] * 500.0 * (-s * nx + c * ny))     # 물체가 미는 방향으로 차지하는 반
    half_t = abs(size_m[0] * 500.0 * (c * ny - s * nx)) + abs(size_m[1] * 500.0 * (s * ny + c * nx))      # 옆(손가락 나란한 방향)
    face = g["wall_clearance_mm"]["along_mm"]                      # TCP → 닫은 손가락 옆면 (닫힘 축이 벽과 나란할 때 벽 거리 실측 9.0)
    w = g["wall_clearance_mm"]["across"]
    side = interp(0.9, w["open_mm"], w["dist_mm"]) + g["wall_margin_mm"]   # 닫힘 축 쪽 벽까지 (닫힘 21.6 + 여유)
    gap, over = drag.get("push_start_gap_mm", 10.0), drag.get("push_over_mm", 2.0)
    reach = g.get("reach_x_max_mm")
    along_n, lat_c, lat_len = (x, y, W) if nx else (y if ny < 0 else W - y, x, L)   # 벽에서 가운데까지, 옆 좌표
    lat = min(max(lat_c, side), lat_len - side)                    # 손가락이 옆(닫힘 축 쪽) 벽에 안 닿게
    if abs(lat - lat_c) > half_t - drag["press_inset_mm"]:
        return None                                                # 미는 줄이 물체 밖
    start_d = along_n + half_n + face + gap                        # 벽에서 시작 TCP
    want = max(along_n - end_center_mm, drag.get("square_min_push_mm", 2.0))   # 물체 가운데 이동 — 이미 벽에 닿아 있어도 조금 밀어 돌려 눕힘
    move = min(want, drag["max_shift_mm"])
    if move < want:                                                # 멀면 최대 거리만 밀고 다시 보고 이어서
        end_d = start_d - gap - move - max(0.0, half_n - end_half_mm)
    else:
        end_d = end_center_mm + end_half_mm + face - over
    behind = (L if nx else W) - start_d - face - g["wall_margin_mm"]   # 시작 자리 뒤 손가락 ↔ 반대쪽 벽
    if behind < 0 or end_d >= start_d - gap:
        return None

    def pt(d):                                                     # 벽에서 d, 옆 lat → 서랍 좌표 m
        if nx:
            return (d / 1000.0, lat / 1000.0)
        return (lat / 1000.0, (d if ny < 0 else W - d) / 1000.0)
    start, stop = pt(start_d), pt(end_d)
    if reach is not None and max(start[0], stop[0]) * 1000.0 > reach + 20.0:
        return None                                                # 아래 칸 위 서랍장 — 수직으로 바닥 닿는 깊이 약 149 (= reach + 20)
    shift = (nx * move / 1000.0, ny * move / 1000.0)
    return DragPlan(True, None, shift[1], start, ny, gap_m, f"뒤에서 밀어 {reason} ({'x' if nx else 'y'} {move * (nx or ny):+.1f} mm)",
                    axis="x" if nx else "y", shift_x_m=shift[0], wall_normal_x=nx, push_to_xy_m=stop, push_dir=(nx, ny))

def _push_to_handle_wall(cx, cy, yaw, size_m, interior_m, g, drag, gap_m):
    """손잡이 쪽 벽 근처에 비스듬히 놓여 못 잡을 때: 손잡이 쪽(x −, 서랍 여는 방향이라 끝까지 열린 서랍은 안 끌림)으로 벽까지 끌어
    벽에 맞춰 눕힘 [사용자 10/10 "손잡이 쪽 벽 끝까지 붙게 넛지하면 수평이 됨 → 기울여 잡기"]. 가로에 가까우면 가로로(가운데 = 짧은 변 반),
    세로에 가까우면 세로로(가운데 = 긴 변 반) 붙는다고 봄 → 다시 보고 가로면 기울여 긴 변, 세로면 짧은 변.
    누르는 TCP 는 손잡이 쪽 벽 쪽으로 기울인 교시 자세의 한계(wall_tcp_min_mm x_min) 밖, 옆벽에서 손가락 자리 밖."""
    if not drag.get("square_to_handle_wall"):
        return None
    half = size_m[1 if is_crosswise(yaw) else 0] * 500.0              # 벽에 붙어 누운 뒤 가운데 x
    if drag.get("push_from_behind"):
        bp = _behind_push(cx, cy, yaw, size_m, interior_m, g, drag, (-1.0, 0.0), half, half, gap_m,
                          f"손잡이 쪽 벽까지 {'가로' if is_crosswise(yaw) else '세로'}로 붙이기")
        if bp is not None:
            return bp
    wall_min = (g.get("wall_tcp_min_mm") or {}).get("x_min", drag["wall_tcp_min_mm"])
    end_x = max(half, wall_min)
    # 이미 모서리가 벽에 닿아 있어도 최소 이만큼은 밀어 돌려 눕힘. 더 못 가면 옆 힘 한계(PUSH_BLOCKED)에서 멈춤 → 다시 보고 집기
    shift = min(end_x - cx * 1000.0, -drag.get("square_min_push_mm", 2.0)) / 1000.0
    if -shift > drag["max_shift_mm"] / 1000.0:
        return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, 0.0, gap_m, f"손잡이 쪽 벽까지 {-shift * 1000:.0f} mm — 최대보다 큼",
                        axis="x", wall_normal_x=-1.0)
    off = g.get("wall_offset_mm") or {}
    along = g["wall_clearance_mm"]["along_mm"] + g["wall_margin_mm"]
    wd, y_mm = interior_m[1] * 1000.0, cy * 1000.0
    y_tcp = min(max(y_mm, along - off.get("y_min", 0.0)), wd - (along - off.get("y_max", 0.0)))
    half_y = abs(size_m[0] * 500.0 * math.sin(yaw)) + abs(size_m[1] * 500.0 * math.cos(yaw))
    if abs(y_tcp - y_mm) > half_y - drag["press_inset_mm"]:
        return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, 0.0, gap_m, "손잡이 쪽 구석: 옆벽에서 누를 자리가 물체 밖",
                        axis="x", wall_normal_x=-1.0)
    how = "가로" if is_crosswise(yaw) else "세로"
    return DragPlan(True, None, 0.0, (cx, y_tcp / 1000.0), 0.0, gap_m,
                    f"손잡이 쪽 벽에 비스듬히 → 벽까지 x {shift * 1000:+.1f} mm 끌어 {how}로 붙이기", axis="x", shift_x_m=shift,
                    wall_normal_x=-1.0)


def _plan_drag_x(cx, cy, yaw, size_m, interior_m, g, drag, margin, ext_x_mm=None):
    """앞뒤 벽(손잡이 쪽 x 0 / 안쪽 x 최대)에 걸려 짧은 변으로 못 잡을 때 서랍 x 로 끌 거리와 누를 점 (close_axis wall 방식).
    깊이 한계(g reach_x_max_mm, 아래 칸)를 넘으면 안쪽 벽 쪽에서 눌러 손잡이 쪽으로 [사용자 10/10 "뒤로 기울여 안쪽으로 땡기기"]."""
    d = interior_m[0] * 1000.0
    x_mm = cx * 1000.0
    ext_x = ext_x_mm if ext_x_mm is not None else wall_extent_mm(size_m[1] * 1000.0 + g["open_margin_mm"], yaw + math.pi / 2, g)
    sx = 1.0 if x_mm > d / 2 else -1.0
    gap = (d - x_mm) if sx > 0 else x_mm
    lack = (ext_x + margin) - gap
    reach = g.get("reach_x_max_mm")
    if reach is not None and x_mm > reach:
        sx, lack = 1.0, max(lack if sx > 0 else 0.0, x_mm - reach)
        gap = d - x_mm
    gap_m = gap / 1000.0
    if sx < 0 and not drag.get("push_inward_ok", False):   # 손잡이 쪽 벽: 안쪽(x +)으로 끌면 서랍이 같이 닫힐 수 있음 [사용자 10/10]
        aligned = min(abs(math.sin(yaw)), abs(math.cos(yaw))) <= math.sin(math.radians(g.get("tilt_align_deg", 15.0)))
        sq = None if aligned else _push_to_handle_wall(cx, cy, yaw, size_m, interior_m, g, drag, gap_m)
        if sq is not None:
            return sq
        return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, 0.0, gap_m,
                        "손잡이 쪽 벽에 붙음 — 안쪽으로 끌면 서랍이 닫혀서 넛지 안 함", axis="x", wall_normal_x=sx)
    shift = -sx * (lack + drag["extra_mm"]) / 1000.0
    if not abs(shift) <= drag["max_shift_mm"] / 1000.0:
        return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, 0.0, gap_m, f"앞뒤로 끌 거리 {abs(shift) * 1000:.0f} mm가 최대보다 큼",
                        axis="x", wall_normal_x=sx)
    wall_min = (g.get("wall_tcp_min_mm") or {}).get("x_max" if sx > 0 else "x_min", drag["wall_tcp_min_mm"])
    need = wall_min + drag.get("wall_press_margin_mm", margin)
    half = abs(size_m[0] * 500.0 * math.cos(yaw)) + abs(size_m[1] * 500.0 * math.sin(yaw))   # 물체가 x 로 차지하는 반
    tcp = max(need, gap)
    if not (gap - half + drag["press_inset_mm"] <= tcp <= gap + half - drag["press_inset_mm"]):
        return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, 0.0, gap_m,
                        f"앞뒤 벽 쪽 누를 점이 물체 밖 (벽에서 TCP {tcp:.1f}, 물체 {gap - half:.1f}~{gap + half:.1f} mm)",
                        axis="x", wall_normal_x=sx)
    press = (cx + sx * (gap - tcp) / 1000.0, cy)
    where = "안쪽 벽" if sx > 0 else "손잡이 쪽 벽"
    return DragPlan(True, None, 0.0, press, 0.0, gap_m, f"{where} 쪽 부족 {lack:.1f} mm → x {shift * 1000:+.1f} mm 끌기",
                    axis="x", shift_x_m=shift, wall_normal_x=sx)


def _plan_drag_round_corner(target, size_m, interior_m, g, drag, side):
    """원통형이 옆벽 + 앞뒤 벽 모서리: 긴 변 양끝 잡기가 앞뒤 벽에 안 걸릴 만큼 서랍 x 로만 끎 (굴러가지 않는 방향) [사용자 10/10].
    누르는 TCP y 는 옆벽에서 손가락 자리(along_mm, 닫힘 축이 옆벽과 나란) + 여유 이상, 물체 폭 안."""
    cx, cy = target["pose"]["position"][:2]
    yaw = target["pose"]["yaw"]
    margin = g["wall_margin_mm"]
    ext_ends = wall_extent_mm(size_m[0] * 1000.0 + g["open_margin_mm"], yaw, g)   # 긴 변 양끝 잡기의 앞뒤 벽 자리
    p = _plan_drag_x(cx, cy, yaw, size_m, interior_m, g, drag, margin, ext_x_mm=ext_ends)
    if not p.needed:
        return p
    wd, y_mm = interior_m[1] * 1000.0, cy * 1000.0
    off = (g.get("wall_offset_mm") or {}).get("y_max" if side > 0 else "y_min", 0.0)
    lim = g["wall_clearance_mm"]["along_mm"] + margin - off
    y_tcp = min(y_mm, wd - lim) if side > 0 else max(y_mm, lim)
    half_y = 1000.0 * (abs(size_m[0] * math.sin(yaw)) + abs(size_m[1] * math.cos(yaw))) / 2.0
    if abs(y_tcp - y_mm) > half_y - drag["press_inset_mm"]:
        return DragPlan(False, NO_PUSH_ACCESS, 0.0, None, side, p.clearance_before_m,
                        f"모서리 원통형: 옆벽에서 누를 자리가 물체 밖 (TCP y {y_tcp:.1f}, 물체 {y_mm - half_y:.1f}~{y_mm + half_y:.1f} mm)",
                        axis="x", wall_normal_x=p.wall_normal_x)
    return dataclasses.replace(p, press_xy_m=(p.press_xy_m[0], y_tcp / 1000.0), wall_normal_y=side,
                               reason="원통형 모서리 — 긴 변 방향으로만 " + p.reason)


# ---------- 놓기 ----------
def place_tcp_above_floor_m(grasp_tcp_above_floor_m: float, drop_m: float) -> float:
    """집을 때 TCP 높이 그대로 + drop_m 위에서 놓음 → 물체 바닥이 drop_m 만큼 떠서 놓임."""
    return grasp_tcp_above_floor_m + drop_m
