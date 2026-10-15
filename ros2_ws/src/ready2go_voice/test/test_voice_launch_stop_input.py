"""E 실행 도구/중단 후 입력 대표 모의. 실제 준비·ROS·장치·API는 호출하지 않습니다."""
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import yaml
import pytest
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.core.safety_exchange import IndependentRegistration,RecoveryRequest
from ready2go_voice.core.recovery_confirmation import TaskEndCandidate,Evidence
from test_safety_exchange import stopped,WORK,SAFE,STT,audio
from test_voice_ux_node import node_class,node


@pytest.fixture
def trial():
    path=Path(__file__).resolve().parents[1]/'tools/voice_trial.py'
    spec=importlib.util.spec_from_file_location('e_voice_trial',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.fixture
def local(cfg,tmp_path,monkeypatch):
    for name in ('E_VOICE_CUE','E_VOICE_SAVE_WAV','E_VOICE_TRIM','E_VOICE_SILENCE','E_VOICE_AUTO_COMPLETE','E_VOICE_STT_HINT'):
        monkeypatch.delenv(name,raising=False)
    root=Path(__file__).resolve().parents[4]
    cfg['ontology_file']=str(root/'knowledge/robot_ontology.jsonld')
    cfg['intent_schema_file']=str(root/'contracts/intent.schema.json')
    cfg['tts_melotts_assets']=str(tmp_path/'assets')
    cfg['tts_prefill_max_texts']=128;cfg['voice_flow']['cue_gain']=.12
    cfg['tts_melotts_startup_timeout_sec']=60.0  # 기존 local의 명시값은 패키지600과 구분합니다.
    path=tmp_path/'local.yaml';path.write_text(yaml.safe_dump(cfg,allow_unicode=True))
    return path


def test_two_explicit_commands_new_folders_shared_selection_and_preserved_original(trial,local,tmp_path):
    before=local.read_bytes();calls=[];root=tmp_path/'runs'
    startup_timeout=yaml.safe_load(before)['tts_melotts_startup_timeout_sec']
    def prepare(cfg):
        calls.append(('prepare',cfg['_tts_prefill_texts']))
        assert cfg['tts_prefill_max_texts']==512 and cfg['voice_flow']['cue_gain']==.18
        assert cfg['tts_melotts_startup_timeout_sec']==startup_timeout
    def live(path,**kw):
        cfg=yaml.safe_load(path.read_text());calls.append(('live',trial.selected_texts(cfg)))
        assert not kw['auto_complete'] and cfg['voice_flow']['capture_save_wav']
        assert cfg['tts_melotts_startup_timeout_sec']==startup_timeout and cfg['tts_prefill_max_texts']==512
    code,first=trial.run('prepare',local,root,prepare_fn=prepare,live_fn=live)
    assert code==0 and [kind for kind,_ in calls]==['prepare']  # 자동 live 없음
    code,second=trial.run('live',local,root,prepare_fn=prepare,live_fn=live)
    assert code==0 and first!=second and calls[0][1]==calls[1][1]
    code,third=trial.run('live',local,root,prepare_fn=prepare,live_fn=live)
    assert code==0 and len({first,second,third})==3
    assert local.read_bytes()==before and all((p/'console.log').exists() for p in (first,second,third))
    assert json.loads((first/'result.json').read_text())['success']


@pytest.mark.parametrize('startup_timeout', [60.0, 600.0])
def test_actual_prepare_uses_3600_only_in_memory_and_preserves_trial_live(trial,local,tmp_path,monkeypatch,startup_timeout):
    import copy
    import ready2go_voice.adapters.melotts as adapter
    raw=yaml.safe_load(local.read_text())
    raw.update(tts_engine='melotts',tts_melotts_startup_timeout_sec=startup_timeout)
    local.write_text(yaml.safe_dump(raw,allow_unicode=True));original=local.read_bytes()
    folder=tmp_path/'trial';folder.mkdir()
    path,cfg=trial.trial_config(local,folder)
    before=copy.deepcopy(cfg);trial_yaml=path.read_bytes();events=[]
    class FakeMelo:
        def __init__(self,actual):
            assert actual['tts_melotts_startup_timeout_sec']==3600.
            assert actual['tts_prefill_max_texts']==512
            events.append('constructor')
        def prepare(self):events.append('prepare')
        def close(self):events.append('close')
    monkeypatch.setattr(adapter,'MeloTTS',FakeMelo)
    trial.prepare(cfg)  # 실제 함수 본문, 모델/worker/API/음향 장치는 호출하지 않습니다.
    assert events==['constructor','prepare','close'] and cfg==before
    assert local.read_bytes()==original and path.read_bytes()==trial_yaml
    assert yaml.safe_load(path.read_text())['tts_melotts_startup_timeout_sec']==startup_timeout


@pytest.mark.parametrize('failure',['missing','latest_failed','changed'])
def test_prepare_failure_or_changed_configuration_cannot_start_live(trial,local,tmp_path,failure):
    root=tmp_path/'runs';live=[]
    if failure!='missing':
        assert trial.run('prepare',local,root,prepare_fn=lambda cfg:None)[0]==0
    if failure=='latest_failed':
        def fail(cfg):raise RuntimeError('private detail')
        assert trial.run('prepare',local,root,prepare_fn=fail)[0]==1
    elif failure=='changed':
        cfg=yaml.safe_load(local.read_text());cfg['tts_melotts_speed']=1.3;local.write_text(yaml.safe_dump(cfg))
    code,folder=trial.run('live',local,root,live_fn=lambda *a,**kw:live.append(a))
    assert code==1 and not live and not json.loads((folder/'result.json').read_text())['success']
    assert 'private detail' not in (folder/'console.log').read_text()


def test_launcher_keyboardinterrupt_records_failure_and_never_starts_live(trial,local,tmp_path):
    def interrupted(cfg):raise KeyboardInterrupt()
    code,folder=trial.run('prepare',local,tmp_path/'runs',prepare_fn=interrupted,
        live_fn=lambda *a,**kw:pytest.fail('준비가 live를 시작하지 않습니다.'))
    assert code==130 and json.loads((folder/'result.json').read_text())['exit_code']==130


@pytest.mark.parametrize('mode',['complete_exit','interrupt'])
def test_actual_dummy_stdin_and_ctrlc_cleanup_without_ros_devices(monkeypatch,mode):
    import sys,inspect
    from types import ModuleType
    from test_flow import dummy_class
    bridge_class=dummy_class();namespace=bridge_class.__init__.__globals__
    events=[];stop=threading.Event()
    voice=SimpleNamespace(stop_event=stop,submit_lock=threading.RLock(),
        close=lambda:stop.set(),destroy_node=lambda:events.append('voice_destroy'))
    class Bridge:
        def __init__(self,*a,**kw):self.active=True;self.peer=object()
        def log(self,*a,**kw):pass
        def complete(self):events.append('complete');return False
        def close(self):events.append('bridge_close')
    class Executor:
        def __init__(self,**kw):pass
        def add_node(self,node):pass
        def spin(self):stop.wait(2)
        def shutdown(self):stop.set();events.append('shutdown')
    rclpy=ModuleType('rclpy');rclpy.init=lambda **kw:None;rclpy.shutdown=lambda:events.append('context_shutdown')
    executors=ModuleType('rclpy.executors');executors.MultiThreadedExecutor=Executor
    nodes=ModuleType('ready2go_voice.nodes.voice_node');nodes.VoiceNode=type('FakeVoice',(),{})
    monkeypatch.setitem(sys.modules,'rclpy',rclpy);monkeypatch.setitem(sys.modules,'rclpy.executors',executors)
    monkeypatch.setitem(sys.modules,'ready2go_voice.nodes.voice_node',nodes)
    monkeypatch.setattr(inspect,'getfile',lambda obj:str(namespace['PACKAGE']/'ready2go_voice/nodes/voice_node.py'))
    monkeypatch.setitem(namespace,'create_live_voice',lambda *a,**kw:voice)
    monkeypatch.setitem(namespace,'LiveDummyBridge',Bridge)
    monkeypatch.setattr(namespace['select'],'select',lambda *a:([sys.stdin],[],[]))
    inputs=iter(['complete','exit'])
    def read():
        if mode=='interrupt':raise KeyboardInterrupt()
        return next(inputs)
    monkeypatch.setattr('builtins.input',read)
    for key in ('ROS_DOMAIN_ID','ROS_LOCALHOST_ONLY','HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','ROS_LOG_DIR'):
        monkeypatch.setenv(key,'test')
    namespace['serve_live'](Path('/tmp/mock-config-no-read.yaml'))
    assert events[-4:]==['shutdown','bridge_close','voice_destroy','context_shutdown']
    assert ('complete' in events)==(mode=='complete_exit') and stop.is_set()


@pytest.mark.parametrize('text,kind',[('복구해',RecoveryRequest),('재개해',IndependentRegistration),('종료해',TaskEndCandidate)])
def test_post_stop_explicit_audio_recovery_resume_end_remain_typed_and_single_use(cfg,text,kind):
    cfg['evaluation_mode']=False;ex=stopped(cfg);now=[6.];target=ex.begin_independent(now=5.,unique_target=True)
    events=[];session=VoiceSession(None,cfg,STT(text,now),clock=lambda:now[0],progress=lambda **e:events.append(e))
    candidate=session.safety_audio(ex,target,audio());assert isinstance(candidate,kind)
    assert any(e['event']=='safety_sdk_result' for e in events)
    if isinstance(candidate,IndependentRegistration):
        final=ex.independent_registered(target,WORK,2,now=7.,valid_state=True,evidence=SAFE)
        assert final==WORK
        assert ex.independent_registered(target,WORK,2,now=7.,valid_state=True,evidence=SAFE) is None
    else:
        assert ex.policy.work==WORK
        if isinstance(candidate,TaskEndCandidate):
            assert candidate.work==WORK
            assert ex.independent_registered(target,WORK,2,now=7.,valid_state=True,evidence=SAFE) is None
            assert session.safety_audio(ex,target,audio()) is None


def test_resume_without_recovery_evidence_is_rejected_and_work_preserved(cfg):
    ex=stopped(cfg);now=[6.];target=ex.begin_independent(now=5.,unique_target=True)
    session=VoiceSession(None,cfg,STT('재개해',now),clock=lambda:now[0])
    assert isinstance(session.safety_audio(ex,target,audio()),IndependentRegistration)
    assert ex.independent_registered(target,WORK,2,now=7.,valid_state=True,
        evidence=Evidence(True,False,False,False,True)) is None
    assert ex.policy.work==WORK


@pytest.mark.parametrize('failure',['fixed_no_speech','empty','no_candidate','sdk_error'])
def test_safety_failure_reason_stage_and_fresh_retry_preserve_work(cfg,failure):
    ex=stopped(cfg);target=ex.begin_independent(now=5.,unique_target=True);now=[6.];events=[]
    record=audio();stt=STT('' if failure=='empty' else '모호한 말',now)
    if failure=='fixed_no_speech':record.recording_mode='fixed'
    if failure=='sdk_error':
        def broken(*a,**kw):raise RuntimeError('private message')
        stt.transcribe=broken
    session=VoiceSession(None,cfg,stt,clock=lambda:now[0],progress=lambda **e:events.append(e),
        speech_gate=SimpleNamespace(check=lambda *a,**kw:False))
    assert session.safety_audio(ex,target,record) is None and ex.policy.work==WORK
    assert ex.policy.independent is None and ex.capture is None
    assert all('private message' not in str(e) for e in events)
    last=events[-1]
    if failure=='fixed_no_speech':assert last['reason']=='NO_SPEECH' and last['stage']=='speech_check'
    elif failure=='empty':assert last['reason']=='NO_SPEECH' and last['stage']=='sdk'
    elif failure=='no_candidate':assert last['reason']=='command_not_matched'
    else:assert last['reason']=='RuntimeError'
    assert ex.begin_independent(now=7.,unique_target=True) is not None  # 새 독립 요청만 허용


def test_stop_capture_sdk_and_publication_diagnostics_are_separate(node,node_class):
    node.now[0]=6.;events=[];node.session.progress=lambda **e:events.append(e)
    node.session.stt=STT('멈춰',node.now)
    doc=node.session.stop_audio(audio());assert doc['intent']=='cancel'
    assert [e['event'] for e in events if e['event'] in ('stop_sdk_request','stop_sdk_result','stop_stt_result')]==['stop_sdk_request','stop_sdk_result','stop_stt_result']
    with node.submit_lock:node_class._stop_locked(node,doc,node.generation)
    assert any(e['event']=='stop_request_published' and e['published'] for e in node.diagnostics)
    assert node.published[-1]['intent']=='cancel'
