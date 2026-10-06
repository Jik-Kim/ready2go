"""inspect_region 실제 구현의 핵심 (ROS 비의존): YOLO 검출 + 뎁스 덩어리 → result_json (형식 원본: docs/runner.md 7.1).

  입력: 검출 목록(class·conf·box 픽셀), 정렬 뎁스(m), 카메라 내부 파라미터, T_drawer_cam, params(vision_params.yaml), 온톨로지 items.
  규칙 (docs/vision.md V2):
    position = YOLO 박스 중심 픽셀을 서랍 좌표 z = top_z/2 평면에 투영한 x·y, position.z = 0
    top_z    = 박스 안 뎁스 덩어리의 높이 (서랍 바닥 기준)
    yaw      = 덩어리 긴 변 방향. 대칭 물체(pose_rules.is_symmetric)는 0 + yaw_valid true,
               덩어리가 비정상이면 0 + yaw_valid false
  뎁스를 쓸 수 없는 검출이 하나라도 있으면 policy.on_invalid_candidate 에 따라 전체 DEPTH_INVALID (기본 fail, 안전 우선).
"""
from __future__ import annotations

import json

from .depth_blob import analyze_box
from .geometry import Intrinsics, ray_plane_xy
from .pose_rules import is_symmetric, result_errors

SUPPORTED_REGIONS = ("drawer_top",)


def inspect_scene(detections, depth_m, K: Intrinsics, T_drawer_cam, params: dict, items: dict,
                  region: str, search_target: str = "") -> tuple[bool, str, str]:
    """(success, error_code, result_json). 미발견은 success=True + target_found=False."""
    if region not in SUPPORTED_REGIONS:
        return False, "UNKNOWN_REGION", ""
    blob_params, policy = params["depth_blob"], params.get("policy", {})
    fail_on_invalid = policy.get("on_invalid_candidate", "fail") == "fail"
    found = []
    for det in sorted(detections, key=lambda d: -d["conf"]):
        if det["conf"] < params["detector"]["conf_min"] or det["class"] not in items:
            continue
        size = items[det["class"]]["size_m"]
        blob = analyze_box(depth_m, det["box"], K, T_drawer_cam, blob_params, nominal_long_m=size[0])
        if not blob.depth_ok or blob.top_z is None:
            if fail_on_invalid:
                return False, "DEPTH_INVALID", ""
            continue
        top_z = round(blob.top_z, 4)
        u, v = (det["box"][0] + det["box"][2]) / 2, (det["box"][1] + det["box"][3]) / 2
        xy = ray_plane_xy(u, v, K, T_drawer_cam, top_z / 2)
        if xy is None:
            if fail_on_invalid:
                return False, "DEPTH_INVALID", ""
            continue
        if is_symmetric(size):
            yaw, valid = 0.0, True
        else:
            yaw, valid = (round(blob.yaw, 4), True) if blob.yaw_ok else (0.0, False)
        found.append({"class": det["class"], "pose": {"frame": region, "position": [round(xy[0], 4), round(xy[1], 4), 0.0],
                                                      "yaw": yaw, "yaw_valid": valid}, "top_z": top_z})
    found.sort(key=lambda i: i["top_z"], reverse=True)
    n = {}
    for it in found:
        n[it["class"]] = n.get(it["class"], 0) + 1
        it["id"] = f"{it['class']}#{n[it['class']]}"
        it["pose"] = {k: it["pose"][k] for k in ("frame", "position", "yaw", "yaw_valid")}
    target = next((i for i in found if search_target and i["class"] == search_target), None)
    result = {"target_found": target is not None, "target": _ordered(target),
              "candidates": [_ordered(i) for i in found if i is not target], "visible_count": len(found)}
    if result_errors(result):
        return False, "RESULT_INVALID", ""
    return True, "", json.dumps(result, ensure_ascii=False)


def _ordered(it):
    return None if it is None else {"id": it["id"], "class": it["class"], "pose": it["pose"], "top_z": it["top_z"]}
