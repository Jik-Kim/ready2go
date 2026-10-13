#!/usr/bin/env python3
"""E P2 로컬 준비 전용. 실제 녹음/API/TTS 및 C/B 증거를 만들지 않습니다."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import threading
import select
import time
import uuid
from urllib.parse import urlsplit
import sys

import yaml

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[2]
REMAPS = {
    '/voice/intent': '/e_p2_dummy/intent',
    '/voice/text_override': '/e_p2_dummy/text_override',
    '/runner/status': '/e_p2_dummy/status',
    '/voice/speak': '/e_p2_dummy/speak',
}


def local_config():
    cfg = yaml.safe_load((PACKAGE / 'params/voice.yaml').read_text())
    # 임시 harness 설정만 변경합니다. 제품 YAML/노드 게이트는 보존합니다.
    cfg.update(audio_enabled=False, evaluation_mode=True, diagnostic_detail=False,
               request_run_enabled=False, p2_goal_enabled=False, tts_engine='espeak',
               ontology_file=str(ROOT / 'knowledge/robot_ontology.jsonld'),
               intent_schema_file=str(ROOT / 'contracts/intent.schema.json'))
    return cfg


class DisabledSTT:
    supports_request_boundary = True

    def transcribe(self, *args, **kwargs):
        raise RuntimeError('LOCAL_PREPARATION_NO_STT')


class NoPlaybackTTS:
    def __init__(self):
        self.lock = threading.Lock()

    def speak(self, text, *, on_start, cancel=None, **kwargs):
        with self.lock:
            if cancel is not None and cancel.is_set():
                raise InterruptedError('LOCAL_DUMMY_CANCELED')
            stamp = dict(tts_mock=True, tts_start_basis='mock',
                         tts_started_monotonic=time.monotonic(),
                         tts_started_unix=time.time())
            print(json.dumps({'local_dummy_tts': text, 'tts_mock': True}, ensure_ascii=False), flush=True)
            on_start(stamp)
            return stamp


def disabled_llm(*args, **kwargs):
    raise RuntimeError('LOCAL_PREPARATION_NO_LLM')


def destination_hosts(cfg):
    """SDK 기본/현재 환경 목적지만 확인합니다. 자격·URL 전체/요청은 출력하지 않습니다."""
    from openai import OpenAI
    from langchain_openai import ChatOpenAI
    with OpenAI(api_key='local-preparation-placeholder', max_retries=0) as sdk:
        stt_host = urlsplit(str(sdk.base_url)).hostname
    llm = ChatOpenAI(api_key='local-preparation-placeholder', model=cfg['llm_model'], max_retries=0)
    try:
        llm_host = urlsplit(str(llm.root_client.base_url)).hostname
    finally:
        llm.root_client.close()
    return stt_host, llm_host


def create_live_voice(config_file, *, transmission_and_playback_approved=False,
                      approved_destination_host=None):
    """승인 후 사용할 실제 adapter factory. 현재 CLI에서는 호출하지 않습니다.

    호출자는 격리 ROS 초기화/실행기를 먼저 준비해야 합니다. 이 bool은 사용자
    승인 증거가 아니며 승인된 실행 담당자가 경계에서 전달하는 값입니다.
    """
    if transmission_and_playback_approved is not True or approved_destination_host is None:
        raise PermissionError('실녹음·OpenAI 전송·재생 실행 승인 대기')
    from dotenv import load_dotenv
    from rclpy.parameter import Parameter
    from ready2go_voice.nodes.voice_node import VoiceNode
    load_dotenv(ROOT / 'secrets/voice.env', override=False)
    cfg = yaml.safe_load(Path(config_file).read_text())
    if destination_hosts(cfg) != (approved_destination_host, approved_destination_host):
        raise PermissionError('실행 환경의 STT/LLM 목적지가 승인 대상과 다릅니다')
    if cfg.get('audio_enabled') is not True or cfg.get('tts_engine') != 'melotts':
        raise ValueError('기존 실마이크/Melo local config가 필요합니다')
    # 주입 장치 없이 기존 Whisper·LLM·SharedInput·Melo를 그대로 사용합니다.
    voice = VoiceNode.__new__(VoiceNode)
    started = time.monotonic()
    try:
        VoiceNode.__init__(voice, parameter_overrides=[Parameter('config_file', value=str(config_file)),
            Parameter('evaluation_mode', value=False), Parameter('p2_goal_enabled', value=True),
            Parameter('request_run_enabled', value=True),
            Parameter('place_test_input_topic', value='/e_p2_dummy/place_input')])
        return voice
    except BaseException:
        tts = getattr(voice, 'tts', None)
        state = getattr(tts, 'runtime', None) or {}
        print(json.dumps(dict(event='live_constructor_failed',
            prepare_error=state.get('error'), elapsed_sec=round(time.monotonic()-started, 3))), flush=True)
        if tts is not None:
            tts.close()
        try:
            voice.destroy_node()
        except Exception as exc:
            print(json.dumps(dict(event='partial_node_cleanup_error', error_type=type(exc).__name__)), flush=True)
        raise


class LiveDummyBridge:
    """명시 모의 C 생산자. 실물·C/B 증거/DB/모션을 생성하지 않습니다.

    live factory와 마찬가지로 현재 로컬 준비 CLI에서는 생성하지 않습니다.
    executor에 peer를 추가하고 기존 REMAPS로 두 노드를 초기화해야 합니다.
    """
    def __init__(self, voice, *, auto_complete=None):
        from rclpy.node import Node
        from rclpy.action import ActionClient
        from std_msgs.msg import String
        from ready2go_interfaces.action import Skill
        self.voice, self.String, self.Skill = voice, String, Skill
        self.peer = Node('e_p2_dummy_peer')
        self.active = True
        self.auto_complete = voice.cfg['voice_flow']['dummy_auto_complete'] if auto_complete is None else auto_complete
        self.run = None
        self.accepted_payload = None
        self.first_action = None
        self.work = self.evidence = None
        self.revision = 0
        self.feedback = None
        self.client = ActionClient(self.peer, Skill, REMAPS['/voice/speak'])
        self.subscription = self.peer.create_subscription(String, REMAPS['/voice/intent'], self.intent, 10)
        voice.bind_request_source(lambda: self.active and not voice.stop_event.is_set(), boot='dummy')
        voice.bind_safety_sender(self.safety_event)

    @staticmethod
    def log(event, **fields):
        print(json.dumps(dict(dummy_assumption=True, event=event, **fields),
                         ensure_ascii=False), flush=True)

    def status(self, payload, run, *, completed=False):
        # 기존 계약07 칸만 사용하며 status JSON을 인증 증거라고 표현하지 않습니다.
        decision = {k: payload[k] for k in ('intent', 'request_id')}
        decision.update(targets=payload.get('targets'), decision='run', run_id=run)
        doc = dict(phase='idle' if completed else 'running',
            task_id=None if completed else 'dummy', halt_code=None, last_intent=decision,
            last=dict(run_id=run, overall_status='COMPLETED') if completed else None)
        self.voice._runner_status(self.String(data=json.dumps(doc, ensure_ascii=False)))

    def intent(self, message):
        payload = json.loads(message.data)
        kind = payload.get('intent')
        if kind == 'cancel':
            from ready2go_voice.core.recovery_confirmation import StoppedWork, Evidence
            with self.voice.submit_lock:
                run = self.run
                self.log('cancel_received_not_physical_stop')
                if run is not None and self.accepted_payload is not None:
                    revision = self.revision + 1  # 생성자 0에서 시작; 부분 변경 전 검사
                    work = StoppedWork('dummy', uuid.uuid4().hex, run, 'dummy_step')
                    evidence = Evidence(True, False, False, False, True)
                    if self.stopped_fixture(work, revision, evidence) is not True:
                        raise RuntimeError('DUMMY_STOP_FIXTURE_REJECTED')
                    self.first_action = None
                    self.voice._runner_status(self.String(data=json.dumps(dict(
                        phase='halted', task_id='dummy', halt_code='CANCELED', last=None, last_intent=None))))
                    self.log('dummy_stopped_run_preserved_not_bc_evidence', run_id=run)
                else:
                    self.first_action = None
                    self.log('dummy_no_active_run_to_preserve')
        elif kind == 'confirm':
            self.log('tray_answer', answer=payload['answer'])
            if payload['answer'] == 'asked':
                registered = {k: payload[k] for k in ('boot_id', 'run_id', 'step_id', 'question_id', 'attempt')}
                registered['type'] = 'registered'
                self.voice._place_input(self.String(data=json.dumps(registered)))
        elif kind in ('find_item', 'achieve_goal') and self.active:
            with self.voice.submit_lock:
                pending = self.voice.request_run.pending
                if pending is None or pending['request_id'] != payload.get('request_id'):
                    return
                run = self.run = uuid.uuid4().hex
                self.accepted_payload = payload
                generation = self.voice.generation
                self.log('accepted_fixture', run_id=run)
                self.status(payload, run)
                goal = self.Skill.Goal()
                goal.params_json = json.dumps({'text': payload['accept_text']}, ensure_ascii=False)
                def accepted(future):
                    handle = future.result()
                    if handle.accepted:
                        handle.get_result_async().add_done_callback(finished)
                    else:
                        self.log('speak_rejected_no_first_action')
                def finished(future):
                    self.finish_speak(future.result().result, run, generation)
                self.client.send_goal_async(goal).add_done_callback(accepted)

    def finish_speak(self, result, run, generation):
        # 실제 Voice._speak의 DAC/finished/non-mock 검사 결과가 선행합니다.
        with self.voice.submit_lock:
            current = self.voice.request_run
            if (result.success is not True or not self.active or self.run != run
                    or self.voice.generation != generation or current.run_id != run
                    or current.finished or not self.voice._request_run_connected()):
                self.log('speak_failed_or_stale_no_first_action')
                return
            self.log('dummy_first_action_after_real_speak_success', run_id=run)
            self.first_action = (run, generation)
        if self.auto_complete is True:
            self.log('dummy_auto_complete_fixture_not_physical', run_id=run)
            self.complete()  # 같은 현재run/세대/취소 gate를 다시 검사합니다.
        else:
            self.log('dummy_waiting_manual_complete', run_id=run,
                     instruction='수동 완료 대기: 터미널에 complete를 입력해 주세요.')

    def complete(self):
        # 담당자가 stdin complete를 선택해야 끝납니다. 임의 실행 시간은 없습니다.
        with self.voice.submit_lock:
            if getattr(self, 'work', None) is not None:
                self.log('completion_rejected_stopped_run_requires_existing_end_path')
                return False
            if (self.first_action is None or self.first_action != (self.run, self.voice.generation)
                    or not self.active or self.voice.request_run.run_id != self.run
                    or self.voice.request_run.finished or not self.voice._request_run_connected()):
                self.log('completion_rejected_no_current_first_action')
                return False
            self.status(self.accepted_payload, self.run, completed=True)
            self.log('dummy_completed_not_robot_result', run_id=self.run)
            self.first_action = None
            self.run = None
            self.accepted_payload = None
            return True

    def tray_question(self, *, items, destination, final_timeout_sec):
        """담당자가 지정한 fixture 기한/등록만 사용합니다. 새로운 TTL은 없습니다."""
        doc = dict(type='question', boot_id='dummy', run_id=uuid.uuid4().hex,
            step_id='place', items=items, destination=destination,
            observation='not_found', final_timeout_sec=final_timeout_sec)
        self.log('tray_question_fixture', run_id=doc['run_id'])
        self.voice._place_input(self.String(data=json.dumps(doc)))

    def tray_result(self, *, restoration_verified):
        identity = self.voice.place_identity
        if identity is None:
            raise ValueError('현재 트레이 질문이 없습니다')
        doc = dict(type='result', boot_id=identity[0], run_id=identity[1], step_id=identity[2],
            overall_status='COMPLETED' if restoration_verified else 'FAILED',
            delivery_verified=True, restoration_verified=restoration_verified)
        self.log('tray_result_fixture_not_observation')
        self.voice._place_input(self.String(data=json.dumps(doc)))

    def stopped_fixture(self, work, revision, evidence):
        with self.voice.submit_lock:
            if type(revision) is not int or revision <= self.revision:
                return False
            previous = (self.work, self.revision, self.evidence)
            self.work, self.revision, self.evidence = work, revision, evidence
            try:
                accepted = self.voice.safety_stopped(work, revision, valid_state=True, evidence=evidence)
            except Exception:
                self.work, self.revision, self.evidence = previous
                raise
            if accepted is not True:
                self.work, self.revision, self.evidence = previous
                return False
            self.log('typed_stopped_fixture_not_bc_evidence')
            return True

    def recovery_question(self, revision, *, valid_until):
        self.revision = revision
        self.log('typed_offer_fixture_not_bc_recovery')
        return self.voice.safety_offer(self.work, revision, self.evidence,
                                      valid_state=True, valid_until=valid_until)

    def safety_event(self, kind, target):
        with self.voice.submit_lock:
            self.log('typed_safety_fixture', kind=kind)
            if kind == 'register_question':
                self.voice.safety_registered(target, target.work, target.revision, valid_state=True)
            elif kind == 'register_independent':
                self.revision += 1
                self.voice.safety_independent_registered(target, self.work, self.revision,
                                                        valid_state=True, evidence=self.evidence)
            elif kind == 'recover' and self.work is not None:
                from ready2go_voice.core.recovery_confirmation import Evidence
                evidence = Evidence(True, True, True, True, True)
                if not self.stopped_fixture(self.work, self.revision + 1, evidence):
                    raise RuntimeError('DUMMY_RECOVERY_FIXTURE_REJECTED')
                self.log('dummy_recovered_fixture_not_bc_evidence', run_id=self.work.task)
                self.feedback = self.voice.safety_feedback(self.work, 'recover')
            elif kind == 'candidate':
                from ready2go_voice.core.recovery_confirmation import TaskEndCandidate, StoppedWork
                work = target.work if isinstance(target, TaskEndCandidate) else target
                if (not self.active or work != self.work or self.run != self.work.task
                        or self.accepted_payload is None):
                    self.log('dummy_control_rejected_no_current_work')
                    if self.work is not None:
                        self.voice.safety_feedback(self.work, 'failed', reason='dummy_work_unconfirmed')
                    return
                if isinstance(target, TaskEndCandidate):
                    self.feedback = self.voice.safety_feedback(work, 'end', candidate=target)
                elif isinstance(target, StoppedWork):
                    self.feedback = self.voice.safety_feedback(work, 'resume', candidate=target)
                else:
                    self.log('dummy_unsupported_candidate_not_motion_permission')
            elif kind == 'feedback_delivered':
                if (target is not self.feedback or not self.active or self.work != target['work']
                        or self.voice.generation != target['generation']):
                    self.log('dummy_feedback_rejected_not_current')
                    return
                if target['kind'] == 'end':
                    if not self.voice.safety_task_end_accepted(target['candidate'], valid_state=True):
                        return
                    self.run = self.work = self.accepted_payload = self.first_action = None
                    self.voice._runner_status(self.String(data=json.dumps(dict(
                        phase='idle',task_id=None,halt_code=None,last=None,last_intent=None))))
                    self.log('dummy_task_end_accepted_idle_fixture_not_physical_result')
                elif target['kind'] == 'resume':
                    # 기존 작업 인자는 보존하되 새 수락의 E 로컬 상관 ID만 만듭니다.
                    payload = dict(self.accepted_payload, request_id=uuid.uuid4().hex)
                    policy = self.voice.safety_exchange.policy
                    if (self.run != self.work.task or not self.voice._request_run_connected()
                            or policy is None or policy.work != self.work
                            or policy._recovery_mode(self.work, self.voice.safety_exchange.evidence) != 'resume'
                            or not self.voice.request_run.register(payload)):
                        self.log('dummy_resume_rejected_current_evidence_or_correlation')
                        return
                    if not policy.resumed(self.work, valid_state=True, evidence=self.voice.safety_exchange.evidence):
                        self.voice.request_run.invalidate()
                        return
                    self.accepted_payload = payload
                    self.work = None
                    self.status(payload, self.run)
                    self.first_action = (self.run, self.voice.generation)
                    self.log('dummy_resume_running_fixture_not_motion_permission', run_id=self.run)
                self.feedback = None
            # 복구/재개/종료는 명시 모의 증빙/후보뿐이며 실제 해제·모션을 실행하지 않습니다.


    def close(self):
        self.active = False
        self.run = None
        self.client.destroy()
        self.peer.destroy_node()


def spin_live(executor, voice, bridge):
    """콜백 예외는 더미 시험 불능으로 표시하고 정상 요청 처리를 중단합니다."""
    try:
        executor.spin()
        if not voice.stop_event.is_set():
            raise RuntimeError('DUMMY_EXECUTOR_STOPPED')
    except Exception as exc:
        with voice.submit_lock:
            if voice.stop_event.is_set() or getattr(bridge,'closing',False):
                bridge.log('dummy_executor_shutdown_interrupted',error_type=type(exc).__name__)
                return
            bridge.executor_failed = True
            bridge.active = False
            bridge.first_action = None
            voice.stop_event.set()
            bridge.log('dummy_test_unavailable_executor_failed', error_type=type(exc).__name__)


def serve_live(config_file, *, auto_complete=None):
    """전송·재생 승인 후의 명시 실행 단계. 사람의 발화를 코드로 대체하지 않습니다."""
    import sys  # stdin 선택의 함수 의존성; 기존 전역 미커밋 import와 독립입니다.
    os.environ.update(ROS_DOMAIN_ID='166', ROS_LOCALHOST_ONLY='1',
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from ready2go_voice.nodes.voice_node import VoiceNode
    from ready2go_voice.core.recovery_confirmation import StoppedWork, Evidence
    import inspect
    if Path(inspect.getfile(VoiceNode)).resolve() != PACKAGE / 'ready2go_voice/nodes/voice_node.py':
        raise RuntimeError('현재 작업 소스 overlay를 확인하십시오')
    with tempfile.TemporaryDirectory(prefix='e-p2-live-dummy-') as folder:
        os.environ['ROS_LOG_DIR'] = str(Path(folder) / 'ros_logs')
        args = ['--ros-args']
        for original, local in REMAPS.items():
            args.extend(['-r', f'{original}:={local}'])
        rclpy.init(args=args)
        voice = bridge = thread = None
        executor = MultiThreadedExecutor(num_threads=4)
        try:
            voice = create_live_voice(config_file, transmission_and_playback_approved=True,
                                      approved_destination_host='api.openai.com')
            bridge = LiveDummyBridge(voice, auto_complete=auto_complete)
            executor.add_node(voice)
            executor.add_node(bridge.peer)
            thread = threading.Thread(target=spin_live, args=(executor, voice, bridge), daemon=True)
            thread.start()
            bridge.log('live_factory_started_not_recording_proof', pid=os.getpid(),
                       config=str(config_file), domain=166, approved_host='api.openai.com')
            print('모델/입력 ready 진단을 확인한 뒤 시험 발화만 말씀하십시오. '
                  'stdin: complete / tray <기한초> / tray_complete / tray_partial / '
                  'stopped / question <기한초> / independent / exit', flush=True)
            while not voice.stop_event.is_set():
                if not select.select([sys.stdin], [], [], .1)[0]:
                    continue
                try:
                    parts = input().split()
                except EOFError:
                    break
                if not parts:
                    continue
                try:
                    command = parts[0]
                    allowed = {'exit','complete','tray','tray_complete','tray_partial','stopped','question','independent'}
                    if command not in allowed:
                        bridge.log('stdin_command_rejected', command='unknown')
                        continue
                    bridge.log('stdin_command_received', command=command)
                    if not bridge.active or voice.stop_event.is_set():
                        bridge.log('stdin_command_rejected', command=command, reason='dummy_test_unavailable')
                        break
                    if command == 'exit':
                        bridge.log('dummy_shutdown_requested',reason='stdin_exit')
                        break
                    elif command == 'complete':
                        ok = bridge.complete()
                        bridge.log('stdin_command_accepted' if ok else 'stdin_command_rejected', command=command)
                    elif command == 'tray':
                        bridge.tray_question(items=['toy_hammer'], destination='handover_zone',
                                             final_timeout_sec=float(parts[1]))
                    elif command in ('tray_complete', 'tray_partial'):
                        bridge.tray_result(restoration_verified=command == 'tray_complete')
                    elif command == 'stopped':
                        bridge.stopped_fixture(StoppedWork('dummy', uuid.uuid4().hex,
                            uuid.uuid4().hex, 'dummy_step'), bridge.revision + 1, Evidence(True, True, True, True, True))
                    elif command == 'question':
                        bridge.recovery_question(bridge.revision + 1,
                            valid_until=time.monotonic() + float(parts[1]))
                    elif command == 'independent':
                        bridge.log('independent_capture_fixture')
                        voice.safety_independent(unique_target=True)
                    else:
                        bridge.log('unknown_stdin_command_no_voice_submission')
                except (ValueError, TypeError, IndexError) as exc:
                    bridge.log('stdin_command_rejected', command=command if command in allowed else 'unknown', error_type=type(exc).__name__)
        except KeyboardInterrupt:
            if bridge is not None:
                bridge.log('dummy_shutdown_requested',reason='keyboard_interrupt')
        finally:
            cleanup_errors = []
            if bridge is not None:
                bridge.closing = True
                bridge.active = False
            def cleanup(name, operation):
                try:
                    operation()
                except Exception as exc:
                    context_ok = getattr(rclpy,'ok',lambda:True)()
                    info = dict(event='dummy_cleanup_error',operation=name,error_type=type(exc).__name__,context_ok=context_ok)
                    print(json.dumps(info),flush=True)
                    if context_ok or type(exc).__name__ != 'RCLError':
                        cleanup_errors.append(name)
            if voice is not None:
                cleanup('voice_close',voice.close)
            cleanup('executor_shutdown',executor.shutdown)
            if thread is not None:
                cleanup('executor_join',lambda:thread.join(timeout=1))
            if bridge is not None:
                cleanup('bridge_close',bridge.close)
            if voice is not None:
                cleanup('voice_destroy',voice.destroy_node)
            if getattr(rclpy,'ok',lambda:True)():
                cleanup('context_shutdown',getattr(rclpy,'try_shutdown',rclpy.shutdown))
            else:
                print(json.dumps(dict(event='dummy_context_already_shutdown')),flush=True)
        if cleanup_errors or bridge is not None and getattr(bridge,'executor_failed',False):
            raise RuntimeError('DUMMY_EXECUTION_OR_CLEANUP_FAILED')


def serve(cfg, *, smoke=False):
    # 기존 격리 ROS 시험 도메인. 실제 Runner와 같은 도메인에서 실행하지 않습니다.
    os.environ['ROS_DOMAIN_ID'] = '166'
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.parameter import Parameter
    from ready2go_voice.nodes.voice_node import VoiceNode

    expected = PACKAGE / 'ready2go_voice/nodes/voice_node.py'
    import inspect
    if Path(inspect.getfile(VoiceNode)).resolve() != expected:
        raise RuntimeError('현재 작업 소스 overlay를 확인하십시오')
    class LocalVoice(VoiceNode):
        def _work(self):
            self.parser.llm = disabled_llm
            super()._work()
    with tempfile.TemporaryDirectory(prefix='e-p2-local-dummy-') as folder:
        path = Path(folder) / 'voice.yaml'
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True))
        os.environ['ROS_LOG_DIR'] = str(Path(folder) / 'ros_logs')
        args = ['--ros-args']
        for original, local in REMAPS.items():
            args.extend(['-r', f'{original}:={local}'])
        rclpy.init(args=args)
        voice = None
        executor = MultiThreadedExecutor(num_threads=4)
        try:
            voice = LocalVoice(tts=NoPlaybackTTS(), stt=DisabledSTT(),
                parameter_overrides=[Parameter('config_file', value=str(path)),
                                     Parameter('evaluation_mode', value=True)])
            voice.parser.llm = disabled_llm
            executor.add_node(voice)
            assert voice.listener is None and voice.shared_input is None
            assert voice.request_source_check is None and voice.safety_sender is None
            assert voice.place_topic == '' and voice.cfg['evaluation_mode'] is True
            print(json.dumps({'local_dummy_ready': True, 'domain': 166,
                'source': str(expected), 'topics': REMAPS,
                'microphone': False, 'api': False, 'playback': False,
                'c_source': False, 'evaluation_mode': True}, ensure_ascii=False), flush=True)
            if smoke:
                executor.spin_once(timeout_sec=0)
            else:
                executor.spin()
        except KeyboardInterrupt:
            pass
        finally:
            if voice is not None:
                voice.close()
            executor.shutdown()
            if voice is not None:
                voice.destroy_node()
            rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--serve-local', action='store_true', help='녹음/API/재생 없는 격리 ROS 노드 유지')
    mode.add_argument('--smoke-local', action='store_true', help='같은 격리 노드 생성·종료 확인')
    mode.add_argument('--serve-live', action='store_true', help='승인된 시험 WAV/텍스트를 api.openai.com으로 전송하고 실제 Melo 재생')
    parser.add_argument('--auto-complete', action='store_true', default=None, help='현재 run의 실제 수락TTS/첫동작 뒤에만 더미 자동완료')
    parser.add_argument('--config-file', type=Path, default=ROOT / 'logs/voice_eval/voice.local.yaml')
    args = parser.parse_args()
    cfg = local_config()
    if args.serve_live:
        serve_live(args.config_file.resolve(), auto_complete=args.auto_complete)
    elif args.serve_local or args.smoke_local:
        serve(cfg, smoke=args.smoke_local)
    else:
        print(json.dumps({'preparation_only': True, 'microphone': False,
            'api': False, 'playback': False, 'evaluation_mode': True,
            'p2_goal_enabled': False, 'request_run_enabled': False,
            'ontology_exists': Path(cfg['ontology_file']).is_file(),
            'schema_exists': Path(cfg['intent_schema_file']).is_file()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
