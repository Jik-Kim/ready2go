"""태스크 실행 전 검사 — docs/runner.md 7.2, docs/safety.md 안전 게이트 1단계(스키마 검증).

① contracts/task.schema.json 스키마 검증
② 아직 구현 안 된 필드 거절 (recovery, on_halt → P2 후속). while·for_each·push/pop·fallback 은 P2 구현
③ 스키마가 잡지 못하는 실행 조건 (set_var 의 name, if·while 의 cond, while 의 max_iter, for_each 의 in·as,
   push/pop 의 stack, fallback 의 options, 스텝 ID 중복, retry 횟수)
④ skill 스텝 (#12): 온톨로지에 있는 primitive 스킬인지, params 이름이 스킬 정의와 맞는지
   (skill 의 retry 는 Runner 가 로봇이 움직이지 않은 실패에만 적용, interpreter.NO_MOTION_BY_ACTION)
⑤ 스킬 expand 안 블록 (#121·#245 계약안): fallback·if 만, fallback 은 next_on 필수, 넛지 뒤 $scan 을 쓰는
   집기·놓기 앞에는 다시 찍기(inspect_region → scan) — 넛지 전 관측으로 집지 않게
문제가 하나라도 있으면 로봇을 움직이기 전에 실행하지 않는다.
"""
from __future__ import annotations

from typing import Iterator

import jsonschema

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


def _check_block(step: dict, action: str | None, label: str) -> list[str]:
    """P2 제어 블록의 필수 칸 (스키마가 action 별로 강제하지 않는 것)."""
    params = step.get("params", {})
    errors = []
    if action == "while":
        if "cond" not in step:
            errors.append(f"{label}: while 에 cond 가 없음")
        if not isinstance(step.get("max_iter"), int) or step.get("max_iter", 0) < 1:
            errors.append(f"{label}: while 에 max_iter(1 이상)가 없음 — 무한 반복 금지")
    elif action == "for_each":
        if not (isinstance(step.get("in"), str) and step["in"].startswith("$")):
            errors.append(f"{label}: for_each 의 in 은 \"$변수\" 참조여야 함")
        if not step.get("as"):
            errors.append(f"{label}: for_each 에 as 가 없음")
    elif action in ("push", "pop"):
        if not isinstance(params.get("stack"), str) or params.get("stack", "").startswith("$"):
            errors.append(f"{label}: {action} 의 params.stack 은 스택 변수 이름(문자열)이어야 함")
        if action == "push" and "value" not in params:
            errors.append(f"{label}: push 에 params.value 가 없음")
    elif action == "fallback":
        options = step.get("options")
        if not isinstance(options, list) or not options or not all(isinstance(o, list) and o for o in options):
            errors.append(f"{label}: fallback 의 options 는 스텝 배열 1개 이상의 목록이어야 함")
        if "next_on" in step and not (isinstance(step["next_on"], list) and step["next_on"]
                                      and all(isinstance(c, str) and c for c in step["next_on"])):
            errors.append(f"{label}: fallback 의 next_on 은 오류 코드 문자열 1개 이상의 목록이어야 함")
    if action in ("while", "for_each") and not step.get("body"):
        errors.append(f"{label}: {action} 에 body 가 없음")
    return errors


RESCAN_NEEDED_BY = ("pick_object", "place_object")   # $scan 을 쓰는 동작 — 넛지 뒤엔 새 관측이 있어야 함


def _check_expand(subs: list, prefix: str, label: str, ids: list[str], stale: bool = False) -> tuple[list[str], bool]:
    """스킬 expand 목록 검사 (#121). (문제 목록, 끝났을 때 $scan 이 넛지 전 관측인지)를 돌려준다."""
    errors: list[str] = []
    for m, sub in enumerate(subs if isinstance(subs, list) else [], 1):
        cid, action = f"{prefix}{m}", sub.get("action") if isinstance(sub, dict) else None
        ids.append(cid)
        where = f"{label} {cid}"
        if not action or "skill" in sub:
            errors.append(f"{where}: 스킬 expand 에는 원자 동작이나 fallback·if 만 (스킬 안 스킬 미지원)")
            continue
        if action == "fallback":
            options = sub.get("options")
            if not isinstance(options, list) or not options or not all(isinstance(o, list) and o for o in options):
                errors.append(f"{where}: fallback 의 options 는 스텝 배열 1개 이상의 목록이어야 함")
                continue
            if not (isinstance(sub.get("next_on"), list) and sub["next_on"]
                    and all(isinstance(c, str) and c for c in sub["next_on"])):
                errors.append(f"{where}: 스킬 expand 안 fallback 은 next_on(다음 대안으로 갈 오류 코드)이 필수")
            ends = []
            for k, option in enumerate(options, 1):
                errs, end = _check_expand(option, f"{cid}.o{k}.", label, ids, stale)
                errors += errs
                ends.append(end)
            stale = any(ends)
        elif action == "if":
            if "cond" not in sub:
                errors.append(f"{where}: if 에 cond 가 없음")
            ends = []
            for key, mark in (("then", "t"), ("else", "f")):
                errs, end = _check_expand(sub.get(key, []), f"{cid}.{mark}", label, ids, stale)
                errors += errs
                ends.append(end)
            stale = any(ends)
        elif action in ("while", "for_each", "push", "pop"):
            errors.append(f"{where}: 스킬 expand 안 {action} 미지원 (fallback·if 만)")
        elif action == "nudge_object":
            stale = True                        # 밀었을 수 있음 → 그 전 관측은 쓰지 않음
        elif action == "inspect_region" and sub.get("output") == "scan":
            stale = False
        elif action in RESCAN_NEEDED_BY and stale and "$scan" in str(sub.get("params", {})):
            errors.append(f"{where}: 넛지 뒤 {action} 앞에 다시 찍기(inspect_region → scan)가 없음 — 넛지 전 관측으로 집지 않음")
    return errors, stale


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
            errors += _check_block(step, action, label)
            for f in sorted(P2_STEP_FIELDS & step.keys()):
                errors.append(f"P1 미지원: {label} 필드 '{f}'")
            if sid in seen:
                errors.append(f"스텝 ID 중복: '{sid}' ({seen[sid]}, {where})")
            seen.setdefault(sid, where)
            if "skill" in step and skills is not None:
                errors += _check_skill(step, label, skills)
                skill = skills.get(step["skill"])
                expand = skill.get("expand", []) if isinstance(skill, dict) else []
                ids: list[str] = []             # Runner 가 붙일 하위 기록 ID (<id>.e<n>, 블록 안 .o<k>.<m>·.t<m>·.f<m>)
                errors += _check_expand(expand, f"{sid}.e", f"{label} 스킬 '{step['skill']}' expand", ids)[0]
                for child in ids:
                    if child in seen:
                        errors.append(f"스텝 ID 중복: '{child}' ({seen[child]}, {where} 스킬의 하위 동작)")
                    seen.setdefault(child, f"{where} → {child}")
            if action == "set_var" and "name" not in step.get("params", {}):
                errors.append(f"{label}: set_var 에 params.name 이 없음")
            if action == "if" and "cond" not in step:
                errors.append(f"{label}: if 에 cond 가 없음")
            if step.get("on_failure") == "retry" and step.get("retry", 0) < 1:
                errors.append(f"{label}: on_failure 'retry' 는 retry 1 이상이 필요함")
    return errors
