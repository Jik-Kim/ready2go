import re
from datetime import datetime, timezone

from ready2go_runner.core.log_records import new_run_id, run_document, step_document, utc_iso

WHEN = datetime(2026, 10, 3, 5, 40, 12, 345678, tzinfo=timezone.utc)


def test_utc_iso_format():
    assert utc_iso(WHEN) == "2026-10-03T05:40:12.345Z"                  # 계약 예시와 같은 모양
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", utc_iso())


def test_run_id_is_readable_and_unique():
    a, b = new_run_id(WHEN), new_run_id(WHEN)
    assert a.startswith("2026-10-03T05:40:12Z_") and len(a) == len("2026-10-03T05:40:12Z_") + 6
    assert a != b                                                          # 같은 초에 시작해도 다름


def test_run_document_start_and_end():
    started = run_document("r1", "find_visible", {"target": "watch", "stt_text": "시계 찾아줘"},
                           "2026-10-03T05:40:12.345Z", extra={"backend": "mock"})
    assert started == {"run_id": "r1", "task_id": "find_visible",
                       "inputs": {"target": "watch", "stt_text": "시계 찾아줘"},   # FR-LOG-01 입력 명령
                       "started_at": "2026-10-03T05:40:12.345Z", "backend": "mock"}

    ended = run_document("r1", "find_visible", {"target": "watch"}, "2026-10-03T05:40:12.345Z",
                         ended_at="2026-10-03T05:41:02.000Z", total_duration_sec=49.7,
                         overall_status="FAILED", error_code="GRASP_FAILED", failed_step="s3")
    assert ended["overall_status"] == "FAILED"
    assert ended["error"] == {"code": "GRASP_FAILED"}                     # 계약 예시의 error.code
    assert ended["failed_step"] == "s3"
    assert "problems" not in ended


def test_run_document_completed_has_no_error():
    doc = run_document("r1", "t", {}, "x", ended_at="y", total_duration_sec=1.0, overall_status="COMPLETED")
    assert "error" not in doc and "failed_step" not in doc


def test_step_document_from_runner_record():
    record = {"id": "s3", "action": "pick_object", "attempts": 2, "params": {"object_id": "watch#1"},
              "started_at": "2026-10-03T05:40:20.000Z", "duration_sec": 4.2,
              "output": {"grasp_ok": True}, "status": "SUCCESS"}
    assert step_document("r1", 2, record) == {
        "run_id": "r1", "seq": 2, "id": "s3", "action": "pick_object", "attempts": 2,
        "params": {"object_id": "watch#1"}, "started_at": "2026-10-03T05:40:20.000Z",
        "duration_sec": 4.2, "result": {"grasp_ok": True}, "status": "SUCCESS"}   # output → result


def test_step_document_errors():
    failed = step_document("r1", 0, {"id": "s1", "action": "drawer_control", "status": "FAILURE",
                                      "error_code": "DRAWER_STUCK"})
    assert failed["error"] == {"code": "DRAWER_STUCK"} and "error_code" not in failed

    internal = step_document("r1", 1, {"id": "s2", "action": "set_var", "status": "FAILURE",
                                       "error_code": "INTERNAL_ERROR", "internal_error": "TypeError: x"})
    assert internal["error"] == {"code": "INTERNAL_ERROR", "message": "TypeError: x"}

    skipped = step_document("r1", 2, {"id": "f1", "action": "drawer_control", "status": "SKIPPED",
                                      "skipped_reason": "ABORTED"})
    assert "error" not in skipped and skipped["skipped_reason"] == "ABORTED"


def test_step_document_does_not_change_runner_record():
    record = {"id": "s1", "action": "speak", "status": "FAILURE", "error_code": "ACTION_FAILED"}
    step_document("r1", 0, record)
    assert record == {"id": "s1", "action": "speak", "status": "FAILURE", "error_code": "ACTION_FAILED"}
