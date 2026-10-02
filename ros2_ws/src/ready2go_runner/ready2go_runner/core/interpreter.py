"""JSON 태스크 해석기 — docs/runner.md 7.1~7.3.

Phase 1 범위: sequence, if, set_var, retry, timeout_sec, finally, 변수($ref·{{}} 보간·조사 필터),
스킬 실행 전 pre 확인 → 실행 → effect 반영(ready2go_knowledge.core.ontology), 스텝 로그(LogStore).
Phase 2: while · for_each · push/pop · recovery · fallback · on_halt, verify/post_check, state_diff 로그.

Runner 는 원자 동작을 직접 실행하지 않는다. 생성 시 받은 execute(action, params) → ActionResult 로
위임하며, #10 에서 ROS 액션 클라이언트(real·sim·mock 백엔드)가 이 자리에 들어간다.
"""
# TODO(C 이영훈): #9 남은 단계 — if, on_failure/retry, finally, timeout_sec, 실행 전 스키마 검증.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .variables import BadFilter, VarUndefined, resolve


@dataclass
class ActionResult:
    """원자 동작 결과. ICD Skill 액션 result(success, error_code, output_json)와 같은 구성."""
    success: bool
    output: Any = None
    error_code: str | None = None


@dataclass
class RunResult:
    overall_status: str                 # COMPLETED / FAILED
    blackboard: dict
    steps: list[dict] = field(default_factory=list)
    error_code: str | None = None       # FAILED 일 때 원인 코드


Execute = Callable[[str, dict], ActionResult]


class StepFailed(Exception):
    def __init__(self, step_id: str, code: str):
        super().__init__(f"{step_id}: {code}")
        self.step_id, self.code = step_id, code


class Runner:
    def __init__(self, execute: Execute):
        self.execute = execute

    def run(self, task: dict, inputs: dict | None = None) -> RunResult:
        """태스크를 실행한다. inputs 는 태스크 기본 inputs 를 덮어쓴다(음성 인텐트 바인딩)."""
        blackboard = {"inputs": {**task.get("inputs", {}), **(inputs or {})}}
        records: list[dict] = []
        try:
            self._run_steps(task["sequence"], blackboard, records)
        except StepFailed as e:
            return RunResult("FAILED", blackboard, records, e.code)
        return RunResult("COMPLETED", blackboard, records)

    def _run_steps(self, steps: list[dict], blackboard: dict, records: list[dict]) -> None:
        for step in steps:
            self._run_step(step, blackboard, records)

    def _run_step(self, step: dict, blackboard: dict, records: list[dict]) -> None:
        record = {"id": step["id"], "action": step["action"]}
        records.append(record)
        try:
            self._dispatch(step, blackboard, record)
        except StepFailed as e:
            record.update(status="FAILURE", error_code=e.code)
            raise
        record["status"] = "SUCCESS"

    def _dispatch(self, step: dict, blackboard: dict, record: dict) -> None:
        action = step["action"]
        try:
            params = resolve(step.get("params", {}), blackboard)
        except (VarUndefined, BadFilter) as e:
            raise StepFailed(step["id"], e.code) from e
        record["params"] = params

        if action == "set_var":
            blackboard[params["name"]] = params.get("value")
            return

        result = self.execute(action, params)
        if not result.success:
            raise StepFailed(step["id"], result.error_code or "ACTION_FAILED")
        record["output"] = result.output
        if "output" in step:
            blackboard[step["output"]] = result.output
