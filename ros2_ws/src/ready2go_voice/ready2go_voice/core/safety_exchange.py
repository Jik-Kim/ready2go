"""현재 E 복구 질문·독립 발화 처리. 공개 wire/로봇 허가는 만들지 않습니다.

호출자는 신뢰할 수 있는 C 상태를 기존 typed core 입력으로 매핑합니다.
등록/증빙 확인은 실제 B/C 입력이며 발화로 대체할 수 없습니다.
"""
from dataclasses import dataclass, replace
import threading
from .recovery_confirmation import (RecoveryConfirmation, StoppedWork, Evidence,
    NewStartEvidence, RunnerOffer, finite, serialized)
from .recovery_confirmation import safety_utterance


@dataclass(frozen=True)
class ControlReceipt:
    """One recording in the E clock; retained after policy consumption, never a log."""
    target: object
    captured_at: float
    ended_at: float
    started_at: float
    result_at: float
    classified_at: float
    tts_finished_at: float | None = None
    registered_at: float | None = None
    valid_until: float | None = None


@dataclass(frozen=True)
class IndependentRegistration:
    request: object


@dataclass(frozen=True)
class QuestionDeclined:
    question: object


@dataclass(frozen=True)
class RecoveryRequest:
    work: StoppedWork


class SafetyExchange:
    def __init__(self, cfg):
        self.cfg = cfg
        self.policy = None
        self.evidence = None
        self.capture = None
        self.last_context = self.last_candidate = None
        self.last_rejection_reason = None
        self._lock = threading.RLock()

    @serialized
    def stopped(self, work, revision, *, valid_state, evidence=None):
        if valid_state is not True or not isinstance(work, StoppedWork):
            return False
        if self.policy is None:
            if not isinstance(work.session, str) or not work.session.strip():
                return False
            self.policy = RecoveryConfirmation.from_config(work.session, self.cfg)
        old = self.policy.work
        if not self.policy.track_boot(work.session, valid_state=valid_state):
            return False
        accepted = self.policy.stopped(work, revision)
        if old != self.policy.work or not self.policy.current_state_confirmed:
            self.capture = self.evidence = None
            self.last_context = self.last_candidate = None
        if accepted and isinstance(evidence, (Evidence, NewStartEvidence, RunnerOffer)):
            self.evidence = evidence
        return accepted

    @serialized
    def offer(self, work, revision, evidence, *, now, valid_until, valid_state):
        if (valid_state is not True or self.policy is None
                or not isinstance(evidence, (Evidence, NewStartEvidence, RunnerOffer))):
            return None
        q = self.policy.recovered(work, revision, evidence, now=now, valid_until=valid_until)
        if q is not None:
            self.evidence = evidence
            self.capture = None
            self.last_context = self.last_candidate = None
        return q

    @serialized
    def current(self, target):
        return (target is not None and self.policy is not None
                and (target is self.policy.question or target is self.policy.independent))

    @serialized
    def cancel(self):
        if self.policy is not None:
            self.policy.ordinary_cancel()  # keep the suspended work.
            self.policy.invalidate()
        self.capture = None
        self.last_context = self.last_candidate = None

    @serialized
    def registered(self, q, work, revision, *, now, valid_state, valid_until=None):
        return self.current(q) and self.policy.registered(q, work, revision, now=now, valid_state=valid_state, valid_until=valid_until)

    @serialized
    def tts_started(self, q, *, now):
        return self.current(q) and self.policy.tts_started(q, now=now)

    @serialized
    def delivered(self, q, *, now, success):
        return self.current(q) and self.policy.delivered(q, now=now, success=success)

    @serialized
    def begin_independent(self, *, now, unique_target):
        if self.policy is None or not finite(now):
            return None
        p = self.policy
        if p.question is not None:
            if p.question_until is None or now < p.question_until:
                return None
            p.expire(now=now)
        if p.independent is not None:
            if p.independent_request_timeout_sec is None:
                return None
            start = p.independent_audio[0] if p.independent_audio is not None else p.independent.issued_at
            limit = start + p.independent_request_timeout_sec
            if p.independent_audio is not None and p.independent_result is None:
                limit = min(limit, p.independent_audio[2] + p.stt_result_timeout_sec)
            if now <= limit:
                return None
            p.invalidate()
        target = self.policy.begin_independent(self.policy.work, now=now, unique_target=unique_target)
        self.capture = None
        self.last_context = self.last_candidate = None
        return target

    @serialized
    def reserve(self, target):
        if not self.current(target) or self.capture is not None:
            return None
        if target is self.policy.question and self.policy.finished_at is None:
            return None
        self.capture = object()
        return self.capture

    @serialized
    def budget(self, target, *, now, captured_at=None):
        if not self.current(target) or not finite(now):
            return None
        p = self.policy
        if target is p.question:
            if p.finished_at is None or p.admission_window_sec is None or p.stt_result_timeout_sec is None:
                return None
            return min(p.question_until, p.finished_at + p.admission_window_sec + p.stt_result_timeout_sec) - now
        if p.independent_request_timeout_sec is None:
            return None
        if p.independent_audio is not None:
            start = p.independent_audio[0]
        elif finite(captured_at) and captured_at >= target.issued_at:
            start = captured_at
        else:
            start = target.issued_at
        return start + p.independent_request_timeout_sec - now

    @serialized
    def admit(self, target, capture, *, captured_at, ended_at, started_at):
        if not self.current(target) or capture is None or capture is not self.capture:
            return None
        if target is self.policy.question:
            return self.policy.admit(target, captured_at=captured_at, ended_at=ended_at, started_at=started_at)
        if self.policy.admit_independent(target, captured_at=captured_at, ended_at=ended_at, started_at=started_at):
            return self.policy.independent_audio
        return None

    @serialized
    def answer(self, target, text, *, captured_at, now, request, result_at=None):
        self.last_rejection_reason = None
        result_at = now if result_at is None else result_at
        if not self.current(target) or request is None:
            self.last_rejection_reason = 'request_not_current_or_not_admitted'
            return None
        if target is self.policy.question:
            valid_receipt = request is self.policy.request and request.question is target and captured_at == request.captured_at
            until = self.policy.question_until
            context = ControlReceipt(target, request.captured_at, request.ended_at,
                request.started_at, result_at, now, self.policy.finished_at, self.policy.registered_at, until) if valid_receipt else None
            candidate = self.policy.answer(text, target, captured_at=captured_at, now=now,
                                            evidence=self.evidence, request=request, result_at=result_at)
            if (valid_receipt and candidate is None and isinstance(text, str) and text.strip().rstrip('.!?') in ('아니', '아니요')
                    and finite(result_at) and finite(now) and request.started_at <= result_at <= now
                    and result_at <= request.result_until and finite(until) and now < until):
                candidate = QuestionDeclined(target)
            if candidate is None:
                self.last_rejection_reason = 'command_not_matched' if safety_utterance(text) is None else 'question_evidence_or_deadline_unconfirmed'
            if candidate is not None:
                self.last_context, self.last_candidate = context, candidate
            return candidate
        if request is not self.policy.independent_audio:
            self.last_rejection_reason = 'request_receipt_mismatch'
            return None
        valid_result = (self.policy._independent_valid(target, result_at) and finite(now)
            and result_at <= now <= captured_at + self.policy.independent_request_timeout_sec)
        if valid_result and safety_utterance(text) == 'recover':
            work = target.work
            self.policy.invalidate()
            candidate = RecoveryRequest(work)
            self.last_context = ControlReceipt(target, *request, result_at, now)
            self.last_candidate = candidate
            return candidate
        valid = self.policy._independent_valid(target, now)
        command = safety_utterance(text)
        from .recovery_confirmation import task_end_utterance
        if self.policy.independent_stt(target, text, now=now, result_at=result_at):
            self.last_context = ControlReceipt(target, *request, result_at, now)
            candidate = (self.policy.independent_end(target, now=now)
                if self.policy.independent_result[0] == 'end' else IndependentRegistration(target))
            self.last_candidate = candidate
            return candidate
        self.last_rejection_reason = ('request_expired_or_state_unconfirmed' if not valid else
            'command_not_matched' if command is None and not task_end_utterance(text) else 'command_not_available_in_current_path')
        return None

    @serialized
    def independent_registered(self, target, work, revision, *, now, valid_state, evidence):
        self.last_rejection_reason = None
        if (not self.current(target) or not self.policy.independent_registered(target, work, revision,
                now=now, valid_state=valid_state)):
            self.last_rejection_reason = 'registration_work_revision_or_deadline_unconfirmed'
            return None
        candidate = self.policy.independent_candidate(target, now=now, evidence=evidence)
        if candidate is None:
            missing = [key for key in ('stopped','recovered','conditions','resume_point','fresh')
                       if isinstance(evidence, Evidence) and getattr(evidence,key) is not True]
            self.last_rejection_reason = 'evidence_missing:' + ','.join(missing) if missing else 'current_recovery_mode_unconfirmed'
        if candidate is not None:
            if self.last_context is not None:
                self.last_context = replace(self.last_context, registered_at=now,
                    valid_until=getattr(evidence, 'valid_until', None))
            self.last_candidate = candidate
        return candidate

    @serialized
    def fail(self, target):
        if self.current(target):
            self.policy.invalidate()
            self.capture = None
            self.last_context = self.last_candidate = None
        elif self.policy is not None and self.policy.question is None and self.policy.independent is None:
            self.capture = None  # answer가 먼저 무효화한 예약만 정리; 새 현재 요청은 보존합니다.
