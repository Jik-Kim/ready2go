"""P2 내부 제안의 의미 검사. 실제 ROS/복구/안전 정지 시험 아님."""
import pytest
from ready2go_voice.core.recovery_confirmation import (
    Evidence, RecoveryConfirmation, StoppedWork, safety_utterance,
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
