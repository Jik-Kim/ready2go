"""실API/마이크/재생 없이 SDK 예외·실제 처리 메서드·진단 필터를 검증합니다."""
import json
from types import SimpleNamespace
import pytest
import yaml
from ready2go_voice.core.stt_error import error_info, error_prompts
from ready2go_voice.core.config import load_config
from ready2go_voice.core.diagnostics import DiagnosticFile
from ready2go_voice.core.tts_prefill import prefill_texts
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.core.intent import IntentParser
from ready2go_voice.adapters.audio import Recording
from test_voice_ux_node import node_class, node, ask


class RateLimitError(Exception):
    def __init__(self, status=429, code=None, kind=None):
        super().__init__('private WAV transcript sk-proj-DO_NOT_PRINT_SECRET')
        self.status_code, self.code, self.type = status, code, kind
        self.body = {'message': str(self), 'error': {'private': 'private transcript'}}
        self.headers = {'authorization': 'private secret'}


@pytest.mark.parametrize('status,code,kind,category', [
    (429, 'rate_limit_exceeded', 'requests', 'rate_limit'),
    (429, 'slow_down', 'rate_limit_error', 'rate_limit'),
    (429, 'insufficient_quota', 'insufficient_quota', 'quota'),
    (429, 'organization_spend_limit_exceeded', None, 'quota'),
    (429, 'credit_balance_exhausted', None, 'quota'),
    (429, 'project_spend_limit_exceeded', None, 'quota'),
    (429, 'organization_usage_limit_exceeded', None, 'quota'),
    (429, 'credit_balance_exhausted', 'rate_limit_error', 'unknown_429'),
    (429, 'project_spend_limit_exceeded', 'rate_limit_error', 'unknown_429'),
    (429, 'organization_usage_limit_exceeded', 'rate_limit_error', 'unknown_429'),
    (429, None, 'insufficient_quota', 'quota'),
    (429, None, None, 'unknown_429'),
    (None, None, None, 'unknown_429'),
    (429, 'future_code', 'private transcript', 'unknown_429'),
    (429, 'rate_limit_exceeded', 'insufficient_quota', 'unknown_429'),
    (429, [], {}, 'unknown_429'),
    ('429', None, None, 'unknown_429'),
    (True, None, None, 'unknown_429'),
    (500, 'insufficient_quota', None, 'other'),
])
def test_closed_metadata_and_classification(status, code, kind, category):
    info = error_info(RateLimitError(status, code, kind))
    assert info['category'] == category
    assert set(info) == {'status', 'code', 'type', 'category'}
    assert not any(x in json.dumps(info) for x in ('private', 'SECRET', 'future_code'))


def test_broken_metadata_never_breaks_failure_handling():
    class Broken(Exception):
        def __getattribute__(self, key):
            if key in ('status_code', 'code', 'type'):
                raise RuntimeError('private')
            return super().__getattribute__(key)
    assert error_info(Broken()) == dict(status=None, code=None, type=None, category='other')
    assert error_info(ValueError('private'))['category'] == 'other'


def test_real_sdk_normalized_metadata_without_api():
    openai = pytest.importorskip('openai')
    import httpx
    response = httpx.Response(429, request=httpx.Request('POST', 'https://api.openai.com'))
    exc = openai.RateLimitError('private', response=response,
        body={'code': 'insufficient_quota', 'type': 'insufficient_quota', 'message': 'private'})
    assert error_info(exc)['category'] == 'quota'


def recording():
    return Recording(b'\0\0' * 1600, None, None, recording_mode='fixed')


@pytest.mark.parametrize('code,kind,category', [
    ('rate_limit_exceeded', None, 'rate_limit'),
    ('insufficient_quota', None, 'quota'),
    (None, None, 'unknown_429'),
])
def test_actual_session_node_tts_and_diagnostic_filter(node, node_class, tmp_path, code, kind, category):
    ask(node)
    assert node.session.conversation.pending is not None
    node.texts.clear(); node.published.clear(); node.diagnostics.clear()
    events = []
    class STT:
        def transcribe(self, *_):
            raise RateLimitError(code=code, kind=kind)
    node.parser.llm = lambda *_: pytest.fail('STT failure must not call LLM')
    node.session.stt = STT()
    node.session.speech_gate = SimpleNamespace(check=lambda *a, **kw: True)
    node.session.progress = lambda **event: events.append(event)
    doc = node.session.audio(recording())
    assert doc['intent'] == 'clarify' and doc['targets'] == []
    assert not doc['source']['execution_allowed'] and not doc['source']['llm_called']
    assert node.session.should_publish(doc)  # 기존 non-execution clarify 발행은 유지합니다.
    assert 'api_error' not in doc['source'] and 'stt_failure' not in doc['source']
    node.deliver(doc)
    expected = node.cfg['stt_error_prompts'][category]
    assert node.texts == [expected]
    assert node.session.conversation.pending is None
    node.parser.llm = None
    assert node.session.text('응')['intent'] != 'find_item'
    assert all(d['intent'] == 'clarify' and not d['source']['execution_allowed'] for d in node.published)
    assert next(d['text'] for d in node.diagnostics if d['event'] == 'final_response') == expected
    messages = []; node.get_logger = lambda: SimpleNamespace(info=messages.append)
    node.cfg['diagnostic_file'] = str(tmp_path/'diagnostic.jsonl')
    writer = node.diagnostic_file = DiagnosticFile(node.cfg, messages.append)
    try:
        for event in events:
            node_class._diagnostic(node, event)
        node_class._diagnostic(node, {'event': 'interpretation', 'intent': doc})
    finally:
        writer.close()
    raw = (tmp_path/'diagnostic.jsonl').read_text()
    assert all(x not in raw + ''.join(messages) for x in ('private', 'SECRET', 'authorization', 'headers', 'body'))
    saved = [json.loads(line) for line in raw.splitlines()]
    assert next(d for d in saved if d['event'] == 'stt_failed')['api_error']['category'] == category
    assert any('429' in m and category in m for m in messages)


@pytest.mark.parametrize('failure', [True, False])
def test_general_failure_and_normal_stt_unchanged(cfg, ontology, schema, failure):
    class STT:
        def transcribe(self, *_):
            if failure: raise RuntimeError('private')
            return '망치 가져다줘'
    session = VoiceSession(IntentParser(ontology, schema, cfg), cfg, STT(),
        speech_gate=SimpleNamespace(check=lambda *a, **kw: True))
    doc = session.audio(recording())
    if failure:
        assert doc['clarify_question'] == cfg['clarify_prompts']['audio_failure']
        assert not doc['source']['execution_allowed']
    else:
        assert doc['intent'] == 'find_item' and doc['targets'] == ['toy_hammer']
        assert 'stt_failure' not in doc['_voice']


def test_old_local_defaults_custom_prompts_prefill(cfg, ontology, tmp_path):
    expected = error_prompts({})
    assert cfg['stt_error_prompts'] == expected  # YAML single source.
    cfg.pop('stt_error_prompts')
    path = tmp_path/'old.yaml'; path.write_text(yaml.safe_dump(cfg))
    loaded = load_config(path)
    assert loaded['stt_error_prompts'] == expected
    loaded['stt_error_prompts']['quota'] = '사용 한도를 확인해 주세요.'
    path.write_text(yaml.safe_dump(loaded))
    checked = load_config(path)
    assert checked['stt_error_prompts']['quota'] == loaded['stt_error_prompts']['quota']
    checked['tts_melotts_assets'] = str(tmp_path/'assets')
    assert set(checked['stt_error_prompts'].values()) <= set(prefill_texts(checked, ontology['world']['items'].values()))


@pytest.mark.parametrize('value', [None, [], {}, {'quota': ''}, {'quota': 123}])
def test_invalid_prompt_settings_fail_config(cfg, tmp_path, value):
    cfg['stt_error_prompts'] = value
    path = tmp_path/'invalid.yaml'; path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match='stt_error_prompts'):
        load_config(path)


def test_source_and_installed_single_yaml_mapping(monkeypatch, tmp_path):
    import sys
    import shutil
    from types import ModuleType
    import ready2go_voice.core.stt_error as module
    source = module._prompt_file()
    assert source.name == 'voice.yaml' and source.parent.name == 'params'
    expected = error_prompts({})
    share = tmp_path/'share/ready2go_voice'
    (share/'params').mkdir(parents=True)
    shutil.copyfile(source, share/'params/voice.yaml')
    package = ModuleType('ament_index_python.packages')
    package.get_package_share_directory = lambda name: str(share) if name == 'ready2go_voice' else pytest.fail(name)
    monkeypatch.setitem(sys.modules, 'ament_index_python', ModuleType('ament_index_python'))
    monkeypatch.setitem(sys.modules, 'ament_index_python.packages', package)
    monkeypatch.setattr(module, '__file__', str(tmp_path/'installed/lib/python3.12/site-packages/ready2go_voice/core/stt_error.py'))
    assert module._prompt_file() == share/'params/voice.yaml'
    assert error_prompts({}) == expected
    assert error_prompts({'stt_error_prompts': dict(expected, quota='사용 한도를 확인해 주세요.')})['quota'] == '사용 한도를 확인해 주세요.'


def test_raw_session_missing_prompts_and_unavailable_yaml_hold_safely(cfg, ontology, schema, monkeypatch):
    import ready2go_voice.core.stt_error as module
    expected = error_prompts({})
    cfg.pop('stt_error_prompts')
    class STT:
        def transcribe(self, *_): raise RateLimitError(code='insufficient_quota')
    session = VoiceSession(IntentParser(ontology, schema, cfg), cfg, STT(),
        speech_gate=SimpleNamespace(check=lambda *a, **kw: True))
    assert session.audio(recording())['clarify_question'] == expected['quota']
    monkeypatch.setattr(module, '_prompt_file', lambda: (_ for _ in ()).throw(FileNotFoundError('private')))
    doc = session.audio(recording())
    assert doc['clarify_question'] == cfg['clarify_prompts']['audio_failure']
    assert not doc['source']['execution_allowed'] and not doc['source']['llm_called']


def test_prefill_raw_cfg_missing_prompts_uses_yaml(cfg, ontology, tmp_path):
    expected = error_prompts({})
    cfg.pop('stt_error_prompts')
    cfg['tts_melotts_assets'] = str(tmp_path/'assets')
    assert set(expected.values()) <= set(prefill_texts(cfg, ontology['world']['items'].values()))
