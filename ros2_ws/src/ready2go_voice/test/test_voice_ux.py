"""승인 P1 UX 핵심 의미/문맥/진단/캐시 모의. 장치·API·합성 실측 아님."""
import json
from pathlib import Path
import threading
import queue
import pytest
from ready2go_voice.core.intent import IntentParser
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.core.tts_prefill import prefill_texts, remember_text
from ready2go_voice.core.diagnostics import DiagnosticFile, redact


def candidate(target='toy_hammer', kind='find_item', response=None):
    return {'intent': kind, 'targets': [target] if kind == 'find_item' else [],
            'confidence': .99, 'clarify_question': None, 'response_text': response}


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
    assert '등록된' in doc['_voice']['final_text'] and '확인하지 못' in doc['_voice']['final_text']


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
    assert doc['intent'] != 'find_item'


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
