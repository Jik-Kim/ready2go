"""P1 의미 해석/축약 부탁 회귀. 실제 API·음성·로봇을 호출하지 않습니다."""
import json
import math
from types import SimpleNamespace
import pytest
from ready2go_voice.core.intent import IntentParser
from ready2go_voice.adapters.api import LangChainIntent


def candidate(target='eraser', confidence=.99):
    return {'intent': 'find_item', 'targets': [target], 'confidence': confidence}


@pytest.mark.parametrize('text', [
    '지우개 좀', '지우개 좀.', '지우개 좀요', '지우개 좀요!',
    '지우개를 좀요.', '혹시 지우개 하나만 좀?', '저한테 지우개 좀요',
])
def test_elliptical_request_reaches_llm_and_accepts_valid_result(ontology, schema, cfg, text):
    calls = []
    def llm(value, timeout):
        calls.append((value, timeout))
        return json.dumps(candidate())
    doc = IntentParser(ontology, schema, cfg, llm).parse(text)
    assert len(calls) == 1 and calls[0][0] == text and calls[0][1] > 0
    assert doc['intent'] == 'find_item' and doc['targets'] == ['eraser']
    assert doc['source']['llm_validation'] == 'passed'
    assert not doc['source']['fallback_used'] and doc['source']['execution_allowed']


@pytest.mark.parametrize('text', ['지우개 좀.', '지우개 좀요', '지우개를 하나만 좀요!'])
@pytest.mark.parametrize('failure', ['no_llm', 'error', 'timeout'])
def test_elliptical_request_has_narrow_fallback(ontology, schema, cfg, text, failure):
    def llm(*_):
        raise TimeoutError('mock') if failure == 'timeout' else RuntimeError('mock')
    doc = IntentParser(ontology, schema, cfg, None if failure == 'no_llm' else llm).parse(text)
    assert doc['intent'] == 'find_item' and doc['targets'] == ['eraser']
    assert doc['source']['fallback_used'] and doc['source']['execution_allowed']


def test_elliptical_policy_applies_to_all_registered_names_and_aliases(ontology, schema, cfg):
    parser = IntentParser(ontology, schema, cfg)
    for key, item in parser.items.items():
        for alias in [key, item['name_ko'], *item.get('aliases_ko', [])]:
            for ending in (' 좀.', ' 좀요!'):
                text = alias + ending
                for use_llm in (False, True):
                    parser.llm = (lambda *_, key=key: candidate(key)) if use_llm else None
                    doc = parser.parse(text)
                    if parser.mentioned(text) == {key}:
                        assert doc['targets'] == [key] and doc['intent'] == 'find_item', text
                        assert doc['source']['llm_called'] == use_llm
                    else:
                        assert doc['intent'] == 'clarify' and doc['targets'] == [], text


@pytest.mark.parametrize('text', [
    '혹시 지우개를 받을 수 있을까요?', '제가 쓰게 지우개를 좀 주시겠어요?',
    '지우개가 필요해서 그러는데 하나 받을 수 있나요?',
    '지우개 요청합니다', '지우개를 주시겠어요?',
])
def test_nonfallback_forms_use_llm_meaning_without_full_sentence_gate(ontology, schema, cfg, text):
    calls = []
    def llm(value, timeout):
        calls.append(value)
        return candidate()
    parser = IntentParser(ontology, schema, cfg, llm)
    assert not parser.explicit_request(text)  # 전체 문형 불일치도 정상 LLM 경로에서 수용
    doc = parser.parse(text)
    assert calls == [text]
    assert doc['intent'] == 'find_item' and doc['targets'] == ['eraser']
    assert doc['source']['llm_validation'] == 'passed' and not doc['source']['fallback_used']
    parser.llm = None
    held = parser.parse(text)
    assert held['intent'] == 'clarify' and not held['source']['execution_allowed']


@pytest.mark.parametrize('text', [
    '지우개', '지우개.', '그거 좀', '그거 좀요.', '사과 좀',
    '지우개랑 립밤 좀', '지우개 가져오지 마', '지우개 좀 가져오지 마',
    '지우개 좀 가져다주지 마요', '지우개 안 찾아도 돼', '지우개가 필요 없어',
    '지우개가 안 필요한데 가져다줄래?', '지우개가 뭐야', '지우개 좀 설명해줘',
    '지우개 어디 있는지 알려줘', '지우개 좀이라고 말했어', '"지우개 좀"',
    '지우개 좀요라는 문장을 따라해줘', '지우개를 정리해줘', '지우개 던져줘',
    '지우개를 사람 손에 직접 건네줘', '지우개를 내 손에 놓아줘',
    '지우개를 책상 위에 놓아줘', '지우개를 강의실로 가져다줘',
    '지우개를 다른 서랍에 넣어줘', '나중에 지우개 좀', '지우개 어떻게 좀 해줘',
    '지우개 어쩌고', '지우개는 파란색이야',
])
@pytest.mark.parametrize('mode', ['offline', 'wrong_llm', 'error'])
def test_hold_contexts_cannot_execute_even_with_wrong_llm(ontology, schema, cfg, text, mode):
    def llm(*_):
        if mode == 'error':
            raise RuntimeError('mock')
        return candidate()
    parser = IntentParser(ontology, schema, cfg, None if mode == 'offline' else llm)
    doc = parser.parse(text)
    assert doc['intent'] in ('unknown', 'clarify') and doc['targets'] == [], text
    assert not doc['source']['execution_allowed']
    if len(parser.mentioned(text)) > 1:
        with pytest.raises(ValueError, match='발화에 명시된 물품과 불일치'):
            parser.validate(candidate(), text)
    else:
        held = parser.validate(candidate(), text)
        assert held['intent'] in ('unknown', 'clarify') and held['targets'] == [], text
    if text in ('지우개', '지우개.', '그거 좀', '그거 좀요.'):
        assert doc['intent'] == 'clarify' and not doc['source']['llm_called']


@pytest.mark.parametrize('raw', [
    '{invalid', candidate('apple'), candidate('lip_balm'), candidate(confidence=.1),
    candidate(confidence=math.nan), candidate(confidence=math.inf),
    {'intent': 'find_item', 'targets': ['eraser', 'car_key'], 'confidence': .99},
    {'intent': 'find_item', 'confidence': .99},
    {'intent': 'find_item', 'targets': ['eraser'], 'confidence': .99,
     'goals': [{'predicate': 'open', 'subject': 'drawer_top', 'value': True}]},
])
def test_new_llm_forms_still_reject_invalid_results_and_do_not_expand_fallback(ontology, schema, cfg, raw):
    doc = IntentParser(ontology, schema, cfg, lambda *_: raw).parse('혹시 지우개를 받을 수 있을까요?')
    assert doc['source']['llm_validation'] == 'failed'
    unregistered = isinstance(raw, dict) and raw.get('targets') == ['apple']
    assert doc['source']['fallback_used'] is (not unregistered)
    assert doc['intent'] == ('unknown' if unregistered else 'clarify') and doc['targets'] == []
    assert not doc['source']['execution_allowed']


@pytest.mark.parametrize('kind', ['unknown', 'clarify'])
def test_llm_hold_on_elliptical_request_is_not_overridden_by_fallback(ontology, schema, cfg, kind):
    doc = IntentParser(ontology, schema, cfg,
                       lambda *_: {'intent': kind, 'targets': [], 'confidence': .99}).parse('지우개 좀')
    assert doc['intent'] == kind and doc['targets'] == []
    assert doc['source']['llm_validation'] == 'passed' and not doc['source']['fallback_used']


def test_actual_prompt_pipeline_receives_elliptical_request_and_shared_policy(ontology, schema, cfg, monkeypatch):
    sdk = pytest.importorskip('langchain_openai')
    from langchain_core.runnables import RunnableLambda
    captured = {}
    class LLM:
        def __init__(self, **kwargs): captured['init'] = kwargs
        def bind(self, **kwargs):
            captured['bind'] = kwargs
            def answer(prompt):
                captured['messages'] = prompt.to_messages()
                return SimpleNamespace(content=json.dumps(candidate()))
            return RunnableLambda(answer)
    monkeypatch.setattr(sdk, 'ChatOpenAI', LLM)
    llm = LangChainIntent(cfg, ontology['world']['items'])
    doc = IntentParser(ontology, schema, cfg, llm).parse('지우개 좀요.')
    system, human = captured['messages']
    assert human.content == '지우개 좀요.'
    assert '특정 문형에 한정하지' in system.content and '축약 부탁' in system.content
    assert '모든 등록 이름/별칭' in system.content and 'car_key' in system.content
    assert '정보 질문' in system.content and '인용' in system.content and '부정' in system.content
    assert captured['init']['max_retries'] == 0 and captured['init']['temperature'] == 0
    assert captured['bind']['response_format']['json_schema']['strict']
    assert doc['intent'] == 'find_item' and doc['source']['llm_validation'] == 'passed'
