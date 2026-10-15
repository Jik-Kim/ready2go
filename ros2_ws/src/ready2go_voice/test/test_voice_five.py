"""실제 E 메서드·현재 C status/step 원본. 장치/API/ROS 실행은 없습니다."""
import copy
import json
import threading
from types import SimpleNamespace
import pytest
from ready2go_voice.core.hotfix import prompts
from ready2go_voice.core.intent import intent
from ready2go_voice.core.runner_notice import Notice, RunnerNoticePolicy, warning_kind
from ready2go_voice.core.tts_prefill import prefill_texts
from ready2go_voice.core.config import load_config
from ready2go_runner.core.runner_status import build_status
from ready2go_runner.core.interpreter import RunResult
from test_voice_ux_node import node, node_class
from test_runtime_322 import memory_node
from conftest import ROOT, PACKAGE


def packet(node, *, phase='idle',seq=1,boot='boot',halt=None,last=None,decision=None,step='s7.1',task='find_with_unpack'):
    result=build_status(phase=='running',phase=='halted','HALTED' if phase=='halted' else None,
        task if phase=='running' else None,step if phase=='running' else None,
        last,task if last else None,False,halt=halt)
    result.update(boot_id=boot,seq=seq,last_intent=decision)
    node._runner_status_with_info(SimpleNamespace(data=json.dumps(result)),
        dict(source_timestamp=seq+10,received_timestamp=seq+11,publication_sequence_number=seq,reception_sequence_number=seq))
    return result


def play(node):
    notice=node.pending_notice
    if notice is not None:
        node.pending_notice=None
        node._play_notice(notice,threading.Event())
    return notice


def query(node,text):
    doc=node.session.text(text,node.generation,blocked=True,runner_state=node.notice_policy.phase)
    node.deliver(doc)
    return doc


def test_halted_new_read_and_rejection_use_notice_without_unlock_or_motion(node):
    _,_,state,_=memory_node(node)
    packet(node,phase='halted');state()
    assert node.normal_notice_cancel.is_set()
    query(node,'지우개 어딨어?');play(node)
    assert node.texts[-1]=='지우개는 아래 서랍에 있습니다.'
    query(node,'복구해');play(node)
    assert node.texts[-1]==prompts(node.cfg)['control_rejected']
    assert not node.published and node.normal_notice_cancel.is_set()
    assert node.notice_policy.phase=='halted' and node.safety_exchange.policy is None


def test_old_normal_and_read_cancelled_by_stop_not_revived(node):
    memory_node(node);packet(node)
    old=node.session.text('지우개 찾아줘',node.generation)
    generation=node.generation
    query(node,'현재 상태');notice=node.pending_notice
    with node.submit_lock:
        node._stop_locked(node.session.text('멈춰',node.generation))
    before=len(node.texts)
    node._deliver(old,generation)
    node._play_notice(notice,threading.Event())
    assert len(node.texts)==before and [d['intent'] for d in node.published]==['cancel']


def test_read_pending_and_playing_high_warning_have_priority(node):
    memory_node(node);packet(node)
    high=Notice('estop','안전 경고',0,node.notice_policy.revision)
    node.pending_notice=high
    query(node,'현재 상태');assert node.pending_notice is high
    node.pending_notice=None;node.active_notice=high
    query(node,'현재 상태');assert node.pending_notice is None
    node.active_notice=None
    query(node,'현재 상태');node.safety_activity.set();before=len(node.texts);play(node)
    assert len(node.texts)==before  # registered question capture is never interrupted


def test_read_normal_heartbeat_keeps_meaning_but_old_seq_and_boot_do_not_restore(node):
    endpoints,_,_,_=memory_node(node);packet(node)
    query(node,'현재 상태');notice=node.pending_notice
    packet(node,seq=2)
    node._play_notice(notice,threading.Event())
    assert node.texts[-1]==prompts(node.cfg)['status_idle']
    packet(node,phase='running',seq=1)
    assert node._runner_status_view()['status']['phase']=='idle'
    query(node,'현재 상태');old=node.pending_notice
    packet(node,seq=1,boot='new-boot')
    before=len(node.texts);node._play_notice(old,threading.Event())
    assert len(node.texts)==before
    packet(node,phase='running',seq=3,boot='boot')
    assert node._runner_status_view()['status']['boot_id']=='new-boot'
    endpoints['/runner/status']=[]
    query(node,'현재 상태');play(node)
    assert node.texts[-1]==prompts(node.cfg)['status_unknown']


def test_status_uses_only_actual_current_request_target_and_never_publishes(node):
    memory_node(node);node.cfg['request_run_enabled']=True;packet(node)
    node.request_run.register(dict(request_id='request',intent='find_item',targets=['eraser'],accept_text='준비'))
    decision=dict(request_id='request',intent='find_item',decision='run',run_id='run',targets=['eraser'])
    packet(node,phase='running',seq=2,decision=decision)
    doc=query(node,'지금 뭐하고 있어?');play(node)
    assert doc['intent']=='status' and not node.session.should_publish(doc)
    assert node.texts[-1]=='지우개를 찾고 있습니다.' and not node.published
    packet(node,phase='running',seq=3,decision=dict(decision,run_id='other'))
    query(node,'현재 상태');play(node)
    assert node.texts[-1]==prompts(node.cfg)['status_running']


def test_status_registered_question_is_read_only_and_unknown_is_not_empty_work(node):
    memory_node(node)
    halt=dict(boot_id='boot',event_id='event',run_id='run',stop='confirmed',locked=False,
        resume=dict(offered=True,from_step='s7.1',question=dict(id='question',state='registered'),request=None))
    # Current actual public C fields, no synthetic query fields in the payload.
    packet(node,phase='idle',halt=halt)
    query(node,'현재 상태');play(node)
    assert node.texts[-1]==prompts(node.cfg)['status_resume_wait']
    with node.submit_lock:
        node._lose_control_source_locked()
    query(node,'이어서 해');play(node)
    assert node.texts[-1]==prompts(node.cfg)['status_unknown']
    assert '작업이 없습니다' not in node.texts[-1] and not node.published


@pytest.mark.parametrize('text',['현재 상태라고 말해','지금 뭐하고 있어라고 했어','현재 상태 말하지 마'])
def test_status_full_form_rejects_quote_or_negation(node,text):
    assert not node.parser.control(text)
    result=node.parser.parse(text)
    assert not result.get('_voice',{}).get('readonly_query')


def test_short_records_and_prefill_preserve_initial_unknown_and_e28(cfg,ontology,tmp_path):
    node_items=ontology['world']['items']
    cfg['tts_melotts_assets']=str(tmp_path)
    selected=[]
    texts=prefill_texts(cfg,node_items.values(),on_selection=selected.append,
        reference_state=ontology['state'],places=ontology['world']['places'],
        item_names={k:v['name_ko'] for k,v in node_items.items()})
    p=prompts(cfg)
    assert p['recorded_location'].format(item_topic='지우개는',place='아래 서랍') in texts
    assert p['recorded_open'].format(place_topic='위 서랍은',value=p['recorded_open_false']) in texts
    assert '지우개를 꺼내지 못했어요' in texts
    assert '물건을 옮기다 멈췄어요. 사람이 확인해 주세요' in texts
    assert len(texts)+1<=256 and len(texts)==len(set(texts))
    assert cfg['tts_melotts_startup_timeout_sec']==60 and cfg['tts_melotts_speed']==1.2


@pytest.mark.parametrize('enabled',[True,False])
def test_cue_effective_switch_constructor_and_diagnostic(node,monkeypatch,enabled):
    import ready2go_voice.adapters.cue as module
    created=[]
    monkeypatch.setattr(module,'WakeCue',lambda cfg,lock:created.append((cfg,lock)) or SimpleNamespace())
    node.cfg['voice_flow']['wake_cue_enabled']=enabled
    node._init_wake_cue()
    assert bool(created)==enabled
    assert node.diagnostics[-1]['enabled']==enabled and node.diagnostics[-1]['available']==enabled
    if enabled:assert created[0][1] is node.tts.lock


def test_cue_default_on_explicit_old_local_false_kept(cfg,tmp_path):
    source=load_config(PACKAGE/'params/voice.yaml')
    assert source['voice_flow']['wake_cue_enabled']
    import yaml
    path=tmp_path/'voice.yaml';local=copy.deepcopy(source);local['voice_flow']['wake_cue_enabled']=False
    path.write_text(yaml.safe_dump(local))
    assert not load_config(path)['voice_flow']['wake_cue_enabled']


def test_cue_initialization_failure_blocks_capture_without_device(node,monkeypatch):
    import ready2go_voice.adapters.cue as module
    def fail(*args):raise ValueError('cue unavailable')
    monkeypatch.setattr(module,'WakeCue',fail)
    node.cfg['voice_flow']['wake_cue_enabled']=True
    node._init_wake_cue()
    with pytest.raises(RuntimeError,match='CUE_INITIALIZATION_FAILED'):
        node._capture_after_wake(SimpleNamespace(),None,node.generation)
    assert node.diagnostics[-2]['reason']=='initialization_failed'


@pytest.mark.parametrize('code,kind', [('CAMERA_TIMEOUT','camera'),('TF_UNAVAILABLE','coordinates'),
    ('REGION_NOT_VISIBLE','region'),('GRASP_FAILED','grasp'),('WALL_TOO_CLOSE','interference'),
    ('NEIGHBOR_TOO_CLOSE','interference'),('NO_FREE_SPACE','no_space'),('NOT_REACHED','failure')])
def test_actual_error_codes_do_not_infer_nudge_or_disconnect(code,kind):
    assert warning_kind(code)[0]==kind


def test_generic_timeout_only_exact_current_task_inspection_is_vision(cfg):
    cfg['ontology_file']=str(ROOT/'knowledge/robot_ontology.jsonld')
    task=json.loads((ROOT/'tasks/find_with_unpack.json').read_text())
    seen=[]
    def walk(x):
        if isinstance(x,dict):
            if x.get('action')=='inspect_region':seen.append(x['id'])
            for v in x.values():walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(task);assert seen
    for step,expected in [(seen[0],'vision_timeout'),('not-a-real-step','timeout')]:
        p=RunnerNoticePolicy(cfg)
        p.observe(build_status(False,False,None,None,None,None,None,False))
        p.observe(build_status(True,False,None,task['task_id'],step,None,None,False))
        last=RunResult('FAILED',{},error_code='TIMEOUT',failed_step=step,run_id='run')
        result=p.observe(build_status(False,False,None,None,None,last,task['task_id'],False))
        assert result.kind==expected
        assert p.observe(build_status(False,False,None,None,None,last,task['task_id'],False)) is None


def test_restore_incomplete_is_item_restore_not_safety_unlock(cfg,ontology,tmp_path):
    task=json.loads((ROOT/'tasks/find_with_unpack.json').read_text())
    # Exact current task error and fixed fn.1 wording, not a made-up C field.
    assert 'RESTORE_INCOMPLETE' in json.dumps(task)
    def find(x):
        if isinstance(x,dict):
            if x.get('id')=='fn.1':return x['params']['text']
            for v in x.values():
                found=find(v)
                if found:return found
        elif isinstance(x,list):
            for v in x:
                found=find(v)
                if found:return found
    wording=find(task)
    p=RunnerNoticePolicy(cfg);p.observe(build_status(False,False,None,None,None,None,None,False))
    p.observe(build_status(True,False,None,task['task_id'],'fr',None,None,False))
    result=RunResult('FAILED',{},error_code='RESTORE_INCOMPLETE',failed_step='fr',run_id='run')
    notice=p.observe(build_status(False,False,None,None,None,result,task['task_id'],False))
    assert notice.kind=='restore' and notice.text==wording and '잠금' not in notice.text
    cfg['tts_melotts_assets']=str(tmp_path)
    assert prefill_texts(cfg,ontology['world']['items'].values()).count(wording)==1


def test_explicit_old_recorded_template_kept_grammatical_and_prefilled(node,tmp_path):
    node.cfg['voice_hotfix']['recorded_open']='{place_topic} Runner 기록 기준 {value} 상태입니다. 실제 현재 상태는 별도 확인이 필요합니다.'
    node.cfg['tts_melotts_assets']=str(tmp_path)
    node.parser.state_provider=lambda:dict(located_in={'eraser':'drawer_bottom'},open={'drawer_top':False})
    doc=node.session.text('위 서랍 열려있어?')
    assert '닫힘 상태' in doc['_voice']['final_text'] and '닫혀 상태' not in doc['_voice']['final_text']
    texts=prefill_texts(node.cfg,node.parser.items.values(),reference_state=node.parser.reference_state,
        places=node.parser.places,item_names={k:v['name_ko'] for k,v in node.parser.items.items()})
    assert doc['_voice']['final_text'] in texts


def test_read_speech_stop_cancels_inflight_and_new_halt_event_retires_old_notice(node):
    memory_node(node)
    halt=dict(boot_id='boot',event_id='event1',run_id='run',stop='confirmed',locked=True,resume=None)
    packet(node,phase='halted',halt=halt)
    query(node,'현재 상태');notice=node.pending_notice
    packet(node,phase='halted',seq=2,halt=dict(halt,event_id='event2'))
    before=len(node.texts);node._play_notice(notice,threading.Event())
    assert len(node.texts)==before
    query(node,'현재 상태');notice=node.pending_notice;cancel=threading.Event()
    def speak(text,**kw):
        kw['on_start']({'tts_mock':True})
        with node.submit_lock:node._stop_locked(node.session.text('멈춰',node.generation))
        assert kw['cancel'].is_set()
        raise InterruptedError('stopped')
    node.tts.speak=speak
    node.notice_cancel=cancel
    node._play_notice(notice,cancel)
    assert cancel.is_set() and node.notice_policy.phase=='halted'
    assert [d['intent'] for d in node.published]==['cancel']


def test_pending_recover_status_uses_existing_operation_and_does_not_authorize_resume(node):
    from test_c_control_wire import Wire
    wire=Wire(node)
    work=node.safety_exchange.policy.work
    assert node.safety_sender('recover',work)
    query(node,'현재 상태');play(node)
    assert wire.tts[-1]==prompts(node.cfg)['status_recovering']
    assert all(item['intent']=='recover' for item in list(wire.out.queue))
    assert node.safety_exchange.policy.work is work


def test_text_status_and_refused_control_no_publication_and_corrupt_source_unknown(node):
    memory_node(node);packet(node)
    node._text(SimpleNamespace(data='현재 상태'));play(node)
    assert node.texts[-1]==prompts(node.cfg)['status_idle'] and not node.published
    node._text(SimpleNamespace(data='복구해'));play(node)
    assert node.texts[-1]==prompts(node.cfg)['runtime_no_recover_work'] and not node.published
    node._query_status['last_intent']=[]
    query(node,'현재 상태');play(node)
    assert node.texts[-1]==prompts(node.cfg)['status_unknown']


def test_halted_end_without_local_work_announces_hold_not_empty_or_new_target(node):
    memory_node(node)
    halt=dict(boot_id='boot',event_id='event',run_id='run',stop='unconfirmed',locked=True,resume=None)
    suspended=RunResult('SUSPENDED',{},error_code='HALTED',failed_step='s7.1',run_id='run')
    packet(node,phase='halted',halt=halt,last=suspended)
    assert node.safety_exchange.policy is None
    query(node,'종료');play(node)
    assert '확인' in node.texts[-1] and '종료할 작업이 없습니다' not in node.texts[-1]
    assert node.pending_task_end is None and not node.published and node.normal_notice_cancel.is_set()


@pytest.mark.parametrize('bad',[[],{'id':[],'state':'registered'}, {'id':'q','state':False}])
def test_corrupt_actual_resume_fields_are_unknown_not_a_question_or_crash(node,bad):
    memory_node(node)
    halt=dict(boot_id='boot',event_id='event',run_id='run',stop='confirmed',locked=False,
        resume=dict(offered=True,from_step='s7.1',question=None,request=bad))
    packet(node,halt=halt)
    query(node,'현재 상태');play(node)
    assert node.texts[-1]==prompts(node.cfg)['status_unknown'] and not node.published


def test_notice_handoff_keeps_high_warning_over_low_feedback(node):
    entered, release = threading.Event(), threading.Event()
    original = node._play_notice
    high = Notice('force', '높은 경고', 0, node.notice_policy.revision)
    node.pending_notice = high
    def intercepted(notice, cancel):
        entered.set()
        assert release.wait(2)
        original(notice, cancel)
        node.stop_event.set()
    node._play_notice = intercepted
    worker = threading.Thread(target=node._notice_work)
    worker.start()
    try:
        assert entered.wait(2)
        with node.submit_lock:
            node._control_notice_locked('readonly_query', '낮은 안내')
        assert node.active_notice is high and not node.notice_cancel.is_set()
        assert node.pending_notice is None
    finally:
        release.set()
        worker.join(2)
        node.stop_event.set()
        with node.notice_condition:
            node.notice_condition.notify_all()
    assert not worker.is_alive() and node.texts == ['높은 경고']
    assert node.active_notice is None


@pytest.mark.parametrize('after_start', [False, True])
def test_new_independent_capture_cancels_read_notice_and_owns_dialog(node, monkeypatch, after_start):
    from test_control_feedback import stopped_bridge
    stopped_bridge(node, monkeypatch)
    node.pending_notice = None  # the earlier stop warning is outside this interleaving
    with node.submit_lock:
        node._control_notice_locked('readonly_query', '읽기 안내')
    notice = node.pending_notice
    cancel = node.notice_cancel = threading.Event()
    node.pending_notice = None
    starts = []
    def say(text, **kwargs):
        stamp = dict(tts_started_monotonic=node.now[0], tts_mock=True)
        if after_start:
            kwargs['on_start'](stamp)
            starts.append(text)
        target = node.safety_independent(unique_target=True)
        assert target is not None and node.safety_activity.is_set()
        assert cancel.is_set()
        assert not node.dialog_lock.acquire(blocking=False)
        if not after_start:
            kwargs['on_start'](stamp)  # current activity/cancel must reject actual start
        raise InterruptedError('QUESTION_PRIORITY')
    node.tts.speak = say
    node._play_notice(notice, cancel)
    assert starts == (['읽기 안내'] if after_start else [])
    assert node.active_notice is None and not node.dialog_lock.locked()
    assert not any(d.get('event') == 'tts_finished' and d.get('notice_kind') == 'readonly_query'
                   for d in node.diagnostics)


def upper_drawer(node):
    node.cfg.update(p2_goal_enabled=True, request_run_enabled=True)
    node.declare_parameter = lambda name, default: SimpleNamespace(value=True if name == 'upper_drawer_enabled' else default)
    node._configure_upper_drawer()
    node.bind_request_source(lambda: True)
    node.observe('idle')


@pytest.mark.parametrize('text,value', [('지금 위 서랍 열어줘', True), ('위쪽 서랍 열어줘', True),
                                        ('위 서랍 닫아줘', False), ('지금 위쪽 서랍 닫아줘', False)])
def test_upper_drawer_scoped_request_reaches_existing_request_gate(node, text, value):
    upper_drawer(node)
    goals = [{'predicate': 'open', 'subject': 'drawer_top', 'value': value}]
    node.parser.llm = lambda *_: dict(intent='achieve_goal', targets=[], confidence=.99, goals=goals)
    doc = node.session.text(text, node.generation, request_id='drawer-request')
    node.deliver(doc)
    assert len(node.cfg['p2_goal_catalog']) == 3
    assert len(node.published) == 1 and node.published[0]['goals'] == goals
    assert node.published[0]['request_id'] == 'drawer-request'
    assert node.published[0]['accept_text'] == doc['_voice']['final_text'] and not node.texts


@pytest.mark.parametrize('text', ['위 서랍 열어줘라고 말했어', '위 서랍 열어줄 수 있어?',
                                 '위 서랍 열지 마', '아래 서랍 열어줘',
                                 '지우개를 트레이에 가져다 놔', '위 서랍 열어줘 그리고 닫아줘', '서랍 열어줘'])
def test_upper_drawer_scope_rejects_other_or_nonrequest_goals(node, text):
    upper_drawer(node)
    # Even a model claiming the allowed goal cannot authorize a mismatched utterance.
    node.parser.llm = lambda *_: dict(intent='achieve_goal', targets=[], confidence=.99,
                                    goals=node.cfg['p2_goal_catalog'][0])
    doc = node.session.text(text, node.generation)
    assert doc['intent'] != 'achieve_goal'
    assert node.parser._expected_goals(text) not in node.cfg['p2_goal_catalog']



@pytest.mark.parametrize('text', ['지우개 갖다주고 위 서랍 열어줘',
                                 '지우개 갖다주고 위 서랍 열어둬',
                                 '지우개를 가져다주고 위쪽 서랍 열어줘',
                                 '지우개 갖다 놓고 위 서랍은 열어 둬'])
def test_p2_compound_delivery_reaches_existing_e_and_c_goal_path(node, ontology, schema, text):
    from ready2go_runner.core.intent_router import IntentRouter, PLAN
    from ready2go_runner.core import planner
    upper_drawer(node)
    goals = node.cfg['p2_goal_catalog'][2]
    node.parser.llm = lambda *_: dict(intent='achieve_goal', targets=[], confidence=.99, goals=goals)
    doc = node.session.text(text, node.generation, request_id='compound-request')
    node.deliver(doc)
    assert len(node.published) == 1 and node.published[0]['goals'] == goals
    assert not node.texts and node.published[0]['request_id'] == 'compound-request'
    decision = IntentRouter(schema, {}, ontology['world']['items'], .85).decide(
        json.dumps(node.published[0]), running=False, locked=False)
    assert decision.kind == PLAN and decision.goals == goals
    result = planner.plan(ontology['state'], ontology, decision.goals,
                          limits=planner.parse_limits(planner.DEFAULT_PLAN_LIMITS))
    assert result.status == planner.PLANNED
    from ready2go_knowledge.core.ontology import apply
    state = copy.deepcopy(ontology['state'])
    for step in result.steps:
        state, _ = apply(state, ontology['skills'][step.skill]['effect'], step.params)
    assert state['open']['drawer_top'] is True
    assert state['located_in']['eraser'] == 'handover_zone'


@pytest.mark.parametrize('gate', ['locked', 'busy', 'source', 'evaluation', 'llm_failure'])
def test_p2_compound_preserves_existing_send_guards(node, gate):
    upper_drawer(node)
    goals = node.cfg['p2_goal_catalog'][2]
    def model(*_):
        if gate == 'llm_failure':
            raise TimeoutError('mock')
        return dict(intent='achieve_goal', targets=[], confidence=.99, goals=goals)
    node.parser.llm = model
    doc = node.session.text('지우개 갖다주고 위 서랍 열어줘', node.generation)
    if gate == 'locked': node.observe('halted')
    if gate == 'busy': node.observe('running')
    if gate == 'source': node.bind_request_source(lambda: False)
    if gate == 'evaluation': node.cfg['evaluation_mode'] = True
    node.deliver(doc)
    assert not any(d['intent'] in ('find_item', 'achieve_goal') for d in node.published)
    assert node.request_run.pending is None


@pytest.mark.parametrize('text', ['지우개 갖다주고 아래 서랍 열어줘',
                                 '립밤 갖다주고 위 서랍 열어줘',
                                 '지우개 갖다주고 위 서랍 닫아줘',
                                 '지우개 갖다주고 위 서랍 열지 마',
                                 '지우개 갖다주고 위 서랍 열어줄 수 있어?'])
def test_p2_compound_rejects_unselected_or_nonrequest_goals(node, text):
    upper_drawer(node)
    node.parser.llm = lambda *_: dict(intent='achieve_goal', targets=[], confidence=.99,
                                    goals=node.cfg['p2_goal_catalog'][2])
    doc = node.session.text(text, node.generation)
    assert doc['intent'] != 'achieve_goal'


def test_upper_drawer_activation_requires_both_existing_optins(node):
    node.declare_parameter = lambda *args: SimpleNamespace(value=True)
    with pytest.raises(ValueError, match='both P2/request'):
        node._configure_upper_drawer()
    assert node.cfg['p2_goal_enabled'] is False and node.cfg['request_run_enabled'] is False


@pytest.mark.parametrize('gate', ['locked', 'busy', 'source', 'evaluation'])
def test_upper_drawer_existing_runtime_gates_still_hold(node, gate):
    upper_drawer(node)
    goals = node.cfg['p2_goal_catalog'][0]
    node.parser.llm = lambda *_: dict(intent='achieve_goal', targets=[], confidence=.99, goals=goals)
    doc = node.session.text('지금 위 서랍 열어줘', node.generation)
    if gate == 'locked': node.observe('halted')
    if gate == 'busy': node.observe('running')
    if gate == 'source': node.bind_request_source(lambda: False)
    if gate == 'evaluation': node.cfg['evaluation_mode'] = True
    node.deliver(doc)
    assert not node.published and node.request_run.pending is None


def test_351_safety_audio_reuses_stt_for_readonly_receiver_and_preserves_work_question(node):
    from test_safety_exchange import stopped, question, delivered, audio, WORK, STT
    memory_node(node);packet(node, phase='halted')
    node.safety_exchange = ex = stopped(node.cfg)
    sent = []
    node.safety_sender = lambda *args: sent.append(args)
    node.now[0] = 6.
    calls = []
    class CountSTT(STT):
        def transcribe(self, *args, **kwargs):
            calls.append(self.text)
            return super().transcribe(*args, **kwargs)
    node.session.stt = CountSTT('현재 상태', node.now)
    node.parser.llm = lambda *args: pytest.fail('readonly STT must not call LLM')
    node._safety_recording(audio(), WORK)  # actual safety_audio -> actual receiver, not text delivery
    assert calls == ['현재 상태'] and ex.policy.work == WORK and ex.policy.independent is None
    assert not sent and not node.published and node.pending_notice.kind == 'readonly_query'
    play(node)
    assert node.texts[-1] == prompts(node.cfg)['status_halted']
    q = question(ex);delivered(ex,q)
    before = (q, ex.policy.question_until, ex.policy.registered_at, ex.policy.finished_at)
    result = node.session.safety_audio(ex, q, audio(), cancel=node.safety_cancel)
    with node.dialog_lock:
        with node.submit_lock:
            node.safety_activity.set()
            node.safety_running = node.safety_cancel
            node._safety_result_locked(result, node.safety_cancel, node.safety_sender)
            node._release_safety_locked(node.safety_cancel)
            assert node.pending_notice is None  # never queue into a still-owned question dialog
    with node.submit_lock:
        node._flush_safety_readonly_locked()
    assert node.pending_notice.kind == 'readonly_query'
    assert calls == ['현재 상태', '현재 상태']  # one SDK call for each distinct recording
    assert before == (ex.policy.question, ex.policy.question_until, ex.policy.registered_at, ex.policy.finished_at)
    assert ex.policy.work == WORK and ex.policy.request is None and ex.reserve(q) is not None
    assert not sent and not node.published


def speech_run(node, *, task='find_with_unpack', goal=False):
    endpoints, _, _, _ = memory_node(node)
    node.cfg['request_run_enabled'] = True
    packet(node)
    if goal:
        node.cfg['p2_goal_enabled'] = True
        node.declare_parameter = lambda name, default: SimpleNamespace(value=True if name == 'upper_drawer_enabled' else default)
        node._configure_upper_drawer()
        node.parser.llm = lambda *_: dict(intent='achieve_goal', targets=[], confidence=.99,
            goals=[{'predicate':'open', 'subject':'drawer_top', 'value':True}])
    node.deliver(node.session.text('위 서랍 열어줘' if goal else '지우개 가져다줘',node.generation, request_id='speech-request'))
    decision = dict(intent='achieve_goal' if goal else 'find_item',targets=[] if goal else ['eraser'],request_id='speech-request',decision='run',run_id='speech-run')
    packet(node,phase='running',seq=2,decision=decision,task=task)
    assert node.request_run.run_id == 'speech-run'
    def actual_proof(text, **kwargs):
        node.texts.append(text)
        stamp = dict(tts_started_monotonic=node.now[0],tts_mock=False,tts_start_basis='portaudio_first_dac')
        kwargs['on_start'](stamp)
        node.now[0] += .01
        kwargs['on_timing'](dict(playback_ended_monotonic=node.now[0],playback_end_basis='portaudio_finished_callback'))
        return stamp
    node.tts.speak = actual_proof  # software playback proof fixture; no physical output
    return endpoints, decision


def receive_speech(node, text):
    request = SimpleNamespace(params_json=json.dumps({'text':text}))
    assert node._goal(request) == 1
    outcomes = []
    goal = SimpleNamespace(request=request,is_cancel_requested=False,succeed=lambda:outcomes.append('success'),
        abort=lambda:outcomes.append('abort'),canceled=lambda:outcomes.append('cancel'))
    return node._speak(goal), outcomes


def first_speech(node):
    result, outcomes = receive_speech(node,node.request_run.pending['accept_text'])
    assert result.success and outcomes == ['success']


def test_351_current_followup_completion_close_error_speak_after_first_success(node):
    speech_run(node)
    first_speech(node)
    assert node._goal(SimpleNamespace(params_json=json.dumps({'text':node.request_run.pending['accept_text']}))) == 0
    for text in ('지우개를 앞쪽 트레이에 놓았어요', '서랍을 닫을게요', '지우개를 꺼내지 못했어요'):
        result, outcomes = receive_speech(node,text)
        assert result.success and outcomes == ['success'] and node.texts[-1] == text


@pytest.mark.parametrize('boundary',['finished','locked','boot','lost','changed_after_accept'])
def test_351_followup_blocks_finished_changed_source_and_lock(node,boundary):
    endpoints, decision = speech_run(node);first_speech(node)
    request = SimpleNamespace(params_json=json.dumps({'text':'서랍을 닫을게요'}))
    if boundary == 'changed_after_accept': assert node._goal(request) == 1
    if boundary in ('finished','changed_after_accept'):
        packet(node,seq=3,last=RunResult('COMPLETED',{},run_id='speech-run'),decision=decision)
    elif boundary == 'locked': packet(node,phase='halted',seq=3,decision=decision)
    elif boundary == 'boot': packet(node,phase='running',seq=3,boot='new-boot',decision=decision)
    else: endpoints['/runner/status'] = []
    if boundary == 'changed_after_accept':
        before = list(node.texts);outcomes=[]
        goal = SimpleNamespace(request=request,is_cancel_requested=False,succeed=lambda:outcomes.append('success'),
            abort=lambda:outcomes.append('abort'),canceled=lambda:outcomes.append('cancel'))
        result = node._speak(goal)
        assert not result.success and outcomes == ['abort'] and node.texts == before
    else: assert node._goal(request) == 0


def test_351_first_speech_failure_keeps_actual_c_first_motion_gate_closed(node):
    from ready2go_runner.core.interpreter import Runner, ActionResult
    from ready2go_runner.core.intent_router import add_accept_speak
    speech_run(node)
    node.tts.speak = lambda text, **kwargs: kwargs['on_start'](dict(tts_started_monotonic=node.now[0],tts_mock=True))
    motions=[]
    def execute(action, params, timeout):
        if action == 'speak':
            result, _ = receive_speech(node,params['text'])
            return ActionResult(result.success,error_code=getattr(result,'error_code',None))
        motions.append(action)
        return ActionResult(True)
    task = add_accept_speak({'task_id':'first-gate-test','sequence':[
        {'id':'p0','action':'set_var','params':{'name':'announce_pending','value':False}},
        {'id':'p1','action':'go_home','params':{}}],
        'finally':[{'id':'fh','action':'go_home','params':{}}]},
        {'accept_text':node.request_run.pending['accept_text']})
    result = Runner(execute).run(task,inputs={'accept_text':node.request_run.pending['accept_text']},run_id='speech-run')
    assert result.overall_status == 'FAILED' and motions == []
    assert getattr(node,'request_speech_completed',None) is None
    assert node._goal(SimpleNamespace(params_json=json.dumps({'text':'서랍을 닫을게요'}))) == 0


def test_351_backend_error_only_exact_speak_step_is_audio_failure_and_required(cfg,ontology,tmp_path):
    cfg['ontology_file']=str(ROOT/'knowledge/robot_ontology.jsonld')
    task=json.loads((ROOT/'tasks/find_with_unpack.json').read_text())
    for task_id, step, kind in [(task['task_id'],'s8.t3','speech'),
                               (task['task_id'],'unknown-step','failure'),('unknown-task','s8.t3','failure')]:
        policy=RunnerNoticePolicy(cfg)
        policy.observe(build_status(False,False,None,None,None,None,None,False))
        policy.observe(build_status(True,False,None,task_id,step,None,None,False))
        last=RunResult('FAILED',{},error_code='BACKEND_ERROR',failed_step=step,run_id='backend-run')
        notice=policy.observe(build_status(False,False,None,None,None,last,task_id,False))
        assert notice.kind == kind
        if kind == 'speech': assert notice.text == prompts(cfg)['notice_speech']
    cfg['tts_melotts_assets']=str(tmp_path)
    assert prompts(cfg)['notice_speech'] in prefill_texts(cfg,ontology['world']['items'].values())


def test_351_busy_preserves_current_speech_but_new_run_does_not(node):
    _, decision = speech_run(node); first_speech(node)
    busy = dict(request_id='other-request', intent='find_item', targets=['car_key'],
                decision='reject', reason='BUSY')
    packet(node, phase='running', seq=3, decision=busy)
    result, outcomes = receive_speech(node, '서랍을 닫을게요')
    assert result.success and outcomes == ['success']
    packet(node, phase='running', seq=4, decision=dict(busy, decision='run', run_id='new-run'))
    assert node._goal(SimpleNamespace(params_json=json.dumps({'text':'서랍을 닫을게요'}))) == 0
    # An old decision heartbeat cannot restore the retired first-playback token.
    packet(node, phase='running', seq=5, decision=decision)
    assert node._goal(SimpleNamespace(params_json=json.dumps({'text':'서랍을 닫을게요'}))) == 0


@pytest.mark.parametrize('case', ['success', 'expanded', 'dynamic_goal', 'playback_failure', 'unconfirmed_playback', 'other_run', 'unrelated_speech', 'safety'])
def test_351_final_notice_suppression_requires_same_run_cause_playback(node, case):
    from ready2go_runner.core import failure_speech
    node.notice_policy = RunnerNoticePolicy(node.cfg)
    task = 'achieve_goal_generated_plan' if case == 'dynamic_goal' else 'find_with_unpack'
    _, decision = speech_run(node, task=task, goal=case == 'dynamic_goal'); first_speech(node)
    packet(node, phase='running', seq=3, decision=decision, step='f1' if case in ('expanded', 'dynamic_goal') else 'fx.1', task=task)
    text = failure_speech.text('CAMERA_TIMEOUT', 'inspect_region')
    if case == 'playback_failure':
        def failed(text, **kwargs): raise RuntimeError('playback failed')
        node.tts.speak = failed
    elif case == 'unconfirmed_playback':
        node.tts.speak = lambda text, **kwargs: {'tts_mock':True}
    result, _ = receive_speech(node, '서랍을 닫았어요' if case == 'unrelated_speech' else text)
    assert result.success == (case not in ('playback_failure', 'unconfirmed_playback'))
    if case == 'other_run':
        packet(node, phase='running', seq=4, decision=dict(decision, request_id='other', run_id='new-run'))
    # Actual C status construction and actual E status receiver, no physical playback.
    last = RunResult('FAILED', {}, error_code='CAMERA_TIMEOUT', failed_step='expanded_skill.s4' if case in ('expanded', 'dynamic_goal') else 's4',
                     run_id='new-run' if case == 'other_run' else 'speech-run')
    packet(node, phase='halted' if case == 'safety' else 'idle', seq=5, last=last, decision=decision, task=task)
    if case in ('success', 'expanded', 'dynamic_goal'): assert node.pending_notice is None
    else:
        assert node.pending_notice is not None
        assert node.pending_notice.priority < 3 if case == 'safety' else node.pending_notice.kind == 'camera'


def test_351_c_failure_factory_and_no_room_are_required_prefill(cfg, ontology, tmp_path):
    from ready2go_voice.core.runner_speech import required_texts, failure_texts
    from ready2go_runner.core import failure_speech
    from ready2go_runner.core.variables import interpolate
    cfg['tts_melotts_assets'] = str(tmp_path)
    items = list(ontology['world']['items'].values())
    selections = []
    texts = prefill_texts(cfg, items, on_selection=selections.append)
    assert set(required_texts(cfg, items)) <= set(texts)
    template = next(s for s in RunnerNoticePolicy(cfg).task_steps['find_with_unpack'].values()
                    if s['id'] == 's8.n1')['params']['text']
    assert {interpolate(template, {'loc': item}) for item in items} <= set(texts)
    assert set(failure_speech.BY_CODE.values()) <= failure_texts()
    assert failure_speech.GENERIC in texts
    for action in failure_speech.ACTION_KO:
        assert failure_speech.text('TIMEOUT', action) in texts
        assert failure_speech.text(None, action) in texts
    assert len(texts) == len(set(texts)) and len(texts) + 1 <= 256
    assert selections[0]['frequent_count'] == 0
