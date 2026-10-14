"""#322 actual E methods + pinned current C bodies; device/ROS/SDK remain mocks."""
import ast
import copy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import pytest
from ready2go_voice.adapters.audio import Recording
from ready2go_voice.adapters.speech import SpeechPresence
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.core.hotfix import prompts, control_notice
from ready2go_voice.core.tts_prefill import prefill_texts
from test_voice_ux_node import node, node_class
from test_c_control_wire import Wire, INFO, C_PACKAGE


def memory_node(node):
    status = SimpleNamespace(node_name='runner',node_namespace='/',topic_type='std_msgs/msg/String',
                             endpoint_gid=bytes([7]*24))
    state = SimpleNamespace(**dict(status.__dict__,endpoint_gid=bytes([9]*24)))
    endpoints={'/runner/status':[status],'/robot_state':[state]}
    node.get_publishers_info_by_topic=lambda topic:list(endpoints[topic])
    subscriptions=[]
    def subscribe(cls,topic,callback,qos,**kw):
        subscriptions.append((topic,callback,qos))
        return SimpleNamespace(topic_name=topic)
    node.create_subscription=subscribe
    node.destroy_subscription=lambda subscription:True
    node.cfg['request_run_enabled']=False
    node.runner_control_source=None;node._control_binding=None;node._control_source_lost=False
    node._init_runner_control_source()
    node._init_runner_memory('latched-reliable-depth1')
    def status_packet(seq=1,boot='boot',stamp=10):
        doc=dict(boot_id=boot,seq=seq,phase='idle',halt=None,halt_code=None,last=None,task_id=None)
        node._runner_status_with_info(SimpleNamespace(data=json.dumps(doc)),dict(INFO,source_timestamp=stamp))
    def state_packet(state_doc=None,stamp=11):
        doc=copy.deepcopy(node.parser.reference_state) if state_doc is None else state_doc
        node._robot_state(SimpleNamespace(data=json.dumps(doc)),dict(INFO,source_timestamp=stamp))
    return endpoints,status_packet,state_packet,subscriptions


def answer(node,text):
    doc=node.session.text(text,node.generation)
    assert doc['_voice']['readonly_query'] and not doc['source']['execution_allowed']
    assert not doc['source']['llm_called']
    node.deliver(doc)
    notice=node.pending_notice
    if notice is not None and notice.kind=='readonly_query':
        node.pending_notice=None
        node._play_notice(notice,threading.Event())
    return node.texts[-1]


def test_real_default_false_memory_callback_parser_and_tts(node):
    endpoints,status,state,subscriptions=memory_node(node)
    assert subscriptions[0][0]=='/robot_state'
    assert '확인할 수 없습니다' in answer(node,'지우개 어딨어?')
    status();state()
    assert '아래 서랍' in answer(node,'지우개 어딨어?')
    doc=copy.deepcopy(node.parser.reference_state)
    doc['located_in']['eraser']='handover_zone';doc['open']['drawer_top']=True
    state(doc,stamp=12)
    assert '전달 트레이' in answer(node,'지우개 어딨어?')
    assert '열려있습니다' in answer(node,'위쪽 서랍 열려있어?')
    doc['open']['drawer_top']=False;state(doc,stamp=13)
    assert '닫혀있습니다' in answer(node,'위쪽 서랍 열려있어?')
    returned=node._runner_memory_state();returned['open']['drawer_top']=True
    assert node._runner_memory_state()['open']['drawer_top'] is False
    assert not node.published and getattr(node,'control_mapper',None) is None


@pytest.mark.parametrize('bad',[[],{}, {'located_in':{'eraser':'missing'},'open':{}},
    {'located_in':{},'open':{'drawer_top':1}}])
def test_bad_memory_never_falls_back_to_initial_state(node,bad):
    _,status,state,_=memory_node(node);status();state()
    state(bad)
    assert '확인할 수 없습니다' in answer(node,'지우개 어딨어?')
    node._robot_state(SimpleNamespace(data='{invalid'),dict(INFO))
    assert node._runner_memory_state() is None and not node.published


def test_state_before_first_status_is_latched_but_loss_and_restart_require_new_sample(node):
    endpoints,status,state,_=memory_node(node)
    state();assert node._runner_memory_state() is None
    status();assert node._runner_memory_state() is not None
    endpoints['/runner/status']=[]
    assert node._runner_memory_state() is None
    endpoints['/runner/status']=[SimpleNamespace(node_name='runner',node_namespace='/',
        topic_type='std_msgs/msg/String',endpoint_gid=bytes([7]*24))]
    status(seq=2,stamp=20)
    assert node._runner_memory_state() is None
    state(stamp=9);assert node._runner_memory_state() is None
    state(stamp=21);assert node._runner_memory_state() is not None
    status(seq=1,boot='new-boot',stamp=30)
    assert node._runner_memory_state() is None
    state(stamp=21);assert node._runner_memory_state() is None
    state(stamp=31);assert node._runner_memory_state() is not None
    endpoints['/robot_state']*=2
    assert '확인할 수 없습니다' in answer(node,'위쪽 서랍 열려있어?')


def test_deep_invalid_json_is_held_in_state_and_status_callbacks(node):
    _,status,state,_=memory_node(node);status();state()
    bad=SimpleNamespace(data='['*2048+']'*2048)
    node._robot_state(bad,dict(INFO))
    assert node._runner_memory_state() is None
    node._runner_status_with_info(bad,dict(INFO))
    assert node._runner_memory_state() is None and not node.published


@pytest.mark.parametrize('score,signal,accepted',[(0.,2000,False),(1.,0,False),(1.,2000,True)])
def test_stop_speech_presence_uses_existing_rms_vad_and_skips_sdk(cfg,score,signal,accepted):
    class Detector:
        def reset_states(self):pass
        def predict(self,*a,**kw):return score
    gate=SpeechPresence(cfg,detector=Detector())
    events=[];calls=[]
    def transcribe(*a,**kw):
        calls.append(1);return '중지'
    stt=SimpleNamespace(transcribe=transcribe)
    session=VoiceSession(None,cfg,stt,clock=lambda:10.,speech_gate=gate,
                         progress=lambda **e:events.append(e))
    import numpy as np
    pcm=(np.tile([signal,-signal],8000).astype('<i2')).tobytes()
    recording=Recording(pcm,9.,123.,recording_started_monotonic=8.,recording_ended_monotonic=9.)
    doc=session.stop_audio(recording)
    if accepted:
        assert doc['intent']=='cancel' and calls==[1]
        assert any(e.get('event')=='stop_control_accepted' for e in events)
    else:
        assert doc is None and not calls
        assert any(e.get('reason')=='NO_SPEECH' for e in events)


def test_console_only_accepted_control_changed_state_and_first_rejection(node,node_class):
    messages=[];detail=[]
    node.get_logger=lambda:SimpleNamespace(info=messages.append)
    node.diagnostic_file=SimpleNamespace(emit=detail.append)
    node.cfg['diagnostic_detail']=True
    emit=lambda doc:node_class._diagnostic(node,doc)
    state=dict(event='voice_state',phase='halted',work_retained=True,termination_pending=False)
    emit(state);emit(state)
    emit(dict(state,termination_pending=True))
    emit(dict(event='stop_stt_result',text='자기 TTS'))
    emit(dict(event='stop_control_accepted',text='중지',kind='stop'))
    held=dict(event='safety_result_held',reason='EXTERNAL_FORCE_UNKNOWN')
    emit(held);emit(held)
    assert len(messages)==4 and len(detail)==7
    assert not any('자기 TTS' in message for message in messages)
    assert any('EXTERNAL_FORCE_UNKNOWN' in message for message in messages)


def test_stop_vad_does_not_wait_for_the_general_input_vad_lock(cfg,monkeypatch):
    class Detector:
        def reset_states(self):pass
        def predict(self,*a,**kw):return 1.
    monkeypatch.setattr(SpeechPresence,'_load',lambda self:Detector())
    general=SpeechPresence(cfg)
    session=VoiceSession(None,cfg,SimpleNamespace(transcribe=lambda *a,**kw:'중지'),clock=lambda:10.)
    session.speech_gate=general
    import numpy as np
    record=Recording(np.tile([2000,-2000],8000).astype('<i2').tobytes(),9.,123.,
        recording_started_monotonic=8.,recording_ended_monotonic=9.)
    done=threading.Event();results=[]
    def stop():
        try:results.append(session.stop_audio(record))
        finally:done.set()
    worker=threading.Thread(target=stop)
    general.lock.acquire();worker.start()
    try:
        assert done.wait(2), '독립 정지가 일반 입력 VAD lock을 기다림'
    finally:
        general.lock.release();worker.join(2)
    assert not worker.is_alive() and results[0]['intent']=='cancel'


class Future:
    def __init__(self,reply,*,timeout=False,error=False):
        self.reply,self.timeout,self.error,self.canceled=reply,timeout,error,False
    def add_done_callback(self,callback):
        if not self.timeout:callback(self)
    def cancel(self):self.canceled=True
    def result(self):
        if self.error:raise RuntimeError('mock service failure')
        return self.reply


def fake_b_services(wire,monkeypatch,*,failure=None,force=False,restop=False):
    """Reuse C b_service response handler and actual _call_trigger/_b_* methods."""
    fake_trigger=SimpleNamespace(Request=SimpleNamespace,Response=SimpleNamespace)
    monkeypatch.setitem(sys.modules,'std_srvs.srv',SimpleNamespace(Trigger=fake_trigger))
    tree=ast.parse((C_PACKAGE/'test/test_voice_intent_node.py').read_text())
    tree.body=[item for item in tree.body if isinstance(item,ast.FunctionDef) and item.name in ('b_service','b_state')]
    namespace={'json':json};exec(compile(tree,'C-b-service-helper','exec'),namespace)
    handlers={};events=[]
    fake_node=SimpleNamespace(create_service=lambda cls,name,handler:handlers.__setitem__(name,handler))
    namespace['b_service'](SimpleNamespace(node=fake_node),'/skills/recover',
        (failure!='reject',dict(recovered=failure!='reject',code='ESTOP_ACTIVE' if failure=='reject' else None)))
    state=namespace['b_state'](wire.c,external_force=force)
    namespace['b_service'](SimpleNamespace(node=fake_node),'/skills/check_state',(True,state))
    futures=[]
    class Client:
        def __init__(self,name):self.name=name
        def service_is_ready(self):return failure!='unavailable'
        def call_async(self,request):
            events.append(self.name)
            if restop and self.name=='/skills/check_state':wire.c.runner.halt(source='test-new-stop')
            response=handlers[self.name](request,SimpleNamespace())
            future=Future(response,timeout=failure=='timeout' or failure=='w1_timeout' and self.name=='/skills/check_state',
                          error=failure=='error' or failure=='w1_error' and self.name=='/skills/check_state')
            futures.append(future);return future
    c=wire.c;c.recover_check='b';c.recover_call_b=True;c.recover_limits=dict(stamp_max_age_s=2.,drawer_open_min_m=.01)
    c.b_timeout_s=.01;c.b_recover_client=Client('/skills/recover');c.b_check_client=Client('/skills/check_state')
    return events,futures


def test_actual_c_b_recover_then_fresh_check_and_one_registered_question(node,monkeypatch):
    wire=Wire(node);events,_=fake_b_services(wire,monkeypatch)
    wire.independent('복구해')
    assert events==['/skills/recover','/skills/check_state']
    assert wire.c._last_intent['decision']=='recover' and not wire.c.runner.halted
    assert node.safety_exchange.policy.question is not None
    assert node.pending_notice is None # recovery announcement must not race registered question
    wire.question('아니요')
    assert len(wire.tts)==1 and len([d for d in wire.sent if d['intent']=='resume_register'])==1
    assert '더미' not in wire.tts[0]


@pytest.mark.parametrize('failure',['reject','unavailable','timeout','error','w1_timeout','w1_error','force','unknown','restop'])
def test_actual_c_b_rejection_failure_timeout_and_restopped_preserve_lock(node,monkeypatch,failure):
    wire=Wire(node)
    events,futures=fake_b_services(wire,monkeypatch,
        failure=failure if failure in ('reject','unavailable','timeout','error','w1_timeout','w1_error') else None,
        force=True if failure=='force' else None if failure=='unknown' else False,
        restop=failure=='restop')
    wire.independent('복구해')
    assert wire.c._last_intent['decision']=='reject'
    assert wire.c.runner.halted and wire.c.runner.suspended is not None
    assert node.safety_exchange.policy.work is not None and node.safety_exchange.policy.question is None
    assert not wire.tts and not wire.started
    assert not any(d['intent'] in ('resume','resume_answer') for d in wire.sent)
    if failure=='timeout':assert futures[0].canceled
    if failure=='w1_timeout':assert futures[1].canceled
    if failure in ('force','unknown','restop'):assert events==['/skills/recover','/skills/check_state']
    if node.pending_notice is not None:assert '더미' not in node.pending_notice.text


def test_runtime_prefill_all_memory_answers_and_not_dummy_notices(cfg,ontology,tmp_path):
    cfg=dict(cfg,tts_melotts_assets=str(tmp_path))
    texts=prefill_texts(cfg,ontology['world']['items'].values(),reference_state=ontology['state'],
        places=ontology['world']['places'],item_names={k:v['name_ko'] for k,v in ontology['world']['items'].items()})
    for key,text in prompts(cfg).items():
        if key.startswith('runtime_'):assert text in texts and '더미' not in text
    assert len(texts)+1<=256
    from ready2go_voice.core.recovery_confirmation import _particle
    for item in ontology['world']['items'].values():
        name=item['name_ko']
        assert prompts(cfg)['recorded_held'].format(item=name,item_topic=_particle(name,'은','는')) in texts
    assert control_notice(cfg,'end',runtime=True) in texts
    assert control_notice(cfg,'failed',runtime=True,operation='recover',reason='B_RECOVER_UNAVAILABLE') in texts
    assert cfg['tts_melotts_startup_timeout_sec']==60.


@pytest.mark.parametrize('order',['state-first','status-first'])
@pytest.mark.parametrize('transition',['first','restart','loss'])
def test_memory_callback_order_after_first_restart_and_loss(node,order,transition):
    endpoints,status,state,subscriptions=memory_node(node)
    if transition!='first':
        status();state()
        if transition=='loss':
            selected=endpoints['/runner/status']
            endpoints['/runner/status']=[]
            assert node._runner_memory_state() is None
            endpoints['/runner/status']=selected
        else:
            for topic in endpoints:
                endpoints[topic][0]=SimpleNamespace(**dict(endpoints[topic][0].__dict__,
                    endpoint_gid=bytes([17 if topic=='/runner/status' else 19]*24)))
    packet=copy.deepcopy(node.parser.reference_state)
    packet['located_in']['eraser']='handover_zone'
    seq=2 if transition=='loss' else 1
    boot='new-boot' if transition=='restart' else 'boot'
    if order=='state-first':
        state(packet,stamp=31)
        assert node._runner_memory_state() is None
        status(seq=seq,boot=boot,stamp=30)
    else:
        status(seq=seq,boot=boot,stamp=30)
        assert node._runner_memory_state() is None
        state(packet,stamp=31)
    assert '전달 트레이' in answer(node,'지우개 어딨어?')
    assert not node.published


def test_same_boot_loss_rereads_current_latched_record_and_retires_old_reader(node):
    endpoints,status,state,subscriptions=memory_node(node)
    status();state(stamp=11)
    old_callback=subscriptions[-1][1]
    selected=endpoints['/runner/status']
    endpoints['/runner/status']=[]
    assert node._runner_memory_state() is None
    endpoints['/runner/status']=selected
    status(seq=2,stamp=30)
    assert len(subscriptions)==2
    assert node._runner_memory_state() is None  # no local cache restoration
    packet=copy.deepcopy(node.parser.reference_state)
    packet['located_in']['eraser']='handover_zone'
    # Publication 20 happened during loss, before the recovery status. The
    # recreated TRANSIENT_LOCAL reader receives it without C republishing.
    old_callback(SimpleNamespace(data=json.dumps(packet)),dict(INFO,source_timestamp=40))
    assert node._runner_memory_state() is None
    subscriptions[-1][1](SimpleNamespace(data=json.dumps(packet)),dict(INFO,source_timestamp=20))
    assert '전달 트레이' in answer(node,'지우개 어딨어?')
    # Also rereceive an unchanged record with the same source stamp after loss.
    endpoints['/runner/status']=[];assert node._runner_memory_state() is None
    endpoints['/runner/status']=selected;status(seq=3,stamp=50)
    assert node._runner_memory_state() is None
    subscriptions[-1][1](SimpleNamespace(data=json.dumps(packet)),dict(INFO,source_timestamp=20))
    assert node._runner_memory_state()['located_in']['eraser']=='handover_zone'


@pytest.mark.parametrize('reader_failure',['destroy','create'])
def test_memory_reader_recreation_failure_stays_unknown(node,reader_failure):
    endpoints,status,state,_=memory_node(node);status();state()
    selected=endpoints['/runner/status'];endpoints['/runner/status']=[]
    assert node._runner_memory_state() is None
    endpoints['/runner/status']=selected
    if reader_failure=='destroy':node.destroy_subscription=lambda subscription:False
    else:
        def fail(*a,**kw):raise RuntimeError('reader unavailable')
        node.create_subscription=fail
    status(seq=2,stamp=30)
    assert node._runner_memory_state() is None and not node.published


def test_restart_rejects_old_latched_record_and_retired_boot(node):
    endpoints,status,state,subscriptions=memory_node(node);status();state(stamp=11)
    old_callback=subscriptions[-1][1]
    for topic in endpoints:
        endpoints[topic][0]=SimpleNamespace(**dict(endpoints[topic][0].__dict__,endpoint_gid=bytes([17]*24)))
    status(boot='new-boot',stamp=30)
    old_callback(SimpleNamespace(data=json.dumps(node.parser.reference_state)),dict(INFO,source_timestamp=40))
    assert node._runner_memory_state() is None
    state(stamp=11);assert node._runner_memory_state() is None
    state(stamp=31);assert node._runner_memory_state() is not None
    status(seq=2,boot='boot',stamp=40)
    assert node.runner_control_source.binding.boot=='new-boot'


def test_actual_pick_place_effect_and_held_stop_support_readonly_queries(node,ontology):
    from ready2go_knowledge.core.ontology import apply
    _,status,state,_=memory_node(node);status();state()
    assert '아래 서랍' in answer(node,'지우개 어딨어?')
    held,_=apply(ontology['state'],ontology['skills']['pick']['effect'],
                 {'item':'eraser','from':'drawer_bottom'})
    assert held['located_in']['eraser']=='gripper'
    assert 'gripper' not in node.parser.places
    state(held,stamp=12)
    assert '그리퍼에 쥐고' in answer(node,'지우개 어딨어?')
    assert node.texts[-1]=='지우개는 그리퍼에 쥐고 있습니다.'
    assert '서랍에 있습니다.' in answer(node,'차키 어딨어?')
    assert '닫혀있습니다' in answer(node,'위쪽 서랍 열려있어?')
    # A held stop preserves the actual effect state; it does not grant motion.
    node._runner_status_with_info(SimpleNamespace(data=json.dumps(dict(boot_id='boot',seq=2,
        phase='halted',halt_code='HALTED',halt=None,last=None,task_id=None))),dict(INFO,source_timestamp=13))
    doc=node.session.text('지우개 어딨어?',node.generation)
    assert '그리퍼에 쥐고' in doc['_voice']['final_text']
    assert doc['_voice']['readonly_query'] and not doc['source']['execution_allowed']
    # Existing halted-state notice/TTS cancellation still has priority.
    placed,_=apply(held,ontology['skills']['place']['effect'],{'item':'eraser','to':'handover_zone'})
    state(placed,stamp=14)
    doc=node.session.text('지우개 어딨어?',node.generation)
    assert '전달 트레이' in doc['_voice']['final_text']
    assert not node.published


@pytest.mark.parametrize('predicate,key,value',[
    ('located_in','eraser','invented_place'),('located_in','unregistered','gripper'),
    ('open','gripper',True),('open','drawer_top',1)])
def test_held_support_keeps_unknown_keys_locations_and_open_types_rejected(node,predicate,key,value):
    _,status,state,_=memory_node(node);status();state()
    packet=copy.deepcopy(node.parser.reference_state)
    packet[predicate][key]=value;state(packet,stamp=12)
    assert node._runner_memory_state() is None and not node.published



def test_same_boot_reader_replay_needs_valid_status_order_metadata(node):
    endpoints,status,state,subscriptions=memory_node(node);status();state(stamp=11)
    selected=endpoints['/runner/status'];endpoints['/runner/status']=[]
    assert node._runner_memory_state() is None
    endpoints['/runner/status']=selected
    status(seq=2,stamp=None)
    subscriptions[-1][1](SimpleNamespace(data=json.dumps(node.parser.reference_state)),dict(INFO,source_timestamp=11))
    assert node._runner_memory_state() is None



def test_initial_status_before_state_endpoint_discovery_accepts_first_state(node):
    endpoints,status,state,_=memory_node(node)
    selected=endpoints['/robot_state'];endpoints['/robot_state']=[]
    status();assert node._runner_memory_state() is None
    endpoints['/robot_state']=selected;state(stamp=11)
    assert '아래 서랍' in answer(node,'지우개 어딨어?')
