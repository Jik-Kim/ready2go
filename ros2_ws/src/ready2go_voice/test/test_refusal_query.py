import copy
import pytest
from ready2go_knowledge.core import refusal_reasons
from ready2go_voice.core.runner_speech import required_texts
from test_voice_ux_node import node, node_class


def failed_status():
    return {'phase': 'idle', 'boot_id': 'boot', 'seq': 1, 'halt': None,
        'accepted': {'request_id': 'req', 'run_id': 'run', 'task_id': 'find_item'},
        'last': {'run_id': 'run', 'overall_status': 'FAILED', 'failure': {
            'run_id': 'run', 'boot_id': 'boot', 'code': 'NEIGHBOR_TOO_CLOSE',
            'step': 'm1', 'action': 'nudge_object', 'case_id': 'cluster_front_wall',
            'strategy': 'impossible', 'text': 'untrusted remote text'}}}


@pytest.mark.parametrize('change', ['running', 'invalid_phase', 'old_run', 'old_boot',
    'other_accepted', 'missing_accepted', 'missing_failure', 'aborted', 'suspended', 'completed', 'blank_run'])
def test_failure_identity_and_terminal_boundaries(change):
    from ready2go_voice.core.runner_speech import refusal_answer
    status = failed_status()
    if change == 'running': status['phase'] = 'running'
    elif change == 'invalid_phase': status['phase'] = 'unknown'
    elif change == 'old_run': status['last']['failure']['run_id'] = 'old'
    elif change == 'old_boot': status['last']['failure']['boot_id'] = 'old'
    elif change == 'other_accepted': status['accepted']['run_id'] = 'new'
    elif change == 'missing_accepted': status.pop('accepted')
    elif change == 'missing_failure': status['last']['failure'] = None
    elif change == 'blank_run':
        status['accepted']['run_id'] = status['last']['run_id'] = status['last']['failure']['run_id'] = ''
    else: status['last']['overall_status'] = change.upper()
    assert refusal_answer(status) is None


@pytest.mark.parametrize('mode', ['pick', 'task_error', 'unknown_case', 'nudge', 'missing_case', 'null_case'])
def test_verified_failure_uses_existing_factory_fallback(mode):
    from ready2go_voice.core.runner_speech import refusal_answer
    from ready2go_runner.core import failure_speech
    status = failed_status(); failure = status['last']['failure']
    if mode == 'pick': failure.update(case_id=None, strategy=None, action='pick_object')
    elif mode == 'task_error': failure.update(case_id=None, strategy=None, text=None, code='NO_FREE_SPACE', action='place_object')
    elif mode == 'unknown_case': failure['case_id'] = 'unknown'
    elif mode == 'nudge': failure['strategy'] = 'nudge'
    elif mode == 'missing_case': failure.pop('case_id')
    else: failure['case_id'] = None
    assert refusal_answer(status) == failure_speech.text(failure['code'], failure['action'])


def test_latest_decision_can_change_without_replacing_accepted_failure():
    from ready2go_voice.core.runner_speech import refusal_answer
    status = failed_status()
    for decision in ('status', 'cancel', 'reject'):
        status['last_intent'] = {'decision': decision, 'run_id': None}
        assert refusal_answer(status) == refusal_reasons.text('cluster_front_wall', 'impossible')


def test_actual_callback_and_tts_respects_source_sequence_and_restart(node):
    import json
    from types import SimpleNamespace
    from test_runtime_322 import memory_node, answer
    from test_c_control_wire import INFO
    endpoints, _, _, _ = memory_node(node)
    packet = failed_status()
    def receive(doc):
        node._runner_status_with_info(SimpleNamespace(data=json.dumps(doc)), dict(INFO))
    receive(packet)
    expected = refusal_reasons.text('cluster_front_wall', 'impossible')
    assert answer(node, '왜 못 꺼내?') == expected
    older = copy.deepcopy(packet); older['seq'] = 0; older['accepted']['run_id'] = 'other'
    receive(older)
    assert answer(node, '왜 안 가져와?') == expected
    packet['seq'] = 2; packet['accepted']['run_id'] = 'new'
    receive(packet)
    assert answer(node, '왜 멈췄어?') == refusal_reasons.unknown_text()
    packet['seq'] = 1; packet['boot_id'] = 'new-boot'; packet['accepted']['run_id'] = 'run'
    receive(packet)
    assert answer(node, '왜 멈췄어?') == refusal_reasons.unknown_text()
    endpoints['/runner/status'] = []
    assert answer(node, '왜 멈췄어?') == refusal_reasons.unknown_text()
    assert not node.published


def test_queued_answer_is_canceled_when_latest_accepted_run_changes(node):
    import json
    import threading
    from types import SimpleNamespace
    from test_runtime_322 import memory_node
    from test_c_control_wire import INFO
    memory_node(node)
    packet = failed_status()
    node._runner_status_with_info(SimpleNamespace(data=json.dumps(packet)), dict(INFO))
    node.deliver(node.session.text('왜 못 꺼내?', node.generation))
    notice, node.pending_notice = node.pending_notice, None
    assert notice.kind == 'readonly_query'
    # Even if another accepted run produces the same generic answer later,
    # the old read's authority must not survive that accepted-run boundary.
    packet['seq'] += 1; packet['accepted']['run_id'] = 'new'
    node._runner_status_with_info(SimpleNamespace(data=json.dumps(packet)), dict(INFO))
    before = list(node.texts)
    node._play_notice(notice, threading.Event())
    assert node.texts == before and not node.published


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
