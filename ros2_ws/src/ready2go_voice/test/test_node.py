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
    def speak(self, text, **kwargs):
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
        voice = VoiceNode(parameter_overrides=[Parameter('config_file', value=str(path))])
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
