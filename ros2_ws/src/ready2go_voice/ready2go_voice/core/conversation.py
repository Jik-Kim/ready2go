"""E 로컬 확인 문맥. 공개 wire/Runner 수락·P2 사건 정책과 독립입니다."""
from dataclasses import dataclass
import math
import re
import threading
import uuid
from .intent import normalize_control, is_context_reply


@dataclass(frozen=True)
class Question:
    id: str
    target: str | None
    generation: int
    expires: float
    epoch: int


class Conversation:
    def __init__(self, cfg, clock):
        self.cfg, self.clock = cfg, clock
        self.lock = threading.RLock()
        self.pending = None
        self.epoch = 0
        self.boot = uuid.uuid4().hex
        self.sequence = 0

    def invalidate(self):
        with self.lock:
            self.pending = None
            self.epoch += 1

    def resolve(self, text, parser, generation, blocked=False, *, preserve_empty=False):
        """현재 질문의 답만 원문과 분리해 해석합니다. 후보 생성 직전 일회 소비합니다."""
        with self.lock:
            q = self.pending
            if blocked or (q and (q.generation != generation or self.clock() >= q.expires)):
                self.pending = q = None
            if q and preserve_empty and isinstance(text, str) and not text.strip():
                return text, None, None  # 현재 질문/기한/epoch 그대로. 성공한 빈 STT만 호출자가 허용합니다.
            value = normalize_control(text)
            reply = is_context_reply(text) or bool(q and q.target and parser.contextual_reply(text))
            keys = parser.mentioned(text)
            correction = bool(q and len(keys) == 1 and any(re.fullmatch(
                r'(?:아니|아니요)?[,，]?' + re.escape(alias) + r'(?:이야|야|말이야|로해줘|으로해줘|줘)?', value)
                for alias, matches in parser.aliases.items() if matches == keys))
            if q and (reply or correction):
                target = next(iter(parser.mentioned(text))) if correction and len(parser.mentioned(text)) == 1 else q.target
                if target is not None:
                    return parser.items[target]['name_ko'] + ' 가져다줘', q.id, target
                return text, None, None
            # 새 요청/부정/관련 없는 말도 이전 질문의 권한을 계속 보존하지 않습니다.
            self.pending = None
            self.epoch += 1
            return text, None, None

    def consume(self, question, generation):
        with self.lock:
            if (self.pending is not question or question is None or question.generation != generation
                    or self.clock() >= question.expires or self.epoch != question.epoch):
                return False
            self.pending = None
            return True

    def delivered(self, doc, generation, success, blocked=False):
        """실제 질문 TTS 완료 뒤에만 새 권한을 생성합니다. WAV 캐시로 복원하지 않습니다."""
        with self.lock:
            data = doc.get('_voice', {})
            if data.get('preserve_question_id'):
                q = self.pending
                if not (success and not blocked and q and q.id == data['preserve_question_id']
                        and q.generation == generation and self.clock() < q.expires):
                    self.pending = None
                return None  # 보존만; 새 question_ready/TTS 기준 기한을 만들지 않습니다.
            self.pending = None
            target = data.get('question_target')
            timeout = self.cfg.get('dialogue_timeout_sec')
            if not (success and not blocked and doc['intent'] == 'clarify' and (target or data.get('asks_delivery_target'))
                    and type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0):
                return None
            self.sequence += 1
            q = Question(f'{self.boot}:{self.sequence}', target, generation, self.clock() + timeout, self.epoch)
            self.pending = q
            data['question_id'] = q.id
            return q
