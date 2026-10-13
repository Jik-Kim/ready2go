"""/runner/status 메시지 내용 (ROS 비의존) — docs/interfaces.md "Runner 상태" (std_msgs/String JSON, #10).

phase: idle(대기) / running(실행 중) / halted(중단 잠김 — 사람이 확인 후 재개 전까지 새 태스크 거절)
halt: 정지 사건 요약 (계약안 — #152·#187·FR-SAF-01, E 포함 2명 승인 전). 잠김·재개 대기일 때만, 아니면 null.
  정지를 요청해도 실행은 진행 중이던 동작의 최종 결과를 받을 때까지 running 이므로, 요청(stop "requested")과
  실제 정지 확인(stop "confirmed"·"unconfirmed"·"none")을 이 칸으로 구분한다 — Runner.halt_summary.
"""
from __future__ import annotations

from .interpreter import RunResult

IDLE, RUNNING, HALTED = "idle", "running", "halted"


def build_status(running: bool, halted: bool, halt_code: str | None, task_id: str | None,
                 current_step: str | None, last: RunResult | None, last_task_id: str | None,
                 log_degraded: bool, halt: dict | None = None) -> dict:
    status = {
        "phase": RUNNING if running else HALTED if halted else IDLE,
        "task_id": task_id if running else None,
        "current_step": current_step if running else None,
        "halt_code": halt_code if halted else None,
        "log_store": "jsonl" if log_degraded else "mongo",    # DB 장애로 파일에 기록 중이면 jsonl
        "last": None,
        "halt": halt,
    }
    if last is not None:
        status["last"] = {"task_id": last_task_id, "run_id": last.run_id, "overall_status": last.overall_status,
                          "error_code": last.error_code, "failed_step": last.failed_step,
                          "problems": last.problems, "log_errors": last.log_errors}
    return status
