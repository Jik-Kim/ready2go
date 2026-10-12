"""계약07 E 상관 모의. 실제 ROS/Runner/로봇 검증이 아닙니다."""
import pytest
from ready2go_voice.core.request_run import RequestRun

PAYLOAD = dict(intent='find_item', targets=['eraser'], request_id='req1', accept_text='지우개를 가져올게요.')


def status(decision=None, last=None, phase='idle', halt_code=None):
    return dict(phase=phase, task_id='find_item' if phase=='running' else None,
                halt_code=halt_code, last_intent=decision, last=last)


def accepted(run='run1', request='req1'):
    return dict(intent='find_item', targets=['eraser'], decision='run', request_id=request, run_id=run)


def completed(run='run1', outcome='COMPLETED', task='find_item'):
    return dict(run_id=run, task_id=task, overall_status=outcome, error_code=None)


@pytest.fixture
def tracker():
    value = RequestRun()
    assert value.register(PAYLOAD)
    return value




def test_accepts_once_and_retains_run_when_last_intent_is_other_request(tracker):
    assert tracker.observe(status(accepted(), phase='running'))[0]['event']=='request_accepted'
    assert not tracker.observe(status(accepted(), phase='running'))
    other = dict(accepted(request='other'), decision='reject', run_id=None)
    events = tracker.observe(status(other, completed()))
    assert [e['event'] for e in events] == ['request_completed']
    assert not tracker.observe(status(other, completed()))


def test_fast_completion_correlates_decision_and_result_in_same_sample(tracker):
    events = tracker.observe(status(accepted(), completed()))
    assert [e['event'] for e in events] == ['request_accepted','request_completed']


@pytest.mark.parametrize('decision',['hold','reject'])
def test_nonacceptance_cannot_become_accepted_later(tracker, decision):
    refused = dict(accepted(), decision=decision, run_id=None)
    assert tracker.observe(status(refused))[0]['decision']==decision
    assert not tracker.observe(status(accepted(), completed()))
    assert tracker.run_id is None


@pytest.mark.parametrize('run',['old','other',None])
def test_other_result_does_not_complete(tracker, run):
    tracker.observe(status(accepted()))
    assert not tracker.observe(status(last=completed(run)))
    assert not tracker.finished


@pytest.mark.parametrize('outcome',['FAILED','ABORTED','SUSPENDED','UNKNOWN'])
def test_noncompletion_never_claims_success(tracker, outcome):
    events = tracker.observe(status(accepted(), completed(outcome=outcome)))
    assert [e['event'] for e in events]==['request_accepted']


def test_halt_overrides_completion(tracker):
    assert [e['event'] for e in tracker.observe(status(accepted(), completed(), 'halted','ESTOP'))]==['request_accepted']


def test_changed_decision_invalidates_instead_of_rebinding(tracker):
    tracker.observe(status(accepted()))
    assert not tracker.observe(status(accepted('another'), completed('another')))
    assert tracker.pending is None and tracker.run_id is None






def test_cancel_or_publish_failure_does_not_retry(tracker):
    tracker.invalidate()
    assert not tracker.observe(status(accepted(),completed()))
    assert not tracker.register(PAYLOAD)




def test_detached_payload_preserves_original(tracker):
    tracker.pending['targets'].append('car_key')
    assert PAYLOAD['targets']==['eraser']


def test_pending_and_active_run_are_preserved_until_terminal(tracker):
    next_request=dict(PAYLOAD,request_id='next',targets=['car_key'])
    assert not tracker.register(next_request)
    assert tracker.pending==PAYLOAD
    tracker.observe(status(accepted(),phase='running'))
    assert not tracker.register(next_request)
    assert tracker.run_id=='run1'
    assert tracker.observe(status(last=completed()))[0]['event']=='request_completed'
    assert not tracker.observe(status(last=completed()))
    assert tracker.register(next_request)
    assert tracker.pending==next_request


@pytest.mark.parametrize('end',['hold','reject','FAILED','ABORTED','cancel'])
def test_nonactive_decision_or_terminal_allows_fresh_request(tracker,end):
    if end=='cancel':tracker.invalidate()
    elif end in ('hold','reject'):tracker.observe(status(dict(accepted(),decision=end,run_id=None)))
    else:tracker.observe(status(accepted(),completed(outcome=end)))
    assert tracker.register(dict(PAYLOAD,request_id='next'))


def test_registration_and_duplicate_content_collision_preserve_first_payload():
    value=RequestRun()
    assert not value.observe(status(accepted(),completed()))
    assert value.register(PAYLOAD)
    assert not value.register(PAYLOAD)
    assert not value.register(dict(PAYLOAD,targets=['car_key']))
    assert value.pending==PAYLOAD


def test_explicit_dependency_invalidation_prevents_old_result_rebinding(tracker):
    tracker.observe(status(accepted()))
    tracker.invalidate()
    assert not tracker.observe(status(accepted(),completed()))
    assert tracker.register(dict(PAYLOAD,request_id='fresh'))
    assert not tracker.observe(status(accepted(),completed()))
    assert tracker.run_id is None


def test_goal_status_without_goals_echo_correlates_by_request_and_run():
    goals=[dict(predicate='located_in',subject='eraser',value='handover_zone'),
           dict(predicate='open',subject='drawer_top',value=True)]
    payload=dict(intent='achieve_goal',goals=goals,targets=[],request_id='goal',accept_text='목표 요청입니다.')
    tracker=RequestRun();assert tracker.register(payload)
    # contract07 summary는 goals를 echo하지 않습니다.
    decision=dict(intent='achieve_goal',request_id='goal',run_id='goal-run',decision='run')
    assert tracker.observe(status(decision))[0]['event']=='request_accepted'
    assert not tracker.observe(status(dict(decision,request_id='other')))
    events=tracker.observe(status(decision,completed('goal-run',task='achieve_goal')))
    assert [event['event'] for event in events]==['request_completed']
    assert not tracker.observe(status(decision,completed('goal-run',task='achieve_goal')))


def test_goal_status_requires_matching_intent_and_nonempty_run_id():
    goals=[dict(predicate='open',subject='drawer_top',value=True)]
    payload=dict(intent='achieve_goal',goals=goals,targets=[],request_id='goal',accept_text='목표 요청입니다.')
    tracker=RequestRun();assert tracker.register(payload)
    wrong_intent=dict(intent='find_item',request_id='goal',run_id='goal-run',decision='run')
    assert not tracker.observe(status(wrong_intent))
    assert not tracker.observe(status(dict(wrong_intent,intent='achieve_goal',run_id='')))
    assert tracker.run_id is None and not tracker.decided
