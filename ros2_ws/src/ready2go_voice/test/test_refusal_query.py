import pytest
from ready2go_knowledge.core import refusal_reasons
from ready2go_voice.core.runner_speech import required_texts
from test_voice_ux_node import node, node_class


@pytest.mark.parametrize('question', ['왜 멈췄어?', '왜 안 가져와?', '왜 못 꺼내?', '왜 못 꺼내요?'])
def test_refusal_question_uses_actual_readonly_route_without_execution(node, question):
    node.parser.llm = lambda *args: pytest.fail('No LLM for refusal query')
    # Unconfirmed private/proposed fields must not be consumed.
    node.parser.status_provider = lambda: {'status': {'last': {'failure': {
        'case_id': 'standing', 'strategy': 'impossible', 'text': 'untrusted'}}}}
    doc = node.session.text(question)
    assert doc['intent'] == 'status'
    assert doc['_voice']['readonly_query']
    assert doc['_voice']['final_text'] == refusal_reasons.unknown_text()
    assert doc['source']['execution_allowed'] is False
    assert doc['source']['llm_called'] is False
    assert not doc['targets']


def test_node_prepare_shared_required_texts_contains_catalog(cfg):
    assert set(refusal_reasons.texts()) <= set(required_texts(cfg, []))


def test_beyond_reach_is_in_node_prepare_shared_prefill(cfg, ontology):
    from ready2go_voice.core.tts_prefill import prefill_texts
    text = refusal_reasons.text('beyond_reach', 'impossible')
    assert text in required_texts(cfg, [])
    assert text in prefill_texts(cfg, ontology['world']['items'].values())
