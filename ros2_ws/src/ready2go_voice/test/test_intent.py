import json
import threading
import time
import pytest
from ready2go_voice.core.intent import IntentParser
from ready2go_voice.core.session import VoiceSession


@pytest.mark.parametrize('text,kind,targets', [
    ('지우개 가져다줘', 'find_item', ['eraser']),
    ('자동차 열쇠 찾아줘', 'find_item', ['car_key']),
    ('지우개', 'clarify', []),
    ('사과 가져다줘', 'unknown', []),
    ('지우개 아래 서랍에 넣어줘', 'unknown', []),
    ('지우개 찾지 마', 'unknown', []),
    ('지우개랑 립밤 가져다줘', 'clarify', []),
    ('멈춰', 'cancel', []), ('지금 뭐 해', 'status', []),
])
def test_rules_use_registered_items_and_hold_unsupported(ontology, schema, cfg, text, kind, targets):
    doc = IntentParser(ontology, schema, cfg).parse(text)
    assert (doc['intent'], doc['targets']) == (kind, targets)
    assert doc['source']['execution_allowed'] == (kind == 'find_item')


@pytest.mark.parametrize('raw', [
    '{bad', {'intent': 'find_item', 'targets': ['apple'], 'confidence': 1},
    {'intent': 'find_item', 'targets': ['lip_balm'], 'confidence': 1},
    {'intent': 'find_item', 'targets': ['eraser'], 'confidence': .1},
    {'intent': 'achieve_goal', 'confidence': 1},
    {'intent': 'cancel', 'confidence': 1},
    {'intent': 'find_item', 'targets': ['eraser', 'car_key'], 'confidence': 1},
])
def test_invalid_llm_cannot_change_named_target(ontology, schema, cfg, raw):
    parser = IntentParser(ontology, schema, cfg, lambda *_: json.dumps(raw) if isinstance(raw, dict) else raw)
    doc = parser.parse('지우개 가져다줘')
    assert doc['targets'] == ['eraser']
    assert doc['source']['llm_validation'] == 'failed'
    assert doc['source']['fallback_used']


@pytest.mark.parametrize('kind', ['unknown', 'clarify'])
def test_normal_hold_is_not_validation_failure(ontology, schema, cfg, kind):
    parser = IntentParser(ontology, schema, cfg, lambda *_: json.dumps({'intent': kind, 'targets': [], 'confidence': 1}))
    doc = parser.parse('글씨 잘못 쓴 걸 지워주는 물건 가져다줘')
    assert doc['intent'] == kind
    assert doc['source']['llm_validation'] == 'passed'
    assert not doc['source']['fallback_used']


@pytest.mark.parametrize('text', ['연필 찾아줘', '연필 자국 없애는 물건 가져다줘'])
def test_unnamed_llm_target_is_held(ontology, schema, cfg, text):
    parser = IntentParser(ontology, schema, cfg, lambda *_: json.dumps(
        {'intent': 'find_item', 'targets': ['eraser'], 'confidence': .95}))
    doc = parser.parse(text)
    assert doc['intent'] == 'clarify' and doc['targets'] == []
    assert not doc['source']['execution_allowed']
    assert doc['source']['llm_validation'] == 'passed'


def test_late_response_dropped_and_single_call_slot(ontology, schema, cfg):
    cfg['llm_timeout_sec'] = .02
    release = threading.Event()
    calls = []
    def late(*args):
        calls.append(args)
        release.wait(1)
        return json.dumps({'intent': 'find_item', 'targets': ['lip_balm'], 'confidence': 1})
    parser = IntentParser(ontology, schema, cfg, late)
    try:
        first = parser.parse('지우개 가져다줘')
        second = parser.parse('지우개 가져다줘')
        assert first['targets'] == second['targets'] == ['eraser']
        assert first['source']['llm_validation'] == 'not_returned'
        assert len(calls) == 1
    finally:
        release.set()
    time.sleep(.01)
    assert first['targets'] == ['eraser']  # 늦은 작업은 반환 문서를 변경할 수 없음


def test_api_error_falls_back_and_no_exception_secret(ontology, schema, cfg):
    def fail(*_):
        raise RuntimeError('SECRET_VALUE')
    doc = IntentParser(ontology, schema, cfg, fail).parse('지우개 찾아줘')
    assert doc['targets'] == ['eraser'] and 'SECRET_VALUE' not in json.dumps(doc)


def test_deadline_exhaustion_does_not_call_llm(ontology, schema, cfg):
    calls = []
    doc = IntentParser(ontology, schema, cfg, lambda *a: calls.append(a)).parse('지우개 찾아줘', deadline=0)
    assert not calls and not doc['source']['llm_called']


def test_evaluation_blocks_all_intents_and_execution_deduplicates(ontology, schema, cfg):
    parser = IntentParser(ontology, schema, cfg)
    session = VoiceSession(parser, cfg)
    for text in ('지우개 찾아줘', '멈춰', '지금 뭐 해'):
        assert not session.should_publish(parser.parse(text))
    cfg['evaluation_mode'] = False
    doc = parser.parse('지우개 찾아줘')
    assert session.should_publish(doc) and session.should_publish(doc)
    session.mark_published(doc)
    assert not session.should_publish(doc)
    assert session.should_publish(parser.parse('멈춰'))


def test_audio_stt_cleans_file_and_marks_speech_end(ontology, schema, cfg, tmp_path):
    from ready2go_voice.adapters.audio import Recording
    paths = []
    class STT:
        def transcribe(self, path, timeout):
            paths.append(path)
            assert path.exists() and timeout > 0
            return '지우개 찾아줘'
    now = time.monotonic()
    session = VoiceSession(IntentParser(ontology, schema, cfg), cfg, STT())
    doc = session.audio(Recording(b'\0\0' * 1600, now, 100))
    assert doc['targets'] == ['eraser'] and doc['source']['speech_ended_unix'] == 100
    assert not paths[0].exists()


def test_late_stt_no_interpretation_or_publication(ontology, schema, cfg):
    from ready2go_voice.adapters.audio import Recording
    release = threading.Event()
    cfg['stt_timeout_sec'] = .01
    class STT:
        def transcribe(self, path, timeout):
            release.wait(1)
            return '지우개 찾아줘'
    session = VoiceSession(IntentParser(ontology, schema, cfg), cfg, STT())
    try:
        doc = session.audio(Recording(b'\0\0', time.monotonic(), 100))
        assert doc['intent'] == 'clarify' and not doc['source']['execution_allowed']
    finally:
        release.set()


@pytest.mark.parametrize('text', [
    '지우개 가져다주지 마', '지우개 안 찾아도 돼', '지우개가 얼마인지 알려줄래',
])
@pytest.mark.parametrize('mode', ['offline', 'hallucination', 'api_error'])
def test_nonexecution_context_cannot_become_pick(ontology, schema, cfg, text, mode):
    def llm(*_):
        if mode == 'api_error':
            raise RuntimeError('api unavailable')
        return {'intent': 'find_item', 'targets': ['eraser'], 'confidence': .99}
    parser = IntentParser(ontology, schema, cfg, None if mode == 'offline' else llm)
    doc = parser.parse(text)
    assert doc['intent'] in ('unknown', 'clarify') and doc['targets'] == []
    assert not doc['source']['execution_allowed']
    # 직접 의미검증 경로도 같은 보류를 적용합니다.
    held = parser.validate({'intent': 'find_item', 'targets': ['eraser'], 'confidence': .99}, text)
    assert held['intent'] in ('unknown', 'clarify') and held['targets'] == []


@pytest.mark.parametrize('text', [
    '지우개 찾아줘', '지우개 찾아주세요', '지우개 찾아줄래', '지우개 꺼내줘',
    '지우개 꺼내주세요', '지우개 꺼내줄래', '지우개 가져다줘', '지우개 가져다주세요',
    '지우개 가져다줄래', '지우개 가져와', '지우개 가져와줘', '지우개 갖다줘',
    '지우개 주세요', '지우개 줄래', '지우개를 좀 가져다줘', '지우개 하나 주세요',
    '저한테 지우개 가져다주세요', '혹시 지우개 좀 찾아줄래요?',
    '지우개가 필요해', '지우개 주면 좋겠어요',
    '자동차 열쇠 찾아줘',
])
@pytest.mark.parametrize('use_llm', [False, True])
def test_explicit_positive_requests_preserved(ontology, schema, cfg, text, use_llm):
    parser = IntentParser(ontology, schema, cfg)
    target = sorted(parser.mentioned(text))
    if use_llm:
        parser.llm = lambda *_: {'intent': 'find_item', 'targets': target, 'confidence': .99}
    doc = parser.parse(text)
    assert doc['intent'] == 'find_item' and doc['targets'] == target
    assert doc['source']['execution_allowed']


def test_all_registered_names_and_aliases_keep_explicit_requests(ontology, schema, cfg):
    parser = IntentParser(ontology, schema, cfg)
    for key, item in parser.items.items():
        for alias in [key, item['name_ko'], *item.get('aliases_ko', [])]:
            named = parser.mentioned(alias)
            if named != {key}:  # 겹치는 별칭은 원래도 모호성 보류 대상입니다.
                continue
            doc = parser.parse(alias + ' 가져다줘')
            assert doc['intent'] == 'find_item' and doc['targets'] == [key]
            assert doc['source']['execution_allowed']


@pytest.mark.parametrize('text', [
    '지우개 찾아줘.', '지우개 좀 가져다줘.',
    '위 서랍에 있는 지우개 꺼내줘.', '지우개가 필요한데 가져다줄래?',
])
@pytest.mark.parametrize('use_llm', [False, True])
def test_user_positive_examples_preserved(ontology, schema, cfg, text, use_llm):
    parser = IntentParser(ontology, schema, cfg)
    if use_llm:
        parser.llm = lambda *_: {'intent': 'find_item', 'targets': ['eraser'], 'confidence': .99}
    doc = parser.parse(text)
    assert doc['intent'] == 'find_item' and doc['targets'] == ['eraser']
    assert doc['source']['execution_allowed']
    assert doc['source']['llm_called'] == use_llm
    assert doc['source']['fallback_used'] == (not use_llm)


@pytest.mark.parametrize('text', [
    '위 서랍에 있는 지우개 꺼내주지 마.',
    '위 서랍에 있는 지우개가 얼마인지 알려줄래?',
    '지우개가 안 필요한데 가져다줄래?',
    '지우개가 필요한데 가져다주지 마.',
])
def test_added_contexts_do_not_discard_negation_or_questions(ontology, schema, cfg, text):
    parser = IntentParser(ontology, schema, cfg,
                          lambda *_: {'intent': 'find_item', 'targets': ['eraser'], 'confidence': .99})
    doc = parser.parse(text)
    assert doc['intent'] in ('unknown', 'clarify') and doc['targets'] == []
    assert not doc['source']['execution_allowed']


@pytest.mark.parametrize('text,kind', [
    ('멈춰.', 'cancel'), ('취소!', 'cancel'), ('지금 뭐 해?', 'status'),
    ('멈춰。', 'cancel'), ('취소！', 'cancel'), ('지금 뭐 해？', 'status'),
])
def test_control_punctuation_uses_exact_match_without_api(ontology, schema, cfg, text, kind):
    calls = []
    parser = IntentParser(ontology, schema, cfg, lambda *args: calls.append(args))
    assert parser.parse(text)['intent'] == kind
    assert parser.fallback(text)['intent'] == kind
    assert parser.validate({'intent': kind, 'confidence': 1}, text)['intent'] == kind
    assert not calls


def test_control_config_uses_same_normalization_and_preserves_context(ontology, schema, cfg):
    cfg['cancel_phrases'] = ['멈춰！']
    cfg['status_phrases'] = ['지금 뭐 해？']
    parser = IntentParser(ontology, schema, cfg)
    assert parser.control('멈춰.')['intent'] == 'cancel'
    assert parser.control('지금 뭐 해?')['intent'] == 'status'
    for text in ('멈추지 마.', '멈춰라고 말하지 마.', '지금 뭐 해?라고 물었어', '취소하지 마!'):
        assert parser.control(text) is None



def test_fixed_commissioning_runs_stt_llm_without_fake_speech_deadline(ontology, schema, cfg):
    from ready2go_voice.adapters.audio import Recording
    paths, timeouts = [], []
    class STT:
        def transcribe(self, path, timeout):
            paths.append(path)
            assert path.exists()
            timeouts.append(timeout)
            return '지우개 찾아줘'
    calls = []
    def llm(text, timeout):
        calls.append(timeout)
        return {'intent': 'find_item', 'targets': ['eraser'], 'confidence': .99}
    cfg.update(timing_mode='commissioning', stt_timeout_sec=30, llm_timeout_sec=30)
    parser = IntentParser(ontology, schema, cfg, llm)
    from types import SimpleNamespace
    session = VoiceSession(parser, cfg, STT(), clock=lambda: 1000,
                           speech_gate=SimpleNamespace(check=lambda *a, **k: True))
    doc = session.audio(Recording(b'\0\0', None, None, recording_mode='fixed', recording_ended_monotonic=1))
    assert doc['targets'] == ['eraser'] and calls == [30] and timeouts == [30]
    assert not paths[0].exists()
    assert doc['source']['speech_ended_monotonic'] is None
    assert doc['source']['confirmation_latency_ms'] is None
    assert doc['source']['latency_measurement'] == 'not_measured'
    assert not session.should_publish(doc)



def test_stt_failure_progress_has_exception_type_only(ontology, schema, cfg):
    from ready2go_voice.adapters.audio import Recording
    events = []
    class Failed:
        def transcribe(self, *_): raise RuntimeError('SECRET')
    from types import SimpleNamespace
    session = VoiceSession(IntentParser(ontology, schema, cfg), cfg, Failed(),
                           progress=lambda **event: events.append(event),
                           speech_gate=SimpleNamespace(check=lambda *a, **k: True))
    doc = session.audio(Recording(b'\0\0', None, None, recording_mode='fixed'))
    assert doc['intent'] == 'clarify'
    assert events[-1] == {'event': 'stt_failed', 'error_type': 'RuntimeError'}
    assert 'SECRET' not in str(events)
