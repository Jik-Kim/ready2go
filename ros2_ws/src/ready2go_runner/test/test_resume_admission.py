"""재개 질문·답·독립 요청 접수 (#152·#271 계약 W3, requirements resume-admission-policy)."""
from pathlib import Path

import pytest
import yaml

from ready2go_runner.core import resume_admission as ra

SRC = Path(__file__).resolve().parents[2]
RESUME_FILE, VOICE_FILE = SRC / "ready2go_runner/params/resume.yaml", SRC / "ready2go_voice/params/voice.yaml"
ANSWER_EV = {"rec_start_after_tts_s": 0.4, "rec_end_after_tts_s": 2.1, "request_after_tts_s": 2.3, "stt_s": 1.2}
REQUEST_EV = {"rec_end_s": 1.8, "request_s": 2.0, "stt_s": 1.1}


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def adm():
    clock = Clock()
    a = ra.ResumeAdmission(clock, ra.load_limits(str(RESUME_FILE), str(VOICE_FILE)))
    a.clock_ = clock
    return a


def test_limits_read_c_file_and_e_original_without_copying():
    limits = ra.load_limits(str(RESUME_FILE), str(VOICE_FILE))
    voice = yaml.safe_load(VOICE_FILE.read_text(encoding="utf-8"))
    assert limits["admission_window_sec"] == voice["resume_admission_window_sec"]          # E 원본 그대로
    assert limits["independent_request_timeout_sec"] == voice["resume_independent_request_timeout_sec"]
    assert (limits["question_offer_sec"], limits["question_answer_sec"], limits["request_sec"]) == (30.0, 60.0, 10.0)
    assert "[팀 확정 필요]" in RESUME_FILE.read_text(encoding="utf-8")


def test_evidence_order_bounds_and_missing_fields():
    limits = ra.load_limits(str(RESUME_FILE), str(VOICE_FILE))
    assert ra.evidence_ok("answer", ANSWER_EV, limits) and ra.evidence_ok("request", REQUEST_EV, limits)
    assert ra.evidence_ok("answer", {**ANSWER_EV, "request_after_tts_s": 10.0}, limits)          # 10.0 포함
    assert not ra.evidence_ok("answer", {**ANSWER_EV, "request_after_tts_s": 10.01}, limits)
    assert not ra.evidence_ok("answer", {**ANSWER_EV, "rec_start_after_tts_s": 2.2}, limits)      # 녹음 시작 > 끝
    assert not ra.evidence_ok("answer", {**ANSWER_EV, "stt_s": 15.0}, limits)                    # 15 s 그 값이면 거절 (E 와 같음)
    assert ra.evidence_ok("answer", {**ANSWER_EV, "stt_s": 14.99}, limits)
    assert not ra.evidence_ok("answer", {k: v for k, v in ANSWER_EV.items() if k != "stt_s"}, limits)
    assert not ra.evidence_ok("answer", {**ANSWER_EV, "stt_s": True}, limits)
    assert not ra.evidence_ok("request", {**REQUEST_EV, "rec_end_s": 2.5}, limits)
    assert not ra.evidence_ok("request", None, limits)


def test_question_register_once_resend_and_answer_resume(adm):
    assert adm.register_question("h1", "r1", "q-01", offered=False) == ra.NOT_OFFERED
    assert adm.register_question("h1", "r1", "q-01", offered=True) is None
    first = adm.view("h1", "r1")["question"]
    adm.clock_.t += 20
    assert adm.register_question("h1", "r1", "q-01", offered=False) is None          # 재전송: 그대로, 기한 연장 없음
    assert adm.view("h1", "r1")["question"] == first and adm.view("h1", "r1")["remaining"] == pytest.approx(40.0)
    assert adm.register_question("h1", "r1", "q-02", offered=True) == ra.QUESTION_MISMATCH   # 사건당 1개
    assert adm.answer("h1", "r1", "q-01", "resume", {**ANSWER_EV, "stt_s": 99}) == ra.EVIDENCE_INVALID
    assert adm.answer("h1", "r1", "q-01", "resume", ANSWER_EV) is None                 # 증빙 틀린 답은 소비 안 함
    adm.settle("h1", "r1", resumed=True)
    assert adm.view("h1", "r1")["question"]["state"] == "resumed"
    assert adm.answer("h1", "r1", "q-01", "resume", ANSWER_EV) == ra.QUESTION_CLOSED   # 첫 유효 답 1개만


def test_decline_and_expiry_close_question_only_then_independent_request(adm):
    adm.register_question("h1", "r1", "q-01", offered=True)
    assert adm.register_request("h1", "r1", "req-1", unlocked=True) == ra.QUESTION_PENDING
    assert adm.answer("h1", "r1", "q-01", "decline", None) is None
    assert adm.view("h1", "r1")["question"]["state"] == "declined"
    assert adm.register_request("h1", "r1", "req-1", unlocked=False) == ra.NOT_RECOVERED
    assert adm.register_request("h1", "r1", "req-1", unlocked=True) is None
    assert adm.register_request("h1", "r1", "req-1", unlocked=True) is None             # 재전송
    assert adm.register_request("h1", "r1", "req-2", unlocked=True) == ra.REQUEST_MISMATCH
    assert adm.consume_request("h1", "r1", "req-x", REQUEST_EV) == ra.REQUEST_MISMATCH
    adm.clock_.t += 10.5                                                                # C 독립 요청 기한 10 s 지남
    assert adm.consume_request("h1", "r1", "req-1", REQUEST_EV) == ra.RESUME_EXPIRED
    assert adm.register_request("h1", "r1", "req-1", unlocked=True) == ra.REQUEST_CLOSED
    assert adm.register_request("h1", "r1", "req-3", unlocked=True) is None
    assert adm.consume_request("h1", "r1", "req-3", REQUEST_EV) is None
    adm.settle("h1", "r1", resumed=False)                                               # B·재진입 거절 → 작업 보존
    assert adm.view("h1", "r1")["request"]["state"] == "refused"
    assert adm.consume_request("h1", "r1", "req-3", REQUEST_EV) == ra.REQUEST_CLOSED     # 일회 소비


def test_question_deadline_and_new_event_invalidates(adm):
    adm.register_question("h1", "r1", "q-01", offered=True)
    adm.clock_.t += 60.5
    assert adm.answer("h1", "r1", "q-01", "resume", ANSWER_EV) == ra.RESUME_EXPIRED     # 만료 뒤 "응" 은 재개 아님
    assert adm.view("h1", "r1")["question"]["state"] == "expired"
    assert adm.answer("h1", "r1", "q-01", "expired", None) == ra.QUESTION_CLOSED
    assert adm.view("h2", "r1") == {"question": None, "request": None, "remaining": None, "until": None}   # 새 사건
    assert adm.register_question("h2", "r1", "q-01", offered=True) == ra.QUESTION_MISMATCH   # 쓴 ID 재사용 거절
    assert adm.register_question("h2", "r1", "q-02", offered=True) is None


def test_independent_request_total_time_like_e():
    """E 회신 10/13·#291 E 리뷰: 독립 요청 30 s 는 녹음부터 STT·분류·등록 확인까지 전체, 그 값이면 거절.
    C 는 증빙으로 아는 최소 전체(SDK 요청 시각 + STT)가 30 s 미만인지 본다."""
    limits = ra.load_limits(str(RESUME_FILE), str(VOICE_FILE))
    assert not ra.evidence_ok("request", {"rec_end_s": 28, "request_s": 29, "stt_s": 14}, limits)   # 리뷰 반례 계열
    assert not ra.evidence_ok("request", {"rec_end_s": 19, "request_s": 20, "stt_s": 10}, limits)   # 정확히 30 → 거절
    assert ra.evidence_ok("request", {"rec_end_s": 19, "request_s": 20, "stt_s": 9.9}, limits)
    assert not ra.evidence_ok("request", {"rec_end_s": 1, "request_s": 2, "stt_s": 15}, limits)      # STT 15 그 값


def test_open_question_deadline_is_fixed_at_registration(adm):
    adm.register_question("h1", "r1", "q-01", offered=True)
    first = adm.view("h1", "r1")
    adm.clock_.t += 30
    later = adm.view("h1", "r1")
    assert later["until"] == first["until"] and later["remaining"] == pytest.approx(30.0)
    adm.clock_.t += 40                                                  # 만료 → 열린 기한 없음
    assert adm.view("h1", "r1")["until"] is None
