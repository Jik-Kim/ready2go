"""계약 W3 (#152, 이름 E 동의 10/13 — 필드는 E 포함 2명 승인 전): 제어 인텐트별 필수 칸.
예시 contracts/examples/intent_{recover,resume_register,resume_answer,resume_request,end_task}.json 은 통과하고,
필수 칸이 빠지면 스키마에서 거절. 일반 요청(find_item)은 새 칸 없이 그대로 통과."""
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "contracts/intent.schema.json").read_text(encoding="utf-8"))
EX = {n: json.loads((ROOT / f"contracts/examples/intent_{n}.json").read_text(encoding="utf-8"))
      for n in ("recover", "resume_register", "resume_answer", "resume_request", "end_task", "find_item")}


def valid(doc):
    return not list(jsonschema.Draft7Validator(SCHEMA).iter_errors(doc))


def test_examples_pass_and_general_request_unchanged():
    assert all(valid(d) for d in EX.values())
    assert valid({"intent": "find_item", "targets": ["eraser"], "confidence": 0.9})   # 새 칸 없는 기존 요청


@pytest.mark.parametrize("name,drop", [
    ("recover", "boot_id"), ("recover", "event_id"), ("recover", "request_id"),
    ("resume_register", "question_id"), ("resume_register", "event_id"), ("resume_register", "run_id"),
    ("resume_answer", "question_id"), ("resume_answer", "answer"), ("resume_answer", "evidence"), ("resume_answer", "run_id"),
    ("resume_request", "phase"), ("resume_request", "request_id"), ("resume_request", "evidence"), ("resume_request", "run_id"),
    ("end_task", "run_id"), ("end_task", "boot_id"), ("end_task", "request_id"),
])
def test_missing_required_field_is_rejected(name, drop):
    doc = {k: v for k, v in EX[name].items() if k != drop}
    assert not valid(doc), (name, drop)


def test_answer_kinds_and_evidence_rules():
    base = {k: v for k, v in EX["resume_answer"].items() if k != "evidence"}
    assert valid({**base, "answer": "decline"})                          # "아니" — 증빙 없이 (작업 보존)
    assert not valid({**base, "answer": "expired"})                      # 자동 종료는 이유 필수
    assert valid({**base, "answer": "expired", "answer_reason": "tts_failed"})
    assert not valid({**EX["resume_answer"], "evidence": {"stt_s": 1.0}})          # resume 증빙 칸 누락
    assert not valid({**EX["resume_answer"], "evidence": {**EX["resume_answer"]["evidence"], "stt_s": -1}})
    register = {k: v for k, v in EX["resume_request"].items() if k != "evidence"}
    assert valid({**register, "phase": "register"})                      # 등록 단계는 증빙 없이
