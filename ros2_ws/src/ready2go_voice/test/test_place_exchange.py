"""#43 E exchange/STT control-flow mocks; no C registration or device evidence."""
from dataclasses import replace
from itertools import count
import threading
import pytest
from ready2go_voice.core.place_exchange import PlaceExchange
from ready2go_voice.core.skill_confirmation import PlaceWork
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.adapters.audio import Recording


def exchange(cfg):
    ids = count(1)
    return PlaceExchange(cfg, item_names={'hammer': '망치'},
                         question_id=lambda: f'q{next(ids)}')


def question(ex, *, run='run', step='place', boot='boot', observation='not_found', destination='handover_zone'):
    return ex.begin(PlaceWork(run, step, destination, ('hammer',)),
                    boot_id=boot, observation=observation)


def ready(ex, q, *, asked=0, delivered=1):
    msg = ex.asked(q, now=asked, final_timeout_sec=100)
    assert msg['answer'] == 'asked'
    assert ex.delivered(q, now=delivered, success=True)
    return msg


def answer(ex, q, text, *, start=2, sdk=3, now=4):
    capture = ex.reserve_audio(q)
    request = ex.admit(q, capture, captured_at=start, ended_at=sdk, started_at=sdk)
    return ex.answer(q, text, captured_at=start, now=now, request=request)


@pytest.mark.parametrize('text,wire', [('네', 'yes'), ('아니요', 'no')])
def test_wire_identity_and_single_consumption(cfg, text, wire):
    ex = exchange(cfg)
    q = question(ex)
    asked = ready(ex, q)
    assert asked == dict(intent='confirm', run_id='run', step_id='place', boot_id='boot',
                         question_id='q1', attempt=1, answer='asked')
    response = answer(ex, q, text)
    assert response.message == dict(asked, answer=wire)
    assert response.next_question is None
    assert ex.policy.final.success is (wire == 'yes')
    assert answer(ex, q, text) is None
    assert question(ex) is None


def test_ambiguity_new_identity_and_duplicate_do_not_extend_deadline(cfg):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    assert question(ex) is q
    assert ex.asked(q, now=8, final_timeout_sec=100)['question_id'] == 'q1'
    first = answer(ex, q, '잘 모르겠어요')
    q2 = first.next_question
    assert first.message['answer'] == 'ambiguous'
    assert first.message['attempt'] == 1
    assert q2.question_id != q.question_id and q2.attempt == 2
    assert ex.policy.final_until == 100
    assert ex.fail(q, answer='error') is None
    ready(ex, q2, asked=20, delivered=21)
    assert ex.policy.final_until == 100
    second = answer(ex, q2, '글쎄요', start=22, sdk=23, now=24)
    assert second.message['answer'] == 'ambiguous'
    assert second.message['attempt'] == 2
    assert second.next_question is None and not ex.policy.final.success


@pytest.mark.parametrize('observation', ['error', 'REGION_NOT_VISIBLE', None])
def test_observation_errors_never_create_user_success(cfg, observation):
    ex = exchange(cfg)
    assert question(ex, observation=observation) is None
    assert ex.policy.final.success is False
    assert ex.policy.final.basis == 'observation_error'


def test_vision_and_drawer_preserve_existing_policy(cfg):
    ex = exchange(cfg)
    assert question(ex, observation='found') is None
    assert ex.policy.final.success and ex.policy.final.basis == 'vision'
    assert question(ex, run='drawer-run', destination='drawer') is None
    assert ex.active is None


def test_stale_or_invalid_work_cannot_clear_current_question(cfg):
    ex = exchange(cfg)
    old = question(ex, run='old')
    ex.invalidate()
    q = question(ex, run='current')
    ready(ex, q)
    assert question(ex, run='old') is None
    assert question(ex, run='bad', destination='drawer') is None
    assert ex.current(q)
    assert ex.fail(old, answer='error') is None


def test_old_boot_and_copied_envelopes_cannot_answer(cfg):
    ex = exchange(cfg)
    old = question(ex)
    ready(ex, old)
    q = question(ex, run='new', boot='new-boot')
    ready(ex, q)
    assert question(ex, run='third', boot='boot') is None
    assert ex.current(q)
    for forged in (old, replace(q), replace(q, boot_id='other'), replace(q, question_id='other')):
        assert ex.reserve_audio(forged) is None
        assert ex.asked(forged, now=5, final_timeout_sec=100) is None
        assert ex.fail(forged, answer='error') is None
    assert answer(ex, q, '네').message['boot_id'] == 'new-boot'


def test_tts_and_capture_authority(cfg):
    ex = exchange(cfg)
    q = question(ex)
    assert not ex.delivered(q, now=1, success=True)
    assert ex.reserve_audio(q) is None
    ready(ex, q)
    capture = ex.reserve_audio(q)
    assert ex.reserve_audio(q) is None
    assert ex.admit(q, object(), captured_at=2, ended_at=3, started_at=3) is None
    assert ex.current(q)
    request = ex.admit(q, capture, captured_at=2, ended_at=3, started_at=3)
    assert ex.answer(q, '네', captured_at=2, now=4, request=replace(request)) is None
    assert ex.answer(q, '네', captured_at=2, now=4, request=request).message['answer'] == 'yes'


@pytest.mark.parametrize('sdk,accepted', [(10.999, True), (11, False), (11.001, False)])
def test_admission_exact_ten_stays_exclusive(cfg, sdk, accepted):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    request = ex.admit(q, ex.reserve_audio(q), captured_at=2, ended_at=3, started_at=sdk)
    assert (request is not None) is accepted


@pytest.mark.parametrize('now,wire', [(17.999, 'yes'), (18, 'expired'), (18.001, 'expired')])
def test_stt_exact_fifteen_stays_exclusive(cfg, now, wire):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    assert answer(ex, q, '네', now=now).message['answer'] == wire


@pytest.mark.parametrize('now,wire', [(99.999, 'yes'), (100, 'yes'), (100.001, 'expired')])
def test_whole_deadline_inclusive(cfg, now, wire):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q, delivered=90)
    assert answer(ex, q, '네', start=91, sdk=92, now=now).message['answer'] == wire


class STT:
    supports_request_boundary = True

    def __init__(self, clock, *, text='네', sdk=3, result=4, hook=lambda: None):
        self.clock, self.text, self.sdk, self.result, self.hook = clock, text, sdk, result, hook
        self.calls = 0

    def transcribe(self, path, timeout, *, before_request):
        assert path.exists() and timeout == 15
        self.hook()
        self.clock[0] = self.sdk
        if not before_request(self.sdk):
            raise TimeoutError('request rejected before SDK')
        self.calls += 1
        self.clock[0] = self.result
        return self.text


def recording(**changes):
    rec = Recording(b'\x00\x01' * 100, 2.5, 200, recording_started_monotonic=2,
                    recording_ended_monotonic=2.5)
    return replace(rec, **changes)


def session(cfg, stt, clock):
    # Any LLM/parser use fails: #43 has only classified STT.
    return VoiceSession(None, cfg, stt, clock=lambda: clock[0])


def test_session_uses_actual_request_boundary_without_llm(cfg):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    clock = [2.5]
    stt = STT(clock)
    response = session(cfg, stt, clock).confirm_audio(ex, q, recording())
    assert response.message['answer'] == 'yes' and stt.calls == 1


@pytest.mark.parametrize('sdk,result,wire,calls', [(11, 12, 'expired', 0), (3, 18, 'expired', 1)])
def test_session_boundary_rejection(cfg, sdk, result, wire, calls):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    clock = [2.5]
    stt = STT(clock, sdk=sdk, result=result)
    response = session(cfg, stt, clock).confirm_audio(ex, q, recording())
    assert response.message['answer'] == wire and stt.calls == calls


@pytest.mark.parametrize('changes', [dict(truncated=True), dict(recording_started_monotonic=0),
                                    dict(recording_ended_monotonic=None), dict(pcm=b'')])
def test_bad_recording_does_not_call_sdk(cfg, changes):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    clock = [2.5]
    stt = STT(clock)
    response = session(cfg, stt, clock).confirm_audio(ex, q, recording(**changes))
    assert response.message['answer'] == 'error' and stt.calls == 0


def test_halt_at_sdk_callback_wins_over_timeout(cfg):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    clock, cancel = [2.5], threading.Event()
    stt = STT(clock, hook=cancel.set)
    assert session(cfg, stt, clock).confirm_audio(ex, q, recording(), cancel=cancel) is None
    assert stt.calls == 0 and not ex.current(q)


def test_duplicate_worker_does_not_invalidate_first_worker(cfg):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    clock = [2.5]
    s = session(cfg, STT(clock), clock)
    responses = []
    s.stt.hook = lambda: responses.append(s.confirm_audio(ex, q, recording()))
    result = s.confirm_audio(ex, q, recording())
    assert responses == [None] and result.message['answer'] == 'yes'


def test_replaced_question_ignores_old_sdk_worker(cfg):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    clock = [2.5]
    newer = []
    def replace_work():
        newer.append(question(ex, run='new-run'))
        ready(ex, newer[0])
    stt = STT(clock, hook=replace_work)
    assert session(cfg, stt, clock).confirm_audio(ex, q, recording()) is None
    assert stt.calls == 0 and ex.current(newer[0])


def test_missing_boundary_and_fixed_silence_are_errors(cfg):
    for missing in (True, False):
        ex = exchange(cfg)
        q = question(ex)
        ready(ex, q)
        clock = [2.5]
        stt = STT(clock)
        stt.supports_request_boundary = not missing
        s = session(cfg, stt, clock)
        class Silent:
            def check(self, *args, **kwargs): return False
        s.speech_gate = Silent()
        response = s.confirm_audio(ex, q, recording(recording_mode='fixed'))
        assert response.message['answer'] == 'error' and stt.calls == 0


def test_failed_tts_and_expired_question_cannot_capture(cfg):
    ex = exchange(cfg)
    q = question(ex)
    ex.asked(q, now=0, final_timeout_sec=100)
    assert not ex.delivered(q, now=1, success=False)
    assert ex.reserve_audio(q) is None
    q = question(ex, run='next')
    ready(ex, q)
    assert ex.expire(q, now=100) is None
    assert ex.expire(q, now=100.001).message['answer'] == 'expired'
    assert ex.reserve_audio(q) is None


def test_late_stt_result_after_new_work_does_not_consume_new_question(cfg):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    clock = [2.5]
    newer = []
    class Late(STT):
        def transcribe(self, path, timeout, *, before_request):
            assert before_request(3)
            self.calls += 1
            newer.append(question(ex, run='new'))
            ready(ex, newer[0])
            clock[0] = 4
            return '네'
    stt = Late(clock)
    assert session(cfg, stt, clock).confirm_audio(ex, q, recording()) is None
    assert stt.calls == 1 and ex.current(newer[0]) and ex.capture is None


@pytest.mark.parametrize('text', ['', '  ', None])
def test_empty_stt_does_not_reask_or_succeed(cfg, text):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    clock = [2.5]
    response = session(cfg, STT(clock, text=text), clock).confirm_audio(ex, q, recording())
    assert response.message['answer'] == 'error' and response.next_question is None


def test_adapter_cannot_return_yes_without_admission_receipt(cfg):
    ex = exchange(cfg)
    q = question(ex)
    ready(ex, q)
    class SkippedBoundary(STT):
        def transcribe(self, *args, **kwargs): return '네'
    clock = [2.5]
    response = session(cfg, SkippedBoundary(clock), clock).confirm_audio(ex, q, recording())
    assert response.message['answer'] == 'error'
