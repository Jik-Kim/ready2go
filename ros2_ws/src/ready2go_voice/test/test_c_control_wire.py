"""Actual C core/router/node bodies -> E Node/Session. ROS/SDK/PCM are mocks.

Publisher metadata has the actual Jazzy four-key dict shape. The graph endpoint
is a connection identity, never a fabricated per-sample GID or B safety proof.
"""
import ast
import __future__
import importlib.util
import json
import os
import sys
from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace
import pytest
from ready2go_runner.core import intent_router
from ready2go_runner.core.backend import RosBackend
from ready2go_runner.core.interpreter import Runner, ResumeRejected, ActionResult
from ready2go_runner.core.logstore import MemoryLogStore
from ready2go_runner.core.log_records import new_run_id, utc_iso
from ready2go_runner.core.request_memory import RequestMemory
from ready2go_runner.core.recovery import MOCK_LIMITS, mock_check, recover_blockers, parse_check
from ready2go_runner.core.resume_admission import ResumeAdmission, load_limits
from ready2go_runner.core.runner_status import build_status
from ready2go_runner.core.start_gate import StartGate, STARTED, CANCELED_BEFORE_START, BUSY
from ready2go_voice.core.safety_exchange import IndependentRegistration
from ready2go_voice.core.recovery_confirmation import RunnerOffer, TaskEndCandidate
from ready2go_voice.adapters.audio import Recording
from test_voice_ux_node import node, node_class

ROOT=Path(__file__).resolve().parents[4]
C_PACKAGE=ROOT/'ros2_ws/src/ready2go_runner'
INFO=dict(source_timestamp=1,received_timestamp=2,publication_sequence_number=1,reception_sequence_number=1)


def tasks_module():
    spec=importlib.util.spec_from_file_location('_wire_c_tasks',C_PACKAGE/'test/test_tasks.py')
    module=importlib.util.module_from_spec(spec)
    sys.path.insert(0,str(C_PACKAGE/'test'))  # C #323's real independent fixture import
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(C_PACKAGE/'test'))
    return module


def controller_class(started):
    source=C_PACKAGE/'ready2go_runner/nodes/runner_node.py'
    tree=ast.parse(source.read_text())
    constants={}
    for item in tree.body:
        if isinstance(item,ast.Assign):
            try:value=ast.literal_eval(item.value)
            except (ValueError,TypeError):continue
            for target in item.targets:
                if isinstance(target,ast.Name):constants[target.id]=value
                elif isinstance(target,ast.Tuple):constants.update(zip([t.id for t in target.elts],value))
    tree.body=[item for item in tree.body if isinstance(item,ast.ClassDef) and item.name=='RunnerNode']
    namespace=dict(Node=object,json=json,os=os,intent_router=intent_router,StartGate=StartGate,
        STARTED=STARTED,CANCELED_BEFORE_START=CANCELED_BEFORE_START,GATE_BUSY=BUSY,
        ResumeRejected=ResumeRejected,MOCK_LIMITS=MOCK_LIMITS,mock_check=mock_check,
        recover_blockers=recover_blockers,new_run_id=new_run_id,utc_iso=utc_iso,
        build_status=build_status,String=SimpleNamespace,
        parse_check=parse_check, Trigger=SimpleNamespace(Request=SimpleNamespace),
        threading=SimpleNamespace(Event=threading.Event, Thread=lambda **kw:SimpleNamespace(start=lambda:started.append(kw))))
    namespace.update(constants)
    exec(compile(tree,str(source),'exec',flags=__future__.annotations.compiler_flag),namespace)
    return namespace['RunnerNode']


class Wire:
    def __init__(self,node, *, suspended=True):
        self.e=node;node.cfg.update(request_run_enabled=True,audio_enabled=True)
        node.now[0]=0.;self.out=queue.Queue();self.to_e=queue.Queue();self.started=[]
        self.endpoint=SimpleNamespace(node_name='runner',node_namespace='/',
            topic_type='std_msgs/msg/String',endpoint_gid=bytes([7]*24))
        self.endpoints=[self.endpoint]
        node.get_publishers_info_by_topic=lambda topic:list(self.endpoints)
        node.declare_parameter=lambda name,default:SimpleNamespace(value=default)
        node.status_subscription=SimpleNamespace(topic_name='/runner/status')
        node.runner_control_source=None;node._runtime_control_check=None;node._control_binding=None
        node._control_source_lost=False
        node._init_runner_control_source() # exact runtime initialization called by __init__
        node._publish=lambda doc:self.out.put(json.loads(json.dumps(doc)))
        module=tasks_module();robot=module.MockRobot(fail={'pick_object':['ESTOP']} if suspended else {})
        store=MemoryLogStore()
        runner=Runner(None,schema=module.SCHEMA,ontology=module.ONTOLOGY,log_store=store,
            resumable=True,clock=lambda:node.now[0]+5000.)
        runner.execute=RosBackend(robot.call_action,robot.call_service,lambda:runner.state,module.ONTOLOGY['world'])
        result=runner.run(module.TASK) if suspended else None
        limits=load_limits(str(C_PACKAGE/'params/resume.yaml'),str(ROOT/'ros2_ws/src/ready2go_voice/params/voice.yaml'))
        runner.admission=ResumeAdmission(limits=limits,clock=lambda:node.now[0]+5000.)
        klass=controller_class(self.started);c=klass.__new__(klass)
        c.__dict__.update(runner=runner,log_store=store,gate=StartGate(),requests=RequestMemory(),
            _lock=threading.RLock(),_pub_lock=threading.RLock(),_last=result,
            _last_task_id='find_item' if suspended else None,_task_id=None,_end_requested=None,
            _last_intent=None,_state_reset_at=None,_seq=0,_sent={'status':None,'state':None},recover_check='mock',
            recover_call_b=False)   # C #316: W2 호출 여부 — mock 조회에서는 쓰지 않음
        c.intents=intent_router.IntentRouter(json.loads((ROOT/'contracts/intent.schema.json').read_text()),
            {'find_item':module.TASK},module.ONTOLOGY['world']['items'],0.65)
        c.get_logger=lambda:SimpleNamespace(info=lambda *a,**k:None,warning=lambda *a,**k:None,error=lambda *a,**k:None)
        c.missing_servers=lambda task:[]
        c.status_pub=SimpleNamespace(publish=lambda msg:self.to_e.put(msg))
        c.state_pub=SimpleNamespace(publish=lambda msg:None)
        self.c=c;self.sent=[];self.tts=[];self.pcm_mock=True
        self.status_packets=[]
        def status_publish(msg):
            self.status_packets.append(msg.data);self.to_e.put(msg)
        c.status_pub=SimpleNamespace(publish=status_publish)
        node.place_test_devices=True
        def playback(text,*,on_start=None,on_timing=None,**kwargs):
            self.tts.append(text)
            stamp=dict(tts_started_monotonic=node.now[0],tts_start_basis='portaudio_first_dac',tts_mock=self.pcm_mock)
            if on_start:on_start(stamp)
            node.now[0]+=.2
            if on_timing:on_timing(dict(playback_ended_monotonic=node.now[0],playback_end_basis='portaudio_finished_callback'))
            return stamp
        node._say=playback
        c.publish();self.flush()

    def flush(self):
        while not self.out.empty() or not self.to_e.empty():
            while not self.out.empty():
                doc=self.out.get();self.sent.append(doc)
                self.c._on_intent(SimpleNamespace(data=json.dumps(doc)))
            while not self.to_e.empty():
                self.e._runner_status_with_info(self.to_e.get(),dict(INFO))

    def recording(self,text):
        node=self.e
        class STT:
            supports_request_boundary=True
            def transcribe(self,path,timeout,*,before_request):
                node.now[0]+=.05
                assert before_request(node.now[0])
                node.now[0]+=.2
                return text
        node.session.stt=STT()
        def capture(cancel,paused):
            start=node.now[0]+.1;end=start+.5;node.now[0]=end
            return Recording(b'\x01\x00'*1280,end,123.,recording_started_monotonic=start,
                recording_ended_monotonic=end)
        node.place_recorder=SimpleNamespace(capture=capture)

    def independent(self,text):
        self.recording(text);node=self.e;ex=node.safety_exchange
        target=ex.begin_independent(now=node.now[0],unique_target=True)
        node.safety_cancel=threading.Event()
        recording=node.place_recorder.capture(node.safety_cancel,lambda:False)
        result=node.session.safety_audio(ex,target,recording)
        node._safety_result_locked(result,node.safety_cancel,node.safety_sender)
        self.flush()
        return result

    def question(self,text):
        node=self.e;ex=node.safety_exchange;q=ex.policy.question
        assert q is not None and isinstance(ex.evidence,RunnerOffer)
        assert not self.tts and ex.policy.registered_at is None
        self.recording(text)
        original=node._release_safety_locked
        def release(cancel):
            original(cancel);node.stop_event.set()
        node._release_safety_locked=release
        worker=threading.Thread(target=node._safety_work)
        worker.start()
        registration=self.out.get(timeout=2)
        assert registration['intent']=='resume_register' and not self.tts
        assert ex.policy.registered_at is None
        self.sent.append(registration)
        self.c._on_intent(SimpleNamespace(data=json.dumps(registration)))
        while not self.to_e.empty():
            self.e._runner_status_with_info(self.to_e.get(),dict(INFO))
        worker.join(timeout=3)
        assert not worker.is_alive(), node.diagnostics[-3:]
        node.stop_event.clear();node._release_safety_locked=original
        self.flush()
        return q


@pytest.mark.parametrize('answer',['응','아니요'])
def test_c_recovery_registration_question_and_final_decision(node,monkeypatch,answer):
    monkeypatch.setenv('BACKEND','mock');wire=Wire(node)
    assert node._request_run_connected() and node.control_mapper is not None
    wire.independent('복구해')
    work=node.safety_exchange.policy.work
    assert wire.c.runner.resume_offer['offered'] and node.safety_exchange.policy.question
    q=wire.question(answer)
    intents=[d['intent'] for d in wire.sent]
    assert intents==['recover','resume_register','resume_answer']
    final=wire.sent[-1]
    assert final['question_id']==q.question_id and final['request_id']
    assert wire.c._last_intent['request_id']==final['request_id']
    if answer=='응':
        assert wire.c._last_intent['decision']=='resume' and wire.c.runner.halt_summary is None
        assert node.safety_exchange.policy.work is None and node.pending_resume is None
        assert node.pending_notice.kind=='control_resume'
    else:
        assert wire.c._last_intent['decision']=='closed'
        assert node.safety_exchange.policy.work==work
        wire.independent('재개해')
        assert [d.get('phase') for d in wire.sent[-2:]]==['register','request']
        assert wire.c._last_intent['decision']=='resume' and node.safety_exchange.policy.work is None
    assert len(wire.tts)==1 # registered question PCM, not fabricated B evidence


def test_locked_end_uses_actual_c_disposal_without_resume_registration(node,monkeypatch):
    monkeypatch.setenv('BACKEND','mock');wire=Wire(node)
    work=node.safety_exchange.policy.work
    result=wire.independent('종료해')
    assert isinstance(result,TaskEndCandidate)
    assert [d['intent'] for d in wire.sent]==['end_task']
    assert wire.c._last_intent['decision']=='end' and wire.c.runner.halted
    assert node.safety_exchange.policy.work==work
    token=node.control_feedback
    assert token and token['kind']=='end'
    node._safety_feedback_play(token,node.safety_cancel,node.safety_sender)
    assert node.safety_exchange.policy.work is None and wire.c.runner.halted


def test_general_request_acceptance_and_first_speech_share_runtime_source(node,monkeypatch):
    monkeypatch.setenv('BACKEND','mock');wire=Wire(node,suspended=False)
    assert node._request_run_connected() and node.control_mapper.status['phase']=='idle'
    doc=node.session.text('지우개 찾아줘',node.generation)
    node.deliver(doc);assert wire.out.qsize()==1 and not wire.tts
    wire.flush()
    sent=wire.sent[-1]
    assert sent['intent']=='find_item' and node.request_run.run_id==wire.c._last_intent['run_id']
    request=SimpleNamespace(params_json=json.dumps({'text':sent['accept_text']}))
    assert node._goal(request)==1
    calls=[]
    goal=SimpleNamespace(request=request,is_cancel_requested=False,abort=lambda:calls.append('abort'),
        succeed=lambda:calls.append('success'),canceled=lambda:calls.append('cancel'))
    wire.pcm_mock=False # injected PCM proof shape; no device, not a physical test
    result=node._speak(goal)
    assert result.success is True and calls==['success']
    assert wire.tts==[sent['accept_text']]
    assert node._goal(request)==0


def test_source_loss_invalidates_generation_and_rejects_old_boot_seq(node,monkeypatch):
    monkeypatch.setenv('BACKEND','mock');wire=Wire(node)
    generation=node.generation;work=node.safety_exchange.policy.work
    wire.endpoints=[]
    assert not node._request_run_connected() and node.generation>generation
    wire.endpoints=[wire.endpoint]
    assert not node._request_run_connected() # cannot revive without new current status
    wire.c._sent['status']=None;wire.c.publish();wire.flush()
    assert node._request_run_connected() and node.safety_exchange.policy.work==work
    seq=node.control_mapper.seq;current=node.generation
    old=wire.c.status();old['seq']=seq-1
    node._runner_status_with_info(SimpleNamespace(data=json.dumps(old)),dict(INFO))
    assert node.generation==current and node.control_mapper.seq==seq
    wire.endpoints=[wire.endpoint,wire.endpoint]
    assert not node._request_run_connected()



def test_actual_c_registration_reject_closes_question_but_keeps_work(node,monkeypatch):
    monkeypatch.setenv('BACKEND','mock');wire=Wire(node);wire.independent('복구해')
    work=node.safety_exchange.policy.work;q=node.safety_exchange.policy.question
    node.now[0]=wire.c.runner.resume_window_sec+1. # C actual offer expired
    node.safety_sender('register_question',q);wire.flush()
    assert wire.c._last_intent['decision']=='reject' and not wire.tts
    assert node.safety_exchange.policy.work==work and node.safety_exchange.policy.question is None
    wire.independent('재개해')
    assert wire.c._last_intent['decision']=='resume' and node.safety_exchange.policy.work is None


def test_actual_c_final_reject_is_consumed_once_without_normalizing_unknown(node,monkeypatch):
    monkeypatch.setenv('BACKEND','mock');wire=Wire(node);wire.independent('복구해');wire.question('아니요')
    work=node.safety_exchange.policy.work
    wire.c.recover_check='none' # actual C missing B check -> reject, no fabricated E proof
    wire.independent('재개해')
    assert wire.c._last_intent['decision']=='reject' and not wire.started
    assert node.safety_exchange.policy.work==work and node.pending_resume is None
    decisions=len([d for d in node.diagnostics if d.get('event')=='control_decision'])
    wire.c._sent['status']=None;wire.c.publish();wire.flush()
    assert len([d for d in node.diagnostics if d.get('event')=='control_decision'])==decisions
    assert node.safety_exchange.begin_independent(now=node.now[0],unique_target=True)


def test_actual_c_other_question_id_cannot_register_current_e_question(node,monkeypatch):
    monkeypatch.setenv('BACKEND','mock');wire=Wire(node);wire.independent('복구해')
    q=node.safety_exchange.policy.question;work=q.work
    foreign=dict(intent='resume_register',confidence=1.,boot_id=work.session,event_id=work.stop,
        run_id=work.task,question_id='other-question',request_id='other-registration')
    wire.c._on_intent(SimpleNamespace(data=json.dumps(foreign)));wire.flush()
    assert node.safety_exchange.policy.registered_at is None and not wire.tts
    node.safety_sender('register_question',q);wire.flush()
    assert wire.c._last_intent['decision']=='reject' and not wire.tts
    assert node.safety_exchange.policy.work==work


def test_real_c_new_boot_invalidates_old_question_and_old_boot_does_not_cancel_new(node,monkeypatch):
    monkeypatch.setenv('BACKEND','mock');wire=Wire(node);wire.independent('복구해')
    q=node.safety_exchange.policy.question;old_packet=wire.status_packets[-1];generation=node.generation
    module=tasks_module()
    wire.c.runner=Runner(None,schema=module.SCHEMA,ontology=module.ONTOLOGY,log_store=MemoryLogStore(),
        resumable=True,clock=lambda:node.now[0]+7000.)
    wire.c._last=None;wire.c._last_intent=None;wire.c._task_id=None;wire.c._last_task_id=None
    wire.endpoint=SimpleNamespace(node_name='runner',node_namespace='/',topic_type='std_msgs/msg/String',endpoint_gid=bytes([8]*24))
    wire.endpoints=[wire.endpoint];wire.c.publish();wire.flush()
    assert node.generation>generation and not node.safety_exchange.current(q)
    assert node._request_run_connected() and node.safety_exchange.policy.work is None
    current=node.generation
    node._runner_status_with_info(SimpleNamespace(data=old_packet),dict(INFO))
    assert node.generation==current and node._request_run_connected()


def test_source_loss_discards_late_actual_sdk_result(node,monkeypatch):
    monkeypatch.setenv('BACKEND','mock');wire=Wire(node);ex=node.safety_exchange
    target=ex.begin_independent(now=node.now[0],unique_target=True);generation=node.generation
    class STT:
        supports_request_boundary=True
        def transcribe(self,path,timeout,*,before_request):
            assert before_request(node.now[0])
            wire.endpoints=[];assert not node._request_run_connected()
            wire.endpoints=[wire.endpoint]
            return '재개해' # a restored graph cannot revive this older capture
    node.session.stt=STT()
    start=node.now[0]+.1;end=start+.5;node.now[0]=end
    recording=Recording(b'\x01\x00'*1280,end,123.,recording_started_monotonic=start,recording_ended_monotonic=end)
    assert node.session.safety_audio(ex,target,recording) is None
    assert node.generation>generation and not wire.sent and ex.policy.work is not None


def test_opt_in_off_and_evaluation_do_not_install_runtime_or_publish(node):
    node.cfg['request_run_enabled']=False;node._init_runner_control_source()
    assert node.runner_control_source is not None and getattr(node,'control_mapper',None) is None and not node.published
    node.cfg.update(request_run_enabled=True,evaluation_mode=True);node._init_runner_control_source()
    assert node.runner_control_source is not None and getattr(node,'control_mapper',None) is None and not node.published



@pytest.mark.parametrize('backend_code,completed,followup',[
    ('CANCELED',True,'reset'),('STOP_UNCONFIRMED',False,'reset'),
    ('STOP_UNCONFIRMED',False,'restop'),('STOP_UNCONFIRMED',False,'restart')])
def test_active_running_voice_end_is_direct_and_waits_for_actual_c_stop(node,monkeypatch,backend_code,completed,followup):
    monkeypatch.setenv('BACKEND','mock');wire=Wire(node,suspended=False)
    doc=node.session.text('지우개 찾아줘',node.generation);node.deliver(doc);wire.flush()
    target=node.request_run.run_id
    # First acceptance speech uses the existing correlated E goal path.
    request=SimpleNamespace(params_json=json.dumps({'text':wire.sent[0]['accept_text']}))
    assert node._goal(request)==1
    goal=SimpleNamespace(request=request,is_cancel_requested=False,abort=lambda:None,succeed=lambda:None,canceled=lambda:None)
    wire.pcm_mock=False
    assert node._speak(goal).success is True
    entered=threading.Event();released=threading.Event()
    original=wire.c.runner.execute
    def backend(action,params,timeout_sec=None):
        if action=='pick_object':
            entered.set();assert released.wait(3)
            return ActionResult(success=False,error_code=backend_code)
        return original(action,params,timeout_sec)
    wire.c.runner.execute=backend
    wire.c.runner.on_halt=lambda:1 # mock active goal cancellation count, not stop confirmation
    task=wire.started[-1]
    execution=threading.Thread(target=task['target'],args=task['args']);execution.start()
    assert entered.wait(2)
    wire.c.publish();wire.flush()
    assert wire.c.runner.active_run_id==target and node.notice_policy.phase=='running'
    wire.recording('종료해')
    recording=node.place_recorder.capture(threading.Event(),lambda:False)
    end_doc=node.session.stop_audio(recording)
    assert end_doc['_voice']['safety_control']=='task_end'
    node._stop_locked(end_doc,node.generation)
    end=wire.out.get(timeout=1);wire.sent.append(end)
    assert end['intent']=='end_task' and end['run_id']==target and 'event_id' not in end
    assert [d['intent'] for d in wire.sent]==['find_item','end_task'] # no cancel-first detour
    wire.c._on_intent(SimpleNamespace(data=json.dumps(end)));wire.flush()
    assert wire.c.runner.halt_summary['stop']=='requested' and wire.c.runner.halted
    assert node.pending_task_end is not None
    assert not any(d.get('event')=='task_end_accepted' for d in node.diagnostics)
    released.set();execution.join(timeout=3);assert not execution.is_alive();wire.flush()
    assert wire.c.runner.halted
    if completed:
        assert wire.c.runner.halt_summary['stop']=='confirmed' and wire.c.runner.suspended is None
        assert node.pending_task_end is None
        assert any(d.get('event')=='task_end_accepted' for d in node.diagnostics)
    else:
        assert wire.c.runner.halt_summary['stop']=='unconfirmed' and wire.c.runner.suspended is not None
        assert node.pending_task_end is None and node.deferred_task_end is not None
        assert not any(d.get('event')=='task_end_accepted' for d in node.diagnostics)
        marker=node.deferred_task_end
        old_packet=wire.status_packets[-1]
        wire.c._sent['status']=None;wire.c.publish();wire.flush()
        assert node.deferred_task_end==marker
        assert len([d for d in node.diagnostics if d.get('event')=='task_end_deferred'])==1
        retry=dict(end,request_id='new-end-retry',event_id=wire.c.runner.halt_summary['event_id'])
        wire.c._on_intent(SimpleNamespace(data=json.dumps(retry)));wire.flush()
        assert wire.c._last_intent['reason']=='STOP_NOT_CONFIRMED'
        assert node.deferred_task_end is not None and wire.c.runner.suspended is not None
        assert not any(d.get('event')=='task_end_accepted' for d in node.diagnostics)
        node._runner_status_with_info(SimpleNamespace(data=old_packet),dict(INFO))
        assert node.deferred_task_end is not None
        if followup=='restop':
            wire.c._on_intent(SimpleNamespace(data=json.dumps(dict(intent='cancel',confidence=1.,targets=[]))));wire.flush()
            assert node.deferred_task_end is None and wire.c.runner.halted
            assert wire.c.runner.suspended is not None and node.notice_policy.blocked
            assert not any(d.get('event')=='task_end_accepted' for d in node.diagnostics)
            return
        if followup=='restart':
            module=tasks_module()
            wire.c.runner=Runner(None,schema=module.SCHEMA,ontology=module.ONTOLOGY,
                log_store=MemoryLogStore(),resumable=True,clock=lambda:node.now[0]+5000.)
            wire.c._last=None;wire.c._last_intent=None;wire.c._task_id=None;wire.c._last_task_id=None
            wire.c._state_reset_at=None
            wire.endpoints=[SimpleNamespace(**dict(wire.endpoint.__dict__,endpoint_gid=bytes([8]*24)))]
            wire.c.publish();wire.flush()
            assert node.deferred_task_end is None
            generation=node.generation
            node._runner_status_with_info(SimpleNamespace(data=old_packet),dict(INFO))
            assert node.generation==generation and node.deferred_task_end is None
            assert not any(d.get('event')=='task_end_accepted' for d in node.diagnostics)
            return
        # Actual C human/reset disposal preserves the physical stop/lock warning.
        response=wire.c._reset_state(SimpleNamespace(),SimpleNamespace());wire.flush()
        assert response.success and wire.c.runner.suspended is None and wire.c.runner.halted
        assert node.pending_task_end is None and node.deferred_task_end is None
        assert node.notice_policy.phase=='halted' and node.notice_policy.blocked
        assert not any(d.get('event')=='task_end_accepted' for d in node.diagnostics)
        assert any(d.get('event')=='task_end_discarded' for d in node.diagnostics)
