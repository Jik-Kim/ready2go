"""묶음 스킬이 들어간 계획 실행 (ROS 비의존) — #302 E 결정 10/15 (사용자 승인, C 권고 2안).

플래너(`planner.plan(..., composites=True)`)가 묶음 스킬(handover_with_unpack — 안은 find_with_unpack)과 primitive 를
조합한 계획을 구간으로 나눠 실행한다. 문장별 고정 순서가 아니라 매 구간 뒤 **실제 Runner 상태**에서 다시 계획한다.

- 구간: 계획 맨 앞이 묶음이면 그 묶음 하나 = 지정 태스크(`task`) 단독 실행(`{"target": ...}`), 아니면 다음 묶음 전까지의
  primitive 들 = 기존 `planner.to_task` 한 번. 구간이 끝나면 실제 상태로 다시 계획(앞 계획의 나머지를 믿지 않음).
- 목표: 처음 목표 + **처음 상태 기준 자동 닫힘 목표**를 끝까지 유지(구간마다 다시 계산하지 않음).
- plan_effect 는 실제 상태에 쓰지 않음 — 상태는 태스크 안 pick/place 등의 검증된 effect 로만 바뀜. 묶음이 COMPLETED 여도
  실제 상태가 plan_effect 를 만족하지 않으면 다음 구간으로 가지 않음(`PLAN_EFFECT_UNMET`).
- 실패·정지·복구 실패면 후속 구간을 보내지 않음 — #371 item_group 규칙 재사용: 도는 동안 재개 보존(`resumable`) 끔
  (구간 실행이 SUSPENDED 로 남지 않게, 정지 잠금은 유지), 복구 실패 표식(`task_error RESTORE_INCOMPLETE`·`restore_failed`)이면 중단.
  전달 뒤 후속 목표 실패는 전달 상태·기록 그대로 두고 전체 FAILED + 그 코드. 묶음 안 재개 확대 없음.
- 끝없이 돌지 않음: 같은 상태로 다시 계획하게 되면(상태 변화 없음) `PLAN_NO_PROGRESS`, 구간 수 상한 `max_rounds`.

노드 연결(#302 C 설계·E 동의 10/15): 요청 하나 = 상위 run_id(R) 하나 — 구간(child) 실행은 `R.1`, `R.2` … 로 따로 기록
(`parent_run_id: R`, 같은 run_id 재사용·덮어쓰기 없음). 첫 수락 안내(`accept_text`)는 첫 구간에만 — 이후 구간은 같은 상위 요청의
후속 안내. 상태 칸·정지 매핑은 노드(nodes/runner_node.py)가 함.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ready2go_knowledge.core import ontology

from . import planner
from .interpreter import Runner
from .item_group import _restore_incomplete
from .intent_router import UNPLANNABLE, add_accept_speak

PLAN_EFFECT_UNMET = "PLAN_EFFECT_UNMET"     # 묶음이 끝났는데 실제 상태가 계획 전용 결과(plan_effect)를 만족하지 않음
PLAN_NO_PROGRESS = "PLAN_NO_PROGRESS"       # 구간 뒤 상태가 그대로라 같은 계획을 반복하게 됨 / 구간 수 상한
MAX_ROUNDS = 6


@dataclass
class Segment:
    kind: str                               # "composite" | "primitive"
    skills: list[str]                       # 구간 스킬 라벨 (예: "handover_with_unpack(eraser, drawer_bottom)")
    plan: list[str]                         # 이 구간을 고른 계획 설명 (planner.describe)
    run_id: str | None = None
    overall_status: str | None = None
    error_code: str | None = None
    failed_step: str | None = None


@dataclass
class PlanRun:
    overall_status: str                     # COMPLETED / FAILED / ABORTED — 기존 값만
    error_code: str | None
    segments: list[Segment] = field(default_factory=list)
    reason: str = ""                        # 끝난 이유 (사람이 읽는 설명)
    failed_step: str | None = None          # 멈춘 구간의 실패 스텝 (상위 결과 last.failed_step)


def _effect_met(state: dict, skill: dict, params: dict) -> bool:
    """묶음 실행 뒤 실제 상태가 계획 전용 결과(plan_effect)를 만족하나 — 성공 표기만으로 다음 구간에 가지 않음."""
    checks = ontology.check(state, [{**r, "op": "=="} for r in skill.get("plan_effect", [])], params)
    return bool(checks) and all(c["pass"] for c in checks)


def run_plan(runner: Runner, onto: dict, goals: list[dict], tasks: Callable[[str], dict],
             limits: dict | None = None, timeouts: dict[str, float] | None = None,
             max_rounds: int = MAX_ROUNDS, run_id: str | None = None, meta: dict | None = None,
             accept_text: str | None = None) -> PlanRun:
    """goals 를 묶음 스킬까지 써서 계획·실행. tasks: 묶음 스킬 task 경로 → 태스크 JSON (노드·시험이 읽어 줌).
    run_id: 상위 실행 ID R — 구간 실행 ID 는 R.1, R.2 … (없으면 Runner 가 새로). meta: 구간 실행 기록 헤더(parent_run_id 붙임).
    accept_text: 첫 구간에만 수락 안내 1회 (묶음이면 태스크 inputs.accept_text, primitive 면 add_accept_speak)."""
    skills = onto.get("skills", {})
    initial_auto = planner._auto_goals(runner.state, onto.get("world", {}), goals)   # 처음 상태 기준 — 끝까지 유지
    all_goals = [*goals, *initial_auto]
    out = PlanRun("FAILED", None)
    seen: set[str] = set()
    resumable = runner.resumable            # 구간 실행이 SUSPENDED 로 남지 않게 (#371 E P2 규칙), 잠금은 그대로
    runner.resumable = False
    try:
        for _ in range(max_rounds):
            if runner.halted:
                out.overall_status, out.error_code, out.reason = "ABORTED", runner.halt_code or "HALTED", "정지 잠금"
                return out
            result = planner.plan(runner.state, onto, all_goals, limits=limits, composites=True)
            lines = planner.describe(result)
            if result.status == planner.SATISFIED:
                out.overall_status, out.error_code, out.reason = "COMPLETED", None, result.reason
                return out
            if result.status != planner.PLANNED:
                out.error_code, out.reason = UNPLANNABLE, result.reason
                return out
            key = planner._key(runner.state)
            if key in seen:                 # 앞 구간이 상태를 바꾸지 못해 같은 상태에서 다시 계획 — 반복하지 않음
                out.error_code, out.reason = PLAN_NO_PROGRESS, "구간 뒤 상태 변화 없음"
                return out
            seen.add(key)

            head = result.steps[0]
            first_segment = not out.segments
            say = {"accept_text": accept_text} if first_segment and accept_text else {}
            child = {"run_id": f"{run_id}.{len(out.segments) + 1}" if run_id else None,
                     "meta": {**(meta or {}), **({"parent_run_id": run_id} if run_id else {})} or None}
            if head.task:                   # 묶음 하나 = 지정 태스크 단독 실행
                seg = Segment("composite", [head.label()], lines)
                run = runner.run(tasks(head.task), {"target": head.params.get("target"), **say}, **child)
            else:                           # 다음 묶음 전까지 primitive = 기존 to_task 한 번
                prefix = []
                for s in result.steps:
                    if s.task:
                        break
                    prefix.append(s)
                seg = Segment("primitive", [s.label() for s in prefix], lines)
                partial = planner.PlanResult(planner.PLANNED, prefix, result.goals)
                first = goals[0]
                task = planner.to_task(partial, f"plan_{first['subject']}_{first['value']}".lower(), timeouts)
                run = runner.run(add_accept_speak(task, say) if say else task, say or None, **child)
            seg.run_id, seg.overall_status, seg.error_code, seg.failed_step = \
                run.run_id, run.overall_status, run.error_code, run.failed_step
            out.failed_step = run.failed_step
            out.segments.append(seg)

            if run.overall_status in ("ABORTED", "SUSPENDED"):
                out.overall_status, out.error_code, out.reason = "ABORTED", run.error_code, f"{seg.skills[0]} 중 정지"
                return out
            if _restore_incomplete(run):    # 허용 코드여도 정리(복구)가 실패했으면 후속 구간 안 함
                out.error_code, out.reason = "RESTORE_INCOMPLETE", f"{seg.skills[0]} 복구 실패"
                return out
            if run.overall_status != "COMPLETED":
                out.error_code, out.reason = run.error_code, f"{seg.skills[0]} 실패"
                return out
            if head.task and not _effect_met(runner.state, skills.get(head.skill, {}), head.params):
                out.error_code, out.reason = PLAN_EFFECT_UNMET, f"{seg.skills[0]} 뒤 실제 상태가 계획 결과와 다름"
                return out
        # 구간 상한 — 루프 첫머리와 같이 정지부터 (#373 E 재리뷰: 마지막 구간 직후 정지를 PLAN_NO_PROGRESS 로 오기록)
        if runner.halted:
            out.overall_status, out.error_code, out.reason = "ABORTED", runner.halt_code or "HALTED", "정지 잠금"
            return out
        # 마지막 구간이 목표를 다 이뤘으면 성공 (#373 E 리뷰: 마지막 허용 구간 성공을 PLAN_NO_PROGRESS 로 오기록)
        if planner.plan(runner.state, onto, all_goals, limits=limits, composites=True).status == planner.SATISFIED:
            out.overall_status, out.error_code, out.reason = "COMPLETED", None, "목표 만족"
            return out
        out.error_code, out.reason = PLAN_NO_PROGRESS, f"구간 {max_rounds}개 안에 목표를 다 만족하지 못함"
        return out
    finally:
        runner.resumable = resumable
