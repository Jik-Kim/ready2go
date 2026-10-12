"""가림 판정 (#109 4단계, P2): 분할 마스크 + 뎁스 → 물체마다 occluded_by·visible_area_m2 (형식 원본: docs/runner.md 7.1).

  visible_area_m2 = 마스크 픽셀마다 그 픽셀 뎁스 d 로 (d/fx)·(d/fy) 를 더한 값. 뎁스 결손 픽셀은 마스크 뎁스 중앙값.
                    마스크 안 유효 뎁스가 없으면 null. 물체 전체 넓이나 가림 비율이 아니다.
  "A 가 B 위에 얹힘" (A 가 B 의 occluded_by 에 들어감):
    ① 두 마스크가 맞닿음: 서로를 contact_dilate_px 만큼 넓힌 띠와 겹친 픽셀이 양쪽 다 min_contact_px 이상
    ② 맞닿은 띠에서 A 높이(서랍 z) 중앙값 − B 높이 중앙값 >= min_height_diff_m (전역 top_z 순서가 아니라 경계 국소 높이)
    ③ B 가 덜 보임(visible_area_m2 / 클래스 기준 면적 < visible_ratio_max) 또는 A 가 B 를 조각으로 나눔
       (B 마스크에서 split_min_px 이상 조각 중 A 띠에 닿는 것이 2개 이상)
  모름(null): 마스크 없음 / 위 물체가 맞닿았는데 높이를 못 잼 / 위 물체가 맞닿았는데 기준 면적이 없어 덜 보임을 못 봄 /
             덜 보이거나 조각났는데 덮은 물체를 못 찾음 / 덮은 물체가 결과에서 빠짐 / 관계가 순환함(걸린 물체 모두).
  [] = 다 보이고 위에 얹힌 물체 없음. 임계값·기준 면적은 config/vision_params.yaml occlusion (전부 [팀 확정 필요]).
  한계(docs/vision.md 9장): 얇은 덮개 밑(높이 차 작음), 끝만 덮임(덜 보이지도 나뉘지도 않음), 덮인 물체 미검출, 가장자리·화면 끝에 걸려 덜 보이는 물체에 높은 물체가 맞닿으면 헛관계 가능.
"""
from __future__ import annotations

import numpy as np

from .geometry import Intrinsics
from .pose_rules import occlusion_cycle


def _cv2():
    import cv2
    return cv2


def drawer_z_map(depth_m: np.ndarray, K: Intrinsics, T_drawer_cam: np.ndarray, min_depth: float, max_depth: float) -> np.ndarray:
    """픽셀마다 서랍 좌표 z(m). 뎁스 결손·범위 밖은 nan."""
    h, w = depth_m.shape
    vs, us = np.mgrid[0:h, 0:w]
    d = depth_m.astype(float)
    ok = np.isfinite(d) & (d > min_depth) & (d < max_depth)
    R, t = T_drawer_cam[2, :3], T_drawer_cam[2, 3]
    z = R[0] * (us - K.cx) / K.fx * d + R[1] * (vs - K.cy) / K.fy * d + R[2] * d + t
    return np.where(ok, z, np.nan)


def visible_area_m2(mask: np.ndarray, depth_m: np.ndarray, K: Intrinsics, min_depth: float, max_depth: float):
    d = depth_m[mask].astype(float)
    ok = np.isfinite(d) & (d > min_depth) & (d < max_depth)
    if not ok.any():
        return None
    d = np.where(ok, d, np.median(d[ok]))
    return float(((d / K.fx) * (d / K.fy)).sum())


def _pieces(mask: np.ndarray, min_px: int, touching: np.ndarray | None = None) -> int:
    cv2 = _cv2()
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return sum(1 for L in range(1, n) if st[L, cv2.CC_STAT_AREA] >= min_px and (touching is None or (touching & (lab == L)).any()))


def occlusion_fields(dets: list[dict], ids: list, depth_m: np.ndarray, K: Intrinsics, T_drawer_cam: np.ndarray,
                     params: dict, min_depth: float, max_depth: float, relations: list | None = None) -> dict:
    """dets = 판정에 쓸 검출(결과에서 빠진 것도 포함 — '덮은 물체가 결과에서 빠짐'을 알기 위해), ids[i] = 결과 id 또는 None(결과에 없음).
    → {결과 id: (occluded_by 목록 또는 None, visible_area_m2 또는 None)}. relations 에 리스트를 주면 판정 근거를 붙인다(로그용)."""
    cv2 = _cv2()
    p = params
    ref = p.get("ref_visible_area_m2", {})
    dil = int(p["contact_dilate_px"])
    kern = np.ones((2 * dil + 1, 2 * dil + 1), np.uint8)
    masks = [d.get("mask") for d in dets]
    Z = drawer_z_map(depth_m, K, T_drawer_cam, min_depth, max_depth) if any(m is not None for m in masks) else None
    grown = [None if m is None else cv2.dilate(m.astype(np.uint8), kern) > 0 for m in masks]
    area = [None if m is None else visible_area_m2(m, depth_m, K, min_depth, max_depth) for m in masks]
    out = {}
    for j, b in enumerate(dets):
        if ids[j] is None:
            continue
        mb = masks[j]
        if mb is None:
            out[ids[j]] = (None, None)
            continue
        r = ref.get(b["class"])
        ratio = None if (r is None or area[j] is None) else area[j] / r
        less = ratio is not None and ratio < p["visible_ratio_max"]
        split = _pieces(mb, p["split_min_px"]) >= 2
        covers, unknown, why = [], [], []
        for i, a in enumerate(dets):
            if i == j or masks[i] is None:
                continue
            band_a, band_b = masks[i] & grown[j], mb & grown[i]
            if band_a.sum() < p["min_contact_px"] or band_b.sum() < p["min_contact_px"]:
                continue
            za, zb = Z[band_a], Z[band_b]
            za, zb = za[np.isfinite(za)], zb[np.isfinite(zb)]
            rel = {"over": ids[i] or f"{a['class']}(결과 밖)", "under": ids[j]}
            if not len(za) or not len(zb):
                unknown.append("맞닿은 띠 높이 못 잼"); rel["judge"] = "모름: 높이"
                relations is not None and relations.append(rel)
                continue
            dz = float(np.median(za) - np.median(zb))
            rel["dz_mm"] = round(dz * 1000, 1)
            if dz < p["min_height_diff_m"]:
                continue                                       # 같은 높이이거나 B 가 위 — 이 쌍에서 B 는 안 덮임
            cut = _pieces(mb, p["split_min_px"], grown[i]) >= 2
            rel.update(visible_ratio=None if ratio is None else round(ratio, 2), split=cut)
            if ratio is None and not cut:
                unknown.append("기준 면적 없음"); rel["judge"] = "모름: 기준 면적"
            elif less or cut:
                if ids[i] is None:
                    unknown.append("덮은 물체가 결과에서 빠짐"); rel["judge"] = "모름: 덮은 물체 결과 밖"
                else:
                    covers.append(ids[i]); rel["judge"] = "얹힘"
            else:
                rel["judge"] = "맞닿음(다 보임)"
            relations is not None and relations.append(rel)
        if not covers and not unknown and (less or (split and ratio is None)):   # 다 보이는데(기준 넓이 이상) 조각만 났으면 마스크 잡조각 — 안 가려짐
            unknown.append("덜 보이거나 조각났는데 덮은 물체 없음")
            relations is not None and relations.append({"under": ids[j], "visible_ratio": None if ratio is None else round(ratio, 2),
                                                        "split": split, "judge": "모름: 덮은 물체 없음"})
        a_ = None if area[j] is None else round(area[j], 6)
        out[ids[j]] = (None if unknown else sorted(covers), a_)
    while True:                                                # 순환이면 걸린 물체를 모두 '모름'으로 (runner.md 7.1)
        cyc = occlusion_cycle([{"id": k, "occluded_by": v[0]} for k, v in out.items()])
        if not cyc:
            break
        for k in set(cyc):
            out[k] = (None, out[k][1])
        relations is not None and relations.append({"cycle": cyc, "judge": "모름: 순환"})
    return out
