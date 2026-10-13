"""P2 내부 제안의 의미 검사. 실제 ROS/복구/안전 정지 시험 아님."""
import pytest
from dataclasses import replace
from ready2go_voice.core.recovery_confirmation import (
    Evidence, RecoveryConfirmation, StoppedWork, safety_utterance,
    HaltNoticeEvidence, NewStartEvidence, NewStartCandidate,
)

from pathlib import Path
from ready2go_voice.core.config import load_config
POLICY_CFG = load_config(Path(__file__).resolve().parents[1] / 'params/voice.yaml')


def make_recovery(session, **overrides):
    cfg = dict(POLICY_CFG)
    cfg.update({'resume_' + key: value for key, value in overrides.items()})
    return RecoveryConfirmation.from_config(session, cfg)


def delivered(policy, question, **kwargs):
    # Test fixture includes a trusted current C ACK and actual TTS start.
    if question is not None and question is policy.question and policy.registered_at is None:
        assert policy.registered(question, question.work, policy.revision,
                                 now=question.issued_at, valid_state=True)
        assert policy.tts_started(question, now=question.issued_at)
    return policy.delivered(question, **kwargs)


SAFE = Evidence(True, True, True, True, True)
WORK = StoppedWork('boot', 'stop1', 'run1', 's5.1')


def ready():
    p = make_recovery('boot', stt_result_timeout_sec=10)
    assert p.stopped(WORK, 1)
    q = p.recovered(WORK, 2, SAFE, now=2, valid_until=10)
    assert q and delivered(p, q, now=3, success=True)
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
    restarted = make_recovery('new_boot')
    assert not restarted.stopped(WORK, 5)
    assert restarted.answer('재개해', q, captured_at=4, now=5, evidence=SAFE, request=p.request) is None


@pytest.mark.parametrize('captured,now', [(2, 4), (4, 10), (7, 5), (float('nan'), 5)])
def test_pre_question_delayed_or_invalid_capture(captured, now):
    p, q = ready()
    assert p.answer('재개해', q, captured_at=captured, now=now, evidence=SAFE, request=p.request) is None


def test_tts_not_finished_or_failed_never_authorizes():
    p = make_recovery('boot', stt_result_timeout_sec=10); p.stopped(WORK, 1)
    q = p.recovered(WORK, 2, SAFE, now=2, valid_until=10)
    assert p.answer('재개해', q, captured_at=3, now=4, evidence=SAFE, request=p.request) is None
    p, q = ready()
    assert not delivered(p, q, now=4, success=False)
    assert p.answer('재개해', q, captured_at=5, now=6, evidence=SAFE, request=p.request) is None


def test_unknown_recovery_and_expiry_do_not_prepare_question():
    p = make_recovery('boot', stt_result_timeout_sec=10); p.stopped(WORK, 1)
    assert p.recovered(WORK, 2, Evidence(), now=2, valid_until=10) is None
    assert p.recovered(WORK, 3, SAFE, now=10, valid_until=10) is None
    assert p.question is None


def test_completion_before_question_creation_is_rejected():
    p = make_recovery('boot', stt_result_timeout_sec=10); p.stopped(WORK, 1)
    q = p.recovered(WORK, 2, SAFE, now=2, valid_until=10)
    assert not delivered(p, q, now=0, success=True)
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
    assert not delivered(p, q, now=4, success=True)
    assert p.answer('재개해', q, captured_at=5, now=6, evidence=SAFE, request=p.request) is None


DROP = replace(WORK, cause='OBJECT_DROPPED', skill='place')
RESTORED = NewStartEvidence(DROP, True, True, True, True, True, True, True, True, True, True)
DROP_NOTICE = HaltNoticeEvidence(DROP, stopped=True, fresh=True, dropped=True,
                                item_name='지우개', item_confirmed=True)


def ready_new_start():
    p = make_recovery('boot', stt_result_timeout_sec=10)
    assert p.stopped(DROP, 1)
    q = p.recovered(DROP, 2, RESTORED, now=2, valid_until=20)
    assert q and q.mode == 'new_start' and '처음부터' in q.text and '멈춘 단계' not in q.text
    assert delivered(p, q, now=3, success=True)
    receipt = p.admit(q, captured_at=4, ended_at=4.5, started_at=5)
    assert receipt
    return p, q, receipt


def test_place_drop_never_offers_old_step_resume_even_with_legacy_safe_flags():
    p = make_recovery('boot', stt_result_timeout_sec=10)
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
    p = make_recovery('boot', stt_result_timeout_sec=10)
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
    p = make_recovery('boot', stt_result_timeout_sec=10); p.stopped(DROP, 1)
    assert p.recovered(DROP, 2, replace(RESTORED, work=replace(DROP, stop='past')),
                       now=2, valid_until=20) is None
    for skill in (None, 'pick'):
        work = replace(DROP, skill=skill)
        p = make_recovery('boot', stt_result_timeout_sec=10); p.stopped(work, 1)
        assert p.recovered(work, 2, replace(RESTORED, work=work), now=2, valid_until=20) is None
        assert p.recovered(work, 3, SAFE, now=3, valid_until=20) is None


def test_tts_failure_abandon_and_restop_cannot_restore_resume_for_dropped_run():
    p, q, _ = ready_new_start()
    assert not delivered(p, q, now=4, success=False)
    assert p.work == DROP and p.question is None
    cancel = replace(DROP, stop='stop2', cause='HALTED', skill=None)
    assert p.stopped(cancel, 3)
    assert p.recovered(cancel, 4, SAFE, now=5, valid_until=20) is None
    assert not p.stopped(replace(cancel, cause='ESTOP'), 5)  # cannot relabel same event
    assert not p.stopped(DROP, 6)  # retired event
    assert not delivered(p, q, now=6, success=True)
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
    p = make_recovery('boot', stt_result_timeout_sec=10); p.stopped(work, 1)
    assert p.recovered(work, 2, SAFE, now=2, valid_until=20) is None
    normal = replace(SAFE, sensor_normal=True)
    q = p.recovered(work, 3, normal, now=3, valid_until=20)
    assert q and q.mode == 'resume'
    assert delivered(p, q, now=4, success=True)
    receipt = p.admit(q, captured_at=5, ended_at=5.5, started_at=6)
    assert p.answer('재개해', q, captured_at=5, now=7, evidence=SAFE, request=receipt) is None
    assert p.work == work


def test_trusted_stop_and_drop_target_are_required_for_recovery_notice():
    p = make_recovery('boot'); p.stopped(DROP, 1)
    assert p.notice(DROP_NOTICE) == '지우개가 떨어져 작업을 중단했습니다. 지우개를 다시 서랍에 넣어주세요.'
    for evidence in (None, replace(DROP_NOTICE, stopped=False), replace(DROP_NOTICE, fresh=False),
                     replace(DROP_NOTICE, dropped=False), replace(DROP_NOTICE, item_confirmed=False),
                     replace(DROP_NOTICE, item_name=None), replace(DROP_NOTICE, work=WORK)):
        text = p.notice(evidence)
        assert '실제 정지' in text and '넣어주세요' not in text and '중단했습니다' not in text
    assert p.work == DROP and p.question is None


def test_sensor_notice_never_infers_dropped_or_empty_gripper_even_with_item_input():
    work = replace(WORK, cause='SENSOR_INVALID', skill='place')
    p = make_recovery('boot'); p.stopped(work, 1)
    text = p.notice(replace(DROP_NOTICE, work=work))
    assert '센서' in text and '물품 상태' in text
    assert all(word not in text for word in ('빈손', '떨어', '넣어주세요'))
    assert p.recovered(work, 2, SAFE, now=2, valid_until=10) is None


def unregistered():
    p = make_recovery('boot')
    assert p.stopped(WORK, 1)
    q = p.recovered(WORK, 2, SAFE, now=2, valid_until=100)
    return p, q


def test_ack_required_before_tts_and_failure_preserves_work():
    p, q = unregistered()
    assert not p.tts_started(q, now=3)
    assert p.work == WORK and p.question is None
    p, q = unregistered()
    assert not p.delivered(q, now=3, success=True)
    assert p.work == WORK


@pytest.mark.parametrize('work,revision,valid', [(replace(WORK, session='old'), 2, True),
    (WORK, 1, True), (WORK, 2, False), (WORK, True, True)])
def test_ack_must_match_current_work_and_sequence(work, revision, valid):
    p, q = unregistered()
    assert not p.registered(q, work, revision, now=3, valid_state=valid)
    assert p.work == WORK and p.question is None


def test_registration_and_tts_use_question_validity_without_extra_timers():
    p, q = unregistered()
    assert not p.expire(now=8)  # previously the extra 5-second ACK timer expired here
    assert p.registered(q, WORK, 3, now=8, valid_state=True)
    assert not p.registered(q, WORK, 4, now=9, valid_state=True)
    assert p.registered_at == 8 and p.revision == 3
    assert not p.expire(now=25)  # no additional registration-to-TTS deadline
    assert p.tts_started(q, now=25)
    # Actual playback success still comes from the existing TTS timeout path.
    assert p.delivered(q, now=26, success=True)
    assert p.admit(q, captured_at=27, ended_at=28, started_at=29)
    assert p.answer('재개해', q, captured_at=27, now=30, evidence=SAFE,
                    request=p.request) == WORK
    assert p.answer('재개해', q, captured_at=27, now=30, evidence=SAFE,
                    request=p.request) is None


@pytest.mark.parametrize('stage', ['ack', 'tts_start', 'tts_finish', 'expire', 'tts_failure'])
def test_question_expiry_or_tts_failure_still_preserves_work(stage):
    p, q = unregistered()
    if stage == 'ack':
        assert not p.registered(q, WORK, 3, now=q.valid_until, valid_state=True)
    elif stage == 'expire':
        assert p.expire(now=q.valid_until)
    else:
        assert p.registered(q, WORK, 3, now=8, valid_state=True)
        if stage == 'tts_start':
            assert not p.tts_started(q, now=q.valid_until)
        else:
            assert p.tts_started(q, now=25)
            assert not p.delivered(q, now=26 if stage == 'tts_failure' else q.valid_until,
                                   success=stage != 'tts_failure')
    assert p.work == WORK and p.question is None


@pytest.mark.parametrize('text,end', [('종료', True), ('작업 종료해', True), ('이 작업 종료해', True),
    ('계속하지 말고 종료해', True), ('종료하지 마', False), ('종료 안 할게', False),
    ('종료하지 말고 이어서 해', False), ('아니', False), ('아니요', False)])
def test_ending_negation_and_question_rejection_have_distinct_lifetimes(text, end):
    from ready2go_voice.core.recovery_confirmation import TaskEndCandidate
    p, q = ready()
    result = p.answer(text, q, captured_at=4, now=6, evidence=SAFE, request=p.request)
    assert isinstance(result, TaskEndCandidate) is end
    assert p.work == WORK  # 후보는 종료 수락/물리 완료가 아닙니다.
    assert p.question is None


def independent_ready():
    p, q = ready()
    p.invalidate()
    request = p.begin_independent(WORK, now=20, unique_target=True)
    assert request and request.request_id != q.question_id
    assert p.admit_independent(request, captured_at=21, ended_at=22, started_at=23)
    return p, request


def test_independent_resume_after_expiry_separate_stt_and_whole_budget_once():
    p, request = independent_ready()
    assert p.independent_stt(request, '이어서 해', now=24)
    # ACK may occur after the already completed STT budget, within whole budget.
    assert p.independent_registered(request, WORK, p.revision, now=40, valid_state=True)
    assert p.independent_candidate(request, now=41, evidence=SAFE) == WORK
    assert p.independent_candidate(request, now=41, evidence=SAFE) is None
    assert p.work == WORK


@pytest.mark.parametrize('stage', ['stt', 'whole', 'unknown', 'no_ack', 'unsafe'])
def test_independent_failure_preserves_work(stage):
    p, request = independent_ready()
    if stage == 'stt':
        assert not p.independent_stt(request, '이어서 해', now=23+POLICY_CFG['resume_stt_result_timeout_sec']+0.000001)
    elif stage == 'unknown':
        assert not p.independent_stt(request, '응', now=24)
    else:
        assert p.independent_stt(request, '이어서 해', now=24)
        if stage == 'whole':
            assert not p.independent_registered(request, WORK, p.revision,
                now=21+POLICY_CFG['resume_independent_request_timeout_sec']+0.000001, valid_state=True)
        else:
            if stage == 'unsafe':
                assert p.independent_registered(request, WORK, p.revision, now=25, valid_state=True)
            assert p.independent_candidate(request, now=26, evidence=Evidence()) is None
    assert p.work == WORK and p.independent is None


def test_old_question_recording_not_reclassified_as_independent():
    p, q = ready()
    p.invalidate()
    request = p.begin_independent(WORK, now=3, unique_target=True)
    assert not p.admit_independent(request, captured_at=4, ended_at=4.5, started_at=5)
    assert p.work == WORK


def test_voice_restart_requires_fresh_c_state_runner_restart_discards_work():
    p, q = ready()
    p.voice_restarted()
    assert p.work == WORK and p.question is None
    assert p.begin_independent(WORK, now=20, unique_target=True) is None
    assert p.stopped(WORK, 3)
    assert p.begin_independent(WORK, now=20, unique_target=True)
    assert p.track_boot('new_boot', valid_state=True)
    assert p.work is None and p.independent is None


def test_drop_independent_request_cannot_restore_old_run_resume():
    p, q, _ = ready_new_start()
    request = p.begin_independent(DROP, now=20, unique_target=True)
    assert p.admit_independent(request, captured_at=21, ended_at=22, started_at=23)
    assert p.independent_stt(request, '이어서 해', now=24)
    assert p.independent_registered(request, DROP, p.revision, now=25, valid_state=True)
    assert p.independent_candidate(request, now=26, evidence=RESTORED) is None
    assert p.work == DROP


def test_only_fresh_current_c_completion_retires_saved_work():
    p, q = ready()
    assert not p.completed(WORK, 2, valid_state=True)
    assert not p.completed(replace(WORK, task='other'), 3, valid_state=True)
    assert not p.completed(WORK, 3, valid_state=False)
    assert p.work == WORK
    assert p.completed(WORK, 3, valid_state=True)
    assert p.work is None and p.question is None
    assert not p.stopped(WORK, 4)


@pytest.mark.parametrize('path', ['question', 'independent'])
def test_explicit_end_retires_same_event_even_with_higher_seq_but_allows_new_event(path):
    from ready2go_voice.core.recovery_confirmation import TaskEndCandidate
    if path == 'question':
        p, q = ready()
        candidate = p.answer('작업 종료해', q, captured_at=4, now=6,
                             evidence=SAFE, request=p.request)
    else:
        p, request = independent_ready()
        assert p.independent_stt(request, '작업 종료해', now=24)
        assert p.independent_registered(request, WORK, p.revision, now=25, valid_state=True)
        candidate = p.independent_candidate(request, now=26, evidence=SAFE)
    assert isinstance(candidate, TaskEndCandidate) and candidate.work == WORK
    assert p.work == WORK
    assert p.ended(candidate.work, valid_state=True)
    assert p.work is None
    assert not p.stopped(WORK, 100)
    assert p.begin_independent(WORK, now=30, unique_target=True) is None
    other = replace(WORK, stop='new_event', task='new_run')
    assert p.stopped(other, 101)
    request = p.begin_independent(other, now=31, unique_target=True)
    assert p.admit_independent(request, captured_at=32, ended_at=33, started_at=34)
    assert p.independent_stt(request, '이어서 해', now=35)
    assert p.independent_registered(request, other, p.revision, now=36, valid_state=True)
    assert p.independent_candidate(request, now=37, evidence=SAFE) == other


@pytest.mark.parametrize('callback', ['stt', 'candidate'])
@pytest.mark.parametrize('stale', ['old_object', 'forged_same_id', 'none'])
def test_stale_independent_callbacks_preserve_current_request_and_single_consumption(callback, stale):
    p, old = independent_ready()
    current = p.begin_independent(WORK, now=30, unique_target=True)
    assert current.request_id != old.request_id
    assert p.admit_independent(current, captured_at=31, ended_at=32, started_at=33)
    if callback == 'candidate':
        assert p.independent_stt(current, '이어서 해', now=35)
        assert p.independent_registered(current, WORK, p.revision, now=36, valid_state=True)
    state = (p.independent, p.independent_audio, p.independent_result, p.independent_ack,
             p.audio_end, p.work, p.revision)
    previous = {'old_object': old, 'forged_same_id': replace(old, request_id=current.request_id),
                'none': None}[stale]
    if callback == 'stt':
        assert not p.independent_stt(previous, '이어서 해', now=34)
    else:
        assert p.independent_candidate(previous, now=37, evidence=SAFE) is None
    assert state == (p.independent, p.independent_audio, p.independent_result, p.independent_ack,
                     p.audio_end, p.work, p.revision)
    if callback == 'stt':
        assert p.independent_stt(current, '이어서 해', now=35)
        assert p.independent_registered(current, WORK, p.revision, now=36, valid_state=True)
    assert p.independent_candidate(current, now=37, evidence=SAFE) == WORK
    assert p.independent_candidate(current, now=37, evidence=SAFE) is None


def test_current_independent_candidate_expiry_still_invalidates_only_current_request():
    p, request = independent_ready()
    assert p.independent_stt(request, '이어서 해', now=24)
    assert p.independent_registered(request, WORK, p.revision, now=25, valid_state=True)
    assert p.independent_candidate(request,
        now=21+POLICY_CFG['resume_independent_request_timeout_sec']+0.000001, evidence=SAFE) is None
    assert p.independent is None and p.work == WORK


def test_same_work_seq_reuses_receipt_but_consumption_rechecks_safety():
    p, q = ready()
    receipt = p.request
    assert p.stopped(WORK, 3)
    assert p.question is q and p.request is receipt
    assert not p.stopped(WORK, 3)  # duplicate status is still rejected
    assert p.question is q and p.request is receipt
    assert p.answer('재개해', q, captured_at=4, now=6, evidence=Evidence(),
                    request=receipt) is None
    assert p.work == WORK and p.question is None


def test_independent_same_state_reuses_recording_and_meaning_after_new_seq(monkeypatch):
    p, request = independent_ready()
    assert p.independent_stt(request, '이어서 해', now=24)
    audio, result = p.independent_audio, p.independent_result
    assert p.independent_registered(request, WORK, 3, now=25, valid_state=True)
    assert p.stopped(WORK, 4)
    assert p.independent_audio is audio and p.independent_result is result
    assert p.independent_ack == 25
    # The same recording's order and semantic classification are not rerun.
    def must_not_classify_again(text):
        raise AssertionError('already classified recording')
    monkeypatch.setattr('ready2go_voice.core.recovery_confirmation.safety_utterance',
                        must_not_classify_again)
    assert p.independent_candidate(request, now=26, evidence=SAFE) == WORK
    assert p.independent_candidate(request, now=26, evidence=SAFE) is None


@pytest.mark.parametrize('change', ['new_halt', 'boot', 'voice_restart', 'semantic_conflict'])
def test_reused_independent_checks_invalidated_by_actual_state_change(change):
    p, request = independent_ready()
    assert p.independent_stt(request, '이어서 해', now=24)
    assert p.independent_registered(request, WORK, 3, now=25, valid_state=True)
    if change == 'new_halt':
        assert p.stopped(replace(WORK, stop='new_halt'), 4)
    elif change == 'boot':
        assert p.track_boot('next_boot', valid_state=True)
    elif change == 'voice_restart':
        p.voice_restarted()
    else:
        assert not p.stopped(replace(WORK, cause='SENSOR_INVALID'), 4)
        assert not p.current_state_confirmed
    assert p.independent_candidate(request, now=26, evidence=SAFE) is None
    assert p.independent is None


def test_old_semantic_conflict_does_not_discard_current_receipt():
    p, q = ready()
    receipt = p.request
    assert not p.stopped(replace(WORK, cause='SENSOR_INVALID'), 1)
    assert p.request is receipt and p.question is q
    assert p.answer('재개해', q, captured_at=4, now=6, evidence=SAFE,
                    request=receipt) == WORK


@pytest.mark.parametrize('past_seq', [3, 4])
def test_new_semantic_conflict_records_floor_and_old_status_ack_cannot_revive(past_seq):
    p, request = independent_ready()  # Confirmed WORK seq2.
    assert p.independent_stt(request, '이어서 해', now=24)
    assert p.independent_registered(request, WORK, 2, now=25, valid_state=True)
    assert not p.stopped(replace(WORK, cause='SENSOR_INVALID'), 4)
    assert p.revision == 4 and p.sequences[('boot', 'run1', 'stop1')] == 4
    assert p.work == WORK and not p.current_state_confirmed
    assert not p.stopped(WORK, past_seq)
    assert not p.current_state_confirmed
    assert p.begin_independent(WORK, now=26, unique_target=True) is None
    assert not p.independent_registered(request, WORK, past_seq, now=26, valid_state=True)
    assert p.independent_candidate(request, now=27, evidence=SAFE) is None
    # A fresh, valid, original semantic state may reconfirm at a higher seq.
    assert p.stopped(WORK, 5) and p.current_state_confirmed
    fresh = p.begin_independent(WORK, now=30, unique_target=True)
    assert fresh and p.admit_independent(fresh, captured_at=31, ended_at=32, started_at=33)
    assert p.independent_stt(fresh, '이어서 해', now=34)
    assert not p.independent_registered(fresh, WORK, past_seq, now=35, valid_state=True)
    assert p.independent_candidate(fresh, now=36, evidence=SAFE) is None
    fresh = p.begin_independent(WORK, now=40, unique_target=True)
    assert fresh and p.admit_independent(fresh, captured_at=41, ended_at=42, started_at=43)
    assert p.independent_stt(fresh, '이어서 해', now=44)
    assert p.independent_registered(fresh, WORK, 6, now=45, valid_state=True)
    assert p.independent_candidate(fresh, now=46, evidence=SAFE) == WORK
    assert p.independent_candidate(fresh, now=46, evidence=SAFE) is None


@pytest.mark.parametrize('bad_work,bad_seq', [
    (replace(WORK, session='other-boot'), 10),
    (replace(WORK, cause=''), 10), (replace(WORK, skill=' '), 10),
    (replace(WORK, task=''), 10), (WORK, True), (WORK, -1), (WORK, '10'),
])
def test_invalid_state_never_advances_conflict_floor(bad_work, bad_seq):
    p, q = ready()
    assert not p.stopped(bad_work, bad_seq)
    assert p.revision == 2 and p.sequences[('boot', 'run1', 'stop1')] == 2
    assert not p._ack_current(WORK, 10, valid_state=False)
    assert p.revision == 2
    assert p.stopped(WORK, 3) and p.question is q
