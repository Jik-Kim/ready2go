"""P1 단일 물품 해석. LLM 출력도 기존 계약과 온톨로지에 재검증합니다."""
import json
import math
import re
import time
from jsonschema import Draft7Validator
from .deadline import DeadlineCall


P1 = {'find_item', 'cancel', 'status', 'unknown', 'clarify'}


def normalize(text):
    return re.sub(r'\s+', '', str(text).lower())


def intent(kind, targets=(), confidence=1.0, question=None):
    doc = {'intent': kind, 'targets': list(targets), 'confidence': confidence}
    if question:
        doc['clarify_question'] = question
    return doc


class IntentParser:
    def __init__(self, ontology, schema, cfg, llm=None, clock=time.monotonic):
        self.items = ontology['world']['items']
        self.validator = Draft7Validator(schema)
        self.cfg, self.llm, self.clock = cfg, llm, clock
        self.calls = DeadlineCall()
        self.aliases = {}
        for key, item in self.items.items():
            for alias in [key, item['name_ko'], *item.get('aliases_ko', [])]:
                self.aliases.setdefault(normalize(alias), set()).add(key)

    def _has(self, text, key):
        return any(normalize(p) in normalize(text) for p in self.cfg[key])

    def mentioned(self, text):
        value = normalize(text)
        return set().union(*(keys for alias, keys in self.aliases.items() if alias in value))

    def control(self, text):
        if normalize(text) in {normalize(p) for p in self.cfg['cancel_phrases']}:
            return intent('cancel')
        if normalize(text) in {normalize(p) for p in self.cfg['status_phrases']}:
            return intent('status')
        return None

    def guard(self, text):
        if not str(text).strip():
            return intent('clarify', question='다시 말씀해 주세요.')
        if self._has(text, 'unsupported_patterns'):
            return intent('unknown', question='지금은 한 물품을 찾아 전달하는 요청만 지원합니다.')
        keys = self.mentioned(text)
        if len(keys) > 1:
            return intent('clarify', question='한 물품씩 요청해 주세요.')
        if len(keys) == 1 and not self._has(text, 'request_patterns'):
            return intent(self.cfg['bare_item_policy'], question='그 물품을 가져다드릴까요?')
        return None

    def fallback(self, text):
        guard = self.control(text) or self.guard(text)
        if guard:
            return guard
        keys = self.mentioned(text)
        if len(keys) == 1 and self._has(text, 'request_patterns'):
            return intent('find_item', sorted(keys))
        return intent('unknown', question='등록된 물품 하나를 요청해 주세요.')

    def validate(self, raw, text):
        doc = json.loads(raw) if isinstance(raw, str) else raw
        self.validator.validate(doc)
        if not math.isfinite(doc['confidence']):
            raise ValueError('유한 confidence 필요')
        if doc['intent'] not in P1:
            raise ValueError('P1 미지원 intent')
        targets = doc.get('targets', [])
        if doc['intent'] == 'find_item':
            if len(targets) != 1 or targets[0] not in self.items:
                raise ValueError('등록된 단일 물품 필요')
            if doc['confidence'] < self.cfg['min_confidence']:
                raise ValueError('확신도 미달')
            named = self.mentioned(text)
            if named and named != set(targets):
                raise ValueError('발화에 명시된 물품과 불일치')
        elif targets:
            raise ValueError('실행 보류/제어 intent에는 targets가 없어야 합니다')
        if doc.get('goals') or doc.get('query'):
            raise ValueError('P1 목표 계획 제외')
        if doc['intent'] in ('cancel', 'status') and not self.control(text):
            raise ValueError('제어 명령은 규칙으로만 확인합니다')
        # LLM source는 신뢰하지 않고 진단은 E가 생성합니다.
        return intent(doc['intent'], targets, doc['confidence'], doc.get('clarify_question'))

    def parse(self, text, deadline=None):
        started = self.clock()
        diag = {'stt_text': text, 'llm_called': False, 'llm_validation': 'not_called',
                'fallback_used': False, 'input_kind': 'text'}
        doc = self.control(text) or self.guard(text)
        if doc is None:
            if self.llm is not None:
                remaining = self.cfg['llm_timeout_sec']
                if deadline is not None:
                    remaining = min(remaining, deadline - self.clock())
                if remaining > 0:
                    diag['llm_called'] = True
                    try:
                        raw = self.calls.call(lambda: self.llm(text, remaining), remaining)
                        diag['llm_raw'] = raw
                        try:
                            doc = self.validate(raw, text)
                            diag['llm_validation'] = 'passed'
                        except Exception as exc:
                            # 예외 상세에 키가 포함될 수 있어 타입만 진단합니다.
                            diag['llm_validation'] = 'failed'
                            diag['llm_error'] = type(exc).__name__
                    except Exception as exc:
                        diag['llm_validation'] = 'not_returned'
                        diag['llm_error'] = type(exc).__name__
            if doc is None:
                doc = self.fallback(text)
                diag['fallback_used'] = True
        self.validator.validate(doc)
        diag['latency_ms'] = round((self.clock() - started) * 1000, 3)
        diag['execution_allowed'] = doc['intent'] == 'find_item'
        doc['source'] = diag
        return doc
