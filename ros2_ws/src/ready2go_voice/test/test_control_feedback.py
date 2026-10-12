"""승인된 더미 전환의 실제 E 메서드 검사. 장치·API·물리 증거가 아닙니다."""
import json
from dataclasses import replace
from types import SimpleNamespace
import pytest
from test_voice_ux_node import node_class, node
from test_stop_cancel_hotfix import _dummy, _accept
from test_safety_exchange import STT, audio
from ready2go_voice.core.recovery_confirmation import Evidence


def stopped_bridge(node, monkeypatch):
    bridge, events = _dummy(monkeypatch)
    bridge.voice = node
    node.cfg.update(request_run_enabled=True, audio_enabled=True)
    node.place_test_devices = True
    node.bind_request_source(lambda: bridge.active)
    node.bind_safety_sender(bridge.safety_event)
    _accept(bridge, 'original')
    with node.submit_lock:
        node._stop_locked(node.session.text('멈춰', node.generation))
    bridge.intent(SimpleNamespace(data=json.dumps({'intent': 'cancel'})))
    return bridge


def play(node, bridge, *, restop=False):
    mode, token = node.safety_pending
    assert mode == 'feedback'
    node.safety_pending = None
    cancel = node.safety_cancel
    def say(text, **kw):
        node.texts.append(text)
        kw['on_start'](dict(tts_started_monotonic=node.now[0], tts_start_basis='portaudio_first_dac', tts_mock=True))
        if restop:
            with node.submit_lock:
                node._stop_locked(node.session.text('멈춰', node.generation))
            bridge.intent(SimpleNamespace(data=json.dumps({'intent': 'cancel'})))
        kw['on_timing'](dict(playback_ended_monotonic=node.now[0], playback_end_basis='portaudio_finished_callback'))
    node.tts.speak = say  # 실제 Voice._say와 재생 문구 추적도 함께 실행합니다.
    node._safety_feedback_play(token, cancel, bridge.safety_event)
    if node.control_feedback is token:
        node.control_feedback = None
    node.safety_activity.clear()
    node.busy.clear()


def command(node, bridge, text):
    base = node.now[0]
    node.session.stt = STT(text, node.now)
    node.now[0] = base + 3
    recording = replace(audio(), recording_started_monotonic=base + 1,
                        recording_ended_monotonic=base + 1.5)
    return node._safety_recording(recording, bridge.work)  # 새 cancel/SDK/ACK 실제 입력 경로


def test_recover_notice_fresh_resume_running_then_complete(node, monkeypatch):
    bridge = stopped_bridge(node, monkeypatch)
    work, payload = bridge.work, dict(bridge.accepted_payload)
    command(node, bridge, '복구해')
    assert node.safety_exchange.policy.question is None
    play(node, bridge)
    assert bridge.work == work and node.notice_policy.phase == 'halted'
    assert command(node, bridge, '응') is None
    play(node, bridge)  # 단순 동의는 실패 안내뿐이며 재개 권한이 없습니다.
    assert bridge.work == work and node.notice_policy.phase == 'halted'
    command(node, bridge, '이어서 해')
    assert bridge.work == work and node.notice_policy.phase == 'halted'
    play(node, bridge)
    assert bridge.work is None and node.notice_policy.phase == 'running'
    assert bridge.accepted_payload['targets'] == payload['targets']
    assert bridge.accepted_payload['request_id'] != payload['request_id']
    assert bridge.complete() is True
    assert node.notice_policy.phase == 'idle'


def test_explicit_end_notice_idle_then_new_request(node, monkeypatch):
    bridge = stopped_bridge(node, monkeypatch)
    command(node, bridge, '종료해')
    assert bridge.work is not None and node.safety_exchange.policy.work == bridge.work
    play(node, bridge)
    assert bridge.work is None and node.notice_policy.phase == 'idle'
    _accept(bridge, 'eraser-new')
    assert bridge.first_action == (bridge.run, node.generation)


@pytest.mark.parametrize('text', ['이어서 해', '종료해'])
def test_restop_during_acceptance_never_applies_stale_transition(node, monkeypatch, text):
    bridge = stopped_bridge(node, monkeypatch)
    if text == '이어서 해':
        bridge.stopped_fixture(bridge.work, bridge.revision + 1, Evidence(True, True, True, True, True))
    command(node, bridge, text)
    play(node, bridge, restop=True)
    assert bridge.work is not None and node.notice_policy.phase == 'halted'
    assert bridge.first_action is None and not bridge.complete()


def test_actual_session_recognition_failure_queues_tts_and_retains_work(node, monkeypatch):
    bridge = stopped_bridge(node, monkeypatch)
    assert command(node, bridge, '종류') is None
    assert node.safety_pending[1]['kind'] == 'failed'
    play(node, bridge)
    assert node.texts and bridge.work is not None and node.notice_policy.phase == 'halted'
    assert node._quiet_stopped()


def test_recovery_feedback_does_not_replace_valid_question(node, monkeypatch):
    bridge = stopped_bridge(node, monkeypatch)
    bridge.stopped_fixture(bridge.work, bridge.revision + 1, Evidence(True, True, True, True, True))
    q = node.safety_offer(bridge.work, bridge.revision + 1, bridge.evidence, valid_state=True, valid_until=node.now[0] + 20)
    assert q is not None
    pending = node.safety_pending
    assert node.safety_feedback(bridge.work, 'recover') is None
    assert node.safety_pending == pending and node.safety_exchange.current(q)


def test_missing_recovery_condition_queues_tts_and_keeps_halted(node, monkeypatch):
    bridge = stopped_bridge(node, monkeypatch)
    command(node, bridge, '이어서 해')  # recovered/conditions/resume_point 미확인
    assert node.safety_pending[1]['kind'] == 'failed'
    assert any(d.get('reason', '').startswith('evidence_missing:') for d in node.diagnostics)
    play(node, bridge)
    assert node.texts and bridge.work is not None and node.notice_policy.phase == 'halted'
    assert bridge.first_action is None


@pytest.mark.parametrize('reason', ['NO_SPEECH', 'empty_transcript', 'not_explicit_stop'])
def test_routine_stop_hold_quiet_console_retains_each_detail(node, node_class, tmp_path, reason):
    from ready2go_voice.core.diagnostics import DiagnosticFile
    path = tmp_path / 'diagnostic.jsonl'
    node.cfg.update(diagnostic_detail=True, diagnostic_file=str(path))
    node.diagnostic_file = DiagnosticFile(node.cfg, lambda text: None)
    console = []
    node.get_logger = lambda: SimpleNamespace(info=console.append, warning=console.append)
    try:
        for _ in range(3):
            node_class._diagnostic(node, dict(event='stop_audio_held', reason=reason, capture_kind='stop'))
        assert console == []
        node_class._diagnostic(node, dict(event='stop_audio_held', reason='TimeoutError'))
        node_class._diagnostic(node, dict(event='safety_stt_result', text='종료해'))
        assert any('TimeoutError' in line for line in console)
        assert any('종료해' in line for line in console)
    finally:
        node.diagnostic_file.close()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert sum(row.get('reason') == reason for row in rows) == 3
    assert any(row.get('text') == '종료해' for row in rows)
