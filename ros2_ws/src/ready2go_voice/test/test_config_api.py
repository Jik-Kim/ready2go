from pathlib import Path
import json
import math
from types import SimpleNamespace
import yaml
import pytest
from jsonschema import Draft7Validator, ValidationError
from ready2go_voice.core.config import load_config
from ready2go_voice.adapters.api import WhisperSTT, LangChainIntent
from ready2go_voice.core.intent import IntentParser


@pytest.mark.parametrize('key,value', [('sample_rate', 22050), ('frame_samples', 1),
    ('llm_timeout_sec', -1), ('min_confidence', math.nan), ('evaluation_mode', 'false'),
    ('bare_item_policy', 'execute'), ('bare_item_policy', 'unknown')])
def test_invalid_config_rejected(cfg, tmp_path, key, value):
    cfg[key] = value
    path = tmp_path/'voice.yaml'; path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError):
        load_config(path)


def test_nan_confidence_cannot_execute(ontology, schema, cfg):
    parser = IntentParser(ontology, schema, cfg)
    with pytest.raises(ValueError):
        parser.validate({'intent': 'find_item', 'targets': ['eraser'], 'confidence': math.nan}, '지우개 찾아줘')


def test_whisper_sdk_arguments_and_file_closed(cfg, tmp_path, monkeypatch):
    openai = pytest.importorskip('openai')
    captured = {}
    class Client:
        def __init__(self, **kwargs):
            captured['client'] = kwargs
            self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self.create))
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kwargs):
            captured['call'] = kwargs
            assert not kwargs['file'].closed
            return SimpleNamespace(text='지우개 찾아줘')
    monkeypatch.setattr(openai, 'OpenAI', Client)
    path = tmp_path/'test.wav'; path.write_bytes(b'audio')
    assert WhisperSTT(cfg, ['지우개']).transcribe(path, .5) == '지우개 찾아줘'
    assert captured['client']['max_retries'] == 0 and captured['client']['timeout'] == .5
    assert captured['call']['model'] == 'whisper-1' and captured['call']['language'] == 'ko'
    assert captured['call']['file'].closed


def test_langchain_prompt_structured_json_and_timeout(cfg, ontology, monkeypatch):
    langchain_openai = pytest.importorskip('langchain_openai')
    from langchain_core.runnables import RunnableLambda
    captured = {}
    class LLM:
        def __init__(self, **kwargs): captured['init'] = kwargs
        def bind(self, **kwargs):
            captured['bind'] = kwargs
            def answer(prompt):
                captured['prompt'] = prompt.to_string()
                raw = {'intent': 'unknown', 'targets': [], 'confidence': 1,
                       'clarify_question': None, 'response_text': '그 물품은 지원하지 않습니다.',
                       'rejection_reason': 'unregistered_item'}
                Draft7Validator(captured['bind']['response_format']['json_schema']['schema']).validate(raw)
                return SimpleNamespace(content=json.dumps(raw))
            return RunnableLambda(answer)
    monkeypatch.setattr(langchain_openai, 'ChatOpenAI', LLM)
    answer = LangChainIntent(cfg, ontology['world']['items'])('미등록 물품 가져줘', .6)
    assert json.loads(answer)['intent'] == 'unknown'
    assert captured['init']['timeout'] == .6 and captured['init']['max_retries'] == 0
    assert captured['bind']['response_format']['json_schema']['strict']
    assert 'car_key' in captured['prompt'] and '미등록 물품 가져줘' in captured['prompt']
    assert 'rejection_reason' in captured['prompt'] and 'unsupported_request' in captured['prompt']
    assert json.loads(answer)['rejection_reason'] == 'unregistered_item'


def test_actual_internal_schema_keeps_registered_enum_and_requires_reason(cfg, ontology):
    schema = LangChainIntent(cfg, ontology['world']['items']).schema
    validator = Draft7Validator(schema)
    raw = {'intent': 'unknown', 'targets': [], 'confidence': 1,
           'clarify_question': None, 'response_text': None, 'rejection_reason': 'unregistered_item'}
    validator.validate(raw)
    assert set(schema['required']) == set(schema['properties'])
    assert schema['additionalProperties'] is False
    assert schema['properties']['targets']['items']['enum'] == list(ontology['world']['items'])
    for invalid in (dict(raw, targets=['apple']), dict(raw, rejection_reason='new_policy'),
                    dict(raw, extra='unapproved'), {k: v for k, v in raw.items() if k != 'rejection_reason'}):
        with pytest.raises(ValidationError):
            validator.validate(invalid)



def test_legacy_config_keeps_silence_budget_defaults(cfg, tmp_path):
    for key in ('recording_mode', 'record_duration_sec', 'timing_mode', 'diagnostic_detail'):
        cfg.pop(key, None)
    path = tmp_path/'voice.yaml'; path.write_text(yaml.safe_dump(cfg))
    loaded = load_config(path)
    assert loaded['recording_mode'] == 'silence' and loaded['timing_mode'] == 'ac_budget'


@pytest.mark.parametrize('updates', [dict(timing_mode='ac_budget'), dict(record_duration_sec=9),
                                    dict(diagnostic_detail='yes')])
def test_invalid_commissioning_configuration(cfg, tmp_path, updates):
    cfg.update(updates)
    path = tmp_path/'voice.yaml'; path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError): load_config(path)


P2_BUDGET_KEYS = ('resume_admission_window_sec', 'resume_stt_result_timeout_sec',
    'resume_register_ack_timeout_sec', 'resume_question_tts_timeout_sec',
    'resume_independent_request_timeout_sec', 'place_admission_window_sec', 'place_stt_result_timeout_sec')


@pytest.mark.parametrize('key', P2_BUDGET_KEYS)
@pytest.mark.parametrize('value', [True, 0, -1, float('inf'), float('nan')])
def test_p2_config_requires_finite_positive_segments(cfg, tmp_path, key, value):
    cfg[key] = value
    path = tmp_path/'cfg.yaml'; path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError): load_config(path)


@pytest.mark.parametrize('updates', [dict(place_answer_timeout_sec=7), dict(place_max_reasks=2),
    dict(place_max_reasks=True), dict(p2_goal_enabled='true'), dict(p2_goal_catalog=[[]])])
def test_removed_and_invalid_p2_settings_rejected(cfg, tmp_path, updates):
    cfg.update(updates)
    path = tmp_path/'cfg.yaml'; path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError): load_config(path)


def test_p2_null_budgets_hold_and_factories_use_yaml(cfg, tmp_path):
    from ready2go_voice.core.recovery_confirmation import RecoveryConfirmation
    from ready2go_voice.core.skill_confirmation import PlaceConfirmation
    p = RecoveryConfirmation.from_config('boot', cfg)
    assert p.register_ack_timeout_sec == cfg['resume_register_ack_timeout_sec']
    assert p.independent_request_timeout_sec == cfg['resume_independent_request_timeout_sec']
    place = PlaceConfirmation.from_config(cfg, item_names={'eraser': '지우개'})
    assert place.admission_window_sec == cfg['place_admission_window_sec']
    cfg.update({key: None for key in P2_BUDGET_KEYS})
    path = tmp_path/'cfg.yaml'; path.write_text(yaml.safe_dump(cfg))
    assert all(load_config(path)[key] is None for key in P2_BUDGET_KEYS)


def test_p2_actual_schema_is_opt_in_and_strict(cfg, ontology):
    cfg['p2_goal_enabled'] = True
    schema = LangChainIntent(cfg, ontology['world']['items']).schema
    Draft7Validator.check_schema(schema)
    raw = dict(intent='achieve_goal', targets=[], confidence=.99, clarify_question=None,
               response_text=None, rejection_reason=None, goals=cfg['p2_goal_catalog'][3])
    Draft7Validator(schema).validate(raw)
    assert schema['additionalProperties'] is False and set(schema['required']) == set(schema['properties'])
    for invalid in (dict(raw, goals=[dict(predicate='open', subject='apple', value=True)]),
                    dict(raw, goals=[dict(predicate='open', subject='drawer_top', value=True, action='move')]),
                    {k: v for k, v in raw.items() if k != 'goals'}):
        with pytest.raises(ValidationError): Draft7Validator(schema).validate(invalid)


def test_empty_opt_in_catalog_is_rejected(cfg, tmp_path):
    cfg.update(p2_goal_enabled=True, p2_goal_catalog=[])
    path = tmp_path/'cfg.yaml'; path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError): load_config(path)


def test_p2_langchain_prompt_keeps_explicit_open_goal(cfg, ontology, monkeypatch):
    langchain_openai = pytest.importorskip('langchain_openai')
    from langchain_core.runnables import RunnableLambda
    captured = {}
    cfg['p2_goal_enabled'] = True
    raw = dict(intent='achieve_goal', targets=[], confidence=.99, clarify_question=None,
        response_text=None, rejection_reason=None, goals=cfg['p2_goal_catalog'][3])
    class LLM:
        def __init__(self, **kwargs): pass
        def bind(self, **kwargs):
            captured['format'] = kwargs['response_format']['json_schema']
            def answer(prompt):
                captured['prompt'] = prompt.to_string()
                Draft7Validator(captured['format']['schema']).validate(raw)
                return SimpleNamespace(content=json.dumps(raw))
            return RunnableLambda(answer)
    monkeypatch.setattr(langchain_openai, 'ChatOpenAI', LLM)
    answer = LangChainIntent(cfg, ontology['world']['items'])('지우개 갖다 놓고 서랍은 열어 둬', .5)
    assert json.loads(answer)['goals'][1]['value'] is True
    assert captured['format']['name'] == 'p2_goal_candidate' and captured['format']['strict']
    assert '명시 열림을 자동 닫힘으로 바꾸지' in captured['prompt']
