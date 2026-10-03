#!/usr/bin/env python3
"""contracts/ · knowledge/ · tasks/ 원본 JSON 검증 (CI·로컬 공통).

- tasks/*.json 이 contracts/task.schema.json 을 통과하는지
- contracts/examples/intent_*.json 이 intent.schema.json 을 통과하는지
- 온톨로지 목록 참조 · 스킬 파라미터($변수) 참조가 맞는지
"""
import json
import re
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ros2_ws/src/ready2go_knowledge"))
sys.path.insert(0, str(ROOT / "ros2_ws/src/ready2go_runner"))
from ready2go_runner.core.validation import check_task  # noqa: E402
from ready2go_knowledge.core import ontology as onto_lib  # noqa: E402


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


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
