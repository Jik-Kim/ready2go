"""Policy/SDK-boundary mocks only. No hardware, API, TTS or C effects."""
from dataclasses import replace
from types import SimpleNamespace
import sys
import pytest
from ready2go_voice.core.recovery_confirmation import RecoveryConfirmation, Evidence, StoppedWork
from ready2go_voice.core.skill_confirmation import (
    PickObservation, pick_verified, PlaceWork, PlaceConfirmation, PlaceQuestion,
)
from ready2go_voice.adapters.api import WhisperSTT

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
WORK = StoppedWork('boot', 'halt', 'run', 'pick')
PLACE = PlaceWork('run', 'place', 'handover_zone', ('eraser', 'car_key', 'eraser'))
NAMES = {'eraser': '지우개', 'car_key': '차키'}
PICK = PickObservation('pick', 'pick', .011, True, True, True, True, True, True)


def ready(*, budget=20, until=100):
    p = make_recovery('boot', stt_result_timeout_sec=budget)
    assert p.stopped(WORK, 100)
    q = p.recovered(WORK, 101, SAFE, now=2, valid_until=until)
    assert delivered(p, q, now=3, success=True)
    return p, q


@pytest.mark.parametrize('width,ok', [(.0099, False), (.010, False), (.0101, True), (0, False),
    (None, False), (float('nan'), False), (float('inf'), False), (True, False)])
def test_pick_strict_width_boundary(width, ok):
    assert pick_verified(replace(PICK, width_m=width), lower_bound_m=.010) is ok


@pytest.mark.parametrize('field', ['closing_completed', 'width_valid', 'grasp_detected',
    'communication_ok', 'not_interrupted', 'lift_held'])
def test_pick_requires_same_completed_closing_grip_and_lift(field):
    assert not pick_verified(replace(PICK, **{field: False}), lower_bound_m=.010)
    assert not pick_verified(replace(PICK, **{field: None}), lower_bound_m=.010)
    assert not pick_verified(replace(PICK, grip_pick_id='old_pick'), lower_bound_m=.010)


def place_answer(policy, question, text, *, captured_at, now):
    receipt = policy.admit(question, captured_at=captured_at, ended_at=captured_at + .1,
                           started_at=captured_at + .2)
    return policy.answer(question, text, captured_at=captured_at, now=now, request=receipt)


def place_ready(**kwargs):
    p = PlaceConfirmation(item_names=NAMES, admission_window_sec=7, stt_result_timeout_sec=7, max_reasks=1, **kwargs)
    q = p.begin(PLACE, normal_observation=True, all_visible=False)
    assert p.delivered(q, now=1, success=True)
    return p, q


def test_place_non_detection_question_inventory_and_final_once():
    p, q = place_ready()
    for s in ('전달 트레이', '지우개 2개', '차키 1개', '총 3개'):
        assert s in q.text
    result = place_answer(p, q, '모두 있어요', captured_at=2, now=3)
    assert result.success and result.basis == 'user' and result.work == PLACE
    assert place_answer(p, q, '네', captured_at=2, now=3) is None
    assert p.begin(PLACE, normal_observation=True, all_visible=True) is None


def test_place_vision_and_user_evidence_are_distinct():
    p = PlaceConfirmation(item_names=NAMES, )
    result = p.begin(PLACE, normal_observation=True, all_visible=True)
    assert result.success and result.basis == 'vision'


def test_place_ambiguous_reasks_with_new_identity_and_tts():
    p, q = place_ready()
    other = place_answer(p, q, '아마 있는 것 같아요', captured_at=2, now=3)
    assert isinstance(other, PlaceQuestion) and other is not q
    assert place_answer(p, q, '네', captured_at=2, now=4) is None
    assert p.delivered(other, now=4, success=True)
    assert place_answer(p, other, '글쎄', captured_at=5, now=6) is None
    assert p.final is None or not p.final.success and p.question is None


@pytest.mark.parametrize('text', ['아니요', '없어요'])
def test_place_explicit_no_is_not_success(text):
    p, q = place_ready()
    result = place_answer(p, q, text, captured_at=2, now=3)
    assert not result.success and result.basis == 'user'


@pytest.mark.parametrize('captured,now', [(0, 3), (2, 10), (5, 3), (2, float('nan'))])
def test_place_past_audio_no_response_expiry_or_bad_time_never_succeeds(captured, now):
    p, q = place_ready()
    assert place_answer(p, q, '네', captured_at=captured, now=now) is None
    assert p.final is None or not p.final.success


def test_place_observation_error_unknown_tts_failure_interrupt_old_run():
    p = PlaceConfirmation(item_names=NAMES, admission_window_sec=7, stt_result_timeout_sec=7)
    assert p.begin(PLACE, normal_observation=False, all_visible=False) is None
    assert p.begin(replace(PLACE, step='unknown'), normal_observation=True, all_visible=None) is None
    q = p.begin(replace(PLACE, step='new_step'), normal_observation=True, all_visible=False)
    assert not p.delivered(q, now=1, success=False)
    assert place_answer(p, q, '네', captured_at=2, now=3) is None
    q = p.begin(replace(PLACE, step='next_step'), normal_observation=True, all_visible=False)
    p.invalidate()
    assert place_answer(p, q, '네', captured_at=2, now=3) is None
    new = p.begin(replace(PLACE, run='new'), normal_observation=True, all_visible=False)
    assert new.work.run == 'new' and place_answer(p, q, '네', captured_at=2, now=3) is None
    assert p.final is None or not p.final.success  # policy cannot apply C effect or success TTS


def test_place_unagreed_wait_or_reask_holds():
    p = PlaceConfirmation(item_names=NAMES, )
    q = p.begin(replace(PLACE, step='new_step'), normal_observation=True, all_visible=False)
    assert not p.delivered(q, now=1, success=True)
    p = PlaceConfirmation(item_names=NAMES, admission_window_sec=7, stt_result_timeout_sec=7)
    q = p.begin(PLACE, normal_observation=True, all_visible=False)
    assert p.delivered(q, now=1, success=True)
    assert place_answer(p, q, '아마', captured_at=2, now=3) is None


@pytest.mark.parametrize('elapsed,admitted', [(9.9, True), (10.0, True), (10.1, False)])
def test_actual_sdk_boundary_window_and_late_stt(elapsed, admitted):
    p, q = ready(until=100)
    receipt = p.admit(q, captured_at=4, ended_at=8, started_at=3+elapsed)
    assert (receipt is not None) is admitted
    result = p.answer('재개해', q, captured_at=4, now=15, evidence=SAFE, request=receipt)
    assert (result == WORK) is admitted  # valid receipt survives admission deadline


def test_stt_processing_expiry_separate_unagreed_budget_and_unreceipted_result():
    p, q = ready(budget=2)
    receipt = p.admit(q, captured_at=4, ended_at=5, started_at=6)
    assert p.answer('재개해', q, captured_at=4, now=8, evidence=SAFE, request=receipt) is None
    p, q = ready(budget=None)
    assert p.admit(q, captured_at=4, ended_at=5, started_at=6) is None
    p, q = ready()
    assert p.answer('재개해', q, captured_at=4, now=6, evidence=SAFE) is None


@pytest.mark.parametrize('captured,ended,started', [(2.9, 6, 7), (4, 3, 7), (4, 8, 7),
    (float('nan'), 8, 9), (4, 8, 100)])
def test_tts_overlap_old_recording_queue_or_invalid_request_rejected(captured, ended, started):
    p, q = ready()
    assert p.admit(q, captured_at=captured, ended_at=ended, started_at=started) is None


def test_sequence_per_event_retired_event_boot_and_ordinary_cancel():
    p, q = ready()
    assert p.ordinary_cancel() == WORK and p.question is q
    assert not p.stopped(WORK, 101) and not p.stopped(WORK, 100)
    new = replace(WORK, stop='halt2')
    assert p.stopped(new, 102)  # new event advances current boot sequence
    assert not p.stopped(WORK, 9999)  # late old event must not become current
    assert p.answer('재개해', q, captured_at=4, now=6, evidence=SAFE) is None
    assert not p.track_boot('newboot', valid_state=False)
    assert p.track_boot('newboot', valid_state=True)
    assert not p.stopped(new, 2)
    assert not p.track_boot('boot', valid_state=True)


def test_question_abandon_failures_duplicates_and_unknown_b_do_not_resume():
    p, q = ready()
    receipt = p.admit(q, captured_at=4, ended_at=5, started_at=6)
    assert p.answer('재개해', q, captured_at=4, now=7, evidence=Evidence(), request=receipt) is None
    assert p.answer('재개해', q, captured_at=4, now=7, evidence=SAFE, request=receipt) is None
    p, q = ready()
    receipt = p.admit(q, captured_at=4, ended_at=5, started_at=6)
    assert p.answer('포기', q, captured_at=4, now=7, evidence=SAFE, request=receipt) is None
    assert p.work is not None
    p, q = ready()
    p.invalidate()  # API/TTS failure, timeout or re-stop adapter boundary
    assert p.admit(q, captured_at=4, ended_at=5, started_at=6) is None


@pytest.mark.parametrize('sdk_delay,wav_delay,allow', [(1, 1, True), (2, 2, False)])
def test_whisper_guard_includes_client_and_wav_delay_before_create(tmp_path, monkeypatch, sdk_delay, wav_delay, allow):
    import ready2go_voice.adapters.api as api
    p, q = ready()
    clock = [10.0]  # earlier whisper_requested could have been in time
    calls = []
    class Client:
        def __init__(self, **kwargs):
            clock[0] += sdk_delay
            self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kwargs):
            calls.append(clock[0])
            return SimpleNamespace(text='재개해')
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=Client))
    wav = tmp_path/'record.wav'; wav.write_bytes(b'test')
    class DelayedPath:
        def __init__(self, name): self.name = name
        def open(self, *args):
            clock[0] += wav_delay
            return wav.open(*args)
    monkeypatch.setattr(api, 'Path', DelayedPath)
    receipts = []
    def guard(at):
        receipts.append(p.admit(q, captured_at=4, ended_at=8, started_at=at))
        return receipts[-1] is not None
    stt = WhisperSTT({'stt_model': 'whisper-1'}, [], clock=lambda: clock[0])
    if allow:
        assert stt.transcribe(wav, 5, before_request=guard) == '재개해'
        assert calls == [12.0]
    else:
        with pytest.raises(TimeoutError, match='NOT_ADMITTED'):
            stt.transcribe(wav, 5, before_request=guard)
        assert calls == []  # no remote request / robot action


def test_config_unagreed_budgets_are_null(cfg, tmp_path):
    import yaml
    from ready2go_voice.core.config import load_config
    cfg.update(resume_stt_result_timeout_sec=None, place_admission_window_sec=None, place_stt_result_timeout_sec=None, place_max_reasks=None)
    path = tmp_path/'cfg.yaml'; path.write_text(yaml.safe_dump(cfg))
    loaded = load_config(path)
    assert loaded['resume_stt_result_timeout_sec'] is None
    assert loaded['place_admission_window_sec'] is None
    for value in (float('nan'), True, -1, 0):
        cfg['resume_stt_result_timeout_sec'] = value
        path.write_text(yaml.safe_dump(cfg))
        with pytest.raises(ValueError): load_config(path)


def test_boot_global_seq_cannot_roll_back_halt_or_other_run():
    p = make_recovery('boot', stt_result_timeout_sec=20)
    assert p.stopped(WORK, 10)
    h2 = replace(WORK, stop='halt2')
    assert p.stopped(h2, 20)
    assert not p.stopped(WORK, 11)
    assert not p.stopped(replace(WORK, task='other', stop='h3'), 15)
    assert p.work == h2 and p.revision == 20


def test_local_context_expiry_is_separate_from_ten_second_admission():
    p, q = ready(budget=20, until=14)
    receipt = p.admit(q, captured_at=4, ended_at=8, started_at=13)
    assert receipt  # 10.0 seconds admission included
    assert p.answer('재개해', q, captured_at=4, now=14, evidence=SAFE, request=receipt) is None
    assert p.question is None


def test_drawer_place_lifo_is_outside_confirmation_policy():
    p = PlaceConfirmation(item_names=NAMES, admission_window_sec=7, stt_result_timeout_sec=7)
    assert p.begin(replace(PLACE, destination='drawer_top'), normal_observation=True, all_visible=False) is None
    assert p.begin(replace(PLACE, destination='drawer_top'), normal_observation=True, all_visible=True) is None


def test_place_unknown_display_names_do_not_read_internal_keys():
    p = PlaceConfirmation(admission_window_sec=7, stt_result_timeout_sec=7)
    assert p.begin(PLACE, normal_observation=True, all_visible=False) is None
    p = PlaceConfirmation(item_names=NAMES, admission_window_sec=7, stt_result_timeout_sec=7)
    q = p.begin(PLACE, normal_observation=True, all_visible=False)
    assert 'eraser' not in q.text and 'car_key' not in q.text
    assert '지우개' in q.text and '차키' in q.text


def test_same_procedure_replay_does_not_reset_reask_or_terminal_state():
    p, q = place_ready()
    assert p.begin(PLACE, normal_observation=True, all_visible=False) is q
    second = place_answer(p, q, '글쎄', captured_at=2, now=3)
    assert p.begin(PLACE, normal_observation=True, all_visible=False) is second
    assert p.delivered(second, now=4, success=True)
    assert place_answer(p, second, '글쎄', captured_at=5, now=6) is None
    assert not p.final.success
    assert p.begin(PLACE, normal_observation=True, all_visible=True) is None
    assert p.begin(replace(PLACE, items=('eraser',)), normal_observation=True, all_visible=False) is None
    assert p.begin(replace(PLACE, step='next'), normal_observation=True, all_visible=False)


@pytest.mark.parametrize('stage', ['tts', 'admission', 'stt'])
def test_place_failure_cannot_create_third_question(stage):
    p, q = place_ready()
    if stage == 'tts':
        assert not p.delivered(q, now=2, success=False)
    elif stage == 'admission':
        assert p.admit(q, captured_at=2, ended_at=3, started_at=8) is None
    else:
        receipt = p.admit(q, captured_at=2, ended_at=3, started_at=4)
        assert p.answer(q, '네', captured_at=2, now=11, request=receipt) is None
    assert p.question is None and not p.final.success
    assert p.begin(PLACE, normal_observation=True, all_visible=False) is None


def test_place_admitted_audio_survives_admission_deadline_within_stt_budget():
    p, q = place_ready()
    receipt = p.admit(q, captured_at=2, ended_at=6, started_at=7)
    result = p.answer(q, '네', captured_at=2, now=12, request=receipt)
    assert result.success and result.basis == 'user'


@pytest.mark.parametrize('times', [(2, 1, 3), (0, 2, 3), (2, 4, 3), (True, 2, 3),
    (2, 3, float('nan'))])
def test_place_audio_ordering_and_invalid_evidence(times):
    p, q = place_ready()
    assert p.admit(q, captured_at=times[0], ended_at=times[1], started_at=times[2]) is None
    assert not p.final.success
