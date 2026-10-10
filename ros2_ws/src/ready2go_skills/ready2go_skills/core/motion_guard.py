"""모션 원자 동작을 시작하기 전 확인 (ROS 비의존·pytest 대상, #15·#19).

걸리면 로봇을 움직이지 않고 에러 코드를 반환한다. 코드 의미의 정본은 docs/runner.md 7.1 에러 코드 표.
  TOOL_NOT_SET         펜던트 활성 TCP·툴이 기대값과 다르거나 조회 실패 (결정 #28, #6 3점 터치 사고)
  DRAWER_NOT_AT_TRAVEL 서랍 인출 거리가 places.yaml `tf_at_travel_m`(서랍 좌표계가 유효한 거리)에서 벗어남
  YAW_INVALID          target.pose.yaw_valid 가 True 가 아님(false·없음) — yaw 0 은 자리표시라 쓰면 안 됨
  NOT_ON_FLOOR         top_z 가 물체 높이보다 커서 다른 물체 위에 있음 — 쌓인 집기(P2, `max_top_m`)를 안 켰거나,
                       켰어도 윗면이 서랍 테두리에 너무 가까움(서랍 안 옆 이동 높이와 부딪힘)
다시 인식은 스킬이 아니라 태스크(C)가 한다. 허용 오차는 params/skills.yaml 에서 받는다 [팀 확정 필요].
"""
import math
from dataclasses import dataclass
from typing import Mapping, Optional

TOOL_NOT_SET = "TOOL_NOT_SET"
DRAWER_NOT_AT_TRAVEL = "DRAWER_NOT_AT_TRAVEL"
YAW_INVALID = "YAW_INVALID"
NOT_ON_FLOOR = "NOT_ON_FLOOR"


@dataclass(frozen=True)
class GuardError:
    error_code: str
    reason: str


def _finite(*values) -> bool:
    """모두 bool이 아닌 유한한 숫자인지. NaN·inf는 비교가 항상 False라 그대로 쓰면 확인을 통과해 버린다 (#70 D 리뷰)."""
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def expected_tool(meta: Mapping) -> tuple:
    """config/calibration/calibration_meta.yaml 에서 기대 (TCP 이름, 툴 이름). 이름을 코드에 두지 않는다."""
    tcp = meta["tcp"]
    return tcp["name_on_pendant"], tcp["tool_weight_on_pendant"]["name"]


def check_tool(current_tcp: Optional[str], current_tool: Optional[str],
               expected_tcp: str, expected_tool_name: str) -> Optional[GuardError]:
    """`get_current_tcp`·`get_current_tool` 결과 확인. 서비스 실패는 None 으로 넘긴다."""
    if current_tcp is None or current_tool is None:
        return GuardError(TOOL_NOT_SET, "활성 TCP·툴 조회 실패")
    if current_tcp != expected_tcp:
        return GuardError(TOOL_NOT_SET, f"활성 TCP {current_tcp!r} ≠ {expected_tcp!r}")
    if current_tool != expected_tool_name:
        return GuardError(TOOL_NOT_SET, f"활성 툴 {current_tool!r} ≠ {expected_tool_name!r}")
    return None


def check_travel(displacement_m: Optional[float], tf_at_travel_m: float,
                 tolerance_m: float) -> Optional[GuardError]:
    """마지막 `drawer_control` 결과의 `drawer_displacement`가 `tf_at_travel_m` 허용 오차 안인지. 값이 없으면 거부."""
    if not _finite(displacement_m, tf_at_travel_m, tolerance_m):
        return GuardError(DRAWER_NOT_AT_TRAVEL,
                          f"인출 거리 값 없음·비정상 ({displacement_m!r}, 기준 {tf_at_travel_m!r}, 허용 {tolerance_m!r})")
    if abs(displacement_m - tf_at_travel_m) > tolerance_m:
        return GuardError(DRAWER_NOT_AT_TRAVEL,
                          f"인출 {displacement_m * 1000:.1f} mm, 기준 {tf_at_travel_m * 1000:.1f} mm")
    return None


def check_yaw(target: Mapping) -> Optional[GuardError]:
    """`target`(inspect_region 결과 그대로)의 pose.yaw_valid. 기본값을 넣지 않는다 — 없으면 거부."""
    valid = (target.get("pose") or {}).get("yaw_valid")
    if valid is not True:
        return GuardError(YAW_INVALID, f"yaw를 믿을 수 없음 (yaw_valid={valid!r}) — 다시 인식 필요")
    return None


def check_on_floor(target: Mapping, height_m: float, tolerance_m: float) -> Optional[GuardError]:
    """top_z − 물체 높이(온톨로지 size_m[2])가 허용 오차보다 크면 다른 물체 위. top_z 가 없으면 거부."""
    top_z = target.get("top_z")
    if not _finite(top_z, height_m, tolerance_m):
        return GuardError(NOT_ON_FLOOR, f"top_z·높이 값 없음·비정상 (top_z {top_z!r}, 높이 {height_m!r}, 허용 {tolerance_m!r})")
    if top_z < -tolerance_m:
        return GuardError(NOT_ON_FLOOR, f"top_z {top_z * 1000:.1f} mm — 바닥 아래라 측정 오류")
    if top_z - height_m > tolerance_m:
        return GuardError(NOT_ON_FLOOR,
                          f"top_z {top_z * 1000:.1f} mm > 높이 {height_m * 1000:.1f} mm + {tolerance_m * 1000:.1f} mm")
    return None


def check_stack(target: Mapping, height_m: float, tolerance_m: float, max_top_m: float) -> Optional[GuardError]:
    """쌓인 물체 집기 [사용자 10/09, P2 3개 겹침]: 바닥 확인(check_on_floor)과 같은 값 검사 + 윗면이 `max_top_m` 이하."""
    top_z = target.get("top_z")
    if not _finite(top_z, height_m, tolerance_m, max_top_m):
        return GuardError(NOT_ON_FLOOR, f"top_z·높이 값 없음·비정상 (top_z {top_z!r}, 높이 {height_m!r}, 상한 {max_top_m!r})")
    if top_z < -tolerance_m:
        return GuardError(NOT_ON_FLOOR, f"top_z {top_z * 1000:.1f} mm — 바닥 아래라 측정 오류")
    if top_z - height_m > tolerance_m and top_z > max_top_m:
        return GuardError(NOT_ON_FLOOR, f"쌓인 윗면 {top_z * 1000:.1f} mm > 상한 {max_top_m * 1000:.1f} mm (서랍 테두리에 너무 가까움)")
    return None


def support_m(target: Mapping, height_m: float, tolerance_m: float) -> float:
    """받침 높이 = top_z − 물체 높이. 허용 오차 안이면 바닥(0). precheck_pick 을 통과한 target 에만 쓴다."""
    s = target["top_z"] - height_m
    return s if s > tolerance_m else 0.0


def precheck_nudge(*, target: Mapping, displacement_m: Optional[float], tf_at_travel_m: float,
                   params: Mapping) -> Optional[GuardError]:
    """`nudge_object` 시작 전 (인출 거리 → yaw). 툴 확인은 노드 시작·첫 동작 직전에 따로 한다."""
    return (check_travel(displacement_m, tf_at_travel_m, params["travel_tolerance_m"])
            or check_yaw(target))


def precheck_pick(*, target: Mapping, height_m: float, displacement_m: Optional[float],
                  tf_at_travel_m: float, params: Mapping, max_top_m: Optional[float] = None) -> Optional[GuardError]:
    """서랍에서 `pick_object` 시작 전 (인출 거리 → yaw → 바닥 위·쌓임). 트레이(`source_slot`)에서 집을 때는 쓰지 않는다.
    `max_top_m` 이 None 이면 다른 물체 위는 거부(P1), 값이 있으면 윗면이 그 이하인 쌓인 물체도 통과(P2)."""
    tol = params["on_floor_tolerance_m"]
    return (precheck_nudge(target=target, displacement_m=displacement_m,
                           tf_at_travel_m=tf_at_travel_m, params=params)
            or (check_on_floor(target, height_m, tol) if max_top_m is None
                else check_stack(target, height_m, tol, max_top_m)))
