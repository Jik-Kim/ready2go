"""E mapping with explicit mock schema/source/typed observations; no C/ROS proof."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
import pytest
from jsonschema import Draft7Validator
from ready2go_voice.core.control_mapping import ControlMapper, SafetyProof
from ready2go_voice.core.recovery_confirmation import Evidence, StoppedWork, TaskEndCandidate, RunnerOffer
from ready2go_voice.core.safety_exchange import SafetyExchange, IndependentRegistration
from test_voice_ux_node import node, node_class

WORK = StoppedWork('boot','event','run','step','HALTED')
MOCK_SAFE = Evidence(True,True,True,True,True)
GID = bytes([1]*16)
# Test-only declarations of the five names; product schema comes from contracts/.
MOCK_SCHEMA = {'type':'object','required':['intent','confidence','boot_id'],
    'properties':{'intent':{'enum':['recover','end_task','resume_register','resume_answer','resume']}}}


def status(seq=1, *, offered=False, locked=False, question=None, request=None):
    return dict(boot_id='boot', seq=seq, phase='idle', task_id=None, halt_code=None,
        last=dict(run_id='run',overall_status='SUSPENDED',failed_step='step'), last_intent=None,
        halt=dict(boot_id='boot', event_id='event',run_id='run',code='HALTED',stop='confirmed',locked=locked,
            resume=dict(offered=offered,from_step='step',needs='empty',question=question,request=request)))


def wire(node, *, provider=True):
    node.cfg.update(request_run_enabled=True)
    node.now[0]=0.
    node.parser.validator=Draft7Validator(MOCK_SCHEMA)
    proof = (lambda doc,work,now:SafetyProof(work,doc['seq'],MOCK_SAFE,100.)) if provider else None
    mapper=node.bind_control_source(lambda:True,boot='boot',publisher_gid=GID,proof_provider=proof)
    def receive(doc,gid=GID):
        node._runner_status_with_info(SimpleNamespace(data=json.dumps(doc)),dict(source_timestamp=1,received_timestamp=2,publication_sequence_number=1,reception_sequence_number=1))
    return mapper,receive


def independent(node,mapper, *, text='이어서 해', result_at=18., classified_at=29.):
    ex=node.safety_exchange
    target=ex.begin_independent(now=0.,unique_target=True)
    receipt=ex.admit(target,ex.reserve(target),captured_at=0.,ended_at=2.,started_at=3.)
    node.now[0]=classified_at
    result=ex.answer(target,text,captured_at=0.,now=classified_at,request=receipt,result_at=result_at)
    assert isinstance(result,IndependentRegistration)
    node.safety_cancel.clear() # simulate the newly owned recording worker
    node._safety_result_locked(result,node.safety_cancel,node.safety_sender)
    return target


def test_installed_schema_allows_current_recover_without_changing_normal_opt_in(node):
    node.cfg['request_run_enabled']=True
    node.bind_control_source(lambda:True,boot='boot',publisher_gid=GID)
    node._runner_status_with_info(SimpleNamespace(data=json.dumps(status())),dict(source_timestamp=1,received_timestamp=2,publication_sequence_number=1,reception_sequence_number=1))
    assert node.safety_exchange.policy.work==WORK
    assert node.safety_sender('recover',WORK)
    assert node.published[-1]['intent']=='recover'
    node.parser.validator.validate(node.published[-1])


def test_proposal_needs_no_extra_provider_but_registration_precedes_tts(node):
    mapper,receive=wire(node,provider=False)
    receive(status(offered=True))
    assert node.safety_exchange.policy.work==WORK
    assert isinstance(node.safety_exchange.evidence,RunnerOffer)
    assert node.safety_exchange.policy.question is not None and not node.texts
    assert node.safety_exchange.policy.registered_at is None
    assert not mapper.accept(json.dumps(status(2,offered=True)),bytes([2]*16))
    assert mapper.seq==1
    node.cfg['request_run_enabled']=False
    receive(status(2,offered=True))
    assert not node.safety_exchange.policy.current_state_confirmed and not node.published


def test_verified_question_registration_echo_preserves_same_event_and_receipt(node):
    mapper,receive=wire(node)
    receive(status(offered=True))
    ex=node.safety_exchange;q=ex.policy.question
    assert q and q.question_id and not node.texts
    assert node.safety_sender('register_question',q)
    doc=node.published[-1]
    assert doc['request_id']
    assert {k:v for k,v in doc.items() if k!='request_id'}==dict(intent='resume_register',confidence=1.,boot_id='boot',event_id='event',run_id='run',question_id=q.question_id)
    receive(status(2,offered=True,question={'id':'other','state':'registered'}))
    assert ex.policy.registered_at is None and ex.current(q)
    node.now[0]=1.
    receive(status(3,offered=True,question={'id':q.question_id,'state':'registered'}))
    assert ex.policy.registered_at==1. and ex.current(q)
    assert ex.tts_started(q,now=2.) and ex.delivered(q,now=3.,success=True)
    receipt=ex.admit(q,ex.reserve(q),captured_at=4.,ended_at=5.,started_at=13.) # exactly TTS+10
    node.now[0]=29.
    result=ex.answer(q,'재개해',captured_at=4.,now=29.,request=receipt,result_at=28.) # exactly SDK+15
    assert result is WORK or result==WORK
    node._send_safety_candidate_locked(result,node.safety_sender)
    doc=node.published[-1]
    assert doc['intent']=='resume_answer' and doc['answer']=='resume'
    assert doc['evidence']==dict(rec_start_after_tts_s=1.,rec_end_after_tts_s=2.,request_after_tts_s=10.,stt_s=15.)
    assert not node.safety_sender('candidate',result)
    receive(status(2,offered=True,question={'id':q.question_id,'state':'registered'}))
    assert mapper.seq==3


@pytest.mark.parametrize('ack_at,allowed',[(30.,True),(30.000001,False)])
def test_independent_whole_30_includes_classification_ack_and_publish(node,ack_at,allowed):
    mapper,receive=wire(node);receive(status())
    target=independent(node,mapper)
    assert node.published[-1]['phase']=='register'
    node.now[0]=ack_at
    receive(status(2,request={'id':target.request_id,'state':'registered'}))
    consumed=[d for d in node.published if d.get('phase')=='request']
    assert bool(consumed)==allowed
    if allowed:
        assert consumed[0]['request_id']==target.request_id
        assert consumed[0]['evidence']==dict(rec_end_s=2.,request_s=3.,stt_s=15.)
        receive(status(3,request={'id':target.request_id,'state':'registered'}))
        assert len([d for d in node.published if d.get('phase')=='request'])==1
    assert node.safety_exchange.policy.work==WORK


def test_registration_echo_requires_current_request_and_work(node):
    mapper,receive=wire(node);receive(status());target=independent(node,mapper)
    node.now[0]=29.5
    receive(status(2,request={'id':'other','state':'registered'}))
    assert node.safety_exchange.current(target) and len(node.published)==1
    changed=status(3,request={'id':target.request_id,'state':'registered'})
    changed['halt']['event_id']='new-event'
    receive(changed)
    assert not node.safety_exchange.current(target) and len(node.published)==1


def test_last_moment_deadline_recheck_uses_immutable_normal_return(node):
    mapper,receive=wire(node);receive(status());target=independent(node,mapper)
    ex=node.safety_exchange
    candidate=ex.independent_registered(target,WORK,ex.policy.revision,now=29.5,valid_state=True,evidence=MOCK_SAFE)
    mapper.status=status(2,request={'id':target.request_id,'state':'registered'})
    node.now[0]=30.000001
    assert not mapper.send('candidate',candidate)
    assert len(node.published)==1 and ex.policy.work==WORK


def test_stt_failure_and_late_classification_cannot_register(node):
    mapper,receive=wire(node);receive(status())
    ex=node.safety_exchange;t=ex.begin_independent(now=0.,unique_target=True)
    receipt=ex.admit(t,ex.reserve(t),captured_at=0.,ended_at=2.,started_at=3.)
    assert ex.answer(t,'이어서 해',captured_at=0.,now=31.,request=receipt,result_at=18.) is None
    assert not node.published and ex.policy.work==WORK


def test_recover_and_end_do_not_require_fabricated_robot_evidence_or_unlock(node):
    mapper,receive=wire(node,provider=False);receive(status(locked=True))
    assert node.safety_sender('recover',WORK)
    recover=node.published[-1]
    assert recover['intent']=='recover' and recover['request_id']
    candidate=TaskEndCandidate(WORK)
    node._send_safety_candidate_locked(candidate,node.safety_sender)
    end=node.published[-1]
    assert end['intent']=='end_task' and end['run_id']=='run' and end['request_id']!=recover['request_id']
    ack=status(2,locked=True);ack['phase']='halted';ack['halt_code']='HALTED'
    ack['last_intent']=dict(intent='end_task',decision='end',request_id=end['request_id'])
    receive(ack) # END admission is not disposal; work remains.
    assert node.safety_exchange.policy.work==WORK and not getattr(node,'control_feedback',None)
    ack=status(3,locked=True);ack['phase']='halted';ack['halt_code']='HALTED'
    ack['halt']['resume']=None;ack['last']['overall_status']='ABORTED'
    ack['last_intent']=dict(intent='end_task',decision='end',request_id=end['request_id'])
    receive(ack)
    assert node.safety_exchange.policy.work==WORK # until actual feedback playback, never unlock/idle
    assert node.notice_policy.phase=='halted'
    token=node.control_feedback
    assert token and token['candidate'] is candidate
    node.place_test_devices=True
    def playback(text, *, on_start, on_timing, **kwargs):
        on_start(dict(tts_started_monotonic=0.,tts_start_basis='portaudio_first_dac',tts_mock=True))
        on_timing(dict(playback_ended_monotonic=0.,playback_end_basis='portaudio_finished_callback'))
    node._say=playback
    node._safety_feedback_play(token,node.safety_cancel,node.safety_sender)
    assert node.safety_exchange.policy.work is None
    assert node.notice_policy.phase=='halted' and mapper.status['halt']['locked'] is True


def test_new_boot_or_newer_malformed_status_cancels_current_capture(node):
    mapper,receive=wire(node);receive(status());target=independent(node,mapper)
    malformed=status(2);malformed['halt']['locked']='false'
    receive(malformed)
    assert not node.safety_exchange.policy.current_state_confirmed
    receive(status(1)) # lower seq cannot revive
    assert not node.safety_exchange.policy.current_state_confirmed
    reboot=status(3);reboot['boot_id']='new-boot'
    receive(reboot)
    assert mapper.reason=='producer_boot_changed' and len(node.published)==1


@pytest.mark.parametrize('answer',['아니요','expired'])
def test_decline_or_failure_closes_only_registered_question_and_preserves_work(node,answer):
    mapper,receive=wire(node);receive(status(offered=True))
    ex=node.safety_exchange;q=ex.policy.question
    assert node.safety_sender('register_question',q)
    node.now[0]=1.
    receive(status(2,offered=True,question={'id':q.question_id,'state':'registered'}))
    if answer=='expired':
        ex.fail(q)
        assert node.safety_sender('expired',q)
        doc=node.published[-1]
        assert doc['answer']=='expired' and doc['answer_reason']
    else:
        assert ex.tts_started(q,now=2.) and ex.delivered(q,now=3.,success=True)
        receipt=ex.admit(q,ex.reserve(q),captured_at=4.,ended_at=5.,started_at=6.)
        node.now[0]=7.
        result=ex.answer(q,answer,captured_at=4.,now=7.,request=receipt)
        node.safety_cancel.clear()
        node._safety_result_locked(result,node.safety_cancel,node.safety_sender)
        assert node.published[-1]['answer']=='decline'
    assert ex.policy.work==WORK
    assert not node.safety_sender('expired',q)


@pytest.mark.parametrize('defect',['wrong_work','wrong_revision','expired','unknown_conditions'])
def test_unqualified_typed_provider_cannot_bypass_gate(node,defect):
    mapper,receive=wire(node)
    def provider(doc,work,now):
        return SafetyProof(replace(work,stop='old') if defect=='wrong_work' else work,
            doc['seq']-1 if defect=='wrong_revision' else doc['seq'],
            Evidence(stopped=True) if defect=='unknown_conditions' else MOCK_SAFE,
            now if defect=='expired' else 100.)
    mapper.proof_provider=provider
    receive(status(offered=True))
    assert mapper.proof is None and node.safety_exchange.policy.question is None
    assert not node.published and not node.texts


def test_stt_exact_end_boundary_keeps_receipt_but_question_validity_stays_strict(cfg):
    ex=SafetyExchange(cfg);assert ex.stopped(WORK,1,valid_state=True,evidence=MOCK_SAFE)
    q=ex.offer(WORK,2,MOCK_SAFE,now=0.,valid_until=100.,valid_state=True)
    assert ex.registered(q,WORK,2,now=0.,valid_state=True)
    assert ex.tts_started(q,now=1.) and ex.delivered(q,now=2.,success=True)
    receipt=ex.admit(q,ex.reserve(q),captured_at=3.,ended_at=4.,started_at=12.)
    assert not ex.policy.expire(now=27.) # SDK +15 included
    assert ex.answer(q,'재개해',captured_at=3.,now=28.,result_at=27.,request=receipt)==WORK
    ex=SafetyExchange(cfg);assert ex.stopped(WORK,1,valid_state=True,evidence=MOCK_SAFE)
    q=ex.offer(WORK,2,MOCK_SAFE,now=0.,valid_until=27.,valid_state=True)
    assert ex.registered(q,WORK,2,now=0.,valid_state=True)
    assert ex.tts_started(q,now=1.) and ex.delivered(q,now=2.,success=True)
    receipt=ex.admit(q,ex.reserve(q),captured_at=3.,ended_at=4.,started_at=12.)
    assert ex.answer(q,'재개해',captured_at=3.,now=27.,result_at=27.,request=receipt) is None
    assert ex.policy.work==WORK


@pytest.mark.parametrize('stop,allowed',[('confirmed',True),('none',False),('unconfirmed',False)])
def test_stop_summary_none_is_not_backend_confirmation(node,stop,allowed):
    mapper,receive=wire(node,provider=False)
    doc=status(offered=True,locked=True);doc['halt']['stop']=stop
    receive(doc)
    assert mapper.evidence().stopped is allowed
    assert (node.safety_exchange.policy is not None and node.safety_exchange.policy.current_state_confirmed)==allowed
    assert node.safety_sender('recover',WORK) is allowed
    before=len(node.published)
    node._send_safety_candidate_locked(TaskEndCandidate(WORK),node.safety_sender)
    assert (len(node.published)>before)==allowed
    assert not node.texts and (node.safety_exchange.policy is None or node.safety_exchange.policy.question is None)


def test_none_needs_separate_current_typed_safety_proof(node):
    mapper,receive=wire(node)
    doc=status(offered=True);doc['halt']['stop']='none'
    receive(doc)
    # Explicit mock provider stands for separate observations, not stop=none.
    assert mapper.proof is not None and node.safety_exchange.policy.question is not None



def test_publish_guard_rechecks_elapsed_time_after_serialization(node,node_class):
    mapper,receive=wire(node);receive(status());target=independent(node,mapper)
    ex=node.safety_exchange
    candidate=ex.independent_registered(target,WORK,ex.policy.revision,now=29.5,valid_state=True,evidence=MOCK_SAFE)
    mapper.status=status(2,request={'id':target.request_id,'state':'registered'})
    node.now[0]=30.
    delivered=[]
    namespace=node_class._publish.__globals__
    namespace['String']=SimpleNamespace
    original_redact=namespace['redact']
    def serialization(value):
        node.now[0]=30.000001 # serialization before the actual transport boundary
        return original_redact(value)
    namespace['redact']=serialization
    node.publisher=SimpleNamespace(publish=lambda message:delivered.append(message.data))
    mapper.publish=lambda payload:node_class._publish(node,payload)
    assert not mapper.send('candidate',candidate)
    assert not delivered and ex.policy.work==WORK
    assert not mapper.send('candidate',candidate) # no replay after attempted consumption



def test_running_end_intention_survives_requested_stop_until_matching_confirmation(node):
    mapper,receive=wire(node,provider=False)
    node.notice_policy.phase='running'
    origin=dict(run='run',boot='boot',check=node.request_source_check,
        generation=node.generation,halt_seen=False)
    node.task_end_request=node.task_end_source=origin
    requested=status();requested['phase']='running';requested['task_id']='task'
    requested['halt']['stop']='requested';requested['halt']['resume']=None;requested['last']=None
    receive(requested)
    assert node.task_end_request is origin and not node.published
    confirmed=status(2,locked=True);confirmed['phase']='halted';confirmed['halt_code']='HALTED'
    receive(confirmed)
    assert [d['intent'] for d in node.published]==['end_task']
    assert node.pending_task_end[0].work==WORK
    assert node.safety_exchange.policy.work==WORK



def test_new_independent_recording_after_refusal_uses_new_uuid_and_receipt(node):
    mapper,receive=wire(node);receive(status());first=independent(node,mapper)
    node.now[0]=30.
    receive(status(2,request={'id':first.request_id,'state':'registered'}))
    receive(status(3,request={'id':first.request_id,'state':'refused'}))
    ex=node.safety_exchange
    second=ex.begin_independent(now=31.,unique_target=True)
    receipt=ex.admit(second,ex.reserve(second),captured_at=31.,ended_at=33.,started_at=34.)
    node.now[0]=35.
    result=ex.answer(second,'이어서 해',captured_at=31.,now=35.,request=receipt,result_at=35.)
    node._safety_result_locked(result,node.safety_cancel,node.safety_sender)
    node.now[0]=36.
    receive(status(4,request={'id':second.request_id,'state':'registered'}))
    consumed=[d for d in node.published if d.get('phase')=='request']
    assert [d['request_id'] for d in consumed]==[first.request_id,second.request_id]
    assert first.request_id!=second.request_id
    assert consumed[1]['evidence']==dict(rec_end_s=2.,request_s=3.,stt_s=1.)



@pytest.mark.parametrize('classified_at,allowed',[(35.,True),(35.000001,False)])
def test_actual_safety_sdk_locked_end_skips_resume_registration(node,classified_at,allowed):
    from test_safety_exchange import STT,audio
    mapper,receive=wire(node,provider=False);receive(status(locked=True))
    ex=node.safety_exchange;target=ex.begin_independent(now=0.,unique_target=True)
    node.now[0]=6.
    node.session.stt=STT('작업 종료해',node.now,hook=lambda:node.now.__setitem__(0,21.))
    original=node.parser.control
    def classify(text):
        node.now[0]=classified_at
        return original(text)
    node.parser.control=classify
    result=node.session.safety_audio(ex,target,audio())
    node.safety_cancel.clear()
    node._safety_result_locked(result,node.safety_cancel,node.safety_sender)
    assert bool(node.published)==allowed
    if allowed:
        assert isinstance(result,TaskEndCandidate)
        assert [d['intent'] for d in node.published]==['end_task']
        assert node.published[0]['boot_id']=='boot' and node.published[0]['run_id']=='run'
        assert node.pending_task_end[0] is result
    assert ex.policy.work==WORK and mapper.status['halt']['locked'] is True
    assert not node.texts
