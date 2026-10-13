"""종료 최소 연결. 실제 메서드/진단/SDK prompt, 장치·API·ROS 전송만 모의."""
from dataclasses import replace
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_voice_ux_node import node_class, node
from test_control_feedback_workers import live_boundary, finish
from test_safety_exchange import audio, stopped, WORK, SAFE
from test_voice_launch_stop_input import trial
from ready2go_voice.adapters.api import WhisperSTT
from ready2go_voice.core.recovery_confirmation import StoppedWork, safety_utterance
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.core.tts_prefill import prefill_texts
from ready2go_voice.core.hotfix import prompts


def sdk(monkeypatch, cfg, clock, answer):
    calls=[]
    class OpenAI:
        def __init__(self, **kwargs):
            self.audio=SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def create(self, **kwargs):
            calls.append(kwargs['prompt'])
            assert kwargs['model']==cfg['stt_model'] and kwargs['language']=='ko'
            assert kwargs['file'].read()
            return SimpleNamespace(text=answer())
    monkeypatch.setitem(sys.modules,'openai',SimpleNamespace(OpenAI=OpenAI))
    return WhisperSTT(cfg,['지우개','립밤'],clock=clock),calls


@pytest.fixture
def end_boundary(live_boundary,monkeypatch):
    h=live_boundary
    h.node.bind_request_source(lambda:h.bridge.active,boot='dummy')
    h.node.session.stt,h.prompts=sdk(monkeypatch,h.node.cfg,lambda:h.node.now[0],lambda:h.device.text)
    return h


def end_capture(h):
    n=h.node;h.queued.clear();h.device.entered.clear();h.device.release.clear();h.device.text='종료'
    generation=n.generation
    record=replace(audio(),recording_started_monotonic=n.now[0]-.2,
                   recording_ended_monotonic=n.now[0])
    assert n._queue_stop_capture(record,generation,())
    assert h.device.entered.wait(5), '실제 stop worker에서 종료 안내 작업으로 연결되지 않음'
    return generation


def diagnostics(h):
    return [json.loads(line) for line in Path(h.node.cfg['diagnostic_file']).read_text().splitlines()]


def test_running_stop_sdk_end_and_general_duplicate_then_idle_new_request(end_boundary):
    h=end_boundary;n=h.node
    finish(h,'복구해');finish(h,'이어서 해')
    assert n.notice_policy.phase=='running' and h.bridge.work is None
    original=h.bridge.run;cancel_count=sum(d['intent']=='cancel' for d in n.published)
    prior_safety=sum(d['event']=='safety_sdk_request' for d in diagnostics(h))
    old_generation=end_capture(h)
    assert n.notice_policy.phase=='halted' and h.bridge.work.task==original
    token=n.control_feedback
    n._runner_status(SimpleNamespace(data=json.dumps(dict(phase='halted',task_id='dummy',halt_code='CANCELED',last=None,last_intent=None))))
    assert h.bridge.stopped_fixture(h.bridge.work,h.bridge.revision+1,h.bridge.evidence)
    assert n.control_feedback is token and not n.safety_cancel.is_set()  # 동일한 heartbeat/seq
    assert not n._submit(('text','종료'),generation=old_generation)  # 오래된 일반 전사 중복
    assert sum(d['intent']=='cancel' for d in n.published)==cancel_count+1
    assert not n._submit(('text','지우개 가져다줘'))  # 종료 안내/수락 전 새 요청 차단
    h.device.release.set();h.settled()
    assert n.notice_policy.phase=='idle' and h.bridge.run is None and h.bridge.work is None
    published=threading.Event();publish=n._publish
    def new_request(doc):
        publish(doc)
        if doc.get('targets')==['eraser']:published.set()
    n._publish=new_request
    h.send('지우개 가져다줘');assert published.wait(5);h.settled()
    assert n.published[-1]['targets']==['eraser'] and n.notice_policy.phase=='running'
    # 종료 발화로 새 safety SDK/독립 등록 증빙을 만들지 않습니다.
    events=diagnostics(h)
    assert sum(d['event']=='stop_sdk_request' for d in events)==1
    assert sum(d['event']=='safety_sdk_request' for d in events)==prior_safety
    assert h.prompts[-2]==n.cfg['stt_control_prompt']


def test_general_worker_end_during_running_uses_same_stop_chain(end_boundary):
    h=end_boundary;n=h.node;finish(h,'복구해');finish(h,'이어서 해')
    h.send('종료');assert h.device.entered.wait(5)
    assert n.notice_policy.phase=='halted' and h.bridge.work is not None
    h.device.release.set();h.settled()
    assert n.notice_policy.phase=='idle' and h.bridge.work is None


def test_halted_end_does_not_need_another_wake_or_recovery(end_boundary):
    h=end_boundary;end_capture(h)
    assert h.bridge.work is not None
    h.device.release.set();h.settled()
    assert h.node.notice_policy.phase=='idle' and h.bridge.work is None


@pytest.mark.parametrize('order',['status_first','typed_first','other_run','other_boot','unconfirmed','restop_waiting'])
def test_waits_for_current_stop_and_does_not_reuse_wrong_confirmation(end_boundary,order):
    h=end_boundary;n=h.node;finish(h,'복구해');finish(h,'이어서 해')
    run=h.bridge.run;requested=threading.Event();emit=h.writer.emit
    def observed(doc):
        emit(doc)
        if doc['event']=='task_end_stop_requested':requested.set()
    h.writer.emit=observed
    n._publish=lambda doc:n.published.append(doc)  # ROS/C 정지 응답 지연만 모의
    h.device.entered.clear();h.device.release.clear();h.device.text='종료'
    assert n._queue_stop_capture(replace(audio(),recording_started_monotonic=n.now[0]-.2,
                                       recording_ended_monotonic=n.now[0]),n.generation,())
    assert requested.wait(5)
    assert not h.device.entered.is_set() and n.task_end_request is not None
    assert n.notice_policy.phase=='running' and h.bridge.run==run
    before=sum(d['intent']=='cancel' for d in n.published)
    with n.submit_lock:
        n._task_end_locked(n.session.text('종료',n.generation,runner_state='running'),n.generation)
    assert sum(d['intent']=='cancel' for d in n.published)==before
    work=StoppedWork('other' if order=='other_boot' else 'dummy','new-halt',
                     'other-run' if order=='other_run' else run,'dummy_step')
    status=SimpleNamespace(data=json.dumps(dict(phase='halted',task_id='dummy',halt_code='CANCELED',last=None,last_intent=None)))
    if order=='typed_first':
        assert h.bridge.stopped_fixture(work,h.bridge.revision+1,SAFE)
        assert not h.device.entered.is_set()
        n._runner_status(status)
    else:
        n._runner_status(status)
        if order=='unconfirmed':n.safety_stopped(work,h.bridge.revision+1,valid_state=False,evidence=SAFE)
        else:
            if order=='restop_waiting':
                with n.submit_lock:n._stop_locked(n.session.text('중지',n.generation))
            assert h.bridge.stopped_fixture(work,h.bridge.revision+1,SAFE)
    if order in ('status_first','typed_first'):
        assert h.device.entered.wait(5)
        h.device.release.set();h.settled()
        assert n.notice_policy.phase=='idle' and h.bridge.work is None
    else:
        assert not h.device.entered.is_set() and n.pending_task_end is None
        assert n.notice_policy.phase=='halted' and h.bridge.run is not None


def test_unconfirmed_running_end_reaches_actual_notice_worker_without_end_permission(end_boundary):
    h=end_boundary;n=h.node;finish(h,'복구해');finish(h,'이어서 해')
    n.request_source_boot=None;n._publish=lambda doc:n.published.append(doc)
    n.pending_notice=None;finished=threading.Event();emit=h.writer.emit
    def observed(doc):
        emit(doc)
        if doc['event']=='tts_finished' and doc.get('notice_kind')=='task_end_held':finished.set()
    h.writer.emit=observed
    worker=threading.Thread(target=n._notice_work);worker.start()
    try:
        h.device.entered.clear();h.device.release.clear();h.device.text='종료'
        assert n._queue_stop_capture(replace(audio(),recording_started_monotonic=n.now[0]-.2,
                                           recording_ended_monotonic=n.now[0]),n.generation,())
        assert h.device.entered.wait(5)
        assert n.texts[-1]==n.session.flow['status_prompts']['unconfirmed']
        h.device.release.set();assert finished.wait(5)
        assert n.notice_policy.phase=='running' and h.bridge.run is not None
        assert n.task_end_request is None and n.pending_task_end is None
    finally:
        n.stop_event.set();h.device.release.set()
        with n.notice_condition:n.notice_condition.notify_all()
        worker.join(5);assert not worker.is_alive()


@pytest.mark.parametrize('change',['restop','unconfirmed','other_run','boot','tts'])
def test_end_feedback_failure_or_current_identity_change_preserves_lock(end_boundary,change):
    h=end_boundary;n=h.node;finish(h,'복구해');finish(h,'이어서 해');end_capture(h)
    if change=='restop':
        with n.submit_lock:n._stop_locked(n.session.text('중지',n.generation))
    elif change=='unconfirmed':
        n.safety_stopped(h.bridge.work,h.bridge.revision+1,valid_state=False,evidence=SAFE)
    elif change=='other_run':
        n.safety_stopped(StoppedWork('dummy','another-halt','another-run','step'),h.bridge.revision+1,
                         valid_state=True,evidence=SAFE)
    elif change=='boot':n.bind_request_source(lambda:True,boot='other-boot')
    else:h.device.fail=True
    h.device.release.set();h.settled()
    assert n.notice_policy.phase=='halted' and n.safety_exchange.policy.work is not None
    assert h.bridge.run is not None and not n.request_run.finished


@pytest.mark.parametrize('text,positive',[('중지',True),('중지하지 마',False),('"중지"',False),
    ('그 사람이 중지하래',False),('요소희',False),('이어서헥스',False)])
def test_exact_stop_and_wrong_transcript_are_not_forced_to_control(node,monkeypatch,text,positive):
    node.session.stt,_=sdk(monkeypatch,node.cfg,lambda:6.,lambda:text)
    node.session.clock=lambda:6.
    result=node.session.stop_audio(audio())
    assert (result is not None)==positive
    assert (safety_utterance(text)=='stop')==positive
    if positive:
        assert node.parser.control(text)['intent']=='cancel'
        assert node.session.stop_audio(audio(),spoken_texts={'중지라고 말씀해 주세요.'}) is None


def test_real_sdk_prompts_split_stop_safety_and_normal(cfg,monkeypatch,tmp_path):
    stt,calls=sdk(monkeypatch,cfg,lambda:6.,lambda:'중지')
    session=VoiceSession(None,cfg,stt,clock=lambda:6.)
    assert session.stop_audio(audio())['intent']=='cancel'
    exchange=stopped(cfg);target=exchange.begin_independent(now=4.,unique_target=True)
    assert session.safety_audio(exchange,target,audio())['intent']=='cancel'
    p=tmp_path/'normal.wav';p.write_bytes(b'mock SDK file')
    stt.transcribe(p,1,before_request=lambda stamp:True,context_hint=lambda:'현재 물품 지우개')
    assert calls[:2]==[cfg['stt_control_prompt']]*2
    assert all('지우개' not in prompt and '립밤' not in prompt for prompt in calls[:2])
    assert calls[-1]=='지우개, 립밤\n현재 물품 지우개'


def test_control_prefill_node_prepare_identity_and_original_limits(node,trial,tmp_path):
    cfg=node.cfg;cfg['tts_melotts_assets']=str(tmp_path)
    cfg['ontology_file']=str(Path(__file__).resolve().parents[4]/'knowledge/robot_ontology.jsonld')
    selected=trial.selected_texts(cfg)
    direct=prefill_texts(cfg,node.parser.items.values(),reference_state=node.parser.reference_state,
                         places=node.parser.places,item_names={k:v['name_ko'] for k,v in node.parser.items.items()})
    assert selected==direct
    assert all(prompts(cfg)[key] in selected for key in ('control_recover','control_resume','control_end','control_failed'))
    assert len(selected)+1<=cfg['tts_prefill_max_texts']==256
    assert cfg['tts_melotts_startup_timeout_sec']==60
    assert trial.preparation_identity(cfg,selected)==trial.preparation_identity(cfg,direct)


@pytest.mark.parametrize('phase',['idle','running','unconfirmed'])
def test_task_end_status_distinguishes_empty_and_unknown_without_llm(node,phase):
    node.parser.llm=lambda *args:pytest.fail('종료에 LLM 사용')
    doc=node.session.text('종료',node.generation,runner_state=phase)
    assert doc['_voice']['safety_control']=='task_end'
    assert doc['_voice']['final_text']==(prompts(node.cfg)['no_end_work'] if phase=='idle'
                                        else node.session.flow['status_prompts']['unconfirmed'])


def test_idle_with_unfinished_correlated_run_is_unconfirmed(node):
    payload=dict(intent='find_item',targets=['eraser'],request_id='current')
    assert node.request_run.register(payload)
    node.request_run.observe(dict(phase='idle',task_id=None,halt_code=None,last=None,
        last_intent=dict(payload,decision='run',run_id='active-run')))
    doc=node.session.text('종료',node.generation,runner_state='idle')
    with node.submit_lock:assert not node._task_end_locked(doc,node.generation)
    assert doc['_voice']['final_text']==node.session.flow['status_prompts']['unconfirmed']
    assert not node.published and node.request_run.run_id=='active-run'
