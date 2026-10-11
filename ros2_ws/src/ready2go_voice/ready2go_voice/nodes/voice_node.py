"""기존 voice ICD. 콘솔 요약/E 로컬 상세 증빙, 실행·DB 상태는 C 책임입니다."""
import json
import uuid
import time
from pathlib import Path
import queue
import threading

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup, MutuallyExclusiveCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from ament_index_python.packages import get_package_share_directory
from std_msgs.msg import String
from ready2go_interfaces.action import Skill
from ready2go_knowledge.core.ontology import load
from ..core.config import load_config
from ..core.intent import IntentParser, intent
from ..core.session import VoiceSession
from ..core.tts_prefill import prefill_texts, remember_text
from ..core.diagnostics import DiagnosticFile, redact
from ..core.response import final_response
from ..core.runner_notice import RunnerNoticePolicy, Notice
from ..core.request_run import RequestRun
from ..core.place_exchange import PlaceExchange
from ..core.place_input import decode, identity, question_input, registered, result_notice
from ..core.safety_exchange import SafetyExchange, IndependentRegistration, QuestionDeclined, RecoveryRequest
from ..core.recovery_confirmation import finite, safety_utterance, task_end_utterance
from ..adapters.api import LangChainIntent, WhisperSTT
from ..adapters.audio import Recorder, WakeAudio, SharedInput
from ..adapters.tts import create_tts


def runner_blocks(node):
    policy = getattr(node, 'notice_policy', None)
    safety = getattr(node, 'safety_exchange', None)
    return bool(policy and (policy.phase in ('running', 'halted') or policy.blocked)
                or safety and safety.policy and safety.policy.work is not None)


class VoiceNode(Node):
    def __init__(self, *, tts=None, stt=None, recorder=None, clock=time.monotonic, **kwargs):
        super().__init__('voice', **kwargs)
        default = str(Path(get_package_share_directory('ready2go_voice')) / 'params/voice.yaml')
        path = self.declare_parameter('config_file', default).value
        # 시작 시 ROS bool 파라미터 > YAML. 미지정 기본은 false입니다.
        evaluation = self.declare_parameter('evaluation_mode', False).value
        self.cfg = load_config(path, evaluation_mode=evaluation)
        request_run = self.declare_parameter('request_run_enabled', self.cfg['request_run_enabled']).value
        if not isinstance(request_run, bool):
            raise ValueError('request_run_enabled: bool 필요')
        self.cfg['request_run_enabled'] = request_run
        goal_enabled = self.declare_parameter('p2_goal_enabled', self.cfg['p2_goal_enabled']).value
        if not isinstance(goal_enabled, bool):
            raise ValueError('p2_goal_enabled: bool 필요')
        self.cfg['p2_goal_enabled'] = goal_enabled
        self.cfg['diagnostic_detail'] = self.declare_parameter('diagnostic_detail', self.cfg['diagnostic_detail']).value
        self.local_context = threading.local()
        self.diagnostic_file = DiagnosticFile(self.cfg, self.get_logger().warning) if self.cfg['diagnostic_detail'] else None
        ontology = load(self.cfg['ontology_file'])
        with open(self.cfg['intent_schema_file'], encoding='utf-8') as f:
            schema = json.load(f)
        self.parser = IntentParser(ontology, schema, self.cfg, LangChainIntent(self.cfg, ontology['world']['items']))
        self.session = VoiceSession(self.parser, self.cfg, stt if stt is not None else WhisperSTT(
            self.cfg, list(dict.fromkeys(name for v in ontology['world']['items'].values()
                for name in [v['name_ko'], *v.get('aliases_ko', [])]))),
            clock=clock, progress=lambda **event: self._diagnostic(event))
        if self.cfg.get('tts_engine') == 'melotts':
            self.cfg['_tts_progress'] = self._diagnostic
            self.cfg['_tts_prefill_texts'] = prefill_texts(self.cfg, self.parser.items.values(), self.get_logger().warning,
                lambda data: self._diagnostic(dict(data, event='prefill_selection')))
        self.tts = tts if tts is not None else create_tts(self.cfg)
        if self.cfg.get('tts_engine') == 'melotts':
            self.tts.prepare()  # 모델/캐시 완료 전 웨이크/ready를 시작하지 않음
        self.stop_event = threading.Event()
        self.busy = threading.Event()
        self.speaking = threading.Event()
        self.requests = queue.Queue(maxsize=1)
        self.submit_lock = threading.RLock()
        self.goal_lock = threading.Lock()
        self.generation = 0
        self.request_cancel = threading.Event()
        self.notice_policy = RunnerNoticePolicy()
        self.request_run = RequestRun()
        self.request_source_check = None  # Actual C producer/restart mapping is supplied at integration.
        self.request_speech_used = set()
        self.goal_request_run = None
        self.notice_condition = threading.Condition()
        self.pending_notice = None
        self.notice_cancel = threading.Event()
        self.normal_notice_cancel = threading.Event()
        self.warning_epoch = 0
        self.audio_lock = threading.Lock()
        self.playback_lock = threading.Lock()
        self.playback_texts = {}
        self.stop_spoken = None  # 현재 정지 녹음과 겹친 자체 재생 문구만 보관합니다.
        self.shared_input = SharedInput(self.cfg, clock=clock) if self.cfg['audio_enabled'] and recorder is None else None
        self.stop_listener = None
        self.dialog_lock = threading.Lock()
        self.place_clock = clock
        # Explicit development boundary; question/registered/result are test fixtures.
        self.place_topic = self.declare_parameter('place_test_input_topic', '').value
        if not isinstance(self.place_topic, str):
            raise ValueError('place_test_input_topic: string required')
        self.place_exchange = PlaceExchange(self.cfg, item_names={
            key: value['name_ko'] for key, value in self.parser.items.items()})
        self.place_recorder = recorder if recorder is not None else Recorder(self.cfg, clock=clock, shared_input=self.shared_input)
        self.place_test_devices = tts is not None or stt is not None or recorder is not None
        self.place_condition = threading.Condition(self.submit_lock)
        self.place_pending = None
        self.place_identity = None
        self.place_results = set()
        self.place_budget = None
        self.place_first_sent = None
        self.place_registered = None
        self.place_registered_at = None
        self.place_cancel = threading.Event()
        self.place_activity = threading.Event()
        self.place_thread = None
        self.place_running = None
        self.safety_exchange = SafetyExchange(self.cfg)
        self.safety_sender = None
        self.safety_pending = None
        self.safety_running = None
        self.safety_cancel = threading.Event()
        self.safety_activity = threading.Event()
        self.safety_thread = threading.Thread(target=self._safety_work, daemon=True)
        group = ReentrantCallbackGroup()
        self.publisher = self.create_publisher(String, '/voice/intent', 10)
        self.subscription = self.create_subscription(String, '/voice/text_override', self._text, 10,
                                                     callback_group=group)
        status_qos = QoSProfile(depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                reliability=ReliabilityPolicy.RELIABLE)
        self.status_subscription = self.create_subscription(String, '/runner/status', self._runner_status_with_info,
                                                            status_qos, callback_group=MutuallyExclusiveCallbackGroup())
        if self.place_topic:
            self.place_subscription = self.create_subscription(String, self.place_topic, self._place_input, 10,
                                                                callback_group=group)
            self.place_thread = threading.Thread(target=self._place_work, daemon=True)
            self.place_thread.start()
        self.server = ActionServer(self, Skill, '/voice/speak', execute_callback=self._speak,
                                   goal_callback=self._goal, cancel_callback=lambda _: CancelResponse.ACCEPT,
                                   callback_group=group)
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.worker.start()
        self.notice_worker = threading.Thread(target=self._notice_work, daemon=True)
        self.notice_worker.start()
        self.safety_thread.start()
        self.listener = None
        if self.cfg['audio_enabled'] and recorder is None:
            self.listener = threading.Thread(target=self._listen, daemon=True)
            self.listener.start()
        self._diagnostic({'event': 'ready', 'evaluation_mode': self.cfg['evaluation_mode'],
                          'audio_enabled': self.cfg['audio_enabled'],
                          'request_run_enabled': self.cfg['request_run_enabled']})

    def _cancel_place_locked(self):
        owned = self.place_activity.is_set()
        self.place_cancel.set()
        self.place_exchange.invalidate()
        self.place_pending = self.place_identity = None
        self.place_registered = None
        self.place_registered_at = None
        if owned and self.place_running is None and not self.safety_activity.is_set():
            self.place_activity.clear()
            self.busy.clear()
        if self.pending_notice and self.pending_notice.kind == 'place_result':
            self.notice_cancel.set()
            self.pending_notice = None
        self.place_condition.notify_all()

    def _place_input(self, message):
        """Explicit E development fixtures; not a guessed Runner status contract."""
        doc = decode(message.data)
        if doc is None or not self.place_topic or self.cfg['evaluation_mode']:
            return
        with self.place_condition:
            self.place_condition.notify_all()
            if self.stop_event.is_set() or self.notice_policy.blocked or self.notice_policy.phase == 'halted':
                return
            if doc.get('type') == 'registered':
                q = self.place_exchange.active
                now = self.place_clock()
                if (registered(doc, q) and self.place_first_sent is not None
                        and finite(now) and self.place_first_sent <= now <= self.place_first_sent + self.place_budget
                        and not self.place_cancel.is_set()):
                    accepted = self.place_exchange.asked(q, now=self.place_first_sent,
                                                        final_timeout_sec=self.place_budget)
                    if accepted and accepted['answer'] == 'asked':
                        if self.place_registered is not q:
                            self.place_registered_at = now
                        self.place_registered = q
                    self.place_condition.notify_all()
                return
            if doc.get('type') == 'result':
                text = result_notice(doc, expected=self.place_identity)
                final = self.place_exchange.policy.final
                if (text is None or self.place_identity in self.place_results
                        or self.place_cancel.is_set() or final is None or final.success is not True):
                    return
                self.place_results.add(self.place_identity)
                with self.notice_condition:
                    self.notice_cancel.set()
                    self.notice_policy.revision += 1
                    self.pending_notice = Notice('place_result', text, 4, self.notice_policy.revision)
                    self.notice_condition.notify_all()
                return
            incoming = question_input(doc)
            if incoming is None or self.busy.is_set() and not self.place_activity.is_set():
                return
            current = self.place_exchange.active
            ident = identity(doc)
            if current is not None and ident == self.place_identity:
                # A conflicting replay cannot mutate the active work or its budget.
                if incoming.work != current.question.work or incoming.final_timeout_sec != self.place_budget:
                    return
            q = self.place_exchange.begin(incoming.work, boot_id=incoming.boot_id,
                                         observation=incoming.observation)
            if q is current and q is not None:
                return
            if q is None:
                if self.place_exchange.current(current):
                    return  # invalid/stale work cannot cancel the current procedure.
                final = self.place_exchange.policy.final
                if final is None or final.work != incoming.work:
                    return  # unrelated rejected input cannot clear a result awaiting notice.
                self._cancel_place_locked()
                if final is not None and final.work == incoming.work and final.success is True:
                    self.place_identity = ident
                    self.place_cancel = threading.Event()
                return
            self.place_cancel.set()  # old worker cannot commit into the new question.
            self.place_cancel = threading.Event()
            self.place_identity, self.place_budget = ident, incoming.final_timeout_sec
            self.place_first_sent = self.place_registered = self.place_registered_at = None
            self.place_pending = q
            self.place_activity.set()
            self.busy.set()
            self.session.conversation.invalidate()
            self.place_condition.notify_all()

    def _place_paused(self, q, cancel):
        return (cancel.is_set() or self.stop_event.is_set() or not self.place_exchange.current(q)
                or self.notice_policy.blocked or self.notice_policy.phase == 'halted')

    def _place_publish_locked(self, message, q, cancel):
        if self.cfg['evaluation_mode'] or self._place_paused(q, cancel):
            return False
        self._publish(message)
        self._diagnostic({'event': 'place_confirm_sent', 'confirm': message,
                          'test_devices': self.place_test_devices})
        return True

    def _place_work(self):
        while not self.stop_event.is_set():
            with self.place_condition:
                self.place_condition.wait_for(lambda: self.place_pending is not None or self.stop_event.is_set())
                if self.stop_event.is_set():
                    return
                q, self.place_pending = self.place_pending, None
                cancel = self.place_cancel
                if self._place_paused(q, cancel):
                    continue
                self.place_running = cancel
                if self.place_first_sent is None:
                    self.place_first_sent = self.place_clock()
                asked = self.place_exchange.asked_candidate(q)
                if not self._place_publish_locked(asked, q, cancel):
                    continue
            try:
                self.dialog_lock.acquire()
                # Poll only the existing whole interval; no additional ACK budget.
                with self.place_condition:
                    while self.place_registered is not q and not self._place_paused(q, cancel):
                        remaining = self.place_first_sent + self.place_budget - self.place_clock()
                        if remaining < 0:
                            raise TimeoutError('PLACE_REGISTRATION_EXPIRED')
                        self.place_condition.wait(min(.1, max(.001, remaining)))
                if self._place_paused(q, cancel):
                    raise InterruptedError('PLACE_CANCELED')
                if self.place_clock() > self.place_first_sent + self.place_budget:
                    raise TimeoutError('PLACE_QUESTION_EXPIRED')
                if not self.cfg['audio_enabled']:
                    raise ValueError('PLACE_AUDIO_DISABLED')
                timing, started = {}, {}
                self.speaking.set()
                self._say(q.question.text, cancel=cancel, on_start=started.update,
                               on_timing=timing.update)
                self.speaking.clear()
                finish, start = timing.get('playback_ended_monotonic'), started.get('tts_started_monotonic')
                evidence = (finite(start) and finite(finish) and self.place_registered_at <= start <= finish <= self.place_clock()
                            and timing.get('playback_end_basis') == 'portaudio_finished_callback'
                            and started.get('tts_start_basis') == 'portaudio_first_dac'
                            and (started.get('tts_mock') is False or self.place_test_devices))
                if self._place_paused(q, cancel):
                    raise InterruptedError('PLACE_CANCELED')
                if not evidence:
                    raise ValueError('PLACE_TTS_UNCONFIRMED')
                if not self.place_exchange.delivered(q, now=finish, success=True):
                    raise TimeoutError('PLACE_TTS_EXPIRED')
                if not self.cfg['audio_enabled']:
                    raise ValueError('PLACE_AUDIO_DISABLED')
                with self.audio_lock:
                    recording = self.place_recorder.capture(cancel, paused=lambda: self._place_paused(q, cancel))
                reply = self.session.confirm_audio(self.place_exchange, q, recording, cancel=cancel,
                                                   paused=lambda: cancel.is_set() or self.stop_event.is_set())
                with self.place_condition:
                    # The core consumes q on answer; compare the owning procedure/cancel instead.
                    if reply is not None and cancel is self.place_cancel and not cancel.is_set() and not self.stop_event.is_set():
                        if self.cfg['evaluation_mode'] or self.notice_policy.blocked or self.notice_policy.phase == 'halted':
                            continue
                        if reply.message['intent'] == 'cancel':
                            self._stop_locked(reply.message)
                            continue
                        self._publish(reply.message)
                        self._diagnostic({'event': 'place_confirm_sent', 'confirm': reply.message,
                                          'test_devices': self.place_test_devices})
                        if reply.next_question is not None:
                            self.place_pending = reply.next_question
                            self.place_registered = None
                            self.place_registered_at = None
                            self.place_condition.notify_all()
            except InterruptedError:
                pass
            except Exception as exc:
                with self.place_condition:
                    if (cancel is self.place_cancel and not cancel.is_set() and not self.stop_event.is_set()
                            and not self.cfg['evaluation_mode'] and not self.notice_policy.blocked
                            and self.notice_policy.phase != 'halted'):
                        reply = self.place_exchange.fail(q, answer='expired' if isinstance(exc, TimeoutError) else 'error')
                        if reply is not None:
                            self._publish(reply.message)
                    self._diagnostic({'event': 'place_question_failed', 'error_type': type(exc).__name__,
                                      'question_id': q.question_id})
            finally:
                self.dialog_lock.release()
                with self.place_condition:
                    if self.place_running is cancel:
                        self.place_running = None
                    if self.place_pending is None:
                        self.place_activity.clear()
                        if not self.safety_activity.is_set():
                            self.busy.clear()
                if not self.tts.lock.locked():
                    self.speaking.clear()

    def bind_safety_sender(self, sender):
        """C 매핑 구현이 E 내부 후보를 받습니다. 공개 payload는 여기서 만들지 않습니다."""
        if not callable(sender):
            raise TypeError('typed C safety sender callable required')
        with self.submit_lock:
            self._cancel_safety_locked()
            self.safety_sender = sender

    def _cancel_safety_locked(self):
        owned = self.safety_activity.is_set()
        self.safety_cancel.set()
        self.safety_exchange.cancel()
        self.safety_pending = None
        if self.safety_running is None:
            self.safety_activity.clear()
            if owned and not self.place_activity.is_set():
                self.busy.clear()
        self.place_condition.notify_all()

    def safety_stopped(self, work, revision, *, valid_state, evidence=None):
        """실제 C 입력 매핑 전용. 상태 JSON이나 seq만으로 valid_state를 추정하지 않습니다."""
        with self.place_condition:
            old = self.safety_exchange.policy.work if self.safety_exchange.policy else None
            accepted = self.safety_exchange.stopped(work, revision, valid_state=valid_state, evidence=evidence)
            policy = self.safety_exchange.policy
            if policy is not None and (not policy.current_state_confirmed or accepted and old != policy.work):
                self._cancel_safety_locked()
            return accepted

    def safety_offer(self, work, revision, evidence, *, valid_state, valid_until):
        """복구 확인된 현재 사건을 질문 작업에 연결합니다. valid_until은 E 로컬 시각입니다."""
        with self.place_condition:
            if (self.safety_sender is None or self.cfg['evaluation_mode'] or self.stop_event.is_set()
                    or self.safety_activity.is_set()):
                return None
            if self.busy.is_set() and not self.place_activity.is_set():
                return None
            q = self.safety_exchange.offer(work, revision, evidence, now=self.place_clock(),
                                          valid_until=valid_until, valid_state=valid_state)
            if q is None:
                return None
            self._cancel_place_locked()
            self.safety_cancel = threading.Event()
            self.safety_pending = ('question', q)
            self.safety_activity.set()
            self.busy.set()
            self.place_condition.notify_all()
            return q

    def safety_registered(self, q, work, revision, *, valid_state):
        with self.place_condition:
            accepted = self.safety_exchange.registered(q, work, revision, now=self.place_clock(),
                                                       valid_state=valid_state)
            self.place_condition.notify_all()
            return accepted

    def safety_independent(self, *, unique_target):
        """질문 만료 뒤의 새 녹음 전용이며 과거 STT 문자열은 받지 않습니다."""
        with self.place_condition:
            if (self.safety_sender is None or self.cfg['evaluation_mode'] or self.stop_event.is_set()
                    or self.busy.is_set()):
                return None
            target = self.safety_exchange.begin_independent(now=self.place_clock(), unique_target=unique_target)
            if target is None:
                return None
            self.safety_cancel = threading.Event()
            self.safety_pending = ('independent', target)
            self.safety_activity.set()
            self.busy.set()
            self.place_condition.notify_all()
            return target

    def safety_independent_registered(self, target, work, revision, *, valid_state, evidence):
        with self.place_condition:
            if self.cfg['evaluation_mode'] or self.stop_event.is_set() or self.safety_cancel.is_set():
                return None
            result = self.safety_exchange.independent_registered(target, work, revision,
                now=self.place_clock(), valid_state=valid_state, evidence=evidence)
            sender = self.safety_sender
            if result is not None and sender is not None:
                sender('candidate', result)
        return result

    def safety_completed(self, work, revision, *, valid_state):
        with self.place_condition:
            policy = self.safety_exchange.policy
            if policy is None or not policy.completed(work, revision, valid_state=valid_state):
                return False
            self._cancel_safety_locked()
            return True

    def _safety_paused(self, target, cancel):
        return cancel.is_set() or self.stop_event.is_set() or not self.safety_exchange.current(target)

    def _safety_result_locked(self, result, cancel, sender):
        if (result is None or sender is None or cancel is not self.safety_cancel or cancel.is_set()
                or self.stop_event.is_set() or self.cfg['evaluation_mode']):
            return
        if isinstance(result, dict) and result.get('intent') == 'cancel':
            self._stop_locked(result)
        elif isinstance(result, IndependentRegistration):
            sender('register_independent', result.request)
        elif isinstance(result, QuestionDeclined):
            sender('declined', result.question)
        elif isinstance(result, RecoveryRequest):
            sender('recover', result.work)
        else:
            sender('candidate', result)

    def _safety_recording(self, recording, work):
        """새 웨이크 녹음만 독립 요청으로 처리하며 질문의 과거 답을 재분류하지 않습니다."""
        with self.place_condition:
            p = self.safety_exchange.policy
            if (p is None or p.work != work or not p.current_state_confirmed
                    or self.safety_sender is None or self.cfg['evaluation_mode']
                    or not finite(recording.recording_started_monotonic)):
                return
            target = self.safety_exchange.begin_independent(now=recording.recording_started_monotonic,
                                                           unique_target=True)
            if target is None:
                return
            cancel = self.safety_cancel = threading.Event()
            self.safety_running = cancel
            self.safety_activity.set()
            sender = self.safety_sender
        try:
            result = self.session.safety_audio(self.safety_exchange, target, recording, cancel=cancel,
                                               paused=lambda: self.stop_event.is_set())
            with self.place_condition:
                self._safety_result_locked(result, cancel, sender)
            if isinstance(result, IndependentRegistration):
                self._wait_safety_registration(target, cancel)
        finally:
            with self.place_condition:
                if self.safety_running is cancel:
                    self.safety_running = None
                if cancel is self.safety_cancel:
                    self.safety_activity.clear()

    def _wait_safety_registration(self, target, cancel):
        # Keep the current request's single ownership until ACK or its existing deadline.
        with self.place_condition:
            while self.safety_exchange.current(target) and not cancel.is_set() and not self.stop_event.is_set():
                remaining = self.safety_exchange.budget(target, now=self.place_clock())
                if remaining is None or remaining <= 0:
                    self.safety_exchange.fail(target)
                    break
                self.place_condition.wait(min(.1, remaining))

    def _safety_work(self):
        while not self.stop_event.is_set():
            with self.place_condition:
                self.place_condition.wait_for(lambda: self.safety_pending is not None or self.stop_event.is_set())
                if self.stop_event.is_set():
                    return
                mode, target = self.safety_pending
                self.safety_pending = None
                cancel, sender = self.safety_cancel, self.safety_sender
                self.safety_running = cancel
            with self.dialog_lock:
                try:
                    if self._safety_paused(target, cancel) or self.cfg['evaluation_mode'] or sender is None:
                        continue
                    if not self.cfg['audio_enabled']:
                        raise ValueError('SAFETY_AUDIO_DISABLED')
                    if mode == 'question':
                        with self.submit_lock:
                            if self._safety_paused(target, cancel):
                                continue
                            sender('register_question', target)
                        with self.place_condition:
                            while self.safety_exchange.policy.registered_at is None and not self._safety_paused(target, cancel):
                                remaining = target.valid_until - self.place_clock()
                                if remaining <= 0:
                                    raise TimeoutError('SAFETY_REGISTRATION_EXPIRED')
                                self.place_condition.wait(min(.1, remaining))
                        if self._safety_paused(target, cancel) or self.place_clock() >= target.valid_until:
                            raise InterruptedError('SAFETY_CANCELED')
                        timing, started = {}, {}
                        def on_start(stamp):
                            started.update(stamp)
                            if not self.safety_exchange.tts_started(target, now=stamp.get('tts_started_monotonic')):
                                cancel.set()
                        self.speaking.set()
                        self._say(target.text, cancel=cancel, on_start=on_start, on_timing=timing.update)
                        self.speaking.clear()
                        end = timing.get('playback_ended_monotonic')
                        proof = (finite(end) and finite(started.get('tts_started_monotonic'))
                                 and started['tts_started_monotonic'] <= end <= self.place_clock()
                                 and started.get('tts_start_basis') == 'portaudio_first_dac'
                                 and timing.get('playback_end_basis') == 'portaudio_finished_callback'
                                 and (started.get('tts_mock') is False or self.place_test_devices))
                        if (not proof or self._safety_paused(target, cancel)
                                or not self.safety_exchange.delivered(target, now=end, success=True)):
                            raise ValueError('SAFETY_TTS_UNCONFIRMED')
                    if not self.cfg['audio_enabled']:
                        raise ValueError('SAFETY_AUDIO_DISABLED')
                    with self.audio_lock:
                        recording = self.place_recorder.capture(cancel, paused=lambda: self._safety_paused(target, cancel))
                    result = self.session.safety_audio(self.safety_exchange, target, recording, cancel=cancel,
                                                      paused=lambda: self.stop_event.is_set())
                    with self.submit_lock:
                        self._safety_result_locked(result, cancel, sender)
                    if isinstance(result, IndependentRegistration):
                        self._wait_safety_registration(target, cancel)
                except Exception as exc:
                    self.safety_exchange.fail(target)
                    self._diagnostic({'event': 'safety_question_failed', 'error_type': type(exc).__name__})
                finally:
                    with self.place_condition:
                        if self.safety_running is cancel:
                            self.safety_running = None
                        if cancel is self.safety_cancel and self.safety_pending is None:
                            self.safety_activity.clear()
                            if not self.place_activity.is_set():
                                self.busy.clear()
                    if not self.tts.lock.locked():
                        self.speaking.clear()

    def _diagnostic(self, doc):
        value = dict(doc)
        context = getattr(self, 'local_context', None)
        if context is not None and getattr(context, 'request_id', None):
            value.setdefault('request_id', context.request_id)
        meta = doc.get('intent', {}).get('_voice', {})
        value.update({k: v for k, v in meta.items() if k in ('request_id', 'question_id')})
        # 원본 LLM 전체는 interpretation에 한 번만; 공개 source 원본 자체는 삭제하지 않습니다.
        if value.get('event') != 'interpretation':
            value = dict(value)
            if isinstance(value.get('source'), dict):
                value['source'] = {k: v for k, v in value['source'].items() if k != 'llm_raw'}
            if isinstance(value.get('intent'), dict):
                value['intent'] = dict(value['intent'])
                value['intent']['source'] = {k: v for k, v in value['intent'].get('source', {}).items() if k != 'llm_raw'}
        writer = getattr(self, 'diagnostic_file', None)
        if writer is not None:
            writer.emit(value)
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
            'request_accepted': 'Runner 요청 수락 확인',
            'request_decided': 'Runner 요청 보류·거절 확인',
            'request_completed': 'Runner 완료 확인 · 음성 안내 대기',
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
            messages[event] = '실행 보류 (평가/확인 정책)' if not doc.get('published') else 'intent 발행 완료 · Runner 수락 미확인'
        if event == 'final_response':
            messages[event] = doc['text']
        if event == 'request_held':
            messages[event] = '요청 보류: ' + doc.get('reason', '')
        if event == 'cache_record_failed':
            messages[event] = doc['reason']
        if event == 'publish_failed':
            messages[event] = '발행 실패: 수락 미확인·새 요청 필요'
        # 일반 콘솔은 최종 응답/발행 상태/보류/오류만. 단계 증빙은 상세 파일에 보존합니다.
        hidden = {'record_started', 'record_finished', 'whisper_requested', 'stt_result', 'speech_check_started', 'tts_started'}
        if event in messages and event not in hidden:
            self.get_logger().info(redact(messages[event]).replace('\n', ' '))

    def _runner_status_with_info(self, message, info):
        # Jazzy 실제 metadata(시각/sequence)는 C 수락·재기동 근거를 대신하지 않습니다.
        self._runner_status(message)

    def _request_run_connected(self):
        # The integration mapper verifies the current producer and restart boundary.
        # Jazzy metadata/graph or a received JSON alone does not authenticate it.
        check = getattr(self, 'request_source_check', None)
        if check is None:
            return False
        try:
            connected = check() is True
        except Exception:
            connected = False
        if not connected:
            with self.submit_lock:
                self.request_run.invalidate()
        return connected

    def bind_request_source(self, check):
        """실제 C 연결 확인 함수를 설치합니다. bool/readiness 캐시는 받지 않습니다."""
        if not callable(check):
            raise TypeError('current C source check callable required')
        with self.submit_lock:
            self.request_run.invalidate()
            self.request_source_check = check

    def _runner_status(self, message):
        # 관측 상태 전환과 질문 무효화는 발행 게이트와 같은 E 로컬 lock으로 직렬화합니다.
        # P1 경고는 유지하고 opt-in 요청만 실제 C 수락/결과에 연결합니다.
        with self.submit_lock:
            with self.notice_condition:
                events = []
                if self.cfg.get('request_run_enabled', False) and self._request_run_connected():
                    try:
                        status = json.loads(message.data)
                    except (ValueError, TypeError):
                        return
                    events = self.request_run.observe(status)
                previous = self.notice_policy.revision
                notice = self.notice_policy.observe(message.data)
                if (self.notice_policy.blocked or self.notice_policy.phase == 'halted'
                        or notice and notice.kind != 'completed'):
                    if hasattr(self, 'safety_exchange'):
                        self._cancel_safety_locked()
                    if getattr(self, 'place_topic', ''):
                        self._cancel_place_locked()
                if (not notice and not self.notice_policy.blocked
                        and any(event['event'] == 'request_completed' for event in events)):
                    self.notice_policy.revision += 1
                    notice = Notice('completed', '요청한 작업을 완료했습니다.', 4,
                                    self.notice_policy.revision)
                for event in events:
                    self._diagnostic(event)
                if self.notice_policy.blocked:
                    if self.cfg.get('request_run_enabled', False):
                        self.request_run.invalidate()
                    self.normal_notice_cancel.set()
                else:
                    self.normal_notice_cancel.clear()
                if self.notice_policy.revision != previous:
                    self.notice_cancel.set()
                    self.pending_notice = notice
                    if notice and notice.kind != 'completed':
                        self.warning_epoch += 1
                    self.notice_condition.notify_all()
                if self.notice_policy.phase in ('running', 'halted') or self.notice_policy.blocked or notice:
                    self.session.conversation.invalidate()
                if notice and notice.kind != 'completed':
                    self.generation += 1
                    self.request_cancel.set()

    def _say(self, text, *, on_start=None, **kwargs):
        """실제 재생과 겹친 자체 문구만 정지 녹음의 echo 대조에 제공합니다."""
        token = object()
        def started(stamp):
            with self.playback_lock:
                self.playback_texts[token] = text
                if self.stop_spoken is not None:
                    self.stop_spoken.add(text)
            if on_start is not None:
                on_start(stamp)
        try:
            return self.tts.speak(text, on_start=started, **kwargs)
        finally:
            with self.playback_lock:
                self.playback_texts.pop(token, None)

    def _stop_locked(self, doc, generation=None):
        """submit_lock 안에서 현재 세대의 cancel을 한 번 발신하고 모든 E 작업을 무효화합니다."""
        if self.stop_event.is_set() or generation is not None and generation != self.generation:
            return False
        self.session.conversation.invalidate()
        self._cancel_place_locked()
        self._cancel_safety_locked()
        self.generation += 1
        self.request_cancel.set()
        self.request_run.invalidate()
        self.warning_epoch += 1
        with self.notice_condition:
            self.notice_cancel.set()
            self.pending_notice = None
            self.notice_condition.notify_all()
        published = self.session.should_publish(doc)
        if published:
            self._publish(doc)
        self._diagnostic({'event': 'intent', 'intent': doc, 'published': published})
        return published

    def _stop_listen(self):
        # 일반 wake/fixed 설정과 무관하게 정지는 기존 RMS/무음 종료 녹음을 사용합니다.
        recorder = Recorder(self.cfg, clock=self.place_clock, shared_input=self.shared_input)
        interval = self.cfg['frame_samples'] / self.cfg['sample_rate']
        while not self.stop_event.is_set():
            active = (self.busy.is_set() or self.speaking.is_set() or self.tts.lock.locked()
                      or self.place_activity.is_set() or self.safety_activity.is_set()
                      or runner_blocks(self))
            if not active:
                self.stop_event.wait(interval)
                continue
            with self.submit_lock:
                generation = self.generation
            spoken = set()
            def interrupted():
                return self.stop_event.is_set() or generation != self.generation
            try:
                with self.playback_lock:
                    spoken.update(self.playback_texts.values())
                    self.stop_spoken = spoken
                try:
                    with self.shared_input.stream() as stream:
                        recording = recorder.record(stream, self.stop_event, paused=interrupted)
                finally:
                    with self.playback_lock:
                        self.stop_spoken = None
                doc = self.session.stop_audio(recording, paused=interrupted, spoken_texts=spoken)
                if doc is not None:
                    with self.submit_lock:
                        self._stop_locked(doc, generation)
            except TimeoutError:
                continue  # 기존 음성 시작/최대 길이 경계. 무음은 API를 호출하지 않습니다.
            except InterruptedError:
                if self.shared_input._closed:
                    return
                continue
            except Exception as exc:
                self._diagnostic({'event': 'stop_input_unavailable', 'error_type': type(exc).__name__})
                return

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
                self._say(notice.text, cancel=cancel, on_timing=timing.update,
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
        message.data = json.dumps(redact({k: v for k, v in doc.items() if not k.startswith('_')}), ensure_ascii=False)
        self.publisher.publish(message)

    def _text(self, message):
        if hasattr(self, 'safety_exchange'):
            kind = safety_utterance(message.data)
            if kind in ('recover', 'resume', 'new_start') or task_end_utterance(message.data):
                with self.submit_lock:
                    p = self.safety_exchange.policy
                    if kind == 'recover' and p is not None and p.current_state_confirmed and p.work is not None and self.safety_sender is not None and not self.cfg['evaluation_mode']:
                        self.safety_sender('recover', p.work)
                    else:
                        self._diagnostic({'event': 'safety_text_held', 'reason': 'current_voice_recording_required'})
                return
        control = self.parser.control(message.data)
        if control:
            with self.submit_lock:
                self.session.conversation.invalidate()  # status도 새 독립 요청입니다.
                if control['intent'] == 'cancel':
                    control['source'] = dict(stt_text=message.data, input_kind='text',
                                            execution_allowed=False, llm_called=False, fallback_used=False)
                    self._stop_locked(control)
                    return
            # 취소/상태 요청은 API 처리 큐 뒤에서 기다리지 않지만 로봇 제어는 C가 담당.
            control['source'] = {'stt_text': message.data, 'input_kind': 'text',
                                 'execution_allowed': False, 'llm_called': False, 'fallback_used': False}
            published = self.session.should_publish(control)
            if published:
                self._publish(control)
            self._diagnostic({'event': 'intent', 'intent': control, 'published': published})
        else:
            self._submit(('text', message.data))

    def _submit(self, request, generation=None, request_id=None):
        with self.submit_lock:
            if (self.busy.is_set() or self.stop_event.is_set() or
                    (generation is not None and generation != self.generation)):
                self._diagnostic({'event': 'request_held', 'reason': 'voice_busy'})
                return False
            self.busy.set()
            self.request_cancel.clear()
            self.requests.put_nowait((*request, self.generation, request_id or uuid.uuid4().hex))
            return True

    def _work(self):
        while not self.stop_event.is_set():
            try:
                kind, value, generation, request_id = self.requests.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                self.local_context.request_id = request_id
                if kind == 'safety_audio':
                    self._safety_recording(*value)
                    continue
                policy = getattr(self, 'notice_policy', None)
                blocked = bool(policy and (policy.phase in ('running', 'halted') or policy.blocked))
                if kind == 'record_error':
                    doc = intent('clarify', question=self.cfg['clarify_prompts']['empty'])
                    doc['source'] = {'input_kind': 'audio', 'stt_text': '', 'record_error': value,
                        'llm_called': False, 'llm_validation': 'not_called', 'fallback_used': False,
                        'execution_allowed': False}
                else:
                    doc = self.session.audio(value, cancel=self.request_cancel,
                        paused=lambda: self.stop_event.is_set() or generation != self.generation,
                        generation=generation, blocked=blocked, request_id=request_id) if kind == 'audio' else self.session.text(value, generation, blocked, request_id=request_id)
                doc.setdefault('_voice', {})['request_id'] = self.local_context.request_id
                with self.submit_lock:
                    if not self.stop_event.is_set() and generation == self.generation:
                        prepared = self.session.prepare_request_payload(
                            doc, generation, request_id=request_id, blocked=runner_blocks(self))
                        if prepared is not None:
                            # Internal candidate only; _publish still strips _voice.
                            doc['_voice']['prepared_request'] = prepared
                self._diagnostic({'event': 'interpretation', 'intent': doc})
                self._deliver(doc, generation)
            except Exception as exc:
                self._diagnostic({'event': 'processing_failed', 'error_type': type(exc).__name__,
                                  'published': False})
            finally:
                self.local_context.request_id = None
                self.busy.clear()
                self.requests.task_done()

    def _deliver(self, doc, generation):
        with self.submit_lock:
            if self.stop_event.is_set() or generation != self.generation or not self.session.valid_context(doc, generation):
                self._diagnostic({'event': 'request_canceled', 'published': False})
                return
            if doc['intent'] in ('find_item', 'achieve_goal') and self.session.is_duplicate(doc):
                self._diagnostic({'event': 'request_duplicate', 'intent': doc, 'published': False})
                return
        if doc['intent'] in ('find_item', 'achieve_goal') and runner_blocks(self):
            self.session.conversation.invalidate()
            self._diagnostic({'event': 'request_held', 'reason': 'runner_busy_or_locked', 'intent': doc, 'published': False})
            return
        source = doc['source']
        text = doc.get('_voice', {}).get('final_text') or final_response(self.parser, doc)
        self._diagnostic({'event': 'final_response', 'text': text, 'intent': doc})
        request_run = self.cfg.get('request_run_enabled', False) and doc['intent'] in ('find_item', 'achieve_goal')
        speak = doc['intent'] in ('unknown', 'clarify') or (
            doc['intent'] == 'find_item' and self.cfg['confirmation_enabled'] and not request_run)
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
                self._say(text, cancel=self.request_cancel, on_start=started, timeout=timeout, start_deadline=start_deadline, on_timing=timing.update)
                self._diagnostic({'event': 'tts_finished', 'timing': dict(timing), 'text': text, 'intent': doc,
                                  'tts_finished_monotonic': time.monotonic()})
                with self.submit_lock:
                    if generation == self.generation and not self.stop_event.is_set() and self.session.valid_context(doc, generation):
                        question_ready = self.session.conversation.delivered(doc, generation, True, blocked=runner_blocks(self))
                        if question_ready:
                            self._diagnostic({'event': 'question_ready', 'intent': doc, 'question_id': question_ready.id,
                                              'expires_monotonic': question_ready.expires})
                if self.cfg.get('tts_engine') == 'melotts':
                    remember_text(self.cfg, text, lambda warning: self._diagnostic({'event': 'cache_record_failed', 'reason': warning}))
            except Exception as exc:
                self.session.conversation.invalidate()
                source['tts_error'] = type(exc).__name__
                self._diagnostic({'event': 'tts_failed', 'error_type': type(exc).__name__})
                if doc['intent'] == 'find_item':
                    doc = intent('clarify', question=self.cfg['clarify_prompts']['tts_failure'])
                    source['execution_allowed'] = False
                    doc['source'] = source
            finally:
                self.speaking.clear()
        if self.stop_event.is_set() or generation != self.generation or not self.session.valid_context(doc, generation):
            return
        with self.submit_lock:
            if self.stop_event.is_set() or generation != self.generation or not self.session.valid_context(doc, generation):
                return
            if doc['intent'] == 'cancel':
                self._stop_locked(doc, generation)
                return
            if doc['intent'] in ('find_item', 'achieve_goal') and runner_blocks(self):
                self.session.conversation.invalidate()
                self._diagnostic({'event': 'request_held', 'reason': 'runner_busy_or_locked', 'intent': doc, 'published': False})
                return
            published = self.session.should_publish(doc)
            payload = doc
            if published and request_run:
                payload = self.session.prepare_request_payload(
                    doc, generation, request_id=doc.get('_voice', {}).get('request_id'),
                    blocked=runner_blocks(self))
                if (not self._request_run_connected() or payload is None
                        or not self.request_run.register(payload)):
                    self._diagnostic({'event': 'request_held', 'reason': 'request_run_unconfirmed',
                                      'published': False})
                    return
                with self.notice_condition:
                    self.notice_cancel.set()
                    self.notice_policy.revision += 1
                    if self.pending_notice and self.pending_notice.kind == 'completed':
                        self.pending_notice = None
            if published:
                try:
                    self._publish(payload)
                    self.session.mark_published(doc)
                except Exception as exc:
                    if request_run:
                        self.request_run.invalidate()
                    self.session.conversation.invalidate()
                    self._diagnostic({'event': 'publish_failed', 'intent': doc, 'error_type': type(exc).__name__, 'published': False})
                    return
        self._diagnostic({'event': 'intent', 'intent': doc, 'published': published,
                          'evaluation_mode': self.cfg['evaluation_mode']})

    def _listen(self):
        try:
            self.shared_input.start()
            self.stop_listener = threading.Thread(target=self._stop_listen, daemon=True)
            self.stop_listener.start()
            wake = WakeAudio(self.cfg, shared_input=self.shared_input)
            recorder = Recorder(self.cfg, clock=self.place_clock, shared_input=self.shared_input)
            while not self.stop_event.is_set():
                if self.busy.is_set() or self.speaking.is_set() or self.tts.lock.locked():
                    self.stop_event.wait(.08)
                    continue
                self.local_context.request_id = request_id = uuid.uuid4().hex
                self._diagnostic({'event': 'wake_waiting', 'input_device': self.cfg['input_device']})
                record_generation = self.generation
                try:
                    with self.audio_lock, wake.stream() as stream:
                        woke = wake.wait(stream, self.stop_event, lambda: self.speaking.is_set() or self.tts.lock.locked() or self.place_activity.is_set() or self.safety_activity.is_set())
                        if not woke:
                            continue
                        if self.speaking.is_set() or self.busy.is_set():
                            continue
                        record_generation = self.generation
                        with self.submit_lock:
                            policy = self.safety_exchange.policy
                            record_work = policy.work if policy and policy.current_state_confirmed else None
                        self._diagnostic({'event': 'wake_detected', 'score': wake.last_score})
                        if self.cfg.get('recording_mode', 'silence') == 'silence':
                            self._diagnostic({'event': 'record_started'})
                            recording = recorder.record(stream, self.stop_event,
                                lambda: self.speaking.is_set() or self.tts.lock.locked() or record_generation != self.generation or self.place_activity.is_set() or self.safety_activity.is_set())
                    # 고정 모드도 같은 물리 입력의 새 소비자로 기존 길이만 수집합니다.
                    if self.cfg.get('recording_mode', 'silence') == 'fixed':
                        self._diagnostic({'event': 'record_started', 'duration': self.cfg['record_duration_sec']})
                        with self.audio_lock:
                            recording = recorder.record_fixed(self.stop_event,
                                lambda: self.speaking.is_set() or self.tts.lock.locked() or record_generation != self.generation or self.place_activity.is_set() or self.safety_activity.is_set())
                    self._diagnostic({'event': 'record_finished',
                        'recording_started_monotonic': recording.recording_started_monotonic,
                        'recording_ended_monotonic': recording.recording_ended_monotonic,
                        'speech_ended_monotonic': recording.ended_monotonic, 'recording_mode': recording.recording_mode})
                except (TimeoutError, InterruptedError, RuntimeError) as exc:
                    self._diagnostic({'event': 'recording_held', 'reason': str(exc)})
                    if not isinstance(exc, InterruptedError):
                        self._submit(('record_error', str(exc)), generation=record_generation, request_id=request_id)
                    continue
                self._submit(('safety_audio', (recording, record_work)) if record_work is not None else ('audio', recording),
                             generation=record_generation, request_id=request_id)
                self.local_context.request_id = None
                while self.busy.is_set() and not self.stop_event.is_set():
                    self.stop_event.wait(.08)
        except Exception as exc:
            # 장치/모델 오류는 모션 입력을 생성하지 않음. 복구는 사람이 설정 확인 후 재시작.
            self._diagnostic({'event': 'audio_unavailable', 'error_type': type(exc).__name__})
            if self.stop_listener is None:
                self.shared_input.close()

    def _goal(self, request):
        if (self.cfg.get('request_run_enabled', False)
                and not self._request_run_connected()):
            return GoalResponse.REJECT
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
        with self.submit_lock:
            self.goal_request_run = None
            if self.cfg.get('request_run_enabled', False):
                pending, run = self.request_run.pending, self.request_run.run_id
                if (pending is None or run is None or self.request_run.finished
                        or params['text'] != pending.get('accept_text')
                        or (pending['request_id'], run) in self.request_speech_used):
                    self.goal_lock.release()
                    return GoalResponse.REJECT
                self.goal_request_run = (pending['request_id'], run, params['text'])
                self.request_speech_used.add((pending['request_id'], run))
        self.goal_warning_epoch = getattr(self, 'warning_epoch', 0)
        return GoalResponse.ACCEPT

    def _speak(self, goal):
        result = Skill.Result()
        cancel = threading.Event()
        done = threading.Event()
        epoch = getattr(self, 'goal_warning_epoch', getattr(self, 'warning_epoch', 0))
        request_identity = getattr(self, 'goal_request_run', None)
        def warning_changed():
            if request_identity is not None:
                with self.submit_lock:
                    pending = self.request_run.pending
                    if (pending is None or (pending['request_id'], self.request_run.run_id, pending.get('accept_text')) != request_identity
                            or self.request_run.finished):
                        return True
            normal_cancel = getattr(self, 'normal_notice_cancel', None)
            return (self.stop_event.is_set()
                    or (normal_cancel is not None and normal_cancel.is_set())
                    or epoch != getattr(self, 'warning_epoch', 0)
                    or (self.cfg.get('request_run_enabled', False)
                        and not self._request_run_connected()))
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
            stamp = self._say(params['text'], cancel=cancel,
                on_start=lambda s: self._diagnostic({'event': 'tts_started', 'source': s, 'timing': dict(timing)}),
                on_timing=timing.update)
            self._diagnostic({'event': 'tts_finished', 'timing': dict(timing)})
            if cancel.is_set() or goal.is_cancel_requested or warning_changed():
                raise InterruptedError('TTS_CANCELED')
            if self.cfg.get('request_run_enabled', False):
                import math
                start = stamp.get('tts_started_monotonic') if isinstance(stamp, dict) else None
                end = timing.get('playback_ended_monotonic')
                if (not isinstance(stamp, dict) or stamp.get('tts_mock') is not False
                        or stamp.get('tts_start_basis') != 'portaudio_first_dac'
                        or timing.get('playback_end_basis') != 'portaudio_finished_callback'
                        or any(isinstance(t, bool) or not isinstance(t, (int, float))
                               or not math.isfinite(t) for t in (start, end))
                        or end < start):
                    raise RuntimeError('TTS_PLAYBACK_UNCONFIRMED')
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
        if self.shared_input is not None:
            self.shared_input.close()
        with self.submit_lock:
            self._cancel_place_locked()
            self._cancel_safety_locked()
        if self.place_thread:
            self.place_thread.join(timeout=1)
        self.safety_thread.join(timeout=1)
        with self.notice_condition:
            self.notice_cancel.set()
            self.notice_condition.notify_all()
        self.worker.join(timeout=1)
        self.notice_worker.join(timeout=1)
        if self.listener:
            self.listener.join(timeout=1)
        if self.stop_listener:
            self.stop_listener.join(timeout=1)
        if hasattr(self.tts, 'close'):
            self.tts.close()
        writer = getattr(self, 'diagnostic_file', None)
        if writer is not None:
            writer.close()
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
