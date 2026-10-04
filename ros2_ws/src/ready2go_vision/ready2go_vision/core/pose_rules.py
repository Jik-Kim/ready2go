"""inspect_region 결과의 pose 규칙 (ROS 비의존). 정의 원본: docs/runner.md 7.1, 서랍 좌표계는 config/places.yaml 첫 부분.

- position = YOLO 박스 중심의 서랍 좌표계 x·y [m], position.z = 0 (높이는 top_z 에만 둔다)
- yaw = 물체 긴 변 방향(서랍 x축 기준 rad), 범위 (-pi/2, pi/2]. 긴 변은 180° 돌려도 같은 직선이라 한 범위로 고정한다.
  원통·정사각형처럼 긴 변이 없는 대칭 물체는 0 으로 고정한다 (판정: is_symmetric).
"""
import math

EPS = 1e-9
SYMMETRY_RATIO = 1.2   # 근거: PM 제안(PR #46 코멘트), 사용자 승인 10/04. 확정 11종 중 masking_tape(1.0)만 대칭, 다음은 cover_plate 1.33·airpods_case 1.34


def normalize_yaw(yaw: float) -> float:
    """임의의 각도(rad)를 같은 직선을 나타내는 (-pi/2, pi/2] 값으로. -pi/2 는 +pi/2 로 쓴다."""
    return yaw - math.pi * math.ceil(yaw / math.pi - 0.5)


def is_symmetric(size_m, ratio: float = SYMMETRY_RATIO) -> bool:
    """온톨로지 명목 size_m 의 가로·세로 두 값(max/min)이 ratio 미만이면 대칭 물체 → yaw 0 고정.
    측정한 덩어리가 아니라 명목 치수로 계산해 재현성을 확보한다. 높이(size_m[2])는 쓰지 않고, 두 값의 순서와 무관하다."""
    a, b = float(size_m[0]), float(size_m[1])
    lo, hi = min(a, b), max(a, b)
    if lo <= 0:
        raise ValueError(f"size_m 가로·세로는 양수여야 함: {size_m}")
    return hi / lo < ratio


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
