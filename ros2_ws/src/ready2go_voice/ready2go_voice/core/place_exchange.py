"""#43 E-local exchange candidates. No ROS, C registration proof or effects.

The future C adapter owns authentic question/boot/observation input and final
registration/decision. Local times belong to Voice, never C monotonic values.
"""
from dataclasses import dataclass
import threading
import uuid
from .skill_confirmation import PlaceConfirmation, PlaceWork, PlaceQuestion, classify_presence
from .recovery_confirmation import finite, serialized


@dataclass(frozen=True)
class PlaceEnvelope:
    boot_id: str
    question_id: str
    question: PlaceQuestion

    @property
    def attempt(self):
        return self.question.attempt + 1


@dataclass(frozen=True)
class PlaceReply:
    message: dict
    next_question: PlaceEnvelope | None = None


class PlaceExchange:
    def __init__(self, cfg, *, item_names, question_id=lambda: uuid.uuid4().hex):
        self.policy = PlaceConfirmation.from_config(cfg, item_names=item_names)
        self.question_id = question_id
        self._lock = threading.RLock()
        self.active = None
        self.capture = None
        self.boot = None
        self.retired_boots = set()
        self.seen_questions = set()

    def _envelope(self, question):
        ident = self.question_id()
        if not isinstance(ident, str) or not ident.strip() or ident in self.seen_questions:
            self.invalidate()
            return None
        self.seen_questions.add(ident)
        self.active = PlaceEnvelope(self.boot, ident, question)
        self.capture = None
        return self.active

    @serialized
    def current(self, envelope):
        return (envelope is not None and envelope is self.active
                and envelope.question is self.policy.question)

    @staticmethod
    def _message(envelope, answer):
        work = envelope.question.work
        return dict(intent='confirm', run_id=work.run, step_id=work.step,
                    boot_id=envelope.boot_id, question_id=envelope.question_id,
                    attempt=envelope.attempt, answer=answer)

    @serialized
    def invalidate(self):
        self.policy.invalidate()
        self.active = self.capture = None

    @serialized
    def begin(self, work, *, boot_id, observation):
        if (not isinstance(boot_id, str) or not boot_id.strip()
                or boot_id in self.retired_boots or not isinstance(work, PlaceWork)):
            return None
        if self.boot is not None and self.boot != boot_id:
            self.retired_boots.add(self.boot)
            self.invalidate()
        self.boot = boot_id
        result = self.policy.begin(work, normal_observation=observation in ('found', 'not_found'),
                                   all_visible=observation == 'found')
        if not isinstance(result, PlaceQuestion):
            if not self.current(self.active):
                self.active = self.capture = None
            return None
        if self.current(self.active) and result is self.active.question:
            return self.active
        return self._envelope(result)

    @serialized
    def asked(self, envelope, *, now, final_timeout_sec):
        """E-local asked candidate; return does not confirm C registration."""
        if not self.current(envelope):
            return None
        if not self.policy.asked(envelope.question, now=now, final_timeout_sec=final_timeout_sec):
            failure = self.fail(envelope, answer='expired')
            return failure.message if failure else None
        return self._message(envelope, 'asked')

    @serialized
    def delivered(self, envelope, *, now, success):
        if not self.current(envelope) or self.policy.asked_at is None:
            return False
        return self.policy.delivered(envelope.question, now=now, success=success)

    @serialized
    def reserve_audio(self, envelope):
        if (not self.current(envelope) or self.capture is not None
                or self.policy.asked_at is None or self.policy.finished_at is None):
            return None
        self.capture = object()
        return self.capture

    @serialized
    def admit(self, envelope, capture, *, captured_at, ended_at, started_at):
        if not self.current(envelope) or capture is None or capture is not self.capture:
            return None
        return self.policy.admit(envelope.question, captured_at=captured_at,
                                 ended_at=ended_at, started_at=started_at)

    @serialized
    def audio_budget(self, envelope, *, now):
        if not self.current(envelope) or not finite(now) or self.policy.finished_at is None:
            return None
        # Existing admission + STT segments only; setup never extends whole deadline.
        return min(self.policy.finished_at + self.policy.admission_window_sec
                   + self.policy.stt_result_timeout_sec, self.policy.final_until) - now

    @serialized
    def answer(self, envelope, text, *, captured_at, now, request):
        if (not self.current(envelope) or request is None or request is not self.policy.request
                or captured_at != request.captured_at):
            return None
        decision = classify_presence(text)
        result = self.policy.answer(envelope.question, text, captured_at=captured_at,
                                    now=now, request=request)
        if result is None and decision is not None:
            return self.fail(envelope, answer='expired')
        if result is None and self.policy.question is None:
            # Timing failure is not an ambiguous answer, except the valid second ambiguity.
            if (not finite(now) or not request.started_at <= now < request.result_until
                    or not self.policy.asked_at <= now <= self.policy.final_until):
                return self.fail(envelope, answer='expired')
        answer = 'yes' if decision is True else 'no' if decision is False else 'ambiguous'
        message = self._message(envelope, answer)
        self.active = self.capture = None
        following = self._envelope(result) if isinstance(result, PlaceQuestion) else None
        return PlaceReply(message, following)

    @serialized
    def fail(self, envelope, *, answer):
        if envelope is None or envelope is not self.active or answer not in ('expired', 'error'):
            return None
        message = self._message(envelope, answer)
        self.invalidate()
        return PlaceReply(message)

    @serialized
    def expire(self, envelope, *, now):
        if not self.current(envelope) or not self.policy.expire(now=now):
            return None
        return self.fail(envelope, answer='expired')
