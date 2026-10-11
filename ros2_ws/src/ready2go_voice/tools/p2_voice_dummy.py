#!/usr/bin/env python3
"""E P2 로컬 준비 전용. 실제 녹음/API/TTS 및 C/B 증거를 만들지 않습니다."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid
from urllib.parse import urlsplit

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
    def __init__(self, voice):
        from rclpy.node import Node
        from rclpy.action import ActionClient
        from std_msgs.msg import String
        from ready2go_interfaces.action import Skill
        self.voice, self.String, self.Skill = voice, String, Skill
        self.peer = Node('e_p2_dummy_peer')
        self.active = True
        self.run = None
        self.accepted_payload = None
        self.first_action = None
        self.work = self.evidence = None
        self.revision = None
        self.client = ActionClient(self.peer, Skill, REMAPS['/voice/speak'])
        self.subscription = self.peer.create_subscription(String, REMAPS['/voice/intent'], self.intent, 10)
        voice.bind_request_source(lambda: self.active and not voice.stop_event.is_set())
        voice.bind_safety_sender(self.safety_event)

    @staticmethod
    def log(event, **fields):
        print(json.dumps(dict(dummy_assumption=True, event=event, **fields),
                         ensure_ascii=False), flush=True)

    def status(self, payload, run, *, completed=False):
        # 기존 계약07 칸만 사용하며 status JSON을 인증 증거라고 표현하지 않습니다.
        decision = {k: payload[k] for k in ('intent', 'request_id')}
        field = 'goals' if payload['intent'] == 'achieve_goal' else 'targets'
        decision.update({field: payload[field], 'decision': 'run', 'run_id': run})
        doc = dict(phase='idle' if completed else 'running',
            task_id=None if completed else 'dummy', halt_code=None, last_intent=decision,
            last=dict(run_id=run, overall_status='COMPLETED') if completed else None)
        self.voice._runner_status(self.String(data=json.dumps(doc, ensure_ascii=False)))

    def intent(self, message):
        payload = json.loads(message.data)
        kind = payload.get('intent')
        if kind == 'cancel':
            self.run = None
            self.first_action = None
            self.log('cancel_received_not_physical_stop')
            self.voice._runner_status(self.String(data=json.dumps(dict(
                phase='idle', task_id=None, halt_code=None, last=None, last_intent=None))))
            self.log('dummy_idle_after_cancel_not_physical_stop_evidence')
        elif kind == 'confirm':
            self.log('tray_answer', answer=payload['answer'])
            if payload['answer'] == 'asked':
                registered = {k: payload[k] for k in ('boot_id', 'run_id', 'step_id', 'question_id', 'attempt')}
                registered['type'] = 'registered'
                self.voice._place_input(self.String(data=json.dumps(registered)))
        elif kind in ('find_item', 'achieve_goal') and self.active:
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
                result = future.result().result
                # VoiceNode._speak 자체가 real DAC/finished callback을 검사합니다.
                with self.voice.submit_lock:
                    current = self.voice.request_run
                    if (not result.success or not self.active or self.run != run
                            or self.voice.generation != generation or current.run_id != run
                            or current.finished or not self.voice._request_run_connected()):
                        self.log('speak_failed_or_stale_no_first_action')
                        return
                    self.log('dummy_first_action_after_real_speak_success', run_id=run)
                    self.first_action = (run, generation)
            self.client.send_goal_async(goal).add_done_callback(accepted)

    def complete(self):
        # 담당자가 stdin complete를 선택해야 끝납니다. 임의 실행 시간은 없습니다.
        with self.voice.submit_lock:
            if (self.first_action is None or self.first_action != (self.run, self.voice.generation)
                    or not self.active or self.voice.request_run.run_id != self.run
                    or self.voice.request_run.finished or not self.voice._request_run_connected()):
                self.log('completion_rejected_no_current_first_action')
                return
            self.status(self.accepted_payload, self.run, completed=True)
            self.log('dummy_completed_not_robot_result', run_id=self.run)
            self.first_action = None

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
        self.work, self.revision, self.evidence = work, revision, evidence
        self.log('typed_stopped_fixture_not_bc_evidence')
        return self.voice.safety_stopped(work, revision, valid_state=True, evidence=evidence)

    def recovery_question(self, revision, *, valid_until):
        self.revision = revision
        self.log('typed_offer_fixture_not_bc_recovery')
        return self.voice.safety_offer(self.work, revision, self.evidence,
                                      valid_state=True, valid_until=valid_until)

    def safety_event(self, kind, target):
        self.log('typed_safety_fixture', kind=kind)
        if kind == 'register_question':
            self.voice.safety_registered(target, target.work, target.revision, valid_state=True)
        elif kind == 'register_independent':
            self.revision += 1
            self.voice.safety_independent_registered(target, self.work, self.revision,
                                                    valid_state=True, evidence=self.evidence)
        # recover/candidate는 로그만 남기며 실제 해제·재개·물리 완료는 생성하지 않습니다.

    def close(self):
        self.active = False
        self.run = None
        self.client.destroy()
        self.peer.destroy_node()


def serve_live(config_file):
    """전송·재생 승인 후의 명시 실행 단계. 사람의 발화를 코드로 대체하지 않습니다."""
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
            bridge = LiveDummyBridge(voice)
            executor.add_node(voice)
            executor.add_node(bridge.peer)
            thread = threading.Thread(target=executor.spin, daemon=True)
            thread.start()
            bridge.log('live_factory_started_not_recording_proof', pid=os.getpid(),
                       config=str(config_file), domain=166, approved_host='api.openai.com')
            print('모델/입력 ready 진단을 확인한 뒤 시험 발화만 말씀하십시오. '
                  'stdin: complete / tray <기한초> / tray_complete / tray_partial / '
                  'stopped / question <기한초> / independent / exit', flush=True)
            while not voice.stop_event.is_set():
                try:
                    parts = input().split()
                except EOFError:
                    break
                if not parts:
                    continue
                try:
                    command = parts[0]
                    if command == 'exit':
                        break
                    elif command == 'complete':
                        bridge.complete()
                    elif command == 'tray':
                        bridge.tray_question(items=['toy_hammer'], destination='handover_zone',
                                             final_timeout_sec=float(parts[1]))
                    elif command in ('tray_complete', 'tray_partial'):
                        bridge.tray_result(restoration_verified=command == 'tray_complete')
                    elif command == 'stopped':
                        bridge.stopped_fixture(StoppedWork('dummy', uuid.uuid4().hex,
                            uuid.uuid4().hex, 'dummy_step'), 1, Evidence(True, True, True, True, True))
                    elif command == 'question':
                        bridge.recovery_question(bridge.revision + 1,
                            valid_until=time.monotonic() + float(parts[1]))
                    elif command == 'independent':
                        bridge.log('independent_capture_fixture')
                        voice.safety_independent(unique_target=True)
                    else:
                        bridge.log('unknown_stdin_command_no_voice_submission')
                except (ValueError, TypeError, IndexError) as exc:
                    bridge.log('fixture_input_error', error_type=type(exc).__name__)
        except KeyboardInterrupt:
            pass
        finally:
            if bridge is not None:
                bridge.active = False
            if voice is not None:
                voice.close()
            executor.shutdown()
            if thread is not None:
                thread.join(timeout=1)
            if bridge is not None:
                bridge.close()
            if voice is not None:
                voice.destroy_node()
            rclpy.shutdown()


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
    parser.add_argument('--config-file', type=Path, default=ROOT / 'logs/voice_eval/voice.local.yaml')
    args = parser.parse_args()
    cfg = local_config()
    if args.serve_live:
        serve_live(args.config_file.resolve())
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
