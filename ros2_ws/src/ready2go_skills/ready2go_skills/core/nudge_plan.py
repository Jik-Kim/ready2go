"""`nudge_object` 판단: 밀지 말지·어느 방향으로·얼마나 (#37, FR-ACT-05, ROS 비의존·pytest 대상).

docs/domain.md 8.5: 두 파지 방향 중 하나라도 손가락 여유가 있으면 밀지 않는다(`pushed: false`).
아니면 벽에서 멀어지는 방향으로 (필요 거리 + 여유)만큼 민다. 1회 호출 = 1회 밀기.

좌표 (서랍 좌표계 `drawer_<id>`, `inspect_region` pose와 같은 기준):
  x ∈ [0, depth], y ∈ [0, width] — `places.yaml`의 `interior_m` = [깊이, 폭, 높이] 순서를 따름.
  원점 = 서랍 안쪽 바닥 모서리. 어느 모서리인지는 #6 3점 터치 규약과 맞출 것 [팀 확정 필요].
물체: 중심 (x, y), `yaw`(서랍 x축 기준, rad), 크기 `size_m`[0]·[1] = 물체 로컬 x·y 길이(온톨로지 규약).
`yaw_valid`(`inspect_region` pose, runner.md 7.1)가 True가 아니면(false·없음) yaw를 믿을 수 없어 판단하지 않고
`YAW_INVALID`을 반환한다 — false일 때 yaw 0은 자리표시라 그대로 쓰면 엉뚱한 밀기 계획이 나온다(#15).
대칭 물체는 비전이 `yaw_valid: true`로 내므로 그대로 진행. 다시 인식은 태스크(C)가 1회 한다.
벽·손가락은 축 정렬 직사각형(AABB)으로 근사한다 — yaw가 있으면 보수적(실제보다 덜 들어간다고 판단).

손가락 치수·여유 값은 모두 실측 전이라 `GripperGeometry`로 받는다 [팀 확정 필요, #37 실측 항목].
TODO(B): 노드가 config/ 에서 읽어 넘기기, 닫은 손가락 폭(미는 방향에 수직)이 옆 벽에 걸리는지 검사.
"""
import math
from dataclasses import dataclass
from typing import Optional

NO_PUSH_ACCESS = "NO_PUSH_ACCESS"
PUSH_LIMIT = "PUSH_LIMIT"
YAW_INVALID = "YAW_INVALID"   # pick_object와 공통, 이름은 C Runner 재시도 규칙과 맞춤 (PR #65 PM 코멘트)


@dataclass(frozen=True)
class GripperGeometry:
    finger_thickness_m: float     # 열린 손가락 한 개 두께 (집는 방향)
    finger_width_m: float         # 손가락 폭 (집는 방향에 수직)
    grasp_clearance_m: float      # 물체 옆면 ~ 손가락 안쪽 여유 (한쪽)
    max_open_width_m: float       # 손가락 안쪽 최대 간격 (RG2 110 mm에서 여유를 뺀 값)
    closed_thickness_m: float     # 닫은 손가락 두께 (미는 방향) — 물체 뒤에 필요한 틈
    wall_margin_m: float          # 손가락과 벽 사이 최소 여유
    push_margin_m: float          # 계산한 최소 밀기 거리에 더하는 여유


@dataclass(frozen=True)
class NudgePlan:
    pushed: bool                          # 밀어야 함(밀기 계획 있음)
    error_code: Optional[str]             # None / NO_PUSH_ACCESS / PUSH_LIMIT / YAW_INVALID
    push_vector_m: tuple                  # 물체 이동 (dx, dy) — 밀지 않으면 (0, 0)
    push_start_m: Optional[tuple]         # 닫은 손가락을 내릴 위치 (x, y)
    finger_travel_m: float                # 손가락 직선 이동 거리 = 물체까지 빈틈 + 밀기 거리
    clearance_before_m: float             # 물체(AABB)와 가장 가까운 벽 사이 거리
    grasp_yaw: Optional[float]            # (밀고 난 뒤) 잡을 수 있는 집는 방향 yaw. 불가면 None
    reason: str


def _half_extents(lx: float, ly: float, yaw: float) -> tuple:
    """로컬 lx×ly 직사각형을 yaw만큼 돌린 AABB 반폭 (hx, hy)."""
    c, s = abs(math.cos(yaw)), abs(math.sin(yaw))
    return (lx / 2 * c + ly / 2 * s, lx / 2 * s + ly / 2 * c)


def _rects_for_grasp(cx, cy, yaw, half_along, geo):
    """집는 축 yaw로 잡을 때 두 손가락의 (중심 x, 중심 y, hx, hy)."""
    ux, uy = math.cos(yaw), math.sin(yaw)
    off = half_along + geo.grasp_clearance_m + geo.finger_thickness_m / 2
    hx, hy = _half_extents(geo.finger_thickness_m, geo.finger_width_m, yaw)
    return [(cx + sgn * off * ux, cy + sgn * off * uy, hx, hy) for sgn in (1, -1)]


def _grasp_options(cx, cy, yaw, size_xy, geo):
    """(집는 축 yaw, 손가락 사각형들) 두 가지. 벌림 폭을 넘는 방향은 제외."""
    out = []
    for axis_yaw, half_along in ((yaw, size_xy[0] / 2), (yaw + math.pi / 2, size_xy[1] / 2)):
        if 2 * (half_along + geo.grasp_clearance_m) <= geo.max_open_width_m:
            out.append((axis_yaw, _rects_for_grasp(cx, cy, axis_yaw, half_along, geo)))
    return out


def _shift_interval(rects, axis, sign, lo, hi):
    """사각형들을 axis 방향으로 sign·d 만큼 옮길 때 [lo, hi] 안에 드는 d ≥ 0 구간. 없으면 None."""
    d_lo, d_hi = 0.0, math.inf
    for r in rects:
        p, h = (r[0], r[2]) if axis == 0 else (r[1], r[3])
        a, b = lo + h - p, hi - h - p          # sign·d ∈ [a, b]
        if sign < 0:
            a, b = -b, -a
        d_lo, d_hi = max(d_lo, a), min(d_hi, b)
    return (d_lo, d_hi) if d_lo <= d_hi + 1e-12 else None


def _fits(rects, axis, lo, hi):
    """옮기지 않고 axis 방향으로 [lo, hi] 안에 드는지."""
    iv = _shift_interval(rects, axis, 1, lo, hi)
    return iv is not None and iv[0] <= 1e-12


def plan_nudge(*, center_xy, yaw, yaw_valid: Optional[bool], size_xy, interior_xy,
               geo: GripperGeometry, check_only: bool = False) -> NudgePlan:
    """물체 하나에 대한 밀기 판단. `interior_xy` = (depth, width) m.
    `yaw_valid`는 pose 그대로(필드가 없으면 None) 넘긴다."""
    if yaw_valid is not True:
        return NudgePlan(False, YAW_INVALID, (0.0, 0.0), None, 0.0, 0.0, None,
                         f"yaw를 믿을 수 없음 (yaw_valid={yaw_valid}) — 다시 인식 필요")
    cx, cy = center_xy
    depth, width = interior_xy
    ohx, ohy = _half_extents(size_xy[0], size_xy[1], yaw)
    if not (0 <= cx <= depth and 0 <= cy <= width):
        raise ValueError(f"물체 중심이 서랍 내부 밖: ({cx:.3f}, {cy:.3f}), 내부 {depth}×{width} m")
    gaps = {(0, -1): cx - ohx, (0, 1): depth - cx - ohx,     # (축, 벽 쪽 부호): 물체~벽 빈틈
            (1, -1): cy - ohy, (1, 1): width - cy - ohy}
    clearance = max(0.0, min(gaps.values()))
    m = geo.wall_margin_m
    lo, hi = (m, m), (depth - m, width - m)

    options = _grasp_options(cx, cy, yaw, size_xy, geo)
    for axis_yaw, rects in options:
        if _fits(rects, 0, lo[0], hi[0]) and _fits(rects, 1, lo[1], hi[1]):
            return NudgePlan(False, None, (0.0, 0.0), None, 0.0, clearance, axis_yaw,
                             "지금 자리에서 파지 가능")
    if check_only:
        return NudgePlan(False, PUSH_LIMIT, (0.0, 0.0), None, 0.0, clearance, None,
                         "밀기 뒤 재판단에서도 파지 불가")

    best = None   # (d, axis, sign, axis_yaw, gap)
    blocked_by_access = False                           # 밀면 되는데 손가락 들어갈 틈이 없는 경우
    for (axis, wall_side), gap in gaps.items():
        has_access = gap >= geo.closed_thickness_m + m  # 이 벽 쪽에 닫은 손가락이 들어갈 틈
        sign = -wall_side                               # 벽에서 멀어지는 방향
        obj = [(cx, cy, ohx, ohy)]
        for axis_yaw, rects in options:
            other = 1 - axis
            if not _fits(rects, other, lo[other], hi[other]):
                continue                                # 미는 방향과 수직으로 걸리면 밀어도 안 됨
            iv_f = _shift_interval(rects, axis, sign, lo[axis], hi[axis])
            iv_o = _shift_interval(obj, axis, sign, 0.0, (depth, width)[axis])
            if iv_f is None or iv_o is None:
                continue
            d_lo, d_hi = max(iv_f[0], iv_o[0]), min(iv_f[1], iv_o[1])
            if d_lo > d_hi:
                continue
            if not has_access:
                blocked_by_access = True
                continue
            d = min(d_lo + geo.push_margin_m, d_hi)
            if best is None or d < best[0]:
                best = (d, axis, sign, axis_yaw, gap)
    if best is None:
        reason = ("물체 뒤에 닫은 손가락이 들어갈 틈이 없음" if blocked_by_access
                  else "어느 방향으로 밀어도 파지 가능한 자리가 없음")
        return NudgePlan(False, NO_PUSH_ACCESS, (0.0, 0.0), None, 0.0, clearance, None, reason)

    d, axis, sign, axis_yaw, gap = best
    vec = (sign * d, 0.0) if axis == 0 else (0.0, sign * d)
    slack = (gap - geo.closed_thickness_m - m) / 2      # 벽·물체 양쪽에 같은 여유를 두고 내린다
    edge = (cx, cy)[axis] - sign * ((ohx, ohy)[axis])   # 물체의 벽 쪽 면
    start_a = edge - sign * (geo.closed_thickness_m / 2 + slack)
    start = (start_a, cy) if axis == 0 else (cx, start_a)
    return NudgePlan(True, None, vec, start, slack + d, clearance, axis_yaw,
                     f"{'xy'[axis]}{'+' if sign > 0 else '−'} 방향으로 {d * 1000:.1f} mm")
