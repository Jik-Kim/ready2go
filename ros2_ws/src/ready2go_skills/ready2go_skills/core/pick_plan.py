"""`pick_object`·`place_object` 계산 (#15, ROS 비의존·pytest 대상).

서랍에서 집기: `target`(inspect_region 결과, 서랍 좌표계) + 온톨로지 `size_m` → base 기준 파지 위치·방향·벌림 폭.
  - 위치: `pose.position` x·y를 서랍 tf(`places.yaml`)로 base에 옮김. 높이는 서랍 바닥(z=0) 기준으로 계산한다
    (바닥 물체는 `top_z`·카메라 뎁스 z를 쓰지 않음, #18). 시작 전 확인(인출 거리·yaw_valid·바닥 위)은 motion_guard.precheck_pick.
  - 높이: TCP를 받침 위 max(물체 높이 + tcp_above_top_m, min_tcp_above_floor_m)에 둔다. 받침 = 바닥(0), 쌓인 물체는
    `support_m` = top_z − 물체 높이 (motion_guard.support_m, 비전 뎁스 — [사용자 10/09] P2 3개 겹침).
    [실측 B 10/04, #8] 지우개(11.5 mm)를 TCP 바닥 위 10.0~11.4 mm에서 3/3 파지 → tcp_above_top_m ≈ 0.
  - 방향: 짧은 변을 잡는다 = 손가락이 긴 변(yaw)에 수직으로 닫힘. 출력은 base 기준 긴 변 각도(deg, (−90, 90]).
    노드는 이 각도에 수직으로 손가락을 닫는 그리퍼 자세를 만든다(`motion_plan.gripper_posx`, 손가락은 툴 x축으로 닫힘 [실측 B 10/05]).
  - 벌림: 짧은 변 + open_margin_m [실측 B 10/04: 물건 폭 + 약 13 mm만 벌리고 접근, 완전히 벌리면 손끝이 바닥에 닿음].
트레이 놓기: 슬롯 중심을 트레이 좌표계(x = 긴 변 방향, 원점 = 바닥 안쪽 모서리)에서 균등 분할로 구한다.
"""
import math
from dataclasses import dataclass
from typing import Mapping, Sequence


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def check_tf(tf: Mapping) -> None:
    """tf 블록이 유한한 숫자이고 쿼터니언이 단위 길이인지. 아니면 ValueError — 로봇 목표로 보내지 않음 (#71 D 리뷰)."""
    t, q = tf.get("translation_m"), tf.get("quaternion_xyzw")
    if not (isinstance(t, Sequence) and len(t) == 3 and isinstance(q, Sequence) and len(q) == 4 and _finite(*t, *q)):
        raise ValueError(f"tf 값 없음·비정상: translation {t!r}, quaternion {q!r}")
    if abs(math.sqrt(sum(c * c for c in q)) - 1.0) > 1e-3:
        raise ValueError(f"쿼터니언 길이가 1이 아님: {q!r}")


def check_pick_params(p: Mapping) -> None:
    """params/skills.yaml `pick` 값이 유한하고 범위 안인지. 아니면 ValueError."""
    keys = ("tcp_above_top_m", "min_tcp_above_floor_m", "open_margin_m", "max_open_width_m")
    vals = [p.get(k) for k in keys]
    if not _finite(*vals):
        raise ValueError(f"pick 파라미터 없음·비정상: {dict(zip(keys, vals))}")
    above, min_above, margin, max_open = vals
    if min_above <= 0 or margin < 0 or not 0 < max_open <= 0.110 or abs(above) > 0.05:
        raise ValueError(f"pick 파라미터 범위 밖: {dict(zip(keys, vals))}")   # RG2 최대 벌림 110 mm [문서]


def rotate(q_xyzw: Sequence[float], v: Sequence[float]) -> tuple:
    """쿼터니언(xyzw)으로 벡터 회전."""
    x, y, z, w = q_xyzw
    r = ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
         (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
         (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))
    return tuple(sum(r[i][j] * v[j] for j in range(3)) for i in range(3))


def to_base(tf: Mapping, p: Sequence[float]) -> tuple:
    """`places.yaml`의 tf 블록(parent = base_link)으로 자식 좌표계 점 p(m)를 base로."""
    t = tf["translation_m"]
    return tuple(a + b for a, b in zip(t, rotate(tf["quaternion_xyzw"], p)))


def frame_yaw_deg(tf: Mapping) -> float:
    """자식 좌표계 x축의 base 기준 수평 각도(deg)."""
    ax = rotate(tf["quaternion_xyzw"], (1.0, 0.0, 0.0))
    return math.degrees(math.atan2(ax[1], ax[0]))


def wrap_line_deg(a: float) -> float:
    """직선 방향 각도를 (−90, 90]로 (평행 그리퍼는 180° 대칭)."""
    a = (a + 90.0) % 180.0 - 90.0
    return 90.0 if math.isclose(a, -90.0) else a


@dataclass(frozen=True)
class GraspPlan:
    position_m: tuple          # base 기준 TCP 목표 (x, y, z)
    long_axis_deg: float       # base 기준 물체 긴 변 방향 (−90, 90]. 손가락은 이에 수직으로 닫힘
    open_width_m: float        # 내려가기 전 벌림 폭
    expected_width_m: float    # grasp_check 기대 폭 (짧은 변)


def plan_drawer_grasp(*, target: Mapping, size_m: Sequence[float], tf: Mapping, params: Mapping,
                      support_m: float = 0.0, long_side: bool = False) -> GraspPlan:
    """`target`은 motion_guard.precheck_pick을 통과한 것만 넘긴다(yaw_valid true, 바닥 위·허용된 쌓임).
    long_side: 긴 변 양끝을 잡음(손가락 닫힘 축 = 긴 변) — 짧은 변 잡기가 벽에 걸릴 때만 [사용자 10/10].
    이때 long_axis_deg 는 90° 돌려 돌려줌(닫힘 축 = long_axis_deg + 90 규칙 유지), 벌림·기대 폭은 긴 변 기준."""
    if not _finite(support_m) or support_m < 0:
        raise ValueError(f"받침 높이는 0 이상 유한한 값: {support_m!r}")
    check_tf(tf)
    check_pick_params(params)
    x, y = target["pose"]["position"][:2]
    length, width, height = size_m
    vals = (x, y, target["pose"]["yaw"], length, width, height)
    if not _finite(*vals):
        raise ValueError(f"위치·yaw·크기에 NaN·inf·숫자 아닌 값: {vals}")     # 로봇 목표로 보내지 않음
    if min(length, width, height) <= 0:
        raise ValueError(f"size_m은 모두 양수: {size_m}")
    if width > length:
        raise ValueError(f"size_m 규약은 [긴 변, 짧은 변, 높이]: {size_m}")
    above_floor = support_m + max(height + params["tcp_above_top_m"], params["min_tcp_above_floor_m"])
    pos = to_base(tf, (x, y, above_floor))
    long_axis = wrap_line_deg(frame_yaw_deg(tf) + math.degrees(target["pose"]["yaw"]) + (90.0 if long_side else 0.0))
    if long_side:
        width = length
    open_w = width + params["open_margin_m"]
    if open_w > params["max_open_width_m"]:
        raise ValueError(f"벌림 폭 {open_w * 1000:.1f} mm > 최대 {params['max_open_width_m'] * 1000:.1f} mm")
    if not _finite(*pos, long_axis, open_w):                     # 마지막으로 한 번 더 (fail-closed)
        raise ValueError(f"계산 결과 비정상: {pos}, {long_axis}, {open_w}")
    return GraspPlan(pos, long_axis, open_w, width)


def slot_centers(bottom_size_m: Sequence[float], n: int, inset_m: Sequence[float] = (0.0, 0.0)) -> list:
    """트레이 바닥(긴 변 x, 짧은 변 y)을 x 방향으로 n칸 균등 분할한 슬롯 중심 (트레이 좌표계, z = 0).
    `inset_m`: 원점(3점 터치 기준점)에서 바닥 안쪽 모서리까지 (x, y) 거리 — 테두리 투영 원점이면 기울어진 벽만큼."""
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError(f"슬롯 수는 1 이상 정수: {n!r}")
    lx, ly = bottom_size_m[:2]
    if not (_finite(lx, ly, *inset_m[:2]) and lx > 0 and ly > 0):
        raise ValueError(f"트레이 크기·원점 보정 비정상: {bottom_size_m!r}, {inset_m!r}")
    return [(inset_m[0] + lx * (i + 0.5) / n, inset_m[1] + ly / 2, 0.0) for i in range(n)]
