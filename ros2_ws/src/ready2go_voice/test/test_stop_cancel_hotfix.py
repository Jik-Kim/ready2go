"""승인된 정지/더미/문맥 회귀. 장치/API/재생/물리 결과는 시험하지 않습니다."""
import copy
import io
import json
import sys
import threading
import wave
from types import ModuleType, SimpleNamespace
import numpy as np
import pytest
from test_voice_ux_node import node_class, node, ask
from test_flow import dummy_class
from ready2go_voice.adapters.audio import Recorder
from ready2go_voice.core.tts_prefill import prefill_texts
from ready2go_voice.core.recovery_confirmation import TaskEndCandidate


def test_dc_offset_does_not_keep_recording_or_modify_pcm(cfg):
    cfg=copy.deepcopy(cfg);cfg.update(silence_sec=.4,max_record_sec=8.,speech_start_timeout_sec=3.)
    now=[0.];frames=[]
    # 실제 장치가 아닌 AC 신호 + 큰 DC. 임계값/기한은 기존 값입니다.
    for amplitude in [100,100,900,900,900,100,100,100,100,100,100]:
        frames.append((7800+np.resize(np.array([-amplitude,amplitude]),cfg['frame_samples'])).astype('<i2').tobytes())
    class Stream:
        index=0
        def read(self,size):
            value=frames[self.index];self.index+=1;now[0]+=size/cfg['sample_rate'];return value,False
    stream=Stream();rec=Recorder(cfg,clock=lambda:now[0],wall=lambda:100.).record(stream,threading.Event())
    assert rec.pcm==b''.join(frames[2:stream.index])
    assert rec.pcm.startswith(frames[2]) and rec.pcm.count(frames[4])>=1
    assert .4<=rec.recording_ended_monotonic-rec.ended_monotonic<.5
    assert stream.index<len(frames)+1


@pytest.mark.parametrize('reply',['어, 그거.','그걸로'])
def test_current_question_reaches_semantic_llm_before_consumption(node,reply):
    ask(node);q=node.session.conversation.pending;received=[]
    def llm(text,remaining,*,context):
        assert node.session.conversation.pending is q
        received.append((text,context))
        return {'intent':'find_item','targets':['toy_hammer'],'confidence':.99}
    llm.supports_context=True;node.parser.llm=llm
    doc=node.session.text(reply)
    assert received[0][1]['reply']==reply and received[0][1]['target']=='toy_hammer'
    assert received[0][1]['question_id']==q.id and received[0][1]['question']
    assert doc['intent']=='find_item' and doc['_voice']['context_answer']
    assert node.session.conversation.pending is None


def test_semantic_hold_keeps_question_without_renewal_then_reuses_target(node):
    ask(node);q=node.session.conversation.pending
    def clarify(*a,**kw):return {'intent':'clarify','targets':[],'confidence':.99}
    clarify.supports_context=True;node.parser.llm=clarify
    doc=node.session.text('어, 그거.');node.deliver(doc)
    assert node.session.conversation.pending is q and q.expires==doc['_voice']['original_question_expires']
    node.parser.llm=None
    assert node.session.text('그걸로')['targets']==['toy_hammer']


@pytest.mark.parametrize('reply',['아니요','아니, 그거.','망치 가져다주지 마','렌치 가져다줘','서랍 닫아줘'])
def test_other_or_negative_reply_never_gets_previous_target(node,reply):
    ask(node);contexts=[]
    def llm(*a,**kw):
        contexts.append(kw.get('context'))
        return {'intent':'find_item','targets':['toy_hammer'],'confidence':.99}
    llm.supports_context=True;node.parser.llm=llm
    doc=node.session.text(reply)
    assert not doc['_voice'].get('context_answer') and all(x is None for x in contexts)
    assert not (doc['source']['execution_allowed'] and doc['targets']==['toy_hammer'])


def test_prefill_matches_actual_readonly_phrases_and_particles(node,cfg):
    parser=node.parser
    texts=prefill_texts(cfg,parser.items.values(),reference_state=parser.reference_state,places=parser.places,
        item_names={k:v['name_ko'] for k,v in parser.items.items()})
    for provider in (None,lambda:parser.reference_state):
        parser.state_provider=provider
        for text in ('지금 망치 어딨어?','위쪽 서랍 열려있어?'):
            answer=node.session.text(text)['_voice']['final_text']
            assert answer in texts and '장난감 망치은' not in answer
    assert len(texts)+1<=cfg['tts_prefill_max_texts']


def _dummy(monkeypatch):
    cls=dummy_class();events=[]
    node_module=ModuleType('rclpy.node');node_module.Node=lambda *a:SimpleNamespace(create_subscription=lambda *a:None)
    action=ModuleType('rclpy.action')
    class Client:
        def __init__(self,*a):pass
        def send_goal_async(self,goal):return SimpleNamespace(add_done_callback=lambda f:None)
    action.ActionClient=Client
    messages=ModuleType('std_msgs.msg');messages.String=lambda **kw:SimpleNamespace(**kw)
    actions=ModuleType('ready2go_interfaces.action');actions.Skill=SimpleNamespace(Goal=lambda:SimpleNamespace())
    for name,value in [('rclpy.node',node_module),('rclpy.action',action),('std_msgs.msg',messages),('ready2go_interfaces.action',actions)]:monkeypatch.setitem(sys.modules,name,value)
    voice=SimpleNamespace(cfg={'voice_flow':{'dummy_auto_complete':False}},stop_event=threading.Event(),
        submit_lock=threading.RLock(),generation=0,request_run=SimpleNamespace(pending=None,run_id=None,finished=False),
        bind_request_source=lambda f,**kw:None,bind_safety_sender=lambda f:None,_request_run_connected=lambda:True,
        safety_task_end_accepted=lambda *a,**kw:True,safety_stopped=lambda *a,**kw:True,
        safety_feedback=lambda work,kind,**kw:dict(work=work,kind=kind,candidate=kw.get('candidate'),generation=0))
    def status(message):
        data=json.loads(message.data);decision=data.get('last_intent')
        if decision:voice.request_run.run_id=decision['run_id'];voice.request_run.finished=data['phase']=='idle'
    voice._runner_status=status
    bridge=cls(voice);bridge.log=lambda event,**kw:events.append((event,kw))
    return bridge,events


def _accept(bridge,request):
    payload={'intent':'find_item','targets':['toy_hammer'],'request_id':request,'accept_text':'요청으로 이해했어요.'}
    bridge.voice.request_run.pending=payload
    bridge.intent(SimpleNamespace(data=json.dumps(payload)))
    bridge.finish_speak(SimpleNamespace(success=True),bridge.run,bridge.voice.generation)


def test_actual_constructor_accept_first_action_cancel_end_next_complete(monkeypatch):
    bridge,events=_dummy(monkeypatch)
    assert bridge.revision==0 and bridge.work is None  # 결함을 가리는 수동 초기값 주입 없음
    _accept(bridge,'one');run=bridge.run
    assert bridge.first_action==(run,0)
    bridge.intent(SimpleNamespace(data=json.dumps({'intent':'cancel'})))
    assert bridge.revision==1 and bridge.work.task==run and bridge.run==run and bridge.first_action is None
    assert bridge.complete() is False
    assert events[-1][0]=='completion_rejected_stopped_run_requires_existing_end_path'
    bridge.safety_event('candidate',TaskEndCandidate(bridge.work))
    assert bridge.work is not None
    bridge.safety_event('feedback_delivered',bridge.feedback)
    assert bridge.work is None and bridge.run is None
    _accept(bridge,'two');assert bridge.complete() is True
    assert bridge.voice.request_run.finished


def test_cancel_fixture_failure_does_not_partially_clear_first_action(monkeypatch):
    bridge,events=_dummy(monkeypatch);_accept(bridge,'one');old=(bridge.first_action,bridge.run,bridge.revision)
    bridge.voice.safety_stopped=lambda *a,**kw:False
    with pytest.raises(RuntimeError):bridge.intent(SimpleNamespace(data=json.dumps({'intent':'cancel'})))
    assert (bridge.first_action,bridge.run,bridge.revision)==old and bridge.work is None


def test_executor_error_marks_dummy_unavailable(monkeypatch):
    bridge,events=_dummy(monkeypatch)
    # dummy_class loader의 함수 globals에서 동일 모듈 구현을 사용합니다.
    spin=bridge.__class__.__init__.__globals__['spin_live']
    def fail():raise TypeError('sensitive raw detail')
    spin(SimpleNamespace(spin=fail),bridge.voice,bridge)
    assert not bridge.active and bridge.voice.stop_event.is_set()
    assert events[-1]==('dummy_test_unavailable_executor_failed',{'error_type':'TypeError'})


def test_console_acceptance_never_regresses_after_request_is_invalidated(node,node_class):
    messages=[];node.get_logger=lambda:SimpleNamespace(info=messages.append)
    node.accepted_request_logs=['request']
    node.request_run.invalidate()
    node_class._diagnostic(node,{'event':'intent','intent':{'intent':'find_item','targets':['toy_hammer'],
        '_voice':{'request_id':'request'}},'published':True})
    assert '현재 요청 수락 확인' in messages[-1] and '미확인' not in messages[-1]
    node_class._diagnostic(node,{'event':'intent','intent':{'intent':'find_item','targets':['toy_hammer'],
        '_voice':{'request_id':'different'}},'published':True})
    assert '수락 미확인' in messages[-1]


def test_stop_addition_rejects_negative_and_own_voice(node):
    assert node.parser.control('중단해')['intent']=='cancel'
    assert node.parser.control('중단하지 마') is None
