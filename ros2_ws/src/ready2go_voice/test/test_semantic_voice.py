"""Semantic voice queries and actual C group execution; audio/ROS are mocks."""
import copy
import importlib.util
import inspect
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from jsonschema import Draft7Validator
from ready2go_voice.core.intent import IntentParser
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.core import semantic_requests, group_speech
from ready2go_voice.core.tts_prefill import prefill_texts
from ready2go_runner.core import intent_router, interpreter, item_group
from test_voice_ux_node import node, node_class

ROOT = Path(__file__).resolve().parents[4]


def current_contract():
    root = Path(inspect.getfile(intent_router)).parents[5]
    schema = json.loads((root / 'contracts/intent.schema.json').read_text())
    if 'find_list' not in schema['properties']['intent']['enum']:
        pytest.skip('C #381 contract is not on this base; run with actual C source')
    return root, schema


@pytest.fixture
def semantic_parser(ontology, cfg):
    _, schema = current_contract()
    cfg.update(request_run_enabled=True, evaluation_mode=False)
    return IntentParser(ontology, schema, cfg, llm=lambda *a: pytest.fail('Semantic input must not use LLM'))


@pytest.mark.parametrize('question', ['출근 준비물 뭐야?', '출근 준비물 뭐가 들어 있어?', '출근 세트 목록 알려줘'])
def test_contents_uses_real_catalog_and_actual_readonly_tts(node, question):
    from test_runtime_322 import answer
    assert answer(node, question) == '출근 준비물은 에어팟 케이스, 차키, 립밤이에요.'
    assert not node.published and node.request_run.pending is None


@pytest.mark.parametrize('text,kind,targets', [
    ('출근 준비물 가져와', 'find_list', ['airpods_case', 'car_key', 'lip_balm']),
    ('출근 준비 물품 찾아줘', 'find_list', ['airpods_case', 'car_key', 'lip_balm']),
    ('귀중품 가져와', 'find_class', ['car_key'])])
def test_real_parser_session_prepares_exact_catalog_payload(semantic_parser, text, kind, targets):
    session = VoiceSession(semantic_parser, semantic_parser.cfg)
    doc = session.text(text, 0, request_id='voice-request')
    payload = session.prepare_request_payload(doc, 0, request_id='voice-request')
    assert payload['intent'] == kind and payload['targets'] == targets
    actual = semantic_requests.select(semantic_parser, text)[0]
    assert payload['semantic'] == {k: actual[k] for k in ('source', 'evidence')}
    assert payload['accept_text'] == semantic_requests.acceptance(actual)
    semantic_parser.validator.validate(payload)


@pytest.mark.parametrize('text', ['출근 준비물과 망치 가져와', '출근 준비물과 귀중품 가져와',
    '귀중품과 귀중품 가져와', '출근 준비물 가져오지 마', '출근 준비물 뭐야 그리고 망치 가져와', '미등록 목록 가져와'])
def test_semantic_mixed_negative_and_unknown_never_extract_partial_targets(semantic_parser, text):
    doc = VoiceSession(semantic_parser, semantic_parser.cfg).text(text)
    assert doc['intent'] in ('unknown','clarify') and doc['targets'] == []
    assert not doc['source']['execution_allowed'] and not doc['source']['llm_called']


def test_same_ttl_changes_contents_and_execution_targets(semantic_parser, tmp_path):
    path = tmp_path / 'semantics.ttl'
    path.write_text((ROOT / 'knowledge/semantics.ttl').read_text().replace(
        'r2g:airpods_case, r2g:car_key, r2g:lip_balm .', 'r2g:car_key, r2g:lip_balm .'))
    semantic_parser.cfg['semantic_catalog_file'] = str(path)
    session = VoiceSession(semantic_parser, semantic_parser.cfg)
    read = session.text('출근 준비물 뭐야?')
    run = session.text('출근 준비물 가져와')
    assert read['_voice']['final_text'] == '출근 준비물은 차키, 립밤이에요.'
    assert run['targets'] == ['car_key', 'lip_balm'] and read['_voice']['readonly_query']
    assert not read['source']['execution_allowed']


def test_contents_during_confirmation_never_reuses_single_item_authority(node):
    from test_voice_ux_node import ask
    ask(node)
    doc = node.session.text('출근 준비물 뭐야?', node.generation)
    assert doc['_voice']['readonly_query'] and not doc['source']['execution_allowed']
    assert doc['targets'] == [] and node.request_run.pending is None


def test_ambiguous_alias_and_retired_catalog_are_not_executable(semantic_parser, tmp_path):
    path = tmp_path / 'ambiguous.ttl'
    raw = (ROOT / 'knowledge/semantics.ttl').read_text()
    path.write_text(raw.replace('rdfs:label "귀중품"@ko', 'rdfs:label "귀중품"@ko ; r2g:alias_ko "출근 준비물"'))
    semantic_parser.cfg['semantic_catalog_file'] = str(path)
    doc = VoiceSession(semantic_parser, semantic_parser.cfg).text('출근 준비물 가져와')
    assert doc['intent'] in ('unknown','clarify') and not doc['source']['execution_allowed']
    path.write_text(raw.replace('r2g:lip_balm a r2g:Item', 'r2g:carrot_pen a r2g:Item'))
    with pytest.raises(ValueError, match='은퇴|미등록'):
        semantic_requests.catalog(semantic_parser.cfg, semantic_parser.items)


def test_operational_catalog_matches_legacy_world_and_is_separate_from_example(ontology, cfg):
    result = semantic_requests.catalog(cfg, ontology['world']['items']).query_list('출근 준비물')
    legacy = ontology['world']['lists']['commute_set']
    assert result['items'] == sorted(legacy['items'] if isinstance(legacy, dict) else legacy)
    assert (ROOT / 'knowledge/semantics.ttl').read_bytes() != (ROOT / 'knowledge/examples/p3_semantics.ttl').read_bytes()
    assert semantic_requests.catalog(cfg, ontology['world']['items']).query_class('귀중품')['items'] == ['car_key']


def test_semantic_catalog_installed_share_lookup(monkeypatch, tmp_path, ontology, cfg):
    from types import ModuleType
    share = tmp_path / 'share'
    (share / 'knowledge').mkdir(parents=True); (share / 'config').mkdir()
    (share / 'knowledge/semantics.ttl').write_bytes((ROOT / 'knowledge/semantics.ttl').read_bytes())
    (share / 'config/yolo_retired_classes.txt').write_bytes((ROOT / 'config/yolo_retired_classes.txt').read_bytes())
    packages = ModuleType('ament_index_python.packages')
    packages.get_package_share_directory = lambda name: str(share)
    monkeypatch.setitem(sys.modules, 'ament_index_python.packages', packages)
    monkeypatch.setattr(semantic_requests, '__file__', str(tmp_path / 'a/b/c/d/e/semantic_requests.py'))
    cfg['ontology_file'] = str(tmp_path / 'missing/robot_ontology.jsonld')
    assert semantic_requests.catalog(cfg, ontology['world']['items']).query_list('출근 준비 물품')['items'] == ['airpods_case','car_key','lip_balm']


def test_existing_request_opt_in_off_holds_group_but_keeps_contents_readonly(semantic_parser):
    semantic_parser.cfg['request_run_enabled'] = False
    session = VoiceSession(semantic_parser, semantic_parser.cfg)
    doc = session.text('출근 준비물 가져와')
    assert not doc['source']['execution_allowed'] and doc['intent'] == 'clarify'
    read = session.text('출근 준비물 뭐야?')
    assert read['_voice']['readonly_query'] and not session.should_publish(read)


def test_bounded_shared_prefill_contains_registered_contents_and_group_factory_fragments(ontology, cfg):
    items = ontology['world']['items']
    selected = prefill_texts(cfg, items.values(), reference_state=ontology['state'], places=ontology['world']['places'],
        item_names={k:v['name_ko'] for k,v in items.items()})
    assert len(selected) + 1 <= 512
    assert set(semantic_requests.required_texts(cfg, items)) <= set(selected)
    assert set(group_speech.required_texts(cfg, items)) <= set(selected)
    pending = {'targets':['airpods_case','car_key','lip_balm']}
    assert group_speech.classify('아무 물건이나 던져요.', pending, items, cfg) is None


@pytest.fixture
def group_wire(node, node_class, monkeypatch):
    croot, schema = current_contract()
    import test_c_control_wire as harness
    monkeypatch.setattr(harness, 'C_PACKAGE', croot / 'ros2_ws/src/ready2go_runner')
    node.parser.validator = Draft7Validator(schema)
    from ready2go_voice.core.runner_notice import RunnerNoticePolicy
    node.notice_policy = RunnerNoticePolicy(node.cfg)
    monkeypatch.setenv('BACKEND', 'mock')
    wire = harness.Wire(node, suspended=False)
    from ready2go_runner.core import plan_exec, planner
    from ready2go_runner.core.log_records import run_document
    wire.c._run_group.__func__.__globals__.update(item_group=item_group, plan_exec=plan_exec,
        planner=planner, run_document=run_document, RunResult=interpreter.RunResult, time=time, Path=Path)
    wire.c._chain_parent, wire.c._chain_events = {}, {}
    test_path = croot / 'ros2_ws/src/ready2go_runner/test'
    spec = importlib.util.spec_from_file_location('_actual_c_item_group', test_path / 'test_item_group.py')
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(test_path))
    try: spec.loader.exec_module(module)
    finally: sys.path.remove(str(test_path))
    runner, robot, _ = module.setup()
    wire.c.runner, wire.c.log_store = runner, runner.log_store
    wire.c.onto = copy.deepcopy(module.ONTOLOGY)
    wire.c.intents.tasks['find_item'] = module.TASK
    # Re-publish the new actual Runner boot before issuing a voice request.
    wire.c.publish(); wire.flush()
    calls, fragments = [], []
    wire.speech_calls = calls; wire.fragments = fragments; wire.robot = robot
    wire.speech_mode = 'ok'
    node._say = node_class._say.__get__(node, node_class)
    def playback(text, on_start=None, on_timing=None, **kwargs):
        fragments.append(text)
        if wire.speech_mode == 'fail': raise RuntimeError('mock PCM unavailable')
        if wire.speech_mode == 'stop':
            wire.c.runner.halt(source='voice')
            raise InterruptedError('CANCELED')
        stamp = dict(tts_started_monotonic=node.now[0], tts_start_basis='portaudio_first_dac', tts_mock=False)
        if on_start: on_start(stamp)
        node.now[0] += .1
        if on_timing: on_timing(dict(playback_ended_monotonic=node.now[0],playback_end_basis='portaudio_finished_callback'))
        return stamp
    node.tts.speak = playback
    node_class._speak.__globals__['Skill'] = SimpleNamespace(Result=lambda:SimpleNamespace(success=False,error_code='',output_json=''))
    original = runner.execute
    def execute(action, params, timeout=None):
        if action == 'speak':
            if getattr(wire, 'interleave', False) and len(calls) == 1:
                wire.c._on_intent(SimpleNamespace(data=json.dumps(dict(intent='find_item', targets=['eraser'], confidence=1., request_id='busy-other'))))
                assert wire.c._last_intent['reason'] == 'BUSY'
                wire.c._on_intent(SimpleNamespace(data=json.dumps(dict(intent='status', targets=[], confidence=1.))))
            wire.flush()
            calls.append(params['text'])
            request = SimpleNamespace(params_json=json.dumps(params))
            if node._goal(request) != 1:
                return interpreter.ActionResult(False, {}, 'BACKEND_ERROR')
            goal = SimpleNamespace(request=request,is_cancel_requested=False,succeed=lambda:None,abort=lambda:None,canceled=lambda:None)
            reply = node._speak(goal)
            return interpreter.ActionResult(reply.success, {}, reply.error_code or None)
        return original(action, params, timeout)
    runner.execute = execute
    return wire


@pytest.mark.parametrize('question,outcome,code', [
    ('출근 준비물 가져와','FAILED','PARTIAL_DELIVERY'), ('귀중품 가져와','COMPLETED',None)])
def test_actual_voice_catalog_c_group_speech_and_parent_result(group_wire, question, outcome, code):
    wire = group_wire; node = wire.e
    doc = node.session.text(question, node.generation)
    node.deliver(doc); wire.flush()
    assert wire.sent[-1]['intent'] in ('find_list','find_class')
    accepted = wire.c.status()['accepted']; run = accepted['run_id']
    assert accepted['task_id'] == 'find_with_unpack'
    assert wire.c.status()['task_id'] == 'group_' + doc['semantic']['source']['id']
    scheduled = wire.started[-1]
    assert scheduled['target'].__name__ == '_run_group'
    scheduled['target'](*scheduled['args']); wire.flush()
    status = wire.c.status()
    assert (status['last']['overall_status'], status['last']['error_code']) == (outcome, code)
    assert status['last']['run_id'] == status['accepted']['run_id'] == run
    assert wire.speech_calls[0] == wire.sent[-1]['accept_text']
    assert wire.c.log_store.read_run(run)['run']['summary_text']
    assert wire.c.log_store.read_run(run + '.1')['run']['parent_run_id'] == run
    if outcome == 'FAILED':
        assert status['last']['failure']['run_id'] == run
        assert '3개 중 2개 가져왔어요.' in wire.fragments
        assert '차키를 찾아 올게요' in wire.fragments and '립밤을 찾아 올게요' in wire.fragments
    else: assert '차키를 가져왔어요.' in wire.fragments
    assert node.pending_notice is None  # verified C summary; no duplicate completion/false PARTIAL warning


@pytest.mark.parametrize('mode', ['fail','stop'])
def test_acceptance_failure_or_stop_sends_zero_robot_actions(group_wire, mode):
    wire = group_wire; node = wire.e
    wire.speech_mode = mode
    node.deliver(node.session.text('출근 준비물 가져와', node.generation)); wire.flush()
    scheduled = wire.started[-1]; scheduled['target'](*scheduled['args']); wire.flush()
    result = wire.c._last
    assert not wire.robot.calls
    if mode == 'stop':
        assert result.overall_status == 'ABORTED' and result.failure is None
    else: assert result.overall_status == 'FAILED'


@pytest.mark.parametrize('mode', ['all_unknown','missing_item','unsafe_stop','busy_status'])
def test_actual_c_group_boundaries_keep_safe_result_and_continuity(group_wire, mode):
    wire = group_wire; node = wire.e
    if mode == 'all_unknown':
        for key in ('airpods_case','car_key','lip_balm'): wire.c.runner._state['located_in'].pop(key, None)
    elif mode == 'missing_item': wire.robot.skills.not_visible.add('lip_balm')
    elif mode == 'unsafe_stop':
        def stop(action, params):
            wire.c.runner.halt(source='voice')
            return interpreter.ActionResult(False, {}, 'CANCELED')
        wire.robot.hook = stop
    else: wire.interleave = True
    node.deliver(node.session.text('출근 준비물 가져와', node.generation)); wire.flush()
    run = wire.c.status()['accepted']['run_id']
    scheduled = wire.started[-1]; scheduled['target'](*scheduled['args']); wire.flush()
    result = wire.c._last
    if mode == 'all_unknown':
        assert not wire.robot.calls and not wire.speech_calls
        assert result.overall_status == 'FAILED' and result.error_code == 'UNKNOWN_ITEM'
    elif mode == 'unsafe_stop':
        assert result.overall_status == 'ABORTED' and result.failure is None
        assert not any(a == 'pick_object' for a, _ in wire.robot.calls)
    else:
        assert result.overall_status == 'FAILED' and result.error_code == 'PARTIAL_DELIVERY'
        assert result.run_id == wire.c.status()['accepted']['run_id'] == run
        assert node.pending_notice is None
        if mode == 'missing_item': assert '립밤은 못 찾았어요.' in wire.fragments
        else:
            assert wire.c._last_intent['decision'] == 'status'
            assert wire.speech_calls.count(wire.sent[0]['accept_text']) == 1


@pytest.mark.parametrize('change', ['new_run','new_boot','cancel','arbitrary','old_seq'])
def test_group_followup_gate_requires_current_factory_bound_run(group_wire, change):
    from test_c_control_wire import INFO
    wire = group_wire; node = wire.e
    node.deliver(node.session.text('출근 준비물 가져와', node.generation)); wire.flush()
    accept = wire.sent[0]['accept_text']
    assert wire.c.runner.execute('speak', {'text':accept}).success
    played = list(wire.fragments)
    if change == 'new_run': wire.c._accepted['run_id'] = 'different-run'
    elif change == 'new_boot': wire.c.runner.boot_id = 'different-boot'
    elif change == 'cancel':
        wire.c._on_intent(SimpleNamespace(data=json.dumps(dict(intent='cancel',targets=[],confidence=1.))))
    elif change == 'old_seq':
        stale = wire.c.status(); stale['seq'] = 0; stale['accepted'] = dict(stale['accepted'],run_id='old')
        node._runner_status_with_info(SimpleNamespace(data=json.dumps(stale)), dict(INFO))
    if change in ('new_run','new_boot','cancel'):
        wire.c.publish(); wire.flush()
    text = '허가 없이 아무 물건이나 던져요.' if change == 'arbitrary' else '서랍을 닫았어요'
    reply = wire.c.runner.execute('speak', {'text':text})
    assert reply.success is (change == 'old_seq')
    if change != 'old_seq': assert wire.fragments == played
    assert not wire.robot.calls
