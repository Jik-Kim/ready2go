"""순수 상태 관측 정책. 실제 정지/즉시 오류 검출/스피커 실측이 아닙니다."""
import json
import pytest
from ready2go_voice.core.runner_notice import RunnerNoticePolicy, STATUS_PROMPTS
from ready2go_voice.core.tts_prefill import prefill_texts


def status(phase='idle', code=None, run=None, error='TIMEOUT', outcome='FAILED', task='find_item'):
    return {'phase': phase, 'task_id': task if phase == 'running' else None, 'halt_code': code,
            'last': None if run is None else {'run_id': run, 'task_id': task,
                    'overall_status': outcome, 'error_code': error, 'failed_step': 'pick', 'problems': []}}


@pytest.mark.parametrize('raw', ['{', '[]', 'null', 3, {}, {'phase': 'bad'},
                               status('running', task=None), status(code=[]), {'phase': 'idle', 'last': []}])
def test_malformed_never_mutates_policy(raw):
    policy = RunnerNoticePolicy()
    assert policy.observe(raw) is None and not policy.initialized and not policy.blocked


def test_first_latched_halt_and_last_do_not_repeat_but_new_halt_does():
    p = RunnerNoticePolicy(); past = status('halted', 'ESTOP', 'past', 'ESTOP', 'ABORTED')
    assert p.observe(json.dumps(past)) is None
    assert p.observe(past) is None and p.blocked
    assert p.observe(status(run='past')) is None and not p.blocked
    notice = p.observe(status('halted', 'ESTOP', 'past'))
    assert notice.kind == 'estop' and p.observe(status('halted', 'ESTOP', 'past')) is None


def test_running_halt_ignores_historical_estop_and_final_duplicate():
    p = RunnerNoticePolicy(); p.observe(status(run='previous', error='ESTOP', outcome='ABORTED'))
    p.observe(status('running', run='previous', error='ESTOP', outcome='ABORTED'))
    notice = p.observe(status('running', 'HALTED', 'previous', 'ESTOP', 'ABORTED'))
    assert notice.kind == 'halted' and '비상정지' not in notice.text and '멈췄' not in notice.text
    assert p.observe(status('halted', 'HALTED', 'current', 'HALTED', 'ABORTED')) is None


@pytest.mark.parametrize('error,kind', [('TIMEOUT','timeout'), ('LATE_RESULT','timeout'),
                                    ('GRASP_FAILED','grasp'), ('DEPTH_INVALID','vision'),
                                    ('UNKNOWN_REGION','vision'), ('unregistered PRIVATE','failure')])
def test_final_failure_once_and_next_run_same_error_again(error, kind):
    p = RunnerNoticePolicy(); p.observe(status()); p.observe(status('running'))
    notice = p.observe(status(run='one', error=error))
    assert notice.kind == kind and error not in notice.text and not p.blocked
    assert p.observe(status(run='one', error=error)) is None
    p.observe(status('running', run='one', error=error))
    assert p.observe(status(run='two', error=error)).kind == kind


@pytest.mark.parametrize('code,kind', [('ESTOP','estop'), ('STOP_UNCONFIRMED','unconfirmed'),
                                   ('STATE_UNKNOWN','unconfirmed'), ('MOVE_UNCONFIRMED','unconfirmed'),
                                   ('LOCKED','unconfirmed'), ('HALTED','halted'), ('UNKNOWN_HALT','unconfirmed')])
def test_running_warning_codes_priority_and_no_stop_claim(code, kind):
    p = RunnerNoticePolicy(); p.observe(status()); p.observe(status('running'))
    notice = p.observe(status('running', code))
    assert notice.kind == kind and '멈췄' not in notice.text
    assert p.observe(status('running', code)) is None


def test_warning_priority_escalates_and_later_final_never_downgrades():
    p = RunnerNoticePolicy(); p.observe(status()); p.observe(status('running'))
    assert p.observe(status('running', 'HALTED')).kind == 'halted'
    assert p.observe(status('running', 'STATE_UNKNOWN')).kind == 'unconfirmed'
    assert p.observe(status('running', 'ESTOP')).kind == 'estop'
    assert p.observe(status('halted', 'ESTOP', 'one', 'TIMEOUT')) is None


def test_completed_historical_stale_and_other_task_results_are_silent():
    p = RunnerNoticePolicy(); p.observe(status(run='historic'))
    p.observe(status('running', run='historic'))
    # running.last는 이전 회차이며 현재 결과로 간주하지 않습니다.
    assert p.observe(status('running', run='delayed-old')) is None
    assert p.observe(status(run='delayed-old')) is None
    assert p.observe(status(run='historic')) is None
    assert p.observe(status(run='other', task='other_task')) is None
    assert p.observe(status(run='current', outcome='COMPLETED')) is None
    assert p.observe(status(run='current')) is None


def test_unobserved_running_result_is_not_claimed_current():
    p = RunnerNoticePolicy(); p.observe(status())
    assert p.observe(status(run='unobserved')) is None
    # 활성 run_id/이벤트 시각 없이 미관측 같은 태스크의 지연 결과는 완전 구분할 수 없습니다.
    # 이 계약 한계는 문서/C 인계이며 임의 timestamp/새 필드를 만들지 않습니다.


def test_new_cycle_invalidates_pending_warning_and_same_error_can_repeat():
    p = RunnerNoticePolicy(); p.observe(status()); p.observe(status('running'))
    first = p.observe(status('running', 'ESTOP'))
    p.observe(status('halted', 'ESTOP', 'one', 'ESTOP', 'ABORTED'))
    p.observe(status(run='one'));p.observe(status('running', run='one'))
    assert p.revision != first.revision
    assert p.observe(status('running', 'ESTOP', 'one')).kind == 'estop'


def test_all_fixed_warning_prompts_are_prefilled_without_user_overwrite(cfg, ontology):
    result = prefill_texts(cfg, ontology['world']['items'].values())
    assert set(STATUS_PROMPTS.values()) <= set(result)
    assert set(cfg['tts_melotts_prefill_texts']) <= set(result)


def test_real_runner_status_shape_running_halt_does_not_replay_previous_last():
    from ready2go_runner.core.runner_status import build_status
    from ready2go_runner.core.interpreter import RunResult
    last = RunResult('ABORTED', {}, error_code='ESTOP', run_id='previous')
    p=RunnerNoticePolicy()
    p.observe(build_status(False,False,None,None,None,last,'find_item',False))
    p.observe(build_status(True,False,None,'find_item','pick',last,'find_item',False))
    notice=p.observe(build_status(True,True,'HALTED','find_item','pick',last,'find_item',False))
    assert notice.kind=='halted'
