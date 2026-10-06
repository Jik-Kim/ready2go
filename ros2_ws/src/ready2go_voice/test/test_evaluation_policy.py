"""D draft SHA256 5995fc225c0a2cc78aa1c9264eee6a07518ad674ed4923763acf5017377aec84.
텍스트 회귀 전용. D 승인 상태/실음성 평가 결과는 변경하지 않습니다."""
import pytest
from ready2go_voice.core.intent import IntentParser


CASES = [
    ('TC-001', 'find_item', '지우개 찾아줘.'),
    ('TC-002', 'find_item', '지우개 좀 찾아줘.'),
    ('TC-003', 'find_item', '지우개 가져다줘.'),
    ('TC-004', 'find_item', '지우개 좀 가져다줄래?'),
    ('TC-005', 'find_item', '지우개 꺼내줘.'),
    ('TC-006', 'find_item', '위 서랍에 있는 지우개 꺼내줘.'),
    ('TC-007', 'find_item', '지우개가 필요한데 가져다줄래?'),
    ('TC-008', 'find_item', '지우개 찾아서 건네줘.'),
    ('TC-009', 'find_item', '지우개를 찾아서 가져와줘.'),
    ('TC-010', 'find_item', '지우개 하나 부탁해.'),
    ('TC-011', 'find_item', '혹시 지우개 좀 줄 수 있어?'),
    ('TC-012', 'find_item', '내게 지우개를 가져다줘.'),
    ('TC-013', 'find_item', '지우개를 찾아서 전달 트레이에 놓아줘.'),
    ('TC-014', 'find_item', '지우개 있으면 꺼내줘.'),
    ('TC-015', 'find_item', '서랍에서 지우개 찾아줘.'),
    ('TC-016', 'find_item', '지우개를 꺼내서 가져다줘.'),
    ('TC-017', 'find_item', '그 지우개 좀 가져와.'),
    ('TC-018', 'find_item', '지우개 하나만 꺼내줄래?'),
    ('TC-019', 'find_item', '지우개가 필요해.'),
    ('TC-020', 'find_item', '지우개 좀 부탁할게.'),
    ('TC-021', 'ambiguous', '지우개.'),
    ('TC-022', 'ambiguous', '그거 찾아줘.'),
    ('TC-023', 'ambiguous', '그거 가져와줘.'),
    ('TC-024', 'ambiguous', '저거 꺼내줘.'),
    ('TC-025', 'ambiguous', '물건 좀 찾아줘.'),
    ('TC-026', 'ambiguous', '서랍에 있는 거 가져다줘.'),
    ('TC-027', 'ambiguous', '필요한 걸 꺼내줘.'),
    ('TC-028', 'ambiguous', '이거 어떻게 좀 해줘.'),
    ('TC-029', 'ambiguous', '하나 가져다줘.'),
    ('TC-030', 'ambiguous', '위에 있는 거 줘.'),
    ('TC-031', 'unsupported', '연필 찾아줘.'),
    ('TC-032', 'unsupported', '볼펜 가져다줘.'),
    ('TC-033', 'unsupported', '가위 꺼내줘.'),
    ('TC-034', 'unsupported', '컵 가져다줘.'),
    ('TC-035', 'unsupported', '지우개를 책상 위에 놓아줘.'),
    ('TC-036', 'unsupported', '지우개를 원래 자리에 돌려놔줘.'),
    ('TC-037', 'unsupported', '지우개를 다른 서랍으로 옮겨줘.'),
    ('TC-038', 'unsupported', '서랍 안을 정리해줘.'),
    ('TC-039', 'unsupported', '지우개를 던져줘.'),
    ('TC-040', 'unsupported', '지우개를 사람 손에 직접 건네줘.'),
]


def parser_for(ontology, schema, cfg, mode, target='eraser'):
    def llm(*_):
        if mode == 'exception':
            raise RuntimeError('mock API error')
        return {'intent': 'find_item', 'targets': [target], 'confidence': .99}
    return IntentParser(ontology, schema, cfg, None if mode == 'rule' else llm)


@pytest.mark.parametrize('case_id,category,text', CASES)
@pytest.mark.parametrize('mode', ['rule', 'mock_llm', 'exception'])
def test_d_draft_text_answers(ontology, schema, cfg, case_id, category, text, mode):
    # 모의 LLM 환각으로 모든 발화에 eraser를 돌려줘도 비실행 문장은 실행 불가.
    parser = parser_for(ontology, schema, cfg, mode)
    doc = parser.parse(text)
    expected = {'find_item'} if category == 'find_item' else (
        {'clarify'} if category == 'ambiguous' else {'unknown', 'clarify'})
    assert doc['intent'] in expected, case_id
    assert doc['targets'] == (['eraser'] if category == 'find_item' else []), case_id
    assert doc['source']['execution_allowed'] == (category == 'find_item'), case_id
    if category == 'ambiguous':
        for kind in ('unknown', 'clarify', 'find_item'):
            raw = {'intent': kind, 'targets': ['eraser'] if kind == 'find_item' else [], 'confidence': .99}
            held = parser.validate(raw, text)
            assert held['intent'] == 'clarify' and held['targets'] == []


def test_normal_forms_generalize_to_registered_names_and_aliases(ontology, schema, cfg):
    parser = IntentParser(ontology, schema, cfg)
    normal = [text for _, category, text in CASES if category == 'find_item']
    for key, item in parser.items.items():
        for alias in [key, item['name_ko'], *item.get('aliases_ko', [])]:
            for form in normal:
                text = form.replace('지우개', alias)
                named = parser.mentioned(text)
                for mode in ('rule', 'mock_llm'):
                    doc = parser_for(ontology, schema, cfg, mode, key).parse(text)
                    if named == {key}:
                        assert doc['intent'] == 'find_item' and doc['targets'] == [key], text
                        assert doc['source']['execution_allowed'], text
                    else:
                        assert doc['intent'] == 'clarify' and doc['targets'] == [], text
                        assert not doc['source']['execution_allowed'], text


def test_colliding_alias_is_held(ontology, schema, cfg):
    import copy
    ontology = copy.deepcopy(ontology)
    ontology['world']['items']['car_key'].setdefault('aliases_ko', []).append('지우개')
    doc = parser_for(ontology, schema, cfg, 'mock_llm').parse('지우개 찾아서 건네줘')
    assert doc['intent'] == 'clarify' and doc['targets'] == []
    assert not doc['source']['execution_allowed']


@pytest.mark.parametrize('text', [
    '지우개 찾아서 건네주지 마.', '지우개 있으면 안 꺼내도 돼.',
    '내게 지우개를 가져다주지 마.', '지우개 하나 부탁하지 않을게.',
    '지우개 찾아서 전달 트레이에 놓지 마.', '지우개가 얼마인지 알려줄래?',
    '지우개 어디 있는지 알려줘.', '지우개 좀 부탁할게라고 말했어.',
    '"지우개 찾아서 건네줘"', '지우개를 사람 손에 직접 건네줘.',
    '지우개 찾아서 내 손에 놓아줘.', '지우개 찾아서 책상 위에 놓아줘.',
    '지우개를 원래 자리에 돌려놔줘.', '지우개를 던져줘.',
    '지우개랑 립밤 하나 부탁해.', '글씨 지우는 물건 좀 부탁해.',
    '연필 찾아서 건네줘.', '아무거나 찾아서 건네줘.',
])
@pytest.mark.parametrize('mode', ['rule', 'mock_llm', 'exception'])
def test_extended_forms_preserve_nonexecution_context(ontology, schema, cfg, text, mode):
    doc = parser_for(ontology, schema, cfg, mode).parse(text)
    assert doc['intent'] in ('unknown', 'clarify') and doc['targets'] == []
    assert not doc['source']['execution_allowed']


@pytest.mark.parametrize('mode', ['hallucination', 'low_confidence', 'invalid_json', 'timeout'])
def test_extended_normal_fallback_revalidates_named_target(ontology, schema, cfg, mode):
    def llm(*_):
        if mode == 'timeout':
            raise TimeoutError('mock deadline')
        if mode == 'invalid_json':
            return '{invalid'
        return {'intent': 'find_item', 'targets': ['lip_balm' if mode == 'hallucination' else 'eraser'],
                'confidence': .1 if mode == 'low_confidence' else .99}
    doc = IntentParser(ontology, schema, cfg, llm).parse('지우개 찾아서 건네줘.')
    assert doc['intent'] == 'find_item' and doc['targets'] == ['eraser']
    assert doc['source']['fallback_used'] and doc['source']['execution_allowed']


@pytest.mark.parametrize('text', ['그거.', '저거', '물건', '하나', '찾아줘', '꺼내줘', '건네줘'])
@pytest.mark.parametrize('mode', ['rule', 'mock_llm', 'exception'])
def test_bare_generic_or_missing_target_is_always_clarify(ontology, schema, cfg, text, mode):
    doc = parser_for(ontology, schema, cfg, mode).parse(text)
    assert doc['intent'] == 'clarify' and doc['targets'] == []
    assert not doc['source']['execution_allowed']
