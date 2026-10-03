"""inspect_region stub 로직 (ROS 비의존). 손으로 잰 좌표를 result_json 형식 그대로 만든다.

실제 구현(YOLO + 뎁스)으로 바뀌어도 반환 형식은 같다: docs/runner.md 7.1.
error_code: UNKNOWN_REGION(stub 에서 쓰는 유일한 코드). 카메라 타임아웃·TF 없음·뎁스 결손은 실제 구현에서 추가 [팀 확정 필요].
"""
import json
from collections import Counter


def inspect(config: dict, region: str, search_target: str = "") -> tuple[bool, str, str]:
    """(success, error_code, result_json) 반환. 미발견은 success=True + target_found=False."""
    regions = config.get("regions", {})
    if region not in regions:
        return False, "UNKNOWN_REGION", ""
    seen = Counter()
    items = []
    for o in regions[region].get("objects", []):
        seen[o["class"]] += 1
        items.append({
            "id": f"{o['class']}#{seen[o['class']]}",
            "class": o["class"],
            "pose": {"frame": region, "position": list(o["position"]), "yaw": o.get("yaw", 0.0)},
            "top_z": o["top_z"],
        })
    items.sort(key=lambda i: i["top_z"], reverse=True)
    target = next((i for i in items if search_target and i["class"] == search_target), None)
    candidates = [i for i in items if i is not target]
    result = {"target_found": target is not None, "target": target,
              "candidates": candidates, "visible_count": len(items)}
    return True, "", json.dumps(result, ensure_ascii=False)
