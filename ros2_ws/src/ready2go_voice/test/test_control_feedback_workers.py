"""실제 진단/작업자/웨이크 연결 회귀. 장치·SDK·ROS 전송만 모의입니다."""
from contextlib import contextmanager
from dataclasses import replace
import io
import json
import logging
import queue
import threading
from types import MethodType, SimpleNamespace
import pytest
from test_voice_ux_node import node_class, node
from test_control_feedback import stopped_bridge
from test_safety_exchange import audio
from ready2go_voice.core.diagnostics import DiagnosticFile


@pytest.fixture
def live_boundary(node, node_class, monkeypatch, tmp_path):
    node.requests = queue.Queue(maxsize=1)
    node.request_running = None
    node.control_feedback = node.pending_resume = node.pending_task_end = None
    node.stop_listener = node.stop_processor = None
    node.stop_captures = queue.Queue(maxsize=1)
    node.cfg.update(recording_mode='fixed', input_device=None, diagnostic_detail=True,
                    diagnostic_file=str(tmp_path / 'diagnostic.jsonl'))
    console = io.StringIO()
    logger = logging.Logger('voice_worker_regression')
    logger.addHandler(logging.StreamHandler(console))
    node.get_logger = lambda: logger
    node._diagnostic = MethodType(node_class._diagnostic, node)
    node.session.progress = lambda **doc: node._diagnostic(doc)
    node.session.parser.llm = None
    node.session.speech_gate = SimpleNamespace(check=lambda *a, **kw: True)
    fault = [False]
    queued = threading.Event()
    class Writer(DiagnosticFile):
        def emit(self, doc):
            failure_event = fault[0] if isinstance(fault[0], str) else 'control_feedback_queued'
            if fault[0] and doc.get('event') == failure_event:
                fault[0] = False
                raise OSError('injected diagnostic output boundary')
            super().emit(doc)
            if doc.get('event') == 'control_feedback_queued':
                queued.set()
    writer = node.diagnostic_file = Writer(node.cfg, logger.warning)
    bridge = stopped_bridge(node, monkeypatch)
    def publish(doc):  # ROS 전송 어댑터만 모의, 실제 더미 수신 메서드 실행
        node.published.append(doc)
        bridge.intent(SimpleNamespace(data=json.dumps(doc)))
    node._publish = publish
    device = SimpleNamespace(inputs=queue.Queue(), wake_ready=threading.Event(),
        text=None, entered=threading.Event(), release=threading.Event(), fail=False)
    class Shared:
        _closed = False
        def start(self): pass
        def close(self): self._closed = True
        @contextmanager
        def stream(self):
            yield SimpleNamespace(begin_capture=lambda boundary: node.now[0])
    node.shared_input = Shared()
    class Wake:
        last_score = .9
        def __init__(self, *a, **kw): pass
        @contextmanager
        def stream(self):
            yield SimpleNamespace(begin_capture=lambda boundary: node.now[0])
        def wait(self, stream, stop, paused):
            if paused():
                return False
            device.wake_ready.set()
            text = device.inputs.get(timeout=5)  # 시험 종료 신호/Event 대기; 실장치 없음
            device.wake_ready.clear()
            if text is None or stop.is_set():
                return False
            device.text = text
            return True
    class Microphone:
        def __init__(self, *a, **kw): pass
        def _fixed_shared(self, stream, stop, paused, **kw):
            start = node.now[0] + 1
            node.now[0] = start + 2
            return replace(audio(), recording_started_monotonic=start,
                           recording_ended_monotonic=start + .5)
        def record(self, stream, stop, paused, **kw):
            stop.wait()  # 독립 stop 장치 모의는 종료 Event까지 대기합니다.
            raise InterruptedError('녹음 중단')
    class SDK:
        supports_request_boundary = True
        def transcribe(self, path, timeout, *, before_request=None):
            if before_request is not None:
                assert before_request(node.now[0])
            return device.text
    node.session.stt = SDK()
    def speak(text, **kw):
        node.texts.append(text)
        kw['on_start'](dict(tts_started_monotonic=node.now[0], tts_start_basis='portaudio_first_dac', tts_mock=False))
        device.entered.set()
        assert device.release.wait(5)
        if device.fail:
            device.fail = False
            raise RuntimeError('injected TTS device failure')
        if kw['cancel'].is_set():
            raise InterruptedError('TTS_CANCELED')
        kw['on_timing'](dict(playback_ended_monotonic=node.now[0], playback_end_basis='portaudio_finished_callback'))
    node.tts.speak = speak
    monkeypatch.setitem(node_class._listen.__globals__, 'WakeAudio', Wake)
    monkeypatch.setitem(node_class._listen.__globals__, 'Recorder', Microphone)
    threads = [threading.Thread(target=fn, daemon=True) for fn in (node._work, node._safety_work, node._listen)]
    for t in threads: t.start()
    def send(text):
        assert device.wake_ready.wait(5), '실제 _listen의 다음 wake 경계 미진입'
        queued.clear(); device.entered.clear(); device.release.clear()
        device.inputs.put(text)
    def settled():
        with node.place_condition:
            assert node.place_condition.wait_for(lambda:
                node.request_running is None and node.safety_running is None
                and node.safety_pending is None and node.control_feedback is None
                and not node.busy.is_set() and not node.safety_activity.is_set(), timeout=5)
        assert device.wake_ready.wait(5), '피드백 뒤 웨이크 재입력 불가'
        assert all(t.is_alive() for t in threads)
    harness = SimpleNamespace(node=node, bridge=bridge, device=device, writer=writer,
        fault=fault, queued=queued, console=console, send=send, settled=settled)
    try:
        yield harness
    finally:
        device.release.set(); node.stop_event.set(); device.inputs.put(None)
        with node.place_condition: node.place_condition.notify_all()
        for t in threads: t.join(5)
        for t in (node.stop_listener, node.stop_processor):
            if t is not None: t.join(5)
        writer.close()
        assert not any(t.is_alive() for t in threads)


def finish(h, text):
    h.send(text)
    assert h.device.entered.wait(5)
    assert h.node.busy.is_set() and h.node.safety_activity.is_set()
    assert h.node._voice_input_busy()
    h.device.release.set()
    h.settled()


def test_real_workers_recovery_resume_complete_and_end_new_request(live_boundary):
    h = live_boundary; node = h.node
    # dialog_lock으로 pending→running 인계를 고정하고 _work가 busy를 지우지 않는지 확인
    with node.dialog_lock:
        h.send('복구해')
        assert h.queued.wait(5)
        with node.place_condition:
            assert node.place_condition.wait_for(lambda: node.request_running is None, timeout=5)
        assert node.busy.is_set() and node.safety_activity.is_set()
        assert not h.device.entered.is_set()
    assert h.device.entered.wait(5)
    h.device.release.set(); h.settled()
    assert node.notice_policy.phase == 'halted' and h.bridge.work is not None
    finish(h, '이어서 해')
    assert node.notice_policy.phase == 'running' and h.bridge.work is None
    assert h.bridge.complete() and node.notice_policy.phase == 'idle'
    h.send('지우개 가져다줘')
    # 일반 요청의 실제 _work→_deliver→더미 수신 완료도 condition으로 대기
    with node.place_condition:
        assert node.place_condition.wait_for(lambda: h.bridge.run is not None and node.request_running is None, timeout=5)
    assert node.notice_policy.phase == 'running'
    node._text(SimpleNamespace(data='멈춰'))
    finish(h, '종료해')
    assert node.notice_policy.phase == 'idle' and h.bridge.work is None
    h.send('지우개 가져다줘')
    with node.place_condition:
        assert node.place_condition.wait_for(lambda: h.bridge.run is not None and node.request_running is None, timeout=5)
    h.writer.queue.join()
    rows = [json.loads(line) for line in h.writer.path.read_text().splitlines()]
    assert {d['kind'] for d in rows if d['event'] == 'control_feedback_queued' and d['reason'] is None} >= {'recover', 'resume', 'end'}
    assert not any(d['event'] in ('processing_failed', 'voice_diagnostic_failed') for d in rows)


@pytest.mark.parametrize('failure', ['queued_diagnostic', 'running_diagnostic', 'tts', 'restop_resume', 'restop_end', 'recognition_first'])
def test_real_worker_exception_cleanup_and_next_wake(live_boundary, failure):
    h = live_boundary; node = h.node
    if failure.startswith('restop'):
        finish(h, '복구해')
    if failure == 'queued_diagnostic':
        h.fault[0] = True
    if failure == 'running_diagnostic':
        h.fault[0] = 'control_feedback_delivered'
    if failure == 'tts':
        h.device.fail = True
    text = '이어서 해' if failure == 'restop_resume' else '종료해' if failure == 'restop_end' else '종류' if failure == 'recognition_first' else '복구해'
    h.send(text)
    if failure != 'queued_diagnostic':
        assert h.device.entered.wait(5)
        if failure.startswith('restop'):
            node._text(SimpleNamespace(data='멈춰'))
        h.device.release.set()
    h.settled()
    assert node.notice_policy.phase == 'halted' and h.bridge.work is not None
    assert node.pending_task_end is None and node.control_feedback is None
    # 자동 재시도가 아니라 새 실제 wake 입력을 보냅니다.
    finish(h, '복구해')
    assert node.notice_policy.phase == 'halted'
    secret = 'sk-proj-' + 'X' * 40
    node._diagnostic(dict(event='safety_stt_result', text='복구해 ' + secret, reason=None))
    h.writer.queue.join()
    detail = h.writer.path.read_text()
    assert secret not in detail and secret not in h.console.getvalue()
    assert '[REDACTED]' in detail
    assert '복구해 [REDACTED]' not in h.console.getvalue()  # raw independent transcript is detail-only
    if failure == 'queued_diagnostic':
        assert 'processing_failed' in detail and '처리 실패: OSError' in h.console.getvalue()
    if failure in ('tts', 'running_diagnostic'):
        assert 'safety_question_failed' in detail and '중단 후 안내 실패:' in h.console.getvalue()
