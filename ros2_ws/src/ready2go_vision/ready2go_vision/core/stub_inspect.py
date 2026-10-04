"""inspect_region stub 로직 (ROS 비의존). 손으로 잰 좌표를 result_json 형식 그대로 만든다.

실제 구현(YOLO + 뎁스)으로 바뀌어도 반환 형식은 같다: docs/runner.md 7.1.
error_code 목록은 docs/runner.md 의 "inspect_region 에러 코드" 표가 원본이다. 이 stub 은 UNKNOWN_REGION, STUB_NOT_READY, CONFIG_INVALID 만 쓴다. 카메라 타임아웃·TF 없음·뎁스 결손은 실제 구현에서 추가 [팀 확정 필요].
"""
import json
from collections import Counter

from .pose_rules import normalize_yaw


def inspect(config: dict, region: str, search_target: str = "") -> tuple[bool, str, str]:
    """(success, error_code, result_json) 반환. 미발견은 success=True + target_found=False."""
    if config.get("ready") is not True:
        return False, "STUB_NOT_READY", ""
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
