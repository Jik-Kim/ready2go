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
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from ament_index_python.packages import get_package_share_directory
from std_msgs.msg import String
from ready2go_interfaces.action import Skill
from ready2go_knowledge.core.ontology import load
from ..core.config import load_config
from ..core.intent import IntentParser, intent, clarify_prompt
from ..core.session import VoiceSession
from ..core.tts_prefill import prefill_texts
from ..core.runner_notice import RunnerNoticePolicy
from ..adapters.api import LangChainIntent, WhisperSTT
from ..adapters.audio import Recorder, WakeAudio
from ..adapters.tts import create_tts


class VoiceNode(Node):
    def __init__(self, **kwargs):
        super().__init__('voice', **kwargs)
        default = str(Path(get_package_share_directory('ready2go_voice')) / 'params/voice.yaml')
        path = self.declare_parameter('config_file', default).value
        # 시작 시 ROS bool 파라미터 > YAML. 미지정 기본은 false입니다.
        evaluation = self.declare_parameter('evaluation_mode', False).value
        self.cfg = load_config(path, evaluation_mode=evaluation)
        self.cfg['diagnostic_detail'] = self.declare_parameter('diagnostic_detail', self.cfg['diagnostic_detail']).value
        ontology = load(self.cfg['ontology_file'])
        with open(self.cfg['intent_schema_file'], encoding='utf-8') as f:
            schema = json.load(f)
        self.parser = IntentParser(ontology, schema, self.cfg, LangChainIntent(self.cfg, ontology['world']['items']))
        self.session = VoiceSession(self.parser, self.cfg, WhisperSTT(
            self.cfg, [v['name_ko'] for v in ontology['world']['items'].values()]),
            progress=lambda **event: self._diagnostic(event))
        if self.cfg.get('tts_engine') == 'melotts':
            self.cfg['_tts_prefill_texts'] = prefill_texts(self.cfg, self.parser.items.values())
        self.tts = create_tts(self.cfg)
        if self.cfg.get('tts_engine') == 'melotts':
            self.tts.prepare()  # 모델/캐시 완료 전 웨이크/ready를 시작하지 않음
        self.stop_event = threading.Event()
        self.busy = threading.Event()
        self.speaking = threading.Event()
        self.requests = queue.Queue(maxsize=1)
        self.submit_lock = threading.Lock()
        self.goal_lock = threading.Lock()
        self.generation = 0
        self.request_cancel = threading.Event()
        self.notice_policy = RunnerNoticePolicy()
        self.notice_condition = threading.Condition()
        self.pending_notice = None
        self.notice_cancel = threading.Event()
        self.normal_notice_cancel = threading.Event()
        self.warning_epoch = 0
        group = ReentrantCallbackGroup()
        self.publisher = self.create_publisher(String, '/voice/intent', 10)
        self.subscription = self.create_subscription(String, '/voice/text_override', self._text, 10,
                                                     callback_group=group)
        status_qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                reliability=ReliabilityPolicy.RELIABLE)
        self.status_subscription = self.create_subscription(String, '/runner/status', self._runner_status,
                                                            status_qos, callback_group=group)
        self.server = ActionServer(self, Skill, '/voice/speak', execute_callback=self._speak,
                                   goal_callback=self._goal, cancel_callback=lambda _: CancelResponse.ACCEPT,
                                   callback_group=group)
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()
        self.notice_worker = threading.Thread(target=self._notice_work, daemon=True)
        self.notice_worker.start()
        self.listener = None
        if self.cfg['audio_enabled']:
            self.listener = threading.Thread(target=self._listen, daemon=True)
            self.listener.start()
        self._diagnostic({'event': 'ready', 'evaluation_mode': self.cfg['evaluation_mode'],
                          'audio_enabled': self.cfg['audio_enabled']})

    def _diagnostic(self, doc):
        # D는 /rosout 또는 voice 콘솔에서 조회. 새 토픽/DB 로거를 만들지 않음.
        if self.cfg.get('diagnostic_detail', False):
            self.get_logger().info(json.dumps({'voice_diagnostic': doc}, ensure_ascii=False))
        event = doc.get('event')
        messages = {
            'ready': '음성 준비 완료 (' + ('평가: 실행 보류' if doc.get('evaluation_mode') else '실행 모드') + ')', 'wake_waiting': f"웨이크 대기 (입력: {doc.get('input_device')})",
            'wake_detected': f"웨이크 감지 (점수 {doc.get('score', 0):.3f})",
            'record_started': f"녹음 시작 ({doc.get('duration', '무음 종료')}초)",
            'record_finished': '녹음 완료', 'whisper_requested': 'Whisper 요청',
            'stt_result': f"STT 결과: {doc.get('text', '')}",
            'speech_check_started': '발화 검사', 'no_speech': '발화 없음: STT·LLM 생략',
            'speech_check_failed': f"발화 검사 보류: {doc.get('error_type', '')}",
            'stt_failed': f"STT 실패: {doc.get('error_type', '')}",
            'tts_failed': f"TTS 실패: {doc.get('error_type', '')}",
            'tts_started': 'TTS 시작', 'tts_finished': 'TTS 종료',
            'runner_notice_failed': f"상태 음성 안내 실패: {doc.get('error_type', '')}",
            'recording_held': f"녹음 보류: {doc.get('reason', '')}",
            'audio_unavailable': f"음성 장치/모델 오류: {doc.get('error_type', '')}",
            'processing_failed': f"처리 실패: {doc.get('error_type', '')}",
            'request_canceled': '취소: 실행 보류', 'request_duplicate': '중복: 실행 보류',
        }
        timing = doc.get('timing', {})
        if event == 'tts_finished' and 'synthesis_wait_sec' in timing and 'playback_sec' in timing:
            messages[event] = (f"TTS 종료 (합성 대기 {timing['synthesis_wait_sec']:.3f}초, "
                               f"재생 {timing['playback_sec']:.3f}초)")
        if event == 'interpretation':
            value = doc['intent']
            route = '폴백' if value['source'].get('fallback_used') else ('LLM' if value['source'].get('llm_called') else '규칙')
            messages[event] = f"{route} 결과: {value['intent']} {','.join(value.get('targets', []))}"
        if event == 'intent':
            messages[event] = '실행 보류 (평가/확인 정책)' if not doc.get('published') else 'intent 발행'
        if event in messages:
            self.get_logger().info(messages[event].replace('\n', ' '))

    def _runner_status(self, message):
        # 파싱/정책/단일 대기 슬롯만 처리. TTS/로봇 서비스/DB 호출 없음.
        with self.notice_condition:
            previous = self.notice_policy.revision
            notice = self.notice_policy.observe(message.data)
            if self.notice_policy.blocked:
                self.normal_notice_cancel.set()
            else:
                self.normal_notice_cancel.clear()
            if self.notice_policy.revision != previous:
                self.notice_cancel.set()
                self.pending_notice = notice
                if notice:
                    self.warning_epoch += 1
                self.notice_condition.notify_all()
        if notice:
            with self.submit_lock:
                self.generation += 1
                self.request_cancel.set()  # 낡은 확인/API 결과는 기존 취소 경로로 보류.

    def _notice_work(self):
        while not self.stop_event.is_set():
            with self.notice_condition:
                self.notice_condition.wait_for(lambda: self.pending_notice is not None or self.stop_event.is_set())
                if self.stop_event.is_set(): return
                notice, self.pending_notice = self.pending_notice, None
                if notice.revision != self.notice_policy.revision: continue
                cancel = self.notice_cancel = threading.Event()
            self.speaking.set()
            timing = {}
            try:
                self.tts.speak(notice.text, cancel=cancel, on_timing=timing.update,
                               on_start=lambda stamp: self._diagnostic({'event': 'tts_started',
                                   'notice_kind': notice.kind, 'source': stamp, 'timing': dict(timing)}))
                self._diagnostic({'event': 'tts_finished', 'notice_kind': notice.kind, 'timing': dict(timing)})
            except InterruptedError:
                pass  # 상위 경고/새 회차/종료 시 폐기, 재시도하지 않음.
            except Exception as exc:
                self._diagnostic({'event': 'runner_notice_failed', 'notice_kind': notice.kind,
                                  'error_type': type(exc).__name__})
            finally:
                if not self.tts.lock.locked(): self.speaking.clear()

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
                    doc = intent('clarify', question=self.cfg['clarify_prompts']['empty'])
                    doc['source'] = {'input_kind': 'audio', 'stt_text': '', 'record_error': value,
                        'llm_called': False, 'llm_validation': 'not_called', 'fallback_used': False,
                        'execution_allowed': False}
                else:
                    doc = self.session.audio(value, cancel=self.request_cancel,
                        paused=lambda: self.stop_event.is_set() or generation != self.generation) if kind == 'audio' else self.parser.parse(value)
                self._diagnostic({'event': 'interpretation', 'intent': doc})
                self._deliver(doc, generation)
            except Exception as exc:
                self._diagnostic({'event': 'processing_failed', 'error_type': type(exc).__name__,
                                  'published': False})
            finally:
                self.busy.clear()
                self.requests.task_done()

    def _deliver(self, doc, generation):
        with self.submit_lock:
            if self.stop_event.is_set() or generation != self.generation:
                self._diagnostic({'event': 'request_canceled', 'published': False})
                return
            if doc['intent'] == 'find_item' and self.session.is_duplicate(doc):
                self._diagnostic({'event': 'request_duplicate', 'intent': doc, 'published': False})
                return
        source = doc['source']
        if doc['intent'] == 'clarify':
            doc['clarify_question'] = clarify_prompt(self.cfg, doc.get('clarify_question'))
        text = doc.get('clarify_question') or '그 요청은 지원하지 않습니다.'
        if doc['intent'] == 'find_item':
            text = self.parser.items[doc['targets'][0]]['name_ko'] + ' 가져다드리겠습니다.'
        speak = doc['intent'] in ('unknown', 'clarify') or (
            doc['intent'] == 'find_item' and self.cfg['confirmation_enabled'])
        if speak:
            try:
                normal_cancel = getattr(self, 'normal_notice_cancel', None)
                if normal_cancel is not None and normal_cancel.is_set():
                    raise InterruptedError('TTS_CANCELED')
                timeout = self.cfg['tts_timeout_sec']
                start_deadline = None
                if (source.get('input_kind') == 'audio' and doc['intent'] == 'find_item'
                        and source.get('timing_mode', 'ac_budget') == 'ac_budget'
                        and source.get('speech_ended_monotonic') is not None):
                    start_deadline = source['speech_ended_monotonic'] + self.cfg['confirmation_budget_sec']
                self.speaking.set()
                timing = {}
                def started(stamp):
                    source.update(stamp)
                    if (source.get('speech_ended_monotonic') is not None
                            and source.get('timing_mode', 'ac_budget') == 'ac_budget'):
                        source['confirmation_latency_ms'] = round(
                            (stamp['tts_started_monotonic'] - source['speech_ended_monotonic']) * 1000, 3)
                    self._diagnostic({'event': 'tts_started', 'source': source, 'timing': dict(timing)})
                self.tts.speak(text, cancel=self.request_cancel, on_start=started, timeout=timeout, start_deadline=start_deadline, on_timing=timing.update)
                self._diagnostic({'event': 'tts_finished', 'timing': dict(timing)})
            except Exception as exc:
                source['tts_error'] = type(exc).__name__
                self._diagnostic({'event': 'tts_failed', 'error_type': type(exc).__name__})
                if doc['intent'] == 'find_item':
                    doc = intent('clarify', question=self.cfg['clarify_prompts']['tts_failure'])
                    source['execution_allowed'] = False
                    doc['source'] = source
            finally:
                self.speaking.clear()
        if self.stop_event.is_set() or generation != self.generation:
            return
        with self.submit_lock:
            if self.stop_event.is_set() or generation != self.generation:
                return
            published = self.session.should_publish(doc)
            if published:
                self._publish(doc)
                self.session.mark_published(doc)
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
                self._diagnostic({'event': 'wake_waiting', 'input_device': self.cfg['input_device']})
                record_generation = self.generation
                try:
                    with wake.stream() as stream:
                        woke = wake.wait(stream, self.stop_event, lambda: self.speaking.is_set() or self.tts.lock.locked())
                        if not woke:
                            continue
                        if self.speaking.is_set() or self.busy.is_set():
                            continue
                        record_generation = self.generation
                        self._diagnostic({'event': 'wake_detected', 'score': wake.last_score})
                        if self.cfg.get('recording_mode', 'silence') == 'silence':
                            self._diagnostic({'event': 'record_started'})
                            recording = recorder.record(stream, self.stop_event,
                                lambda: self.speaking.is_set() or self.tts.lock.locked() or record_generation != self.generation)
                    # 웨이크 스트림을 닫은 뒤 원본 sd.rec가 같은 입력으로 새 스트림을 엽니다.
                    if self.cfg.get('recording_mode', 'silence') == 'fixed':
                        self._diagnostic({'event': 'record_started', 'duration': self.cfg['record_duration_sec']})
                        recording = recorder.record_fixed(self.stop_event,
                            lambda: self.speaking.is_set() or self.tts.lock.locked() or record_generation != self.generation)
                    self._diagnostic({'event': 'record_finished'})
                except (TimeoutError, InterruptedError, RuntimeError) as exc:
                    self._diagnostic({'event': 'recording_held', 'reason': str(exc)})
                    if not isinstance(exc, InterruptedError):
                        self._submit(('record_error', str(exc)), generation=record_generation)
                    continue
                self._submit(('audio', recording), generation=record_generation)
                while self.busy.is_set() and not self.stop_event.is_set():
                    self.stop_event.wait(.08)
        except Exception as exc:
            # 장치/모델 오류는 모션 입력을 생성하지 않음. 복구는 사람이 설정 확인 후 재시작.
            self._diagnostic({'event': 'audio_unavailable', 'error_type': type(exc).__name__})

    def _goal(self, request):
        normal_cancel = getattr(self, 'normal_notice_cancel', None)
        if normal_cancel is not None and normal_cancel.is_set(): return GoalResponse.REJECT
        try:
            params = json.loads(request.params_json)
            if not isinstance(params, dict) or not isinstance(params.get('text'), str) or not params['text'].strip():
                return GoalResponse.REJECT
        except (ValueError, TypeError):
            return GoalResponse.REJECT
        if not self.goal_lock.acquire(blocking=False):
            return GoalResponse.REJECT
        self.goal_warning_epoch = getattr(self, 'warning_epoch', 0)
        return GoalResponse.ACCEPT

    def _speak(self, goal):
        result = Skill.Result()
        cancel = threading.Event()
        done = threading.Event()
        epoch = getattr(self, 'goal_warning_epoch', getattr(self, 'warning_epoch', 0))
        def warning_changed():
            normal_cancel = getattr(self, 'normal_notice_cancel', None)
            return ((normal_cancel is not None and normal_cancel.is_set())
                    or epoch != getattr(self, 'warning_epoch', 0))
        def watch():
            while not done.wait(.02):
                if goal.is_cancel_requested or self.stop_event.is_set() or warning_changed():
                    cancel.set()
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        self.speaking.set()
        try:
            if warning_changed():
                raise InterruptedError('TTS_CANCELED')
            timing = {}
            params = json.loads(goal.request.params_json)
            stamp = self.tts.speak(params['text'], cancel=cancel,
                on_start=lambda s: self._diagnostic({'event': 'tts_started', 'source': s, 'timing': dict(timing)}),
                on_timing=timing.update)
            self._diagnostic({'event': 'tts_finished', 'timing': dict(timing)})
            if cancel.is_set() or goal.is_cancel_requested or warning_changed():
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
        with self.notice_condition:
            self.notice_cancel.set()
            self.notice_condition.notify_all()
        self.worker.join(timeout=1)
        self.notice_worker.join(timeout=1)
        if self.listener:
            self.listener.join(timeout=1)
        if hasattr(self.tts, 'close'):
            self.tts.close()
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
