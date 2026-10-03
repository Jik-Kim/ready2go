"""실행 로그 레코드 형식 — docs/runner.md 7.4, FR-LOG-01, contracts/examples/execution_log.json.

MongoDB(runs·steps 컬렉션)와 JSONL 폴백이 **같은 형식**을 쓰도록 레코드 모양을 한곳에서 만든다.
- runs: 실행 1건 = 문서 1개 (실행 ID·입력 명령·시작 시각·실행 상태·오류 코드)
- steps: 스텝 1개 = 문서 1개 (실행 ID·단계 ID·시작 시각·상태·오류 코드)
키 이름은 계약 예시를 따른다: 오류 `error.code`, 동작 결과 `result`, 시각은 UTC ISO 8601(`Z`).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

# Runner 스텝 기록(interpreter.py)의 키 → 로그 레코드 키. 나머지는 그대로 옮긴다.
_RENAMED = {"output": "result"}
_ERROR_KEYS = ("error_code", "internal_error")


def utc_iso(when: datetime | None = None) -> str:
    """UTC ISO 8601, 밀리초까지 (예: 2026-10-03T05:40:12.345Z)."""
    when = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def new_run_id(when: datetime | None = None) -> str:
    """실행 ID: 시작 시각(초) + 짧은 난수. 사람이 읽기 쉽고 동시에 시작해도 겹치지 않음."""
    when = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ") + "_" + uuid.uuid4().hex[:6]


def _error(code: str | None, message: str | None = None) -> dict | None:
    if code is None:
        return None
    return {"code": code, **({"message": message} if message else {})}


def run_document(run_id: str, task_id: str, inputs: dict, started_at: str, *,
                 ended_at: str | None = None, total_duration_sec: float | None = None,
                 overall_status: str | None = None, error_code: str | None = None,
                 failed_step: str | None = None, problems: list[str] | None = None,
                 extra: dict | None = None) -> dict:
    """runs 레코드. 시작 시점에는 상태 없이 만들고, 끝나면 같은 함수로 완성본을 만든다.
    extra: backend·STT 원문·LLM 응답 등 헤더에 덧붙일 값 (runner.md 7.4)."""
    doc = {"run_id": run_id, "task_id": task_id, "inputs": inputs, "started_at": started_at,
           **(extra or {})}
    if overall_status is not None:
        doc.update(ended_at=ended_at, total_duration_sec=total_duration_sec, overall_status=overall_status)
        if error_code is not None:
            doc["error"] = _error(error_code)
            doc["failed_step"] = failed_step
        if problems:
            doc["problems"] = problems
    return doc


def step_document(run_id: str, seq: int, record: dict) -> dict:
    """Runner 스텝 기록 1개를 steps 레코드로. seq 는 실행 안에서의 순서(0부터)."""
    doc = {"run_id": run_id, "seq": seq}
    for key, value in record.items():
        if key in _ERROR_KEYS:
            continue
        doc[_RENAMED.get(key, key)] = value
    error = _error(record.get("error_code"), record.get("internal_error"))
    if error:
        doc["error"] = error
    return doc
