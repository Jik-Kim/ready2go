"""태스크 실행 전 검사 — docs/runner.md 7.2, docs/safety.md 안전 게이트 1단계(스키마 검증).

① contracts/task.schema.json 스키마 검증
② Phase 1 범위 밖 블록·필드 거절 (while, for_each, push/pop, fallback, recovery, on_halt → P2)
③ 스키마가 잡지 못하는 실행 조건 (set_var 의 name, if 의 cond, 스텝 ID 중복, retry 횟수)
④ skill 스텝 (#12): 온톨로지에 있는 primitive 스킬인지, params 이름이 스킬 정의와 맞는지
   (skill 의 retry 는 Runner 가 로봇이 움직이지 않은 실패에만 적용, interpreter.NO_MOTION_CODES)
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


def _check_skill(step: dict, label: str, skills: dict) -> list[str]:
    name = step["skill"]
    skill = skills.get(name)
    if not isinstance(skill, dict):
        return [f"{label}: 온톨로지에 없는 스킬 '{name}'"]
    if skill.get("kind") != "primitive":
        return [f"P1 미지원: {label} {skill.get('kind')} 스킬 '{name}' (P1 은 primitive 만)"]
    expected, given = set(skill.get("params", {})), set(step.get("params", {}))
    errors = [f"{label}: 스킬 '{name}' 에 params.{p} 가 없음" for p in sorted(expected - given)]
    errors += [f"{label}: 스킬 '{name}' 에 없는 파라미터 params.{p}" for p in sorted(given - expected)]
    return errors


def check_task(task: dict, schema: dict | None, skills: dict | None = None) -> list[str]:
    """문제 목록을 돌려준다. 빈 목록이면 실행 가능.
    skills: 온톨로지의 skills (Runner 가 전달). None 이면 skill 스텝의 이름·파라미터는 검사하지 않음."""
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
            if "skill" in step and skills is not None:
                errors += _check_skill(step, label, skills)
                skill = skills.get(step["skill"])
                expand = skill.get("expand", []) if isinstance(skill, dict) else []
                for i in range(1, len(expand) + 1):   # Runner 가 붙일 하위 기록 ID (<id>.e<n>)
                    child = f"{sid}.e{i}"
                    if child in seen:
                        errors.append(f"스텝 ID 중복: '{child}' ({seen[child]}, {where} 스킬의 하위 동작)")
                    seen.setdefault(child, f"{where}.e{i}")
            if action == "set_var" and "name" not in step.get("params", {}):
                errors.append(f"{label}: set_var 에 params.name 이 없음")
            if action == "if" and "cond" not in step:
                errors.append(f"{label}: if 에 cond 가 없음")
            if step.get("on_failure") == "retry" and step.get("retry", 0) < 1:
                errors.append(f"{label}: on_failure 'retry' 는 retry 1 이상이 필요함")
    return errors
