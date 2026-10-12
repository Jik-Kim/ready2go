"""승인 핫픽스 대표 묶음. 실제 STT/정지/복구/재개/물리 결과가 아닙니다."""
import copy
from types import SimpleNamespace
import pytest
from ready2go_voice.adapters.audio import Recording
from test_voice_ux_node import node_class, node, ask


@pytest.mark.parametrize('text',['어, 맞아.','맞아, 그거 갖다줘.','맞아, 그걸로 갖다줘.','그걸로'])
def test_representative_current_question_reply_preserves_until_classified(node,text):
    ask(node);q=node.session.conversation.pending
    def llm(*a):
        assert node.session.conversation.pending is q
        return {'intent':'find_item','targets':['toy_hammer'],'confidence':.99}
    node.parser.llm=llm
    doc=node.session.text(text)
    assert doc['intent']=='find_item' and doc['targets']==['toy_hammer']
    assert doc['source']['stt_text']==text and node.session.conversation.pending is None


@pytest.mark.parametrize('state',['absent','expired','negative','other_target'])
def test_current_question_boundary_no_wrong_target(node,state):
    if state!='absent':ask(node)
    if state=='expired':node.now[0]=node.session.conversation.pending.expires
    text='맞아, 그걸로 갖다줘.' if state in ('absent','expired') else '맞아, 가져다주지 마' if state=='negative' else '렌치 가져다줘'
    doc=node.session.text(text)
    if state=='other_target':assert doc['targets']==['toy_wrench'] and not doc['_voice'].get('context_answer')
    else:assert not doc['source']['execution_allowed'] and doc['targets']==[]


def test_availability_never_executes_then_explicit_confirmation_can_request(node):
    doc=node.session.text('망치 가져올 수 있어?');node.deliver(doc)
    assert doc['intent']=='clarify' and not doc['source']['execution_allowed']
    assert '재고와 파지는 확인하지 못' in node.texts[-1]
    assert node.session.conversation.pending.target=='toy_hammer'
    assert node.session.text('응')['intent']=='find_item'
    lip=node.session.text('립밤 가져올 수 있어?')
    assert lip['intent']=='clarify' and not lip['source']['execution_allowed']


@pytest.mark.parametrize('text',['망치 어디있어?','위 서랍 열려있어?',
    '지금 망치 어딨어?','지금 망치 어딨어.','위쪽 서랍 열려있어?','위쪽 서랍 열려있어.'])
def test_readonly_initial_state_query_before_llm(node,text):
    initial=copy.deepcopy(node.parser.reference_state)
    node.parser.llm=lambda *a:pytest.fail('읽기 전용 질의는 실행 분류 전에 처리합니다.')
    doc=node.session.text(text)
    assert '초기 배치 기준' in doc['_voice']['final_text']
    assert not doc['source']['execution_allowed'] and node.parser.reference_state==initial


@pytest.mark.parametrize('text',['복구해','이어서 해','종료해'])
def test_no_work_control_does_not_leak_into_llm(node,text):
    node.parser.llm=lambda *a:pytest.fail('안전 제어는 일반 LLM으로 보내지 않습니다.')
    doc=node.session.text(text)
    assert doc['_voice'].get('safety_control') and not doc['source']['llm_called']
    assert not doc['source']['execution_allowed']


@pytest.mark.parametrize('text',['멈춰','정지','그만','정지해'])
def test_independent_stop_four_exact_phrases(node,text):
    class STT:
        def transcribe(self,*a):return text
    node.session.stt=STT();now=node.now[0]
    record=Recording(b'\0\0'*1600,now,100.,recording_started_monotonic=now-.2,recording_ended_monotonic=now)
    assert node.session.stop_audio(record)['intent']=='cancel'
    assert node.session.stop_audio(record,spoken_texts={text}) is None


def test_dummy_cancel_preserves_current_run_in_existing_typed_fixture():
    import json
    from test_flow import dummy_class
    from ready2go_voice.core.recovery_confirmation import TaskEndCandidate
    cls=dummy_class();bridge=cls.__new__(cls);observed=[]
    bridge.run='current-run';bridge.accepted_payload={'request_id':'request'}
    bridge.first_action=('current-run',0);bridge.work=None;bridge.revision=0;bridge.evidence=None
    bridge.voice=SimpleNamespace(safety_stopped=lambda *a,**kw:observed.append(a) or True,
        _runner_status=lambda message:observed.append(json.loads(message.data)))
    bridge.String=lambda **kw:SimpleNamespace(**kw);bridge.log=lambda *a,**kw:None
    bridge.intent(SimpleNamespace(data=json.dumps({'intent':'cancel'})))
    assert bridge.run=='current-run' and bridge.work.task=='current-run'
    assert bridge.evidence.stopped and not bridge.evidence.recovered
    assert observed[-1]['phase']=='halted'
    bridge.safety_event('recover',bridge.work)
    assert bridge.evidence.verified()  # 명시 모의 증빙뿐이며 실제 복구 증거가 아닙니다.
    bridge.safety_event('candidate',TaskEndCandidate(bridge.work))
    assert bridge.work is None and bridge.run is None
