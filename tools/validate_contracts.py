#!/usr/bin/env python3
"""contracts/ · knowledge/ · tasks/ 원본 JSON 검증 (CI·로컬 공통).

- tasks/*.json 이 contracts/task.schema.json 을 통과하는지
- contracts/examples/intent_*.json 이 intent.schema.json 을 통과하는지
- contracts/examples/inspect_region_result.json 의 pose 규칙(position.z = 0, yaw 범위)
- contracts/examples/nudge_object_result.json 의 target_after 규칙(성공일 때만 target 형식, 실패면 null)
- contracts/examples/place_object_result.json 의 서랍 안 놓기 규칙(pose·scan, placed_pose 는 놓은 뒤에만, 거부는 blocked_by)
- contracts/examples/pick_object_result.json 의 hand·grasp_evidence 규칙, drawer_control_result.json 의 열기·닫기 근거 규칙 (PR #223)
- 온톨로지 목록 참조 · 스킬 파라미터($변수) 참조가 맞는지
"""
import json
import math
import re
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ros2_ws/src/ready2go_knowledge"))
sys.path.insert(0, str(ROOT / "ros2_ws/src/ready2go_runner"))
sys.path.insert(0, str(ROOT / "ros2_ws/src/ready2go_vision"))
from ready2go_runner.core.validation import check_task  # noqa: E402
from ready2go_knowledge.core import ontology as onto_lib  # noqa: E402
from ready2go_vision.core.pose_rules import pose_errors, result_errors  # noqa: E402


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


PLACE_BEFORE_MOTION = {"PLACE_BLOCKED", "WALL_TOO_CLOSE", "BAD_PARAMS", "NOT_HOLDING", "UNSUPPORTED_PARAMS",
                       "PLACE_NOT_CONFIGURED", "TRAY_FULL", "DRAWER_NOT_AT_TRAVEL"}   # 움직이기 전 거부 — 놓지 않았으므로 placed_pose 없음


def place_pose_errors(pose, frame, where):
    """서랍 안 놓기 pose: {frame, position [x, y, 0], yaw (-pi/2, pi/2]} — inspect_region pose 와 같은 기준 (yaw_valid 없음)."""
    if not isinstance(pose, dict):
        return [f"{where} 는 {{frame, position, yaw}}"]
    errs = pose_errors({**pose, "yaw_valid": True}, where)
    nums = list(pose.get("position") or [])[:2] + [pose.get("yaw")]
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in nums):
        errs.append(f"{where} 의 position x·y·yaw 는 유한한 수 — 값 {nums}")
    if pose.get("frame") != frame:
        errs.append(f"{where}.frame 은 location 과 같은 서랍 ({frame}) — 값 {pose.get('frame')}")
    return errs


HANDS = {"holding", "empty", "released", "unknown"}


def pick_result_errors(doc):
    """pick_object 결과 (PR #223): grasp_ok(파지 성공)와 hand(손 상태)를 따로. 빈손 확정(empty)은 들어 올리다 놓침(DROPPED, 폭 ≤ 2 mm)만
    [#43 결정 E-B-C-GRIPPER-OBSERVATION-20261011-10], 성공은 같은 pick 의 닫은 폭 > 하한·grasp_detected·들어 올린 뒤 유지."""
    errs = []
    for c in doc["cases"]:
        out, name = c["output"], c["case"]
        hand, ev = out.get("hand"), out.get("grasp_evidence") or {}
        if hand not in HANDS:
            errs.append(f"{name}: hand 는 {sorted(HANDS)} 중 하나 — 값 {hand!r}")
        if out.get("grasp_ok") is not c["success"]:
            errs.append(f"{name}: grasp_ok 는 success 와 같음")
        if c["success"]:
            w, lo = ev.get("closed_width_m"), ev.get("min_width_m")
            if hand != "holding" or ev.get("grasp_detected") is not True or ev.get("lift") not in ("HELD", "SLIPPED") \
                    or not (isinstance(w, (int, float)) and isinstance(lo, (int, float)) and w > lo):
                errs.append(f"{name}: 성공은 hand holding·grasp_detected·닫은 폭 > min_width_m·lift HELD/SLIPPED")
            if not isinstance(out.get("pick_pose_drawer_frame"), dict):
                errs.append(f"{name}: 성공 결과에 pick_pose_drawer_frame 필요")
        if hand == "empty" and ev.get("lift") != "DROPPED":
            errs.append(f"{name}: hand empty(빈손 확정)는 들어 올리다 폭이 빈손 닫힘까지 줄었을 때(lift DROPPED)만")
    return errs


def drawer_result_errors(doc):
    """drawer_control 결과 (PR #223): 열기 성공은 drawer_displacement ≥ 0.9 × open_distance_m(open_drawer verify 근거),
    close_confirmed 는 남은 거리 ≤ 허용오차이고 밀기가 중간에 멈추지 않았을 때만."""
    errs = []
    for c in doc["cases"]:
        out, name, state = c["output"], c["case"], c["params"].get("state")
        if state == "open" and c["success"] and not out["drawer_displacement"] >= 0.9 * out.get("open_distance_m", float("inf")):
            errs.append(f"{name}: 열기 성공은 drawer_displacement ≥ 0.9 × open_distance_m")
        if state == "close" and out.get("close_confirmed"):
            rem, tol = out.get("close_remaining_m"), out.get("close_pos_tol_m")
            if out.get("close_push_interrupted") is not False or rem is None or tol is None or rem > tol:
                errs.append(f"{name}: close_confirmed 는 close_remaining_m ≤ close_pos_tol_m·close_push_interrupted false 일 때만")
        if state == "close" and c["success"] != bool(out.get("close_confirmed")):
            errs.append(f"{name}: 닫기 성공 = close_confirmed")
    return errs


def place_result_errors(doc):
    """place_object 결과 규칙 (#120 ② 계약안): 서랍 안 놓기는 pose 또는 slot + scan(직전 inspect_region 결과 전체 — target 도 이웃으로 검사, #166 D 리뷰),
    placed_pose 는 그리퍼를 연 뒤에만(움직이기 전 거부면 null), 이웃·벽 거부는 blocked_by."""
    errs = []
    for c in doc["cases"]:
        p, out, code, name = c["params"], c["output"], c["error_code"], c["case"]
        loc = p.get("location")
        drawer = isinstance(loc, str) and loc.startswith("drawer_")
        if drawer:
            if ("pose" in p) == ("slot" in p) and code != "BAD_PARAMS":
                errs.append(f"{name}: 서랍 안 놓기는 params.pose·params.slot 중 정확히 하나 — 둘 다·둘 다 없음은 BAD_PARAMS")
            if "pose" in p and code != "BAD_PARAMS":
                errs += [f"{name}: {m}" for m in place_pose_errors(p["pose"], loc, "params.pose")]
            scan = p.get("scan")
            if code != "BAD_PARAMS":
                if not isinstance(scan, dict):
                    errs.append(f"{name}: 서랍 안 놓기는 params.scan(직전 inspect_region 결과 전체, $scan) 필요 — 없으면 BAD_PARAMS")
                else:
                    errs += [f"{name}: params.scan {m}" for m in result_errors(scan)]
            seen = ([scan["target"]] if isinstance(scan, dict) and scan.get("target") else []) + \
                (scan.get("candidates", []) if isinstance(scan, dict) else [])
            by = out.get("blocked_by")
            if code == "PLACE_BLOCKED" and by not in {o.get("id") for o in seen}:
                errs.append(f"{name}: PLACE_BLOCKED 의 blocked_by 는 scan 의 target·candidates 중 하나의 id — 값 {by}")
        placed = out.get("placed_pose", "없음")
        if c["success"] and not isinstance(placed, dict):
            errs.append(f"{name}: 성공 결과에 placed_pose 필요")
        if not c["success"] and code in PLACE_BEFORE_MOTION and placed is not None:
            errs.append(f"{name}: 움직이기 전 거부({code})의 placed_pose 는 null")
        if drawer and isinstance(placed, dict):
            errs += [f"{name}: {m}" for m in place_pose_errors(placed, loc, "output.placed_pose")]
        if code in ("PLACE_BLOCKED", "WALL_TOO_CLOSE") and not out.get("blocked_by"):
            errs.append(f"{name}: {code} 결과에 blocked_by(이웃 id 또는 \"wall\") 필요")
    return errs


def main() -> int:
    errors = []
    task_schema = load(ROOT / "contracts/task.schema.json")
    for p in sorted((ROOT / "tasks").glob("*.json")):
        try:
            jsonschema.validate(load(p), task_schema)
        except jsonschema.ValidationError as e:
            errors.append(f"{p.name}: {e.message}")
    for p in sorted((ROOT / "contracts/examples").glob("task_*.json")):   # 예시 태스크: 스키마 + Phase 1 범위(실행 전 검사와 같은 규칙)
        for msg in check_task(load(p), task_schema):
            errors.append(f"{p.name}: {msg}")
    intent_schema = load(ROOT / "contracts/intent.schema.json")
    for p in sorted((ROOT / "contracts/examples").glob("intent_*.json")):
        try:
            jsonschema.validate(load(p), intent_schema)
        except jsonschema.ValidationError as e:
            errors.append(f"{p.name}: {e.message}")
    load(ROOT / "contracts/examples/execution_log.json")
    errors += [f"inspect_region_result.json: {m}" for m in result_errors(load(ROOT / "contracts/examples/inspect_region_result.json"))]   # pose 규칙: position.z=0, yaw (-pi/2, pi/2]
    for c in load(ROOT / "contracts/examples/nudge_object_result.json")["cases"]:   # target_after: 성공일 때만, 실패면 null (#83)
        after = c["output"].get("target_after", "없음")
        if not c["success"] and after is not None:
            errors.append(f"nudge_object_result.json {c['case']}: 실패 결과의 target_after 는 null")
        if c["success"]:
            if not isinstance(after, dict):
                errors.append(f"nudge_object_result.json {c['case']}: 성공 결과에 target_after(target 형식) 필요")
            else:
                errors += [f"nudge_object_result.json {c['case']}: {m}"
                           for m in result_errors({"target_found": True, "target": after, "candidates": [], "visible_count": 1})]
    errors += [f"place_object_result.json {m}" for m in place_result_errors(load(ROOT / "contracts/examples/place_object_result.json"))]
    errors += [f"pick_object_result.json {m}" for m in pick_result_errors(load(ROOT / "contracts/examples/pick_object_result.json"))]
    errors += [f"drawer_control_result.json {m}" for m in drawer_result_errors(load(ROOT / "contracts/examples/drawer_control_result.json"))]
    raw = load(ROOT / "knowledge/robot_ontology.jsonld")   # 서랍 물리 값(인출 거리 등)의 정본은 config/places.yaml. 온톨로지에 따로 두면 서로 어긋난다
    for pname, pdef in raw.get("world", {}).get("places", {}).items():
        if pdef.get("max_travel_m") is not None:
            errors.append(f"knowledge/robot_ontology.jsonld: places.{pname}.max_travel_m 은 config/places.yaml 이 정본이므로 온톨로지에는 null 로 둔다")
    onto = onto_lib.load(ROOT / "knowledge/robot_ontology.jsonld")
    classes_f = ROOT / "config/yolo_classes.txt"   # YOLO 클래스 고정 목록: 온톨로지에 없는 이름이 있으면 라벨 번호가 깨진다
    if classes_f.exists():
        names = [l.strip() for l in classes_f.read_text(encoding="utf-8").splitlines() if l.strip()]
        errors += [f"config/yolo_classes.txt: 온톨로지 world.items 에 없는 클래스 {n}" for n in names if n not in onto.get("world", {}).get("items", {})]
        if len(set(names)) != len(names):
            errors.append("config/yolo_classes.txt: 중복된 클래스 이름")
    errors += onto_lib.list_reference_errors(onto)
    for name, skill in onto.get("skills", {}).items():
        if skill.get("kind") != "primitive":
            continue
        for var in set(re.findall(r'"\$(\w+)', json.dumps(skill))):
            if var not in skill["params"] and var != "scan":
                errors.append(f"skills.{name}: 파라미터에 없는 변수 ${var}")
    for e in errors:
        print("ERROR", e)
    print("OK" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
