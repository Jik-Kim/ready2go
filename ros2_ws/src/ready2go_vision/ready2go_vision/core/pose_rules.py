"""inspect_region 결과의 pose 규칙 (ROS 비의존). 정의 원본: docs/runner.md 7.1, 서랍 좌표계는 config/places.yaml 첫 부분.

- position = YOLO 박스 중심의 서랍 좌표계 x·y [m], position.z = 0 (높이는 top_z 에만 둔다)
- yaw = 물체 긴 변 방향(서랍 x축 기준 rad), 범위 (-pi/2, pi/2]. 긴 변은 180° 돌려도 같은 직선이라 한 범위로 고정한다.
  원통·정사각형처럼 긴 변이 없는 물체는 0 으로 고정한다 (대칭 판정 기준은 아직 [팀 확정 필요]).
"""
import math

EPS = 1e-9


def normalize_yaw(yaw: float) -> float:
    """임의의 각도(rad)를 같은 직선을 나타내는 (-pi/2, pi/2] 값으로. -pi/2 는 +pi/2 로 쓴다."""
    return yaw - math.pi * math.ceil(yaw / math.pi - 0.5)


def pose_errors(pose: dict, where: str = "pose") -> list[str]:
    errs = []
    pos = pose.get("position")
    if not (isinstance(pos, list) and len(pos) == 3):
        errs.append(f"{where}.position 은 [x, y, z] 3개 값")
    elif abs(pos[2]) > EPS:
        errs.append(f"{where}.position.z 는 0 이어야 함 (높이는 top_z) — 값 {pos[2]}")
    yaw = pose.get("yaw")
    if not isinstance(yaw, (int, float)):
        errs.append(f"{where}.yaw 는 숫자(rad)")
    elif not (-math.pi / 2 + EPS < yaw <= math.pi / 2 + EPS):
        errs.append(f"{where}.yaw 는 (-pi/2, pi/2] 범위 — 값 {yaw}")
    return errs


def result_errors(result: dict) -> list[str]:
    """inspect_region result_json 의 target·candidates pose 검사. 빈 리스트면 규칙을 지킨 것."""
    errs = []
    items = [("target", result.get("target"))] + [(f"candidates[{i}]", c) for i, c in enumerate(result.get("candidates", []))]
    for name, it in items:
        if it is not None:
            errs += pose_errors(it.get("pose", {}), f"{name}.pose")
    tops = [c["top_z"] for c in result.get("candidates", [])]
    if tops != sorted(tops, reverse=True):
        errs.append("candidates 는 top_z 내림차순")
    return errs
