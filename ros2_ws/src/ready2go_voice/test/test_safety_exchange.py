"""현재 E 교환/Session/노드 후보의 반례. typed 입력은 실제 C/B 증거가 아닙니다."""
from dataclasses import replace
import threading
from types import SimpleNamespace
import pytest
from ready2go_voice.core.safety_exchange import SafetyExchange, IndependentRegistration, QuestionDeclined, RecoveryRequest
from ready2go_voice.core.recovery_confirmation import StoppedWork,Evidence,TaskEndCandidate
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.adapters.audio import Recording
from test_voice_ux_node import node_class,node

WORK=StoppedWork('boot','halt','run','step')
SAFE=Evidence(True,True,True,True,True)


def stopped(cfg):
    exchange=SafetyExchange(cfg)
    assert exchange.stopped(WORK,1,valid_state=True,evidence=SAFE)
    return exchange


def question(exchange):
    q=exchange.offer(WORK,2,SAFE,now=2.,valid_until=50.,valid_state=True)
    assert q is not None
    return q


def delivered(exchange,q):
    assert exchange.registered(q,WORK,2,now=2.5,valid_state=True)
    assert exchange.tts_started(q,now=3.)
    assert exchange.delivered(q,now=4.,success=True)


def request(exchange,target,start=5.,sdk=6.):
    capture=exchange.reserve(target)
    assert capture is not None
    receipt=exchange.admit(target,capture,captured_at=start,ended_at=sdk-.5,started_at=sdk)
    assert receipt is not None
    return receipt


def test_question_requires_registration_real_completion_and_single_capture(cfg):
    ex=stopped(cfg);q=question(ex)
    assert ex.reserve(q) is None
    # ACK 이전 TTS 시작은 질문 권한을 폐기하고 work는 보존합니다.
    assert not ex.tts_started(q,now=2.)
    assert ex.policy.work==WORK and not ex.current(q)
    ex=stopped(cfg);q=question(ex);delivered(ex,q)
    receipt=request(ex,q)
    assert ex.reserve(q) is None
    assert ex.answer(q,'네',captured_at=5.,now=7.,request=receipt) is None
    assert ex.policy.work==WORK


@pytest.mark.parametrize('answer',['재개해','아니요'])
def test_question_once_accept_or_decline_preserves_work(cfg,answer):
    ex=stopped(cfg);q=question(ex);delivered(ex,q);receipt=request(ex,q)
    candidate=ex.answer(q,answer,captured_at=5.,now=7.,request=receipt)
    assert candidate==WORK if answer=='재개해' else isinstance(candidate,QuestionDeclined)
    assert ex.answer(q,answer,captured_at=5.,now=7.,request=receipt) is None
    assert ex.policy.work==WORK


def test_normal_seq_preserves_capture_but_conflict_invalidates_with_floor(cfg):
    ex=stopped(cfg);q=question(ex);delivered(ex,q);receipt=request(ex,q)
    capture=ex.capture
    assert not ex.stopped(WORK,1,valid_state=True)
    assert ex.current(q) and ex.capture is capture
    assert ex.stopped(WORK,3,valid_state=True)
    assert ex.answer(q,'재개해',captured_at=5.,now=7.,request=receipt)==WORK
    # 낮은/같은 seq 입력은 현재 의미를 바꾸지 않으며, 새로운 의미 충돌은 하한을 보존합니다.
    assert not ex.stopped(replace(WORK,stop='conflict'),3,valid_state=True)
    assert ex.policy.current_state_confirmed
    assert not ex.stopped(replace(WORK,cause='SENSOR_INVALID'),4,valid_state=True)
    assert not ex.policy.current_state_confirmed
    assert not ex.stopped(WORK,3,valid_state=True)
    assert not ex.stopped(WORK,4,valid_state=True)
    assert not ex.policy.current_state_confirmed
    assert ex.stopped(WORK,5,valid_state=True)
    assert ex.policy.current_state_confirmed


def test_independent_cannot_overwrite_question_or_inflight_and_uses_new_capture_budget(cfg):
    ex=stopped(cfg);q=question(ex)
    assert ex.begin_independent(now=3.,unique_target=True) is None and ex.current(q)
    ex.cancel();target=ex.begin_independent(now=5.,unique_target=True)
    assert target is not None
    assert ex.begin_independent(now=6.,unique_target=True) is None and ex.current(target)
    assert ex.budget(target,now=11.,captured_at=10.)==29.
    receipt=request(ex,target,start=10.,sdk=11.)
    candidate=ex.answer(target,'재개해',captured_at=10.,now=12.,request=receipt)
    assert isinstance(candidate,IndependentRegistration)
    assert ex.independent_registered(target,WORK,3,now=13.,valid_state=True,evidence=SAFE)==WORK
    assert ex.independent_registered(target,WORK,3,now=13.,valid_state=True,evidence=SAFE) is None


def test_expired_cancel_and_old_callback_do_not_consume_new_work(cfg):
    ex=stopped(cfg);q=question(ex);delivered(ex,q);receipt=request(ex,q)
    assert ex.answer(q,'네',captured_at=5.,now=50.,request=receipt) is None
    assert ex.policy.work==WORK
    ex.cancel();new=replace(WORK,stop='next')
    assert ex.stopped(new,3,valid_state=True,evidence=SAFE)
    target=ex.begin_independent(now=51.,unique_target=True)
    assert target is not None
    ex.fail(q)
    assert ex.current(target) and ex.policy.work==new
    assert ex.answer(q,'네',captured_at=5.,now=52.,request=receipt) is None
    assert ex.current(target)


@pytest.mark.parametrize('text',['복구해','작업 종료해'])
def test_independent_recovery_and_explicit_end_have_distinct_candidates(cfg,text):
    ex=stopped(cfg);target=ex.begin_independent(now=2.,unique_target=True);receipt=request(ex,target)
    candidate=ex.answer(target,text,captured_at=5.,now=7.,request=receipt)
    if text=='복구해':
        assert isinstance(candidate,RecoveryRequest) and candidate.work==WORK and ex.policy.work==WORK
    else:
        assert isinstance(candidate,IndependentRegistration)
        final=ex.independent_registered(target,WORK,2,now=8.,valid_state=True,evidence=SAFE)
        assert isinstance(final,TaskEndCandidate) and final.work==WORK
        assert ex.policy.work == WORK  # 명시 수락 전 작업 보존


class STT:
    supports_request_boundary=True
    def __init__(self,text,clock,hook=lambda:None):self.text,self.clock,self.hook=text,clock,hook
    def transcribe(self,path,timeout,*,before_request):
        assert before_request(self.clock[0]);self.hook();return self.text


def audio():
    return Recording(b'\x01\x00'*1280,5.5,123.,recording_started_monotonic=5.,recording_ended_monotonic=5.5)


def test_actual_safety_question_stop_reaches_existing_publisher(node):
    node.safety_exchange=ex=stopped(node.cfg);q=question(ex);delivered(ex,q)
    node.now[0]=6.;node.session.stt=STT('멈춰',node.now)
    node.safety_sender=lambda *a:None
    cancel=node.safety_cancel
    result=node.session.safety_audio(ex,q,audio(),cancel=cancel)
    assert result is not None and result['intent']=='cancel'
    with node.submit_lock:node._safety_result_locked(result,cancel,node.safety_sender)
    assert [doc['intent'] for doc in node.published]==['cancel']
    assert ex.policy.work==WORK and node.request_cancel.is_set()


def test_session_stale_sdk_callback_cannot_clear_new_target(cfg):
    ex=stopped(cfg);q=question(ex);delivered(ex,q)
    now=[6.];new=replace(WORK,stop='new')
    def changed():
        assert ex.stopped(new,3,valid_state=True,evidence=SAFE)
        assert ex.begin_independent(now=6.,unique_target=True)
    session=VoiceSession(None,cfg,STT('네',now,changed),clock=lambda:now[0])
    assert session.safety_audio(ex,q,audio()) is None
    assert ex.policy.work==new and ex.policy.independent is not None


@pytest.mark.parametrize('completion',['observed','missing'])
def test_actual_safety_worker_registered_before_tts_and_requires_completion(node,completion):
    h=node;h.cfg['audio_enabled']=True;h.now[0]=2.;h.place_test_devices=True
    h.safety_exchange=ex=stopped(h.cfg)
    events=[];finished=threading.Event();capture_calls=[]
    diagnostic=h._diagnostic
    def diagnose(doc):
        diagnostic(doc)
        if doc.get('event')=='safety_question_failed':finished.set()
    h._diagnostic=diagnose
    def sender(kind,target):
        events.append(kind)
        if kind=='register_question':
            h.now[0]=2.5
            assert h.safety_registered(target,WORK,2,valid_state=True)
        elif kind=='candidate':
            assert target==WORK;finished.set()
    h.bind_safety_sender(sender)
    q=h.safety_offer(WORK,2,SAFE,valid_state=True,valid_until=50.)
    assert q is not None
    def speak(text,*,on_start,on_timing,**kw):
        assert events==['register_question'] and ex.policy.registered_at==2.5
        events.append('tts');h.now[0]=3.
        on_start(dict(tts_started_monotonic=3.,tts_start_basis='portaudio_first_dac',tts_mock=True))
        h.now[0]=4.
        if completion=='observed':on_timing(dict(playback_ended_monotonic=4.,playback_end_basis='portaudio_finished_callback'))
    h.tts.speak=speak
    def capture(cancel,paused):
        assert ex.policy.finished_at==4. and not paused()
        capture_calls.append('capture');h.now[0]=6.;return audio()
    h.place_recorder=SimpleNamespace(capture=capture)
    h.session.stt=STT('재개해',h.now)
    worker=threading.Thread(target=h._safety_work);worker.start()
    try:
        assert finished.wait(1)
        assert ex.policy.work==WORK and not h.published
        if completion=='observed':assert events==['register_question','tts','candidate'] and capture_calls==['capture']
        else:assert events==['register_question','tts'] and not capture_calls and not ex.current(q)
    finally:
        h.stop_event.set()
        with h.place_condition:h.place_condition.notify_all()
        worker.join(1);assert not worker.is_alive()


def test_actual_new_recording_independent_ack_consumes_once_and_old_work_does_not_rebind(node):
    h=node;h.safety_exchange=ex=stopped(h.cfg);h.now[0]=6.
    h.session.stt=STT('재개해',h.now);events=[]
    def sender(kind,target):
        events.append((kind,target))
        if kind=='register_independent':
            assert h.safety_independent_registered(target,WORK,2,valid_state=True,evidence=SAFE)==WORK
    h.bind_safety_sender(sender)
    h._safety_recording(audio(),WORK)
    assert [kind for kind,_ in events]==['register_independent','candidate']
    old=events[0][1]
    assert h.safety_independent_registered(old,WORK,2,valid_state=True,evidence=SAFE) is None
    assert ex.stopped(replace(WORK,stop='new'),3,valid_state=True,evidence=SAFE)
    h._safety_recording(audio(),WORK)
    assert len(events)==2 and ex.policy.independent is None
