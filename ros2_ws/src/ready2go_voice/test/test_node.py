"""노드 게이트 검사. 모의 재생 시각이며 실제 40문장/3초 측정이 아닙니다."""
import copy
import threading
import time
from types import SimpleNamespace
import pytest
pytest.importorskip('rclpy')
pytest.importorskip('ready2go_interfaces.action')
from ready2go_voice.nodes.voice_node import VoiceNode
from ready2go_voice.core.intent import IntentParser
from ready2go_voice.core.session import VoiceSession


class FakeTTS:
    def __init__(self):
        self.lock = threading.Lock()
        self.fail = False
        self.texts = []
    def speak(self, text, **kwargs):
        self.texts.append(text)
        if self.fail:
            raise RuntimeError('audio missing')
        stamp = {'tts_started_unix': 123, 'tts_started_monotonic': time.monotonic(),
                 'tts_start_basis': 'mock', 'tts_mock': True}
        kwargs['on_start'](stamp)
        return stamp


@pytest.fixture
def harness(cfg, ontology, schema):
    node = SimpleNamespace(cfg=cfg, parser=IntentParser(ontology, schema, cfg),
        stop_event=threading.Event(), request_cancel=threading.Event(), speaking=threading.Event(),
        submit_lock=threading.Lock(), generation=0, tts=FakeTTS(), published=[], diagnostics=[])
    node.session = VoiceSession(node.parser, cfg)
    node._publish = lambda doc: node.published.append(copy.deepcopy(doc))
    node._diagnostic = lambda doc: node.diagnostics.append(copy.deepcopy(doc))
    return node


def test_evaluation_never_publishes(harness):
    VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    VoiceNode._text(harness, SimpleNamespace(data='멈춰'))
    assert not harness.published
    assert any(d['event'] == 'tts_started' and d['source']['tts_mock'] for d in harness.diagnostics)


def test_tts_failure_does_not_publish_find_item(harness):
    harness.cfg['evaluation_mode'] = False
    harness.tts.fail = True
    VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    assert [d['intent'] for d in harness.published] == ['clarify']
    assert not harness.published[0]['source']['execution_allowed']


def test_cancel_blocks_pending_result_and_only_forwards_control(harness):
    harness.cfg['evaluation_mode'] = False
    pending = harness.parser.parse('지우개 찾아줘')
    VoiceNode._text(harness, SimpleNamespace(data='멈춰'))
    VoiceNode._deliver(harness, pending, 0)
    assert [d['intent'] for d in harness.published] == ['cancel']
    assert harness.request_cancel.is_set()


def test_execution_duplicate_publishes_once(harness):
    harness.cfg['evaluation_mode'] = False
    for _ in range(2):
        VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    assert len(harness.published) == 1
    assert len(harness.tts.texts) == 1
    assert harness.published[0]['source']['tts_start_basis'] == 'mock'


def test_ros_evaluation_topic_and_tts_action(cfg, tmp_path, monkeypatch):
    """독립 ROS 도메인에서 실제 topic/action 연결, API/장치만 모의."""
    import json
    import yaml
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from std_msgs.msg import String
    from ready2go_interfaces.action import Skill
    from conftest import ROOT
    monkeypatch.setenv('ROS_DOMAIN_ID', '166')
    monkeypatch.setenv('ROS_LOG_DIR', str(tmp_path/'ros_logs'))
    cfg['ontology_file'] = str(ROOT/'knowledge/robot_ontology.jsonld')
    cfg['intent_schema_file'] = str(ROOT/'contracts/intent.schema.json')
    path = tmp_path/'voice.yaml'; path.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    rclpy.init()
    voice = None
    peer = None
    executor = MultiThreadedExecutor(num_threads=4)
    thread = None
    try:
        voice = VoiceNode(parameter_overrides=[Parameter('config_file', value=str(path)),
                                               Parameter('evaluation_mode', value=True)])
        voice.tts = FakeTTS()
        voice.parser.llm = None  # 유료 호출 없음
        peer = Node('voice_test_peer')
        received = []
        subscription = peer.create_subscription(String, '/voice/intent', lambda msg: received.append(msg.data), 10)
        publisher = peer.create_publisher(String, '/voice/text_override', 10)
        client = ActionClient(peer, Skill, '/voice/speak')
        executor.add_node(voice); executor.add_node(peer)
        thread = threading.Thread(target=executor.spin, daemon=True); thread.start()
        def until(check):
            deadline = time.monotonic() + 4
            while not check() and time.monotonic() < deadline:
                time.sleep(.01)
            assert check()
        until(lambda: publisher.get_subscription_count() > 0)
        publisher.publish(String(data='지우개 찾아줘'))
        time.sleep(.2)
        assert not received  # 실제 ROS 발행도 평가모드에서 없음
        assert client.wait_for_server(timeout_sec=3)
        bad = Skill.Goal(); bad.params_json = '{}'
        future = client.send_goal_async(bad); until(future.done)
        assert not future.result().accepted
        good = Skill.Goal(); good.params_json = json.dumps({'text': '지우개'})
        future = client.send_goal_async(good); until(future.done)
        handle = future.result(); assert handle.accepted
        result = handle.get_result_async(); until(result.done)
        assert result.result().result.success
        assert json.loads(result.result().result.output_json)['tts_mock']
        voice.cfg['evaluation_mode'] = False  # 이 검사만의 격리된 모드 변경
        publisher.publish(String(data='지우개 찾아줘'))
        until(lambda: len(received) == 1)
        assert json.loads(received[0])['targets'] == ['eraser']
        client.destroy()
        peer.destroy_subscription(subscription)
    finally:
        if voice:
            voice.close()
        executor.shutdown(timeout_sec=2)
        if thread:
            thread.join(timeout=2)
        if voice:
            voice.destroy_node()
        if peer:
            peer.destroy_node()
        rclpy.try_shutdown()


@pytest.mark.parametrize('text', [
    '연필 찾아줘', '연필 자국 없애는 물건 가져다줘',
    '지우개 가져다주지 마', '지우개 안 찾아도 돼', '지우개가 얼마인지 알려줄래',
])
@pytest.mark.parametrize('use_llm', [False, True])
def test_execution_node_holds_unconfirmed_meaning(harness, text, use_llm):
    harness.cfg['evaluation_mode'] = False
    if use_llm:
        harness.parser.llm = lambda *_: {'intent': 'find_item', 'targets': ['eraser'], 'confidence': .99}
    doc = harness.parser.parse(text)
    VoiceNode._deliver(harness, doc, 0)
    assert harness.published
    assert all(d['intent'] in ('unknown', 'clarify') and d['targets'] == []
               and not d['source']['execution_allowed'] for d in harness.published)
    assert harness.tts.texts == [doc['clarify_question']]
    assert all('가져다드리겠습니다' not in t for t in harness.tts.texts)


@pytest.mark.parametrize('text,kind', [('멈춰.', 'cancel'), ('취소!', 'cancel'), ('지금 뭐 해?', 'status')])
def test_punctuated_control_fast_path(harness, text, kind):
    harness.cfg['evaluation_mode'] = False
    harness._submit = lambda *_: pytest.fail('control must bypass request queue')
    harness.parser.llm = lambda *_: pytest.fail('control must bypass API')
    VoiceNode._text(harness, SimpleNamespace(data=text))
    assert [doc['intent'] for doc in harness.published] == [kind]
    assert not harness.tts.texts
    assert harness.generation == (1 if kind == 'cancel' else 0)
    assert harness.request_cancel.is_set() == (kind == 'cancel')
    if kind == 'cancel':
        harness.parser.llm = None
        VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
        assert [doc['intent'] for doc in harness.published] == [kind]


def test_tts_failed_find_can_be_retried(harness):
    harness.cfg['evaluation_mode'] = False
    harness.tts.fail = True
    VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    harness.tts.fail = False
    VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    assert [doc['intent'] for doc in harness.published] == ['clarify', 'find_item']
    assert len(harness.tts.texts) == 2


def test_duplicate_window_expires_after_successful_publication(harness):
    harness.cfg['evaluation_mode'] = False
    now = [10.0]
    harness.session.clock = lambda: now[0]
    VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    now[0] += harness.cfg['duplicate_window_sec']
    VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    assert len(harness.published) == len(harness.tts.texts) == 2


def test_evaluation_duplicate_inputs_both_speak_without_publication(harness):
    for _ in range(2):
        VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    assert not harness.published
    assert len(harness.tts.texts) == 2
    assert sum(d['event'] == 'tts_started' for d in harness.diagnostics) == 2
    assert sum(d['event'] == 'intent' for d in harness.diagnostics) == 2
    assert harness.session._last is None


def test_publication_failure_does_not_consume_find(harness):
    harness.cfg['evaluation_mode'] = False
    publish = harness._publish
    def fail(_):
        raise RuntimeError('publication unavailable')
    harness._publish = fail
    with pytest.raises(RuntimeError):
        VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    assert harness.session._last is None
    harness._publish = publish
    VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    assert [doc['intent'] for doc in harness.published] == ['find_item']
    assert len(harness.tts.texts) == 2


def test_canceled_tts_does_not_consume_find(harness):
    harness.cfg['evaluation_mode'] = False
    speak = harness.tts.speak
    def cancel_during_tts(text, **kwargs):
        VoiceNode._text(harness, SimpleNamespace(data='취소!'))
        raise InterruptedError('cancelled')
    harness.tts.speak = cancel_during_tts
    VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    assert harness.session._last is None
    harness.request_cancel.clear()  # 다음 _submit의 기존 초기화 동작
    harness.tts.speak = speak
    VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), harness.generation)
    assert [doc['intent'] for doc in harness.published] == ['cancel', 'find_item']


def test_expired_confirmation_does_not_consume_find(harness):
    harness.cfg['evaluation_mode'] = False
    speak = harness.tts.speak
    def expire(*args, **kwargs):
        assert kwargs['start_deadline'] < time.monotonic()
        raise TimeoutError('late playback')
    harness.tts.speak = expire
    late = harness.parser.parse('지우개 찾아줘')
    late['source'].update(input_kind='audio', speech_ended_monotonic=time.monotonic() - 10)
    VoiceNode._deliver(harness, late, 0)
    harness.tts.speak = speak
    VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    assert [doc['intent'] for doc in harness.published] == ['clarify', 'find_item']


@pytest.mark.parametrize('text,kind', [
    ('지우개 찾아서 건네줘.', 'find_item'),
    ('지우개를 찾아서 전달 트레이에 놓아줘.', 'find_item'),
    ('그거 가져와줘.', 'clarify'), ('물건 좀 찾아줘.', 'clarify'),
])
def test_evaluation_policy_deliver_path(harness, text, kind):
    harness.cfg['evaluation_mode'] = False
    harness.parser.llm = lambda *_: {'intent': 'find_item', 'targets': ['eraser'], 'confidence': .99}
    doc = harness.parser.parse(text)
    VoiceNode._deliver(harness, doc, 0)
    assert [d['intent'] for d in harness.published] == [kind]
    assert harness.published[0]['source']['execution_allowed'] == (kind == 'find_item')
    assert harness.published[0]['targets'] == (['eraser'] if kind == 'find_item' else [])
    if kind == 'find_item':
        assert harness.tts.texts == ['지우개 가져다드리겠습니다.']
    else:
        assert harness.tts.texts == [doc['clarify_question']]



def test_fixed_listener_closes_wake_before_recording(harness, monkeypatch):
    from contextlib import contextmanager
    from ready2go_voice.adapters.audio import Recording
    import ready2go_voice.nodes.voice_node as module
    events = []
    harness.cfg.update(recording_mode='fixed', record_duration_sec=5)
    harness.busy = threading.Event()
    class Wake:
        last_score = .8
        def __init__(self, cfg): cfg['input_device'] = 4
        @contextmanager
        def stream(self):
            events.append('wake_open')
            try: yield object()
            finally: events.append('wake_close')
        def wait(self, *args): return True
    class Record:
        def __init__(self, cfg): self.cfg = cfg
        def record_fixed(self, *args):
            assert events[-1] == 'wake_close' and self.cfg['input_device'] == 4
            events.append('record')
            return Recording(b'\0\0', None, None, recording_mode='fixed')
    def submit(*args, **kwargs): harness.stop_event.set(); return True
    harness._submit = submit
    monkeypatch.setattr(module, 'WakeAudio', Wake)
    monkeypatch.setattr(module, 'Recorder', Record)
    VoiceNode._listen(harness)
    assert events == ['wake_open', 'wake_close', 'record']


def test_fixed_tts_cannot_report_ac_latency(harness):
    doc = harness.parser.parse('지우개 찾아줘')
    doc['source'].update(input_kind='audio', timing_mode='commissioning',
                         speech_ended_monotonic=None, confirmation_latency_ms=None)
    VoiceNode._deliver(harness, doc, 0)
    assert doc['source']['confirmation_latency_ms'] is None
    assert not harness.published



def test_progress_default_short_and_detailed_mode_preserves_json(harness):
    messages = []
    harness.get_logger = lambda: SimpleNamespace(info=messages.append)
    doc = {'event': 'stt_result', 'text': '지우개 찾아줘', 'source': {'llm_raw': 'detailed raw'}}
    VoiceNode._diagnostic(harness, doc)
    assert messages == ['STT 결과: 지우개 찾아줘']
    harness.cfg['diagnostic_detail'] = True
    VoiceNode._diagnostic(harness, doc)
    assert 'voice_diagnostic' in messages[1] and 'detailed raw' in messages[1]


@pytest.mark.parametrize('enabled', [True, False])
def test_ready_reports_actual_mode(harness, enabled):
    messages = []
    harness.get_logger = lambda: SimpleNamespace(info=messages.append)
    VoiceNode._diagnostic(harness, {'event': 'ready', 'evaluation_mode': enabled})
    assert ('평가: 실행 보류' in messages[0]) == enabled
    assert ('실행 모드' in messages[0]) == (not enabled)


def test_failure_progress_contains_type_without_sensitive_source(harness):
    messages = []
    harness.get_logger = lambda: SimpleNamespace(info=messages.append)
    for event in ('stt_failed', 'tts_failed'):
        VoiceNode._diagnostic(harness, {'event': event, 'error_type': 'RuntimeError',
                                       'source': {'error': 'SECRET'}})
    assert messages == ['STT 실패: RuntimeError', 'TTS 실패: RuntimeError']


@pytest.mark.parametrize('reason', ['NO_SPEECH', 'VAD_UNAVAILABLE_OR_FAILED', 'SPEECH_CHECK_CANCELED'])
def test_speech_hold_never_publishes_in_execution_mode(harness, reason):
    harness.cfg['evaluation_mode'] = False
    doc = harness.parser.parse('')
    doc['source'].update(record_error=reason, llm_validation='not_called', execution_allowed=False)
    VoiceNode._deliver(harness, doc, 0)
    assert not harness.published and harness.tts.texts == [doc['clarify_question']]
    assert doc['clarify_question'] == harness.cfg['clarify_prompts']['empty']


@pytest.mark.parametrize('prepare_fails', [False, True])
def test_melo_prepare_precedes_listener_and_ready(cfg, ontology, schema, monkeypatch, prepare_fails):
    import ready2go_voice.nodes.voice_node as module
    order = []
    cfg['audio_enabled'] = True
    monkeypatch.setattr(module.Node, '__init__', lambda *a, **k: None)
    monkeypatch.setattr(module, 'get_package_share_directory', lambda _: '.')
    monkeypatch.setattr(module, 'load_config', lambda *a, **k: cfg)
    monkeypatch.setattr(module, 'load', lambda _: ontology)
    monkeypatch.setattr(module, 'LangChainIntent', lambda *a: None)
    from conftest import ROOT
    cfg['intent_schema_file'] = str(ROOT / 'contracts/intent.schema.json')
    monkeypatch.setattr(VoiceNode, 'declare_parameter', lambda self, name, default: SimpleNamespace(value=default))
    for method in ('create_publisher', 'create_subscription'):
        monkeypatch.setattr(VoiceNode, method, lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(module, 'ActionServer', lambda *a, **k: None)
    monkeypatch.setattr(VoiceNode, '_diagnostic', lambda self, doc: order.append(doc['event']))
    class TTS:
        def prepare(self):
            order.append('prepare')
            if prepare_fails:
                raise RuntimeError('MELOTTS_PREPARE_FAILED')
    monkeypatch.setattr(module, 'create_tts', lambda _: TTS())
    monkeypatch.setattr(module.threading, 'Thread', lambda *a, **k: SimpleNamespace(start=lambda: order.append('thread_start')))
    if prepare_fails:
        with pytest.raises(RuntimeError, match='MELOTTS_PREPARE_FAILED'):
            VoiceNode()
        assert order == ['prepare']
    else:
        node = VoiceNode()
        assert order == ['prepare', 'thread_start', 'thread_start', 'thread_start', 'ready']
        assert '서랍을 닫았어요' in node.cfg['_tts_prefill_texts']


def test_ros_runner_status_subscription_dispatch(cfg, tmp_path, monkeypatch):
    """실제 ROS 상태 구독 연결, TTS/API/장치는 모의이며 입력 전체 순서 보장 검사가 아닙니다."""
    import json
    import rclpy
    import yaml
    import ready2go_voice.nodes.voice_node as module
    from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from std_msgs.msg import String
    from conftest import ROOT
    from ready2go_voice.core.runner_notice import STATUS_PROMPTS

    class PreparedTTS(FakeTTS):
        def prepare(self):
            pass

    tts = PreparedTTS()
    monkeypatch.setattr(module, 'create_tts', lambda _: tts)
    monkeypatch.setenv('ROS_DOMAIN_ID', '167')
    monkeypatch.setenv('ROS_LOG_DIR', str(tmp_path / 'ros_logs'))
    cfg.update(audio_enabled=False, ontology_file=str(ROOT / 'knowledge/robot_ontology.jsonld'),
               intent_schema_file=str(ROOT / 'contracts/intent.schema.json'))
    path = tmp_path / 'voice.yaml'
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True))
    rclpy.init()
    voice = peer = thread = None
    executor = MultiThreadedExecutor(num_threads=4)
    try:
        voice = VoiceNode(parameter_overrides=[Parameter('config_file', value=str(path)),
                                              Parameter('evaluation_mode', value=True)])
        voice.parser.llm = None
        assert isinstance(voice.status_subscription.callback_group, MutuallyExclusiveCallbackGroup)
        assert isinstance(voice.subscription.callback_group, ReentrantCallbackGroup)
        qos = voice.status_subscription.qos_profile
        assert qos.depth == 10 and qos.reliability == ReliabilityPolicy.RELIABLE
        assert qos.durability == DurabilityPolicy.TRANSIENT_LOCAL
        peer = Node('runner_status_test_peer')
        publisher = peer.create_publisher(String, '/runner/status', QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL))
        executor.add_node(voice)
        executor.add_node(peer)
        thread = threading.Thread(target=executor.spin, daemon=True)
        thread.start()

        def until(check):
            deadline = time.monotonic() + 4
            while not check() and time.monotonic() < deadline:
                time.sleep(.01)
            assert check()

        until(lambda: publisher.get_subscription_count() > 0)
        publisher.publish(String(data=json.dumps({'phase': 'idle', 'halt_code': None, 'last': None})))
        until(lambda: voice.notice_policy.initialized)
        assert not tts.texts
        publisher.publish(String(data=json.dumps({'phase': 'running', 'task_id': 'find_item',
                                                   'halt_code': None, 'last': None})))
        until(lambda: voice.notice_policy.phase == 'running')
        stopped = String(data=json.dumps({'phase': 'halted', 'halt_code': 'ESTOP', 'last': None}))
        publisher.publish(stopped)
        until(lambda: tts.texts == [STATUS_PROMPTS['estop']])
        revision = voice.notice_policy.revision
        publisher.publish(stopped)
        time.sleep(.15)
        assert tts.texts == [STATUS_PROMPTS['estop']] and voice.notice_policy.revision == revision
    finally:
        if voice:
            voice.close()
        executor.shutdown(timeout_sec=2)
        if thread:
            thread.join(timeout=2)
        if voice:
            voice.destroy_node()
        if peer:
            peer.destroy_node()
        rclpy.try_shutdown()


def test_timing_diagnostics_stay_out_of_intent_and_action_result(harness):
    import json
    details = {'synthesis_wait_sec': .2, 'worker_synth_sec': .002, 'cache_hit': True}
    class TimedTTS(FakeTTS):
        def speak(self, text, **kwargs):
            kwargs['on_timing'](dict(details))
            stamp = super().speak(text, **kwargs)
            kwargs['on_timing']({'playback_sec': .4, 'playback_end_basis': 'portaudio_finished_callback'})
            return stamp
    harness.tts = TimedTTS()
    harness.cfg['evaluation_mode'] = False
    VoiceNode._deliver(harness, harness.parser.parse('지우개 찾아줘'), 0)
    started = next(doc for doc in harness.diagnostics if doc['event'] == 'tts_started')
    ended = next(doc for doc in harness.diagnostics if doc['event'] == 'tts_finished')
    assert started['timing'] == details and 'playback_sec' not in started['timing']
    assert ended['timing']['playback_sec'] == .4
    assert not set(details).intersection(harness.published[0]['source'])
    harness.goal_lock = threading.Lock(); harness.goal_lock.acquire()
    outcomes = []
    goal = SimpleNamespace(request=SimpleNamespace(params_json=json.dumps({'text': '서랍을 닫았어요'})),
                           is_cancel_requested=False, succeed=lambda: outcomes.append('success'),
                           abort=lambda: outcomes.append('abort'), canceled=lambda: outcomes.append('cancel'))
    result = VoiceNode._speak(harness, goal)
    assert result.success and outcomes == ['success'] and not harness.goal_lock.locked()
    assert harness.tts.texts[-1] == '서랍을 닫았어요'
    assert set(json.loads(result.output_json)) == {'tts_started_unix', 'tts_started_monotonic', 'tts_start_basis', 'tts_mock'}


def test_finished_timing_default_is_one_short_line_and_detail_keeps_fields(harness):
    messages = []; harness.get_logger = lambda: SimpleNamespace(info=messages.append)
    doc = {'event': 'tts_finished', 'timing': {'synthesis_wait_sec': .2, 'playback_sec': .4, 'cache_hit': True}}
    harness.cfg['diagnostic_detail'] = False
    VoiceNode._diagnostic(harness, doc)
    assert messages == ['TTS 종료 (합성 대기 0.200초, 재생 0.400초)']
    harness.cfg['diagnostic_detail'] = True
    VoiceNode._diagnostic(harness, doc)
    assert 'cache_hit' in messages[1]


@pytest.fixture
def status_harness(harness):
    from ready2go_voice.core.runner_notice import RunnerNoticePolicy
    harness.notice_policy = RunnerNoticePolicy()
    harness.notice_condition = threading.Condition()
    harness.pending_notice = None
    harness.notice_cancel = threading.Event()
    harness.normal_notice_cancel = threading.Event()
    harness.warning_epoch = 0
    harness.goal_lock = threading.Lock()
    def observe(phase, code=None):
        import json
        doc = {'phase': phase, 'task_id': 'find_item' if phase == 'running' else None,
               'halt_code': code, 'last': None}
        VoiceNode._runner_status(harness, SimpleNamespace(data=json.dumps(doc)))
    harness.observe_status = observe
    harness.observe_status('idle');harness.observe_status('running')
    return harness


def test_status_callback_queues_only_and_priority_replaces_pending(status_harness):
    h = status_harness
    h.observe_status('running', 'HALTED')
    assert h.pending_notice.kind == 'halted' and h.request_cancel.is_set()
    assert h.normal_notice_cancel.is_set() and not h.tts.texts
    h.observe_status('running', 'ESTOP')
    assert h.pending_notice.kind == 'estop' and h.generation == 2
    h.observe_status('running', 'HALTED')
    assert h.pending_notice.kind == 'estop' and h.generation == 2
    h.observe_status('idle')
    assert h.pending_notice is None and not h.normal_notice_cancel.is_set()


def test_warning_aborts_accepted_old_goal_and_rejects_new_normal_goal(status_harness):
    import json
    from rclpy.action import GoalResponse
    h = status_harness; request = SimpleNamespace(params_json=json.dumps({'text': '앞쪽 트레이에 놓았어요'}))
    assert VoiceNode._goal(h, request) == GoalResponse.ACCEPT
    h.observe_status('running', 'ESTOP')
    assert VoiceNode._goal(h, request) == GoalResponse.REJECT
    outcomes = []
    goal = SimpleNamespace(request=request, is_cancel_requested=False, succeed=lambda: outcomes.append('success'),
                           abort=lambda: outcomes.append('abort'), canceled=lambda: outcomes.append('cancel'))
    result = VoiceNode._speak(h, goal)
    assert not result.success and result.error_code == 'CANCELED'
    assert outcomes == ['abort'] and not h.tts.texts and not h.goal_lock.locked()


def test_warning_race_after_playback_return_cannot_mark_old_goal_success(status_harness):
    import json
    h=status_harness; h.goal_lock.acquire();h.goal_warning_epoch=h.warning_epoch
    class TTS(FakeTTS):
        def speak(self, text, **kwargs):
            stamp=super().speak(text, **kwargs)
            h.observe_status('running', 'ESTOP')
            return stamp
    h.tts=TTS();outcomes=[]
    goal=SimpleNamespace(request=SimpleNamespace(params_json=json.dumps({'text':'정상 안내'})),
        is_cancel_requested=False, succeed=lambda:outcomes.append('success'),
        abort=lambda:outcomes.append('abort'), canceled=lambda:outcomes.append('cancel'))
    result=VoiceNode._speak(h,goal)
    assert not result.success and outcomes==['abort']


def test_warning_tts_failure_is_logged_once_without_retry(status_harness):
    h=status_harness;h.observe_status('running','ESTOP');calls=[]
    class TTS(FakeTTS):
        def speak(self, text, **kwargs):
            calls.append(text);raise RuntimeError('speaker unavailable')
    h.tts=TTS()
    def diagnostic(doc):
        h.diagnostics.append(doc)
        if doc['event']=='runner_notice_failed':h.stop_event.set()
    h._diagnostic=diagnostic
    VoiceNode._notice_work(h)
    assert len(calls)==1
    assert sum(doc['event']=='runner_notice_failed' for doc in h.diagnostics)==1
    assert not h.published


def test_active_lower_priority_warning_is_canceled_then_estop_is_spoken(status_harness):
    h=status_harness;h.observe_status('running','HALTED');entered=threading.Event();calls=[]
    class TTS(FakeTTS):
        def speak(self,text,**kwargs):
            calls.append(text)
            if len(calls)==1:
                entered.set()
                if kwargs['cancel'].wait(1):raise InterruptedError('TTS_CANCELED')
                raise AssertionError('warning was not canceled')
            return super().speak(text,**kwargs)
    h.tts=TTS()
    def diagnostic(doc):
        h.diagnostics.append(doc)
        if doc['event']=='tts_finished':h.stop_event.set()
    h._diagnostic=diagnostic
    worker=threading.Thread(target=lambda:VoiceNode._notice_work(h));worker.start()
    try:
        assert entered.wait(1)
        h.observe_status('running','ESTOP')
        worker.join(timeout=1)
        assert not worker.is_alive() and len(calls)==2
        assert calls[1].startswith('비상정지가 감지') and not h.published
    finally:
        h.stop_event.set()
        with h.notice_condition:h.notice_condition.notify_all()
        worker.join(timeout=1)


def test_general_failed_result_does_not_block_next_voice_confirmation_and_intent(status_harness):
    import json
    import queue
    h=status_harness;h.cfg['evaluation_mode']=False
    failed={'phase':'idle','halt_code':None,'task_id':None,
            'last':{'run_id':'failed-one','task_id':'find_item','overall_status':'FAILED','error_code':'GRASP_FAILED'}}
    VoiceNode._runner_status(h,SimpleNamespace(data=json.dumps(failed)))
    assert h.pending_notice.kind=='grasp' and not h.normal_notice_cancel.is_set()
    h.busy=threading.Event();h.requests=queue.Queue(maxsize=1)
    assert VoiceNode._submit(h,('text','지우개 찾아줘'))
    kind,text,generation=h.requests.get_nowait()
    assert kind=='text' and not h.request_cancel.is_set()
    VoiceNode._deliver(h,h.parser.parse(text),generation)
    assert h.tts.texts==['지우개 가져다드리겠습니다.']
    assert len(h.published)==1 and h.published[0]['intent']=='find_item'
