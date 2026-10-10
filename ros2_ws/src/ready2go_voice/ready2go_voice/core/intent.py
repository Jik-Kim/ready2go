"""P1 단일 물품 해석. LLM 출력도 기존 계약과 온톨로지에 재검증합니다."""
import json
import math
import re
import time
from jsonschema import Draft7Validator
from .deadline import DeadlineCall


class InvalidIntent(ValueError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


class UnregisteredItem(ValueError):
    pass


P1 = {'find_item', 'cancel', 'status', 'unknown', 'clarify'}


def normalize(text):
    return re.sub(r'\s+', '', str(text).lower())


def normalize_control(text):
    # 정확 비교를 유지하고 끝 종결 기호만 허용합니다.
    return normalize(text).rstrip('.!?。？！')


def is_context_reply(text):
    """A reply needs a live question; the words themselves grant no target."""
    return normalize_control(text) in {'응', '네', '예', '맞아', '맞아요', '그걸로',
                                       '그거', '그거줘', '그걸로해줘'}


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
        if normalize_control(text) in {normalize_control(p) for p in self.cfg['cancel_phrases']}:
            return intent('cancel')
        if normalize_control(text) in {normalize_control(p) for p in self.cfg['status_phrases']}:
            return intent('status')
        return None

    def _request_form(self, text, target):
        """LLM 실패 시의 좁은 폴백 문형입니다. 정상 LLM 후보의 허용 목록이 아닙니다."""
        value = normalize_control(text)
        prefix = (r'(?:헬로로키|로키|저기)?(?:혹시)?'
                  r'(?:(?:저|나)(?:에게|한테)|내게)?(?:좀)?'
                  r'(?:위서랍에있는|서랍에서)?(?:그|이|저)?')
        particle = r'(?:을|를|이|가)?(?:하나|한개)?(?:만)?(?:좀)?'
        ending = r'(?:줘|주세요|줄래|줄래요|주실래요|주면좋겠어|주면좋겠어요|주시면좋겠어요)?'
        delivery = r'(?:가져와|가져다|가져|갖다|건네)' + ending
        action = (r'(?:(?:찾아|꺼내)' + ending + '|' + delivery +
                  r'|(?:찾아서|꺼내서)(?:' + delivery + r'|전달트레이에놓아' + ending + r')'
                  r'|줘|주세요|줄래|줄래요|주실래요|줄수있어|주면좋겠어|주면좋겠어요'
                  r'|필요해|필요해요|필요합니다|부탁해|부탁할게)')
        return bool(re.fullmatch(prefix + '(?:' + target + ')' + particle +
                                 r'(?:있으면|필요한데)?' + action, value))

    def _elliptical_request(self, text, target):
        # 사용자 승인: 단일 물품 + 좀/좀요는 가져오기 부탁. 문맥을 잘라내지 않습니다.
        prefix = (r'(?:헬로로키|로키|저기)?(?:혹시)?'
                  r'(?:(?:저|나)(?:에게|한테)|내게)?(?:그|이|저)?')
        return bool(re.fullmatch(prefix + '(?:' + target + ')' +
                                 r'(?:을|를|이|가)?(?:하나|한개)?(?:만)?좀(?:요)?',
                                 normalize_control(text)))

    def explicit_request(self, text):
        # 폴백 전용: 기존 긍정 전체 문형 + 승인된 축약 부탁을 등록 어휘에 적용합니다.
        target = '|'.join(re.escape(alias) for alias in self.aliases)
        return self._request_form(text, target) or self._elliptical_request(text, target)

    def ambiguous_request(self, text):
        target = r'그거|저거|이거|물건|하나|서랍에있는거|필요한걸|위에있는거'
        return (bool(re.fullmatch(target, normalize_control(text))) or
                self._request_form(text, target) or self._request_form(text, '') or
                self._elliptical_request(text, target) or
                bool(re.fullmatch(r'(?:그거|저거|이거)어떻게좀해줘', normalize_control(text))))

    def _unsupported_context(self, text):
        value = normalize_control(text)
        return self._has(text, 'unsupported_patterns') or bool(re.search(
            r'던(?:져|지)|정리|청소|반납|돌려(?:놔|놓|줘)|되돌|옮(?:겨|기)|'
            r'사람손|손(?:에|으로|바닥)|직접.*(?:손|건네)|'
            r'(?:책상|테이블|바닥|다른서랍|옆서랍|아래서랍).*'
            r'(?:놓|둬|두|넣|전달|건네|가져|갖다)|'
            r'(?<!전달트레이)(?:에|으로|로)(?:좀)?(?:놓|둬|두|넣|전달|건네|가져|갖다)|'
            r'지워(?:줘|주세요|줄래)|깎아|잘라', value))

    def _nonrequest_context(self, text):
        # 명백한 부정/정보/인용/불명확 문맥은 잘못된 LLM 후보에도 선제 보류합니다.
        value = normalize_control(text)
        negative = (r'않|지마(?:$|[.!?]|라|세요|요)|지말|'
                    r'(?:안|못)(?:찾|꺼내|가져|갖다|건네|받|주|줘|필요)|'
                    r'필요없|필요하지|싫|불필요|안돼|안되|빼고|제외')
        information = (r'뭐|무엇|얼마|어디|어떻게|설명|알려|알고|궁금|뜻|의미|정보|'
                       r'가격|색깔|어쩌|아마|글쎄|나중|내일|언젠가|만약|번역|따라해')
        quotation = r'예시|문장|표현|읽었|적었'
        # 인용/전언은 가져오기 요청 의미가 있는 경우에 한해 정상 LLM 판정으로 넘깁니다.
        if re.search(r'라고|라며|말했|말한|들었', value) and not re.search(r'가져|갖다|꺼내|찾아', value):
            return True
        if re.fullmatch(r'[\"\'“‘「『`].*[\"\'”’」』`]', value):
            return True
        return bool(re.search(negative + '|' + information + '|' + quotation, value))

    def _request_context(self, text):
        # 이름만으로 실행하지 않음. 요청/필요/받기/축약 부탁의 단서는 전체 문형과 다릅니다.
        # 이 단서만으로 실행하지 않고 정상 LLM의 의미 판정과 공통 검증을 함께 요구합니다.
        return bool(re.search(r'찾|꺼내|가져|갖다|건네|받|줘|줄|주(?:세|시|실|면|겠)|'
                              r'요청|부탁|필요|좀|쓰고싶|사용하고싶', normalize_control(text)))

    def guard(self, text):
        if not str(text).strip():
            return intent('clarify', question=self.cfg['clarify_prompts']['empty'])
        if self._unsupported_context(text):
            return intent('unknown', question='지금은 한 물품을 찾아 전달하는 요청만 지원합니다.')
        keys = self.mentioned(text)
        if len(keys) > 1:
            return intent('clarify', question=self.cfg['clarify_prompts']['multiple'])
        if len(keys) == 1:
            if normalize_control(text) in self.aliases:
                doc = intent('clarify', question=self.cfg['clarify_prompts']['bare'])
                doc['_voice'] = {'question_target': next(iter(keys))}
                return doc
            if self._nonrequest_context(text):
                return intent('clarify', question=self.cfg['clarify_prompts']['request'])
        if not keys and (is_context_reply(text) or self.ambiguous_request(text)):
            doc = intent('clarify', question=self.cfg['clarify_prompts']['missing_item'])
            doc['_voice'] = {'asks_delivery_target': True}
            return doc
        return None

    def fallback(self, text):
        guard = self.control(text) or self.guard(text)
        if guard:
            return guard
        keys = self.mentioned(text)
        if len(keys) == 1 and self.explicit_request(text):
            return intent('find_item', sorted(keys))
        if keys:
            return intent('clarify', question=self.cfg['clarify_prompts']['request'])
        return intent('unknown', question='등록된 물품 하나를 요청해 주세요.')

    def validate(self, raw, text):
        doc = json.loads(raw) if isinstance(raw, str) else dict(raw)
        doc.pop('response_text', None)  # 내부 후보 문장: 공개 계약의 clarify_question과 구분
        reason = doc.pop('rejection_reason', None)  # API-local, never a public intent field
        if reason is not None and (not isinstance(reason, str) or
                                   reason not in ('unregistered_item', 'unsupported_request')):
            raise InvalidIntent('invalid_rejection_reason', '지원되는 내부 사유 필요')
        if isinstance(doc, dict) and type(doc.get('confidence')) in (int, float) and not math.isfinite(doc['confidence']):
            raise InvalidIntent('nonfinite_confidence', '유한 confidence 필요')
        self.validator.validate(doc)
        if not math.isfinite(doc['confidence']):
            raise InvalidIntent('nonfinite_confidence', '유한 confidence 필요')
        if doc['intent'] not in P1:
            raise InvalidIntent('unsupported_intent', 'P1 미지원 intent')
        targets = doc.get('targets', [])
        if doc['intent'] == 'find_item':
            if len(targets) != 1:
                raise InvalidIntent('single_target_required', '등록된 단일 물품 필요')
            if targets[0] not in self.items:
                raise UnregisteredItem('등록되지 않은 물품')
            if doc['confidence'] < self.cfg['min_confidence']:
                raise InvalidIntent('low_confidence', '확신도 미달')
            named = self.mentioned(text)
            if named and named != set(targets):
                raise InvalidIntent('target_mismatch', '발화에 명시된 물품과 불일치')
        elif targets:
            raise InvalidIntent('targets_on_hold', '실행 보류/제어 intent에는 targets가 없어야 합니다')
        if reason is not None and doc['intent'] != 'unknown':
            raise InvalidIntent('rejection_reason_mismatch', 'unknown 보류에서만 사유 사용')
        if doc.get('goals') or doc.get('query'):
            raise InvalidIntent('p1_goal_or_query', 'P1 목표 계획 제외')
        if doc['intent'] in ('cancel', 'status') and not self.control(text):
            raise InvalidIntent('unconfirmed_control', '제어 명령은 규칙으로만 확인합니다')
        if doc['intent'] in ('find_item', 'unknown', 'clarify'):
            hold = self.guard(text)
            if hold:
                return hold
        if doc['intent'] == 'find_item':
            # 등록 키/확신도는 사용자의 물품·긍정 요청 확인을 대체하지 않습니다.
            if not self.mentioned(text) or not self._request_context(text):
                return intent('clarify', question=self.cfg['clarify_prompts']['unconfirmed'])
        if reason == 'unregistered_item' and self.mentioned(text):
            raise InvalidIntent('rejection_reason_mismatch', '등록 물품 발화와 미등록 사유 불일치')
        # LLM source는 신뢰하지 않고 진단은 E가 생성합니다.
        result = intent(doc['intent'], targets, doc['confidence'], doc.get('clarify_question'))
        if reason is not None:
            result['_voice'] = {'reason': reason}
        return result

    def parse(self, text, deadline=None):
        started = self.clock()
        diag = {'stt_text': text, 'llm_called': False, 'llm_validation': 'not_called',
                'fallback_used': False, 'input_kind': 'text'}
        from .response import final_response
        candidate = None
        stages = {'interpretation_started_monotonic': started}
        keys = self.mentioned(text)
        availability = bool(re.fullmatch(r'.+(?:되나|되나요|가능해|가능한가|가능해요|가능한가요|지원해|지원하나요)[?？.!]*', normalize_control(text)))
        doc = self.control(text) or self.guard(text)
        if availability:
            doc = intent('unknown')
            doc['_voice'] = {'availability': True, 'question_target': next(iter(keys)) if len(keys) == 1 else None,
                             'reason': 'availability_only' if len(keys) == 1 else 'unregistered_item'}
        if doc is None:
            if self.llm is not None:
                remaining = self.cfg['llm_timeout_sec']
                if deadline is not None:
                    remaining = min(remaining, deadline - self.clock())
                if remaining > 0:
                    diag['llm_called'] = True
                    stages['llm_started_monotonic'] = self.clock()
                    try:
                        raw = self.calls.call(lambda: self.llm(text, remaining), remaining)
                        stages['llm_result_monotonic'] = self.clock()
                        diag['llm_raw'] = raw
                        try:
                            decoded = json.loads(raw) if isinstance(raw, str) else raw
                            candidate = (decoded.get('response_text') if decoded.get('response_text') is not None else decoded.get('clarify_question')) if isinstance(decoded, dict) else None
                            doc = self.validate(raw, text)
                            diag['llm_validation'] = 'passed'
                        except UnregisteredItem:
                            diag.update(llm_validation='failed', llm_error='UnregisteredItem', validation_reason='unregistered_item')
                            doc = intent('unknown')
                            doc['_voice'] = {'reason': 'unregistered_item'}
                        except Exception as exc:
                            # 예외 상세에 키가 포함될 수 있어 타입만 진단합니다.
                            diag['llm_validation'] = 'failed'
                            diag['llm_error'] = type(exc).__name__
                            diag['validation_reason'] = (exc.reason if isinstance(exc, InvalidIntent) else
                                'invalid_json' if isinstance(exc, json.JSONDecodeError) else
                                'schema_mismatch' if type(exc).__name__ == 'ValidationError' else 'invalid_candidate_type')
                    except Exception as exc:
                        diag['llm_validation'] = 'not_returned'
                        diag['llm_error'] = type(exc).__name__
            if doc is None:
                doc = self.fallback(text)
                diag['fallback_used'] = True
        if doc['intent'] == 'clarify' and not doc.get('_voice', {}).get('question_target') and len(keys) == 1 and not self._nonrequest_context(text) and not self._unsupported_context(text):
            doc.setdefault('_voice', {})['question_target'] = next(iter(keys))
        doc.setdefault('_voice', {}).update(stages)
        if 'validation_reason' in diag:
            doc['_voice']['validation_reason'] = diag.pop('validation_reason')
        final_response(self, doc, candidate)
        self.validator.validate(doc)
        diag['latency_ms'] = round((self.clock() - started) * 1000, 3)
        diag['execution_allowed'] = doc['intent'] == 'find_item'
        doc['source'] = diag
        return doc


def clarify_prompt(cfg, question=None):
    prompts = cfg['clarify_prompts']
    return question if question in prompts.values() else prompts['general']
