"""승인 음성 흐름의 모의 경계. 실제 발화/echo/API/재생·물리 성공 증거가 아닙니다."""
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace
import threading
import wave
import numpy as np
import pytest
import yaml
from ready2go_voice.core.config import load_config
from ready2go_voice.core.flow import settings
from ready2go_voice.core.signal import prepare
from ready2go_voice.adapters.audio import Recording, SharedInput, Recorder
from ready2go_voice.adapters.cue import WakeCue
from test_voice_ux_node import node_class, node, ask


@pytest.mark.parametrize('reply', ['어어 맞아','어 그걸로 갖다줘','가져다줘'])
@pytest.mark.parametrize('mode', ['rule','llm','failure'])
def test_natural_current_reply_is_one_target_once(node, reply, mode):
    q = ask(node)
    calls = []
    class LLM:
        supports_context = True
        def __call__(self, text, timeout, *, context=None):
            calls.append(context)
            if mode == 'failure': raise TimeoutError('mock')
            return {'intent':'find_item','targets':['toy_hammer'],'confidence':.99,
                    'response_text':'장난감 망치 가져오기 요청으로 이해했어요.'}
    node.parser.llm = None if mode == 'rule' else LLM()
    doc = node.session.text(reply, node.generation)
    assert doc['intent'] == 'find_item' and doc['targets'] == ['toy_hammer']
    assert doc['_voice']['question_id'] == q['_voice']['question_id']
    if calls: assert calls == [{'target':'toy_hammer','reply':reply,
        'question_id':q['_voice']['question_id'],'question':'장난감 망치 가져오기 요청이 맞나요?'}]
    node.deliver(doc)
    again = node.session.text(reply, node.generation)
    assert not again['source']['execution_allowed'] and again['targets'] == []


@pytest.mark.parametrize('text', ['사과 가져다줘','어 그걸로 갖다주지 마','어 그걸로 정리해줘',
    '망치랑 지우개 가져다줘','"가져다줘"','그 사람이 가져다줘라고 했어'])
def test_natural_reply_guards_do_not_grant_past_target(node, text):
    ask(node)
    doc = node.session.text(text, node.generation)
    assert not doc['source']['execution_allowed'] and doc['targets'] == []
    assert not doc['_voice'].get('context_answer')


@pytest.mark.parametrize('text',['어어 맞아','어 그걸로 갖다줘','가져다줘'])
@pytest.mark.parametrize('running',[False,True])
def test_targetless_natural_reply_asks_target_or_reports_running(node,text,running):
    if running: node.observe('running')
    doc=node.session.text(text,blocked=running,runner_state='running' if running else None)
    assert doc['intent']=='clarify' and doc['targets']==[] and not doc['source']['execution_allowed']
    node.deliver(doc)
    assert node.texts==[node.cfg['voice_flow']['status_prompts']['running'] if running else node.cfg['clarify_prompts']['missing_item']]
    if running:assert node.session.conversation.pending is None
    else:assert node.session.conversation.pending.target is None


@pytest.mark.parametrize('boundary', ['live','expires_during_tts','blocked','generation','sdk_error','cancel'])
def test_successful_empty_stt_preserves_only_current_p1_question(node, boundary):
    ask(node); q = node.session.conversation.pending
    counts = sum(d['event']=='question_ready' for d in node.diagnostics)
    class STT:
        supports_request_boundary = True
        supports_context_hint = True
        def transcribe(self, path, timeout, *, before_request=None, context_hint=None):
            assert before_request(node.now[0])
            if boundary == 'sdk_error': raise RuntimeError('mock')
            return ''
    node.session.stt = STT()
    node.session.speech_gate = SimpleNamespace(check=lambda *a,**kw:True)
    if boundary == 'cancel': node.request_cancel.set()
    doc = node.session.audio(Recording(b'\0\0'*1600,None,None,recording_mode='fixed'),
        cancel=node.request_cancel, generation=node.generation+(boundary=='generation'), blocked=boundary=='blocked')
    if boundary == 'expires_during_tts': node.now[0] = q.expires
    node.deliver(doc)
    if boundary == 'live':
        assert node.session.conversation.pending is q
        assert q.expires == doc['_voice']['original_question_expires']
    else:
        assert node.session.conversation.pending is None
    assert sum(d['event']=='question_ready' for d in node.diagnostics) == counts
    assert not doc['source']['execution_allowed']


def test_state_notice_keeps_original_find_and_does_not_ask_question(node, node_class):
    node.observe('running')
    doc = node.session.text('망치 가져다줘', blocked=True, runner_state='running')
    assert doc['_voice']['original_interpretation']['intent'] == 'find_item'
    assert doc['intent'] == 'clarify' and not doc['source']['execution_allowed']
    messages=[];node.get_logger=lambda:SimpleNamespace(info=messages.append)
    node_class._diagnostic(node, {'event':'interpretation','intent':doc})
    assert 'find_item' in messages[0] and '실행 보류' in messages[0]
    node.deliver(doc)
    assert node.texts == [node.cfg['voice_flow']['status_prompts']['running']]
    assert not node.session.conversation.pending
    node_class._diagnostic(node, {'event':'intent','intent':doc,'published':True})
    assert '안내/제어' in messages[-1] and '실행 요청 수락 아님' in messages[-1]


def test_state_change_after_interpretation_reads_state_instead_of_new_question(node):
    doc=node.session.text('망치 가져다줘')
    node.observe('running');node.deliver(doc)
    assert node.texts==[node.cfg['voice_flow']['status_prompts']['running']]
    assert not any(d['intent']=='find_item' for d in node.published)
    assert not node.session.conversation.pending


def test_running_does_not_overwrite_stt_quota_error_notice(node):
    node.observe('running')
    class RateLimitError(Exception):
        status_code=429;code='insufficient_quota';type='insufficient_quota'
    class STT:
        def transcribe(self,*a):raise RateLimitError()
    node.session.stt=STT();node.session.speech_gate=SimpleNamespace(check=lambda *a,**k:True)
    doc=node.session.audio(Recording(b'\0\0'*1600,None,None,recording_mode='fixed'),blocked=True)
    node.deliver(doc)
    assert node.texts==[node.cfg['stt_error_prompts']['quota']]


def test_signal_opt_in_save_trim_and_file_failure(cfg,tmp_path):
    cfg['voice_flow'].update(capture_save_wav=True,capture_dir=str(tmp_path/'capture'),capture_trim=True)
    pcm=np.concatenate([np.zeros(16000),np.ones(3200)*2000,np.zeros(16000)]).astype('<i2').tobytes()
    original=Recording(pcm,None,None,recording_mode='fixed',recording_started_monotonic=1.,recording_ended_monotonic=3.)
    events=[]
    sent=prepare(original,cfg,'one',lambda **e:events.append(e))
    assert len(sent.pcm)<len(pcm) and sent.recording_started_monotonic==1. and sent.recording_ended_monotonic==3.
    with wave.open(str(tmp_path/'capture/one.wav')) as wav: assert wav.readframes(wav.getnframes())==pcm
    assert any(e['event']=='capture_signal' and e['peak']==2000 for e in events)
    prepare(original,cfg,'one',lambda **e:events.append(e))  # 기존 증빙 파일을 덮어쓰지 않습니다.
    assert any(e['event']=='capture_save_failed' for e in events)
    cfg['voice_flow'].update(capture_save_wav=False,capture_trim=False)
    assert prepare(original,cfg,'off',lambda **e:None) is original


def test_whisper_hint_evaluated_after_actual_sdk_admission(cfg,tmp_path,monkeypatch):
    from ready2go_voice.adapters.api import WhisperSTT
    openai=pytest.importorskip('openai');calls=[];valid=[True]
    class Client:
        def __init__(self,**kw):
            assert kw['max_retries']==0
            self.audio=SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))
        def create(self,**kw):calls.append(kw['prompt']);return SimpleNamespace(text='응')
        def __enter__(self):return self
        def __exit__(self,*a):pass
    monkeypatch.setattr(openai,'OpenAI',Client)
    path=tmp_path/'speech.wav';path.write_bytes(b'mock')
    stt=WhisperSTT(cfg,['망치'])
    hint=lambda:'현재 망치 질문' if valid[0] else None
    assert stt.transcribe(path,1.,context_hint=hint)=='응'
    def boundary(stamp):valid[0]=False;return True
    assert stt.transcribe(path,1.,before_request=boundary,context_hint=hint)=='응'
    assert calls==['망치\n현재 망치 질문','망치']


def test_shared_input_cue_overlap_clipped_and_post_cue_short_word_preserved(cfg):
    now=[0.]; shared=SharedInput(cfg,clock=lambda:now[0],wall=lambda:100.)
    shared._stream=object()
    with shared.stream() as reader:
        now[0]=3.
        samples=np.arange(cfg['frame_samples'],dtype='<i2')+1000
        # 알림음 종료 경계 직후의 짧은 답이 guard 종료 전에 큐에 들어옵니다.
        stamp=SimpleNamespace(inputBufferAdcTime=1.,currentTime=3.)
        shared._receive(samples.tobytes(),cfg['frame_samples'],stamp,False)
        shared._receive(samples.tobytes(),cfg['frame_samples'],SimpleNamespace(inputBufferAdcTime=1.08,currentTime=3.),False)
        reader.begin_capture(1.04)
        first,_=reader.read(cfg['frame_samples']); second,_=reader.read(cfg['frame_samples'])
        assert first and len(first)<len(samples.tobytes()) and second==samples.tobytes()
        assert np.frombuffer(first,dtype='<i2')[0]>=1640
        # 다음 콜백에서도 경계를 걸친 정상 샘플을 통째로 버리지 않습니다.
        shared._receive(samples.tobytes(),cfg['frame_samples'],SimpleNamespace(inputBufferAdcTime=1.03,currentTime=3.),False)
        assert reader.read(cfg['frame_samples'])[0]


def test_cue_uses_shared_output_lock_and_audible_end_before_buffer_drain(cfg,monkeypatch):
    lock=threading.Lock(); cue=WakeCue(cfg,lock)
    assert cue.lock is lock
    import io
    with wave.open(io.BytesIO(cue.audio)) as wav:
        assert wav.getframerate()==cfg['voice_flow']['cue_rate_hz'] and wav.getsampwidth()==2
        assert cue.audible_samples < wav.getnframes()
    def speak(*a,**kw):
        kw['on_timing']({'playback_end_basis':'portaudio_finished_callback','playback_ended_monotonic':2.})
        return {'tts_started_monotonic':1.,'tts_mock':False,'tts_start_basis':'portaudio_first_dac'}
    monkeypatch.setattr(cue,'speak',speak)
    _,timing=cue.play()
    assert 1.<timing['cue_audible_ended_monotonic']<2.


def test_node_capture_preserves_during_guard_and_passes_prepared_boundary_once(node,node_class):
    events=[]; node.cue_active=threading.Event();node.cue_cancel=threading.Event()
    node.cue=SimpleNamespace(play=lambda **kw:({},dict(cue_audible_ended_monotonic=1.,playback_ended_monotonic=2.)))
    stream=SimpleNamespace(last_frame_monotonic=.5,begin_capture=lambda boundary:events.append(('boundary',boundary)) or boundary,
                           discard=lambda:pytest.fail('늦은 전체 discard 금지'))
    recorder=SimpleNamespace(_fixed_shared=lambda *a,**kw:events.append(('record',kw['prepared_at'])) or 'recorded')
    assert node_class._capture_after_wake(node,stream,recorder,node.generation)=='recorded'
    assert events==[('boundary',1.),('record',1.)]
    assert not node.cue_active.is_set()
    assert any(e['event']=='capture_ready' for e in node.diagnostics)


def test_node_cue_failure_never_marks_capture_ready(node,node_class):
    node.cue_active=threading.Event();node.cue_cancel=threading.Event()
    def fail(**kw):raise RuntimeError('mock')
    node.cue=SimpleNamespace(play=fail)
    stream=SimpleNamespace(last_frame_monotonic=1.,begin_capture=lambda *a:pytest.fail('준비되지 않은 cue'))
    with pytest.raises(RuntimeError):node_class._capture_after_wake(node,stream,None,node.generation)
    assert not node.cue_active.is_set() and not any(e['event']=='capture_ready' for e in node.diagnostics)


def test_old_local_and_yaml_single_source(cfg,tmp_path):
    cfg.pop('voice_flow')
    path=tmp_path/'old.yaml';path.write_text(yaml.safe_dump(cfg))
    loaded=load_config(path)
    assert loaded['voice_flow']==settings({})
    assert not loaded['voice_flow']['wake_cue_enabled'] and not loaded['voice_flow']['capture_save_wav']


def test_flow_installed_share_lookup_reads_single_yaml(monkeypatch,tmp_path):
    import sys,shutil
    from types import ModuleType
    import ready2go_voice.core.stt_error as original
    source=original._prompt_file();expected=settings({});share=tmp_path/'share/ready2go_voice'
    (share/'params').mkdir(parents=True);shutil.copyfile(source,share/'params/voice.yaml')
    index=ModuleType('ament_index_python.packages');index.get_package_share_directory=lambda name:str(share)
    monkeypatch.setitem(sys.modules,'ament_index_python',ModuleType('ament_index_python'))
    monkeypatch.setitem(sys.modules,'ament_index_python.packages',index)
    monkeypatch.setattr(original,'__file__',str(tmp_path/'lib/python3.12/site-packages/ready2go_voice/core/stt_error.py'))
    assert settings({})==expected


@pytest.mark.parametrize('value',[None,{'capture_trim':'yes'},{'cue_gain':2},{'cue_guard_sec':float('nan')},
    {'capture_save_wav':True,'capture_dir':None},{'context_reply_pattern':'['}])
def test_invalid_flow_config_rejected(cfg,value):
    cfg['voice_flow']=value
    with pytest.raises((ValueError,re.error)):
        settings(cfg)


def dummy_class():
    path=Path(__file__).resolve().parents[1]/'tools/p2_voice_dummy.py'
    spec=importlib.util.spec_from_file_location('e_flow_dummy',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.LiveDummyBridge


@pytest.mark.parametrize('changed',['none','run','generation','cancel','tts_failure','finished'])
def test_dummy_auto_complete_requires_current_real_speak_gate(changed):
    cls=dummy_class(); bridge=cls.__new__(cls)
    current=SimpleNamespace(run_id='run',finished=changed=='finished')
    bridge.voice=SimpleNamespace(submit_lock=threading.RLock(),request_run=current,
        generation=2 if changed=='generation' else 1,_request_run_connected=lambda:True)
    bridge.run='other' if changed=='run' else 'run';bridge.active=changed!='cancel'
    bridge.auto_complete=True;bridge.first_action=None;events=[];done=[]
    bridge.log=lambda event,**kw:events.append(event)
    bridge.complete=lambda:done.append(bridge.first_action)
    bridge.finish_speak(SimpleNamespace(success=changed!='tts_failure'),'run',1)
    assert bool(done)==(changed=='none')
    if done:assert done==[('run',1)] and 'dummy_first_action_after_real_speak_success' in events


def test_dummy_cancel_between_first_action_and_auto_complete_rechecks_gate():
    cls=dummy_class();bridge=cls.__new__(cls);events=[];completed=[]
    current=SimpleNamespace(run_id='run',finished=False)
    bridge.voice=SimpleNamespace(submit_lock=threading.RLock(),request_run=current,generation=1,
        _request_run_connected=lambda:True)
    bridge.run='run';bridge.active=True;bridge.auto_complete=True;bridge.first_action=None;bridge.accepted_payload={}
    def log(event,**kw):
        events.append(event)
        if event=='dummy_auto_complete_fixture_not_physical':bridge.voice.generation=2
    bridge.log=log;bridge.status=lambda *a,**kw:completed.append(kw)
    bridge.finish_speak(SimpleNamespace(success=True),'run',1)
    assert not completed and 'completion_rejected_no_current_first_action' in events
