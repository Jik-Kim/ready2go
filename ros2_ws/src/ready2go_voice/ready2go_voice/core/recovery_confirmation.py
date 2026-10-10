"""E-local P2 confirmation policy; no ROS, wire publisher, unlock or motion.

Caller serializes trusted C state into StoppedWork. Local monotonic values must
come from one Voice process. Evidence flags require real B/C adapters; seq alone
is not fresh robot observation. No adapter is enabled by this module.
"""
from dataclasses import dataclass
from functools import wraps
import math
import threading
from .runner_notice import STATUS_PROMPTS, warning_kind

RESUME_QUESTION = '복구 확인이 끝났어요. 멈춘 단계부터 작업을 이어서 할까요?'
NEW_START_QUESTION = '물리 복원과 상태 확인이 끝났어요. 새 작업을 처음부터 시작할까요?'


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def safety_utterance(text):
    if not isinstance(text, str):
        return None
    return {'멈춰': 'stop', '정지해': 'stop', '복구해': 'recover',
            '상태 확인 후 복구해': 'recover', '재개해': 'resume',
            '이어서 실행해': 'resume', '처음부터 시작해': 'new_start',
            '새 작업 시작해': 'new_start'}.get(text.strip().rstrip('.!?').strip())


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


@dataclass(frozen=True)
class AudioRequest:
    question: Question
    captured_at: float
    ended_at: float
    started_at: float
    result_until: float


class RecoveryConfirmation:
    def __init__(self, session, *, admission_window_sec=10.0, stt_result_timeout_sec=None):
        if not isinstance(session, str) or not session.strip():
            raise ValueError('session required')
        if not finite(admission_window_sec) or admission_window_sec <= 0:
            raise ValueError('finite positive admission window required')
        if stt_result_timeout_sec is not None and (
                not finite(stt_result_timeout_sec) or stt_result_timeout_sec <= 0):
            raise ValueError('finite positive STT result budget required')
        self.session = session
        self.admission_window_sec = admission_window_sec
        self.stt_result_timeout_sec = stt_result_timeout_sec
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
        self.restart_required_runs = set()  # candidate eligibility only, no global motion lock

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
        if (self.work is not None and key == (self.work.session, self.work.task, self.work.stop)
                and work != self.work):
            return False
        if revision <= self.revision or revision <= self.sequences.get(key, -1):
            return False
        self.sequences[key] = revision
        self.revision = revision
        return True

    @serialized
    def invalidate(self):
        self.question = None
        self.finished_at = None
        self.request = None

    @serialized
    def stopped(self, work, revision):
        if not self._accept(work, revision):
            return False
        if self.work is not None and work != self.work:
            self.retired_events.add((self.work.session, self.work.task, self.work.stop))
        self.work = work
        if work.cause == 'OBJECT_DROPPED':
            self.restart_required_runs.add((work.session, work.task))
        self.invalidate()
        return True

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
        self.work = None
        return True

    @serialized
    def recovered(self, work, revision, evidence, *, now, valid_until):
        if work != self.work or not self._accept(work, revision):
            return None
        mode = self._recovery_mode(work, evidence)
        if (mode is None or
                not finite(now) or not finite(valid_until) or valid_until <= now):
            self.invalidate()
            return None
        if work in self.asked:
            return None
        self.asked.add(work)
        self.question = Question(work, revision, valid_until, now,
                                 NEW_START_QUESTION if mode == 'new_start' else RESUME_QUESTION,
                                 mode)
        self.finished_at = None
        self.request = None
        return self.question

    @serialized
    def delivered(self, question, *, now, success):
        """now must be actual successful TTS playback completion, not enqueue."""
        if question is None or question is not self.question:
            return False
        if (success is not True or not finite(now) or
                not question.issued_at <= now < question.valid_until):
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
        an operational resume request. Result expiry is separate from admission. valid_until is an additional
        E-local context/evidence limit, never a C-process monotonic timestamp.
        """
        if question is None or question is not self.question:
            return None
        if (self.request is not None or self.stt_result_timeout_sec is None or
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
        if isinstance(text, str) and text.strip().rstrip('.!?') in ('아니', '아니요', '포기'):
            self.abandon(question)
            return None
        if (safety_utterance(text) != question.mode or
                self._recovery_mode(question.work, evidence) != question.mode):
            self.invalidate()
            return None
        self.invalidate()  # consume even if later C execution fails; never replay
        return (NewStartCandidate(question.work) if question.mode == 'new_start'
                else question.work)
