"""태스크 실행 전 검사 — docs/runner.md 7.2, docs/safety.md 안전 게이트 1단계(스키마 검증).

① contracts/task.schema.json 스키마 검증
② Phase 1 범위 밖 블록·필드 거절 (while, for_each, push/pop, fallback, recovery, on_halt → P2)
③ 스키마가 잡지 못하는 실행 조건 (set_var 의 name, if 의 cond, 스텝 ID 중복, retry 횟수)
문제가 하나라도 있으면 로봇을 움직이기 전에 실행하지 않는다.
"""
from __future__ import annotations

from typing import Iterator

import jsonschema

P2_ACTIONS = {"while", "for_each", "push", "pop", "fallback"}
P2_STEP_FIELDS = {"recovery"}
P2_TASK_FIELDS = {"on_halt"}
CHILD_LISTS = ("then", "else", "body", "recovery")     # 스텝 안에 스텝 배열이 들어가는 필드
TASK_INVALID = "TASK_INVALID"


def _walk(steps: list[dict], where: str) -> Iterator[tuple[dict, str]]:
    """중첩 스텝까지 모두 (스텝, 위치) 로 돌려준다. 위치 예: sequence[2].then[0]"""
    for i, step in enumerate(steps):
        here = f"{where}[{i}]"
        yield step, here
        for key in CHILD_LISTS:
            yield from _walk(step.get(key, []), f"{here}.{key}")
        for j, option in enumerate(step.get("options", [])):
            yield from _walk(option, f"{here}.options[{j}]")


def check_task(task: dict, schema: dict | None) -> list[str]:
    """문제 목록을 돌려준다. 빈 목록이면 실행 가능."""
    if schema is not None:
        errors = [f"스키마: {'/'.join(map(str, e.absolute_path)) or '(최상위)'}: {e.message}"
                  for e in jsonschema.Draft7Validator(schema).iter_errors(task)]
        if errors:
            return errors                       # 형식이 틀리면 아래 검사는 의미가 없음

    errors = [f"P1 미지원: 태스크 필드 '{f}'" for f in sorted(P2_TASK_FIELDS & task.keys())]
    seen: dict[str, str] = {}
    for part in ("sequence", "finally"):
        for step, where in _walk(task.get(part, []), part):
            sid, action = step.get("id"), step.get("action")
            label = f"{where}({sid})"
            if action in P2_ACTIONS:
                errors.append(f"P1 미지원: {label} action '{action}'")
            for f in sorted(P2_STEP_FIELDS & step.keys()):
                errors.append(f"P1 미지원: {label} 필드 '{f}'")
            if sid in seen:
                errors.append(f"스텝 ID 중복: '{sid}' ({seen[sid]}, {where})")
            seen.setdefault(sid, where)
            if action == "set_var" and "name" not in step.get("params", {}):
                errors.append(f"{label}: set_var 에 params.name 이 없음")
            if action == "if" and "cond" not in step:
                errors.append(f"{label}: if 에 cond 가 없음")
            if step.get("on_failure") == "retry" and step.get("retry", 0) < 1:
                errors.append(f"{label}: on_failure 'retry' 는 retry 1 이상이 필요함")
    return errors
