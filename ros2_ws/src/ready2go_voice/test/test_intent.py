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


def test_valid_free_expression_uses_llm(ontology, schema, cfg):
    parser = IntentParser(ontology, schema, cfg, lambda *_: json.dumps(
        {'intent': 'find_item', 'targets': ['eraser'], 'confidence': .95}))
    assert parser.parse('연필 자국 없애는 물건 가져다줘')['targets'] == ['eraser']


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
    assert session.should_publish(doc) and not session.should_publish(doc)
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
