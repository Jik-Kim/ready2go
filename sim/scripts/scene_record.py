"""씬(USD) 생성 설정 기록과 궤적 설정 대조 (#215). Isaac Sim 에 의존하지 않는다 — 단위 시험·로컬 CI 에서 돈다.

build_scene.py 가 만든 USD 루트 레이어 customLayerData[RECORD_KEY] 에 생성 설정(JSON 문자열)을 남기고,
play_motion_trace.py 가 **실제로 연 USD** 의 그 기록을 궤적 설정(trace config, trace_skill_flow.places_record)과 대조한다.
저장소의 현재 config/places.yaml 은 대조에 쓰지 않는다 — YAML·궤적만 갱신하고 USD 를 다시 만들지 않았거나 다른 --scene 을 열어도 잡히게.
"""
from __future__ import annotations

import hashlib
import json
import math

RECORD_KEY = "ready2go_build_json"
SCENE_KEYS = ("drawer_top", "drawer_bottom", "handover_zone")
TOL_M = 1e-4                # tf 평행이동·쿼터니언 성분 차이 허용 (0.1 mm)


def build_record(places: dict, places_bytes: bytes, code_sha: str, places_path: str = "") -> dict:
    """씬을 만든 설정. tf 는 그대로, 트레이는 floor_m 도 (형상이 그것으로 정해짐, #220)."""
    rec = {"version": 1, "code_sha": code_sha, "places_path": places_path,
           "places_sha256": hashlib.sha256(places_bytes).hexdigest(),
           "tf": {k: (places.get(k) or {}).get("tf") for k in SCENE_KEYS},
           "handover_floor_m": (places.get("handover_zone") or {}).get("floor_m")}
    return rec


def dumps(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True)


def loads(text) -> dict | None:
    if not text:
        return None
    try:
        rec = json.loads(text)
    except (TypeError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("version") == 1 else None


def _num_diff(a, b) -> float:
    return max(abs(float(x) - float(y)) for x, y in zip(a, b)) if len(a) == len(b) else math.inf


def compare(scene_rec: dict | None, trace_cfg: dict | None, tol: float = TOL_M) -> dict:
    """→ {"status": ok | no_scene_record | no_trace_config | mismatch, "diffs": [...], "notes": [...]}.
    ok 가 아니면 재생기는 거부한다(--allow-mismatch 면 '우회'로 표시하고 진행)."""
    if scene_rec is None:
        return {"status": "no_scene_record", "diffs": ["열린 USD 에 생성 설정 기록이 없음(예전 생성본) — build_scene.py 로 다시 만들 것"], "notes": []}
    if not trace_cfg or not trace_cfg.get("places"):
        return {"status": "no_trace_config", "diffs": ["궤적에 설정 기록이 없음(예전 형식) — trace_skill_flow.py 로 다시 뽑을 것"], "notes": []}
    places = trace_cfg["places"]
    diffs, notes = [], []
    for k in SCENE_KEYS:
        a, b = (places.get(k) or {}).get("tf") or {}, (scene_rec.get("tf") or {}).get(k) or {}
        for f in ("translation_m", "quaternion_xyzw"):
            va, vb = a.get(f), b.get(f)
            if va is None and vb is None:
                continue
            if va is None or vb is None:
                diffs.append(f"{k}.{f} 궤적 {va} / 씬 {vb} (한쪽만 있음)")
            elif _num_diff(va, vb) > tol:
                diffs.append(f"{k}.{f} 궤적 {va} ≠ 씬 {vb}")
    fa, fb = (places.get("handover_zone") or {}).get("floor_m"), scene_rec.get("handover_floor_m")
    if fa is not None and fb is not None and any(_num_diff(fa[ax], fb[ax]) > tol for ax in ("x", "y")):
        diffs.append(f"handover_zone.floor_m 궤적 {fa} ≠ 씬 {fb}")
    elif fa is None and fb is not None:
        notes.append("궤적에 handover_zone.floor_m 기록 없음 — 트레이 형상은 대조 못 함(tf 만 대조)")
    if trace_cfg.get("places_sha256") and trace_cfg["places_sha256"] != scene_rec.get("places_sha256"):
        notes.append(f"places.yaml sha256 다름(궤적 {trace_cfg['places_sha256'][:12]} / 씬 {str(scene_rec.get('places_sha256'))[:12]}) — "
                     "tf·트레이가 같으면 주석 등 다른 부분 차이")
    return {"status": "mismatch" if diffs else "ok", "diffs": diffs, "notes": notes}


def pose_diff(T_base_prim, tf: dict) -> tuple[float, float]:
    """씬 prim 의 base 기준 4x4(중첩 리스트 또는 배열)와 tf 의 (평행이동 차이 m, 회전 차이 deg)."""
    t = tf["translation_m"]
    x, y, z, w = (float(v) for v in tf["quaternion_xyzw"])
    n = math.sqrt(x * x + y * y + z * z + w * w)
    x, y, z, w = x / n, y / n, z / n, w / n
    R = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    P = [[float(T_base_prim[i][j]) for j in range(4)] for i in range(4)]
    dpos = math.sqrt(sum((P[i][3] - float(t[i])) ** 2 for i in range(3)))
    tr = sum(P[i][j] * R[i][j] for i in range(3) for j in range(3))      # trace(P_R^T R)
    drot = math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1) / 2))))
    return dpos, drot
