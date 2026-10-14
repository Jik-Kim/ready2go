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


def packet(node, *, phase='idle',seq=1,boot='boot',halt=None,last=None,decision=None):
    result=build_status(phase=='running',phase=='halted','HALTED' if phase=='halted' else None,
        'find_with_unpack' if phase=='running' else None,'s7.1' if phase=='running' else None,
        last,'find_with_unpack' if last else None,False,halt=halt)
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
    assert node.texts[-1]==prompts(node.cfg)['control_rejected'] and not node.published
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
    assert len(node.cfg['p2_goal_catalog']) == 2
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
    assert node.parser._expected_goals(text) is None


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
