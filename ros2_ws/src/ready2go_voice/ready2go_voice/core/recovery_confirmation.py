"""E-local P2 confirmation policy; no ROS, wire publisher, unlock or motion.

Caller serializes trusted C state into StoppedWork. Local monotonic values must
come from one Voice process. Evidence flags require real B/C adapters; seq alone
is not fresh robot observation. No adapter is enabled by this module.
"""
from dataclasses import dataclass
from functools import wraps
import math
import threading
import uuid
from .runner_notice import STATUS_PROMPTS, warning_kind

RESUME_QUESTION = '복구 확인이 끝났어요. 멈춘 단계부터 작업을 이어서 할까요?'
NEW_START_QUESTION = '물리 복원과 상태 확인이 끝났어요. 새 작업을 처음부터 시작할까요?'


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def safety_utterance(text):
    if not isinstance(text, str):
        return None
    forms = {'멈춰': 'stop', '정지해': 'stop', '중단': 'stop', '중단해': 'stop', '복구': 'recover', '복구해': 'recover',
            '상태 확인 후 복구해': 'recover', '재개해': 'resume',
            '이어서 실행해': 'resume', '이어서 해': 'resume', '처음부터 시작해': 'new_start',
            '새 작업 시작해': 'new_start'}
    normalized = ''.join(text.split()).rstrip('.!?。？！')
    return {''.join(key.split()):value for key,value in forms.items()}.get(normalized)


def task_end_utterance(text):
    """Narrow positive grammar, with negation scoped to ending this work."""
    if not isinstance(text, str):
        return False
    text = ''.join(text.split()).rstrip('.!?。？！')
    return text in ('종료', '종료해', '작업종료해', '이작업종료해', '계속하지말고종료해')


@dataclass(frozen=True)
class TaskEndCandidate:
    work: 'StoppedWork'


@dataclass(frozen=True)
class IndependentRequest:
    work: 'StoppedWork'
    request_id: str
    issued_at: float


def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


@dataclass(frozen=True)
class StoppedWork:
    session: str  # accepted current boot
    stop: str     # halt event
    task: str     # run
    step: str
    cause: str | None = None  # trusted event classification, not a new wire field
    skill: str | None = None  # actual skill, never inferred from step/task name


@dataclass(frozen=True)
class Evidence:
    stopped: bool = False
    recovered: bool = False
    conditions: bool = False  # includes pre / no external force / normal observation
    resume_point: bool = False
    fresh: bool = False
    sensor_normal: bool = False  # additional recovery evidence for SENSOR_INVALID

    def verified(self):
        return all(v is True for v in (self.stopped, self.recovered, self.conditions,
                                      self.resume_point, self.fresh))


@dataclass(frozen=True)
class NewStartEvidence:
    """B/C observations for a place drop; speech alone cannot set these flags."""
    work: StoppedWork
    stopped: bool = False
    run_ended: bool = False
    restored: bool = False
    gripper_checked: bool = False
    item_checked: bool = False
    drawer_checked: bool = False
    workspace_checked: bool = False
    state_synced: bool = False
    conditions: bool = False  # B/C safety, including normal sensors/no external force
    fresh: bool = False

    def verified(self):
        return all(value is True for key, value in self.__dict__.items() if key != 'work')


@dataclass(frozen=True)
class NewStartCandidate:
    """Internal fresh-run intent only; no old step params/coordinates/effects."""
    previous_work: StoppedWork  # correlation/audit, never a resume point


@dataclass(frozen=True)
class HaltNoticeEvidence:
    work: StoppedWork
    stopped: bool = False
    fresh: bool = False
    dropped: bool = False  # genuine drop, not merely B's current error_code
    item_name: str | None = None  # registered/observed name provided by trusted adapter
    item_confirmed: bool = False


def _particle(name, with_jong, without_jong):
    last = ord(name[-1])
    return name + (with_jong if 0xAC00 <= last <= 0xD7A3 and (last - 0xAC00) % 28
                   else without_jong)


@dataclass(frozen=True)
class Question:
    work: StoppedWork
    revision: int
    valid_until: float
    issued_at: float
    text: str = RESUME_QUESTION
    mode: str = 'resume'  # E-local only; not an intent enum
    question_id: str = ''


@dataclass(frozen=True)
class AudioRequest:
    question: Question
    captured_at: float
    ended_at: float
    started_at: float
    result_until: float


class RecoveryConfirmation:
    def __init__(self, session, *, admission_window_sec=None, stt_result_timeout_sec=None,
                 independent_request_timeout_sec=None):
        if not isinstance(session, str) or not session.strip():
            raise ValueError('session required')
        for value in (admission_window_sec, stt_result_timeout_sec, independent_request_timeout_sec):
            if value is not None and (not finite(value) or value <= 0):
                raise ValueError('finite positive budget or None required')
        self.session = session
        self.admission_window_sec = admission_window_sec
        self.stt_result_timeout_sec = stt_result_timeout_sec
        self.independent_request_timeout_sec = independent_request_timeout_sec
        self._lock = threading.RLock()
        self.retired_boots = set()
        self.sequences = {}
        self.retired_events = set()
        self.revision = -1
        self.work = None
        self.asked = set()
        self.question = None
        self.finished_at = None
        self.request = None
        self.registered_at = None
        self.tts_started_at = None
        self.independent = None
        self.independent_audio = None
        self.independent_result = None
        self.independent_ack = None
        self.audio_end = -1
        self.current_state_confirmed = True
        self.restart_required_runs = set()  # candidate eligibility only, no global motion lock

    @classmethod
    def from_config(cls, session, cfg):
        return cls(session, **{name: cfg.get('resume_' + name) for name in (
            'admission_window_sec', 'stt_result_timeout_sec', 'independent_request_timeout_sec')})

    @serialized
    def voice_restarted(self):
        """Require a fresh trusted C state; do not discard C's preserved work."""
        self.invalidate()
        self.current_state_confirmed = False

    @serialized
    def track_boot(self, session, *, valid_state):
        """Only an authenticated valid state can advance the current boot."""
        if valid_state is not True or not isinstance(session, str) or not session.strip():
            return False
        if session == self.session:
            return True
        if session in self.retired_boots:
            return False
        self.retired_boots.add(self.session)
        self.session = session
        self.work = None
        self.current_state_confirmed = False
        self.invalidate()
        self.sequences.clear()
        self.revision = -1
        return True

    def _accept(self, work, revision):
        if (not isinstance(work, StoppedWork) or work.session != self.session or
                not all(isinstance(v, str) and v.strip() for v in
                        (work.stop, work.task, work.step)) or
                any(v is not None and (not isinstance(v, str) or not v.strip())
                    for v in (work.cause, work.skill)) or
                type(revision) is not int or revision < 0):
            return False
        key = (work.session, work.task, work.stop)
        if key in self.retired_events:
            return False
        if revision <= self.revision or revision <= self.sequences.get(key, -1):
            return False
        # A trusted newer conflict is still an observed ordering boundary.
        # Record it before rejecting its meaning so older status/ACK cannot revive work.
        self.sequences[key] = revision
        self.revision = revision
        if (self.work is not None and key == (self.work.session, self.work.task, self.work.stop)
                and work != self.work):
            self.invalidate()  # newer conflicting semantic state cannot reuse prior checks
            self.current_state_confirmed = False
            return False
        return True

    @serialized
    def invalidate(self):
        self.question = None
        self.finished_at = None
        self.request = None
        self.registered_at = None
        self.tts_started_at = None
        self.independent = None
        self.independent_audio = None
        self.independent_result = None
        self.independent_ack = None

    @serialized
    def stopped(self, work, revision):
        if not self._accept(work, revision):
            return False
        if self.work is not None and work != self.work:
            self.retired_events.add((self.work.session, self.work.task, self.work.stop))
        unchanged = work == self.work
        self.work = work
        self.current_state_confirmed = True
        if work.cause == 'OBJECT_DROPPED':
            self.restart_required_runs.add((work.session, work.task))
        if not unchanged:
            self.invalidate()
        # A newer status for the same semantic halt is not a new recording/request.
        return True

    @serialized
    def completed(self, work, revision, *, valid_state):
        """Trusted current C completion retires local work; no C state mutation."""
        if valid_state is not True or work != self.work or not self._accept(work, revision):
            return False
        self._retire_work(work)
        return True

    def _retire_work(self, work):
        # E-local retirement only; neither a C termination ACK nor a motion action.
        self.retired_events.add((work.session, work.task, work.stop))
        self.invalidate()
        self.work = None

    @serialized
    def notice(self, evidence=None):
        """Trusted current event evidence only. No wire adapter calls this yet."""
        if self.work is None:
            return STATUS_PROMPTS['unconfirmed']
        kind = warning_kind(self.work.cause, halted=True)[0]
        default = STATUS_PROMPTS[kind]
        if (not isinstance(evidence, HaltNoticeEvidence) or evidence.work != self.work or
                evidence.stopped is not True or evidence.fresh is not True):
            return default
        if self.work.cause == 'SENSOR_INVALID':
            return '센서값 이상으로 작업을 중단했습니다. 센서와 물품 상태를 확인해 주세요.'
        if self.work.cause == 'ESTOP':
            return '비상정지로 작업을 중단했습니다. 물리 비상정지와 장치 상태를 확인해 주세요.'
        name = evidence.item_name
        if (self.work.cause == 'OBJECT_DROPPED' and self.work.skill == 'place' and
                evidence.dropped is True and evidence.item_confirmed is True and
                isinstance(name, str) and name.strip() == name and name and
                all(c.isalnum() or c == ' ' for c in name)):
            return (_particle(name, '이', '가') + ' 떨어져 작업을 중단했습니다. ' +
                    _particle(name, '을', '를') + ' 다시 서랍에 넣어주세요.')
        return default

    def _recovery_mode(self, work, evidence):
        if (work.session, work.task) in self.restart_required_runs:
            if (work.cause == 'OBJECT_DROPPED' and work.skill == 'place' and
                    isinstance(evidence, NewStartEvidence) and evidence.work == work and
                    evidence.verified()):
                return 'new_start'
            return None
        if (isinstance(evidence, Evidence) and evidence.verified() and
                (work.cause != 'SENSOR_INVALID' or evidence.sensor_normal is True)):
            return 'resume'
        return None

    @serialized
    def ordinary_cancel(self):
        """Cancel is not an answer declining this question; preserve stopped work."""
        return self.work

    @serialized
    def abandon(self, question):
        if question is None or question is not self.question:
            return False
        self.invalidate()
        return True

    @serialized
    def recovered(self, work, revision, evidence, *, now, valid_until):
        if not self.current_state_confirmed or work != self.work or not self._accept(work, revision):
            return None
        mode = self._recovery_mode(work, evidence)
        if (mode is None or
                not finite(now) or now < 0 or not finite(valid_until) or valid_until <= now):
            self.invalidate()
            return None
        if work in self.asked:
            return None
        self.asked.add(work)
        self.question = Question(work, revision, valid_until, now,
                                 NEW_START_QUESTION if mode == 'new_start' else RESUME_QUESTION,
                                 mode, uuid.uuid4().hex)
        self.finished_at = None
        self.request = None
        return self.question

    def _ack_current(self, work, revision, valid_state):
        # ACK may arrive in a newer seq of the same boot/run/halt. It is not
        # fresh robot evidence or permission to resume, and cannot revive work.
        if (valid_state is not True or not self.current_state_confirmed or
                work != self.work or type(revision) is not int or revision < self.revision):
            return False
        return revision == self.revision or self._accept(work, revision)

    @serialized
    def registered(self, question, work, revision, *, now, valid_state):
        """Current trusted C registration only; no extra E ACK timer.

        valid_until is an E-local bound supplied from trusted C validity, never
        a raw C monotonic timestamp. A wire/clock adapter is still not enabled.
        """
        if question is None or question is not self.question:
            return False
        if self.registered_at is not None:
            return False  # retransmission cannot extend deadlines or replay TTS
        if (not finite(now) or not question.issued_at <= now < question.valid_until or
                not self._ack_current(work, revision, valid_state)):
            self.invalidate()
            return False
        self.registered_at = now
        return True

    @serialized
    def tts_started(self, question, *, now):
        if question is None or question is not self.question:
            return False
        if self.tts_started_at is not None:
            return False
        if (self.registered_at is None or not finite(now) or
                not self.registered_at <= now < question.valid_until):
            self.invalidate()
            return False
        self.tts_started_at = now
        return True

    @serialized
    def expire(self, *, now):
        if not finite(now) or now < 0:
            self.invalidate()
            return True
        q = self.question
        if q is None:
            return False
        limit = q.valid_until
        if self.finished_at is not None and self.request is None:
            if self.admission_window_sec is None:
                self.invalidate(); return True
            # The approved admission boundary itself is included.
            if now <= self.finished_at + self.admission_window_sec and now < q.valid_until:
                return False
            limit = min(limit, self.finished_at + self.admission_window_sec)
        elif self.request is not None:
            limit = min(limit, self.request.result_until)
        if now >= limit:
            self.invalidate(); return True
        return False

    @serialized
    def delivered(self, question, *, now, success):
        """Actual completion after the existing PCMTTS timeout checks, not enqueue.

        The future caller must report timeout/cancel/failure as success=False.
        No operational recovery TTS caller is connected here.
        """
        if question is None or question is not self.question:
            return False
        if (success is not True or not finite(now) or self.registered_at is None or
                self.tts_started_at is None or
                not self.tts_started_at <= now < question.valid_until):
            self.invalidate()
            return False
        if self.finished_at is not None:
            return False
        self.finished_at = now
        return True

    @serialized
    def admit(self, question, *, captured_at, ended_at, started_at):
        """Called at Whisper SDK create boundary, after WAV/client initialization.

        10.0 is included. Missing agreed processing budget disables admission.
        A receipt binds recording, question and current boot/run/halt. It is not
        an operational resume request. Result expiry is separate from admission.
        valid_until is an E-local trusted validity bound, never C monotonic time.
        The immutable receipt reuses the checked recording order at answer().
        """
        if question is None or question is not self.question:
            return None
        if (self.request is not None or self.stt_result_timeout_sec is None or self.admission_window_sec is None or
                self.finished_at is None or not all(finite(v) for v in
                    (captured_at, ended_at, started_at)) or
                not self.finished_at <= captured_at <= ended_at <= started_at or
                not question.issued_at <= started_at < question.valid_until or
                started_at > self.finished_at + self.admission_window_sec):
            self.invalidate()
            return None
        until = started_at + self.stt_result_timeout_sec
        if not finite(until):
            self.invalidate()
            return None
        self.audio_end = max(self.audio_end, ended_at)
        self.request = AudioRequest(question, captured_at, ended_at, started_at, until)
        return self.request

    @serialized
    def answer(self, text, question, *, captured_at, now, evidence, request=None):
        if question is None or question is not self.question:
            return None
        if (request is None or request is not self.request or request.question is not question or
                captured_at != request.captured_at or not finite(now) or
                not request.started_at <= now < min(request.result_until, question.valid_until)):
            self.invalidate()
            return None
        if task_end_utterance(text):
            candidate = TaskEndCandidate(self.work)
            self._retire_work(candidate.work)
            return candidate
        if isinstance(text, str) and text.strip().rstrip('.!?') in ('아니', '아니요'):
            self.abandon(question)
            return None
        if (safety_utterance(text) != question.mode or
                self._recovery_mode(question.work, evidence) != question.mode):
            self.invalidate()
            return None
        self.invalidate()  # consume even if later C execution fails; never replay
        return (NewStartCandidate(question.work) if question.mode == 'new_start'
                else question.work)


    @serialized
    def begin_independent(self, work, *, now, unique_target):
        if (work is None or work != self.work or not self.current_state_confirmed or
                unique_target is not True or not finite(now) or now < 0):
            return None
        self.invalidate()
        self.independent = IndependentRequest(work, uuid.uuid4().hex, now)
        return self.independent

    @serialized
    def admit_independent(self, request, *, captured_at, ended_at, started_at):
        if request is None or request is not self.independent:
            return False
        if (self.independent_audio is not None or self.independent_request_timeout_sec is None or
                self.stt_result_timeout_sec is None or not all(finite(v) for v in
                    (captured_at, ended_at, started_at)) or
                not request.issued_at <= captured_at <= ended_at <= started_at or
                captured_at <= self.audio_end or
                started_at >= captured_at + self.independent_request_timeout_sec):
            self.invalidate(); return False
        self.audio_end = ended_at
        self.independent_audio = (captured_at, ended_at, started_at)
        return True

    def _independent_valid(self, request, now):
        if (request is None or request is not self.independent or self.independent_audio is None or
                request.work != self.work or not self.current_state_confirmed or
                not finite(now)):
            return False
        captured, _, started = self.independent_audio
        limit = captured + self.independent_request_timeout_sec
        if self.independent_result is None:
            limit = min(limit, started + self.stt_result_timeout_sec)
        return started <= now < limit

    @serialized
    def independent_stt(self, request, text, *, now):
        if request is None or request is not self.independent:
            return False  # stale callbacks must not invalidate another current request
        if not self._independent_valid(request, now) or self.independent_result is not None:
            self.invalidate(); return False
        kind = 'end' if task_end_utterance(text) else safety_utterance(text)
        if kind != 'end' and kind != 'resume':
            self.invalidate(); return False
        # Reuse this classified recording at ACK/consumption; a new request
        # or semantic invalidation clears it, while normal seq progress does not.
        self.independent_result = (kind, now)
        return True

    @serialized
    def independent_registered(self, request, work, revision, *, now, valid_state):
        if request is None or request is not self.independent:
            return False
        if self.independent_ack is not None:
            return False
        if (not self._independent_valid(request, now) or self.independent_result is None or
                now < self.independent_result[1] or
                not self._ack_current(work, revision, valid_state)):
            self.invalidate(); return False
        self.independent_ack = now
        return True

    @serialized
    def independent_candidate(self, request, *, now, evidence):
        if request is None or request is not self.independent:
            return None  # preserve the current request's audio/result/ACK and deadlines
        if (not self._independent_valid(request, now) or self.independent_ack is None or
                now < self.independent_ack):
            self.invalidate(); return None
        kind = self.independent_result[0]
        work = request.work
        if kind == 'end':
            candidate = TaskEndCandidate(work)
            self._retire_work(work)
            return candidate
        if self._recovery_mode(work, evidence) != 'resume':
            self.invalidate(); return None
        self.invalidate()  # single use; cannot replay even if C later rejects
        return work
