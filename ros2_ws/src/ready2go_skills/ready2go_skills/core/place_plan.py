"""`place_object` 서랍 안 놓기 계산 (#120 ②·#166 계약, ROS 비의존·pytest 대상). 계약 정본 docs/runner.md 7.1 `place_object`.

- 놓을 자리: `pose`(서랍 좌표계 {frame, position [x, y, 0], yaw}) 또는 `slot`(places.yaml `<서랍>.place_slots`) 중 정확히 하나.
- 움직이기 전 겹침 확인 (이 순서):
  ① 이웃: 놓을 footprint 가 scan 의 target·candidates 각 footprint(온톨로지 size_m, yaw 방향)와 겹치면 PLACE_BLOCKED(blocked_by = 그 id).
     쥔 물체와 같은 id 는 무시. yaw_valid 가 true 가 아니면 어느 방향이든 덮게 대각선 반을 반폭으로 [계산].
  ② 벽: footprint 가 서랍 경계(+ 실측 옆벽 바깥 거리) 밖이거나, TCP 가 손가락·관절 벽 간섭 거리(motion_plan.wall_extent_mm,
     집기 wall_blocks_grasp 와 같은 기준)보다 벽에 가까우면 WALL_TOO_CLOSE(blocked_by = "wall").
- footprint = 쥔 물체 [긴 변, 짧은 변] — 짧은 변 쪽은 놓을 때 벌린 폭/2 + 손가락 두께(gripper.fingertip_outer_mm) — 양쪽에 여유(place.footprint_margin_mm).
- 손가락은 긴 변에 수직으로 닫혀 있음(집기와 같음) → base 닫힘 방향 = 긴 변 각도 + 90°.
"""
import math
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

from ready2go_skills.core import motion_plan as mp
from ready2go_skills.core import pick_plan as pp

BAD_PARAMS = "BAD_PARAMS"
PLACE_NOT_CONFIGURED = "PLACE_NOT_CONFIGURED"
PLACE_BLOCKED = "PLACE_BLOCKED"
WALL_TOO_CLOSE = "WALL_TOO_CLOSE"


@dataclass(frozen=True)
class Refusal:
    error_code: str
    reason: str
    blocked_by: Optional[str] = None


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def pose_error(pose, location: str) -> Optional[str]:
    """놓을 pose 규칙 (inspect_region pose 와 같은 기준, yaw_valid 없음). 맞으면 None."""
    if not isinstance(pose, Mapping):
        return f"pose 는 {{frame, position, yaw}}: {pose!r}"
    if pose.get("frame") != location:
        return f"pose.frame {pose.get('frame')!r} ≠ location {location!r}"
    p, yaw = pose.get("position"), pose.get("yaw")
    if not (isinstance(p, Sequence) and not isinstance(p, str) and len(p) == 3 and _finite(*p, yaw)):
        return f"pose position [x, y, 0]·yaw 는 유한한 수: {p!r}, {yaw!r}"
    if p[2] != 0:
        return f"pose position z 는 0 (서랍 바닥 기준): {p[2]!r}"
    if not -math.pi / 2 < yaw <= math.pi / 2:
        return f"pose yaw 는 (−π/2, π/2]: {yaw!r}"
    return None


def resolve_pose(params: Mapping, location: str, place_slots: Optional[Mapping]):
    """params 의 pose·slot → (pose, slot 이름 또는 None, Refusal 또는 None). 둘 다·둘 다 없음 = BAD_PARAMS,
    교시 안 된 slot(없는 이름·null) = PLACE_NOT_CONFIGURED. slot 교시값 형식 = {position: [x, y, 0], yaw} (서랍 좌표계)."""
    if ("pose" in params) == ("slot" in params):
        return None, None, Refusal(BAD_PARAMS, "서랍 안 놓기는 pose·slot 중 정확히 하나")
    if "pose" in params:
        err = pose_error(params["pose"], location)
        if err:
            return None, None, Refusal(BAD_PARAMS, err)
        p = params["pose"]
        return {"frame": location, "position": [float(p["position"][0]), float(p["position"][1]), 0.0],
                "yaw": float(p["yaw"])}, None, None
    slot = params["slot"]
    if not isinstance(slot, str) or not slot:
        return None, None, Refusal(BAD_PARAMS, f"slot 은 이름(문자열): {slot!r}")
    taught = (place_slots or {}).get(slot) if isinstance(place_slots, Mapping) else None
    if not isinstance(taught, Mapping):
        return None, None, Refusal(PLACE_NOT_CONFIGURED, f"places.yaml {location}.place_slots.{slot} 교시 전")
    pose = {"frame": location, "position": taught.get("position"), "yaw": taught.get("yaw")}
    err = pose_error(pose, location)
    if err:                                               # 교시값이 규칙 밖 = 설정 문제 (요청 문제가 아님)
        return None, None, Refusal(PLACE_NOT_CONFIGURED, f"places.yaml {location}.place_slots.{slot} 값 비정상: {err}")
    return {"frame": location, "position": [float(pose["position"][0]), float(pose["position"][1]), 0.0],
            "yaw": float(pose["yaw"])}, slot, None


def scan_objects(scan, location: str):
    """scan(직전 inspect_region 결과 전체) → ([target(있으면)] + candidates, 오류 문자열 또는 None).
    candidates 에는 target 이 빠져 있으므로 둘 다 이웃 (#166 D 리뷰 P1)."""
    if not isinstance(scan, Mapping):
        return None, "scan(직전 inspect_region 결과 전체, $scan) 필요"
    cands, target = scan.get("candidates"), scan.get("target")
    if not isinstance(cands, list) or not (target is None or isinstance(target, Mapping)):
        return None, "scan 형식: candidates 목록·target(객체 또는 null)"
    objs = ([target] if target else []) + cands
    for o in objs:
        pose = o.get("pose") if isinstance(o, Mapping) else None
        if not isinstance(pose, Mapping) or not isinstance(o.get("id"), str):
            return None, f"scan 물체 형식 (id·pose 필요): {o!r}"
        p = pose.get("position")
        if pose.get("frame") != location:
            return None, f"scan 물체 {o['id']} frame {pose.get('frame')!r} ≠ {location!r} (다른 서랍 촬영)"
        if not (isinstance(p, Sequence) and len(p) >= 2 and _finite(p[0], p[1], pose.get("yaw"))):
            return None, f"scan 물체 {o['id']} 위치·yaw 비정상: {p!r}, {pose.get('yaw')!r}"
    return objs, None


def corners(cx: float, cy: float, yaw: float, half_long: float, half_short: float) -> list:
    """긴 변이 yaw 방향인 직사각형 꼭짓점 4개."""
    c, s = math.cos(yaw), math.sin(yaw)
    return [(cx + a * half_long * c - b * half_short * s, cy + a * half_long * s + b * half_short * c)
            for a, b in ((1, 1), (-1, 1), (-1, -1), (1, -1))]


def rects_overlap(a: Sequence, b: Sequence) -> bool:
    """꼭짓점 목록 두 볼록 사각형이 겹치는지 (분리축). 맞닿기만 하면 겹침 아님."""
    for poly in (a, b):
        for i in range(4):
            (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % 4]
            n = (y1 - y2, x2 - x1)
            pa = [n[0] * x + n[1] * y for x, y in a]
            pb = [n[0] * x + n[1] * y for x, y in b]
            if max(pa) <= min(pb) or max(pb) <= min(pa):
                return False
    return True


def place_half_mm(size_m: Sequence[float], open_mm: float, finger_mm: float, margin_mm: float) -> tuple:
    """놓을 footprint 반폭 (긴 변 쪽, 짧은 변 쪽) mm. 짧은 변 쪽 = max(물체 반폭, 벌린 손가락 바깥면) + 여유."""
    half_short = max(size_m[1] * 500.0, open_mm / 2.0 + finger_mm)
    return size_m[0] * 500.0 + margin_mm, half_short + margin_mm


def neighbor_rect_mm(obj: Mapping, size_m: Sequence[float]) -> list:
    """이웃 footprint 꼭짓점 (mm). yaw_valid 가 true 가 아니면 방향을 모름 → 대각선 반을 반폭으로 하는 정사각형 [계산]."""
    pose = obj["pose"]
    x, y = pose["position"][0] * 1000.0, pose["position"][1] * 1000.0
    hl, hs = size_m[0] * 500.0, size_m[1] * 500.0
    if pose.get("yaw_valid") is True:
        return corners(x, y, pose["yaw"], hl, hs)
    r = math.hypot(hl, hs)
    return corners(x, y, 0.0, r, r)


def wall_reason(x_mm: float, y_mm: float, yaw: float, half: tuple, open_mm: float, interior_m: Sequence[float],
                g: Mapping) -> Optional[str]:
    """벽 확인 (서랍 좌표 mm). 실제 옆벽이 경계보다 바깥인 거리 g['wall_offset_mm'] {y_min, y_max} 는 집기와 같이 반영."""
    off = g.get("wall_offset_mm") or {}
    d, wd = interior_m[0] * 1000.0, interior_m[1] * 1000.0
    y_lo, y_hi = -float(off.get("y_min", 0.0)), wd + float(off.get("y_max", 0.0))
    for cx, cy in corners(x_mm, y_mm, yaw, *half):
        if not (0.0 <= cx <= d and y_lo <= cy <= y_hi):
            return f"놓을 footprint 가 서랍 벽 밖 (꼭짓점 {cx:.1f}, {cy:.1f} mm, 경계 x 0~{d:.1f}, y {y_lo:.1f}~{y_hi:.1f})"
    close_ang = yaw + math.pi / 2                           # 서랍 좌표 닫힘 축 = 긴 변에 수직 (집기와 같음)
    need_x = mp.wall_extent_mm(open_mm, close_ang, g) + g["wall_margin_mm"]
    need_y = mp.wall_extent_mm(open_mm, close_ang - math.pi / 2, g) + g["wall_margin_mm"]
    gap_x, gap_y = min(x_mm, d - x_mm), min(y_mm - y_lo, y_hi - y_mm)
    if gap_x < need_x:
        return f"앞뒤 벽까지 {gap_x:.1f} mm < 손가락·관절 간섭 {need_x:.1f} mm"
    if gap_y < need_y:
        return f"옆벽까지 {gap_y:.1f} mm < 손가락·관절 간섭 {need_y:.1f} mm"
    return None


def check_place(*, pose: Mapping, held_id: str, held_size_m: Sequence[float], open_mm: float, objects: Sequence[Mapping],
                size_of: Callable[[str], Optional[Sequence[float]]], interior_m: Sequence[float], g: Mapping,
                place: Mapping) -> Optional[Refusal]:
    """움직이기 전 겹침 확인: ① 이웃(PLACE_BLOCKED) → ② 벽(WALL_TOO_CLOSE). 통과면 None.
    size_of(class) = 온톨로지 size_m, 모르면 None → place.default_obstacle_size_m."""
    x, y = pose["position"][0] * 1000.0, pose["position"][1] * 1000.0
    yaw = pose["yaw"]
    vals = (x, y, yaw, open_mm, *held_size_m[:2], *interior_m[:2], g["fingertip_outer_mm"], place["footprint_margin_mm"])
    if not _finite(*vals):
        raise ValueError(f"놓기 확인 입력 비정상: {vals}")       # 로봇 목표로 보내지 않음 (fail-closed)
    half = place_half_mm(held_size_m, open_mm, g["fingertip_outer_mm"], place["footprint_margin_mm"])
    mine = corners(x, y, yaw, *half)
    for o in objects:
        if o["id"] == held_id:
            continue
        size = size_of(o.get("class")) or place["default_obstacle_size_m"]
        if rects_overlap(mine, neighbor_rect_mm(o, size)):
            return Refusal(PLACE_BLOCKED, f"놓을 자리가 {o['id']} 와 겹침", o["id"])
    why = wall_reason(x, y, yaw, half, open_mm, interior_m, g)
    if why:
        return Refusal(WALL_TOO_CLOSE, why, "wall")
    return None


def fit_slot(*, pose: Mapping, check: Callable[[Mapping], Optional[Refusal]], max_shift_mm: float,
             step_mm: float = 2.0) -> tuple:
    """고정 빈 자리(slot)에 쥔 물체가 안 들어가면(벽·이웃) 자리 가운데에서 가장 적게 옮긴(·90° 돌린) 자세를 찾음
    [P2 시연 시뮬레이션 10/10: 가림막 98.5 × 74.2 mm 가 aside_1 에서 손잡이 쪽 벽 밖 3 mm → WALL_TOO_CLOSE].
    (자세, None) 또는 못 찾으면 (원래 자세, 원래 거부). 명령한 pose(되돌리기)는 쓰지 않음 — 원래 자리여야 하므로."""
    first = check(pose)
    if first is None or max_shift_mm <= 0:
        return pose, first
    n = int(max_shift_mm // step_mm)
    offs = sorted(((i * step_mm, j * step_mm) for i in range(-n, n + 1) for j in range(-n, n + 1)
                   if math.hypot(i, j) * step_mm <= max_shift_mm), key=lambda d: math.hypot(*d))
    x, y = pose["position"][:2]
    for dyaw in (0.0, math.pi / 2):
        yaw = pose["yaw"] + dyaw
        yaw = (yaw + math.pi / 2) % math.pi - math.pi / 2          # (−π/2, π/2]
        if yaw <= -math.pi / 2 + 1e-9:
            yaw += math.pi
        for dx, dy in offs:
            cand = dict(pose, position=[x + dx / 1000.0, y + dy / 1000.0, 0.0], yaw=yaw)
            if check(cand) is None:
                return cand, None
    return pose, first


def stack_support(*, pose: Mapping, held_id: str, held_size_m: Sequence[float], objects: Sequence[Mapping],
                  size_of: Callable[[str], Optional[Sequence[float]]], max_top_m: float) -> Optional[Mapping]:
    """다른 물체 위에 놓기(되돌리기 — 쌓여 있던 원위치) [P2 시뮬레이션 10/11: 차키를 캐러멜 위였던 자리로 못 되돌림 → PLACE_BLOCKED].
    놓을 물체 가운데가 이웃 footprint 안이고 그 이웃 윗면 + 놓을 물체 높이가 max_top_m(테두리 − 여유) 이하면 그 이웃(받침), 아니면 None.
    받침은 하나만 — 가운데를 덮는 이웃이 여럿이면 가장 높은 것(맨 위). top_z 를 모르면 받침으로 안 씀."""
    x, y = pose["position"][0] * 1000.0, pose["position"][1] * 1000.0
    best = None
    for o in objects:
        if o["id"] == held_id or not _finite(o.get("top_z")):
            continue
        size = size_of(o.get("class"))
        if not size:
            continue
        ox, oy, oyaw = o["pose"]["position"][0] * 1000.0, o["pose"]["position"][1] * 1000.0, o["pose"]["yaw"]
        c, s = math.cos(oyaw), math.sin(oyaw)
        dx, dy = x - ox, y - oy
        if abs(dx * c + dy * s) <= size[0] * 500.0 and abs(-dx * s + dy * c) <= size[1] * 500.0:
            if best is None or o["top_z"] > best["top_z"]:
                best = o
    if best is None or best["top_z"] + held_size_m[2] > max_top_m:
        return None
    return best


def ontology_support_m(*, target: Mapping, objects: Sequence[Mapping], size_of: Callable[[str], Optional[Sequence[float]]],
                       gap_m: float = 0.005, _depth: int = 0) -> Optional[float]:
    """쌓인 물체의 받침 높이를 온톨로지 높이로 [사용자 10/11 "온톨로지로 높이 파악해서"]: 비전은 무엇이 밑에 깔렸는지(가운데가 그 물체
    footprint 안이고 윗면이 gap_m 넘게 낮음)만 보고, 높이는 깔린 물체의 size_m[2] 를 아래로 차례로 더함. 비전 깊이는 캐러멜을 7~9 mm 높게 봄
    [실측 PC2 10/11 top_z 25~27 / 18.5]. 밑에 깔린 게 없으면 None (호출한 쪽이 비전 값 또는 바닥)."""
    if _depth > 5:
        return None
    best = None
    for o in objects_under(target=target, objects=objects, size_of=size_of, gap_m=gap_m):
        below = ontology_support_m(target=o, objects=objects, size_of=size_of, gap_m=gap_m, _depth=_depth + 1) or 0.0
        h = below + float(size_of(o.get("class"))[2])
        best = h if best is None else max(best, h)
    return best


def objects_under(*, target: Mapping, objects: Sequence[Mapping], size_of: Callable[[str], Optional[Sequence[float]]],
                  gap_m: float = 0.005, ambiguous_m: float = 0.010) -> list:
    """target 밑에 깔린 것(받침): 분할 모델 관계(o.occluded_by 에 target) 이거나, target 가운데가 o footprint 안이고 윗면이 gap_m 넘게 낮음.
    집을 때 이웃 확인에서 뺌."""
    if not _finite(target.get("top_z")):
        return []
    x, y = target["pose"]["position"][0] * 1000.0, target["pose"]["position"][1] * 1000.0
    out = []
    for o in objects:
        if o.get("id") == target.get("id") or o.get("id") in (target.get("occluded_by") or []):
            continue                                        # target 위에 얹힌 물체는 받침이 아님
        if target.get("id") in (o.get("occluded_by") or []) and size_of(o.get("class")):
            out.append(o)                                   # 분할 모델 관계: o 위에 target 이 얹힘 — 비전 윗면이 번져 높아도 [사용자 10/11 PC2: 캐러멜 54.6 / 차키 55.5]
            continue
        if not _finite(o.get("top_z")):
            continue
        lower = o["top_z"] < target["top_z"] - gap_m
        # 쌓인 물체 윗면이 번져 위 물체와 비슷하게 나옴 [실측 PC2 10/11: 몽키 53.7·캐러멜 54·차키 55] — 분할 결과가 target 위에 아무것도
        # 없다고 하면(occluded_by == []) 높이 차 ambiguous_m 안의 '가운데 밑' 물체는 밑에 깔린 것. 높이 차가 확실하면 높이대로
        top_clear = isinstance(target.get("occluded_by"), list) and not target["occluded_by"]
        ts, os_ = size_of(target.get("class")), size_of(o.get("class"))
        bigger = bool(ts and os_) and os_[0] * os_[1] >= ts[0] * ts[1]   # 높이로 못 가를 땐 큰 게 밑 (몽키 > 캐러멜 > 차키) — 밑 물체를 집을 때 위 물체를 받침으로 안 봄
        if not (lower or (top_clear and bigger and abs(o["top_z"] - target["top_z"]) <= ambiguous_m)):
            continue
        size = size_of(o.get("class"))
        if not size:
            continue
        ox, oy, oyaw = o["pose"]["position"][0] * 1000.0, o["pose"]["position"][1] * 1000.0, o["pose"]["yaw"]
        c, s_ = math.cos(oyaw), math.sin(oyaw)
        dx, dy = x - ox, y - oy
        if abs(dx * c + dy * s_) <= size[0] * 500.0 and abs(-dx * s_ + dy * c) <= size[1] * 500.0:
            out.append(o)
    return out


def place_tcp_m(tf: Mapping, pose: Mapping, tcp_above_floor_m: float) -> tuple:
    """놓는 TCP (base m)와 base 기준 물체 긴 변 각도(deg, (−90, 90]). 높이 = 서랍 바닥 + tcp_above_floor_m (drop 포함)."""
    pp.check_tf(tf)
    x, y = pose["position"][:2]
    if not _finite(x, y, pose["yaw"], tcp_above_floor_m):
        raise ValueError(f"놓기 목표 비정상: {x, y, pose['yaw'], tcp_above_floor_m}")
    pos = pp.to_base(tf, (x, y, tcp_above_floor_m))
    long_axis = pp.wrap_line_deg(pp.frame_yaw_deg(tf) + math.degrees(pose["yaw"]))
    return pos, long_axis
