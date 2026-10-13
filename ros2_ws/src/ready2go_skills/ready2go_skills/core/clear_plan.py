"""파지 공간 만들기 — 쌓인 물체를 빈 곳에 치우기·목표 넛지·좌우 밀기 계획 (ROS 비의존·pytest 대상) [사용자 10/11 제안].

서랍 바닥을 세 가지로 본다 (#117):
  - 벽: 못 움직임 → 벽 반대쪽으로만 (기존 벽 넛지, motion_plan.plan_drag)
  - 다른 물체: 움직일 수 있는 장애물 → 집어서 빈 곳에 두거나, 목표를 밀 때 같이 밀려남
  - 빈 곳: 바로 집을 수 있는 자리
순서 [사용자 10/11]: 파지 공간 확보(쌓인 것 치우기·좌우 밀기) → 다시 보기 → 넛지·밀기 → 다시 보기 → 집기.

이 모듈은 계산만 한다. 집을 수 있는지·놓을 수 있는지는 스킬 서버의 실제 사전 검사(벽·앞판·이웃·긴 변)를
`oracle` 로 받아 쓴다 — 판단 규칙을 따로 만들지 않음. 밀었을 때 물체가 어디로 가는지는 2D 평면에서 미끄러짐만 본다
(회전·넘어짐·마찰 없음 [추정 — 실물 확인 필요]).

물체 = inspect_region 결과와 같은 dict: {id, class, top_z, pose{frame, position[x, y, 0], yaw}, occluded_by}. 좌표 m (서랍 좌표).
occluded_by 는 리스트여야 함(모름 null·박스 모델은 부르는 쪽이 먼저 거부 — skill_server _make_room).
한계: 빈 자리·밀기는 검출된 물체만 앎 — 검출 안 된 낮은 물체 자리를 빈 곳으로 볼 수 있음 [A·PM #226 리뷰, #228 세운 립밤 미검출].
"""
import math
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional, Sequence

from ready2go_skills.core import place_plan as plp

AXES = ((-1.0, 0.0), (0.0, 1.0), (0.0, -1.0), (1.0, 0.0))   # 서랍 축만 [사용자 10/10 "넛지는 x·y 만"]. +x(안쪽)는 서랍이 끌려 기본 끔


@dataclass
class Action:
    kind: str                     # "pick" | "unstack" | "remove" | "nudge" | "sweep" | "wall_nudge" | "fail"
    target: str = ""              # 움직이는 물체 id
    reason: str = ""
    to_pose: Optional[dict] = None          # unstack·remove: 놓을 pose {frame, position, yaw}
    dir: tuple = (0.0, 0.0)                 # nudge·sweep: 서랍 축 방향
    dist_m: float = 0.0                     # nudge: 끌 거리 / sweep: 밀 거리
    back_m: float = 0.0                     # sweep: 되돌아올 거리
    pushed: tuple = ()                      # sweep: 같이 밀린 물체 (예상)
    code: str = ""                          # fail: 마지막 거부 코드
    extra: dict = field(default_factory=dict)


def size_xy(o: Mapping, size_of: Callable) -> tuple:
    s = size_of(o["class"])
    return s[0], s[1]


def footprint_mm(o: Mapping, size_of: Callable, pad_mm: float = 0.0) -> list:
    sx, sy = size_xy(o, size_of)
    p = o["pose"]["position"]
    return plp.corners(p[0] * 1000.0, p[1] * 1000.0, o["pose"]["yaw"], sx * 500.0 + pad_mm, sy * 500.0 + pad_mm)


def inside(o: Mapping, size_of: Callable, interior_m: Sequence[float], margin_mm: float = 0.0) -> bool:
    d, w = interior_m[0] * 1000.0, interior_m[1] * 1000.0
    return all(margin_mm <= x <= d - margin_mm and margin_mm <= y <= w - margin_mm for x, y in footprint_mm(o, size_of))


def overlaps(a: Mapping, b: Mapping, size_of: Callable, gap_mm: float = 0.0) -> bool:
    return plp.rects_overlap(footprint_mm(a, size_of, gap_mm), footprint_mm(b, size_of))


def zrange(o: Mapping, size_of: Callable) -> tuple:
    """물체가 차지하는 높이 [바닥면, 윗면] (m). 다리 있는 물체(덮개 판)는 바닥부터."""
    top = o.get("top_z")
    h = size_of(o["class"])[2]
    if top is None:
        return 0.0, h
    return max(0.0, top - h), top


def collide(a: Mapping, b: Mapping, size_of: Callable, gap_mm: float = 0.0, z_tol_m: float = 0.001) -> bool:
    """부딪힘: 바닥 사각형이 겹치고 높이 구간도 겹침 — 위에 얹힌 물체는 그 밑 물체와 안 부딪힘."""
    if a["id"] in (b.get("occluded_by") or []) or b["id"] in (a.get("occluded_by") or []):
        return False                                   # 얹힘·덮임 관계(받침 위, 덮개 판 밑)는 위아래로 지나감
    (a0, a1), (b0, b1) = zrange(a, size_of), zrange(b, size_of)
    if a1 <= b0 + z_tol_m or b1 <= a0 + z_tol_m:
        return False
    return overlaps(a, b, size_of, gap_mm)


def moved(o: Mapping, dx_m: float, dy_m: float, yaw: Optional[float] = None) -> dict:
    p = o["pose"]["position"]
    pose = dict(o["pose"], position=[p[0] + dx_m, p[1] + dy_m] + list(p[2:]))
    if yaw is not None:
        pose["yaw"] = yaw
    return dict(o, pose=pose)


def riders(objs: Sequence[Mapping], base_id: str) -> set:
    """base 위에 얹힌 물체 id (occluded_by 를 따라 끝까지) — base 를 옮기면 같이 움직인다고 봄."""
    by = {o["id"]: o for o in objs}
    out, todo = set(), [base_id]
    while todo:
        for r in (by.get(todo.pop(), {}).get("occluded_by") or []):
            if r not in out and r in by:
                out.add(r)
                todo.append(r)
    return out


LEG_CLASSES = {"cover_plate"}   # 다리로 바닥에 섬 — 밑에 물체가 있어도 바닥 물체 (#8 덮개 판)


def on_floor(objs: Sequence[Mapping], oid: str) -> bool:
    """다른 물체 위에 얹히지 않았는지 (그 물체가 누구의 occluded_by 에도 없음). 다리 있는 물체는 늘 바닥."""
    o = next((x for x in objs if x["id"] == oid), None)
    if o is not None and o.get("class") in LEG_CLASSES:
        return True
    return not any(oid in (x.get("occluded_by") or []) for x in objs)


def _blocking(objs, group) -> list:
    """움직이는 group 밖의 물체 — 실제로 부딪히는지는 collide(높이 구간까지)로."""
    return [o for o in objs if o["id"] not in group]


def ahead(dx: float, dy: float, u: tuple) -> bool:
    """가운데끼리 차이 (dx, dy) 인 물체가 u 방향 '앞'인지 — u 성분이 옆 성분의 절반보다 커야 앞(약 63° 원뿔 안).
    옆에 맞붙은 물체(u 성분이 몇 mm 뿐)는 앞이 아님 [실측 PC2 10/13: 벽 쪽 에어팟을 +y 로 밀 때 -x 옆에 맞붙은 캐러멜(가운데 차
    y +2 mm)을 앞으로 보고 같이 밀려다 막힘]."""
    along = dx * u[0] + dy * u[1]
    side = abs(-dx * u[1] + dy * u[0])
    return along > 0.5 * side


def out_mm(o: Mapping, size_of: Callable, interior_m: Sequence[float]) -> float:
    """footprint 가 서랍 경계 밖으로 나간 최대 거리(mm, 안이면 0) — 비전 각도·외접 박스로 벽에 맞붙은 물체가 경계를 몇 mm
    넘게 그려짐(캐러멜 14° → 4 mm). 움직일 때 처음부터 나간 만큼은 봐줌."""
    d, w = interior_m[0] * 1000.0, interior_m[1] * 1000.0
    return max([0.0] + [max(-x, x - d, -y, y - w) for x, y in footprint_mm(o, size_of)])


def _behind(objs: Sequence[Mapping], mover: str, u: tuple, size_of) -> set:
    """처음부터 mover 와 footprint 가 겹친 물체 중 u 쪽 '앞'(ahead)이 아닌 것(뒤·옆) — 멀어지거나 옆으로 스치므로 겹침이 늘지 않음.
    온톨로지 외접 박스가 실제보다 커서(몽키 머리 61 × 길이 170) 맞붙은 물체끼리 처음부터 겹치면 어느 쪽으로도 0 mm 로 나와
    아무 동작도 못 고르던 것 [실측 PC2 10/13 B clear top 에어팟: 에어팟·캐러멜·몽키·지우개 서로 1~2 mm 겹침 → fail]."""
    by = {o["id"]: o for o in objs}
    m = by[mover]
    mx, my = m["pose"]["position"][:2]
    out = set()
    for o in objs:
        if o["id"] == mover or not overlaps(m, o, size_of):
            continue
        ox, oy = o["pose"]["position"][:2]
        if not ahead((ox - mx) * 1000.0, (oy - my) * 1000.0, u):
            out.add(o["id"])
    return out


def free_move(objs: Sequence[Mapping], mover: str, u: tuple, dist_m: float, interior_m, size_of, step_mm: float = 1.0,
              gap_mm: float = 0.0) -> float:
    """mover(위 물체 포함)를 u 로 dist_m 까지 — 다른 바닥 물체·벽에 닿기 전까지 갈 수 있는 거리(m). 밀지 않음.
    처음부터 겹친 물체 중 뒤쪽(멀어지는 쪽)은 막지 않음 (_behind)."""
    group = {mover} | riders(objs, mover)
    by = {o["id"]: o for o in objs}
    behind = _behind(objs, mover, u, size_of)
    others = [o for o in _blocking(objs, group) if o["id"] not in behind]
    slack = out_mm(by[mover], size_of, interior_m)               # 처음부터 경계 밖으로 그려진 만큼은 봐줌
    done = 0.0
    for k in range(1, int(round(dist_m * 1000.0 / step_mm)) + 1):
        s = k * step_mm / 1000.0
        m = moved(by[mover], u[0] * s, u[1] * s)
        if not inside(m, size_of, interior_m, -slack) or any(collide(m, o, size_of, gap_mm) for o in others):
            break
        done = s
    return done


def push_move(objs: Sequence[Mapping], mover: str, u: tuple, dist_m: float, interior_m, size_of,
              pushable: Callable[[Mapping], bool], max_chain: int = 2, step_mm: float = 1.0):
    """mover 를 u 로 밀어 dist_m 까지 — 앞을 막는 바닥 물체는 같이 밀림(줄줄이, 최대 max_chain 개, 위에 얹힌 것도 같이).
    밀린 물체가 벽·못 미는 물체에 걸리면 거기서 멈춤. → (새 물체 목록, 간 거리 m, 밀린 id 목록)."""
    order = [o["id"] for o in objs]
    cur = {o["id"]: dict(o) for o in objs}
    base = [mover] + sorted(riders(objs, mover))
    # 처음부터 겹친 뒤·옆 물체는 밀지도 막지도 않음 — 목표만이 아니라 같이 밀리기 시작한 물체도 그때 겹친 뒤·옆 물체는 봐줌
    # [실측 PC2 10/13 inspect_20261013_060416_812Z: 에어팟 +y 밀기 → 몽키 외접 박스(길이 170 × 머리 폭 61)가 손잡이 쪽
    # 캐러멜과 처음부터 겹쳐 캐러멜까지 같이 밀려다 0 mm → 밀기 후보 없음 → 몽키 머리 넛지(접촉 없음)]
    ign = {g: _behind(objs, g, u, size_of) for g in base}
    slack = {o["id"]: out_mm(o, size_of, interior_m) for o in objs}   # 처음부터 경계 밖으로 그려진 만큼은 봐줌
    pushed = []
    done = 0.0
    dx, dy = u[0] * step_mm / 1000.0, u[1] * step_mm / 1000.0
    for _ in range(int(round(dist_m * 1000.0 / step_mm))):
        lst = list(cur.values())
        moving = list(base) + [g for p_ in pushed for g in [p_] + sorted(riders(lst, p_))]
        trial = dict(cur)
        for gid in moving:
            trial[gid] = moved(cur[gid], dx, dy)
        ok, changed = True, True
        while changed and ok:
            changed = False
            tl = list(trial.values())
            for oid in order:
                if oid in moving:
                    continue
                if not any(oid not in ign.get(m, ()) and collide(trial[m], trial[oid], size_of) for m in moving):
                    continue
                if not pushable(trial[oid]) or len(set(pushed) | {oid}) > max_chain:
                    ok = False
                    break
                pushed.append(oid)
                cl = list(cur.values())
                for gid in [oid] + sorted(riders(tl, oid)):
                    ign.setdefault(gid, _behind(cl, gid, u, size_of))
                    trial[gid] = moved(cur[gid], dx, dy)
                    moving.append(gid)
                changed = True
                break
        if not ok or not all(inside(trial[m], size_of, interior_m, -slack.get(m, 0.0)) for m in moving
                             if on_floor(list(trial.values()), m)):
            break
        cur = trial
        done += step_mm / 1000.0
    return [cur[i] for i in order], done, pushed


def press_point(objs: Sequence[Mapping], tid: str, size_of: Callable, *, finger_r_mm: float, rise_tol_m: float = 0.003,
                inset_mm: float = 4.0, narrow_of: Optional[Callable] = None, center_only: Sequence[str] = (),
                hole: Sequence[str] = ()) -> Optional[tuple]:
    """닫은 손가락으로 목표 윗면을 누를 점 (서랍 좌표 m) — 가운데에서 가까운 점부터: 긴 변을 따라 가운데·절반·끝,
    폭 방향으로 (손잡이 폭(narrow_of, m) 또는 짧은 변)/2 − 8 mm 까지 비켜서.
    center_only 종류는 가운데(폭 방향 비킴만)만 — 윗면 높이가 고르지 않아 머리·끝은 top_z 보다 낮아 접촉 없음
    [사용자 10/13 PC2 "몽키 헤드 중 가장 낮은 부분을 자꾸 건드림", "옮겨도 몽키 중앙 부분을 눌러야지"]. 가운데가 막히면 None
    (그땐 같이 밀리기·집어서 치우기).
    누르는 손가락(반지름 finger_r_mm)이 목표보다 높은 물체에 걸리지 않는 점. 위에 얹힌 것이 있으면 None [추정 — 손가락 띠 모양 실측 없음].
    [실측 PC2 10/13 inspect_20261013_060416_812Z: 에어팟 옆 몽키 — 가운데·절반은 에어팟에 걸려 머리 끝(입 벌어진 곳)을 눌러
    접촉 없음 → 폭 방향으로 비켜 가운데 근처를 누름]"""
    by = {o["id"]: o for o in objs}
    t = by[tid]
    if t["class"] in hole:                                       # 가운데가 뚫림(마스킹테이프) — 누르면 손끝이 구멍으로 빠짐 [사용자 10/13]
        return None
    if t.get("occluded_by") or t.get("top_z") is None:
        return None if t.get("occluded_by") else tuple(t["pose"]["position"][:2])
    tx, ty, yaw = t["pose"]["position"][0] * 1000.0, t["pose"]["position"][1] * 1000.0, t["pose"]["yaw"]
    size = size_of(t["class"])
    half = max(0.0, size[0] * 500.0 - inset_mm)
    nw = (narrow_of(t["class"]) if narrow_of else None) or size[1]
    side = max(0.0, nw * 500.0 - 8.0)
    high = [footprint_mm(o, size_of) for o in objs
            if o["id"] != tid and o.get("top_z") is not None and o["top_z"] > t["top_z"] + rise_tol_m]
    ks = (0.0,) if t["class"] in center_only else (0.0, 0.5, -0.5, 1.0, -1.0)
    cand = sorted(((k * half, w) for k in ks for w in ((0.0, side, -side) if side else (0.0,))),
                  key=lambda c: (round(math.hypot(*c), 3), c[1] != 0.0))
    c_, s_ = math.cos(yaw), math.sin(yaw)
    for a, w in cand:
        x, y = tx + a * c_ - w * s_, ty + a * s_ + w * c_
        circle = plp.corners(x, y, 0.0, finger_r_mm, finger_r_mm)
        if not any(plp.rects_overlap(circle, fp) for fp in high):
            return x / 1000.0, y / 1000.0
    return None


def _pkw(cfg) -> dict:
    """press_point 설정값 (Config 에서)."""
    return {"finger_r_mm": cfg.press_finger_r_mm, "narrow_of": cfg.narrow_of, "center_only": cfg.press_center_only_classes,
            "hole": cfg.hole_classes}


def press_ok(objs: Sequence[Mapping], tid: str, size_of: Callable, **kw) -> bool:
    """목표 윗면을 닫은 손가락으로 누를 수 있는지 (press_point 가 있음)."""
    return press_point(objs, tid, size_of, **kw) is not None


def free_poses(objs: Sequence[Mapping], held_id: str, size_of: Callable, interior_m: Sequence[float], frame: str,
               avoid: Sequence[Mapping] = (), step_mm: float = 10.0, gap_mm: float = 6.0, avoid_pad_mm: float = 25.0,
               yaws: Sequence[float] = (0.0, math.pi / 2), min_clear_mm: float = 25.0) -> list:
    """쥔 물체를 내려놓을 빈 자리 후보 (점수 순). 벽·다른 물체와 gap_mm 이상, avoid(목표 등)는 avoid_pad_mm 이상 떨어짐.
    점수: 벽·모서리에 붙일수록(남는 빈 곳을 크게) 좋고, 같으면 목표에서 멀수록 [사용자 10/11 "빈 공간에 최대한 효율적으로"].
    실제 놓기·다시 집기 가능 여부는 oracle 로 따로 확인."""
    by = {o["id"]: o for o in objs}
    held = by[held_id]
    others = [o for o in objs if o["id"] != held_id and o["id"] not in riders(objs, held_id)
              and (on_floor(objs, o["id"]) or o.get("class") in LEG_CLASSES)]   # 바닥에 놓으니 바닥 물체만
    d, w = interior_m[0] * 1000.0, interior_m[1] * 1000.0
    out = []
    x = step_mm
    while x < d:
        y = step_mm
        while y < w:
            for yaw in yaws:
                c = dict(held, pose={"frame": frame, "position": [x / 1000.0, y / 1000.0, 0.0], "yaw": yaw})
                if not inside(c, size_of, interior_m, gap_mm):
                    continue
                if any(overlaps(c, o, size_of, gap_mm) for o in others):
                    continue
                if any(overlaps(c, a, size_of, avoid_pad_mm) for a in avoid):
                    continue
                fp = footprint_mm(c, size_of)
                wall = min(min(px, d - px, py, w - py) for px, py in fp)          # 가장 가까운 벽까지
                near = min((math.dist((x, y), (a["pose"]["position"][0] * 1000.0, a["pose"]["position"][1] * 1000.0))
                            for a in avoid), default=0.0)
                clear = min([_gap_mm(c, o, size_of) for o in others], default=1e9)   # 다른 물체까지 빈 거리 (벽은 놓기 검사가 봄)
                out.append((clear, wall, near, c))
            y += step_mm
        x += step_mm
    # 손가락이 들어갈 여유(clear ≥ min_clear_mm)가 있는 곳 중 벽에 붙고(빈 곳을 크게 남김) 목표에서 먼 순서
    ok = sorted([t for t in out if t[0] >= min_clear_mm], key=lambda t: (round(t[1] / 10.0), -t[2]))
    rest = sorted([t for t in out if t[0] < min_clear_mm], key=lambda t: -t[0])
    return [t[3] for t in ok + rest]


def _gap_mm(a: Mapping, b: Mapping, size_of: Callable) -> float:
    """두 바닥 사각형 사이 거리 근사 (꼭짓점 중 가장 가까운 것, 겹치면 0)."""
    if overlaps(a, b, size_of):
        return 0.0
    pa, pb = footprint_mm(a, size_of), footprint_mm(b, size_of)

    def seg_d(p, q1, q2):
        (x, y), (x1, y1), (x2, y2) = p, q1, q2
        dx, dy = x2 - x1, y2 - y1
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy or 1.0)))
        return math.hypot(x - x1 - t * dx, y - y1 - t * dy)
    return min([seg_d(p, pb[i], pb[(i + 1) % 4]) for p in pa for i in range(4)] +
               [seg_d(p, pa[i], pa[(i + 1) % 4]) for p in pb for i in range(4)])


def as_pose(o: Mapping) -> dict:
    p = o["pose"]
    yaw = (p["yaw"] + math.pi / 2) % math.pi - math.pi / 2
    if yaw <= -math.pi / 2 + 1e-9:
        yaw += math.pi
    return {"frame": p["frame"], "position": [round(p["position"][0], 4), round(p["position"][1], 4), 0.0],
            "yaw": min(round(yaw, 6), math.pi / 2)}      # (−π/2, π/2] — 반올림으로 π/2 를 넘지 않게


# ---------------------------------------------------------------- 계획: 다음 동작 하나 [사용자 10/11 순서]
@dataclass
class Config:
    interior_m: Sequence[float]
    frame: str
    size_of: Callable
    axes: Sequence[tuple] = AXES[:3]          # +x(안쪽) 빼기 — drag.push_inward_ok 거짓이면
    max_shift_m: float = 0.08                # drag.max_shift_mm
    nudge_step_m: float = 0.005
    sweep_step_m: float = 0.01
    max_chain: int = 2                       # 한 번에 같이 밀 물체 수 [추정 — 실물 확인 필요]
    slack_mm: float = 0.0                    # 넛지·밀기 뒤 여유 — 집기 검사가 딱 통과하는 거리보다 이만큼 더 (실행 값 make_room.slack_mm)
    round_classes: Sequence[str] = ("lip_balm",)
    free_try: int = 60                       # 빈 자리 후보 중 oracle 로 확인할 개수
    allow_unpickable_place: bool = True      # 다시 바로 집기 어려운 자리라도 놓을 수 있으면 치움 (목표 꺼내기 우선)
    neighbor_r_m: float = 0.08               # 목표 둘레 이 거리 안 물체는 옮겨 볼 후보
    avoid_pad_mm: float = 25.0               # 치운 물체를 목표에서 이만큼 떨어뜨려 놓음 (먼저 봄)
    near_pad_mm: float = 5.0                 # 위가 없으면 이만큼까지 가까이 — 목표 집기 손가락 자리를 안 막을 때만
    reach_x_m: Optional[float] = None
    remove_first: bool = True                # 옆 물체를 같이 미는 밀기보다 막는 물체 집어 치우기 먼저 — 실행 값 make_room.remove_first [사용자 10/12]
    narrow_of: Optional[Callable] = None     # 손잡이 폭(m) — 누를 점을 폭 방향으로 비킬 범위 (몽키·망치 item_grasp)
    press_center_only_classes: Sequence[str] = ("toy_wrench",)   # 가운데만 누름 — 머리·끝은 윗면이 낮음 [사용자 10/13 PC2]
    hole_classes: Sequence[str] = ("masking_tape",)            # 가운데가 뚫림 — 공간 만들기에서 안 누름(같이 밀리기·집기만) [사용자 10/13]
    front_keep_mm: float = 10.0              # 손잡이 쪽 벽(x 0)에서 이만큼 안으로 새로 들어오게 미는 동작은 벌점 — 앞벽에 붙으면 안쪽으로 못 끌어
    front_penalty_m: float = 0.05            # (서랍이 닫힘) 사방이 막혀 못 풂 [사용자 10/13 "sweep 할 때 손잡이 쪽 벽엔 최대한 붙이지 말기"] — 이동 거리로 셈
    sweep_max_m: Optional[float] = None      # 밀기(sweep) 최대 거리 — 없으면 max_shift_m. 실행 값 make_room.sweep_max_mm
    press_finger_r_mm: float = 16.0          # 누르는 닫은 손가락 범위(원 반지름) — 실행 값은 skills.yaml make_room.press_finger_r_mm [팀 확정 필요]        # 손이 수직으로 닿는 물체 가운데 x 최대 (drawer_reach_x_mm) — 빈 자리 후보에서 미리 뺌


def _round_axis_ok(t: Mapping, u: tuple, cfg: Config) -> bool:
    """원통형은 굴러가니 긴 변 방향으로만 [사용자 10/10 립밤]."""
    if t["class"] not in cfg.round_classes:
        return True
    yaw = t["pose"]["yaw"]
    return abs(u[0] * math.cos(yaw) + u[1] * math.sin(yaw)) >= math.cos(math.radians(20.0))


def pushable(o: Mapping) -> bool:
    """같이 밀려도 되는 물체: 다리 있는 물체(덮개 판)·위에 뭐가 얹힌 물체는 안 밂 (넘어짐·흩어짐) [추정]."""
    return o.get("class") not in LEG_CLASSES and not o.get("occluded_by")


def _with(objs, new_obj):
    return [new_obj if o["id"] == new_obj["id"] else o for o in objs]


def _relocated(objs, oid, pose, size_of=None):
    """oid 를 바닥의 pose 로 (받침에서 내림) — 받침의 occluded_by 에서 빼고 top_z 는 자기 온톨로지 높이.
    비전 top_z − 받침 top_z 로 빼지 않음: 쌓인 물체 top_z 는 마스크 번짐으로 틀림(캐러멜 54.6 vs 실제 37 mm, #216) [A·PM #226 리뷰]."""
    out = []
    for o in objs:
        if o["id"] == oid:
            h = size_of(o["class"])[2] if size_of else o["top_z"]
            out.append(dict(o, pose=dict(pose, yaw_valid=True), occluded_by=[], top_z=round(h, 4)))
        elif oid in (o.get("occluded_by") or []):
            out.append(dict(o, occluded_by=[x for x in o["occluded_by"] if x != oid]))
        else:
            out.append(o)
    return out


def find_free_pose(objs, held_id, avoid_ids, oracle, cfg: Config):
    """쥔 물체(held_id, 아직 원래 자리)를 놓을 빈 자리: 놓기 검사 통과 + 목표(avoid_ids) 둘레 비움.
    먼저 목표에서 cfg.avoid_pad_mm 떨어진 곳, 없으면 더 가까이(near_pad_mm)도 보되 놓은 물체가 목표를 집을 손가락 자리를
    막지 않는지 집기 검사로 확인 (가운데 가로로 놓인 몽키 위 차키 [P2 시뮬레이션 10/11: 25 mm 비우면 놓을 데가 없음]).
    놓은 뒤 바로 다시 집을 수 있는 곳을 먼저, 없으면 놓을 수만 있는 곳 (나중에 꺼낼 땐 그때 공간 만들기)."""
    fallback = None
    for pad in (cfg.avoid_pad_mm, cfg.near_pad_mm):
        avoid = [o for o in objs if o["id"] in avoid_ids]
        cands = [c for c in free_poses(objs, held_id, cfg.size_of, cfg.interior_m, cfg.frame, avoid=avoid, avoid_pad_mm=pad)
                 if cfg.reach_x_m is None or c["pose"]["position"][0] <= cfg.reach_x_m]   # 안쪽 벽에 붙여도 손이 안 닿으면 못 놓음
        for c in cands[: cfg.free_try]:
            pose = as_pose(c)
            ok, _, _ = oracle.place(objs, held_id, pose)
            if not ok:
                continue
            after = _relocated(objs, held_id, pose, cfg.size_of)
            if pad < cfg.avoid_pad_mm and any(_blocks(after, a, held_id, oracle) for a in avoid_ids):
                continue
            if oracle.pick(after, held_id)[0]:
                return pose
            if fallback is None and cfg.allow_unpickable_place:
                fallback = pose
        if fallback is not None:
            return fallback
    return None


def _blocks(objs, tid, placed_id, oracle) -> bool:
    """placed_id 가 목표 tid 를 집을 손가락·끄는 길을 막는지 — 목표 위 물체는 다 치웠다고 보고 집기 검사."""
    up = riders(objs, tid)
    rest = [dict(o, occluded_by=[]) if o["id"] == tid else o for o in objs if o["id"] not in up]
    ok, _, reason = oracle.pick(rest, tid)
    return not ok and placed_id in (reason or "")


def plan_next(objs: Sequence[Mapping], tid: str, oracle, cfg: Config, _depth: int = 0) -> Action:
    """목표 tid 를 집기까지 다음 동작 하나. oracle: pick(objs, id) → (ok, code, reason), place(objs, held_id, pose) → (ok, code, reason),
    wall_nudge(objs, id) → (새 목표 dict | None, code, reason).
    순서 [사용자 10/11]: ① 파지 공간 확보 — 위에 얹힌 것 빈 곳에 치우기 / 옆이 막히면 목표 넛지(빈 쪽)·좌우 밀기(사방 막힘)
    ② (다시 보기는 부르는 쪽) ③ 집기. 긴 변(가로) 잡기는 pick 검사 안에서 먼저 봄(우선순위 1)."""
    by = {o["id"]: o for o in objs}
    tops = [r for r in riders(objs, tid) if not riders(objs, r)]
    if tops:                                                       # 쌓임: 맨 위부터 빈 곳으로
        top = max(tops, key=lambda r: by[r]["top_z"])
        ok, code, reason = oracle.pick(objs, top)
        if not ok:
            if _depth >= 1:
                return Action("fail", top, f"위 물체 {top} 못 집음: {reason}", code=code)
            a = plan_next(objs, top, oracle, cfg, _depth + 1)      # 위 물체부터 공간 만들기
            return a if a.kind != "pick" else Action("fail", top, "계획 오류", code=code)
        pose = find_free_pose(objs, top, [tid], oracle, cfg)
        if pose is None:
            return Action("fail", top, f"{top} 놓을 빈 자리 없음", code="NO_FREE_SPACE")
        return Action("unstack", top, f"{top} → 빈 자리", to_pose=pose)
    ok, code, reason = oracle.pick(objs, tid)
    if ok:
        return Action("pick", tid)
    wall = None
    if code == "WALL_TOO_CLOSE":                                   # 벽: 벽 반대쪽으로 (기존 벽 넛지)
        after, c2, r2 = oracle.wall_nudge(objs, tid)
        if after is not None:
            wall = Action("wall_nudge", tid, r2, to_pose=as_pose(after), extra={"after": after})
            if oracle.pick(apply(objs, wall, cfg), tid)[0]:
                return wall
        else:
            code, reason = c2 or code, r2 or reason
    if not press_ok(objs, tid, cfg.size_of, **_pkw(cfg)):
        if wall is not None:
            return wall
        return _remove_blocker(objs, tid, oracle, cfg, code, reason, _depth)
    # 한 번 움직여 잡힘: 빈 쪽 넛지(안 밂) 또는 한쪽으로 쭉 밀고(옆 물체 같이) 되돌아오기 — 덜 움직이는 것부터.
    # remove_first: 목표 말고는 다 방해물 — 벽은 못 움직이고 물체는 옮길 수 있음 [사용자 10/12]. 다른 물체를 건드리지 않는
    # 넛지 → 막는 물체를 집어 빈 자리로 → (그래도 안 되면) 옆 물체를 같이 미는 밀기 순서
    # 순서 [사용자 10/13 "넛지로 넓은 공간으로 끌어온 뒤 집기 → 안 되면 sweep 으로 근처 정리 → 그래도 안 되면 다른 놈들 치우기"]:
    # 다른 물체를 안 건드리는 넛지 먼저(그중 덜 움직이는 것), 그다음 옆 물체를 같이 미는 sweep. 치우기는 아래(remove_first 면 sweep 보다 먼저)
    moves = sorted(_self_moves(objs, tid, cfg, fine=True), key=lambda c: (bool(c[1].pushed), c[0]))
    for cost, act, after in moves:
        if (not cfg.remove_first or not act.pushed) and oracle.pick(after, tid)[0]:
            return _with_slack(moves, act, tid, oracle, cfg.slack_mm)
    if cfg.remove_first:
        a = _remove_to_open(objs, tid, oracle, cfg, reason) or _nudge_blocker(objs, tid, oracle, cfg, reason)
        if a is not None:
            return a
        for cost, act, after in moves:
            if act.pushed and oracle.pick(after, tid)[0]:
                return _with_slack(moves, act, tid, oracle, cfg.slack_mm)
    # 두 번 움직여야 잡힘 (예: 뒷벽에서 빼고 → 옆벽에서 빼기): 첫 동작만 하고 다시 보기 [사용자 10/11 순서]
    best = None
    for c1, a1, o1 in sorted(_self_moves(objs, tid, cfg, fine=False, coarse=True), key=lambda c: c[0]):
        if best is not None and c1 >= best[0]:
            break
        if not press_ok(o1, tid, cfg.size_of, **_pkw(cfg)):   # 두 번째도 눌러서 움직여야 함
            continue
        for c2, a2, o2 in sorted(_self_moves(o1, tid, cfg, fine=False), key=lambda c: c[0]):
            if a2.dir in (a1.dir, (-a1.dir[0], -a1.dir[1])) or (best is not None and c1 + c2 >= best[0]):
                continue
            if oracle.pick(o2, tid)[0]:
                best = (c1 + c2, a1, a2)
                break
    if best:
        a1, a2 = best[1], best[2]
        a1.reason += f" → 다시 보고 {a2.kind} {a2.dir} (2단계)"
        return a1
    if wall is not None:                                           # 벽 넛지만으론 아직 안 잡히지만 벽에서는 벗어남
        return wall
    # 목표만 움직여선 안 됨 → 막는 물체를 집어 빈 자리로 옮긴 뒤 목표를 한 번 움직이면(넛지·밀기) 집힘 [사용자 10/13]
    a = _remove_to_open(objs, tid, oracle, cfg, reason, then_move=True) if _depth == 0 else None
    if a is not None:
        return a
    return _remove_blocker(objs, tid, oracle, cfg, code, reason, _depth)


def _remove_to_open(objs, tid, oracle, cfg: Config, reason: str = "", then_move: bool = False) -> Optional[Action]:
    """막는 물체를 집어 빈 자리로 옮기면 목표를 바로(또는 벽 넛지 몇 번으로) 집을 수 있게 되는지 — 거부 이유에 나온 물체 먼저,
    그다음 목표 가까운 바닥 물체. 그 물체를 지금 집을 수 없으면 건너뜀(그 물체 둘레 공간 만들기는 _remove_blocker)."""
    near = _near_blockers(objs, tid, cfg, reason)
    for o in near:
        if not oracle.pick(objs, o["id"])[0]:
            continue
        pose = find_free_pose(objs, o["id"], [tid], oracle, cfg)
        if pose is None:
            continue
        if _opens_way(_relocated(objs, o["id"], pose, cfg.size_of), tid, oracle, cfg=cfg if then_move else None):
            return Action("remove", o["id"], f"막는 {o['id']} → 빈 자리 (목표 {tid} 손가락·끄는 길 비움"
                          + (", 다음에 목표 넛지·밀기" if then_move else "") + ")", to_pose=pose)
    return None


def _near_blockers(objs, tid, cfg: Config, reason: str = "") -> list:
    """목표 둘레 바닥 물체 (거부 이유에 나온 물체 먼저, 그다음 가까운 순) — 위에 뭐가 얹힌 것·목표 위 물체는 뺌."""
    by = {o["id"]: o for o in objs}
    tx, ty = by[tid]["pose"]["position"][:2]
    who = next((i for i in by if i != tid and i in (reason or "")), None)
    return sorted((o for o in objs if o["id"] != tid and on_floor(objs, o["id"]) and not riders(objs, o["id"])
                   and tid not in (o.get("occluded_by") or [])
                   and (o["id"] == who or math.dist((tx, ty), o["pose"]["position"][:2])
                        <= cfg.neighbor_r_m + 0.5 * max(cfg.size_of(o["class"])[:2]))),
                  key=lambda o: (o["id"] != who, math.dist((tx, ty), o["pose"]["position"][:2])))[:4]


def _nudge_blocker(objs, tid, oracle, cfg: Config, reason: str = "") -> Optional[Action]:
    """막는 물체를 지금 못 집을 때(그 물체도 벽·다른 물체에 막힘): 그 물체만 다른 것을 안 건드리고 넛지 —
    ① 그것만으로 목표 길이 열리면 ② 아니면 그 물체를 집을 수 있게 되면(다음 단계에서 집어 빈 자리로) [사용자 10/12]."""
    later = None
    for o in _near_blockers(objs, tid, cfg, reason):
        if oracle.pick(objs, o["id"])[0] or not press_ok(objs, o["id"], cfg.size_of, **_pkw(cfg)):
            continue
        for c, a, after in sorted(_self_moves(objs, o["id"], cfg, fine=False), key=lambda c: c[0]):
            if a.pushed:
                continue
            if _opens_way(after, tid, oracle):
                a.reason = f"{o['id']} 를 " + a.reason + f" — {tid} 집을 자리 열림"
                return a
            if later is None and oracle.pick(after, o["id"])[0]:
                a.reason = f"{o['id']} 를 " + a.reason + " — 집을 수 있게 (다음에 빈 자리로)"
                later = a
    return later


def _dir_name(u) -> str:
    """서랍 축 방향 이름 (x 0 = 손잡이 쪽 벽) — B plan 이유에 어느 쪽으로 움직이는지 보이게."""
    return {(-1.0, 0.0): "-x 손잡이 쪽", (1.0, 0.0): "+x 안쪽", (0.0, 1.0): "+y", (0.0, -1.0): "-y"}.get(
        (float(u[0]), float(u[1])), f"{u[0]:+.2f}, {u[1]:+.2f}")


def _with_slack(moves, act: "Action", tid: str, oracle, slack_mm: float) -> "Action":
    """고른 넛지·밀기보다 slack_mm 더 여유 있는 같은 종류·방향 후보 (넛지는 더 멀리, 밀기는 같은 거리 밀고 더 많이 되돌아옴) 중
    집기 검사를 통과하는 가장 가까운 것. 없으면 그대로 [사용자 10/13 PC2: 딱 통과하는 최소값이라 실물에서 다시 막혀 같은 밀기 반복]."""
    if slack_mm <= 0 or act.kind not in ("nudge", "sweep"):
        return act
    need = slack_mm / 1000.0 - 1e-9
    best = None
    for _, a, after in moves:
        if a.kind != act.kind or a.dir != act.dir:
            continue
        if a.kind == "nudge" and a.dist_m >= act.dist_m + need:
            key = a.dist_m
        elif a.kind == "sweep" and abs(a.dist_m - act.dist_m) < 1e-6 and a.back_m >= act.back_m + need:
            key = a.back_m
        else:
            continue
        if (best is None or key < best[0]) and oracle.pick(after, tid)[0]:
            best = (key, a)
    return best[1] if best else act


def _front_cost(before, after, cfg: Config) -> float:
    """움직인 물체(목표·같이 밀린 것) 중 손잡이 쪽 벽(x 0)에 front_keep_mm 안으로 새로 붙는 게 있으면 front_penalty_m (아니면 0)."""
    if cfg.front_penalty_m <= 0:
        return 0.0
    old = {o["id"]: o for o in before}
    for o in after:
        b = old.get(o["id"])
        if b is None or b["pose"]["position"][:2] == o["pose"]["position"][:2]:
            continue
        x_new = min(x for x, _ in footprint_mm(o, cfg.size_of))
        if x_new < cfg.front_keep_mm and x_new < min(x for x, _ in footprint_mm(b, cfg.size_of)) - 0.5:
            return cfg.front_penalty_m
    return 0.0


def _self_moves(objs, tid, cfg: Config, fine: bool = True, coarse: bool = False) -> list:
    """목표 자신을 서랍 축으로 움직이는 후보 → [(움직인 거리 m, Action, 예상 물체 목록)].
    nudge: 막힘 없이 끌기 / sweep: 앞 물체를 같이 밀고(최대 max_chain) back 만큼 되돌아오기 (양쪽 공간) [사용자 10/11].
    fine: 5 mm 간격·되돌아오기 전부 / 아니면 10 mm·되돌아오기 0·절반. coarse: 축마다 몇 개만 (2단계 첫 동작용)."""
    t = next(o for o in objs if o["id"] == tid)
    step = cfg.nudge_step_m if fine else cfg.sweep_step_m
    out = []
    pp_ = press_point(objs, tid, cfg.size_of, **_pkw(cfg))
    press = {"press_xy_m": [round(v, 4) for v in pp_]} if pp_ else {}
    for u in cfg.axes:
        if not _round_axis_ok(t, u, cfg):
            continue
        can = free_move(objs, tid, u, cfg.max_shift_m, cfg.interior_m, cfg.size_of)
        dists = [k * step for k in range(1, int(can / step + 1e-6) + 1)]
        for s in dists:
            after = _with(objs, moved(t, u[0] * s, u[1] * s))
            out.append((s + _front_cost(objs, after, cfg),
                        Action("nudge", tid, f"빈 쪽({_dir_name(u)})으로 {s * 1000:.0f} mm", dir=u, dist_m=s, extra=dict(press)), after))
        d = (int(can / cfg.sweep_step_m + 1e-6) + 1) * cfg.sweep_step_m
        last = can
        while d <= (cfg.sweep_max_m or cfg.max_shift_m) + 1e-9:
            o2, done, pushed = push_move(objs, tid, u, d, cfg.interior_m, cfg.size_of, pushable, cfg.max_chain)
            if done <= last + 0.0015:                                  # 더 못 밂
                break
            last = done
            t2 = next(o for o in o2 if o["id"] == tid)
            back_max = free_move(o2, tid, (-u[0], -u[1]), done, cfg.interior_m, cfg.size_of)
            if fine:
                backs = [k * cfg.nudge_step_m for k in range(int(back_max / cfg.nudge_step_m + 1e-6) + 1)]
            else:
                backs = sorted({0.0, round(min(done / 2.0, back_max), 3)})
            for bk in backs:
                act = Action("sweep", tid, f"{done * 1000:.0f} mm 밀고 {bk * 1000:.0f} mm 되돌아옴 (같이 밀림 {list(pushed)})",
                             dir=u, dist_m=done, back_m=bk, pushed=tuple(pushed), extra=dict(press))
                after = _with(o2, moved(t2, -u[0] * bk, -u[1] * bk))
                out.append((done + bk + _front_cost(objs, after, cfg), act, after))
            d += cfg.sweep_step_m
    if coarse:                                                         # 종류·방향마다 짧게·중간·끝까지만
        keep = []
        for key in {(a.kind, a.dir) for _, a, _ in out}:
            grp = sorted((c for c in out if (c[1].kind, c[1].dir) == key), key=lambda c: (c[1].dist_m, c[1].back_m))
            ds = sorted({c[1].dist_m for c in grp})
            pick = {ds[0], ds[-1], min(ds, key=lambda v: abs(v - 0.04))}
            keep += [c for c in grp if c[1].dist_m in pick]
        out = keep
    return out


def _remove_blocker(objs, tid, oracle, cfg, code, reason, depth) -> Action:
    """마지막: 막는 이웃을 치움 (#117 '물체 영역은 치울 수 있음').
    ① 거부 이유에 나온 이웃을 집어 빈 곳으로 ② 이웃(이유에 나온 것 먼저, 그다음 목표 둘레)을 넛지·밀기 — 목표가 잡히게 되는 것
    ③ 집지도 밀지도 못하면 그 이웃 둘레부터 공간 만들기 (한 단계만)."""
    by = {o["id"]: o for o in objs}
    t = by[tid]
    who = next((i for i in by if i != tid and i in (reason or "")), None)
    if who and depth <= 1 and not riders(objs, who):
        ok, c2, r2 = oracle.pick(objs, who)
        if ok:
            pose = find_free_pose(objs, who, [tid], oracle, cfg)
            if pose is not None:
                return Action("remove", who, f"막는 {who} → 빈 자리", to_pose=pose)
    if depth == 0:
        tx, ty = t["pose"]["position"][:2]
        near = sorted((o for o in objs if o["id"] != tid and on_floor(objs, o["id"]) and pushable(o)
                       and tid not in (o.get("occluded_by") or [])
                       and (o["id"] == who or
                            math.dist((tx, ty), o["pose"]["position"][:2]) <= cfg.neighbor_r_m + 0.5 * max(cfg.size_of(o["class"])[:2]))),
                      key=lambda o: (o["id"] != who, math.dist((tx, ty), o["pose"]["position"][:2])))
        best = then = None
        for o in near[:4]:
            if not press_ok(objs, o["id"], cfg.size_of, **_pkw(cfg)):
                continue
            for c, a, after in sorted(_self_moves(objs, o["id"], cfg, fine=False), key=lambda c: c[0]):
                if tid in a.pushed or (best is not None and c >= best[0]):
                    continue
                if _opens_way(after, tid, oracle):
                    best = (c, a)
                    break
                if then is None and _opens_way(after, tid, oracle, wall_steps=0, cfg=cfg):   # 이웃 옮긴 뒤 목표 넛지·밀기 한 번 [사용자 10/13]
                    then = a
        if best:
            a = best[1]
            a.reason = f"목표 {tid} 옆 {a.target} 를 " + a.reason
            return a
        if then:
            then.reason = f"목표 {tid} 옆 {then.target} 를 " + then.reason + f" — 다음에 {tid} 넛지·밀기"
            return then
    if who and depth == 0 and not riders(objs, who):               # 막는 물체도 못 집으면 그 물체 둘레부터 공간 만들기 (한 단계만)
        a = plan_next(objs, who, oracle, cfg, depth + 1)
        if a.kind in ("nudge", "sweep", "wall_nudge", "unstack", "remove"):
            return Action(a.kind, a.target, f"막는 {who} 먼저 — {a.reason}", to_pose=a.to_pose, dir=a.dir,
                          dist_m=a.dist_m, back_m=a.back_m, pushed=a.pushed, extra=a.extra)
    return Action("fail", tid, reason or "", code=code or "")


def _opens_way(objs, tid, oracle, wall_steps: int = 3, cfg: Optional[Config] = None) -> bool:
    """이웃을 옮긴 뒤 목표를 바로 집거나, 벽 넛지만 몇 번(끄는 길이 비어서, 예: 안쪽 벽 → 옆벽)으로 집을 수 있게 되는지
    (예: 아래 칸 안쪽 구석 물체를 손잡이 쪽으로 끌어야 하는데 지우개가 가로막음 → 지우개를 옆으로 밀면 길이 열림).
    cfg 를 주면 목표를 한 번 움직여(넛지·밀기) 집히는 것도 됨 — 막는 물체 치우기 → 목표 sweep [사용자 10/13 "sweep 해도 각이
    안 나오면 다음 순서를 찾아야지": 앞벽 에어팟 뒤 몽키를 빈 자리로 → 에어팟 sweep]."""
    cur = objs
    for _ in range(wall_steps + 1):
        ok, code, _ = oracle.pick(cur, tid)
        if ok:
            return True
        if code != "WALL_TOO_CLOSE":
            break
        after, _, _ = oracle.wall_nudge(cur, tid)
        if after is None:
            break
        cur = _with(cur, after)
    if cfg is not None and press_ok(objs, tid, cfg.size_of, **_pkw(cfg)):
        return any(oracle.pick(after, tid)[0] for _, _, after in sorted(_self_moves(objs, tid, cfg, fine=False), key=lambda c: c[0]))
    return False


def apply(objs: Sequence[Mapping], a: Action, cfg: Config) -> list:
    """계획한 동작의 예상 결과 (시뮬레이션·다시 보기 전 예상). 실물은 동작 뒤 다시 보기로 확인."""
    if a.kind in ("unstack", "remove"):
        return _relocated(objs, a.target, a.to_pose, cfg.size_of)
    if a.kind == "wall_nudge":
        return _with(objs, dict(a.extra["after"], occluded_by=next(o for o in objs if o["id"] == a.target).get("occluded_by", [])))
    if a.kind == "nudge":
        t = next(o for o in objs if o["id"] == a.target)
        return _with(objs, moved(t, a.dir[0] * a.dist_m, a.dir[1] * a.dist_m))
    if a.kind == "sweep":
        o2, _, _ = push_move(objs, a.target, a.dir, a.dist_m, cfg.interior_m, cfg.size_of, pushable, cfg.max_chain)
        t2 = next(o for o in o2 if o["id"] == a.target)
        return _with(o2, moved(t2, -a.dir[0] * a.back_m, -a.dir[1] * a.back_m))
    return list(objs)
