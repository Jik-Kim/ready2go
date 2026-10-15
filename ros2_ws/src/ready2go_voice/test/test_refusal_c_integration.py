"""Actual C #379 source -> status callback -> E readonly TTS; ROS/device mocked.

Run with C #379 source first in PYTHONPATH before its merge. The ordinary base
without failure_record skips these integration cases instead of fabricating C.
"""
import inspect
import json
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest
from ready2go_knowledge.core import refusal_reasons
from ready2go_runner.core import interpreter, failure_speech
from ready2go_voice.core.runner_speech import refusal_answer
from test_voice_ux_node import node, node_class


@pytest.fixture
def actual_c(node, monkeypatch):
    if not hasattr(interpreter, 'failure_record'):
        pytest.skip('C #379 actual failure snapshot implementation is not on this base')
    import test_c_control_wire as wire_module
    monkeypatch.setattr(wire_module, 'C_PACKAGE', Path(inspect.getfile(interpreter)).parents[2])
    monkeypatch.setenv('BACKEND', 'mock')
    wire = wire_module.Wire(node, suspended=False)
    return wire


@pytest.mark.parametrize('mode', ['registered', 'cleanup', 'pick', 'unknown', 'nonimpossible', 'task_error', 'stop'])
def test_actual_c_accepted_failure_status_question_callback_and_tts(actual_c, mode):
    wire = actual_c; node = wire.e
    task = {'task_id': 'find_item', 'sequence': [{'id': 'm1', 'action': 'nudge_object',
        'params': {'drawer_id': 'drawer_top', 'target': {'id': 'eraser#1'}, 'make_room': True}}],
        'finally': [{'id': 'f1', 'action': 'move_to_named_pose', 'params': {'pose_name': 'home'}}]}
    if mode == 'pick': task['sequence'][0].update(action='pick_object', params={'target': {'id': 'eraser#1'}})
    if mode == 'task_error':
        task['sequence'] = [{'id': 'm1', 'action': 'set_var', 'params': {
            'name': 'task_error', 'value': {'code': 'NO_FREE_SPACE', 'step': 'm1'}}}]
    wire.c.intents.tasks['find_item'] = task
    def execute(action, params, timeout=None):
        if mode == 'cleanup' and action == 'move_to_named_pose':
            return interpreter.ActionResult(False, {}, 'MOVE_FAILED')
        if action in ('nudge_object', 'pick_object'):
            if mode == 'stop': wire.c.runner.halt(source='voice')
            room = {'case_id': 'unknown' if mode == 'unknown' else 'cluster_front_wall',
                    'strategy': 'nudge' if mode == 'nonimpossible' else 'impossible'}
            output = {} if mode == 'pick' else {'make_room': room}
            return interpreter.ActionResult(False, output, 'CANCELED' if mode == 'stop' else 'NEIGHBOR_TOO_CLOSE')
        return interpreter.ActionResult(True, {})
    wire.c.runner.execute = execute
    request = {'intent': 'find_item', 'targets': ['eraser'], 'confidence': .99, 'request_id': 'origin'}
    wire.c._on_intent(SimpleNamespace(data=json.dumps(request)))
    assert wire.c._accepted['request_id'] == 'origin'
    accepted = dict(wire.c._accepted)
    # Execute the actual C scheduled _run, including failure_record and finally.
    scheduled = wire.started[-1]
    scheduled['target'](*scheduled['args'])
    wire.flush()
    result = wire.c._last
    assert wire.c.status()['accepted'] == accepted
    if mode == 'stop':
        assert result.overall_status in ('ABORTED', 'SUSPENDED') and result.failure is None
        expected = refusal_reasons.unknown_text()
    else:
        assert result.overall_status == 'FAILED'
        assert result.failure['run_id'] == accepted['run_id'] == result.run_id
        expected = (refusal_reasons.text('cluster_front_wall', 'impossible') if mode in ('registered', 'cleanup')
                    else failure_speech.text(result.failure['code'], result.failure['action']))
        assert refusal_answer(wire.c.status()) == expected
    # A real C status decision overwrites last_intent but leaves accepted intact.
    wire.c._on_intent(SimpleNamespace(data=json.dumps({'intent': 'status', 'targets': [], 'confidence': 1.})))
    wire.flush()
    assert wire.c._last_intent['decision'] == 'status'
    assert wire.c.status()['accepted'] == accepted
    # Existing higher-priority failure/stop warning must finish first. Do not
    # bypass the warning gate just to make the readonly answer play.
    warning, node.pending_notice = node.pending_notice, None
    if warning is not None:
        node._play_notice(warning, threading.Event())
    sent_before = list(wire.sent)
    doc = node.session.text('왜 못 꺼내?', node.generation)
    assert doc['_voice']['final_text'] == expected
    assert not doc['source']['execution_allowed'] and not doc['source']['llm_called']
    node.deliver(doc)
    notice, node.pending_notice = node.pending_notice, None
    assert notice.kind == 'readonly_query'
    node._play_notice(notice, threading.Event())
    assert wire.tts[-1] == expected and wire.sent == sent_before


def test_actual_c_contract_examples_match_e_consumption(actual_c):
    from ready2go_runner.core import runner_status
    root = Path(inspect.getfile(runner_status)).parents[5]
    cases = json.loads((root / 'contracts/examples/runner_status.json').read_text())['cases']
    selected = {c['case']: c['status'] for c in cases}
    for key in ('failed_with_refusal_reason', 'status_question_after_failure'):
        assert refusal_answer(selected[key]) == refusal_reasons.text('cluster_front_wall', 'impossible')
    task_error = selected['failed_task_error_without_reason']['last']['failure']
    assert refusal_answer(selected['failed_task_error_without_reason']) == failure_speech.text(task_error['code'], task_error['action'])
