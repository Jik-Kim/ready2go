"""실제 control decision→diagnostic 회귀. ROS/장치/권한 승인 시험은 아닙니다."""
import json
from types import SimpleNamespace
import pytest
from ready2go_voice.core.control_mapping import ControlDecision, SentControl
from ready2go_voice.core.diagnostics import DiagnosticFile
from ready2go_voice.core.recovery_confirmation import StoppedWork
from test_voice_ux_node import node, node_class


@pytest.mark.parametrize('operation', ['recover', 'resume', 'end_task'])
def test_actual_control_decision_diagnostic_handles_string_and_keeps_dict_metadata(node, node_class, tmp_path, operation):
    node.bind_request_source(lambda: True)
    node.cfg.update(diagnostic_detail=True, diagnostic_file=str(tmp_path/'diagnostic.jsonl'))
    console = []
    node.get_logger = lambda: SimpleNamespace(info=console.append)
    writer = node.diagnostic_file = DiagnosticFile(node.cfg, lambda _: None)
    node._diagnostic = node_class._diagnostic.__get__(node, node_class)
    sent = SentControl(intent=operation, work=StoppedWork('boot', 'event', 'run', 'step'),
        request_id='control-request', question_id=None, phase=None, answer=None,
        sent_at=node.now[0], generation=node.generation, candidate=None)
    result = ControlDecision(sent=sent, decision='hold', reason='current_condition_unconfirmed', revision=1)
    try:
        assert node._consume_control_decision(result) is None
        node._diagnostic({'event': 'request_decided', 'intent': {'intent': 'find_item',
            '_voice': {'request_id': 'dict-request', 'question_id': 'dict-question'}}})
    finally:
        writer.close()
    rows = [json.loads(line) for line in (tmp_path/'diagnostic.jsonl').read_text().splitlines()]
    assert rows[0]['event'] == 'control_decision' and rows[0]['intent'] == operation
    assert rows[0]['request_id'] == 'control-request'
    assert rows[1]['request_id'] == 'dict-request' and rows[1]['question_id'] == 'dict-question'
    assert any(operation in line for line in console)
    assert not node.published
