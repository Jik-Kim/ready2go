"""태스크 실행 전 검사 — docs/runner.md 7.2, docs/safety.md 안전 게이트 1단계(스키마 검증).

① contracts/task.schema.json 스키마 검증
② 아직 구현 안 된 필드 거절 (recovery, on_halt → P2 후속). while·for_each·push/pop·fallback 은 P2 구현
③ 스키마가 잡지 못하는 실행 조건 (set_var 의 name, if·while 의 cond, while 의 max_iter, for_each 의 in·as,
   push/pop 의 stack, fallback 의 options, 스텝 ID 중복, retry 횟수)
④ skill 스텝 (#12): 온톨로지에 있는 primitive 스킬인지, params 이름이 스킬 정의와 맞는지
   (skill 의 retry 는 Runner 가 로봇이 움직이지 않은 실패에만 적용, interpreter.NO_MOTION_BY_ACTION)
⑤ 스킬 expand 안 블록 (#121·#245 계약): fallback·if 만, fallback 은 next_on 필수, 넛지 뒤 집기·놓기는
   넛지 뒤 새로 찍은 관측의 target·scan 만 (분기 뒤엔 모든 경로에서 새로 찍은 것), target_after 는 집기·놓기에 안 씀
문제가 하나라도 있으면 로봇을 움직이기 전에 실행하지 않는다.
"""
from __future__ import annotations

import re
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


RESCAN_NEEDED_BY = ("pick_object", "place_object")   # 관측을 쓰는 동작 — 넛지 뒤엔 그 뒤 새 관측의 값만
_TARGET_REF = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)\.target$")
_VAR_REF = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")


def _rescan_errors(action: str, params: dict, fresh: set[str] | None) -> list[str]:
    """넛지 뒤 집기·놓기가 **넛지 뒤 새로 찍은 관측**만 쓰는지 (#263 E 리뷰: 글자 포함 검사는 우회됨).
    fresh: 마지막 넛지 뒤 inspect_region 출력 변수들(None = 아직 넛지 없음). 집기 target 은 "$<새 관측>.target",
    scan 을 주면 "$<같은 새 관측>" 이어야 함. target_after(넛지 예상값)는 넛지 여부와 무관하게 집기·놓기에 쓰지 않음."""
    params = params if isinstance(params, dict) else {}
    target, scan = params.get("target"), params.get("scan")
    errors = []
    if any(isinstance(v, str) and "target_after" in v for v in (target, scan)):
        errors.append(f"{action} 에 넛지 예상값(target_after)을 씀 — 다시 찍은 관측으로만")
    if fresh is None:
        return errors
    m = _TARGET_REF.match(target) if isinstance(target, str) else None
    if action == "pick_object" and not (m and m.group(1) in fresh):
        errors.append(f"넛지 뒤 {action} 의 target 이 넛지 뒤 새로 찍은 관측(inspect_region 출력)의 .target 이 아님")
    if scan is not None:
        v = _VAR_REF.match(scan) if isinstance(scan, str) else None
        if not (v and v.group(1) in fresh and (not m or v.group(1) == m.group(1))):
            errors.append(f"넛지 뒤 {action} 의 scan 이 target 과 같은, 넛지 뒤 새 관측 전체가 아님")
    return errors


def _check_expand(subs: list, prefix: str, label: str, ids: list[str],
                  fresh: set[str] | None = None) -> tuple[list[str], set[str] | None]:
    """스킬 expand 목록 검사 (#121). (문제 목록, 끝났을 때의 fresh)를 돌려준다 — fresh 는 마지막 넛지 뒤
    inspect_region 출력 변수(None = 넛지 없음). 분기 뒤에는 모든 경로에서 새로 찍은 변수만 남김(보수적)."""
    errors: list[str] = []
    for m, sub in enumerate(subs if isinstance(subs, list) else [], 1):
        cid, action = f"{prefix}{m}", sub.get("action") if isinstance(sub, dict) else None
        ids.append(cid)
        where = f"{label} {cid}"
        if not action or "skill" in sub:
            errors.append(f"{where}: 스킬 expand 에는 원자 동작이나 fallback·if 만 (스킬 안 스킬 미지원)")
            continue
        if action in ("fallback", "if"):
            if action == "fallback":
                branches = sub.get("options")
                if not isinstance(branches, list) or not branches or not all(isinstance(o, list) and o for o in branches):
                    errors.append(f"{where}: fallback 의 options 는 스텝 배열 1개 이상의 목록이어야 함")
                    continue
                if not (isinstance(sub.get("next_on"), list) and sub["next_on"]
                        and all(isinstance(c, str) and c for c in sub["next_on"])):
                    errors.append(f"{where}: 스킬 expand 안 fallback 은 next_on(다음 대안으로 갈 오류 코드)이 필수")
                parts = [(f"{cid}.o{k}.", o) for k, o in enumerate(branches, 1)]
            else:
                if "cond" not in sub:
                    errors.append(f"{where}: if 에 cond 가 없음")
                parts = [(f"{cid}.t", sub.get("then", [])), (f"{cid}.f", sub.get("else", []))]
            ends = []
            for pre, branch in parts:
                errs, end = _check_expand(branch, pre, label, ids, None if fresh is None else set(fresh))
                errors += errs
                ends.append(end)
            nudged = [e for e in ends if e is not None]
            fresh = None if not nudged else set.intersection(*nudged)   # 한 경로라도 넛지했으면 모든 경로의 새 관측만
        elif action in ("while", "for_each", "push", "pop"):
            errors.append(f"{where}: 스킬 expand 안 {action} 미지원 (fallback·if 만)")
        else:
            if action in RESCAN_NEEDED_BY:      # 입력 먼저 검사한 뒤, 이 동작이 쓰는 변수를 반영
                errors += [f"{where}: {e}" for e in _rescan_errors(action, sub.get("params", {}), fresh)]
            if action == "nudge_object":
                fresh = set()                   # 밀었을 수 있음 → 그 전 관측은 모두 버림
            elif fresh is not None:
                fresh = _after_writes(action, sub, fresh)
    return errors, fresh


def _after_writes(action: str, sub: dict, fresh: set[str]) -> set[str]:
    """동작이 변수를 쓰면 그 변수는 '넛지 뒤 새 관측' 자격을 잃음 — inspect_region 출력만 다시 얻음 (#263 E 재리뷰:
    set_var 로 새 관측 변수를 넛지 전 값으로 되돌리면 검사가 통과하던 것). 쓰기 대상을 정적으로 모르면 전부 버림."""
    fresh = set(fresh)
    out = sub.get("output")
    if action == "inspect_region":
        if isinstance(out, str):
            fresh.add(out)
        return fresh
    if isinstance(out, str):
        fresh.discard(out)
    if action == "set_var":
        name = (sub.get("params") or {}).get("name")
        if isinstance(name, str) and name and not name.startswith("$"):
            fresh.discard(name)
        else:
            fresh.clear()                       # 동적·누락 이름 → 어느 변수를 바꿨는지 모름
    return fresh


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
