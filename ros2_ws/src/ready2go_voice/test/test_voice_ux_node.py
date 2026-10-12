"""실제 VoiceNode 메서드의 ROS 비의존 모의. ROS topic/action 시험과 구분합니다."""
import ast
import copy
from collections import deque
import json
import queue
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import uuid
import pytest
from jsonschema import Draft7Validator
from ready2go_voice.adapters.api import LangChainIntent
from ready2go_voice.core.intent import intent, IntentParser
from ready2go_voice.core.recovery_confirmation import TaskEndCandidate
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.core.response import final_response
from ready2go_voice.core.diagnostics import redact
from ready2go_voice.core.runner_notice import RunnerNoticePolicy, Notice
from ready2go_voice.core.request_run import RequestRun
from ready2go_voice.core.place_exchange import PlaceExchange
from ready2go_voice.core.place_input import decode, identity, question_input, registered, result_notice
from ready2go_voice.core.safety_exchange import SafetyExchange, IndependentRegistration, QuestionDeclined, RecoveryRequest
from ready2go_voice.core.recovery_confirmation import finite, safety_utterance, task_end_utterance
from ready2go_voice.adapters.audio import Recorder
from ready2go_voice.core.tts_prefill import remember_text


@pytest.fixture
def node_class():
    # ROS import/초기화를 모방하지 않고 저장된 실제 메서드 본문만 실행합니다.
    source=Path(__file__).resolve().parents[1]/'ready2go_voice/nodes/voice_node.py'
    tree=ast.parse(source.read_text())
    tree.body=[n for n in tree.body if isinstance(n,ast.ClassDef) or isinstance(n,ast.FunctionDef) and n.name=='runner_blocks']
    namespace=dict(Node=object,deque=deque,json=json,queue=queue,threading=threading,time=time,uuid=uuid,
                   intent=intent,final_response=final_response,redact=redact,remember_text=remember_text,
                   Notice=Notice,RunnerNoticePolicy=RunnerNoticePolicy, Recorder=Recorder,
                   TaskEndCandidate=TaskEndCandidate,finite=finite,safety_utterance=safety_utterance,task_end_utterance=task_end_utterance,
                   decode=decode,identity=identity,question_input=question_input,registered=registered,result_notice=result_notice,
                   IndependentRegistration=IndependentRegistration,QuestionDeclined=QuestionDeclined,RecoveryRequest=RecoveryRequest,
                   GoalResponse=SimpleNamespace(ACCEPT=1,REJECT=0),
                   Skill=SimpleNamespace(Result=SimpleNamespace))
    exec(compile(tree,str(source),'exec'),namespace)
    return namespace['VoiceNode']


@pytest.fixture
def node(node_class,ontology,schema,cfg):
    cfg.update(evaluation_mode=False,tts_engine='espeak')
    now=[time.monotonic()]
    parser=IntentParser(ontology,schema,cfg)
    h=node_class.__new__(node_class)
    h.__dict__.update(cfg=cfg,parser=parser,session=VoiceSession(parser,cfg,clock=lambda:now[0]),
        generation=0,stop_event=threading.Event(),request_cancel=threading.Event(),speaking=threading.Event(),
        submit_lock=threading.RLock(),notice_condition=threading.Condition(),notice_policy=RunnerNoticePolicy(),
        normal_notice_cancel=threading.Event(),notice_cancel=threading.Event(),pending_notice=None,warning_epoch=0,
        diagnostics=[],published=[],texts=[],now=now,requests=queue.Queue(),request_running=None)
    h.local_context=threading.local()
    h.place_clock=lambda:now[0]
    h.playback_lock=threading.Lock();h.playback_texts={};h.stop_spoken=None
    h.busy=threading.Event();h.audio_lock=threading.Lock();h.dialog_lock=threading.Lock()
    h.request_run=RequestRun();h.request_source_check=None;h.request_speech_used=set();h.goal_request_run=None
    h.goal_lock=threading.Lock()
    h.place_condition=threading.Condition(h.submit_lock)
    h.place_exchange=PlaceExchange(cfg,item_names={k:v['name_ko'] for k,v in parser.items.items()})
    h.place_topic='';h.place_pending=h.place_identity=h.place_registered=h.place_registered_at=None
    h.place_running=None;h.place_cancel=threading.Event();h.place_activity=threading.Event();h.place_results=set()
    h.safety_exchange=SafetyExchange(cfg);h.safety_sender=None;h.safety_pending=h.safety_running=None
    h.safety_cancel=threading.Event();h.safety_activity=threading.Event()
    h._diagnostic=lambda d:h.diagnostics.append(copy.deepcopy(d))
    h._publish=lambda d:h.published.append(copy.deepcopy(d))
    def speak(text,**kw):
        h.texts.append(text)
        kw['on_start']({'tts_started_monotonic':now[0],'tts_started_unix':123,'tts_mock':True})
    h.tts=SimpleNamespace(speak=speak,lock=threading.Lock())
    h.deliver=lambda d:node_class._deliver(h,d,h.generation)
    h.observe=lambda phase:node_class._runner_status(h,SimpleNamespace(data=json.dumps({
        'phase':phase,'halt_code':'HALTED' if phase=='halted' else None,
        'task_id':'find_item' if phase=='running' else None,'last':None})))
    return h


def ask(node):
    doc=node.session.text('망치',node.generation)
    node.deliver(doc)
    assert node.session.conversation.pending
    return doc


def test_actual_work_passes_queue_identity_to_session_preparation(node, node_class):
    node.requests = queue.Queue()
    node.requests.put(('text', '망치 좀', 0, 'queued-request'))
    node.busy = threading.Event()
    node.local_context = threading.local()
    docs = []
    def deliver(doc, generation):
        docs.append(doc)
        node.stop_event.set()  # 한 요청의 실제 _work 경로만 확인합니다.
    node._deliver = deliver
    node_class._work(node)
    assert len(docs) == 1 and docs[0]['_voice']['request_id'] == 'queued-request'
    assert node.session.consume_acceptance_text(docs[0], 0) == docs[0]['_voice']['final_text']
    assert not node.texts and not node.published  # 내부 준비는 재생/발행하지 않습니다.


@pytest.mark.parametrize('first,second', [('응', '맞아'), ('응 맞아', '네 맞아요'), ('네 맞아요', '응 맞아'), ('어어', '어어')])
def test_initial_question_then_different_affirmations_only_one_find(node, first, second):
    doc=ask(node)
    assert node.published[0]['intent']=='clarify'
    assert any(d['event']=='question_ready' and d['question_id']==doc['_voice']['question_id'] for d in node.diagnostics)
    node.deliver(node.session.text(first,0))
    node.deliver(node.session.text(second,0))
    assert sum(d['intent']=='find_item' for d in node.published)==1
    accepted = next(d for d in node.published if d['intent'] == 'find_item')
    assert accepted['targets'] == ['toy_hammer']
    assert accepted['_voice']['question_id'] == doc['_voice']['question_id']
    assert len(node.texts)==3
    final=[d['text'] for d in node.diagnostics if d['event']=='final_response']
    assert final==node.texts


@pytest.mark.parametrize('reply', ['응 맞아', '네 맞아요', '어어'])
@pytest.mark.parametrize('state', ['absent', 'expired', 'tts_failure', 'running'])
def test_short_reply_requires_successful_current_question(node, reply, state):
    if state == 'tts_failure':
        node.tts.speak = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('mock'))
    if state == 'running':
        node.observe('running')
    if state != 'absent':
        question = node.session.text('망치', node.generation)
        node.deliver(question)
    if state == 'expired':
        node.now[0] = node.session.conversation.pending.expires
    if state in ('running', 'tts_failure'):
        assert node.session.conversation.pending is None
        assert not any(d['event'] == 'question_ready' for d in node.diagnostics)
    doc = node.session.text(reply, node.generation, blocked=state == 'running')
    assert doc['intent'] == 'clarify' and doc['targets'] == []
    assert not doc['source']['execution_allowed']


@pytest.mark.parametrize('reply', ['응 맞아 하지 마', '네 맞아요 아니요', '응 맞아 취소해', '응 맞아? 아니야',
    '어', '어어어', '어어 아니요', '"어어"', '그 사람이 어어라고 했어', '어어 하지 마', '어어 취소해'])
def test_mixed_or_unapproved_short_reply_cannot_consume_target_as_positive(node, reply):
    from ready2go_voice.core.intent import is_context_reply
    assert not is_context_reply(reply)
    ask(node)
    doc = node.session.text(reply, node.generation)
    assert doc['intent'] != 'find_item' and not doc['source']['execution_allowed']
    assert doc['targets'] == [] and node.session.conversation.pending is None


@pytest.mark.parametrize('reply', ['응 맞아', '어어'])
@pytest.mark.parametrize('stt_failure', [False, True])
def test_empty_transcript_preserves_but_sdk_failure_drops_short_reply_context(node, stt_failure, reply):
    from ready2go_voice.adapters.audio import Recording
    question = ask(node)
    expires = node.session.conversation.pending.expires
    class STT:
        def transcribe(self, *_):
            if stt_failure: raise RuntimeError('mock SDK failure')
            return ''
    node.session.stt = STT()
    node.session.speech_gate = SimpleNamespace(check=lambda *a, **k: True)
    doc = node.session.audio(Recording(b'\0\0' * 1600, None, None, recording_mode='fixed'))
    node.deliver(doc)
    assert node.now[0] < expires
    if stt_failure:
        assert node.session.conversation.pending is None
    else:
        assert node.session.conversation.pending.id == question['_voice']['question_id']
        assert node.session.conversation.pending.expires == expires
    later = node.session.text(reply, node.generation)
    assert later['intent'] == ('clarify' if stt_failure else 'find_item')
    assert later['targets'] == ([] if stt_failure else ['toy_hammer'])
    assert later['source']['execution_allowed'] is not stt_failure


def test_evaluation_question_and_answers_never_publish(node):
    node.cfg['evaluation_mode']=True
    ask(node);node.deliver(node.session.text('응',0))
    assert not node.published


@pytest.mark.parametrize('phase',['running','halted'])
@pytest.mark.parametrize('when',['before_parse','after_parse','during_tts'])
def test_observed_busy_or_lock_invalidates_question_candidate(node,phase,when):
    ask(node)
    node.published.clear()
    if when=='before_parse':node.observe(phase)
    doc=node.session.text('응',0)
    if when=='after_parse':node.observe(phase)
    if when=='during_tts':
        original=node.tts.speak
        def speak(text,**kw):
            original(text,**kw);node.observe(phase);node.observe('idle')
        node.tts.speak=speak
    node.deliver(doc)
    assert not any(d['intent']=='find_item' for d in node.published)
    assert not node.session.conversation.pending


def test_first_latched_running_and_halted_cannot_execute(node):
    for phase in ('running','halted'):
        node.notice_policy=RunnerNoticePolicy();node.observe(phase)
        node.deliver(node.session.text('지우개 가져와',0))
    assert not any(d['intent']=='find_item' for d in node.published)


@pytest.mark.parametrize('failure',['tts','publish','cancel'])
def test_answer_failure_has_no_automatic_retry(node,node_class,failure):
    ask(node);node.published.clear()
    doc=node.session.text('응',0)
    if failure=='tts':node.tts.speak=lambda *a,**k:(_ for _ in ()).throw(RuntimeError())
    if failure=='publish':node._publish=lambda d:(_ for _ in ()).throw(RuntimeError())
    if failure=='cancel':node_class._text(node,SimpleNamespace(data='취소'))
    node.deliver(doc)
    assert not any(d['intent']=='find_item' for d in node.published)
    assert not node.session.conversation.pending
    assert node.session.text('맞아',node.generation)['intent']!='find_item'


def test_final_valid_llm_text_is_exact_console_and_speak_input(node,node_class):
    text='망치를 가져오는 요청으로 이해했어요.'
    node.parser.llm=lambda *_:{'intent':'find_item','targets':['toy_hammer'],'confidence':.99,'response_text':text}
    node.deliver(node.session.text('망치 좀',0))
    assert node.texts==[text]
    event=next(d for d in node.diagnostics if d['event']=='final_response')
    messages=[];node.get_logger=lambda:SimpleNamespace(info=messages.append)
    node_class._diagnostic(node,event)
    assert messages==[text]
    assert 'clarify_question' not in node.published[0]


def test_wire_omits_internal_question_authority_but_preserves_source(node,node_class):
    class String:pass
    node_class._publish.__globals__['String']=String
    sent=[];node.publisher=SimpleNamespace(publish=lambda m:sent.append(json.loads(m.data)))
    doc=node.session.text('지우개 가져와',0)
    node_class._publish(node,doc)
    assert '_voice' not in sent[0]
    assert sent[0]['source']==doc['source']


def test_detail_file_gets_raw_once_and_console_never_full_json(node,node_class):
    messages=[];details=[]
    node.get_logger=lambda:SimpleNamespace(info=messages.append)
    node.diagnostic_file=SimpleNamespace(emit=details.append)
    doc=node.session.text('지우개 가져와',0)
    doc['source']['llm_raw']={'confidence':.99,'raw':'original'}
    node_class._diagnostic(node,{'event':'interpretation','intent':doc})
    node_class._diagnostic(node,{'event':'intent','intent':doc,'published':True})
    assert details[0]['intent']['source']['llm_raw']['raw']=='original'
    assert 'llm_raw' not in details[1]['intent']['source']
    assert not any('original' in message or 'confidence' in message for message in messages)
    assert '수락 미확인' in messages[-1]


@pytest.mark.parametrize('text', ['망치 가져다줘', '', '망치\r\n가져다줘'])
def test_stt_console_one_line_and_detail_redaction(node, node_class, tmp_path, monkeypatch, text):
    from ready2go_voice.core.diagnostics import DiagnosticFile
    secret = 'test-sensitive-transcription-token'
    monkeypatch.setenv('OPENAI_API_KEY', secret)
    messages = []
    node.get_logger = lambda: SimpleNamespace(info=messages.append)
    node.cfg['diagnostic_file'] = str(tmp_path/'diagnostic.jsonl')
    writer = node.diagnostic_file = DiagnosticFile(node.cfg, messages.append)
    try:
        payload = text + ' ' + secret if text else ''
        node_class._diagnostic(node, {'event': 'stt_result', 'text': payload})
    finally:
        writer.close()
    expected = text + ' [REDACTED]' if text else ''
    assert messages == ['STT 결과: ' + expected.replace('\n', ' ').replace('\r', ' ')]
    assert '\n' not in messages[0] and '\r' not in messages[0]
    records = [json.loads(line) for line in (tmp_path/'diagnostic.jsonl').read_text().splitlines()]
    assert len(records) == 1 and records[0]['event'] == 'stt_result'
    assert records[0]['text'] == expected
    assert secret not in (tmp_path/'diagnostic.jsonl').read_text()


def test_no_speech_and_stt_failure_are_distinct_console_events(node, node_class):
    messages = []
    node.get_logger = lambda: SimpleNamespace(info=messages.append)
    node_class._diagnostic(node, {'event': 'no_speech'})
    node_class._diagnostic(node, {'event': 'stt_failed', 'error_type': 'RateLimitError',
        'api_error': {'status': 429, 'code': None, 'type': None, 'category': 'unknown_429'}})
    assert len(messages) == 2
    assert messages[0].startswith('발화 없음:') and messages[1].startswith('STT 실패:')
    assert not any(m.startswith('STT 결과:') for m in messages)


@pytest.mark.parametrize('text,expected', [('망치 가져다줘', 'find_item'), ('망치', 'clarify'),
    ('망치, 망치, 망치, 망치', 'clarify'), ('망치 가져다주지 마', 'clarify'), ('응', 'clarify')])
@pytest.mark.parametrize('mock_llm', [False, True])
def test_hammer_delivery_and_noncommands_keep_decision(node, text, expected, mock_llm):
    if mock_llm:
        node.parser.llm = lambda *_: {'intent': 'find_item' if expected == 'find_item' else expected,
            'targets': ['toy_hammer'] if expected == 'find_item' else [], 'confidence': .99,
            'clarify_question': '장난감 망치 가져오기 요청이 맞나요?' if expected == 'clarify' else None}
    doc = node.session.text(text)
    assert doc['intent'] == expected
    assert doc['source']['execution_allowed'] == (expected == 'find_item')
    if expected == 'find_item':
        assert doc['targets'] == ['toy_hammer'] and 'question_target' not in doc['_voice']
    else:
        assert doc['targets'] == []


def test_submit_to_work_keeps_local_request_id(node,node_class):
    node.busy=threading.Event();node.requests=queue.Queue(maxsize=1);node.local_context=threading.local()
    assert node_class._submit(node,('text','지우개 가져와'),request_id='r-one')
    def deliver(doc,generation):
        node_class._deliver(node,doc,generation)
        node.stop_event.set()
    node._deliver=deliver
    node_class._work(node)
    interpretation=next(d for d in node.diagnostics if d['event']=='interpretation')
    assert interpretation['intent']['_voice']['request_id']=='r-one'
    assert not node.busy.is_set() and len(node.published)==1


@pytest.mark.parametrize('control',['지금 뭐해?','취소'])
@pytest.mark.parametrize('evaluation',[False,True])
def test_control_fast_path_invalidates_question_without_wait(node,node_class,control,evaluation):
    ask(node);node.published.clear();node.cfg['evaluation_mode']=evaluation
    node_class._text(node,SimpleNamespace(data=control))
    assert not node.session.conversation.pending
    assert (len(node.published)==0) is evaluation
    assert node.session.text('응',node.generation)['intent']!='find_item'


def test_targetless_invalid_clarify_console_and_tts_are_safe(node,node_class):
    node.parser.llm=lambda *_:{'intent':'clarify','targets':[],'confidence':.99,
                               'clarify_question':'실행을 완료했어요.','response_text':None}
    node.deliver(node.session.text('무슨 말인지 모르겠어',0))
    assert node.texts==[node.cfg['clarify_prompts']['general']]
    assert all('실행을 완료' not in d.get('text','') for d in node.diagnostics)


@pytest.mark.parametrize('text,reason,expected', [
    ('사과 가져와', 'unregistered_item', '그 물품은 지원하지 않습니다.'),
    ('박수 쳐줘', 'unsupported_request', '그 요청은 지원하지 않습니다.'),
])
@pytest.mark.parametrize('evaluation', [False, True])
def test_schema_reason_reaches_console_tts_and_existing_wire_shape(node, node_class, text, reason, expected, evaluation):
    raw = {'intent': 'unknown', 'targets': [], 'confidence': .99, 'clarify_question': None,
           'response_text': '그 물품은 지원하지 않습니다.', 'rejection_reason': reason}
    Draft7Validator(LangChainIntent(node.cfg, node.parser.items).schema).validate(raw)
    node.parser.llm = lambda *_: json.dumps(raw)
    node.cfg['evaluation_mode'] = evaluation
    class String: pass
    node_class._publish.__globals__['String'] = String
    wire = []
    node.publisher = SimpleNamespace(publish=lambda m: wire.append(json.loads(m.data)))
    node._publish = lambda doc: node_class._publish(node, doc)
    doc = node.session.text(text, node.generation)
    node.deliver(doc)
    assert doc['intent'] == 'unknown' and doc['targets'] == []
    assert node.texts == [expected]
    final = next(d for d in node.diagnostics if d['event'] == 'final_response')
    messages = []; node.get_logger = lambda: SimpleNamespace(info=messages.append)
    node_class._diagnostic(node, final)
    assert messages == [expected]
    assert bool(wire) is not evaluation
    if wire:
        assert set(wire[0]) == {'intent', 'targets', 'confidence', 'source'}
        assert wire[0]['source'] == doc['source']
        assert 'rejection_reason' not in wire[0]['source']
        assert json.loads(wire[0]['source']['llm_raw']) == raw  # existing raw diagnostic retained
        assert wire[0]['targets'] == [] and not wire[0]['source']['execution_allowed']
    assert node.session.conversation.pending is None


@pytest.mark.parametrize('reply', ['응', '맞아', '그걸로'])
@pytest.mark.parametrize('state', ['absent', 'expired', 'cancel', 'generation', 'warning'])
@pytest.mark.parametrize('evaluation', [False, True])
def test_orphan_reply_node_reasks_without_publishing_old_target(node, node_class, reply, state, evaluation):
    if state != 'absent':
        ask(node)
    if state == 'expired':
        node.now[0] += node.cfg['dialogue_timeout_sec']
    elif state == 'cancel':
        node_class._text(node, SimpleNamespace(data='취소'))
    elif state == 'generation':
        node.generation += 1
    elif state == 'warning':
        node.observe('halted'); node.observe('idle')
    node.published.clear(); node.texts.clear(); node.diagnostics.clear()
    node.cfg['evaluation_mode'] = evaluation
    doc = node.session.text(reply, node.generation)
    node.deliver(doc)
    expected = node.cfg['clarify_prompts']['missing_item']
    assert doc['intent'] == 'clarify' and doc['targets'] == []
    assert node.texts == [expected]
    assert not doc['_voice'].get('context_answer') and 'question_target' not in doc['_voice']
    assert all(d['intent'] == 'clarify' and d['targets'] == [] for d in node.published)
    assert bool(node.published) is not evaluation
    assert node.session.conversation.pending.target is None


def test_internal_goal_console_diagnostics_only_no_tts_or_publish(node):
    node.cfg['p2_goal_enabled'] = True
    node.parser.llm = lambda *_: dict(intent='achieve_goal', targets=[], confidence=.99,
        goals=node.cfg['p2_goal_catalog'][1], response_text='서랍을 열었어요.')
    doc = node.session.text('위 서랍 열어 둬', 0)
    assert doc['intent'] == 'achieve_goal'
    node.deliver(doc)
    assert not node.published
    assert not node.session.conversation.pending
    assert node.texts == []  # actual _deliver never calls TTS for achieve_goal
    final = [d for d in node.diagnostics if d['event'] == 'final_response']
    assert len(final) == 1 and final[0]['text'] == doc['_voice']['final_text']
    assert '목표 요청' in final[0]['text']  # opt-in gate와 실제 실행은 별도로 검사합니다.
    events = [d for d in node.diagnostics if d['event'] == 'intent']
    assert len(events) == 1 and events[0]['published'] is False


def test_work_prepares_queue_bound_candidate_but_p1_publish_keeps_wire(node, node_class):
    node.requests = queue.Queue()
    node.requests.put(('text', '지우개 가져와', 0, 'actual-queue'))
    node.busy = threading.Event()
    node.local_context = threading.local()
    docs = []
    def deliver(doc, generation):
        docs.append(doc)
        node_class._deliver(node, doc, generation)
        node.stop_event.set()
    node._deliver = deliver
    node_class._work(node)
    prepared = docs[0]['_voice']['prepared_request']
    assert prepared['request_id'] == 'actual-queue'
    assert prepared['accept_text'] == docs[0]['_voice']['final_text']
    # Use the actual serialization method, not the fixture's publishing stub.
    sent = []
    node.publisher = SimpleNamespace(publish=lambda msg: sent.append(json.loads(msg.data)))
    node_class._publish.__globals__['String'] = SimpleNamespace
    node_class._publish(node, node.published[0])
    assert len(sent) == 1 and '_voice' not in sent[0]
    assert 'request_id' not in sent[0] and 'accept_text' not in sent[0]
    assert len(node.texts) == 1  # Existing P1 confirmation remains.


@pytest.mark.parametrize('case', ['stale_generation', 'halted', 'evaluation', 'record_error', 'goal'])
def test_work_never_prepares_unsafe_or_ineligible_public_candidate(node, node_class, case):
    node.requests = queue.Queue()
    node.busy = threading.Event()
    node.local_context = threading.local()
    if case == 'halted': node.observe('halted')
    if case == 'evaluation': node.cfg['evaluation_mode'] = True
    if case == 'stale_generation': node.generation = 1
    value = '지우개 가져와'
    kind = 'record_error' if case == 'record_error' else 'text'
    if case == 'goal':
        node.cfg['p2_goal_evaluation_enabled'] = True
        value = '지우개를 아래 서랍에 넣어줘'
    node.requests.put((kind, value, 0, 'queue-id'))
    docs = []
    def deliver(doc, generation):
        docs.append(doc)
        node.stop_event.set()
    node._deliver = deliver
    if case == 'stale_generation':
        original_done = node.requests.task_done
        node.requests.task_done = lambda: (original_done(), node.stop_event.set())
    node_class._work(node)
    assert not docs or 'prepared_request' not in docs[0].get('_voice', {})
    assert not node.published and not node.texts


@pytest.fixture
def wire_node(node,node_class):
    # C 연결이 있다고 가정하는 기존 모의입니다. 실제 checker 경계는 별도 검사합니다.
    node.cfg['request_run_enabled']=True
    node.request_run=RequestRun()
    node._request_run_connected=lambda:True
    node.wire_status=lambda status:node_class._runner_status(node,SimpleNamespace(data=json.dumps(status)))
    node.wire_status(dict(phase='idle',halt_code=None,last=None,last_intent=None))
    return node


def wire_request(node,request_id='queue1'):
    return node.session.text('지우개 찾아줘',node.generation,request_id=request_id)


def wire_result(request='queue1',run='run1',outcome='COMPLETED',phase='idle'):
    return dict(phase=phase,task_id='find_item' if phase=='running' else None,halt_code=None,
        last_intent=dict(intent='find_item',targets=['eraser'],request_id=request,run_id=run,decision='run'),
        last=dict(task_id='find_item',run_id=run,overall_status=outcome,error_code=None))


def test_wire_publication_has_trusted_fields_without_preacceptance_speech(wire_node):
    doc=wire_request(wire_node)
    wire_node.deliver(doc)
    assert len(wire_node.published)==1 and not wire_node.texts
    payload=wire_node.published[0]
    assert payload['request_id']=='queue1'
    assert payload['accept_text']==doc['_voice']['final_text']
    assert '_voice' not in payload and wire_node.request_run.pending==payload


def test_wire_fast_completed_status_is_once_and_same_run_only(wire_node):
    wire_node.deliver(wire_request(wire_node))
    wire_node.wire_status(wire_result())
    assert wire_node.pending_notice.kind=='completed'
    assert [d['event'] for d in wire_node.diagnostics if d['event'].startswith('request_')][-2:]==[
        'request_accepted','request_completed']
    wire_node.pending_notice=None
    wire_node.wire_status(wire_result())
    assert wire_node.pending_notice is None


def test_wire_different_run_never_queues_completion(wire_node):
    wire_node.deliver(wire_request(wire_node))
    doc=wire_result();doc['last']['run_id']='old'
    wire_node.wire_status(doc)
    assert wire_node.request_run.run_id=='run1' and wire_node.pending_notice is None


def test_wire_publish_failure_discards_local_connection(wire_node):
    wire_node._publish=lambda _:(_ for _ in ()).throw(RuntimeError('publish failed'))
    wire_node.deliver(wire_request(wire_node))
    assert wire_node.request_run.pending is None
    wire_node.wire_status(wire_result())
    assert wire_node.pending_notice is None and not wire_node.texts






def test_wire_evaluation_never_registers_or_publishes(wire_node):
    wire_node.cfg['evaluation_mode']=True
    wire_node.deliver(wire_request(wire_node))
    assert not wire_node.published and wire_node.request_run.pending is None


def test_wire_stop_clears_pending_and_completion(wire_node,node_class):
    wire_node.deliver(wire_request(wire_node))
    node_class._text(wire_node,SimpleNamespace(data='멈춰'))
    wire_node.wire_status(wire_result())
    assert wire_node.request_run.pending is None and wire_node.pending_notice is None
    assert [d['intent'] for d in wire_node.published]==['find_item','cancel']


def test_actual_subscription_uses_required_message_info_wrapper(node_class):
    import inspect
    signature=inspect.signature(node_class._runner_status_with_info)
    with pytest.raises(TypeError):signature.bind(object(),object())
    signature.bind(object(),object(),object())
    source=Path(__file__).resolve().parents[1]/'ready2go_voice/nodes/voice_node.py'
    tree=ast.parse(source.read_text())
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
           and n.func.attr=='create_subscription']
    status_call=next(c for c in calls if any(isinstance(a,ast.Constant) and a.value=='/runner/status' for a in c.args))
    assert status_call.args[2].attr=='_runner_status_with_info'


@pytest.mark.parametrize('playback',['confirmed','noop','mock','failed','canceled'])
def test_wire_speak_success_requires_pcm_completion(wire_node,node_class,playback):
    # PCM-shaped mock proves control flow only, never real sound or C first motion.
    namespace=node_class._speak.__globals__
    namespace['Skill']=SimpleNamespace(Result=lambda:SimpleNamespace(success=False,error_code='',output_json=''))
    outcomes=[]
    goal=SimpleNamespace(request=SimpleNamespace(params_json=json.dumps({'text':'지우개를 가져올게요.'})),
        is_cancel_requested=False,succeed=lambda:outcomes.append('success'),abort=lambda:outcomes.append('abort'),
        canceled=lambda:outcomes.append('canceled'))
    wire_node.goal_lock=threading.Lock();wire_node.goal_lock.acquire()
    def speak(text,**kwargs):
        if playback=='failed':raise RuntimeError('device failed')
        if playback=='canceled':
            goal.is_cancel_requested=True
            raise InterruptedError('canceled')
        if playback=='noop':return None
        kwargs['on_timing'](dict(playback_ended_monotonic=2.,playback_end_basis='portaudio_finished_callback'))
        return dict(tts_started_monotonic=1.,tts_start_basis='portaudio_first_dac',tts_mock=playback=='mock')
    wire_node.tts=SimpleNamespace(speak=speak)
    result=node_class._speak(wire_node,goal)
    assert result.success is (playback=='confirmed')
    assert outcomes==(['success'] if playback=='confirmed' else ['canceled'] if playback=='canceled' else ['abort'])
    assert not wire_node.goal_lock.locked()


@pytest.mark.parametrize('change',['disconnected','stop','cancel'])
def test_inflight_wire_speak_cannot_succeed_after_transport_or_stop_change(wire_node,node_class,change):
    node_class._speak.__globals__['Skill']=SimpleNamespace(Result=lambda:SimpleNamespace(success=False,error_code='',output_json=''))
    outcomes=[]
    goal=SimpleNamespace(request=SimpleNamespace(params_json=json.dumps({'text':'확인 안내'})),
        is_cancel_requested=False,succeed=lambda:outcomes.append('success'),abort=lambda:outcomes.append('abort'))
    wire_node.goal_lock=threading.Lock();wire_node.goal_lock.acquire()
    def speak(text,**kwargs):
        if change=='disconnected':wire_node._request_run_connected=lambda:False
        elif change=='cancel':node_class._text(wire_node,SimpleNamespace(data='멈춰'))
        else:wire_node.stop_event.set()
        kwargs['on_timing'](dict(playback_ended_monotonic=2.,playback_end_basis='portaudio_finished_callback'))
        return dict(tts_started_monotonic=1.,tts_start_basis='portaudio_first_dac',tts_mock=False)
    wire_node.tts=SimpleNamespace(speak=speak)
    result=node_class._speak(wire_node,goal)
    assert not result.success and result.error_code=='CANCELED' and outcomes==['abort']




def test_wire_pending_request_survives_second_request_and_releases_after_completion(wire_node):
    wire_node.deliver(wire_request(wire_node))
    second=wire_node.session.text('망치 좀',wire_node.generation,request_id='second')
    wire_node.deliver(second)
    assert len(wire_node.published)==1
    assert wire_node.request_run.pending['request_id']=='queue1'
    wire_node.wire_status(wire_result())
    assert wire_node.pending_notice.kind=='completed'
    third=wire_node.session.text('망치 좀',wire_node.generation,request_id='third')
    wire_node.deliver(third)
    assert [doc['request_id'] for doc in wire_node.published]==['queue1','third']
    assert wire_node.request_run.pending['request_id']=='third'


def test_unsupported_c_dependency_holds_opt_in_but_keeps_halt_warning(wire_node,node_class):
    wire_node._request_run_connected=lambda:node_class._request_run_connected(wire_node)
    wire_node._runner_status=lambda msg:node_class._runner_status(wire_node,msg)
    wire_node.deliver(wire_request(wire_node))
    assert not wire_node.published and not wire_node.texts and wire_node.request_run.pending is None
    info=dict(source_timestamp=1,received_timestamp=2,publication_sequence_number=None,reception_sequence_number=None)
    node_class._runner_status_with_info(wire_node,SimpleNamespace(data=json.dumps(wire_result())),info)
    assert wire_node.request_run.run_id is None and wire_node.pending_notice is None
    halted=dict(phase='halted',halt_code='ESTOP',task_id='find_item',last=None,last_intent=None)
    node_class._runner_status_with_info(wire_node,SimpleNamespace(data=json.dumps(halted)),info)
    assert wire_node.normal_notice_cancel.is_set() and wire_node.pending_notice.kind=='estop'
    node_class._goal.__globals__['GoalResponse']=SimpleNamespace(REJECT='reject',ACCEPT='accept')
    assert node_class._goal(wire_node,SimpleNamespace(params_json=json.dumps({'text':'수락 안내'})))=='reject'


@pytest.fixture
def selected_node(node):
    node.cfg.update(p2_goal_enabled=True,request_run_enabled=True)
    current={'ready':True}
    node.bind_request_source(lambda:current['ready'])
    node.observe('idle')
    node.parser.llm=lambda *_:dict(intent='achieve_goal',targets=[],confidence=.99,
        goals=copy.deepcopy(node.cfg['p2_goal_catalog'][1]),response_text=None)
    node.source_state=current
    return node


def selected_request(node):
    return node.session.text('위 서랍 열어 둬',node.generation,request_id='goal-request')


def selected_decision(node,*,complete=False):
    return dict(phase='idle' if complete else 'running',task_id='achieve_goal',halt_code=None,
        last_intent=dict(intent='achieve_goal',targets=[],request_id='goal-request',
                         decision='run',run_id='goal-run'),
        last=dict(task_id='achieve_goal',run_id='goal-run',overall_status='COMPLETED',error_code=None) if complete else None)


def test_selected_goal_payload_and_current_source_loss_cannot_rebind(selected_node):
    h=selected_node;doc=selected_request(h);h.deliver(doc)
    assert len(h.published)==1 and not h.texts
    payload=h.published[0]
    assert payload['goals']==h.cfg['p2_goal_catalog'][1]
    assert payload['request_id']=='goal-request' and payload['accept_text']==doc['_voice']['final_text']
    decision=selected_decision(h)
    h.source_state['ready']=False
    h._runner_status(SimpleNamespace(data=json.dumps(decision)))
    assert h.request_run.pending is None and h.request_run.run_id is None
    h.source_state['ready']=True
    h._runner_status(SimpleNamespace(data=json.dumps(decision)))
    assert h.request_run.run_id is None


@pytest.mark.parametrize('gate',['optin','evaluation','source'])
def test_selected_goal_publication_respects_each_gate(selected_node,gate):
    h=selected_node
    if gate=='optin':h.cfg['request_run_enabled']=False
    if gate=='evaluation':h.cfg['evaluation_mode']=True
    if gate=='source':h.source_state['ready']=False
    h.deliver(selected_request(h))
    assert not h.published and h.request_run.pending is None and not h.texts


def test_selected_goal_acceptance_speak_is_current_run_once_and_mock_is_not_success(selected_node,node_class):
    h=selected_node;h.deliver(selected_request(h))
    h._runner_status(SimpleNamespace(data=json.dumps(selected_decision(h))))
    assert h.request_run.run_id=='goal-run'
    text=h.request_run.pending['accept_text']
    assert h._goal(SimpleNamespace(params_json=json.dumps({'text':text+'이전 요청'})))==0
    request=SimpleNamespace(params_json=json.dumps({'text':text}))
    assert h._goal(request)==1
    calls=[]
    goal=SimpleNamespace(request=request,is_cancel_requested=False,abort=lambda:calls.append('abort'),
                         succeed=lambda:calls.append('success'),canceled=lambda:calls.append('cancel'))
    result=h._speak(goal)
    assert result.success is False and calls==['abort']  # no-op/mock 재생은 실제 성공 증거가 아닙니다.
    assert h._goal(request)==0 and h.texts==[text]


def test_selected_goal_fast_final_prevents_late_acceptance_speech(selected_node):
    h=selected_node;h.deliver(selected_request(h))
    h._runner_status(SimpleNamespace(data=json.dumps(selected_decision(h,complete=True))))
    assert h.request_run.finished
    request=SimpleNamespace(params_json=json.dumps({'text':h.request_run.pending['accept_text']}))
    assert h._goal(request)==0 and not h.texts
