"""실제 VoiceNode 메서드의 ROS 비의존 모의. ROS topic/action 시험과 구분합니다."""
import ast
import copy
import json
import queue
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import uuid
import pytest
from ready2go_voice.core.intent import intent, IntentParser
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.core.response import final_response
from ready2go_voice.core.diagnostics import redact
from ready2go_voice.core.runner_notice import RunnerNoticePolicy
from ready2go_voice.core.tts_prefill import remember_text


@pytest.fixture
def node_class():
    # ROS import/초기화를 모방하지 않고 저장된 실제 메서드 본문만 실행합니다.
    source=Path(__file__).resolve().parents[1]/'ready2go_voice/nodes/voice_node.py'
    tree=ast.parse(source.read_text())
    tree.body=[n for n in tree.body if isinstance(n,ast.ClassDef) or isinstance(n,ast.FunctionDef) and n.name=='runner_blocks']
    namespace=dict(Node=object,json=json,queue=queue,threading=threading,time=time,uuid=uuid,
                   intent=intent,final_response=final_response,redact=redact,remember_text=remember_text)
    exec(compile(tree,str(source),'exec'),namespace)
    return namespace['VoiceNode']


@pytest.fixture
def node(node_class,ontology,schema,cfg):
    cfg.update(evaluation_mode=False,tts_engine='espeak')
    now=[time.monotonic()]
    parser=IntentParser(ontology,schema,cfg)
    h=SimpleNamespace(cfg=cfg,parser=parser,session=VoiceSession(parser,cfg,clock=lambda:now[0]),
        generation=0,stop_event=threading.Event(),request_cancel=threading.Event(),speaking=threading.Event(),
        submit_lock=threading.Lock(),notice_condition=threading.Condition(),notice_policy=RunnerNoticePolicy(),
        normal_notice_cancel=threading.Event(),notice_cancel=threading.Event(),pending_notice=None,warning_epoch=0,
        diagnostics=[],published=[],texts=[],now=now)
    h._diagnostic=lambda d:h.diagnostics.append(copy.deepcopy(d))
    h._publish=lambda d:h.published.append(copy.deepcopy(d))
    def speak(text,**kw):
        h.texts.append(text)
        kw['on_start']({'tts_started_monotonic':now[0],'tts_started_unix':123,'tts_mock':True})
    h.tts=SimpleNamespace(speak=speak)
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


def test_initial_question_then_different_affirmations_only_one_find(node):
    doc=ask(node)
    assert node.published[0]['intent']=='clarify'
    assert any(d['event']=='question_ready' and d['question_id']==doc['_voice']['question_id'] for d in node.diagnostics)
    node.deliver(node.session.text('응',0))
    node.deliver(node.session.text('맞아',0))
    assert sum(d['intent']=='find_item' for d in node.published)==1
    assert len(node.texts)==3
    final=[d['text'] for d in node.diagnostics if d['event']=='final_response']
    assert final==node.texts


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
