"""inspect_region 실제 구현의 핵심 (ROS 비의존): YOLO 검출 + 뎁스 덩어리 → result_json (형식 원본: docs/runner.md 7.1).

  입력: 검출 목록(class·conf·box 픽셀), 정렬 뎁스(m), 카메라 내부 파라미터, T_drawer_cam, params(vision_params.yaml), 온톨로지 items.
  규칙 (docs/vision.md V2):
    position = YOLO 박스 중심 픽셀을 서랍 좌표 z = top_z/2 평면에 투영한 x·y, position.z = 0
    top_z    = 박스 안 뎁스 덩어리의 높이 (서랍 바닥 기준). 검출에 mask(분할 모델)가 있으면 마스크 안 뎁스만 (#109)
    yaw      = 덩어리 긴 변 방향. 대칭 물체(pose_rules.is_symmetric)는 0 + yaw_valid true,
               덩어리가 비정상이면 0 + yaw_valid false
  서랍 영역 ROI: 박스 중심 광선이 서랍 바닥(z=0)과 만나는 점이 서랍 안쪽 + region.detect_roi_margin_m 밖이면 뎁스 계산 전에 뺀다.
    서랍 밖 책상 위 물체·케이블·그리퍼 손끝을 잘못 검출해도 뎁스 실패로 호출 전체가 DEPTH_INVALID 가 되지 않게 한다 [실측 PC2 10/07].
    TF 로 계산하므로 촬영 자세가 바뀌어도 따라간다. 값이 없으면(옛 설정) 끈다.
  footprint 가 서랍 안쪽(interior_m, 오차 여유 region.edge_tolerance_m)을 벗어난 검출은 결과에서 뺀다(서랍 밖 파지 방지).
  분할 모델(모든 검출에 mask)이면 뎁스 전에 같은 클래스 중복 검출 중 신뢰도 높은 쪽만 남긴다(core/dedup.py, dedup.min_overlap, 합집합 안 함). 박스 모델은 그대로.
  뎁스를 쓸 수 없는 검출이 하나라도 있으면 policy.on_invalid_candidate 에 따라 전체 DEPTH_INVALID (기본 fail, 안전 우선).
  지역(region)은 서랍 칸마다 places.yaml 의 tf·interior_m 으로 계산하고 pose.frame = 요청 지역 (#155, 아래 칸 = drawer_bottom).
  가림 필드(P2, #109 4단계, core/occlusion.py): 분할 모델이면 결과의 모든 물체에 occluded_by·visible_area_m2(모르면 null),
  박스 모델이면 결과 전체에 두 필드를 내지 않는다(#185). 판정에는 결과에서 빠진 검출(footprint 밖 등)도 '덮은 물체' 후보로 넣는다.
"""
from __future__ import annotations

import json
import math

from .dedup import merge_duplicates
from .depth_blob import analyze_box
from .geometry import Intrinsics, make_T, ray_plane_xy
from .occlusion import occlusion_fields
from .pose_rules import is_symmetric, result_errors, round_yaw

SUPPORTED_REGIONS = ("drawer_top", "drawer_bottom")


def region_frames(places: dict) -> dict:
    """places.yaml → {지역: {"tf", "interior_m"(깊이·폭), "T_base_drawer"}}. tf 가 아직 측정 전(null)인 지역은 빠진다(요청하면 UNKNOWN_REGION)."""
    out = {}
    for name in SUPPORTED_REGIONS:
        tf = (places.get(name) or {}).get("tf")
        if tf and tf.get("translation_m") is not None and tf.get("quaternion_xyzw") is not None:
            out[name] = {"tf": tf, "interior_m": places[name]["interior_m"][:2],
                         "T_base_drawer": make_T(tf["translation_m"], tf["quaternion_xyzw"])}
    return out


def footprint_inside(x, y, yaw, yaw_known, size, interior, tol):
    """물체 윗면 footprint 가 서랍 안쪽(0~interior[0], 0~interior[1])에 들어가는가. tol 은 측정 오차 여유(m).
    yaw 를 아는 직사각형은 회전한 직사각형의 축 정렬 범위, 모르면(대칭·덩어리 비정상) 외접원 반지름으로 보수적으로 본다."""
    if yaw_known:
        c, s = abs(math.cos(yaw)), abs(math.sin(yaw))
        hx, hy = (size[0] * c + size[1] * s) / 2, (size[0] * s + size[1] * c) / 2
    else:
        hx = hy = math.hypot(size[0], size[1]) / 2
    return (x - hx >= -tol and x + hx <= interior[0] + tol) and (y - hy >= -tol and y + hy <= interior[1] + tol)


def inspect_scene(detections, depth_m, K: Intrinsics, T_drawer_cam, params: dict, items: dict,
                  region: str, search_target: str = "", interior_m=None, debug: list | None = None,
                  seg_model: bool | None = None) -> tuple[bool, str, str]:
    """(success, error_code, result_json). 미발견은 success=True + target_found=False.
    debug 에 리스트를 넘기면 검출마다 판단 근거(dict)를 붙인다 (로그·덤프용, 결과에는 영향 없음).
    seg_model = 분할 모델인가(가림 필드를 낼지). None 이면 검출 중 하나라도 mask 가 있으면 분할 모델로 본다."""
    note = (lambda det, **kv: debug.append({"class": det["class"], "conf": round(float(det["conf"]), 3),
                                            "box": [round(float(b), 1) for b in det["box"]], **kv})) if debug is not None else (lambda det, **kv: None)
    if region not in SUPPORTED_REGIONS:
        return False, "UNKNOWN_REGION", ""
    if seg_model is None:
        seg_model = any(d.get("mask") is not None for d in detections)
    blob_params, policy = params["depth_blob"], params.get("policy", {})
    fail_on_invalid = policy.get("on_invalid_candidate", "fail") == "fail"
    roi_margin = params.get("region", {}).get("detect_roi_margin_m")
    kept = []
    for det in sorted(detections, key=lambda d: -d["conf"]):
        if det["conf"] < params["detector"]["conf_min"] or det["class"] not in items:
            note(det, skip="conf_min 미만 또는 온톨로지에 없는 클래스")
            continue
        if roi_margin is not None and interior_m is not None:
            u0, v0 = (det["box"][0] + det["box"][2]) / 2, (det["box"][1] + det["box"][3]) / 2
            xy0 = ray_plane_xy(u0, v0, K, T_drawer_cam, 0.0)
            if xy0 is None or not (-roi_margin <= xy0[0] <= interior_m[0] + roi_margin and -roi_margin <= xy0[1] <= interior_m[1] + roi_margin):
                note(det, skip="서랍 영역 밖 (뎁스 전 제외)", xy_floor=None if xy0 is None else [round(xy0[0], 4), round(xy0[1], 4)])
                continue
        kept.append(det)
    min_overlap = params.get("dedup", {}).get("min_overlap")
    if min_overlap is not None and kept and all(d.get("mask") is not None for d in kept):
        kept, dropped = merge_duplicates(kept, min_overlap)
        for d in dropped:
            note(d, skip=f"중복 검출 → 같은 클래스 conf {d['merged_into_conf']:.3f} 만 남기고 버림")
    found, in_result = [], {}
    for det in kept:
        merged = {"merged_from": det["merged_from"]} if det.get("merged_from") else {}
        size = items[det["class"]]["size_m"]
        mask = det.get("mask")
        blob = analyze_box(depth_m, det["box"], K, T_drawer_cam, blob_params, nominal_long_m=size[0], mask=mask)
        src = "mask" if mask is not None else "box"
        if not blob.depth_ok or blob.top_z is None:
            note(det, skip=f"뎁스 덩어리 실패: {blob.reason}", depth_src=src, n_valid=blob.n_valid, invalid_ratio=round(blob.invalid_ratio, 3), **merged)
            if fail_on_invalid:
                return False, "DEPTH_INVALID", ""
            continue
        top_z = round(blob.top_z, 4)
        u, v = (det["box"][0] + det["box"][2]) / 2, (det["box"][1] + det["box"][3]) / 2
        xy = ray_plane_xy(u, v, K, T_drawer_cam, top_z / 2)
        if xy is None:
            note(det, skip="광선이 top_z/2 평면과 만나지 않음", top_z=top_z)
            if fail_on_invalid:
                return False, "DEPTH_INVALID", ""
            continue
        if is_symmetric(size):
            yaw, valid, yaw_known = 0.0, True, False                 # 대칭 물체의 yaw 0 은 약속값이라 footprint 는 외접원으로 본다
        else:
            yaw, valid = (round_yaw(blob.yaw), True) if blob.yaw_ok else (0.0, False)
            yaw_known = valid
        info = dict(**merged, depth_src=src, top_z=top_z, xy=[round(xy[0], 4), round(xy[1], 4)], yaw=yaw, yaw_valid=valid, yaw_reason=blob.reason,
                    n_blob=blob.n_blob, blob_long_mm=round(blob.blob_long_m * 1000, 1), blob_short_mm=round(blob.blob_short_m * 1000, 1))
        if interior_m is not None and not footprint_inside(xy[0], xy[1], yaw, yaw_known, size, interior_m,
                                                           params.get("region", {}).get("edge_tolerance_m", 0.01)):
            note(det, skip="footprint 가 서랍 안쪽 밖", **info)
            continue
        in_result[id(det)] = len(found)                                    # 가림 판정에서 결과 id 를 찾기 위해 (입력 dict 는 안 바꿈)
        note(det, **info)                                                  # 서랍 밖(시야에 잡힌 다른 물체·TF 오차)은 결과에 넣지 않는다
        found.append({"class": det["class"], "pose": {"frame": region, "position": [round(xy[0], 4), round(xy[1], 4), 0.0],
                                                      "yaw": yaw, "yaw_valid": valid}, "top_z": top_z})
    order = sorted(range(len(found)), key=lambda i: found[i]["top_z"], reverse=True)
    n = {}
    for i in order:
        it = found[i]
        n[it["class"]] = n.get(it["class"], 0) + 1
        it["id"] = f"{it['class']}#{n[it['class']]}"
        it["pose"] = {k: it["pose"][k] for k in ("frame", "position", "yaw", "yaw_valid")}
    if seg_model:
        rels = [] if debug is not None else None
        occ = occlusion_fields(kept, [found[in_result[id(d)]]["id"] if id(d) in in_result else None for d in kept],
                               depth_m, K, T_drawer_cam, params["occlusion"], blob_params["min_depth_m"], blob_params["max_depth_m"], rels)
        for it in found:
            it["occluded_by"], it["visible_area_m2"] = occ[it["id"]]
        if debug is not None:
            debug += [{"occlusion": r} for r in rels]
    found = [found[i] for i in order]
    target = next((i for i in found if search_target and i["class"] == search_target), None)
    result = {"target_found": target is not None, "target": _ordered(target),
              "candidates": [_ordered(i) for i in found if i is not target], "visible_count": len(found)}
    if result_errors(result):
        return False, "RESULT_INVALID", ""
    return True, "", json.dumps(result, ensure_ascii=False)


def _ordered(it):
    if it is None:
        return None
    out = {"id": it["id"], "class": it["class"], "pose": it["pose"], "top_z": it["top_z"]}
    out.update({k: it[k] for k in ("occluded_by", "visible_area_m2") if k in it})
    return out
