"""E-only #43 verification candidates. No effect, success TTS, ROS or motion.

C owns verify waiting/final effect/logs. A/B/C adapters must supply authentic
observations for this same action. Test flags are not operational observations.
"""
from collections import Counter
from dataclasses import dataclass
from .recovery_confirmation import finite, serialized
import threading


@dataclass(frozen=True)
class PickObservation:
    pick_id: str
    grip_pick_id: str
    width_m: float | None
    closing_completed: bool = False
    width_valid: bool = False
    grasp_detected: bool = False
    communication_ok: bool = False
    not_interrupted: bool = False
    lift_held: bool = False


def pick_verified(observation, *, lower_bound_m):
    """Strict width lower bound from approved config, not world bounding box."""
    if not finite(lower_bound_m) or lower_bound_m <= 0:
        return False
    return (isinstance(observation, PickObservation) and
            isinstance(observation.pick_id, str) and bool(observation.pick_id.strip()) and
            observation.pick_id == observation.grip_pick_id and
            finite(observation.width_m) and observation.width_m > lower_bound_m and
            all(v is True for v in (observation.closing_completed, observation.width_valid,
                observation.grasp_detected, observation.communication_ok,
                observation.not_interrupted, observation.lift_held)))


@dataclass(frozen=True)
class PlaceWork:
    run: str
    step: str
    destination: str
    items: tuple[str, ...]  # expected item IDs in this destination/current run


@dataclass(frozen=True)
class PlaceQuestion:
    work: PlaceWork
    attempt: int
    text: str


@dataclass(frozen=True)
class PlaceResult:
    work: PlaceWork
    success: bool
    basis: str  # internal provenance: vision vs user (not wire enum)


def classify_presence(text):
    if not isinstance(text, str):
        return None
    text = text.strip().rstrip('.!?。？！').strip()
    if text in ('네', '예', '모두 있어요', '다 있어요'):
        return True
    if text in ('아니', '아니요', '없어요', '다 있지 않아요'):
        return False
    return None


@dataclass(frozen=True)
class PlaceAudioRequest:
    question: PlaceQuestion
    captured_at: float
    ended_at: float
    started_at: float
    result_until: float


class PlaceConfirmation:
    def __init__(self, *, item_names=None, admission_window_sec=None,
                 stt_result_timeout_sec=None, max_reasks=None):
        for value in (admission_window_sec, stt_result_timeout_sec):
            if value is not None and (not finite(value) or value <= 0):
                raise ValueError('finite positive place segment budget required')
        if max_reasks is not None and (type(max_reasks) is not int or max_reasks not in (0, 1)):
            raise ValueError('place reask limit must be None, 0 or 1')
        if item_names is not None and not isinstance(item_names, dict):
            raise ValueError('current world item display names required')
        self.item_names = dict(item_names or {})
        self.admission_window_sec = admission_window_sec
        self.stt_result_timeout_sec = stt_result_timeout_sec
        self.max_reasks = max_reasks
        self._lock = threading.RLock()
        self.question = None
        self.finished_at = None
        self.request = None
        self.final = None
        self.completed = set()
        self.procedures = {}  # immutable identity per run/step; no resetting by retransmission
        self.attempt = 0
        self.asked_at = None
        self.final_until = None
        self.final_budget = None

    @classmethod
    def from_config(cls, cfg, *, item_names):
        return cls(item_names=item_names, admission_window_sec=cfg.get('place_admission_window_sec'),
                   stt_result_timeout_sec=cfg.get('place_stt_result_timeout_sec'),
                   max_reasks=cfg.get('place_max_reasks'))

    def _clear(self):
        self.question = None
        self.finished_at = None
        self.request = None

    @serialized
    def invalidate(self):
        if self.question is not None:
            self._finish(self.question.work, False, 'unconfirmed')
        else:
            self._clear()

    def _question(self, work):
        counts = Counter(work.items)
        names = ', '.join(f'{self.item_names[item]} {count}개' for item, count in counts.items())
        self._clear()
        self.question = PlaceQuestion(work, self.attempt,
            f'이번 작업에서 전달 트레이에 놓았어야 할 물품은 {names}, 총 {len(work.items)}개예요. 모두 있나요?')
        return self.question

    @serialized
    def begin(self, work, *, normal_observation, all_visible):
        if (not isinstance(work, PlaceWork) or
                not all(isinstance(s, str) and s.strip() for s in (work.run, work.step, work.destination)) or
                work.destination != 'handover_zone' or
                not isinstance(work.items, tuple) or not work.items or
                not all(isinstance(s, str) and s.strip() for s in work.items) or
                not all(isinstance(self.item_names.get(s), str) and self.item_names[s].strip() for s in work.items)):
            return None
        key = (work.run, work.step)
        if key in self.procedures:
            if key in self.completed or self.procedures[key] != work:
                return None
            # Replayed status cannot replace the active question, answer or counter.
            if normal_observation is not True:
                self.invalidate(); return None
            return self.question
        self.invalidate()  # retire the old procedure before a new run/step begins
        self.procedures[key] = work
        self.final = None
        self.attempt = 0
        self.asked_at = self.final_until = self.final_budget = None
        if normal_observation is not True or type(all_visible) is not bool:
            self._finish(work, False, 'observation_error'); return None
        if all_visible:
            return self._finish(work, True, 'vision')
        return self._question(work)

    def _finish(self, work, success, basis):
        self.final = PlaceResult(work, success, basis)
        self.completed.add((work.run, work.step))
        self._clear()
        return self.final

    @serialized
    def asked(self, question, *, now, final_timeout_sec):
        """Bind the first asked registration to one local clock interval.

        The caller supplies the approved C budget, not a new E default. A C
        acknowledgement must be mapped to this local clock; remote monotonic
        timestamps cannot be compared here. C still checks its final deadline.
        """
        if question is None or question is not self.question:
            return False
        if (not finite(now) or now < 0 or not finite(final_timeout_sec) or
                final_timeout_sec <= 0):
            self.invalidate(); return False
        if self.asked_at is not None:
            if (now < self.asked_at or final_timeout_sec != self.final_budget or
                    not self._within_final(now)):
                self.invalidate(); return False
            return True  # Same question or reask cannot restart the interval.
        if question.attempt != 0 or self.finished_at is not None:
            self.invalidate(); return False
        until = now + final_timeout_sec
        if not finite(until):
            self.invalidate(); return False
        self.asked_at, self.final_until, self.final_budget = now, until, final_timeout_sec
        return True

    def _within_final(self, now):
        return self.final_until is None or self.asked_at <= now <= self.final_until

    @serialized
    def expire(self, *, now):
        """Poll the existing whole interval; no timer thread or new wire."""
        if self.question is None or self.final_until is None:
            return False
        if not finite(now) or not self._within_final(now):
            self.invalidate(); return True
        return False

    @serialized
    def delivered(self, question, *, now, success):
        if question is None or question is not self.question:
            return False
        if (success is not True or not finite(now) or now < 0 or not self._within_final(now) or
                self.admission_window_sec is None or self.stt_result_timeout_sec is None):
            self.invalidate(); return False
        if self.finished_at is not None:
            return False
        self.finished_at = now
        return True

    @serialized
    def admit(self, question, *, captured_at, ended_at, started_at):
        if question is None or question is not self.question:
            return None
        if (self.request is not None or self.finished_at is None or
                not all(finite(v) for v in (captured_at, ended_at, started_at)) or
                not self.finished_at <= captured_at <= ended_at <= started_at or
                not self._within_final(started_at) or
                started_at >= self.finished_at + self.admission_window_sec):
            self.invalidate(); return None
        until = started_at + self.stt_result_timeout_sec
        if not finite(until):
            self.invalidate(); return None
        self.request = PlaceAudioRequest(question, captured_at, ended_at, started_at, until)
        return self.request

    @serialized
    def answer(self, question, text, *, captured_at, now, request=None):
        if question is None or question is not self.question:
            return None
        if (request is None or request is not self.request or request.question is not question or
                captured_at != request.captured_at or not finite(now) or
                not request.started_at <= now < request.result_until or not self._within_final(now)):
            self.invalidate(); return None
        decision = classify_presence(text)
        if decision is not None:
            return self._finish(question.work, decision, 'user')
        if self.max_reasks is None or self.attempt >= self.max_reasks:
            self.invalidate(); return None
        self.attempt += 1
        return self._question(question.work)
