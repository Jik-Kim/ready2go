"""P2 내부 제안의 의미 검사. 실제 ROS/복구/안전 정지 시험 아님."""
import pytest
from dataclasses import replace
from ready2go_voice.core.recovery_confirmation import (
    Evidence, RecoveryConfirmation, StoppedWork, safety_utterance,
    HaltNoticeEvidence, NewStartEvidence, NewStartCandidate,
)

SAFE = Evidence(True, True, True, True, True)
WORK = StoppedWork('boot', 'stop1', 'run1', 's5.1')


def ready():
    p = RecoveryConfirmation('boot', stt_result_timeout_sec=10)
    assert p.stopped(WORK, 1)
    q = p.recovered(WORK, 2, SAFE, now=2, valid_until=10)
    assert q and p.delivered(q, now=3, success=True)
    assert p.admit(q, captured_at=4, ended_at=4.5, started_at=5)
    return p, q


@pytest.mark.parametrize('text', ['재개하지 마', '재개해라고 말했어', '아마 재개해', '네', '', None])
def test_ambiguous_or_quoted_text_is_not_resume(text):
    assert safety_utterance(text) is None


@pytest.mark.parametrize('text,kind', [('멈춰', 'stop'), ('복구해', 'recover'), ('재개해!', 'resume')])
def test_explicit_internal_candidates(text, kind):
    assert safety_utterance(text) == kind


def test_question_once_and_response_once():
    p, q = ready()
    assert p.recovered(WORK, 3, SAFE, now=4, valid_until=20) is None
    assert p.answer('재개해', q, captured_at=4, now=5, evidence=SAFE, request=p.request) == WORK
    assert p.answer('재개해', q, captured_at=4, now=5, evidence=SAFE, request=p.request) is None
    assert p.recovered(WORK, 4, SAFE, now=5, valid_until=20) is None


@pytest.mark.parametrize('field', ['stopped', 'recovered', 'conditions', 'resume_point', 'fresh'])
def test_unverified_condition_revokes_confirmation(field):
    p, q = ready()
    evidence = Evidence(**{k: k != field for k in SAFE.__dict__})
    assert p.answer('재개해', q, captured_at=4, now=5, evidence=evidence, request=p.request) is None
    assert p.question is None


def test_restop_stale_events_wrong_work_and_restart():
    p, q = ready()
    other = StoppedWork('boot', 'stop2', 'run1', 's5.1')
    assert p.stopped(other, 3)
    assert p.recovered(WORK, 2, SAFE, now=4, valid_until=10) is None
    assert p.answer('재개해', q, captured_at=4, now=5, evidence=SAFE, request=p.request) is None
    assert p.recovered(WORK, 4, SAFE, now=4, valid_until=10) is None
    restarted = RecoveryConfirmation('new_boot')
    assert not restarted.stopped(WORK, 5)
    assert restarted.answer('재개해', q, captured_at=4, now=5, evidence=SAFE, request=p.request) is None


@pytest.mark.parametrize('captured,now', [(2, 4), (4, 10), (7, 5), (float('nan'), 5)])
def test_pre_question_delayed_or_invalid_capture(captured, now):
    p, q = ready()
    assert p.answer('재개해', q, captured_at=captured, now=now, evidence=SAFE, request=p.request) is None


def test_tts_not_finished_or_failed_never_authorizes():
    p = RecoveryConfirmation('boot', stt_result_timeout_sec=10); p.stopped(WORK, 1)
    q = p.recovered(WORK, 2, SAFE, now=2, valid_until=10)
    assert p.answer('재개해', q, captured_at=3, now=4, evidence=SAFE, request=p.request) is None
    p, q = ready()
    assert not p.delivered(q, now=4, success=False)
    assert p.answer('재개해', q, captured_at=5, now=6, evidence=SAFE, request=p.request) is None


def test_unknown_recovery_and_expiry_do_not_prepare_question():
    p = RecoveryConfirmation('boot', stt_result_timeout_sec=10); p.stopped(WORK, 1)
    assert p.recovered(WORK, 2, Evidence(), now=2, valid_until=10) is None
    assert p.recovered(WORK, 3, SAFE, now=10, valid_until=10) is None
    assert p.question is None


def test_completion_before_question_creation_is_rejected():
    p = RecoveryConfirmation('boot', stt_result_timeout_sec=10); p.stopped(WORK, 1)
    q = p.recovered(WORK, 2, SAFE, now=2, valid_until=10)
    assert not p.delivered(q, now=0, success=True)
    assert p.answer('재개해', q, captured_at=1, now=3, evidence=SAFE, request=p.request) is None


def test_recording_start_before_tts_completion_is_rejected():
    p, q = ready()
    assert p.answer('재개해', q, captured_at=2.5, now=4, evidence=SAFE, request=p.request) is None


def test_clock_regression_after_completion_is_rejected():
    p, q = ready()
    assert p.answer('재개해', q, captured_at=3, now=2, evidence=SAFE, request=p.request) is None


def test_restopping_during_question_invalidates_late_tts_completion():
    p, q = ready()
    new = StoppedWork('boot', 'stop2', 'run1', 's5.1')
    assert p.stopped(new, 3)
    assert not p.delivered(q, now=4, success=True)
    assert p.answer('재개해', q, captured_at=5, now=6, evidence=SAFE, request=p.request) is None


DROP = replace(WORK, cause='OBJECT_DROPPED', skill='place')
RESTORED = NewStartEvidence(DROP, True, True, True, True, True, True, True, True, True, True)
DROP_NOTICE = HaltNoticeEvidence(DROP, stopped=True, fresh=True, dropped=True,
                                item_name='지우개', item_confirmed=True)


def ready_new_start():
    p = RecoveryConfirmation('boot', stt_result_timeout_sec=10)
    assert p.stopped(DROP, 1)
    q = p.recovered(DROP, 2, RESTORED, now=2, valid_until=20)
    assert q and q.mode == 'new_start' and '처음부터' in q.text and '멈춘 단계' not in q.text
    assert p.delivered(q, now=3, success=True)
    receipt = p.admit(q, captured_at=4, ended_at=4.5, started_at=5)
    assert receipt
    return p, q, receipt


def test_place_drop_never_offers_old_step_resume_even_with_legacy_safe_flags():
    p = RecoveryConfirmation('boot', stt_result_timeout_sec=10)
    assert p.stopped(DROP, 1)
    assert p.recovered(DROP, 2, SAFE, now=2, valid_until=20) is None
    assert p.ordinary_cancel() == DROP and p.question is None
    assert p.recovered(DROP, 3, Evidence(True, True, True, True, True, True),
                       now=3, valid_until=20) is None


@pytest.mark.parametrize('field', ['stopped', 'run_ended', 'restored', 'gripper_checked',
                                  'item_checked', 'drawer_checked', 'workspace_checked',
                                  'state_synced', 'conditions', 'fresh'])
def test_new_start_requires_each_physical_and_c_evidence_at_both_boundaries(field):
    missing = replace(RESTORED, **{field: False})
    p = RecoveryConfirmation('boot', stt_result_timeout_sec=10)
    assert p.stopped(DROP, 1)
    assert p.recovered(DROP, 2, missing, now=2, valid_until=20) is None
    p, q, receipt = ready_new_start()
    assert p.answer('처음부터 시작해', q, captured_at=4, now=6,
                    evidence=missing, request=receipt) is None
    assert p.question is None and p.work == DROP


@pytest.mark.parametrize('text', ['다시 넣었어', '재개해', '이어서 실행해', '네',
                                  '처음부터 시작하지 마', '처음부터 시작해라고 말했어'])
def test_restoration_claim_or_old_resume_cannot_authorize_new_start(text):
    p, q, receipt = ready_new_start()
    assert p.answer(text, q, captured_at=4, now=6, evidence=RESTORED, request=receipt) is None
    assert p.work == DROP and p.question is None


def test_explicit_new_start_returns_distinct_candidate_once_without_executing_old_step():
    p, q, receipt = ready_new_start()
    candidate = p.answer('처음부터 시작해', q, captured_at=4, now=6,
                         evidence=RESTORED, request=receipt)
    assert isinstance(candidate, NewStartCandidate) and not isinstance(candidate, StoppedWork)
    assert candidate.previous_work == DROP  # audit only, no action/run creation
    assert p.answer('처음부터 시작해', q, captured_at=4, now=6,
                    evidence=RESTORED, request=receipt) is None
    assert p.recovered(DROP, 3, RESTORED, now=6, valid_until=20) is None


def test_wrong_event_or_unknown_dropped_skill_never_restores_or_resumes():
    p = RecoveryConfirmation('boot', stt_result_timeout_sec=10); p.stopped(DROP, 1)
    assert p.recovered(DROP, 2, replace(RESTORED, work=replace(DROP, stop='past')),
                       now=2, valid_until=20) is None
    for skill in (None, 'pick'):
        work = replace(DROP, skill=skill)
        p = RecoveryConfirmation('boot', stt_result_timeout_sec=10); p.stopped(work, 1)
        assert p.recovered(work, 2, replace(RESTORED, work=work), now=2, valid_until=20) is None
        assert p.recovered(work, 3, SAFE, now=3, valid_until=20) is None


def test_tts_failure_abandon_and_restop_cannot_restore_resume_for_dropped_run():
    p, q, _ = ready_new_start()
    assert not p.delivered(q, now=4, success=False)
    assert p.work == DROP and p.question is None
    cancel = replace(DROP, stop='stop2', cause='HALTED', skill=None)
    assert p.stopped(cancel, 3)
    assert p.recovered(cancel, 4, SAFE, now=5, valid_until=20) is None
    assert not p.stopped(replace(cancel, cause='ESTOP'), 5)  # cannot relabel same event
    assert not p.stopped(DROP, 6)  # retired event
    assert not p.delivered(q, now=6, success=True)
    p, q, _ = ready_new_start()
    assert p.abandon(q)
    assert p.stopped(cancel, 3)
    assert p.recovered(cancel, 4, SAFE, now=5, valid_until=20) is None


def test_restop_expiry_and_restart_reject_previous_new_start_response():
    p, q, receipt = ready_new_start()
    current = replace(DROP, stop='stop2')
    assert p.stopped(current, 3)
    assert p.answer('처음부터 시작해', q, captured_at=4, now=6,
                    evidence=RESTORED, request=receipt) is None
    assert p.recovered(current, 4, RESTORED, now=6, valid_until=20) is None
    p, q, receipt = ready_new_start()
    assert p.answer('처음부터 시작해', q, captured_at=4, now=20,
                    evidence=RESTORED, request=receipt) is None
    p, q, receipt = ready_new_start()
    assert p.track_boot('new_boot', valid_state=True)
    assert not p.stopped(DROP, 3)
    assert p.answer('처음부터 시작해', q, captured_at=4, now=6,
                    evidence=RESTORED, request=receipt) is None


def test_sensor_invalid_requires_normal_sensor_and_current_state_before_resume():
    work = replace(WORK, cause='SENSOR_INVALID', skill='place')
    p = RecoveryConfirmation('boot', stt_result_timeout_sec=10); p.stopped(work, 1)
    assert p.recovered(work, 2, SAFE, now=2, valid_until=20) is None
    normal = replace(SAFE, sensor_normal=True)
    q = p.recovered(work, 3, normal, now=3, valid_until=20)
    assert q and q.mode == 'resume'
    assert p.delivered(q, now=4, success=True)
    receipt = p.admit(q, captured_at=5, ended_at=5.5, started_at=6)
    assert p.answer('재개해', q, captured_at=5, now=7, evidence=SAFE, request=receipt) is None
    assert p.work == work


def test_trusted_stop_and_drop_target_are_required_for_recovery_notice():
    p = RecoveryConfirmation('boot'); p.stopped(DROP, 1)
    assert p.notice(DROP_NOTICE) == '지우개가 떨어져 작업을 중단했습니다. 지우개를 다시 서랍에 넣어주세요.'
    for evidence in (None, replace(DROP_NOTICE, stopped=False), replace(DROP_NOTICE, fresh=False),
                     replace(DROP_NOTICE, dropped=False), replace(DROP_NOTICE, item_confirmed=False),
                     replace(DROP_NOTICE, item_name=None), replace(DROP_NOTICE, work=WORK)):
        text = p.notice(evidence)
        assert '실제 정지' in text and '넣어주세요' not in text and '중단했습니다' not in text
    assert p.work == DROP and p.question is None


def test_sensor_notice_never_infers_dropped_or_empty_gripper_even_with_item_input():
    work = replace(WORK, cause='SENSOR_INVALID', skill='place')
    p = RecoveryConfirmation('boot'); p.stopped(work, 1)
    text = p.notice(replace(DROP_NOTICE, work=work))
    assert '센서' in text and '물품 상태' in text
    assert all(word not in text for word in ('빈손', '떨어', '넣어주세요'))
    assert p.recovered(work, 2, SAFE, now=2, valid_until=10) is None
