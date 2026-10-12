"""승인 P1 UX 핵심 의미/문맥/진단/캐시 모의. 장치·API·합성 실측 아님."""
import json
from pathlib import Path
import threading
import queue
from copy import deepcopy
import pytest
from jsonschema import Draft7Validator
from ready2go_voice.adapters.api import LangChainIntent
from ready2go_voice.core.intent import IntentParser
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.core.tts_prefill import prefill_texts, remember_text
from ready2go_voice.core.diagnostics import DiagnosticFile, redact


def test_acceptance_keeps_validated_sentence_and_queue_identity(ontology, schema, cfg):
    sentence = '망치를 가져다달라는 요청을 확인했어요.'
    parser = IntentParser(ontology, schema, cfg, lambda *_: candidate(response=sentence))
    session = VoiceSession(parser, cfg)
    doc = session.text('망치 좀', generation=7, request_id='local-queued-request')
    assert doc['_voice']['request_id'] == 'local-queued-request'
    assert session.consume_acceptance_text(deepcopy(doc), 7) is None
    assert session.consume_acceptance_text(doc, 7) == sentence
    assert session.consume_acceptance_text(doc, 7) is None
    assert 'request_id' not in doc['source']  # 새 wire를 만들지 않습니다.


@pytest.mark.parametrize('change', ['target', 'intent', 'sentence', 'request', 'source', 'generation', 'epoch'])
def test_acceptance_changed_or_canceled_request_is_not_reusable(ontology, schema, cfg, change):
    session = VoiceSession(IntentParser(ontology, schema, cfg), cfg)
    doc = session.text('망치 좀', generation=2)
    generation = 2
    if change == 'target': doc['targets'] = ['toy_wrench']
    elif change == 'intent': doc['intent'] = 'cancel'
    elif change == 'sentence': doc['_voice']['final_text'] = '망치 실행을 완료했어요.'
    elif change == 'request': doc['_voice']['request_id'] = 'another'
    elif change == 'source': doc['source']['execution_allowed'] = False
    elif change == 'generation': generation = 3
    else: session.conversation.invalidate()
    assert session.consume_acceptance_text(doc, generation) is None
    assert session.consume_acceptance_text(doc, 2) is None


def test_acceptance_new_request_and_restart_cannot_restore_old_text(ontology, schema, cfg):
    parser = IntentParser(ontology, schema, cfg)
    session = VoiceSession(parser, cfg)
    old = session.text('망치 좀', request_id='old')
    current = session.text('렌치 좀', request_id='new')
    assert session.consume_acceptance_text(old, 0) is None
    assert VoiceSession(parser, cfg).consume_acceptance_text(current, 0) is None
    assert session.consume_acceptance_text(current, 0) == current['_voice']['final_text']


@pytest.mark.parametrize('response', ['사과 가져오기 요청으로 이해했어요.', '망치 실행을 완료했어요.'])
def test_acceptance_uses_replacement_not_unsafe_llm_sentence(ontology, schema, cfg, response):
    session = VoiceSession(IntentParser(ontology, schema, cfg, lambda *_: candidate(response=response)), cfg)
    doc = session.text('망치 좀')
    assert doc['_voice']['response_replacement_reason']
    assert session.consume_acceptance_text(doc, 0) == doc['_voice']['final_text'] != response


@pytest.mark.parametrize('text,blocked', [('립밤 되나?', False), ('사과 좀', False), ('망치 좀', True), ('응', False)])
def test_acceptance_nonexecution_has_no_sentence_to_consume(ontology, schema, cfg, text, blocked):
    session = VoiceSession(IntentParser(ontology, schema, cfg), cfg)
    doc = session.text(text, blocked=blocked)
    assert session.consume_acceptance_text(doc, 0) is None


def candidate(target='toy_hammer', kind='find_item', response=None, reason=None):
    return {'intent': kind, 'targets': [target] if kind == 'find_item' else [],
            'confidence': .99, 'clarify_question': None, 'response_text': response,
            'rejection_reason': reason}


@pytest.mark.parametrize('text', ['망치 가져오라고 말했잖아', '엄마가 망치 가져오라고 했어'])
def test_reported_delivery_request(ontology, schema, cfg, text):
    doc = IntentParser(ontology, schema, cfg, lambda *_: candidate()).parse(text)
    assert doc['intent'] == 'find_item' and doc['targets'] == ['toy_hammer']
    assert doc['source']['llm_validation'] == 'passed'
    assert '이해했어요' in doc['_voice']['final_text']


@pytest.mark.parametrize('text', ["'망치 가져와'라는 문장을 번역해줘", '망치 가져다주면 안 돼',
                                   '망치 빼고 다른 것 가져줘', '망치 안 가져와도 돼'])
def test_bad_candidate_cannot_override_nonrequest(ontology, schema, cfg, text):
    p = IntentParser(ontology, schema, cfg, lambda *_: candidate())
    doc = p.parse(text)
    assert not doc['source']['execution_allowed'] and not doc['targets']
    assert p.validate(candidate(), text)['intent'] != 'find_item'


@pytest.mark.parametrize('text,target', [('망치 좀', 'toy_hammer'), ('렌치 좀', 'toy_wrench'), ('스패너 좀', 'toy_wrench')])
def test_daily_aliases_same_registered_keys(ontology, schema, cfg, text, target):
    doc = IntentParser(ontology, schema, cfg).parse(text)
    assert doc['targets'] == [target]


@pytest.mark.parametrize('kind,text,response,valid', [
    ('find_item', '망치 좀', '망치를 가져오는 요청으로 이해했어요.', True),
    ('find_item', '망치 좀', '망치를 가져다달라는 요청을 확인했어요.', True),
    ('find_item', '망치 좀', '망치를 가져다드리겠습니다.', False),
    ('find_item', '망치 좀', '망치 실행을 완료했어요.', False),
    ('find_item', '망치 좀', '사과 가져오기 요청으로 이해했어요.', False),
    ('clarify', '망치 좀', '망치를 가져다드릴까요?', True),
    ('clarify', '망치 좀', '망치 가져오기 요청이 맞나요?', True),
    ('clarify', '망치 좀', '망치와 사과 가져오기 요청이 맞나요?', False),
    ('clarify', '망치 좀', '망치 가져오기 요청이 아니죠?', False),
    ('clarify', '망치 좀', '립밤을 가져다드릴까요?', False),
])
def test_response_matches_target_action_and_decision(ontology, schema, cfg, kind, text, response, valid):
    doc = IntentParser(ontology, schema, cfg, lambda *_: candidate(kind=kind, response=response)).parse(text)
    meta = doc['_voice']
    assert (meta['final_text'] == response) is valid
    assert (meta['response_replacement_reason'] is None) is valid
    if kind == 'clarify':
        assert doc['clarify_question'] == meta['final_text']
    else:
        assert 'clarify_question' not in doc


def test_unsupported_availability_and_raw_reasons(ontology, schema, cfg):
    p = IntentParser(ontology, schema, cfg, lambda *_: candidate('apple'))
    doc = p.parse('사과 가져와')
    assert doc['intent'] == 'unknown' and doc['targets'] == []
    assert doc['_voice']['final_text'] == '그 물품은 지원하지 않습니다.'
    assert doc['_voice']['validation_reason'] == 'unregistered_item'
    assert doc['source']['llm_raw']['targets'] == ['apple']
    p.llm = lambda *_: candidate(kind='unknown')
    assert p.parse('달을 점령해줘')['_voice']['final_text'] == '그 요청은 지원하지 않습니다.'
    doc = p.parse('립밤 되나?')
    assert doc['_voice']['availability'] and not doc['source']['llm_called']
    assert not doc['source']['execution_allowed'] and not doc['targets']
    assert '등록 지원 대상' in doc['_voice']['final_text'] and '실제 재고와 파지는 확인하지 못' in doc['_voice']['final_text']


@pytest.mark.parametrize('text,reason,expected', [
    ('사과 가져와', 'unregistered_item', '그 물품은 지원하지 않습니다.'),
    ('귤 가져다줘', 'unregistered_item', '그 물품은 지원하지 않습니다.'),
    ('수건 좀', 'unregistered_item', '그 물품은 지원하지 않습니다.'),
    ('박수 쳐줘', 'unsupported_request', '그 요청은 지원하지 않습니다.'),
    ('달을 점령해줘', 'unsupported_request', '그 요청은 지원하지 않습니다.'),
])
@pytest.mark.parametrize('response', [None, '그 물품은 지원하지 않습니다.', '그 요청은 지원하지 않습니다.'])
def test_schema_valid_unknown_reason_selects_final_notice_not_candidate_phrase(
        ontology, schema, cfg, text, reason, expected, response):
    raw = candidate(kind='unknown', response=response, reason=reason)
    Draft7Validator(LangChainIntent(cfg, ontology['world']['items']).schema).validate(raw)
    p = IntentParser(ontology, schema, cfg, lambda *_: json.dumps(raw))
    assert not p.mentioned(text)
    doc = p.parse(text)
    assert doc['intent'] == 'unknown' and doc['targets'] == []
    assert doc['source']['llm_validation'] == 'passed' and not doc['source']['fallback_used']
    assert doc['_voice']['reason'] == reason and doc['_voice']['final_text'] == expected
    assert not doc['source']['execution_allowed']
    assert doc['source']['llm_raw'] == json.dumps(raw)  # existing raw diagnostic field retained
    assert 'response_text' not in doc and 'rejection_reason' not in doc
    assert 'rejection_reason' not in doc['source']


@pytest.mark.parametrize('reason', ['arbitrary', 1, [], {}])
def test_invalid_internal_reason_uses_safe_unknown_fallback(ontology, schema, cfg, reason):
    raw = candidate(kind='unknown', reason=reason)
    doc = IntentParser(ontology, schema, cfg, lambda *_: raw).parse('사과 가져와')
    assert doc['intent'] == 'unknown' and doc['targets'] == []
    assert doc['_voice']['final_text'] == '그 요청은 지원하지 않습니다.'
    assert doc['_voice']['validation_reason'] == 'invalid_rejection_reason'
    assert not doc['source']['execution_allowed']


@pytest.mark.parametrize('raw,text', [
    (candidate(reason='unregistered_item'), '망치 좀'),
    (candidate(kind='clarify', reason='unsupported_request'), '망치 좀'),
    (candidate(kind='unknown', reason='unregistered_item'), '지우개 가져와'),
])
def test_reason_must_match_hold_kind_and_registered_target(ontology, schema, cfg, raw, text):
    p = IntentParser(ontology, schema, cfg)
    with pytest.raises(ValueError):
        p.validate(raw, text)


@pytest.fixture
def dialogue(ontology, schema, cfg):
    cfg['evaluation_mode'] = False
    now = [100.0]
    p = IntentParser(ontology, schema, cfg)
    session = VoiceSession(p, cfg, clock=lambda: now[0])
    qdoc = session.text('망치', 4)
    assert session.conversation.pending is None
    session.conversation.delivered(qdoc, 4, True)
    return session, now, qdoc


@pytest.mark.parametrize('reply,target', [('응','toy_hammer'),('맞아','toy_hammer'),('그걸로','toy_hammer'),
                                        ('렌치','toy_wrench'),('아니 렌치야','toy_wrench')])
def test_current_answer_consumed_once_preserves_original(dialogue, reply, target):
    s, now, q = dialogue
    doc = s.text(reply, 4)
    assert doc['targets'] == [target] and doc['source']['stt_text'] == reply
    assert doc['_voice']['context_answer'] and s.valid_context(doc, 4)
    assert s.should_publish(doc)
    s.mark_published(doc)
    assert not s.should_publish(doc)
    assert s.text('맞아',4)['intent'] != 'find_item'


@pytest.mark.parametrize('invalidate', ['cancel','warning','expired','generation','restart','blocked','new_request'])
def test_past_question_never_executes(dialogue, invalidate):
    s, now, q = dialogue
    if invalidate in ('cancel','warning'):
        s.conversation.invalidate()
    elif invalidate == 'expired': now[0] += s.cfg['dialogue_timeout_sec']
    elif invalidate == 'restart': s = VoiceSession(s.parser, s.cfg, clock=lambda: now[0])
    elif invalidate == 'new_request': s.text('지우개 가져와',4)
    doc = s.text('응',5 if invalidate=='generation' else 4, blocked=invalidate=='blocked')
    assert doc['intent'] == 'clarify' and doc['targets'] == []
    assert doc['_voice']['final_text'] == (s.cfg['voice_flow']['status_prompts']['unconfirmed']
        if (invalidate == 'blocked') else s.cfg['clarify_prompts']['missing_item'])
    assert not doc['_voice'].get('context_answer') and 'question_target' not in doc['_voice']


@pytest.mark.parametrize('reply', ['응', '맞아', '그걸로', '그거줘'])
@pytest.mark.parametrize('state', ['absent', 'expired', 'cancel', 'generation', 'restart',
                                  'warning', 'blocked', 'new_request'])
@pytest.mark.parametrize('llm_mode', ['none', 'failure', 'normal'])
def test_contextless_replies_reask_target_without_restoring_previous_authority(
        dialogue, reply, state, llm_mode):
    s, now, qdoc = dialogue
    previous_id = qdoc['_voice']['question_id']
    if state in ('absent', 'cancel', 'warning'):
        s.conversation.invalidate()
    elif state == 'expired':
        now[0] += s.cfg['dialogue_timeout_sec']
    elif state == 'restart':
        s = VoiceSession(s.parser, s.cfg, clock=lambda: now[0])
    elif state == 'new_request':
        s.text('지우개 가져와', 4)
    calls = []
    def llm(*args):
        calls.append(args)
        if llm_mode == 'failure':
            raise TimeoutError('mock only')
        return candidate()
    s.parser.llm = None if llm_mode == 'none' else llm
    generation = 5 if state == 'generation' else 4
    doc = s.text(reply, generation, blocked=state == 'blocked')
    assert doc['intent'] == 'clarify' and doc['targets'] == []
    assert doc['source']['stt_text'] == reply and not doc['source']['execution_allowed']
    assert doc['_voice']['final_text'] == (s.cfg['voice_flow']['status_prompts']['unconfirmed']
        if state == 'blocked' else s.cfg['clarify_prompts']['missing_item'])
    assert not calls and not doc['_voice'].get('context_answer')
    assert 'question_target' not in doc['_voice'] and 'question_id' not in doc['_voice']
    assert s.conversation.pending is None
    new_question = s.conversation.delivered(doc, generation, True, blocked=state == 'blocked')
    if state == 'blocked':
        assert new_question is None
    else:
        assert new_question.id != previous_id and new_question.target is None
        assert s.text('응', generation)['targets'] == []


@pytest.mark.parametrize('reply,target', [('응','toy_hammer'), ('맞아','toy_hammer'),
                                        ('그걸로','toy_hammer'), ('렌치','toy_wrench'),
                                        ('아니 렌치야','toy_wrench')])
@pytest.mark.parametrize('llm_mode', ['none', 'failure', 'normal'])
def test_live_question_answer_and_correction_remain_single_use(dialogue, reply, target, llm_mode):
    s, _, qdoc = dialogue
    def llm(*_):
        if llm_mode == 'failure':
            raise TimeoutError('mock only')
        return candidate(target)
    s.parser.llm = None if llm_mode == 'none' else llm
    doc = s.text(reply, 4)
    assert doc['intent'] == 'find_item' and doc['targets'] == [target]
    assert doc['_voice']['question_id'] == qdoc['_voice']['question_id']
    assert doc['_voice']['context_answer'] and s.valid_context(doc, 4)
    s.mark_published(doc)
    assert not s.should_publish(doc)
    again = s.text('그걸로', 4)
    assert again['intent'] == 'clarify' and again['targets'] == []


def test_question_tts_failure_and_invalidation_after_candidate(dialogue):
    s, now, q = dialogue
    doc = s.text('응',4)
    s.conversation.invalidate()
    assert not s.valid_context(doc,4)
    s.conversation.delivered(q,4,False)
    assert not s.conversation.pending
    assert s.text('응',4)['intent'] != 'find_item'


def test_initial_question_document_is_not_answer_authority(dialogue):
    s, now, q = dialogue
    assert q['_voice']['question_id']
    assert not q['_voice'].get('context_answer')
    assert s.valid_context(q,4) and s.should_publish(q)
    s.mark_published(q)
    answer = s.text('응',4)
    assert s.should_publish(answer)


def test_prefill_frequent_restart_bounds_and_no_authority(cfg,ontology,tmp_path):
    cfg['tts_melotts_assets']=str(tmp_path)
    cfg['tts_frequent_max_texts']=2
    warnings=[]
    text='망치를 가져다드릴까요?'
    initial=prefill_texts(cfg,ontology['world']['items'].values(),warnings.append)
    assert '장난감 망치 가져오기 요청이 맞나요?' in initial
    remember_text(cfg,text,warnings.append)
    assert text not in prefill_texts(cfg,ontology['world']['items'].values())
    remember_text(cfg,text,warnings.append)
    assert text in prefill_texts(dict(cfg),ontology['world']['items'].values())
    for other in ['하나','둘','셋']:remember_text(cfg,other,warnings.append)
    assert len(json.loads((tmp_path/'validated_phrases.json').read_text()))<=2
    cfg['tts_prefill_max_texts']=1
    with pytest.raises(ValueError,match='PREFILL_REQUIRED_LIMIT'):prefill_texts(cfg,ontology['world']['items'].values())
    assert not warnings


def test_frequent_record_failure_warns_and_keeps_existing_asset(cfg,tmp_path):
    asset=tmp_path/'asset';asset.write_text('preserve')
    cfg['tts_melotts_assets']=str(asset)
    warnings=[];remember_text(cfg,'확인 질문',warnings.append)
    assert warnings and asset.read_text()=='preserve'


def test_diagnostics_redact_rotate_and_fail_without_escape(cfg,tmp_path,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','sk-private-123456789')
    cfg.update(diagnostic_file=str(tmp_path/'detail.jsonl'),diagnostic_max_bytes=200,diagnostic_backups=2)
    warnings=[];writer=DiagnosticFile(cfg,warnings.append)
    writer.emit({'llm_raw':'sk-private-123456789 token=secret123456', 'api_key':'hide', 'request_id':'r1'})
    writer.queue.join()
    raw=Path(cfg['diagnostic_file']).read_text()
    assert 'sk-private' not in raw and 'secret123456' not in raw and 'hide' not in raw
    writer.emit({'request_id':'r2','timing':{'cache_hit':True}});writer.queue.join()
    assert Path(cfg['diagnostic_file']+'.1').exists()
    monkeypatch.setattr(writer,'_append',lambda _: (_ for _ in ()).throw(OSError('disk failure')))
    writer.emit({'event':'tts_finished'});writer.queue.join()
    writer.emit({'bad':object()})
    cycle={};cycle['self']=cycle;writer.emit(cycle)
    assert len(warnings)>=3
    writer.close()


def test_queue_full_and_warning_failure_do_not_escape():
    writer=object.__new__(DiagnosticFile)
    writer.queue=queue.Queue(maxsize=1);writer.stop=threading.Event();warnings=[];writer.warning=warnings.append
    writer.queue.put('occupied');writer.emit({'event':'intent'})
    assert warnings
    writer.warning=lambda _: (_ for _ in ()).throw(RuntimeError())
    writer.emit({'bad':object()})


@pytest.mark.parametrize('raw,reason', [('{bad','invalid_json'),
    ({'intent':'find_item','targets':['toy_hammer'],'confidence':.1},'low_confidence'),
    ({'intent':'find_item','targets':['eraser'],'confidence':.99},'target_mismatch'),
    ({'intent':'find_item','targets':['toy_hammer'],'confidence':float('inf')},'nonfinite_confidence'),
    ({'intent':'find_item','targets':['toy_hammer']},'schema_mismatch')])
def test_safe_validation_reasons_no_exception_messages(ontology,schema,cfg,raw,reason):
    doc=IntentParser(ontology,schema,cfg,lambda *_:raw).parse('망치 좀')
    assert doc['_voice']['validation_reason']==reason
    assert 'sk-' not in doc['source'].get('llm_error','')


def test_recording_sdk_and_final_internal_request_link(cfg,ontology,schema):
    from ready2go_voice.adapters.audio import Recording
    events=[]
    class STT:
        supports_request_boundary=True
        def transcribe(self,path,timeout,*,before_request):
            assert path.exists() and before_request(101.0) is True
            return '지우개 가져와'
    session=VoiceSession(IntentParser(ontology,schema,cfg),cfg,STT(),progress=lambda **event:events.append(event))
    recording=Recording(b'\1\0'*16000,100,200,recording_started_monotonic=99,
                        recording_ended_monotonic=100.4,recording_ended_unix=200.4)
    doc=session.audio(recording,request_id='recording-request-1')
    assert doc['_voice']['request_id']=='recording-request-1'
    assert doc['_voice']['recording_started_monotonic']==99
    assert doc['source']['recording_ended_monotonic']==100.4
    event=next(e for e in events if e['event']=='whisper_sdk_request')
    assert event['request_id']==doc['_voice']['request_id'] and event['requested_monotonic']==101.0
    assert session.consume_acceptance_text(doc, 0) == doc['_voice']['final_text']


@pytest.mark.parametrize('response',[None,'실행을 완료했어요.'])
def test_targetless_invalid_clarify_never_reaches_final_text(cfg,ontology,schema,response):
    raw={'intent':'clarify','targets':[],'confidence':.99,
         'clarify_question':'실행을 완료했어요.','response_text':response}
    doc=IntentParser(ontology,schema,cfg,lambda *_:raw).parse('잘 모르겠어')
    assert doc['_voice']['final_text']==cfg['clarify_prompts']['general']
    assert doc['clarify_question']==cfg['clarify_prompts']['general']
    assert doc['_voice']['response_replacement_reason']=='response_action_or_promise'
    assert doc['source']['llm_raw']==raw


def test_valid_targetless_question_keeps_text_then_accepts_current_target(cfg,ontology,schema):
    text='어떤 물품을 가져다드릴까요?'
    p=IntentParser(ontology,schema,cfg,lambda *_:{'intent':'clarify','targets':[],
        'confidence':.99,'response_text':text})
    s=VoiceSession(p,cfg)
    doc=s.text('요청이 있어',0)
    assert doc['_voice']['final_text']==text
    s.conversation.delivered(doc,0,True)
    p.llm=None
    assert s.text('망치',0)['targets']==['toy_hammer']


def test_silence_pcm_pause_and_fixed_vad_comparison(cfg):
    """합성 PCM/모의VAD만: 정상 실제 음성을 판정하거나 임계값을 확정하지 않습니다."""
    import numpy as np
    from ready2go_voice.adapters.audio import Recorder, Recording
    from ready2go_voice.adapters.speech import SpeechPresence
    stop=threading.Event()
    def run(amplitudes):
        index=[0]
        data=[(np.ones(cfg['frame_samples'],dtype=np.int16)*amp).tobytes() for amp in amplitudes]
        class Stream:
            def read(self,n):
                index[0]+=1
                return data.pop(0) if data else b'\0\0'*n, False
        recorder=Recorder(cfg,clock=lambda:index[0]*.08,wall=lambda:100+index[0]*.08)
        return recorder.record(Stream(),stop),data
    short,_=run([1000]*3+[0]*10)
    assert short.ended_monotonic < short.recording_ended_monotonic
    resumed,_=run([1000]*3+[0]*2+[1000]*3+[0]*10)
    assert len(resumed.pcm)>len(short.pcm)
    cut,remaining=run([1000]*3+[0]*10+[1000]*3)
    assert remaining and cut.ended_monotonic==short.ended_monotonic
    with pytest.raises(TimeoutError,match='NO_SPEECH'):run([int(cfg['speech_rms'])-1]*60)
    with pytest.raises(TimeoutError,match='RECORD_LIMIT'):run([1000]*150)
    class VAD:
        def reset_states(self):pass
        def predict(self,*args,**kwargs):return 0
    assert not SpeechPresence(cfg,VAD()).check(Recording(short.pcm,None,None,recording_mode='fixed'))
    stop.set()
    with pytest.raises(InterruptedError):run([1000])


def test_worker_progress_is_not_synthesis_response(cfg):
    import io
    from types import SimpleNamespace
    from ready2go_voice.adapters.melotts import MeloTTS
    messages=[{'event':'model_prepared','model_prepare_sec':1.5},
              {'event':'prefill_progress','done':2,'total':2,'cache_hit':True,'elapsed_sec':.01},
              {'ready':True,'model_prepare_sec':1.5,'prefill_prepare_sec':.01,'prepare_total_sec':1.7}]
    progress=[]
    state={'process':SimpleNamespace(stdout=io.StringIO(''.join(json.dumps(m)+'\n' for m in messages))),
           'progress':progress.append,'ready':threading.Event(),'responses':queue.Queue(),'error':None}
    MeloTTS._read(state)
    assert state['ready'].is_set() and state['prepare_timing']['prefill_prepare_sec']==.01
    assert [m['event'] for m in progress]==['model_prepared','prefill_progress','tts_prepare_finished']
    assert state['responses'].qsize()==1  # stream 종료 오류만; progress/ready는 응답 슬롯에 없음.


def test_secret_literals_inside_llm_string_are_redacted():
    raw='{"api_key":"plain-secret","token":"other-secret","Authorization":"Bearer another-secret"}'
    clean=redact({'llm_raw':raw},secrets=[])
    assert all(x not in clean['llm_raw'] for x in ('plain-secret','other-secret','another-secret'))
    assert 'api_key' in clean['llm_raw']


def test_opt_in_goal_response_preserves_requested_open_without_completion_promise(ontology, schema, cfg):
    cfg['p2_goal_enabled'] = True
    doc = IntentParser(ontology, schema, cfg, lambda *_: dict(intent='achieve_goal', targets=[],
        confidence=.99, goals=cfg['p2_goal_catalog'][3], response_text='서랍을 닫고 전달을 완료했어요.')).parse(
            '지우개 갖다 놓고 서랍은 열어 둬')
    assert doc['goals'][1]['value'] is True
    text = doc['_voice']['final_text']
    assert '열림' in text and '목표 요청' in text and '완료했어요' not in text and '닫고' not in text


def test_prepared_payload_uses_queue_id_validated_text_and_detached_copy(ontology, schema, cfg):
    cfg['evaluation_mode'] = False
    raw = candidate(response='망치 실행을 완료했어요.')
    raw.update(request_id='llm-forged-id', accept_text='작업이 완료됐습니다.')
    session = VoiceSession(IntentParser(ontology, schema, cfg, lambda *_: json.dumps(raw)), cfg)
    doc = session.text('망치 좀', generation=3, request_id='queue-real')
    assert 'request_id' not in doc and 'accept_text' not in doc
    payload = session.prepare_request_payload(doc, 3, request_id='queue-real')
    assert payload['request_id'] == 'queue-real'
    assert payload['accept_text'] == doc['_voice']['final_text'] != raw['accept_text']
    assert '_voice' not in payload
    payload['targets'].clear()
    payload['source']['execution_allowed'] = False
    assert doc['targets'] and doc['source']['execution_allowed'] is True
    assert session.consume_acceptance_text(doc, 3) == doc['_voice']['final_text']
    assert session.prepare_request_payload(doc, 3, request_id='queue-real') is None


@pytest.mark.parametrize('change', ['copy', 'queue', 'empty_id', 'generation', 'epoch',
                                  'confidence', 'text', 'target', 'new_request', 'blocked', 'evaluation'])
def test_prepared_payload_rejects_stale_modified_or_untrusted_inputs(ontology, schema, cfg, change):
    cfg['evaluation_mode'] = False
    session = VoiceSession(IntentParser(ontology, schema, cfg), cfg)
    doc = session.text('망치 좀', generation=3, request_id='queue-real')
    generation, request_id, blocked = 3, 'queue-real', False
    if change == 'copy': doc = deepcopy(doc)
    elif change == 'queue': request_id = 'other-queue'
    elif change == 'empty_id': request_id = ''
    elif change == 'generation': generation = 4
    elif change == 'epoch': session.conversation.invalidate()
    elif change == 'confidence': doc['confidence'] = 0.01
    elif change == 'text': doc['_voice']['final_text'] = '작업이 완료됐어요.'
    elif change == 'target': doc['targets'] = ['toy_wrench']
    elif change == 'new_request': session.text('렌치 좀', request_id='next')
    elif change == 'blocked': blocked = True
    elif change == 'evaluation': cfg['evaluation_mode'] = True
    assert session.prepare_request_payload(doc, generation, request_id=request_id, blocked=blocked) is None
