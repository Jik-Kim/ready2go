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


class PlaceConfirmation:
    def __init__(self, *, item_names=None, answer_timeout_sec=None, max_reasks=None):
        if answer_timeout_sec is not None and (
                not finite(answer_timeout_sec) or answer_timeout_sec <= 0):
            raise ValueError('finite positive place answer budget required')
        if max_reasks is not None and (type(max_reasks) is not int or max_reasks < 0):
            raise ValueError('nonnegative place reask limit required')
        if item_names is not None and not isinstance(item_names, dict):
            raise ValueError("current world item display names required")
        self.item_names = dict(item_names or {})
        self.answer_timeout_sec, self.max_reasks = answer_timeout_sec, max_reasks
        self._lock = threading.RLock()
        self.question = None
        self.finished_at = None
        self.final = None
        self.completed = set()
        self.attempt = 0

    @serialized
    def invalidate(self):
        self.question = None
        self.finished_at = None

    def _question(self, work):
        counts = Counter(work.items)
        names = ', '.join(f'{self.item_names[item]} {count}개' for item, count in counts.items())
        self.question = PlaceQuestion(work, self.attempt,
            f'이번 작업에서 전달 트레이에 놓았어야 할 물품은 {names}, 총 {len(work.items)}개예요. 모두 있나요?')
        self.finished_at = None
        return self.question

    @serialized
    def begin(self, work, *, normal_observation, all_visible):
        self.invalidate()
        self.final = None
        self.attempt = 0
        if (not isinstance(work, PlaceWork) or
                not all(isinstance(s, str) and s.strip() for s in (work.run, work.step, work.destination)) or
                work.destination != 'handover_zone' or
                not isinstance(work.items, tuple) or not work.items or
                not all(isinstance(s, str) and s.strip() for s in work.items) or
                not all(isinstance(self.item_names.get(s), str) and self.item_names[s].strip() for s in work.items) or
                (work.run, work.step) in self.completed or normal_observation is not True):
            return None
        if all_visible is True:
            return self._finish(work, True, 'vision')
        if all_visible is not False:  # unknown/error is not normal non-detection
            return None
        return self._question(work)

    def _finish(self, work, success, basis):
        self.final = PlaceResult(work, success, basis)
        self.completed.add((work.run, work.step))
        self.invalidate()
        return self.final

    @serialized
    def delivered(self, question, *, now, success):
        if question is None or question is not self.question:
            return False
        if success is not True or not finite(now) or self.answer_timeout_sec is None:
            self.invalidate()
            return False
        if self.finished_at is not None:
            return False
        self.finished_at = now
        return True

    @serialized
    def answer(self, question, text, *, captured_at, now):
        if question is None or question is not self.question:
            return None
        if (self.finished_at is None or not finite(captured_at) or not finite(now) or
                not self.finished_at <= captured_at <= now < self.finished_at + self.answer_timeout_sec):
            self.invalidate()
            return None
        decision = classify_presence(text)
        if decision is not None:
            return self._finish(question.work, decision, 'user')
        # Unknown limits mean safe hold, not an invented operational default.
        if self.max_reasks is None or self.attempt >= self.max_reasks:
            self.invalidate()
            return None
        self.attempt += 1
        return self._question(question.work)
