"""P2 내부 제안: 복구 뒤 명시적 재개 확인. ROS/잠금/모션 연결 없음.

TODO(E/C/B): 승인된 사건·관측·재개점 계약으로 입력을 검증하는 adapter.
시간/유효기간·안전 증빙은 호출자 책임이며 임계값을 이 모듈에서 정하지 않는다.
"""
from dataclasses import dataclass
import math


RESUME_QUESTION = '복구 확인이 끝났어요. 멈춘 단계부터 작업을 이어서 할까요?'


def safety_utterance(text):
    """내부 후보만 분류. 기존 intent enum/파서와 연결하지 않는다."""
    if not isinstance(text, str):
        return None
    return {'멈춰': 'stop', '정지해': 'stop', '복구해': 'recover',
            '상태 확인 후 복구해': 'recover', '재개해': 'resume',
            '이어서 실행해': 'resume'}.get(text.strip().rstrip('.!?').strip())


@dataclass(frozen=True)
class StoppedWork:
    session: str
    stop: str
    task: str
    step: str


@dataclass(frozen=True)
class Evidence:
    stopped: bool = False
    recovered: bool = False
    conditions: bool = False
    resume_point: bool = False
    fresh: bool = False

    def verified(self):
        return all(v is True for v in (self.stopped, self.recovered, self.conditions,
                                      self.resume_point, self.fresh))


@dataclass(frozen=True)
class Question:
    work: StoppedWork
    revision: int
    valid_until: float
    issued_at: float
    text: str = RESUME_QUESTION


class RecoveryConfirmation:
    """단일 호출자용 내부 상태. 질문/응답 후보는 B/C 허가·잠금 해제가 아니다.

    호출 순서 직렬화와 세션/순서값의 진위·시계 기준은 후속 adapter 계약 대상.
    새 정지, 불명확한 증빙, TTS 실패/기한 만료 뒤에는 기존 응답을 재사용하지 않는다.
    """
    def __init__(self, session):
        if not isinstance(session, str) or not session.strip():
            raise ValueError('session required')
        self.session = session
        self.revision = -1
        self.work = None
        self.asked = set()
        self.question = None
        self.finished_at = None

    @staticmethod
    def _time(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def _accept(self, work, revision):
        if (not isinstance(work, StoppedWork) or work.session != self.session or
                not all(isinstance(v, str) and v.strip() for v in
                        (work.stop, work.task, work.step)) or
                type(revision) is not int or revision <= self.revision):
            return False
        self.revision = revision
        return True

    def invalidate(self):
        self.question = None
        self.finished_at = None

    def stopped(self, work, revision):
        if not self._accept(work, revision):
            return False
        self.work = work
        self.invalidate()
        return True

    def recovered(self, work, revision, evidence, *, now, valid_until):
        if not self._accept(work, revision):
            return None
        if (work != self.work or not isinstance(evidence, Evidence) or not evidence.verified() or
                not self._time(now) or not self._time(valid_until) or valid_until <= now):
            self.invalidate()
            return None
        if work in self.asked:
            return None
        self.asked.add(work)
        self.question = Question(work, revision, valid_until, now)
        self.finished_at = None
        return self.question

    def delivered(self, question, *, now, success):
        if (question is not self.question or question is None):
            return False
        if (success is not True or not self._time(now) or not question.issued_at <= now < question.valid_until):
            self.invalidate()
            return False
        if self.finished_at is not None:
            return False
        self.finished_at = now
        return True

    def answer(self, text, question, *, captured_at, now, evidence):
        """captured_at은 발화/녹음 시작 시각. STT 완료 시각이 아니다."""
        if question is None or question is not self.question:
            return None
        if (self.finished_at is None or not self._time(captured_at) or not self._time(now) or
                not self.finished_at <= captured_at <= now < question.valid_until or
                not isinstance(evidence, Evidence) or not evidence.verified()):
            self.invalidate()
            return None
        if safety_utterance(text) != 'resume':
            self.invalidate()
            return None
        self.invalidate()  # 일회성 후보. 실행 실패 뒤에도 자동 재전송하지 않는다.
        return question.work
