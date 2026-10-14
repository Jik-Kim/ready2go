"""기존 voice ICD. 콘솔 요약/E 로컬 상세 증빙, 실행·DB 상태는 C 책임입니다."""
import json
from copy import deepcopy
import uuid
import time
from pathlib import Path
import queue
import threading
from collections import deque

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
from ..core.recovery_confirmation import finite, safety_utterance, task_end_utterance, TaskEndCandidate
from ..adapters.api import LangChainIntent, WhisperSTT
from ..adapters.audio import Recorder, WakeAudio, SharedInput
from ..adapters.tts import create_tts
from ..adapters.cue import WakeCue


def runner_blocks(node):
    policy = getattr(node, 'notice_policy', None)
    safety = getattr(node, 'safety_exchange', None)
    return bool(getattr(node, 'pending_task_end', None) is not None or policy and (policy.phase in ('running', 'halted') or policy.blocked)
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
        self._configure_upper_drawer()
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
                lambda data: self._diagnostic(dict(data, event='prefill_selection')),
                reference_state=self.parser.reference_state, places=self.parser.places,
                item_names={k:v['name_ko'] for k,v in self.parser.items.items()})
        self.tts = tts if tts is not None else create_tts(self.cfg)
        if self.cfg.get('tts_engine') == 'melotts':
            self.tts.prepare()  # 모델/캐시 완료 전 웨이크/ready를 시작하지 않음
        self.cue_cancel = threading.Event()
        self.cue_active = threading.Event()
        self.cue = None
        self._cue_initialization_failed = False
        self.stop_event = threading.Event()
        self.busy = threading.Event()
        self.speaking = threading.Event()
        self.requests = queue.Queue(maxsize=1)
        self.request_running = None
        self.submit_lock = threading.RLock()
        self.goal_lock = threading.Lock()
        self.generation = 0
        self.request_cancel = threading.Event()
        self.notice_policy = RunnerNoticePolicy(self.cfg)
        self.request_run = RequestRun()
        self.accepted_request_logs = deque(maxlen=128)
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
        self.stop_processor = None
        self.stop_captures = queue.Queue(maxsize=1)
        self.pending_task_end = None
        self.deferred_task_end = None
        self.task_end_request = self.task_end_source = None
        self.request_source_boot = None
        self.pending_resume = None
        self.control_feedback = None
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
        self.control_mapper = None
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
        self.runner_control_source = None
        self._runtime_control_check = None
        self._control_binding = None
        self._control_source_lost = False
        self._init_runner_control_source()
        self._init_runner_memory(QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                           reliability=ReliabilityPolicy.RELIABLE))
        if self.place_topic:
            self.place_subscription = self.create_subscription(String, self.place_topic, self._place_input, 10,
                                                                callback_group=group)
            self.place_thread = threading.Thread(target=self._place_work, daemon=True)
            self.place_thread.start()
        self.server = ActionServer(self, Skill, '/voice/speak', execute_callback=self._speak,
                                   goal_callback=self._goal, cancel_callback=lambda _: CancelResponse.ACCEPT,
                                   callback_group=group)
        self._init_wake_cue()
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
                          'request_run_enabled': self.cfg['request_run_enabled'],
                          'p2_goal_enabled': self.cfg['p2_goal_enabled'],
                          'upper_drawer_enabled': self.cfg.get('upper_drawer_enabled', False),
                          'wake_cue_enabled': self.cfg['voice_flow']['wake_cue_enabled'],
                          'output_device': self.cfg.get('output_device'),
                          'cue_gain': self.cfg['voice_flow']['cue_gain']})

    def _configure_upper_drawer(self):
        """Explicit startup scope; reuse the selected catalog and both send gates."""
        enabled = self.declare_parameter('upper_drawer_enabled', False).value
        if type(enabled) is not bool:
            raise ValueError('upper_drawer_enabled: bool required')
        self.cfg['upper_drawer_enabled'] = enabled
        if not enabled:
            return
        if not self.cfg['p2_goal_enabled'] or not self.cfg['request_run_enabled']:
            raise ValueError('upper_drawer_enabled requires both P2/request opt-ins')
        selected = [[{'predicate': 'open', 'subject': 'drawer_top', 'value': value}]
                    for value in (True, False)]
        catalog = self.cfg['p2_goal_catalog']
        if any(group not in catalog for group in selected):
            raise ValueError('upper drawer goals must exist in selected catalog')
        self.cfg['p2_goal_catalog'] = deepcopy(selected)

    def _init_wake_cue(self):
        from ready2go_voice.adapters.cue import WakeCue
        enabled = self.cfg['voice_flow']['wake_cue_enabled']
        self.cue = None
        self._cue_initialization_failed = False
        try:
            if enabled:
                self.cue = WakeCue(self.cfg, self.tts.lock)
        except Exception as exc:
            self._cue_initialization_failed = True
            self._diagnostic({'event':'wake_cue_failed','reason':'initialization_failed',
                              'error_type':type(exc).__name__})
        self._diagnostic({'event':'wake_cue_config','enabled':enabled,
                          'available':self.cue is not None,'output_device':self.cfg.get('output_device'),
                          'gain':self.cfg['voice_flow']['cue_gain'],
                          'reason':'configured_off' if not enabled else 'initialization_failed' if self._cue_initialization_failed else 'ready'})

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
            self._cancel_readonly_notice_locked()
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
                            self._refresh_busy_locked()
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
        self.control_feedback = None
        self.pending_resume = None
        self.pending_task_end = None
        self.deferred_task_end = None
        self.task_end_request = self.task_end_source = None
        if self.safety_running is None:
            self.safety_activity.clear()
            if owned and not self.place_activity.is_set():
                self._refresh_busy_locked()
        self.place_condition.notify_all()

    def safety_stopped(self, work, revision, *, valid_state, evidence=None):
        """실제 C 입력 매핑 전용. 상태 JSON이나 seq만으로 valid_state를 추정하지 않습니다."""
        with self.place_condition:
            ending = getattr(self, 'task_end_request', None)
            old = self.safety_exchange.policy.work if self.safety_exchange.policy else None
            accepted = self.safety_exchange.stopped(work, revision, valid_state=valid_state, evidence=evidence)
            policy = self.safety_exchange.policy
            if accepted and old != policy.work:
                self.pending_task_end = None
            if policy is not None and (not policy.current_state_confirmed or accepted and old != policy.work):
                self._cancel_safety_locked()
            if valid_state is not True:
                if policy is not None:
                    policy.current_state_confirmed = False
                self._cancel_safety_locked()
            elif ending is not None:
                if (accepted and work.task == ending['run'] and work.session == ending['boot']
                        and ending['generation'] == self.generation):
                    self.task_end_request = ending
                    self.task_end_source = ending
                else:
                    self.task_end_request = self.task_end_source = None
                    self._diagnostic({'event':'task_end_held','reason':'stop_identity_not_current'})
            self._advance_task_end_locked()
            return accepted

    def _task_end_source_current(self):
        origin = getattr(self, 'task_end_source', None)
        if origin is None:
            return True  # 기존 typed 중단 작업 종료 경로
        try:
            return (origin['check'] is getattr(self, 'request_source_check', None)
                    and origin['boot'] == getattr(self, 'request_source_boot', None)
                    and origin['check']() is True)
        except Exception:
            return False

    def _advance_task_end_locked(self):
        ending = getattr(self, 'task_end_request', None)
        if ending is None:
            return
        if ending['generation'] != self.generation or not self._task_end_source_current():
            self.task_end_request = self.task_end_source = None
            self._diagnostic({'event':'task_end_held','reason':'generation_or_source_changed'})
            return
        p = self.safety_exchange.policy
        if (p is None or not p.current_state_confirmed or p.work is None
                or self.notice_policy.phase != 'halted'
                or getattr(self.safety_exchange.evidence, 'stopped', False) is not True):
            return  # 실제 현재 정지 확인 없이 종료 후보/idle을 만들지 않습니다.
        if (p.work.task, p.work.session) != (ending['run'], ending['boot']):
            self.task_end_request = self.task_end_source = None
            self._diagnostic({'event':'task_end_held','reason':'stop_identity_not_current'})
            return
        self.task_end_request = None
        self._send_safety_candidate_locked(TaskEndCandidate(p.work), self.safety_sender)

    def _task_end_locked(self, doc, generation):
        """원래 명시 종료 의도를 현재 대상에 연결. STT/재개 등록 증빙 재사용 없음."""
        if self.stop_event.is_set() or generation != self.generation or self.cfg['evaluation_mode']:
            return True
        if (getattr(self, 'task_end_request', None) is not None
                or getattr(self, 'pending_task_end', None) is not None):
            return True  # 일반/독립 전사 중복은 새 cancel·후보·TTS를 만들지 않습니다.
        from ready2go_voice.core.hotfix import prompts
        meta = doc.setdefault('_voice', {})
        if getattr(self, 'deferred_task_end', None) is not None:
            from ready2go_voice.core.hotfix import control_notice
            self._task_end_notice_locked(control_notice(self.cfg, 'end_pending', runtime=True))
            return True  # C still requires human confirmation/reset; no retry/permission.
        p = self.safety_exchange.policy
        if self.notice_policy.phase == 'running':
            check = getattr(self, 'request_source_check', None)
            run, boot = self.request_run.run_id, getattr(self, 'request_source_boot', None)
            connected = self._request_run_connected()
            mapper = getattr(self, 'control_mapper', None)
            if mapper is not None and mapper.proof_provider is None and connected:
                from ready2go_voice.core.recovery_confirmation import ActiveRun
                run = run or mapper.active_run
                if isinstance(run,str) and run.strip() and boot == mapper.boot:
                    candidate = TaskEndCandidate(ActiveRun(boot,run))
                    self.pending_task_end = (candidate,self.generation)
                    if mapper.send_running_end(candidate):
                        self._diagnostic({'event':'task_end_requested','run_id':run,'reason':'current_running_target'})
                    else:
                        self.pending_task_end = None
                        self._diagnostic({'event':'task_end_held','reason':'running_source_not_current'})
                    return True
            identified = (connected and isinstance(run, str) and bool(run.strip())
                          and isinstance(boot, str) and bool(boot.strip()) and self.safety_sender is not None)
            cancel = intent('cancel'); cancel['source'] = dict(doc['source'])
            self._stop_locked(cancel, generation)  # 기존 공개 cancel만 발신; 정지 성공 아님
            if not identified:
                meta['final_text'] = self.session.flow['status_prompts']['unconfirmed']
                self._diagnostic({'event':'task_end_held','reason':'current_run_boot_or_adapter_unconfirmed'})
                self._task_end_notice_locked(meta['final_text'])
                return True
            ending = dict(run=run, boot=boot, check=check, generation=self.generation, halt_seen=False)
            self.task_end_request = self.task_end_source = ending
            self._diagnostic({'event':'task_end_stop_requested','run_id':run,'reason':'explicit_end_not_completion'})
            self._advance_task_end_locked()
            return True
        if (self.notice_policy.phase == 'halted' and p is not None and p.work is not None
                and p.current_state_confirmed and self.safety_sender is not None
                and getattr(self.safety_exchange.evidence, 'stopped', False) is True):
            self._send_safety_candidate_locked(TaskEndCandidate(p.work), self.safety_sender)
            return True
        current = self._current_runner_status()
        idle_confirmed = (getattr(self, 'runner_control_source', None) is None or
                          current is not None and current['phase'] == 'idle' and current.get('halt') is None)
        empty = (idle_confirmed and self.notice_policy.phase == 'idle' and (p is None or p.work is None)
                 and (self.request_run.run_id is None or self.request_run.finished))
        last = (current or {}).get('last') or {}
        if (current is not None and current['phase'] == 'idle' and current.get('halt') is None
                and last.get('overall_status') == 'ABORTED'
                and (current.get('last_intent') or {}).get('decision') != 'run'
                and (self.request_run.run_id is None or self.request_run.run_id == last.get('run_id')
                     or self.request_run.finished)):
            empty = True  # C가 작업 종료를 확인했으면 오래된 E 문맥으로 불명 처리하지 않음.
        meta['final_text'] = prompts(self.cfg)['no_end_work'] if empty else self.session.flow['status_prompts']['unconfirmed']
        self._diagnostic({'event':'task_end_held','reason':'no_active_work' if empty else 'current_stop_unconfirmed'})
        if doc['intent'] == 'cancel' or self.normal_notice_cancel.is_set():
            self._task_end_notice_locked(meta['final_text'])
            return True
        return False

    def _task_end_notice_locked(self, text):
        marker = self._feedback_marker()
        self._control_notice_locked('task_end_held',text,guard=lambda: self._feedback_marker() == marker)

    def _control_notice_locked(self, kind, text, *, guard=None):
        # 기존 비권한 notice worker. 높은 안전 경고는 종료 보류 안내로 덮지 않습니다.
        with self.notice_condition:
            active = getattr(self, 'active_notice', None)
            if (self.pending_notice is not None and self.pending_notice.priority < 4
                    or active is not None and active.priority < 4):
                self._diagnostic({'event':'readonly_feedback_held','reason':'safety_warning_priority'})
                return
            self.notice_policy.revision += 1
            self.notice_cancel.set()
            self.pending_notice = Notice(kind, text, 4, self.notice_policy.revision, self.generation, guard)
            self.notice_condition.notify_all()

    def _cancel_readonly_notice_locked(self):
        # Caller owns submit_lock. Keep submit_lock -> notice_condition ordering.
        with self.notice_condition:
            kinds = ('readonly_query', 'control_rejected', 'task_end_held')
            if self.pending_notice is not None and self.pending_notice.kind in kinds:
                self.pending_notice = None
            active = getattr(self, 'active_notice', None)
            if active is not None and active.kind in kinds:
                self.notice_cancel.set()

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
            self._cancel_readonly_notice_locked()
            self.safety_activity.set()
            self.busy.set()
            self.place_condition.notify_all()
            return q

    def safety_registered(self, q, work, revision, *, valid_state, valid_until=None):
        with self.place_condition:
            accepted = self.safety_exchange.registered(q, work, revision, now=self.place_clock(),
                                                       valid_state=valid_state, valid_until=valid_until)
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
            self._cancel_readonly_notice_locked()
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
                self._send_safety_candidate_locked(result, sender)
            elif result is None:
                reason = self.safety_exchange.last_rejection_reason or 'no_current_candidate'
                self._diagnostic({'event':'safety_result_held','reason':reason})
                self.safety_feedback(work, 'failed', reason=reason)
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
        if result is None:
            return  # Session/등록 측의 구체 사유를 중복하지 않습니다.
        if (sender is None or cancel is not self.safety_cancel or cancel.is_set()
                or self.stop_event.is_set() or self.cfg['evaluation_mode']):
            return
        if isinstance(result, dict) and result.get('_voice', {}).get('readonly_query'):
            self.safety_readonly_result = (result, cancel, self.generation)
            self._flush_safety_readonly_locked()
        elif isinstance(result, dict) and result.get('intent') == 'cancel':
            self._stop_locked(result)
        elif isinstance(result, IndependentRegistration):
            sender('register_independent', result.request)
        elif isinstance(result, QuestionDeclined):
            sender('declined', result.question)
        elif isinstance(result, RecoveryRequest):
            sender('recover', result.work)
        else:
            self._send_safety_candidate_locked(result, sender)

    def _flush_safety_readonly_locked(self):
        pending = getattr(self, 'safety_readonly_result', None)
        if pending is None or self.safety_activity.is_set() or self.dialog_lock.locked():
            return
        self.safety_readonly_result = None
        doc, cancel, generation = pending
        if (cancel is self.safety_cancel and not cancel.is_set() and generation == self.generation
                and not self.stop_event.is_set()):
            self._readonly_feedback_locked(doc, generation)

    def _send_safety_candidate_locked(self, result, sender):
        if isinstance(result, TaskEndCandidate):
            self.pending_task_end = (result, self.generation)
            self._diagnostic({'event':'task_end_candidate','reason':'termination_acceptance_pending'})
        else:
            self.pending_resume = (result, self.generation)
        sender('candidate', result)

    def running_end_completed(self, candidate):
        pending = getattr(self,'pending_task_end',None)
        deferred = getattr(self, 'deferred_task_end', None)
        current = pending == (candidate, self.generation) or (deferred is not None
            and deferred[:2] == (candidate, self.generation))
        if (not current
                or not self._request_run_connected()):
            return False
        self.pending_task_end = None
        self._cancel_safety_locked()
        self._diagnostic({'event':'task_end_accepted','reason':'current_c_stop_and_disposal_confirmed'})
        from ready2go_voice.core.hotfix import control_notice
        self._control_notice_locked('control_end',control_notice(self.cfg, 'end', runtime=True))
        return True

    def running_end_deferred(self, candidate, event_id, request_id):
        """Unconfirmed is a retained target, not pending success or new permission."""
        marker = (candidate, self.generation, event_id, request_id)
        if getattr(self, 'deferred_task_end', None) == marker:
            return
        if getattr(self, 'pending_task_end', None) != (candidate, self.generation):
            return
        self.pending_task_end = None
        self.deferred_task_end = marker
        self._diagnostic({'event':'task_end_deferred','reason':'STOP_NOT_CONFIRMED',
                          'run_id':candidate.work.task, 'event_id':event_id})
        from ready2go_voice.core.hotfix import control_notice
        self._control_notice_locked('task_end_deferred',control_notice(self.cfg, 'end_pending', runtime=True))

    def running_end_discarded(self, candidate):
        deferred = getattr(self, 'deferred_task_end', None)
        if (deferred is None or deferred[:2] != (candidate, self.generation)
                or not self._request_run_connected()):
            return False
        self._cancel_safety_locked()
        self._diagnostic({'event':'task_end_discarded','reason':'current_c_reset_disposal_not_stop_confirmation'})
        from ready2go_voice.core.hotfix import control_notice
        self._control_notice_locked('control_end_discarded',control_notice(self.cfg, 'discarded', runtime=True))
        return True

    def safety_task_end_accepted(self, candidate, *, valid_state):
        # 신뢰된 현재 C 수락 adapter/명시 더미 입력만 호출합니다. 모션/물리완료 증거 아님.
        with self.submit_lock:
            pending = getattr(self, 'pending_task_end', None)
            if (valid_state is not True or pending is None or pending[0] is not candidate
                    or pending[1] != self.generation or self.stop_event.is_set()):
                self._diagnostic({'event':'safety_result_held','reason':'termination_acceptance_not_current'})
                return False
            policy = self.safety_exchange.policy
            if (policy is None or getattr(self.safety_exchange.evidence, 'stopped', False) is not True
                    or not self._task_end_source_current() or not policy.ended(candidate.work, valid_state=True)):
                return False
            self.pending_task_end = None
            self._diagnostic({'event':'task_end_accepted','reason':'trusted_termination_acceptance_not_physical_completion'})
            return True

    def _refresh_busy_locked(self):
        occupied = (getattr(self, 'request_running', None) is not None or self.requests.unfinished_tasks > 0
                    or self.place_activity.is_set() or self.safety_activity.is_set())
        self.busy.set() if occupied else self.busy.clear()

    def _release_safety_locked(self, cancel):
        if self.safety_running is cancel:
            self.safety_running = None
        if self.safety_running is None and self.safety_pending is None:
            self.safety_activity.clear()
        self._refresh_busy_locked()
        self._flush_safety_readonly_locked()
        self.place_condition.notify_all()

    def _finish_feedback_locked(self, token):
        if getattr(self, 'control_feedback', None) is token:
            self.control_feedback = None
        pending = getattr(self, 'pending_task_end', None)
        if (token['kind'] == 'end' and pending is not None
                and pending[0] is token['candidate'] and pending[1] == token['generation']):
            self.pending_task_end = None  # 실패/취소된 후보도 재사용하지 않습니다. work는 보존합니다.

    def _report_worker_failure(self, event, exc):
        try:
            self._diagnostic({'event':event, 'error_type':type(exc).__name__, 'published':False})
        except Exception as diagnostic_exc:
            # 진단 경로 자체의 실패를 숨기지 않고 최소 비밀값 없는 오류를 남깁니다.
            print(json.dumps({'event':'voice_diagnostic_failed', 'operation':event,
                              'error_type':type(exc).__name__,
                              'diagnostic_error_type':type(diagnostic_exc).__name__}), flush=True)

    def _voice_input_busy(self):
        return (self.busy.is_set() or self.speaking.is_set() or self.tts.lock.locked()
                or self.place_activity.is_set() or self.safety_activity.is_set())

    def safety_feedback(self, work, kind, *, candidate=None, reason=None):
        """권한 없는 안내 작업. 질문 객체·TTL·과거 답변을 생성하지 않습니다."""
        from ready2go_voice.core.hotfix import prompts
        with self.place_condition:
            p = self.safety_exchange.policy
            if (self.cfg['evaluation_mode'] or self.stop_event.is_set() or p is None
                    or not p.current_state_confirmed or self.safety_sender is None
                    or getattr(self, 'control_feedback', None) is not None
                    or self.safety_pending is not None):
                return None
            if p.question is not None:  # 유효한 기존 질문의 등록/재생/답변 경로를 보존합니다.
                return None
            if kind == 'end':
                pending = getattr(self, 'pending_task_end', None)
                if pending != (candidate, self.generation) or pending[0] is not candidate:
                    return None
            elif p.work != work:
                return None
            if kind == 'resume':
                pending = getattr(self, 'pending_resume', None)
                if (pending != (candidate, self.generation) or pending[0] is not candidate
                        or p._recovery_mode(work, self.safety_exchange.evidence) != 'resume'):
                    return None
                self.pending_resume = None  # 후보는 한 번만 수락합니다.
            from ready2go_voice.core.hotfix import control_notice
            text = control_notice(self.cfg, kind, runtime=getattr(self, 'control_mapper', None) is not None,
                                  reason=reason)
            token = dict(work=work, kind=kind, candidate=candidate, generation=self.generation, text=text)
            previous_cancel = self.safety_cancel
            self.control_feedback = token
            self.safety_cancel = threading.Event()
            self.safety_pending = ('feedback', token)
            self._cancel_readonly_notice_locked()
            self.safety_activity.set()
            self.busy.set()
            try:
                self._diagnostic({'event':'control_feedback_queued','kind':kind,'reason':reason})
            except Exception:
                self.safety_cancel.set()
                self.safety_cancel = previous_cancel
                self.safety_pending = None
                self._finish_feedback_locked(token)
                if self.safety_running is None:
                    self.safety_activity.clear()
                self._refresh_busy_locked()
                self.place_condition.notify_all()
                raise
            self.place_condition.notify_all()
            return token

    def _feedback_current(self, token, cancel):
        p = self.safety_exchange.policy
        return (getattr(self, 'control_feedback', None) is token and token['generation'] == self.generation
                and cancel is self.safety_cancel and not cancel.is_set() and not self.stop_event.is_set()
                and p is not None and p.current_state_confirmed
                and (p.work == token['work'] if token['kind'] != 'end'
                     else p.work == token['work'] and self._task_end_source_current()
                     and getattr(self.safety_exchange.evidence, 'stopped', False) is True
                     and getattr(self, 'pending_task_end', None) == (token['candidate'], self.generation)))

    def _safety_feedback_play(self, token, cancel, sender):
        timing, started = {}, {}
        with self.submit_lock:
            if not self._feedback_current(token, cancel):
                return
        self.speaking.set()
        self._say(token['text'], cancel=cancel, on_start=started.update, on_timing=timing.update)
        end = timing.get('playback_ended_monotonic')
        proof = (finite(end) and finite(started.get('tts_started_monotonic'))
                 and started['tts_started_monotonic'] <= end <= self.place_clock()
                 and started.get('tts_start_basis') == 'portaudio_first_dac'
                 and timing.get('playback_end_basis') == 'portaudio_finished_callback'
                 and (started.get('tts_mock') is False or self.place_test_devices))
        with self.submit_lock:
            if not proof or not self._feedback_current(token, cancel):
                self._diagnostic({'event':'control_feedback_failed','reason':'tts_or_current_state_unconfirmed'})
                return
            sender('feedback_delivered', token)
            self._diagnostic({'event':'control_feedback_delivered','kind':token['kind']})

    def _safety_failure_feedback(self, work, generation, reason):
        with self.submit_lock:
            if generation == self.generation:
                self.safety_feedback(work, 'failed', reason=reason)

    def _safety_recording(self, recording, work):
        """새 웨이크 녹음만 독립 요청으로 처리하며 질문의 과거 답을 재분류하지 않습니다."""
        with self.place_condition:
            p = self.safety_exchange.policy
            if (p is None or p.work != work or not p.current_state_confirmed
                    or self.safety_sender is None or self.cfg['evaluation_mode']
                    or not finite(recording.recording_started_monotonic)):
                self._diagnostic({'event':'safety_input_held','reason':'work_state_sender_or_capture_unconfirmed'})
                return
            target = (p.question if p.question is not None else
                      self.safety_exchange.begin_independent(now=recording.recording_started_monotonic,
                                                             unique_target=True))
            if target is None:
                self._diagnostic({'event':'safety_input_held','reason':'current_question_or_request_pending'})
                return
            cancel = self.safety_cancel = threading.Event()
            self.safety_running = cancel
            self._cancel_readonly_notice_locked()
            self.safety_activity.set()
            sender = self.safety_sender
        try:
            generation = self.generation
            result = self.session.safety_audio(self.safety_exchange, target, recording, cancel=cancel,
                                               paused=lambda: self.stop_event.is_set(),
                                               on_failure=lambda reason: self._safety_failure_feedback(work, generation, reason))
            with self.place_condition:
                self._safety_result_locked(result, cancel, sender)
            if isinstance(result, IndependentRegistration):
                self._wait_safety_registration(target, cancel)
        finally:
            with self.place_condition:
                self._release_safety_locked(cancel)

    def _wait_safety_registration(self, target, cancel):
        # Keep the current request's single ownership until ACK or its existing deadline.
        with self.place_condition:
            while self.safety_exchange.current(target) and not cancel.is_set() and not self.stop_event.is_set():
                remaining = self.safety_exchange.budget(target, now=self.place_clock())
                if remaining is None or remaining < 0:
                    self.safety_exchange.fail(target)
                    break
                self.place_condition.wait(.001 if remaining == 0 else min(.1, remaining))

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
            result = None
            with self.dialog_lock:
                try:
                    if mode == 'feedback':
                        if self.cfg['audio_enabled'] and sender is not None:
                            self._safety_feedback_play(target, cancel, sender)
                        continue
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
                                limit = self.safety_exchange.policy.question_until
                                remaining = limit - self.place_clock() if limit is not None else None
                                if remaining is not None and remaining <= 0:
                                    raise TimeoutError('SAFETY_REGISTRATION_EXPIRED')
                                self.place_condition.wait(.1 if remaining is None else min(.1, remaining))
                        if self._safety_paused(target, cancel) or self.place_clock() >= self.safety_exchange.policy.question_until:
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
                    generation = self.generation
                    result = self.session.safety_audio(self.safety_exchange, target, recording, cancel=cancel,
                                                      paused=lambda: self.stop_event.is_set(),
                                                      on_failure=lambda reason: self._safety_failure_feedback(target.work, generation, reason))
                    with self.submit_lock:
                        self._safety_result_locked(result, cancel, sender)
                    if isinstance(result, IndependentRegistration):
                        self._wait_safety_registration(target, cancel)
                except Exception as exc:
                    if mode != 'feedback':
                        self.safety_exchange.fail(target)
                    self._report_worker_failure('safety_question_failed', exc)
                finally:
                    if not self.tts.lock.locked():
                        self.speaking.clear()
                    with self.place_condition:
                        if (mode == 'question' and getattr(self, 'control_mapper', None) is not None
                                and not (isinstance(result, dict) and result.get('_voice', {}).get('readonly_query'))):
                            sender('expired', target)  # close only this C-registered unanswered question
                        if mode == 'feedback':
                            self._finish_feedback_locked(target)
                        self._release_safety_locked(cancel)
            with self.submit_lock:
                self._flush_safety_readonly_locked()

    def _diagnostic(self, doc):
        value = dict(doc)
        context = getattr(self, 'local_context', None)
        if context is not None and getattr(context, 'request_id', None):
            value.setdefault('request_id', context.request_id)
        meta = (doc.get('intent') if isinstance(doc.get('intent'), dict) else {}).get('_voice') or {}
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
        if event == 'voice_state':
            state = tuple(doc.get(key) for key in ('phase','work_retained','termination_pending'))
            if state == getattr(self, '_console_voice_state', None):
                return
            self._console_voice_state = state
        if event in ('stop_stt_result', 'safety_stt_result'):
            return  # raw/self/irrelevant transcripts remain in bounded detail only
        if event == 'stop_audio_held' and doc.get('reason') in ('empty_transcript', 'not_explicit_stop', 'overlapping_self_speech', 'canceled', 'stale_generation', 'NO_SPEECH'):
            return
        reason = '' if doc.get('reason') is None else str(doc['reason'])
        if event in ('safety_audio_held','safety_input_held','safety_result_held','stop_audio_held','control_feedback_failed','runner_memory_held'):
            key = (event, reason, getattr(self, 'generation', None))
            seen = getattr(self, '_console_held', None)
            if seen is None:
                self._console_held = seen = deque(maxlen=128)
            if key in seen:
                return
            seen.append(key)
        messages = {
            'ready': '음성 준비 완료 (' + ('평가: 실행 보류' if doc.get('evaluation_mode') else '실행 모드') + ')', 'wake_waiting': f"웨이크 대기 (입력: {doc.get('input_device')})",
            'capture_ready': '말씀해 주세요 (새 녹음 준비)',
            'wake_cue_finished': '알림음 종료 · 수락 TTS 아님',
            'wake_detected': f"웨이크 감지 (점수 {(doc.get('score') or 0):.3f})",
            'record_started': f"녹음 시작 ({doc.get('duration', '무음 종료')}초)",
            'record_finished': '녹음 완료', 'whisper_requested': 'Whisper 요청',
            'stt_result': f"STT 결과: {doc.get('text', '')}",
            'stop_stt_result': f"정지 STT 결과: {doc.get('text','')}",
            'stop_control_accepted': f"제어 입력 수용 ({doc.get('kind')}): {doc.get('text','')}",
            'task_end_deferred': '정지 미확인: 종료 보류 · 작업/잠금 보존 · 직접 확인 필요',
            'task_end_discarded': '현재 C 보존 작업 폐기 확인 · 정지/잠금 해제 아님',
            'runner_memory_held': 'Runner 기록 확인 불가: ' + reason,
            'control_decision': f"제어 결과: {doc.get('intent')} / {doc.get('decision')} / {reason or '사유 없음'}",
            'safety_stt_result': f"중단 후 STT 결과: {doc.get('text','')}",
            'voice_state': f"Voice 상태: {doc.get('phase')} / 중단 작업 보존={doc.get('work_retained')} / 종료 수락 대기={doc.get('termination_pending')}",
            'task_end_candidate': '작업 종료 후보 · 수락 대기',
            'task_end_accepted': '현재 작업 종료 수락 · 물리 완료 아님',
            'stop_audio_held': '정지 입력 보류: ' + reason,
            'speech_check_started': '발화 검사', 'no_speech': '발화 없음: STT·LLM 생략',
            'speech_check_failed': f"발화 검사 보류: {doc.get('error_type', '')}",
            'stt_failed': f"STT 실패: {doc.get('error_type', '')}",
            'tts_failed': f"TTS 실패: {doc.get('error_type', '')}",
            'tts_started': 'TTS 시작', 'tts_finished': 'TTS 종료',
            'runner_notice_failed': f"상태 음성 안내 실패: {doc.get('error_type', '')}",
            'recording_held': f"녹음 보류: {doc.get('reason', '')}",
            'audio_unavailable': f"음성 장치/모델 오류: {doc.get('error_type', '')}",
            'processing_failed': f"처리 실패: {doc.get('error_type', '')}",
            'safety_audio_failed': f"중단 후 음성 실패 ({doc.get('stage','')}): {doc.get('reason',doc.get('error_type',''))}",
            'safety_audio_held': '중단 후 음성 보류: ' + reason,
            'safety_input_held': '중단 후 입력 보류: ' + reason,
            'safety_result_held': '중단 후 후보 없음: ' + reason,
            'control_feedback_failed': '제어 안내 보류: ' + reason,
            'safety_question_failed': f"중단 후 안내 실패: {doc.get('error_type', '')}",
            'safety_audio_result': '중단 후 음성 후보: ' + doc.get('candidate_type',''),
            'execution_held': '원래 판정 ' + str(doc.get('original_intent') or '') + ' / 실행 보류: ' + reason,
            'request_accepted': 'Runner 요청 수락 확인',
            'request_decided': 'Runner 요청 보류·거절 확인',
            'request_completed': 'Runner 완료 확인 · 음성 안내 대기',
            'request_canceled': '취소: 실행 보류', 'request_duplicate': '중복: 실행 보류',
        }
        if event == 'stt_failed' and doc.get('api_error'):
            info = doc['api_error']
            messages[event] += (' / ' + json.dumps(redact(info), ensure_ascii=False))
        timing = doc.get('timing') or {}
        if event == 'tts_finished' and 'synthesis_wait_sec' in timing and 'playback_sec' in timing:
            messages[event] = (f"TTS 종료 (합성 대기 {timing['synthesis_wait_sec']:.3f}초, "
                               f"재생 {timing['playback_sec']:.3f}초)")
        if event == 'interpretation':
            value = doc['intent']
            route = '폴백' if value['source'].get('fallback_used') else ('LLM' if value['source'].get('llm_called') else '규칙')
            meta = value.get('_voice', {})
            original = meta.get('original_interpretation', value)
            messages[event] = f"{route} 결과: {original['intent']} {','.join(original.get('targets', []))}"
            if meta.get('execution_hold_reason'):
                messages[event] += ' / 실행 보류: ' + meta['execution_hold_reason']
        if event == 'intent':
            if not doc.get('published'):
                messages[event] = '실행 보류 (평가/확인 정책)'
            elif doc.get('intent', {}).get('intent') in ('find_item','achieve_goal'):
                pending = getattr(getattr(self, 'request_run', None), 'pending', None)
                request = doc.get('intent', {}).get('request_id') or doc.get('intent', {}).get('_voice', {}).get('request_id')
                accepted = request in getattr(self, 'accepted_request_logs', ()) or (pending is not None and pending.get('request_id') == request and self.request_run.run_id is not None)
                messages[event] = '실행 요청 발행 · 현재 요청 수락 확인' if accepted else '실행 요청 발행 · Runner 수락 미확인'
            else:
                messages[event] = '안내/제어 메시지 발행 · 실행 요청 수락 아님'
        if event == 'final_response':
            messages[event] = doc['text']
        if event == 'request_held':
            messages[event] = '요청 보류: ' + reason
        if event == 'cache_record_failed':
            messages[event] = doc['reason']
        if event == 'publish_failed':
            messages[event] = '발행 실패: 수락 미확인·새 요청 필요'
        # 일반 콘솔은 STT 전사/최종 응답/발행 상태/보류/오류를 표시합니다. 나머지 단계 증빙은 상세 파일에 보존합니다.
        hidden = {'record_started', 'record_finished', 'whisper_requested', 'speech_check_started', 'tts_started'}
        if event in messages and event not in hidden:
            try:
                self.get_logger().info(redact(messages[event]).replace('\n', ' ').replace('\r', ' '))
            except Exception as exc:
                if not self.stop_event.is_set():
                    raise
                print(json.dumps({'event':'voice_logger_cleanup_error','error_type':type(exc).__name__}),flush=True)

    def _init_runner_control_source(self):
        """Selected Runner source; control binding alone remains opt-in."""
        from ready2go_voice.adapters.runner_control import RunnerSource
        name = self.declare_parameter('control_runner_name', 'runner').value
        namespace = self.declare_parameter('control_runner_namespace', '/').value
        if not isinstance(name,str) or not name or not isinstance(namespace,str) or not namespace.startswith('/'):
            raise ValueError('selected Runner name/namespace required')
        topic = getattr(self.status_subscription, 'topic_name', '/runner/status')
        self.runner_control_source = RunnerSource(self.get_publishers_info_by_topic,topic,name=name,namespace=namespace)
        self._query_status = self._query_binding = None
        self._read_recovering = None
        self.parser.status_provider = self._runner_status_view

    def _current_runner_status(self):
        source = getattr(self, 'runner_control_source', None)
        binding = getattr(self, '_query_binding', None)
        doc = getattr(self, '_query_status', None)
        if source is None or binding is None or not isinstance(doc, dict):
            return None
        if not source.check(binding):
            # Reuse the existing loss/generation boundary while preserving only
            # an unaccepted state-first candidate for the next verified status.
            self._lose_control_source_locked(preserve_memory_candidate=True)
            return None
        halt = doc.get('halt')
        if (doc.get('boot_id') != binding.boot or doc.get('phase') not in ('idle','running','halted')
                or doc.get('last') is not None and not isinstance(doc['last'], dict)
                or doc.get('last_intent') is not None and not isinstance(doc['last_intent'], dict)
                or doc.get('phase') == 'running' and (not isinstance(doc.get('task_id'), str) or not doc['task_id'].strip())):
            return None
        if halt is not None:
            if (not isinstance(halt, dict) or halt.get('boot_id') != binding.boot
                    or type(halt.get('locked')) is not bool
                    or not isinstance(halt.get('event_id'), str) or not halt['event_id'].strip()
                    or halt.get('run_id') is not None and (not isinstance(halt['run_id'], str) or not halt['run_id'].strip())
                    or halt.get('stop') not in ('requested','confirmed','unconfirmed','none')
                    or halt.get('resume') is not None and not isinstance(halt['resume'], dict)):
                return None
            resume = halt.get('resume') or {}
            if halt.get('resume') is not None and (type(resume.get('offered')) is not bool
                    or not isinstance(resume.get('from_step'), str) or not resume['from_step'].strip()):
                return None
            for key in ('question','request'):
                value = resume.get(key)
                if value is not None and (not isinstance(value, dict)
                        or not isinstance(value.get('id'), str) or not value['id'].strip()
                        or not isinstance(value.get('state'), str) or not value['state'].strip()):
                    return None
        return deepcopy(doc)

    def _runner_status_view(self):
        # The wrapper is E-local read-only context, never a new public payload.
        with self.submit_lock:
            doc = self._current_runner_status()
            if doc is None:
                return None
            target = None
            pending, run = self.request_run.pending, self.request_run.run_id
            decision = doc.get('last_intent') or {}
            if (doc['phase'] == 'running' and isinstance(decision, dict) and pending is not None
                    and run is not None and not self.request_run.finished
                    and decision.get('decision') == 'run' and decision.get('run_id') == run
                    and decision.get('request_id') == pending['request_id']
                    and pending.get('intent') == decision.get('intent') == 'find_item'
                    and pending.get('targets') == decision.get('targets')
                    and len(pending.get('targets') or []) == 1):
                target = pending['targets'][0]
            mapper = getattr(self, 'control_mapper', None)
            request_id = getattr(self, '_read_recovering', None)
            sent = mapper.operations.get(request_id) if mapper is not None else None
            halt = doc.get('halt') or {}
            recovering = bool(sent is not None and sent.intent == 'recover'
                and sent.request_id not in mapper.result_ids and sent.generation == self.generation
                and mapper.boot == doc['boot_id'] and sent.work.session == doc['boot_id']
                and sent.work.task == halt.get('run_id') and sent.work.stop == halt.get('event_id'))
            return {'status':doc, 'target':target, 'recovering':recovering}

    def _feedback_marker(self):
        view = self._runner_status_view()
        if view is None:
            return None
        doc = view['status']; halt = doc.get('halt') or {}; last = doc.get('last') or {}
        resume = halt.get('resume') or {}; question = resume.get('question') or {}; request = resume.get('request') or {}
        # Seq/stamp progression alone does not obsolete a fresh read. Events,
        # active run/request and visible workflow meaning do.
        return (doc['boot_id'], doc['phase'], doc.get('task_id'),
                halt.get('event_id'), halt.get('run_id'), halt.get('stop'), halt.get('locked'),
                last.get('run_id') if doc['phase'] != 'running' else None,
                last.get('overall_status') if doc['phase'] != 'running' else None,
                self.request_run.run_id, view['target'], view['recovering'],
                resume.get('offered'), resume.get('from_step'),
                question.get('id'), question.get('state'), request.get('id'), request.get('state'),
                getattr(self, '_read_recovering', None) if view['recovering'] else None)

    def _control_rejection_text(self, operation):
        from ready2go_voice.core.hotfix import prompts
        from ready2go_voice.core.runner_speech import unavailable_work_text
        current = self._current_runner_status()
        values = prompts(self.cfg)
        text = unavailable_work_text(current, self.notice_policy.task_steps, values, operation=operation)
        return text or values['control_rejected' if current is not None else 'status_unknown']

    def _readonly_feedback_locked(self, doc, generation):
        from ready2go_voice.core.hotfix import reference_query, prompts
        meta = doc.get('_voice', {})
        source = doc.get('source', {})
        query = bool(meta.get('readonly_query') and doc['intent'] in ('status','unknown')
                     and source.get('execution_allowed') is False and source.get('llm_called') is False)
        rejection = meta.get('safety_control') in ('recover','resume','new_start')
        if not query and not rejection:
            return False
        request = source.get('stt_text', '')
        if query:
            text = reference_query(self.parser, request)
            if text is None or text != meta.get('final_text'):
                self._diagnostic({'event':'readonly_feedback_held','reason':'record_changed'})
                return True
        else:
            text = self._control_rejection_text(meta.get('safety_control'))
        binding = getattr(self, '_query_binding', None)
        marker = self._feedback_marker()
        memory_epoch = getattr(self, 'memory_epoch', None) if meta.get('query_kind') == 'record' else None
        def current():
            if self.stop_event.is_set() or generation != self.generation:
                return False
            if (getattr(self, '_query_binding', None) != binding or self._feedback_marker() != marker
                    or memory_epoch is not None and getattr(self, 'memory_epoch', None) != memory_epoch):
                return False
            if query:
                return reference_query(self.parser, request) == text
            expected = self._control_rejection_text(meta.get('safety_control'))
            return expected == text
        self._diagnostic({'event':'final_response','text':text,'intent':doc})
        self._diagnostic({'event':'readonly_feedback','kind':'query' if query else 'control_rejection',
                          'query_source':meta.get('query_source'), 'boot_id':binding.boot if binding else None,
                          'source_confirmed':self._current_runner_status() is not None, 'physical_observation':False,
                          'published':False})
        self._control_notice_locked('readonly_query' if query else 'control_rejected', text, guard=current)
        return True

    def _init_runner_memory(self, qos):
        from ready2go_voice.adapters.runner_control import RunnerMemory
        self.memory_qos = qos
        self.memory_epoch = 0
        self.memory_subscription = None
        self.runner_memory = RunnerMemory(self.runner_control_source, '/robot_state',
            items=self.parser.items, places=self.parser.places)
        self._replace_runner_memory_subscription()
        self.parser.state_provider = self._runner_memory_state

    def _replace_runner_memory_subscription(self):
        # Epoch belongs to this reader lifecycle, not a public state/boot field.
        # Queued callbacks from a destroyed reader cannot restore pre-loss state.
        self.memory_epoch += 1
        epoch = self.memory_epoch
        previous = self.memory_subscription
        self.memory_subscription = None
        try:
            if previous is not None and not self.destroy_subscription(previous):
                self.memory_subscription = previous
                raise RuntimeError('runner_memory_reader_destroy_failed')
            def receive(message, info):
                with self.submit_lock:
                    if epoch == self.memory_epoch:
                        self._robot_state(message, info)
            self.memory_subscription = self.create_subscription(String, '/robot_state', receive,
                self.memory_qos, callback_group=MutuallyExclusiveCallbackGroup())
            self.runner_memory.state_source.topic = getattr(self.memory_subscription, 'topic_name', '/robot_state')
            self.runner_memory.begin_replay()
        except Exception as exc:
            self.runner_memory.invalidate()
            self._diagnostic({'event':'runner_memory_held','reason':type(exc).__name__})

    def _robot_state(self, message, info):
        with self.submit_lock:
            if not self.runner_memory.observe(message.data, info):
                self._diagnostic({'event':'runner_memory_held','reason':'state_or_source_unconfirmed'})

    def _runner_memory_state(self):
        with self.submit_lock:
            state = self.runner_memory.current()
            if getattr(self, 'runner_control_source', None) is not None and self._current_runner_status() is None:
                return None
            return state

    def _lose_control_source_locked(self, *, preserve_memory_candidate=False):
        if not getattr(self, '_control_source_lost', False):
            self.generation += 1
            self.request_cancel.set()
            self.session.conversation.invalidate()
        self._control_source_lost = True
        self._control_binding = None
        self._query_status = self._query_binding = None
        with self.notice_condition:
            active = getattr(self, 'active_notice', None)
            if active is not None and active.priority == 4:
                self.notice_cancel.set()
            if self.pending_notice is not None and self.pending_notice.priority == 4:
                self.pending_notice = None
        if getattr(self, 'runner_memory', None) is not None:
            candidate = self.runner_memory.pending if preserve_memory_candidate else None
            self.runner_memory.invalidate()
            self.runner_memory.pending = candidate
        self._cancel_safety_locked()
        self.request_run.invalidate()

    def _runtime_control_current(self, source, binding):
        if not source.check(binding):
            with self.submit_lock:
                self._lose_control_source_locked()
            return False
        return not getattr(self, '_control_source_lost', False)

    def _consume_control_decision(self, result):
        sent = result.sent
        if sent.generation != self.generation or not self._request_run_connected():
            return None
        self._diagnostic({'event':'control_decision','intent':sent.intent,
            'decision':result.decision,'request_id':sent.request_id,'reason':result.reason})
        from ready2go_voice.core.recovery_confirmation import ActiveRun
        if isinstance(sent.work,ActiveRun):
            if result.decision in ('reject','hold'):
                pending = getattr(self,'pending_task_end',None)
                if pending == (sent.candidate,self.generation):
                    self.pending_task_end = None
                    self.control_mapper.pending = None
                    return 'failed'
            return None
        policy = self.safety_exchange.policy
        if policy is None or policy.work != sent.work:
            return None
        if result.decision == 'resume':
            pending = getattr(self, 'pending_resume', None)
            if pending is None or pending != (sent.candidate,self.generation):
                return None
            if not policy.c_resume_accepted(sent.work,sent.request_id,valid_state=True):
                return None
            self.pending_resume = None
            self.control_mapper.pending = None
            self._cancel_safety_locked()
            return 'resume'
        if result.decision in ('reject','hold','closed'):
            self._cancel_safety_locked()  # local question/request only, preserved work
            self.control_mapper.pending = None
            return 'failed' if result.decision in ('reject','hold') else None
        if result.decision == 'recover':
            return 'recover'
        return None  # END admission is not disposal; existing terminal checks remain.

    def _runner_status_with_info(self, message, info):
        source = getattr(self, 'runner_control_source', None)
        if source is not None:
            with self.submit_lock:
                binding = source.observe(message.data, info)
                if binding is None:
                    if source.reason not in ('runner_sequence_not_current','runner_boot_retired'):
                        self._lose_control_source_locked()
                    self._diagnostic({'event':'control_status_held','reason':source.reason})
                    return
                if binding != self._control_binding:
                    self._control_source_lost = False
                    if self.cfg.get('request_run_enabled') and not self.cfg['evaluation_mode']:
                        self._runtime_control_check = lambda: self._runtime_control_current(source,binding)
                        self.bind_control_source(self._runtime_control_check,boot=binding.boot,
                            publisher_gid=binding.endpoint_gid)
                    self._control_binding = binding
                self._query_status = json.loads(message.data)
                self._query_binding = binding
                memory = getattr(self, 'runner_memory', None)
                if memory is not None:
                    if memory.observe_status(binding, info):
                        self._replace_runner_memory_subscription()
        mapper = getattr(self, 'control_mapper', None)
        if mapper is None:
            self._runner_status(message)
            return
        with self.submit_lock:
            # Jazzy supplies four-key dict metadata, no per-sample publisher GID.
            previous_intent = (mapper.status or {}).get('last_intent')
            gid = info.get('publisher_gid') if isinstance(info,dict) else None
            if gid is not None:
                try:
                    gid = bytes(gid)
                except (TypeError,ValueError):
                    return
            if not mapper.accept(message.data, gid):
                if not mapper.connected() or mapper.reason in ('invalid_current_status','producer_boot_changed'):
                    if source is not None:
                        self._lose_control_source_locked()
                    else:
                        self._cancel_safety_locked()
                        self.request_run.invalidate()
                self._diagnostic({'event':'control_status_held','reason':mapper.reason})
                return
            decision = mapper.status.get('last_intent') or {}
            if (decision != previous_intent and decision.get('intent') == 'cancel'
                    and decision.get('decision') == 'cancel'
                    and (getattr(self, 'pending_task_end', None) is not None
                         or getattr(self, 'deferred_task_end', None) is not None)):
                self.generation += 1
                self.request_cancel.set()
                self.session.conversation.invalidate()
                self._cancel_safety_locked()
                mapper.pending = None  # visible C re-stop retires the old END intent
            notices = [(kind, result) for result in mapper.results
                       if (kind := self._consume_control_decision(result)) is not None]
            pending = getattr(self, 'pending_task_end', None)
            deferred = getattr(self, 'deferred_task_end', None)
            origin = getattr(self, 'task_end_source', None)
            end_current = (pending is not None and mapper.pending is not None
                and mapper.pending[0] == 'end_task' and mapper.pending[2] is pending[0]
                and pending[1] == self.generation and (pending[0].work == mapper.work
                    and mapper.evidence().stopped or getattr(pending[0].work,'stop',None) is None
                    and (mapper.status.get('halt') or {}).get('run_id') == pending[0].work.task))
            halt = mapper.status.get('halt') or {}
            deferred_current = (deferred is not None and deferred[1] == self.generation
                and mapper.pending is not None and mapper.pending[0] == 'end_task'
                and mapper.pending[1] == deferred[3] and mapper.pending[2] == deferred[0]
                and halt.get('boot_id') == deferred[0].work.session
                and halt.get('run_id') == deferred[0].work.task and halt.get('event_id') == deferred[2])
            self._runner_status(message, preserve_safety=mapper.same_work, control_verified=True)
            if (end_current or deferred_current) and mapper.connected():
                # A terminal phase transition may invalidate ordinary requests.
                # Restore only this verified END's pending feedback correlation.
                if end_current:
                    self.pending_task_end = (pending[0], self.generation)
                if deferred_current:
                    self.deferred_task_end = (deferred[0], self.generation, deferred[2], deferred[3])
                if mapper.pending is not None:
                    from dataclasses import replace
                    operation = mapper.operations.get(mapper.pending[1])
                    if operation is not None:
                        mapper.operations[mapper.pending[1]] = replace(operation,generation=self.generation)
                self.task_end_source = origin
            mapper.dispatch(self)
            if notices:
                from ready2go_voice.core.hotfix import control_notice
                kind, result = notices[-1]
                # Registered recovery question takes precedence over a second
                # recovery announcement; rejection remains explicit/detail-led.
                policy = self.safety_exchange.policy
                if not (kind == 'recover' and policy is not None and policy.question is not None):
                    text = control_notice(self.cfg,kind,runtime=True,reason=result.reason,operation=result.sent.intent)
                    if kind == 'recover':
                        from ready2go_voice.core.hotfix import prompts
                        from ready2go_voice.core.runner_speech import unavailable_work_text
                        text = unavailable_work_text(mapper.status,self.notice_policy.task_steps,prompts(self.cfg),
                            recovered=True,run_id=result.sent.work.task) or text
                    self._control_notice_locked('control_' + kind,text)

    def bind_control_source(self, check, *, boot, publisher_gid, proof_provider=None):
        """Explicit verified C binding; existing request_run opt-in still required.

        Runtime initializes from RunnerSource and uses current C proposals/ACKs.
        proof_provider is an optional legacy typed adapter; it is not a required
        C public interface. Endpoint GID here is graph identity, not sample proof.
        """
        from ready2go_voice.core.control_mapping import ControlMapper
        mapper = ControlMapper(boot=boot, publisher_gid=publisher_gid, source_check=check,
            enabled=lambda: (self.cfg.get('request_run_enabled', False) is True
                and not self.cfg['evaluation_mode'] and not self.stop_event.is_set()),
            schema=self.parser.validator.schema,
            clock=self.place_clock, cfg=self.cfg, publish=self._publish,
            exchange=self.safety_exchange, proof_provider=proof_provider, generation=lambda: self.generation)
        with self.submit_lock:
            self.bind_request_source(check, boot=boot)
            self.control_mapper = mapper
            self.safety_sender = self._send_control
            policy = self.safety_exchange.policy
            if policy is not None and policy.session != boot and mapper.connected():
                policy.track_boot(boot,valid_state=True)
        return mapper

    def _send_control(self, kind, value):
        with self.submit_lock:
            mapper = getattr(self, 'control_mapper', None)
            if mapper is None:
                return False
            if kind == 'feedback_delivered':
                pending = mapper.pending
                if (pending is None or value.get('candidate') is not pending[2]
                        or value.get('generation') != self.generation or not mapper.connected()
                        or value.get('work') != mapper.work):
                    return False
                if value['kind'] == 'end':
                    doc = mapper.status
                    decision, halt, last = doc.get('last_intent') or {}, doc.get('halt') or {}, doc.get('last') or {}
                    valid = (pending[0] == 'end_task' and decision.get('intent') == 'end_task'
                        and decision.get('decision') == 'end' and decision.get('request_id') == pending[1]
                        and 'resume' in halt and halt['resume'] is None and mapper.evidence().stopped is True
                        and last.get('run_id') == mapper.work.task and last.get('overall_status') == 'ABORTED')
                    accepted = self.safety_task_end_accepted(pending[2], valid_state=valid)
                elif value['kind'] == 'resume':
                    key = 'question' if pending[0] == 'resume_answer' else 'request'
                    echo = ((mapper.status.get('halt') or {}).get('resume') or {}).get(key) or {}
                    expected = mapper.operations[pending[1]].question_id if key == 'question' else pending[1]
                    accepted = (echo.get('id') == expected and echo.get('state') == 'resumed'
                        and self.safety_exchange.policy.resumed(mapper.work, valid_state=True, evidence=mapper.evidence()))
                else:
                    return False
                if accepted:
                    mapper.pending = None
                return accepted
            previous_operations = set(mapper.operations) if kind == 'recover' else None
            accepted = mapper.send(kind, value)
            if accepted and kind == 'recover':
                current_requests = set(mapper.operations) - previous_operations
                self._read_recovering = next(iter(current_requests)) if len(current_requests) == 1 else None
            if not accepted:
                self._diagnostic({'event':'control_publish_held','kind':kind,'reason':mapper.reason or 'proof_or_target_unconfirmed'})
                if kind in ('register_question','register_independent'):
                    self.safety_exchange.fail(value)
                    self.place_condition.notify_all()
                elif kind == 'candidate':
                    if isinstance(value, TaskEndCandidate):
                        self.pending_task_end = None
                    else:
                        self.pending_resume = None
                if not mapper.connected():
                    mapper.invalidate()
                    self._cancel_safety_locked()
                    self.request_run.invalidate()
            return accepted

    def _request_run_connected(self):
        # The integration mapper verifies the current producer and restart boundary.
        # Jazzy metadata/graph or a received JSON alone does not authenticate it.
        check = getattr(self, 'request_source_check', None)
        if check is None:
            return False
        try:
            mapper = getattr(self, 'control_mapper', None)
            connected = (check() is True and (mapper is None or mapper.connected() and mapper.status is not None))
        except Exception:
            connected = False
        if not connected:
            with self.submit_lock:
                self.request_run.invalidate()
        return connected

    def bind_request_source(self, check, *, boot=None):
        """실제 C 연결 확인 함수를 설치합니다. bool/readiness 캐시는 받지 않습니다."""
        if not callable(check):
            raise TypeError('current C source check callable required')
        if boot is not None and (not isinstance(boot, str) or not boot.strip()):
            raise TypeError('current verified producer boot identity required')
        with self.submit_lock:
            if check is not getattr(self, '_runtime_control_check', None):
                self.runner_control_source = None  # explicit legacy/dummy binding keeps its workflow
            if getattr(self, 'control_mapper', None) is not None:
                self.control_mapper.invalidate()
                self.control_mapper = None
                self.safety_sender = None
            if getattr(self, 'request_source_check', None) is not None:
                self.generation += 1
                self.request_cancel.set()
                self.session.conversation.invalidate()
            self._cancel_safety_locked()
            self.request_run.invalidate()
            self.request_source_check = check
            self.request_source_boot = boot  # 내부 검증 adapter 입력; 새 공개 wire 필드 아님
            p = self.safety_exchange.policy
            if p is not None and boot is not None and p.session != boot:
                p.current_state_confirmed = False

    def _runner_status(self, message, *, preserve_safety=False, control_verified=False):
        if getattr(self, 'control_mapper', None) is not None and not control_verified:
            return  # active W4 binding cannot be bypassed by a raw status callback
        # 관측 상태 전환과 질문 무효화는 발행 게이트와 같은 E 로컬 lock으로 직렬화합니다.
        # P1 경고는 유지하고 opt-in 요청만 실제 C 수락/결과에 연결합니다.
        with self.submit_lock:
            with self.notice_condition:
                events = []
                cause = None
                if self.cfg.get('request_run_enabled', False) and self._request_run_connected():
                    try:
                        status = json.loads(message.data)
                    except (ValueError, TypeError):
                        return
                    if (not isinstance(status, dict) or status.get('phase') not in ('idle', 'running', 'halted')
                            or status.get('last_intent') is not None and not isinstance(status['last_intent'], dict)
                            or status.get('halt') is not None and not isinstance(status['halt'], dict)):
                        return
                    pending = self.request_run.pending
                    token = ((pending['request_id'], self.request_run.run_id,
                              getattr(self, 'request_source_boot', None), self.generation) if pending else None)
                    evidence = getattr(self, 'cause_speech', None)
                    if evidence is not None and evidence[0] == token:
                        cause = (token[1], evidence[1], evidence[2])
                    continuity = getattr(self, 'request_speech_current', None)
                    decision = status.get('last_intent') or {}
                    if continuity is not None and (status['phase'] != 'running'
                            or (status.get('halt') or {}).get('locked') is True
                            or status.get('task_id') != continuity[1]
                            or decision.get('decision') == 'run' and decision.get('run_id') != continuity[0][1]):
                        self.request_speech_current = self.request_speech_completed = None
                    events = self.request_run.observe(status)
                previous = self.notice_policy.revision
                previous_phase = self.notice_policy.phase
                notice = self.notice_policy.observe(message.data, cause=cause)
                if self.notice_policy.phase != 'running':
                    self.cause_speech = None
                retained = bool(self.safety_exchange.policy and self.safety_exchange.policy.work
                                or getattr(self, 'deferred_task_end', None))
                if control_verified:
                    retained = bool(((self.control_mapper.status or {}).get('halt') or {}).get('resume'))
                self._diagnostic({'event':'voice_state','phase':self.notice_policy.phase,
                    'work_retained':retained,
                    'termination_pending':getattr(self,'pending_task_end',None) is not None})
                ending = getattr(self, 'task_end_request', None)
                first_end_stop = (ending is not None and not ending['halt_seen']
                                  and ending['generation'] == self.generation and self.notice_policy.phase == 'halted')
                same_end_halt = ((ending is not None or getattr(self, 'pending_task_end', None) is not None)
                                 and previous_phase == self.notice_policy.phase == 'halted'
                                 and notice is None and previous == self.notice_policy.revision
                                 and self._task_end_source_current())
                if (self.notice_policy.blocked or self.notice_policy.phase == 'halted'
                        or notice and notice.kind != 'completed'):
                    if (hasattr(self, 'safety_exchange') and not same_end_halt
                            and not (preserve_safety and notice is None)):
                        self._cancel_safety_locked()
                        if first_end_stop:
                            self.task_end_request = self.task_end_source = ending
                    if getattr(self, 'place_topic', ''):
                        self._cancel_place_locked()
                if (not notice and not self.notice_policy.blocked
                        and any(event['event'] == 'request_completed' for event in events)):
                    self.notice_policy.revision += 1
                    notice = Notice('completed', '요청한 작업을 완료했습니다.', 4,
                                    self.notice_policy.revision)
                for event in events:
                    if event['event'] == 'request_accepted':
                        self.request_speech_current = ((event['request_id'], event['run_id'],
                            getattr(self, 'request_source_boot', None), self.generation), status.get('task_id'))
                        if not hasattr(self, 'accepted_request_logs'):
                            self.accepted_request_logs = deque(maxlen=128)
                        self.accepted_request_logs.append(event['request_id'])
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
                    if getattr(self, 'cue_cancel', None) is not None:
                        self.cue_cancel.set()
                if first_end_stop:
                    ending.update(generation=self.generation, halt_seen=True)
                if ending is not None and self.notice_policy.phase == 'idle':
                    self.task_end_request = self.task_end_source = None
                self._advance_task_end_locked()

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
        if doc.get('_voice', {}).get('safety_control') == 'task_end':
            return self._task_end_locked(doc, self.generation if generation is None else generation)
        self.session.conversation.invalidate()
        self._cancel_place_locked()
        self._cancel_safety_locked()
        self.generation += 1
        self.request_cancel.set()
        if getattr(self, 'cue_cancel', None) is not None:
            self.cue_cancel.set()
        self.request_run.invalidate()
        self.warning_epoch += 1
        with self.notice_condition:
            self.notice_cancel.set()
            self.pending_notice = None
            self.notice_condition.notify_all()
        published = self.session.should_publish(doc)
        if published:
            self._publish(doc)
        self._diagnostic({'event':'stop_request_published','published':published,'requested_monotonic':self.place_clock()})
        self._diagnostic({'event': 'intent', 'intent': doc, 'published': published})
        return published

    def _stop_process(self):
        interval = self.cfg['frame_samples'] / self.cfg['sample_rate']
        while not self.stop_event.is_set():
            try:
                recording, generation, spoken = self.stop_captures.get(timeout=interval)
            except queue.Empty:
                continue
            try:
                def interrupted():
                    return self.stop_event.is_set() or generation != self.generation
                if interrupted():
                    self._diagnostic({'event':'stop_audio_held','reason':'stale_generation'})
                    continue
                doc = self.session.stop_audio(recording, paused=interrupted, spoken_texts=spoken)
                if doc is not None:
                    with self.submit_lock:
                        self._stop_locked(doc, generation)
            except Exception as exc:
                self._report_worker_failure('stop_processing_failed', exc)
            finally:
                self.stop_captures.task_done()

    def _queue_stop_capture(self, recording, generation, spoken):
        with self.submit_lock:
            if self.stop_event.is_set() or generation != self.generation:
                return False
            try:
                self.stop_captures.put_nowait((recording,generation,frozenset(spoken)))
            except queue.Full:
                try:
                    self.stop_captures.get_nowait();self.stop_captures.task_done()
                except queue.Empty:
                    pass
                self.stop_captures.put_nowait((recording,generation,frozenset(spoken)))
                try:
                    self._diagnostic({'event':'stop_capture_replaced','reason':'newest_pending_capture_only'})
                except Exception as exc:
                    self._report_worker_failure('stop_capture_diagnostic_failed', exc)
            return True

    def _quiet_stopped(self):
        with self.submit_lock:
            exchange = self.safety_exchange
            p = exchange.policy
            return (p is not None and p.current_state_confirmed and p.work is not None
                    and getattr(exchange.evidence, 'stopped', False) is True
                    and self.notice_policy.phase == 'halted'
                    and getattr(self, 'pending_resume', None) is None
                    and getattr(self, 'pending_task_end', None) is None
                    and getattr(self, 'control_feedback', None) is None)

    def _stop_listen(self):
        if not hasattr(self,'stop_captures'):
            self.stop_captures = queue.Queue(maxsize=1)
        if getattr(self,'stop_processor',None) is None:
            self.stop_processor = threading.Thread(target=self._stop_process,daemon=True)
            self.stop_processor.start()
        # 일반 wake/fixed 설정과 무관하게 정지는 기존 RMS/무음 종료 녹음을 사용합니다.
        recorder = Recorder(self.cfg, clock=self.place_clock, shared_input=self.shared_input)
        interval = self.cfg['frame_samples'] / self.cfg['sample_rate']
        def diagnostic(doc):
            try:
                self._diagnostic(doc)
            except Exception as exc:
                self._report_worker_failure('stop_capture_diagnostic_failed', exc)
        while not self.stop_event.is_set():
            cue_active = getattr(self, 'cue_active', None)
            if cue_active is not None and cue_active.is_set():
                self.stop_event.wait(interval); continue
            active = (self.busy.is_set() or self.speaking.is_set() or self.tts.lock.locked()
                      or self.place_activity.is_set() or self.safety_activity.is_set()
                      or runner_blocks(self) and not self._quiet_stopped())
            if not active:
                self.stop_event.wait(interval)
                continue
            with self.submit_lock:
                generation = self.generation
            diagnostic({'event':'stop_capture_started'})
            spoken = set()
            def interrupted():
                return (self.stop_event.is_set() or generation != self.generation
                        or cue_active is not None and cue_active.is_set())
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
                diagnostic({'event':'stop_capture_finished','recording_started_monotonic':recording.recording_started_monotonic,
                    'recording_ended_monotonic':recording.recording_ended_monotonic,'speech_ended_monotonic':recording.ended_monotonic,
                    'sample_count':len(recording.pcm)//2})
                self._queue_stop_capture(recording, generation, spoken)
            except TimeoutError as exc:
                code = str(exc)
                diagnostic({'event':'stop_capture_held','reason':code if code in ('NO_SPEECH','RECORD_LIMIT') else type(exc).__name__})
                continue  # 기존 음성 시작/최대 길이 경계. 무음은 API를 호출하지 않습니다.
            except InterruptedError as exc:
                if (self.stop_event.is_set() or self.shared_input._closed
                        or self.shared_input._stream is None):
                    return
                if not interrupted():
                    diagnostic({'event':'stop_input_unavailable','error_type':type(exc).__name__})
                    return
                continue
            except Exception as exc:
                if isinstance(exc, RuntimeError) and str(exc) == 'AUDIO_OVERFLOW':
                    diagnostic({'event':'stop_capture_held','reason':'AUDIO_OVERFLOW'})
                    continue  # stream context를 닫아 손상 PCM을 버리고 새 reader만 사용합니다.
                diagnostic({'event': 'stop_input_unavailable', 'error_type': type(exc).__name__})
                return

    def _notice_work(self):
        while not self.stop_event.is_set():
            with self.notice_condition:
                self.notice_condition.wait_for(lambda: self.pending_notice is not None or self.stop_event.is_set())
                if self.stop_event.is_set(): return
                notice, self.pending_notice = self.pending_notice, None
                if notice.revision != self.notice_policy.revision: continue
                cancel = self.notice_cancel = threading.Event()
                # Reserve before releasing the queue lock; low feedback sees inflight warnings.
                self.active_notice = notice
            self._play_notice(notice, cancel)

    def _play_notice(self, notice, cancel=None):
        cancel = cancel if cancel is not None else self.notice_cancel
        low = notice.kind in ('readonly_query', 'control_rejected', 'task_end_held')
        timing = {}
        owns_dialog = False
        try:
            if low:
                owns_dialog = self.dialog_lock.acquire(blocking=False)
                if not owns_dialog:
                    cancel.set()
                    return
            with self.submit_lock:
                if (cancel.is_set() or self.stop_event.is_set() or notice.revision != self.notice_policy.revision
                        or notice.generation is not None and notice.generation != self.generation
                        or notice.guard is not None and not notice.guard()):
                    return
                if low and (self.place_activity.is_set() or self.safety_activity.is_set()):
                    self._diagnostic({'event':'readonly_feedback_held','reason':'question_capture_priority'})
                    return
                self.active_notice = notice
            self.speaking.set()
            def started(stamp):
                with self.submit_lock:
                    if (cancel.is_set() or self.stop_event.is_set()
                            or notice.revision != self.notice_policy.revision
                            or notice.generation is not None and notice.generation != self.generation
                            or notice.guard is not None and not notice.guard()
                            or low and (self.place_activity.is_set() or self.safety_activity.is_set())):
                        cancel.set()
                        raise InterruptedError('NOTICE_NOT_CURRENT')
                self._diagnostic({'event':'tts_started','notice_kind':notice.kind,'source':stamp,'timing':dict(timing)})
            self._say(notice.text, cancel=cancel, on_timing=timing.update, on_start=started)
            self._diagnostic({'event':'tts_finished','notice_kind':notice.kind,'timing':dict(timing)})
        except InterruptedError:
            pass
        except Exception as exc:
            self._diagnostic({'event':'runner_notice_failed','notice_kind':notice.kind,'error_type':type(exc).__name__})
        finally:
            with self.notice_condition:
                if getattr(self, 'active_notice', None) is notice:
                    self.active_notice = None
            if owns_dialog:
                self.dialog_lock.release()
            if not self.tts.lock.locked(): self.speaking.clear()

    def _publish(self, doc):
        message = String()
        message.data = json.dumps(redact({k: v for k, v in doc.items() if not k.startswith('_')}), ensure_ascii=False)
        mapper = getattr(self, 'control_mapper', None)
        if mapper is not None and mapper.publishing is not None and not mapper.publish_guard(doc):
            return False  # serialized payload still needs a current send-boundary proof
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
                        if kind in ('recover','resume','new_start'):
                            self._readonly_feedback_locked(self.session.text(message.data, self.generation), self.generation)
                        else:
                            from ready2go_voice.core.hotfix import prompts
                            self._task_end_notice_locked(prompts(self.cfg)['status_unknown'] if self._current_runner_status() is None else prompts(self.cfg)['control_rejected'])
                return
        control = self.parser.control(message.data)
        if control:
            if control['intent'] == 'status':
                with self.submit_lock:
                    self._deliver(self.parser.parse(message.data), self.generation)
                return
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
            if (self.busy.is_set() or self.place_activity.is_set() or self.safety_activity.is_set() or self.stop_event.is_set() or
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
            owner = object()
            with self.submit_lock:
                self.request_running = owner
            try:
                self.local_context.request_id = request_id
                if kind == 'safety_audio':
                    self._safety_recording(*value)
                    continue
                policy = getattr(self, 'notice_policy', None)
                blocked = runner_blocks(self)
                state = policy.phase if policy else None
                if blocked and state not in ('running','halted'):
                    safety_policy = getattr(getattr(self, 'safety_exchange', None), 'policy', None)
                    state = 'locked' if safety_policy and safety_policy.work is not None else 'unconfirmed'
                if kind == 'record_error':
                    self.session.conversation.invalidate()
                    doc = intent('clarify', question=self.cfg['clarify_prompts']['empty'])
                    doc['source'] = {'input_kind': 'audio', 'stt_text': '', 'record_error': value,
                        'llm_called': False, 'llm_validation': 'not_called', 'fallback_used': False,
                        'execution_allowed': False}
                else:
                    doc = self.session.audio(value, cancel=self.request_cancel,
                        paused=lambda: self.stop_event.is_set() or generation != self.generation,
                        generation=generation, blocked=blocked, request_id=request_id, runner_state=state) if kind == 'audio' else self.session.text(value, generation, blocked, request_id=request_id, runner_state=state)
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
                self._report_worker_failure('processing_failed', exc)
            finally:
                self.local_context.request_id = None
                self.requests.task_done()
                with self.place_condition:
                    if self.request_running is owner:
                        self.request_running = None
                    self._refresh_busy_locked()
                    self.place_condition.notify_all()

    def _deliver(self, doc, generation):
        with self.submit_lock:
            if (not self.stop_event.is_set() and generation == self.generation and runner_blocks(self)
                    and doc['intent'] in ('find_item','clarify')
                    and not doc['source'].get('stt_error') and not doc['source'].get('record_error')):
                from ready2go_voice.core.flow import blocked_prompt
                meta = doc.setdefault('_voice', {})
                meta.setdefault('original_interpretation', {k: doc[k] for k in ('intent','targets','confidence') if k in doc})
                self.session.conversation.invalidate()
                # 현재 상태 안내만 합니다. 과거 질문 권한/실행 후보는 복원하지 않습니다.
                for key in ('question_target','asks_delivery_target','context_answer','context_generation','context_epoch','question_expires','preserve_question_id'):
                    meta.pop(key, None)
                state = getattr(getattr(self, 'notice_policy', None), 'phase', None)
                safety = getattr(getattr(self, 'safety_exchange', None), 'policy', None)
                if state != 'running' and safety and safety.work is not None:
                    state = 'locked'
                doc.update(intent='clarify', targets=[], clarify_question=blocked_prompt(self.cfg, state))
                doc['source']['execution_allowed'] = False
                meta.update(request_epoch=self.session.conversation.epoch, execution_hold_reason='runner_busy_or_locked', final_text=doc['clarify_question'])
                self._diagnostic({'event':'execution_held','reason':'runner_busy_or_locked','original_intent':meta['original_interpretation']['intent']})
            readonly = doc.get('_voice', {}).get('readonly_query') is True
            if (self.stop_event.is_set() or generation != self.generation
                    or not readonly and not self.session.valid_context(doc, generation)):
                self._diagnostic({'event': 'request_canceled', 'published': False})
                return
            if doc['intent'] in ('find_item', 'achieve_goal') and self.session.is_duplicate(doc):
                self._diagnostic({'event': 'request_duplicate', 'intent': doc, 'published': False})
                return
        with self.submit_lock:
            if self._readonly_feedback_locked(doc, generation):
                return
        if doc['intent'] == 'achieve_goal' and runner_blocks(self):
            self.session.conversation.invalidate()
            self._diagnostic({'event':'request_held','reason':'runner_busy_or_locked','intent':doc,'published':False})
            return  # P2 목표 차단 계약은 불변입니다.
        if doc.get('_voice', {}).get('safety_control') == 'task_end':
            with self.submit_lock:
                if self._task_end_locked(doc, generation):
                    return
        if doc.get('_voice', {}).get('safety_control') not in (None, 'task_end'):
            from ready2go_voice.core.hotfix import prompts
            policy = getattr(getattr(self,'safety_exchange',None),'policy',None)
            if policy is not None and policy.work is not None:
                doc['_voice']['final_text'] = prompts(self.cfg)['control_held']
                self._diagnostic({'event':'safety_control_held','reason':'fresh_typed_voice_path_required'})
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
            published = self.session.should_publish(doc) and not doc.get('_voice', {}).get('readonly_query')
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

    def _capture_after_wake(self, stream, recorder, generation):
        def paused():
            return (self.stop_event.is_set() or generation != self.generation or self.speaking.is_set()
                    or self.tts.lock.locked() or self.place_activity.is_set() or self.safety_activity.is_set())
        self._diagnostic({'event': 'capture_input_prepared', 'last_input_monotonic': getattr(stream, 'last_frame_monotonic', None)})
        cue = getattr(self, 'cue', None)
        if getattr(self, '_cue_initialization_failed', False):
            raise RuntimeError('CUE_INITIALIZATION_FAILED')
        capture_boundary = None
        if cue is not None:
            with self.submit_lock:
                if generation != self.generation or self.stop_event.is_set():
                    raise InterruptedError('CUE_CANCELED')
                self.cue_cancel.clear()
                self.cue_active.set()
            try:
                stamp, timing = cue.play(cancel=self.cue_cancel, on_start=lambda value:
                    self._diagnostic({'event': 'wake_cue_started', 'timing': value}))
                self._diagnostic({'event': 'wake_cue_finished', 'timing': timing, 'source_basis': 'local_cue_not_acceptance'})
                capture_boundary = timing['cue_audible_ended_monotonic']
                if self.stop_event.wait(self.cfg['voice_flow']['cue_guard_sec']) or generation != self.generation:
                    raise InterruptedError('CUE_CANCELED')
            except Exception as exc:
                self._diagnostic({'event':'wake_cue_failed','reason':'playback_failed','error_type':type(exc).__name__})
                raise
            finally:
                self.cue_active.clear()
        else:
            self._diagnostic({'event':'wake_cue_disabled','reason':'configured_off'})
        if paused():
            raise InterruptedError('CAPTURE_CANCELED')
        prepared = stream.begin_capture(capture_boundary) if hasattr(stream, 'begin_capture') else stream.discard()
        self._diagnostic({'event': 'capture_ready', 'captured_after_monotonic': prepared,
                          'recording_mode': self.cfg['recording_mode']})
        self._diagnostic({'event': 'record_started', 'duration': self.cfg.get('record_duration_sec')})
        if self.cfg['recording_mode'] == 'fixed':
            return recorder._fixed_shared(stream, self.stop_event, paused, prepared_at=prepared)
        return recorder.record(stream, self.stop_event, paused, prepared_at=prepared)

    def _listen(self):
        try:
            self.shared_input.start()
            self.stop_listener = threading.Thread(target=self._stop_listen, daemon=True)
            self.stop_listener.start()
            wake = WakeAudio(self.cfg, shared_input=self.shared_input)
            recorder = Recorder(self.cfg, clock=self.place_clock, shared_input=self.shared_input)
            while not self.stop_event.is_set():
                if self._voice_input_busy():
                    self.stop_event.wait(.08)
                    continue
                self.local_context.request_id = request_id = uuid.uuid4().hex
                self._diagnostic({'event': 'wake_waiting', 'input_device': self.cfg['input_device']})
                record_generation = self.generation
                try:
                    with self.audio_lock, wake.stream() as stream:
                        woke = wake.wait(stream, self.stop_event, self._voice_input_busy)
                        if not woke:
                            continue
                        if self._voice_input_busy():
                            continue
                        record_generation = self.generation
                        with self.submit_lock:
                            policy = self.safety_exchange.policy
                            record_work = policy.work if policy and policy.current_state_confirmed else None
                        self._diagnostic({'event': 'wake_detected', 'score': wake.last_score})
                        recording = self._capture_after_wake(stream, recorder, record_generation)
                    self._diagnostic({'event': 'record_finished',
                        'recording_started_monotonic': recording.recording_started_monotonic,
                        'recording_ended_monotonic': recording.recording_ended_monotonic,
                        'speech_ended_monotonic': recording.ended_monotonic, 'recording_mode': recording.recording_mode})
                except (TimeoutError, InterruptedError, RuntimeError) as exc:
                    code = str(exc)
                    reason = code if code in ('NO_SPEECH','RECORD_LIMIT','AUDIO_OVERFLOW','입력 종료','녹음 중단','CUE_CANCELED','CAPTURE_CANCELED') else type(exc).__name__
                    self._diagnostic({'event': 'recording_held', 'reason': reason})
                    # 일시 overflow는 손상 녹음만 폐기. 사용자 재질문·clarify는 만들지 않음.
                    if not isinstance(exc, InterruptedError) and code != 'AUDIO_OVERFLOW':
                        self._submit(('record_error', reason), generation=record_generation, request_id=request_id)
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

    def _current_speech_run(self):
        """Current C status correlation, not provenance for a text-only action call."""
        if not self._request_run_connected() or self.cfg['evaluation_mode']:
            return None
        doc = self._current_runner_status()
        pending, run = self.request_run.pending, self.request_run.run_id
        if (doc is None or doc['phase'] != 'running' or (doc.get('halt') or {}).get('locked') is True
                or pending is None or run is None or self.request_run.finished):
            return None
        decision = doc.get('last_intent') or {}
        token = (pending['request_id'], run, getattr(self, 'request_source_boot', None), self.generation)
        if (getattr(self, 'request_speech_current', None) == (token, doc['task_id'])
                and not (decision.get('decision') == 'run' and decision.get('run_id') != run)):
            return token
        if (decision.get('decision') != 'run' or decision.get('run_id') != run
                or decision.get('request_id') != pending['request_id']
                or decision.get('intent') != pending['intent']
                or pending['intent'] == 'find_item' and decision.get('targets') != pending.get('targets')):
            return None
        return token

    def _goal(self, request):
        if self.stop_event.is_set() or self.cfg.get('request_run_enabled') and self.cfg['evaluation_mode']:
            return GoalResponse.REJECT
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
            self.goal_first_speech = False
            self.goal_cause_speech = None
            self.goal_request_boot = getattr(self, 'request_source_boot', None)
            self.goal_generation = self.generation
            if self.cfg.get('request_run_enabled', False):
                pending, run = self.request_run.pending, self.request_run.run_id
                first = pending is not None and params['text'] == pending.get('accept_text')
                token = (pending['request_id'], run, self.goal_request_boot, self.generation) if pending else None
                if (pending is None or run is None or self.request_run.finished
                        or first and (pending['request_id'], run) in self.request_speech_used
                        or not first and (getattr(self, 'request_speech_completed', None) != token
                                          or self._current_speech_run() != token)):
                    self.goal_lock.release()
                    return GoalResponse.REJECT
                self.goal_request_run = (pending['request_id'], run, params['text'])
                self.goal_first_speech = first
                status = self._current_runner_status()
                if (not first and status is not None
                        and params['text'] in self.notice_policy.failure_texts):
                    self.goal_cause_speech = (token, status['task_id'], params['text'])
                if first:
                    self.request_speech_used.add((pending['request_id'], run))
        self.goal_warning_epoch = getattr(self, 'warning_epoch', 0)
        return GoalResponse.ACCEPT

    def _speak(self, goal):
        result = Skill.Result()
        cancel = threading.Event()
        done = threading.Event()
        epoch = getattr(self, 'goal_warning_epoch', getattr(self, 'warning_epoch', 0))
        request_identity = getattr(self, 'goal_request_run', None)
        first_speech = getattr(self, 'goal_first_speech', False)
        token = ((request_identity[0], request_identity[1], getattr(self, 'goal_request_boot', None),
                  getattr(self, 'goal_generation', self.generation)) if request_identity else None)
        def warning_changed():
            if request_identity is not None:
                with self.submit_lock:
                    pending = self.request_run.pending
                    if (pending is None or (pending['request_id'], self.request_run.run_id) != request_identity[:2]
                            or self.request_run.finished or token[2] != getattr(self, 'request_source_boot', None)
                            or token[3] != self.generation or self.cfg['evaluation_mode']
                            or first_speech and pending.get('accept_text') != request_identity[2]
                            or not first_speech and (self._current_speech_run() != token
                                or getattr(self, 'request_speech_completed', None) != token)):
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
            with self.submit_lock:
                if warning_changed():
                    raise InterruptedError('TTS_CANCELED')
                if request_identity is not None and first_speech:
                    self.request_speech_completed = token  # Only actual successful first playback.
                    status = self._current_runner_status()
                    if status is not None and self._current_speech_run() == token:
                        self.request_speech_current = (token, status['task_id'])
                evidence = getattr(self, 'goal_cause_speech', None)
                if evidence is not None and self._current_speech_run() == evidence[0]:
                    self.cause_speech = evidence  # Same verified run + actual cause playback only.
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
        if getattr(self, 'cue_cancel', None) is not None:
            self.cue_cancel.set()
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
        if getattr(self,'stop_processor',None):
            self.stop_processor.join(timeout=1)
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
