"""기존 voice ICD 구현. 진단은 ROS 로그로만 출력하며 실행/DB 상태는 C가 관리합니다."""
import json
from pathlib import Path
import queue
import threading
import time

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from ament_index_python.packages import get_package_share_directory
from std_msgs.msg import String
from ready2go_interfaces.action import Skill
from ready2go_knowledge.core.ontology import load
from ..core.config import load_config
from ..core.intent import IntentParser, intent
from ..core.session import VoiceSession
from ..adapters.api import LangChainIntent, WhisperSTT
from ..adapters.audio import Recorder, WakeAudio
from ..adapters.tts import EspeakTTS


class VoiceNode(Node):
    def __init__(self, **kwargs):
        super().__init__('voice', **kwargs)
        default = str(Path(get_package_share_directory('ready2go_voice')) / 'params/voice.yaml')
        path = self.declare_parameter('config_file', default).value
        self.cfg = load_config(path)
        ontology = load(self.cfg['ontology_file'])
        with open(self.cfg['intent_schema_file'], encoding='utf-8') as f:
            schema = json.load(f)
        self.parser = IntentParser(ontology, schema, self.cfg, LangChainIntent(self.cfg, ontology['world']['items']))
        self.session = VoiceSession(self.parser, self.cfg, WhisperSTT(
            self.cfg, [v['name_ko'] for v in ontology['world']['items'].values()]))
        self.tts = EspeakTTS(self.cfg)
        self.stop_event = threading.Event()
        self.busy = threading.Event()
        self.speaking = threading.Event()
        self.requests = queue.Queue(maxsize=1)
        self.submit_lock = threading.Lock()
        self.goal_lock = threading.Lock()
        self.generation = 0
        self.request_cancel = threading.Event()
        group = ReentrantCallbackGroup()
        self.publisher = self.create_publisher(String, '/voice/intent', 10)
        self.subscription = self.create_subscription(String, '/voice/text_override', self._text, 10,
                                                     callback_group=group)
        self.server = ActionServer(self, Skill, '/voice/speak', execute_callback=self._speak,
                                   goal_callback=self._goal, cancel_callback=lambda _: CancelResponse.ACCEPT,
                                   callback_group=group)
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()
        self.listener = None
        if self.cfg['audio_enabled']:
            self.listener = threading.Thread(target=self._listen, daemon=True)
            self.listener.start()
        self._diagnostic({'event': 'ready', 'evaluation_mode': self.cfg['evaluation_mode'],
                          'audio_enabled': self.cfg['audio_enabled']})

    def _diagnostic(self, doc):
        # D는 /rosout 또는 voice 콘솔에서 조회. 새 토픽/DB 로거를 만들지 않음.
        self.get_logger().info(json.dumps({'voice_diagnostic': doc}, ensure_ascii=False))

    def _publish(self, doc):
        message = String()
        message.data = json.dumps(doc, ensure_ascii=False)
        self.publisher.publish(message)

    def _text(self, message):
        control = self.parser.control(message.data)
        if control:
            if control['intent'] == 'cancel':
                with self.submit_lock:
                    self.generation += 1
                    self.request_cancel.set()
            # 취소/상태 요청은 API 처리 큐 뒤에서 기다리지 않지만 로봇 제어는 C가 담당.
            control['source'] = {'stt_text': message.data, 'input_kind': 'text',
                                 'execution_allowed': False, 'llm_called': False, 'fallback_used': False}
            published = self.session.should_publish(control)
            if published:
                self._publish(control)
            self._diagnostic({'event': 'intent', 'intent': control, 'published': published})
        else:
            self._submit(('text', message.data))

    def _submit(self, request, generation=None):
        with self.submit_lock:
            if (self.busy.is_set() or self.stop_event.is_set() or
                    (generation is not None and generation != self.generation)):
                self._diagnostic({'event': 'request_held', 'reason': 'voice_busy'})
                return False
            self.busy.set()
            self.request_cancel.clear()
            self.requests.put_nowait((*request, self.generation))
            return True

    def _work(self):
        while not self.stop_event.is_set():
            try:
                kind, value, generation = self.requests.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                if kind == 'record_error':
                    doc = intent('clarify', question='다시 말씀해 주세요.')
                    doc['source'] = {'input_kind': 'audio', 'stt_text': '', 'record_error': value,
                        'llm_called': False, 'llm_validation': 'not_called', 'fallback_used': False,
                        'execution_allowed': False}
                else:
                    doc = self.session.audio(value) if kind == 'audio' else self.parser.parse(value)
                self._deliver(doc, generation)
            except Exception as exc:
                self._diagnostic({'event': 'processing_failed', 'error_type': type(exc).__name__,
                                  'published': False})
            finally:
                self.busy.clear()
                self.requests.task_done()

    def _deliver(self, doc, generation):
        if generation != self.generation:
            self._diagnostic({'event': 'request_canceled', 'published': False})
            return
        source = doc['source']
        text = doc.get('clarify_question') or '그 요청은 지원하지 않습니다.'
        if doc['intent'] == 'find_item':
            text = self.parser.items[doc['targets'][0]]['name_ko'] + ' 가져다드리겠습니다.'
        speak = doc['intent'] in ('unknown', 'clarify') or (
            doc['intent'] == 'find_item' and self.cfg['confirmation_enabled'])
        if speak:
            try:
                timeout = self.cfg['tts_timeout_sec']
                start_deadline = None
                if source.get('input_kind') == 'audio' and doc['intent'] == 'find_item':
                    start_deadline = source['speech_ended_monotonic'] + self.cfg['confirmation_budget_sec']
                self.speaking.set()
                def started(stamp):
                    source.update(stamp)
                    if 'speech_ended_monotonic' in source:
                        source['confirmation_latency_ms'] = round(
                            (stamp['tts_started_monotonic'] - source['speech_ended_monotonic']) * 1000, 3)
                    self._diagnostic({'event': 'tts_started', 'source': source})
                self.tts.speak(text, cancel=self.request_cancel, on_start=started, timeout=timeout, start_deadline=start_deadline)
            except Exception as exc:
                source['tts_error'] = type(exc).__name__
                if doc['intent'] == 'find_item':
                    doc = intent('clarify', question='음성 안내를 확인하지 못했습니다. 실행을 보류합니다.')
                    source['execution_allowed'] = False
                    doc['source'] = source
            finally:
                self.speaking.clear()
        if self.stop_event.is_set() or generation != self.generation:
            return
        with self.submit_lock:
            if generation != self.generation:
                return
            published = self.session.should_publish(doc)
            if published:
                self._publish(doc)
        self._diagnostic({'event': 'intent', 'intent': doc, 'published': published,
                          'evaluation_mode': self.cfg['evaluation_mode']})

    def _listen(self):
        try:
            wake = WakeAudio(self.cfg)
            recorder = Recorder(self.cfg)
            while not self.stop_event.is_set():
                if self.busy.is_set() or self.speaking.is_set() or self.tts.lock.locked():
                    self.stop_event.wait(.08)
                    continue
                with wake.stream() as stream:
                    woke = wake.wait(stream, self.stop_event, lambda: self.speaking.is_set() or self.tts.lock.locked())
                    if woke is None:
                        continue
                    if not woke:
                        break
                    if self.speaking.is_set() or self.busy.is_set():
                        continue
                    record_generation = self.generation
                    try:
                        recording = recorder.record(stream, self.stop_event, lambda: self.speaking.is_set() or self.tts.lock.locked())
                    except (TimeoutError, InterruptedError) as exc:
                        self._diagnostic({'event': 'recording_held', 'reason': str(exc)})
                        if isinstance(exc, TimeoutError):
                            self._submit(('record_error', str(exc)), generation=record_generation)
                        continue
                self._submit(('audio', recording), generation=record_generation)
                while self.busy.is_set() and not self.stop_event.is_set():
                    self.stop_event.wait(.08)
        except Exception as exc:
            # 장치/모델 오류는 모션 입력을 생성하지 않음. 복구는 사람이 설정 확인 후 재시작.
            self._diagnostic({'event': 'audio_unavailable', 'error_type': type(exc).__name__})

    def _goal(self, request):
        try:
            params = json.loads(request.params_json)
            if not isinstance(params, dict) or not isinstance(params.get('text'), str) or not params['text'].strip():
                return GoalResponse.REJECT
        except (ValueError, TypeError):
            return GoalResponse.REJECT
        if not self.goal_lock.acquire(blocking=False):
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _speak(self, goal):
        result = Skill.Result()
        cancel = threading.Event()
        done = threading.Event()
        def watch():
            while not done.wait(.02):
                if goal.is_cancel_requested or self.stop_event.is_set():
                    cancel.set()
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        self.speaking.set()
        try:
            params = json.loads(goal.request.params_json)
            stamp = self.tts.speak(params['text'], cancel=cancel,
                on_start=lambda s: self._diagnostic({'event': 'tts_started', 'source': s}))
            if cancel.is_set() or goal.is_cancel_requested:
                raise InterruptedError('TTS_CANCELED')
            result.success = True
            result.output_json = json.dumps(stamp)
            goal.succeed()
        except InterruptedError:
            result.success, result.error_code = False, 'CANCELED'
            if goal.is_cancel_requested:
                goal.canceled()
            else:
                goal.abort()
        except Exception as exc:
            result.success, result.error_code = False, 'TTS_FAILED'
            goal.abort()
            self._diagnostic({'event': 'tts_failed', 'error_type': type(exc).__name__})
        finally:
            done.set()
            watcher.join(timeout=.1)
            self.speaking.clear()
            self.goal_lock.release()
        return result

    def close(self):
        self.stop_event.set()
        self.request_cancel.set()
        self.worker.join(timeout=1)
        if self.listener:
            self.listener.join(timeout=1)
        self.server.destroy()


def main(args=None):
    rclpy.init(args=args)
    node = None
    executor = MultiThreadedExecutor(num_threads=4)
    try:
        node = VoiceNode()
        executor.add_node(node)
        executor.spin()
    finally:
        if node:
            node.close()
        executor.shutdown()
        if node:
            node.destroy_node()
        rclpy.try_shutdown()
