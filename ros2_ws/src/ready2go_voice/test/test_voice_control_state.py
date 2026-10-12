"""상태·정지 동시성·원음/출력 보존 핵심 모의. 장치·SDK·ROS·물리 완료는 호출하지 않습니다."""
from contextlib import contextmanager
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import queue
import threading
from types import SimpleNamespace
import wave
import pytest
from test_voice_ux_node import node_class,node
from test_voice_launch_stop_input import trial
from test_stop_audio import microphone
from test_safety_exchange import WORK,SAFE,STT,stopped,request,audio
from test_flow import dummy_class
from ready2go_voice.core.recovery_confirmation import safety_utterance,TaskEndCandidate
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.core.diagnostics import DiagnosticFile


@pytest.mark.parametrize('text,kind',[('중단','stop'),('중단해','stop'),('복구','recover'),('복구해','recover'),('이어서해.','resume')])
def test_exact_standalone_control_and_existing_spacing(text,kind):
    assert safety_utterance(text)==kind


@pytest.mark.parametrize('text',['중단하지 마','복구하지 마','"중단"','복구라고 말했어','재개하지마','그사람이 중단하래'])
def test_negative_quote_third_party_do_not_become_control(text):
    assert safety_utterance(text) is None


def test_python_ros_native_and_three_stt_routes_saved_once_and_redacted(trial,node,node_class,tmp_path):
    logfile=tmp_path/'console.log';secret='sk-proj-'+'B'*40
    node.cfg.update(diagnostic_detail=True,diagnostic_file=str(tmp_path/'diagnostic.jsonl'))
    writer=node.diagnostic_file=DiagnosticFile(node.cfg,lambda text:None)
    node.get_logger=lambda:SimpleNamespace(info=lambda text:os.write(2,(text+'\n').encode()))
    with logfile.open('w') as output,trial.console_capture(output):
        print('python marker')
        os.write(1,('ROS native marker '+secret+'\n').encode())
        for event in ('stt_result','stop_stt_result','safety_stt_result'):
            node_class._diagnostic(node,{'event':event,'text':'지우개 '+secret})
    writer.close()
    text=logfile.read_text()
    assert text.count('python marker')==text.count('ROS native marker')==1
    assert text.count('STT 결과:')==3 and secret not in text
    raw=(tmp_path/'diagnostic.jsonl').read_text();assert secret not in raw
    assert {json.loads(line)['event'] for line in raw.splitlines()}=={'stt_result','stop_stt_result','safety_stt_result'}


def test_second_capture_queued_while_stop_sdk_waits_and_current_stop_once(node,microphone):
    shared,clock,feed,_=microphone;node.cfg['silence_sec']=.2
    node.now=clock;node.place_clock=lambda:clock[0];node.session.clock=lambda:clock[0]
    node.shared_input=shared;node.busy.set();entered=threading.Event();release=threading.Event()
    queued=threading.Event();second_ready=threading.Event();count=[0];calls=[]
    oldstream=shared.stream
    @contextmanager
    def stream():
        with oldstream() as reader:
            old=reader.discard
            def discard():
                stamp=old();count[0]+=1
                if count[0]>=2:second_ready.set()
                return stamp
            reader.discard=discard
            yield reader
    shared.stream=stream
    class STT:
        supports_request_boundary=True
        def transcribe(self,path,timeout,*,before_request):
            assert before_request(clock[0]);calls.append(1)
            if len(calls)==1:
                entered.set();assert release.wait(2);return '지우개 가져다줘'
            return '멈춰'
    node.session.stt=STT();queue_orig=node._queue_stop_capture
    def submit(*a):
        value=queue_orig(*a)
        if entered.is_set() and not release.is_set():queued.set()
        return value
    node._queue_stop_capture=submit
    published=node._publish;node._publish=lambda doc:(published(doc),node.stop_event.set())
    worker=threading.Thread(target=node._stop_listen);worker.start()
    try:
        # 첫 소비자의 준비를 기다립니다.
        for _ in range(100):
            if count[0]:break
            node.stop_event.wait(.005)
        assert count[0]
        feed(at=100.4);feed(0,at=100.8)
        assert entered.wait(1) and second_ready.wait(1)
        feed(at=101.2);feed(0,at=101.6)
        assert queued.wait(1) and node.stop_captures.qsize()==1 and len(calls)==1
        release.set();worker.join(1)
        assert not worker.is_alive() and len(calls)==2
        assert [doc['intent'] for doc in node.published]==['cancel'] and node.generation==1
    finally:
        release.set();node.stop_event.set();shared.close();worker.join(1)
        if getattr(node,'stop_processor',None):node.stop_processor.join(1)


def test_pending_capture_is_bounded_newest_and_old_generation_cannot_publish(node):
    node.stop_captures=queue.Queue(maxsize=1);first=audio();second=replace(first,recording_started_monotonic=7.)
    assert node._queue_stop_capture(first,0,()) and node._queue_stop_capture(second,0,())
    assert node.stop_captures.qsize()==1 and node.stop_captures.get_nowait()[0] is second
    node.stop_captures.task_done();node.generation=1
    assert not node._queue_stop_capture(first,0,()) and not node.published


def test_sdk_result_after_new_generation_is_discarded(node):
    node.now[0]=6.
    class STT:
        supports_request_boundary=True
        def transcribe(self,path,timeout,*,before_request):
            assert before_request(6.);node.generation+=1;return '중단'
    node.session.stt=STT()
    assert node.session.stop_audio(audio(),paused=lambda:node.generation!=0) is None and not node.published


def test_termination_acceptance_then_idle_fixture_allows_new_eraser_request(node):
    node.cfg['evaluation_mode']=False;node.safety_exchange=ex=stopped(node.cfg);node.now[0]=6.
    node.observe('halted');sent=[];node.session.stt=STT('종료해',node.now)
    def sender(kind,value):
        sent.append((kind,value))
        if kind=='register_independent':
            node.safety_independent_registered(value,WORK,2,valid_state=True,evidence=SAFE)
    node.bind_safety_sender(sender)
    node._safety_recording(audio(),WORK)  # 실제 입력 경로의 새 cancel/SDK/등록 gate를 통과합니다.
    end=sent[-1][1]
    assert isinstance(end,TaskEndCandidate) and node.pending_task_end is not None and ex.policy.work is None
    assert not node.safety_task_end_accepted(TaskEndCandidate(WORK),valid_state=True)
    bridge=dummy_class().__new__(dummy_class())
    bridge.voice=node;bridge.work=WORK;bridge.run=WORK.task;bridge.accepted_payload={};bridge.first_action=None
    bridge.String=lambda **kw:SimpleNamespace(**kw);bridge.log=lambda *a,**kw:None
    bridge.safety_event('candidate',end)
    assert node.pending_task_end is None and node.notice_policy.phase=='idle' and bridge.work is None
    assert not node.safety_task_end_accepted(end,valid_state=True)  # 수락도 일회
    doc=node.session.text('지우개 가져다줘',node.generation);node.deliver(doc)
    assert node.published[-1]['intent']=='find_item' and node.published[-1]['targets']==['eraser']


def test_safety_no_speech_saves_original_opt_in_wav_without_trim(cfg,tmp_path):
    cfg['voice_flow'].update(capture_save_wav=True,capture_dir=str(tmp_path),capture_trim=True)
    ex=stopped(cfg);target=ex.begin_independent(now=5.,unique_target=True);record=replace(audio(),recording_mode='fixed')
    events=[];session=VoiceSession(None,cfg,SimpleNamespace(supports_request_boundary=True),clock=lambda:6.,
        progress=lambda **e:events.append(e),speech_gate=SimpleNamespace(check=lambda *a,**kw:False))
    assert session.safety_audio(ex,target,record) is None
    assert events[-1]['reason']=='NO_SPEECH' and events[-1]['stage']=='speech_check'
    files=list(tmp_path.glob('safety_*.wav'));assert len(files)==1
    with wave.open(str(files[0])) as wav:assert wav.readframes(wav.getnframes())==record.pcm
    assert not any(e['event']=='capture_trimmed' for e in events)


@pytest.mark.parametrize('closing',[False,True])
def test_executor_runtime_failure_vs_expected_shutdown(closing):
    cls=dummy_class();bridge=cls.__new__(cls);events=[]
    bridge.closing=closing;bridge.active=True;bridge.first_action=None;bridge.log=lambda *a,**kw:events.append((a,kw))
    voice=SimpleNamespace(stop_event=threading.Event(),submit_lock=threading.RLock())
    class RCLError(RuntimeError):pass
    def fail():raise RCLError('context invalid')
    cls.__init__.__globals__['spin_live'](SimpleNamespace(spin=fail),voice,bridge)
    assert len(events)==1
    assert bool(getattr(bridge,'executor_failed',False)) is (not closing)
    assert voice.stop_event.is_set() is (not closing)
