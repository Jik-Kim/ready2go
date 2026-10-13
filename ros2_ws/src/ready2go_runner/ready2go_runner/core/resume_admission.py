"""재개 질문·답·독립 요청 접수 (ROS 비의존) — 계약 W3 resume_register·resume_answer·resume (#152·#271, FR-SAF-03·AC-SAF-04).

정본: requirements.md "P2 재개 응답 접수"(resume-admission-policy), runner.md 제어 인텐트 표·같은 ID 처리.
- 정지 사건(event_id)·보존 작업(run_id)마다 접수 기록 하나. 사건·작업이 바뀌면 새로 (과거 질문·요청은 무효)
- 질문은 사건당 1개: E 가 TTS 전에 등록(resume_register) → C 등록 확인(halt.resume.question) → 첫 유효 답 1개만 소비
- 질문이 닫힌 뒤(아니·만료·거절) "이어서 해" = 독립 요청: register(C 등록 확인) → request 로 일회 소비
- C 시계(monotonic) 기한: 질문 답(등록 뒤)·독립 요청(등록 뒤 소비까지). 질문 제안 기한은 Runner.resume_window_sec(잠금 해제 뒤)
- 증빙 2차 검사: 순서 + E 원본(voice.yaml) 상한. 시간 원점·경계 포함 여부는 E·C 합의 전 [E·C 합의 필요] — 지금은 상한 포함
- 여기서는 접수만 판단. 실제 재개(B 상태 재조회·재진입·pre 검사·이어 실행)는 노드가 Runner.resume_run 으로 하고 settle() 로 알림
같은 ID 재전송(등록 ACK 유실 대비)은 기존 결과를 다시 알리고 기한을 늘리지 않는다. 소비·종료 뒤 재사용·다른 사건의 같은 ID 는 거절.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import yaml

NOT_OFFERED = "NOT_OFFERED"             # 질문 등록 불가 (잠김·제안 기한 지남·보존 작업 없음)
QUESTION_MISMATCH = "QUESTION_MISMATCH"   # 사건당 질문 1개인데 다른 ID / 등록 안 된 ID 로 답 / 다른 사건에서 쓴 ID
QUESTION_CLOSED = "QUESTION_CLOSED"     # 이미 답을 받았거나 만료된 질문
QUESTION_PENDING = "QUESTION_PENDING"   # 질문이 열려 있는데 독립 요청 (질문에 답해야 함)
REQUEST_MISMATCH = "REQUEST_MISMATCH"   # 등록 안 된 요청 ID 로 소비 / 다른 요청이 이미 열림 / 다른 사건에서 쓴 ID
REQUEST_CLOSED = "REQUEST_CLOSED"       # 이미 소비했거나 만료된 요청
RESUME_EXPIRED = "RESUME_EXPIRED"       # C 기한(질문 답·독립 요청) 지남 → 질문·요청만 닫고 작업 보존
EVIDENCE_INVALID = "EVIDENCE_INVALID"   # 녹음 증빙 형식·순서·상한 불충족 (소비하지 않음)
NOT_RECOVERED = "NOT_RECOVERED"         # 아직 잠김 (복구 전) — interpreter.NOT_RECOVERED 와 같은 값

OPEN = "registered"
# 닫힌 상태: resumed(재개 시작)·refused(유효한 답이었지만 재개 검사 거절)·declined("아니")·expired(만료·무응답·TTS 실패)
ANSWER_KEYS = ("rec_start_after_tts_s", "rec_end_after_tts_s", "request_after_tts_s", "stt_s")
REQUEST_KEYS = ("rec_end_s", "request_s", "stt_s")


def load_limits(resume_file: str, voice_file: str) -> dict:
    """C 기한(resume.yaml) + E 증빙 상한(voice.yaml 원본 — 복사하지 않고 그 파일을 읽음). 없거나 틀리면 예외."""
    with open(resume_file, encoding="utf-8") as f:
        c = yaml.safe_load(f) or {}
    with open(voice_file, encoding="utf-8") as f:
        e = yaml.safe_load(f) or {}
    limits = {"question_offer_sec": c["question_offer_sec"], "question_answer_sec": c["question_answer_sec"],
              "request_sec": c["request_sec"],
              "admission_window_sec": e["resume_admission_window_sec"],
              "stt_result_timeout_sec": e["resume_stt_result_timeout_sec"],
              "independent_request_timeout_sec": e["resume_independent_request_timeout_sec"]}
    for key, value in limits.items():
        if not _number(value) or value <= 0:
            raise ValueError(f"재개 기한 {key} 는 양수여야 함: {value!r}")
    return limits


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evidence_ok(kind: str, evidence: dict | None, limits: dict) -> bool:
    """C 2차 증빙 검사. kind "answer": TTS 완료 기준 녹음 시작 ≤ 녹음 끝 ≤ SDK 요청 ≤ 접수창, STT ≤ 상한.
    kind "request"(독립 요청): 녹음 끝 ≤ SDK 요청 ≤ 독립 요청 상한, STT ≤ 상한. 칸 하나라도 없으면 불충족."""
    keys = ANSWER_KEYS if kind == "answer" else REQUEST_KEYS
    if not isinstance(evidence, dict) or not all(_number(evidence.get(k)) and evidence[k] >= 0 for k in keys):
        return False
    if evidence["stt_s"] > limits["stt_result_timeout_sec"]:
        return False
    if kind == "answer":
        return (evidence["rec_start_after_tts_s"] <= evidence["rec_end_after_tts_s"] <= evidence["request_after_tts_s"]
                <= limits["admission_window_sec"])
    return evidence["rec_end_s"] <= evidence["request_s"] <= limits["independent_request_timeout_sec"]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ResumeAdmission:
    def __init__(self, clock, limits: dict):
        self.clock = clock
        self.limits = limits
        self._lock = threading.Lock()
        self._key: tuple | None = None          # (event_id, run_id)
        self._question: dict | None = None      # {id, state, registered_at, t}
        self._request: dict | None = None
        self._used_questions: set[str] = set()  # 이번 기동에서 쓴 ID (다른 사건의 같은 ID 거절)
        self._used_requests: set[str] = set()

    # ---- 내부 ----
    def _session(self, event_id, run_id) -> None:
        if self._key != (event_id, run_id):
            self._key, self._question, self._request = (event_id, run_id), None, None

    def _expire(self) -> None:
        now = self.clock()
        for item, limit in ((self._question, "question_answer_sec"), (self._request, "request_sec")):
            if item and item["state"] == OPEN and now - item["t"] > self.limits[limit]:
                item["state"] = "expired"

    # ---- 질문 ----
    def register_question(self, event_id, run_id, question_id: str, offered: bool) -> str | None:
        """거절 이유 또는 None(등록됨·재전송 확인). offered = Runner 가 지금 질문을 제안할 수 있음."""
        with self._lock:
            self._session(event_id, run_id)
            self._expire()
            q = self._question
            if q is not None:
                if q["id"] != question_id:
                    return QUESTION_MISMATCH
                return None if q["state"] == OPEN else QUESTION_CLOSED   # 재전송: 기존 등록 그대로, 기한 연장 없음
            if question_id in self._used_questions:
                return QUESTION_MISMATCH
            if not offered:
                return NOT_OFFERED
            self._question = {"id": question_id, "state": OPEN, "registered_at": _utc(), "t": self.clock()}
            self._used_questions.add(question_id)
            return None

    def answer(self, event_id, run_id, question_id: str, answer: str, evidence: dict | None) -> str | None:
        """거절 이유 또는 None. decline·expired 는 질문만 닫음(작업 보존). resume 은 접수만 — 노드가 재개 검사 뒤 settle."""
        with self._lock:
            self._session(event_id, run_id)
            self._expire()
            q = self._question
            if q is None or q["id"] != question_id:
                return QUESTION_MISMATCH
            if q["state"] == "expired" and answer != "expired":
                return RESUME_EXPIRED
            if q["state"] != OPEN:
                return QUESTION_CLOSED
            if answer == "resume":
                if not evidence_ok("answer", evidence, self.limits):
                    return EVIDENCE_INVALID           # 소비하지 않음 — 기한 안 다른 유효 답을 받을 수 있음
                q["state"] = "admitted"
                return None
            q["state"] = "declined" if answer == "decline" else "expired"
            return None

    # ---- 독립 요청 ----
    def register_request(self, event_id, run_id, request_id: str, unlocked: bool) -> str | None:
        with self._lock:
            self._session(event_id, run_id)
            self._expire()
            r = self._request
            if r is not None and r["id"] == request_id:
                return None if r["state"] == OPEN else REQUEST_CLOSED
            if self._question is not None and self._question["state"] in (OPEN, "admitted"):
                return QUESTION_PENDING
            if request_id in self._used_requests or (r is not None and r["state"] == OPEN):
                return REQUEST_MISMATCH
            if not unlocked:
                return NOT_RECOVERED
            self._request = {"id": request_id, "state": OPEN, "registered_at": _utc(), "t": self.clock()}
            self._used_requests.add(request_id)
            return None

    def consume_request(self, event_id, run_id, request_id: str, evidence: dict | None) -> str | None:
        with self._lock:
            self._session(event_id, run_id)
            self._expire()
            r = self._request
            if r is None or r["id"] != request_id:
                return REQUEST_CLOSED if request_id in self._used_requests else REQUEST_MISMATCH
            if r["state"] == "expired":
                return RESUME_EXPIRED
            if r["state"] != OPEN:
                return REQUEST_CLOSED
            if not evidence_ok("request", evidence, self.limits):
                return EVIDENCE_INVALID
            r["state"] = "admitted"
            return None

    def settle(self, event_id, run_id, resumed: bool) -> None:
        """접수한 답·요청의 재개 검사 결과: resumed(이어 실행 시작) / refused(B·재진입·pre 거절 — 작업 보존)."""
        with self._lock:
            if self._key != (event_id, run_id):
                return
            for item in (self._question, self._request):
                if item and item["state"] == "admitted":
                    item["state"] = "resumed" if resumed else "refused"

    # ---- 상태 (/runner/status halt.resume) ----
    def view(self, event_id, run_id) -> dict:
        """{"question": {id, state, registered_at}|None, "request": …, "remaining": 열린 질문·요청의 C 기한 남은 초|None}."""
        with self._lock:
            if self._key != (event_id, run_id):
                return {"question": None, "request": None, "remaining": None}
            self._expire()
            remaining = None
            for item, limit in ((self._question, "question_answer_sec"), (self._request, "request_sec")):
                if item and item["state"] in (OPEN, "admitted") and remaining is None:
                    remaining = max(0.0, self.limits[limit] - (self.clock() - item["t"]))
            show = lambda item: None if item is None else {  # noqa: E731
                "id": item["id"], "state": OPEN if item["state"] == "admitted" else item["state"],
                "registered_at": item["registered_at"]}
            return {"question": show(self._question), "request": show(self._request), "remaining": remaining}
