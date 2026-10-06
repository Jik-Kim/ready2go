"""inspect_region stub 로직 (ROS 비의존). 손으로 잰 좌표를 result_json 형식 그대로 만든다.

실제 구현(YOLO + 뎁스)으로 바뀌어도 반환 형식은 같다: docs/runner.md 7.1.
error_code 목록은 docs/runner.md 의 "inspect_region 에러 코드" 표가 원본이다. 이 stub 은 UNKNOWN_REGION, STUB_NOT_READY, CONFIG_INVALID 만 쓴다.
노드는 실측 규칙(validate_config)을 interiors(places.yaml 의 서랍 interior_m)와 함께 적용한다 — 손으로 옮긴 값의 오류가 서랍 밖 이동이 되지 않게(PR #81 D 검수). 카메라 타임아웃·TF 없음·뎁스 결손은 실제 구현에서 추가 [팀 확정 필요].
"""
import json
import math
from collections import Counter

from .pose_rules import normalize_yaw


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_config(config: dict, interiors: dict) -> list[str]:
    """ready: true 인 설정의 실측 규칙 위반 목록 (빈 리스트면 통과).
    interiors = {region: [깊이, 폭]} (config/places.yaml 의 interior_m). 목록에 있는 region 은 위치가 그 안이어야 한다."""
    errs, n = [], 0
    for region, body in (config.get("regions") or {}).items():
        for i, o in enumerate((body or {}).get("objects") or []):
            n += 1
            w = f"{region}.objects[{i}]"
            if not isinstance(o.get("class"), str) or not o["class"]:
                errs.append(f"{w}.class 없음")
            pos = o.get("position")
            if not (isinstance(pos, list) and len(pos) == 3 and all(_finite(v) for v in pos)):
                errs.append(f"{w}.position 은 유한한 숫자 3개")
            else:
                if pos[2] != 0:
                    errs.append(f"{w}.position.z 는 0 (높이는 top_z)")
                if region in interiors:
                    d, wd = interiors[region][0], interiors[region][1]
                    if not (0 <= pos[0] <= d and 0 <= pos[1] <= wd):
                        errs.append(f"{w}.position {pos[:2]} 가 {region} 내부 [0~{d}, 0~{wd}] 밖")
            if not isinstance(o.get("yaw_valid"), bool):
                errs.append(f"{w}.yaw_valid(bool) 를 명시해야 함")
            if not _finite(o.get("yaw", 0.0)):
                errs.append(f"{w}.yaw 는 유한한 숫자")
            if not (_finite(o.get("top_z")) and o["top_z"] > 0):
                errs.append(f"{w}.top_z 는 양수")
    if n == 0:
        errs.append("ready: true 인데 물체가 하나도 없음")
    return errs


def inspect(config: dict, region: str, search_target: str = "", interiors: dict | None = None) -> tuple[bool, str, str]:
    """(success, error_code, result_json) 반환. 미발견은 success=True + target_found=False.
    interiors 를 주면(노드) 실측 규칙 위반 시 CONFIG_INVALID 로 막는다."""
    if config.get("ready") is not True:
        return False, "STUB_NOT_READY", ""
    if interiors is not None and validate_config(config, interiors):
        return False, "CONFIG_INVALID", ""
    regions = config.get("regions", {})
    if region not in regions:
        return False, "UNKNOWN_REGION", ""
    seen = Counter()
    items = []
    for o in regions[region].get("objects", []):
        seen[o["class"]] += 1
        valid = o.get("yaw_valid", True)                      # 스텁은 기본 true. false 예시를 시험하려면 설정에서 지정 (이때 yaw 는 0)
        if not isinstance(valid, bool):                       # "false"(문자열)·0 같은 값이 참/거짓으로 잘못 읽히지 않게 설정 오류로 막는다
            return False, "CONFIG_INVALID", ""
        items.append({
            "id": f"{o['class']}#{seen[o['class']]}",
            "class": o["class"],
            "pose": {"frame": region, "position": list(o["position"]), "yaw": normalize_yaw(o.get("yaw", 0.0)) if valid else 0.0, "yaw_valid": valid},
            "top_z": o["top_z"],
        })
    items.sort(key=lambda i: i["top_z"], reverse=True)
    target = next((i for i in items if search_target and i["class"] == search_target), None)
    candidates = [i for i in items if i is not target]
    result = {"target_found": target is not None, "target": target,
              "candidates": candidates, "visible_count": len(items)}
    return True, "", json.dumps(result, ensure_ascii=False)
