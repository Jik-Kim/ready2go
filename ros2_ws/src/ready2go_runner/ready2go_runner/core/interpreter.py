"""JSON 태스크 해석기 — docs/runner.md 7.1~7.3.

Phase 1 범위: sequence, if, set_var, retry, timeout_sec, finally, 변수($ref·{{}} 보간·조사 필터),
스킬 실행 전 pre 확인 → 실행 → effect 반영(ready2go_knowledge.core.ontology), 스텝 로그(LogStore).
Phase 2: while · for_each · push/pop · recovery · fallback · on_halt, verify/post_check, state_diff 로그.

Runner 는 원자 동작을 직접 실행하지 않는다. 생성 시 받은 execute(action, params, timeout_sec) → ActionResult
로 위임하며, #10 에서 ROS 액션 클라이언트(real·sim·mock 백엔드)가 이 자리에 들어간다.
timeout_sec 이 지나면 동작을 취소하는 것은 백엔드 책임이고, Runner 는 걸린 시간을 재서 초과하면 TIMEOUT 으로 판정한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .conditions import BadCondition, evaluate
from .validation import TASK_INVALID, check_task
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
    failed_step: str | None = None      # FAILED 일 때 실패한 스텝 ID
    problems: list[str] = field(default_factory=list)   # TASK_INVALID 일 때 실행 전 검사 문제 목록


Execute = Callable[[str, dict, "float | None"], ActionResult]   # (action, params, timeout_sec)

SAFE_HOME_POSE = "home"                 # on_failure: safe_home 이 이동할 기준 포즈 (docs/runner.md 7.1)


class StepFailed(Exception):
    def __init__(self, step_id: str, code: str):
        super().__init__(f"{step_id}: {code}")
        self.step_id, self.code = step_id, code


class Runner:
    def __init__(self, execute: Execute, schema: dict | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.execute = execute
        self.schema = schema                    # contracts/task.schema.json 내용 (노드가 읽어서 전달)
        self.clock = clock                      # 소요 시간·timeout 측정용 (테스트에서 가짜 시계 주입)

    def run(self, task: dict, inputs: dict | None = None) -> RunResult:
        """태스크를 실행한다. inputs 는 태스크 기본 inputs 를 덮어쓴다(음성 인텐트 바인딩)."""
        blackboard = {"inputs": {**task.get("inputs", {}), **(inputs or {})}}
        problems = check_task(task, self.schema)
        if problems:                            # 로봇을 움직이기 전에 거절 (finally 도 실행하지 않음)
            return RunResult("FAILED", blackboard, [], TASK_INVALID, problems=problems)
        records: list[dict] = []
        error: StepFailed | None = None
        try:
            self._run_steps(task["sequence"], blackboard, records)
        except StepFailed as e:
            error = e
        # finally 는 sequence 가 성공·실패 어느 쪽으로 끝나도 실행 (복구·서랍 닫기·홈 복귀)
        # TODO(C 이영훈): #10 E-stop 연결 시 ABORTED 이면 finally 의 로봇 동작을 실행하지 않음 (docs/runner.md 7.1)
        try:
            self._run_steps(task.get("finally", []), blackboard, records)
        except StepFailed as e:
            error = error or e                  # 둘 다 실패하면 처음(sequence) 원인을 남김
        if error:
            return RunResult("FAILED", blackboard, records, error.code, error.step_id)
        return RunResult("COMPLETED", blackboard, records)

    def _run_steps(self, steps: list[dict], blackboard: dict, records: list[dict]) -> None:
        for step in steps:
            self._run_step(step, blackboard, records)

    def _run_step(self, step: dict, blackboard: dict, records: list[dict]) -> None:
        """스텝 하나를 실행하고 on_failure 정책(abort·retry·skip·safe_home)을 적용."""
        record = {"id": step["id"], "action": step["action"]}
        records.append(record)
        policy = step.get("on_failure", "abort")
        max_attempts = 1 + (step.get("retry", 0) if policy == "retry" else 0)
        started = self.clock()

        for attempt in range(1, max_attempts + 1):
            record["attempts"] = attempt
            try:
                self._dispatch(step, blackboard, record, records, self.clock())
            except StepFailed as e:
                failure = e
                continue
            finally:
                record["duration_sec"] = round(self.clock() - started, 3)   # 재시도 포함 전체 시간
            record["status"] = "SUCCESS"
            return

        record.update(status="FAILURE", error_code=failure.code)
        if policy == "skip":
            record["on_failure"] = "skip"
            return
        if policy == "safe_home":
            self._safe_home(step, records)
        raise failure

    def _safe_home(self, step: dict, records: list[dict]) -> None:
        """실패 후 홈 포즈로 이동. 이동 결과도 기록하되, 실패해도 원래 실패로 중단한다."""
        params = {"pose_name": SAFE_HOME_POSE}
        record = {"id": f"{step['id']}.safe_home", "action": "move_to_named_pose", "params": params}
        records.append(record)
        try:
            result = self.execute("move_to_named_pose", params, None)
        except Exception:
            result = ActionResult(False, error_code="BACKEND_ERROR")
        record["status"] = "SUCCESS" if result.success else "FAILURE"
        if not result.success:
            record["error_code"] = result.error_code or "ACTION_FAILED"

    def _check_timeout(self, step: dict, attempt_started: float) -> None:
        timeout = step.get("timeout_sec")
        if timeout is not None and self.clock() - attempt_started > timeout:
            raise StepFailed(step["id"], "TIMEOUT")

    def _dispatch(self, step: dict, blackboard: dict, record: dict, records: list[dict],
                  attempt_started: float) -> None:
        action = step["action"]
        if action == "if":
            self._run_if(step, blackboard, record, records)
            self._check_timeout(step, attempt_started)    # 블록은 취소할 수 없어 끝난 뒤 판정
            return
        try:
            params = resolve(step.get("params", {}), blackboard)
        except (VarUndefined, BadFilter) as e:
            raise StepFailed(step["id"], e.code) from e
        record["params"] = params

        if action == "set_var":
            blackboard[params["name"]] = params.get("value")
            return

        try:
            result = self.execute(action, params, step.get("timeout_sec"))
        except Exception as e:                  # 통신 끊김 등 백엔드 예외도 스텝 실패로 처리해 finally 를 보장
            raise StepFailed(step["id"], "BACKEND_ERROR") from e
        if not result.success:
            raise StepFailed(step["id"], result.error_code or "ACTION_FAILED")
        self._check_timeout(step, attempt_started)        # 늦게 성공한 결과는 쓰지 않음
        record["output"] = result.output
        if "output" in step:
            blackboard[step["output"]] = result.output

    def _run_if(self, step: dict, blackboard: dict, record: dict, records: list[dict]) -> None:
        """cond 가 참이면 then, 거짓이면 else 를 실행. 자식 스텝 기록은 if 기록 뒤에 이어진다."""
        try:
            taken = evaluate(step["cond"], blackboard)
        except (BadCondition, VarUndefined, BadFilter) as e:
            raise StepFailed(step["id"], e.code) from e
        branch = "then" if taken else "else"
        record["branch"] = branch
        self._run_steps(step.get(branch, []), blackboard, records)
