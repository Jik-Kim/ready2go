"""자동 스킬 플래너 (ROS 비의존) — FR-PLN-02, docs/planner.md 7.7, #150.

현재 상태와 온톨로지 primitive 스킬의 pre(조건)·effect(결과)만으로 목표를 만족하는 **최단 스킬 순서**를
너비 우선 탐색(BFS, 깊이 제한)으로 찾는다. 동작 순서는 코드에 없다 — 스킬 정의(E)에서 도출된다.

- 목표: [{"predicate", "subject", "value"}] (E LLM 이 목표만 출력, contracts/examples/intent_goal.json)
- 자동 목표: 계획 시작 때 닫혀 있던 서랍은 끝에 닫혀 있어야 함("이번 계획에서 연 서랍은 닫기").
  명시 목표가 그 서랍을 열어 두라고 하면 명시 목표가 우선
- 결과: PLANNED(스텝 + 단계별 근거) / SATISFIED(이미 만족, 길이 0) / UNPLANNABLE(원인)
- 후보 줄이기: 물품 파라미터는 목표에 나온 물품과 지금 쥔 물품만 (다른 물품은 목표 달성에 필요 없음)
- 지원 범위(limits): 백엔드가 실제로 할 수 있는 파라미터 값만 후보로 (예: 실물 놓기는 전달 트레이만). 그 밖의
  계획은 만들지 않고 UNPLANNABLE — 기호상 가능하지만 실물이 못 하는 계획을 중간까지 실행하지 않게 (#154 E 리뷰 P1)
"""
from __future__ import annotations

import itertools
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ready2go_knowledge.core import ontology

PLANNED, SATISFIED, UNPLANNABLE = "PLANNED", "SATISFIED", "UNPLANNABLE"
MAX_DEPTH = 8                           # docs/planner.md: 스킬 10개 안팎의 작은 세계라 깊이 8이면 충분
MAX_STATES = 20000                      # 탐색 상한 (넘으면 계획 불가로 끝냄 — 무한 탐색 방지)
ROBOT, GRIPPER = "robot", "gripper"


@dataclass
class Step:
    skill: str
    params: dict[str, str]
    reasons: list[str] = field(default_factory=list)   # 이 스텝이 필요한 이유 (단계별 근거)

    def label(self) -> str:
        return f"{self.skill}({', '.join(f'{v}' for v in self.params.values())})"


@dataclass
class PlanResult:
    status: str
    steps: list[Step]
    goals: list[dict]                   # 명시 목표 + 자동 목표
    reason: str = ""                    # SATISFIED·UNPLANNABLE 일 때 사람이 읽는 설명
    explored: int = 0                   # 탐색한 상태 수 (로그)


# ---- 목표 ----

def _goal_ok(state: dict, goal: dict) -> bool:
    return ontology.get(state, goal["predicate"], goal["subject"]) == goal["value"]


def _auto_goals(state: dict, world: dict, goals: list[dict]) -> list[dict]:
    """시작 때 닫힌 서랍은 끝에 닫혀 있게 (명시 목표가 그 서랍의 open 을 정하면 그것을 따름)."""
    explicit = {(g["predicate"], g["subject"]) for g in goals}
    auto = []
    for place, info in sorted(world.get("places", {}).items()):
        if info.get("class") == "Drawer" and ontology.get(state, "open", place) is False \
                and ("open", place) not in explicit:
            auto.append({"predicate": "open", "subject": place, "value": False, "auto": True})
    return auto


def _goal_text(goal: dict) -> str:
    return f"{goal['predicate']}.{goal['subject']} = {json.dumps(goal['value'], ensure_ascii=False)}"


# ---- 파라미터 후보 ----

def _is_a(cls: str | None, want: str, classes: dict) -> bool:
    seen = set()
    while cls and cls not in seen:
        if cls == want:
            return True
        seen.add(cls)
        cls = (classes.get(cls) or {}).get("subClassOf")
    return False


def _candidates(want: str, onto: dict, relevant_items: set[str]) -> list[str]:
    classes, world = onto.get("classes", {}), onto.get("world", {})
    out = [p for p, info in world.get("places", {}).items() if _is_a(info.get("class"), want, classes)]
    out += [i for i, info in world.get("items", {}).items()
            if i in relevant_items and _is_a(info.get("class", "Item"), want, classes)]
    return sorted(out)


# Runner 노드 plan_limits 기본값 = P2 실물 지원 범위 [B 확인 필요]. 서랍은 위·아래 칸(B 아래 칸 열기 교시·S2 꺼내기 실물 10/12),
# 집기는 서랍에서만, 놓기는 전달 트레이만. open_drawer.one_open=true = 서랍은 한 번에 하나만 엶(위 칸이 열리면 아래 칸 위를 덮음 —
# 두 칸을 같이 열고 아래 칸에서 집는 계획을 만들지 않음). P3 다중 서랍 동시 작업은 범위 밖.
DEFAULT_PLAN_LIMITS = ("open_drawer.drawer_id=drawer_top|drawer_bottom,open_drawer.one_open=true,"
                       "close_drawer.drawer_id=drawer_top|drawer_bottom,pick.from=drawer_top|drawer_bottom,"
                       "place.to=handover_zone")


def parse_limits(text: str) -> dict[str, dict[str, set[str]]]:
    """"place.to=handover_zone,pick.from=drawer_top|drawer_bottom" → {"place": {"to": {"handover_zone"}}, ...}.
    빈 문자열이면 제한 없음."""
    limits: dict[str, dict[str, set[str]]] = {}
    for entry in filter(None, (part.strip() for part in text.split(","))):
        key, _, values = entry.partition("=")
        skill, _, param = key.strip().partition(".")
        if not skill or not param or not values.strip():
            raise ValueError(f"지원 범위 형식은 스킬.파라미터=값|값: {entry!r}")
        limits.setdefault(skill, {})[param] = {v.strip() for v in values.split("|") if v.strip()}
    return limits


def _groundings(skills: dict, onto: dict, relevant_items: set[str],
                limits: dict | None = None) -> list[tuple[str, dict, dict]]:
    """(스킬 이름, 스킬 정의, 파라미터 값) 전부 — 결정적 순서 (스킬 이름·파라미터 값 정렬). limits 밖의 값은 뺌."""
    out = []
    for name in sorted(skills):
        skill = skills[name]
        if not isinstance(skill, dict) or skill.get("kind") != "primitive":
            continue
        names = list(skill.get("params", {}))
        allowed = (limits or {}).get(name, {})
        pools = [[v for v in _candidates(skill["params"][n], onto, relevant_items)
                  if n not in allowed or v in allowed[n]] for n in names]
        for values in itertools.product(*pools):
            out.append((name, skill, dict(zip(names, values))))
    return out


# ---- 탐색 ----

def _key(state: dict) -> str:
    return json.dumps(state, sort_keys=True, ensure_ascii=False)


def plan(state: dict, onto: dict, goals: list[dict], max_depth: int = MAX_DEPTH,
         limits: dict | None = None) -> PlanResult:
    """목표를 만족하는 최단 스킬 순서. state 는 Runner 상태(predicate → subject → value).
    limits: 스킬 → 파라미터 → 허용 값 (백엔드 지원 범위, parse_limits). None 이면 제한 없음(mock·시험)."""
    problem = _check_goals(goals, onto)
    if problem:
        return PlanResult(UNPLANNABLE, [], goals, problem)
    all_goals = [*goals, *_auto_goals(state, onto.get("world", {}), goals)]
    if all(_goal_ok(state, g) for g in all_goals):
        return PlanResult(SATISFIED, [], all_goals, "이미 만족: " + ", ".join(_goal_text(g) for g in goals))

    skills = onto.get("skills", {})
    unreachable = _unreachable(goals, skills)
    if unreachable:
        return PlanResult(UNPLANNABLE, [], all_goals, unreachable)

    held = ontology.get(state, "gripper", ROBOT)
    relevant = {g["subject"] for g in goals} | {g["value"] for g in goals if isinstance(g["value"], str)}
    relevant |= {held} if held and held != "empty" else set()
    actions = _groundings(skills, onto, relevant, limits)
    one_open = (limits or {}).get("open_drawer", {}).get("one_open") == {"true"}   # 서랍은 한 번에 하나만

    start = state
    queue: deque = deque([(start, [])])
    seen = {_key(start)}
    while queue:
        current, path = queue.popleft()
        if len(path) >= max_depth:
            continue
        for name, skill, binding in actions:
            if one_open and name == "open_drawer" and any(
                    v is True for k, v in (current.get("open") or {}).items() if k.startswith("drawer")):
                continue                        # 다른 서랍이 열려 있으면 열지 않음 (먼저 닫는 계획만)
            if not all(c["pass"] for c in ontology.check(current, skill.get("pre", []), binding)):
                continue
            nxt, _ = ontology.apply(current, skill.get("effect", []), binding)
            k = _key(nxt)
            if k in seen:
                continue
            seen.add(k)
            new_path = [*path, (name, skill, binding)]
            if all(_goal_ok(nxt, g) for g in all_goals):
                return PlanResult(PLANNED, _explain(start, new_path, all_goals), all_goals, explored=len(seen))
            if len(seen) >= MAX_STATES:
                return PlanResult(UNPLANNABLE, [], all_goals,
                                  f"탐색 상한({MAX_STATES} 상태)을 넘음", explored=len(seen))
            queue.append((nxt, new_path))
    within = " (지원 범위 안에서)" if limits else ""
    return PlanResult(UNPLANNABLE, [], all_goals,
                      f"깊이 {max_depth} 안에서{within} 목표를 모두 만족하는 스킬 순서가 없음: "
                      + ", ".join(_goal_text(g) for g in all_goals), explored=len(seen))


def _check_goals(goals: Any, onto: dict) -> str:
    """형식·이름 확인. 문제가 있으면 설명, 없으면 ''."""
    if not isinstance(goals, list) or not goals:
        return "목표가 없음"
    world = onto.get("world", {})
    known = set(world.get("items", {})) | set(world.get("places", {})) | {ROBOT}
    places = set(world.get("places", {})) | {GRIPPER}
    for g in goals:
        if not isinstance(g, dict) or not all(isinstance(g.get(k), (str, bool)) for k in ("predicate", "subject")) \
                or "value" not in g:
            return f"목표 형식 오류: {g!r}"
        if g["subject"] not in known:
            return f"모르는 대상: {g['subject']}"
        if g["predicate"] == "located_in" and g["value"] not in places:
            return f"모르는 장소: {g['value']}"
    return ""


def _unreachable(goals: list[dict], skills: dict) -> str:
    """어떤 스킬 effect 도 바꾸지 못하는 술어를 목표로 하면 바로 원인 반환."""
    produced = {e["predicate"] for s in skills.values() if isinstance(s, dict) and s.get("kind") == "primitive"
                for e in s.get("effect", [])}
    missing = sorted({g["predicate"] for g in goals} - produced)
    return f"어떤 스킬도 바꾸지 못하는 상태: {', '.join(missing)}" if missing else ""


# ---- 단계별 근거 ----

def _explain(start: dict, path: list[tuple[str, dict, dict]], goals: list[dict]) -> list[Step]:
    """각 스텝의 effect 가 뒤 스텝의 조건이나 목표를 만족시키는지 찾아 이유로 적는다."""
    states = [start]
    diffs = []
    for _, skill, binding in path:
        nxt, diff = ontology.apply(states[-1], skill.get("effect", []), binding)
        states.append(nxt)
        diffs.append(diff)
    steps = []
    for i, ((name, skill, binding), diff) in enumerate(zip(path, diffs)):
        reasons = []
        for key, (_, after) in diff.items():
            predicate, _, subject = key.partition(".")
            for j in range(i + 1, len(path)):
                later_name, later_skill, later_binding = path[j]
                used = [c for c in ontology.check(states[j], later_skill.get("pre", []), later_binding)
                        if c["predicate"] == predicate and c["subject"] == subject and c["value"] == after]
                if used:
                    reasons.append(f"{j + 1}번 {later_name} 의 조건 {key} = {json.dumps(after, ensure_ascii=False)}")
                    break
            else:
                for g in goals:
                    if g["predicate"] == predicate and g["subject"] == subject and g["value"] == after:
                        kind = "자동 목표(연 서랍 닫기)" if g.get("auto") else "목표"
                        reasons.append(f"{kind} {_goal_text(g)}")
        steps.append(Step(name, dict(binding), reasons))
    return steps


def describe(result: PlanResult) -> list[str]:
    """사람이 읽는 줄 (로그·화면·#150 시험 기록용)."""
    if result.status != PLANNED:
        return [f"{result.status}: {result.reason}"]
    return [f"{n}. {s.label()} — " + ("; ".join(s.reasons) or "(근거 없음)")
            for n, s in enumerate(result.steps, 1)]


# ---- 계획 → 태스크 JSON (docs/runner.md 7.2) ----

def to_task(result: PlanResult, task_id: str = "plan", timeouts: dict[str, float] | None = None) -> dict:
    """PLANNED 결과를 Runner 태스크로. 스텝 ID p1..pn, 단계별 근거는 description 에.
    finally 는 find_item 과 같은 안전 규칙: **계획이 끝나지 못했을 때만** 이번 계획이 연 서랍 닫기(skip — 이미 닫혔거나
    쥔 채면 PRE_UNMET 로 건너뜀), 그리퍼가 비어 있을 때만 홈 (물품을 쥔 채면 정지·사람 복구, PR #82).
    성공하면 서랍은 계획대로 둔다 — 자동 목표 서랍은 계획 안에서 이미 닫혔고, "열어 둬" 같은 명시 목표는 지킨다
    (#151 D·E 리뷰 P1: 성공 뒤 finally 가 명시적 열림 목표를 다시 닫던 것). 끝났는지는 마지막 스텝의 plan_done 으로.
    timeouts: 스킬 이름 → timeout_sec (없으면 넣지 않음 — 실물은 호출하는 쪽이 설정에서 넘김)."""
    if result.status != PLANNED:
        raise ValueError(f"PLANNED 가 아닌 결과는 태스크로 만들지 않음: {result.status}")
    timeouts = timeouts or {}
    sequence = [{"id": "p0", "action": "set_var", "params": {"name": "plan_done", "value": False}}]
    for n, s in enumerate(result.steps, 1):
        step = {"id": f"p{n}", "skill": s.skill, "params": dict(s.params)}
        if s.skill in timeouts:
            step["timeout_sec"] = timeouts[s.skill]
        sequence.append(step)
    sequence.append({"id": f"p{len(result.steps) + 1}", "action": "set_var",
                     "params": {"name": "plan_done", "value": True}})
    opened = sorted({s.params.get("drawer_id") for s in result.steps if s.skill == "open_drawer"} - {None})
    final = [{"id": "f1", "action": "query_ontology", "params": {"state": "gripper.robot"}, "output": "hold"},
             # 일반 실패면 정리(닫기·홈) 전에 원인 한 문장 — Runner 가 finally 시작 때 넣는 run_failure (정지·취소·성공이면 null, E #196 10/14)
             {"id": "fx", "action": "if", "on_failure": "skip", "cond": {"op": "!=", "args": ["$run_failure", None]},
              "then": [{"id": "fx.1", "action": "speak", "params": {"text": "$run_failure.text"}, "on_failure": "skip",
                        "timeout_sec": 20}]}]
    closes = []
    for n, drawer in enumerate(opened, 1):
        step = {"id": f"fc.{n}", "skill": "close_drawer", "params": {"drawer_id": drawer}, "on_failure": "skip"}
        if "close_drawer" in timeouts:
            step["timeout_sec"] = timeouts["close_drawer"]
        closes.append(step)
    if closes:                                  # 계획이 끝나지 못했을 때만 연 서랍 정리
        final.append({"id": "fc", "action": "if", "cond": {"op": "==", "args": ["$plan_done", False]},
                      "then": closes})
    home = {"id": "fh.1", "action": "move_to_named_pose", "params": {"pose_name": "home"}}
    if "move_to_named_pose" in timeouts:
        home["timeout_sec"] = timeouts["move_to_named_pose"]
    final.append({"id": "fh", "action": "if", "cond": {"op": "==", "args": ["$hold.value", "empty"]},
                  "then": [home],
                  "else": [{"id": "fh.2", "action": "set_var",
                            "params": {"name": "stopped_holding", "value": "물품을 쥔 채 정지 — 홈 이동 안 함, 사람 복구"}}]})
    goals = ", ".join(_goal_text(g) for g in result.goals if not g.get("auto"))
    return {"task_id": task_id,
            "description": f"플래너 계획 (FR-PLN-02, #150) 목표 {goals} — " + " / ".join(describe(result)),
            "sequence": sequence, "finally": final}
