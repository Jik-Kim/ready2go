"""inspect_region 결과의 pose 규칙 (ROS 비의존). 정의 원본: docs/runner.md 7.1, 서랍 좌표계는 config/places.yaml 첫 부분.

- position = YOLO 박스 중심의 서랍 좌표계 x·y [m], position.z = 0 (높이는 top_z 에만 둔다)
- yaw = 물체 긴 변 방향(서랍 x축 기준 rad), 범위 (-pi/2, pi/2]. 긴 변은 180° 돌려도 같은 직선이라 한 범위로 고정한다.
  위에서 본 모양이 정사각형이거나 둥근 대칭 물체는 0 으로 고정한다 (판정: is_symmetric, 기준값은 이 파일의 SYMMETRY_RATIO 하나뿐).
- yaw_valid(bool) = yaw 를 믿어도 되는가. 대칭 물체와 정상 산출은 True, 덩어리 비정상(뎁스 결손·너무 얇음 등)은 False 이며 이때 yaw 는 0 자리표시.
  소비자(pick_object·nudge_object)가 진짜 0° 와 '모름'을 구분하려는 것이다 (B 요청, 사용자 승인 10/04).
"""
import math

EPS = 1e-9
SYMMETRY_RATIO = 1.2   # 근거: PM 제안(PR #46 코멘트), 사용자 승인 10/04. 확정 11종 중 masking_tape(1.0)만 대칭, 다음은 cover_plate 1.33·airpods_case 1.34


def normalize_yaw(yaw: float) -> float:
    """임의의 각도(rad)를 같은 직선을 나타내는 (-pi/2, pi/2] 값으로. -pi/2 는 +pi/2 로 쓴다."""
    return yaw - math.pi * math.ceil(yaw / math.pi - 0.5)


def round_yaw(yaw: float, ndigits: int = 4) -> float:
    """결과 JSON 용 반올림. ±90° 근처는 반올림하면 범위를 벗어나므로(1.5708 > pi/2, -1.5708 < -pi/2) 같은 직선인 pi/2 로 쓴다."""
    y = round(yaw, ndigits)
    return math.pi / 2 if (y > math.pi / 2 or y <= -math.pi / 2) else y


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
    valid = pose.get("yaw_valid")
    if not isinstance(valid, bool):
        errs.append(f"{where}.yaw_valid 는 bool 필수")
    elif not valid and isinstance(yaw, (int, float)) and abs(yaw) > EPS:
        errs.append(f"{where}.yaw_valid 가 false 이면 yaw 는 0 이어야 함 — 값 {yaw}")
    return errs


OCCLUSION_KEYS = ("occluded_by", "visible_area_m2")


def occlusion_errors(it: dict, ids: set, where: str) -> list[str]:
    """가림 필드(P2, #169·runner.md 7.1): null 이면 '모름'. occluded_by = 같은 결과 안의 다른 물체 id 목록, visible_area_m2 >= 0.
    필드가 있는지(분할 모델은 모든 물체, 박스 모델은 결과 전체에 없음)는 result_errors 가 본다."""
    errs = []
    occ = it.get("occluded_by")
    if occ is not None:
        if not (isinstance(occ, list) and all(isinstance(i, str) for i in occ)):
            errs.append(f"{where}.occluded_by 는 id 문자열 목록 또는 null — 값 {occ!r}")
        else:
            errs += [f"{where}.occluded_by 에 결과에 없는 id {i!r}" for i in occ if i not in ids]
            if it.get("id") in occ:
                errs.append(f"{where}.occluded_by 에 자기 자신 {it.get('id')!r}")
    area = it.get("visible_area_m2")
    if area is not None and (isinstance(area, bool) or not isinstance(area, (int, float)) or not math.isfinite(area) or area < 0):
        errs.append(f"{where}.visible_area_m2 는 0 이상 유한한 숫자 또는 null — 값 {area!r}")
    return errs


def occlusion_cycle(items: list[dict]) -> list[str] | None:
    """occluded_by 관계(덮은 물체 → 덮인 물체)의 순환 하나를 id 목록으로, 없으면 None. 형식이 틀린 항목은 건너뛴다(형식 오류는 따로 보고)."""
    edges = {}
    for it in items:
        occ = it.get("occluded_by")
        if isinstance(occ, list):
            for over in occ:
                if isinstance(over, str):
                    edges.setdefault(over, []).append(it.get("id"))
    state, stack = {}, []

    def visit(n):
        state[n] = 1; stack.append(n)
        for m in edges.get(n, []):
            if state.get(m) == 1:
                return stack[stack.index(m):] + [m]
            if state.get(m) is None and (c := visit(m)):
                return c
        state[n] = 2; stack.pop()
        return None
    for n in list(edges):
        if state.get(n) is None and (c := visit(n)):
            return c
    return None


def result_errors(result: dict) -> list[str]:
    """inspect_region result_json 의 target·candidates pose·가림 필드 검사. 빈 리스트면 규칙을 지킨 것."""
    errs = []
    items = [("target", result.get("target"))] + [(f"candidates[{i}]", c) for i, c in enumerate(result.get("candidates", []))]
    id_list = [it.get("id") for _, it in items if it is not None]
    ids = set(id_list)
    errs += [f"id {i!r} 가 결과 안에 두 번 이상 (id 는 유일해야 occluded_by 가 한 물체를 가리킴)" for i in sorted({i for i in id_list if id_list.count(i) > 1}, key=str)]
    for name, it in items:
        if it is not None:
            errs += pose_errors(it.get("pose", {}), f"{name}.pose")
            errs += occlusion_errors(it, ids, name)
    present = [(name, [k for k in OCCLUSION_KEYS if k in it]) for name, it in items if it is not None]
    if any(keys for _, keys in present):            # 분할 모델: 모든 물체에 두 필드, 박스 모델: 결과 전체에 없음 (#120 C 동의)
        errs += [f"{name} 에 가림 필드 {', '.join(k for k in OCCLUSION_KEYS if k not in keys)} 없음 — 한 결과는 모든 물체에 두 필드(분할 모델) 또는 전부 없음(박스 모델)"
                 for name, keys in present if len(keys) < len(OCCLUSION_KEYS)]
    cycle = occlusion_cycle([it for _, it in items if it is not None])
    if cycle:
        errs.append(f"occluded_by 관계가 순환함 (맨 위 물체를 정할 수 없음): {' → '.join(cycle)}")
    tops = [c["top_z"] for c in result.get("candidates", [])]
    if tops != sorted(tops, reverse=True):
        errs.append("candidates 는 top_z 내림차순")
    return errs
