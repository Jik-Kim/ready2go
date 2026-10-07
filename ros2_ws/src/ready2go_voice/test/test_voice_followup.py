import json
import threading
from types import SimpleNamespace
import numpy as np
import pytest
from ready2go_voice.adapters.audio import Recording, WakeAudio
from ready2go_voice.adapters.speech import SpeechPresence
from ready2go_voice.core.session import VoiceSession
from ready2go_voice.core.intent import IntentParser


class Detector:
    def __init__(self, scores):
        self.scores=iter(scores); self.resets=0
    def reset_states(self): self.resets+=1
    def predict(self, data, frame_size):
        assert frame_size==480 and len(data)==480 and data.dtype==np.int16
        return next(self.scores,0)


def recording(amp=1000):
    return Recording((np.ones(80000,dtype=np.int16)*amp).tobytes(),None,None,recording_mode='fixed')


@pytest.mark.parametrize('amp,scores,expected',[(0,[1]*10,False),(10,[1]*10,False),
    (1000,[0]*10,False),(1000,[.9]*3+[0]*160,False), # 90ms 순간 소음/잔음 후보
    (1000,[0]*20+[.9]*6+[0]*150,True), # 전체5초 평균 없이 180ms짧은 발화
    (1000,[.9]*6+[0]*150,True)]) # 180ms잔음도 통과가능: 실제튜닝 필요
def test_frame_presence(cfg,amp,scores,expected):
    detector=Detector(scores)
    assert SpeechPresence(cfg,detector).check(recording(amp)) is expected
    assert detector.resets==2


def test_empty_and_cancel_and_invalid_scores(cfg):
    gate=SpeechPresence(cfg,Detector([float('nan')]))
    assert gate.check(Recording(b'',None,None,recording_mode='fixed')) is False
    cancel=threading.Event(); cancel.set()
    with pytest.raises(InterruptedError): gate.check(recording(),cancel=cancel)
    with pytest.raises(RuntimeError,match='VAD_FAILED'): gate.check(recording())


@pytest.mark.parametrize('mode',['silent','missing','error','cancel'])
def test_no_speech_or_vad_failure_skips_stt_llm_and_publish(cfg,ontology,schema,mode):
    counters={'stt':0,'llm':0}; events=[]
    class STT:
        def transcribe(self,*args): counters['stt']+=1; return '지우개 찾아줘'
    def llm(*args): counters['llm']+=1; return {}
    def check(*args,**kwargs):
        if mode=='missing': raise RuntimeError('VAD_UNAVAILABLE')
        if mode=='error': raise RuntimeError('VAD_FAILED')
        if mode=='cancel': raise InterruptedError()
        return False
    session=VoiceSession(IntentParser(ontology,schema,cfg,llm),cfg,STT(),
        speech_gate=SimpleNamespace(check=check),progress=lambda **event:events.append(event))
    doc=session.audio(recording())
    assert counters=={'stt':0,'llm':0}
    assert doc['intent']=='clarify' and not doc.get('targets')
    assert doc['source']['llm_validation']=='not_called' and not doc['source']['execution_allowed']
    assert 'stt_error' not in doc['source'] and not any(e['event']=='stt_failed' for e in events)
    assert doc['source']['confirmation_latency_ms'] is None
    cfg['evaluation_mode']=False
    assert session.should_publish(doc) is False


def test_short_speech_checks_then_sends_full_five_seconds(cfg,ontology,schema):
    captured=[]; parser=IntentParser(ontology,schema,cfg)
    class STT:
        def transcribe(self,path,timeout):
            import wave
            with wave.open(str(path)) as w: captured.append(w.getnframes())
            return '지우개 찾아줘'
    gate=SpeechPresence(cfg,Detector([0]*12+[.9]*6))
    doc=VoiceSession(parser,cfg,STT(),speech_gate=gate).audio(recording())
    assert doc['intent']=='find_item' and captured==[80000]


def test_free_llm_clarify_is_fixed_but_raw_retained(cfg,ontology,schema):
    raw={'intent':'clarify','targets':[],'confidence':.99,'clarify_question':'긴 임의 질문입니다.'}
    parser=IntentParser(ontology,schema,cfg,llm=lambda *a:raw)
    doc=parser.parse('알 수 없는 특수 요청입니다')
    assert doc['clarify_question']==cfg['clarify_prompts']['general']
    assert doc['source']['llm_raw']==raw and not doc['source']['execution_allowed']


@pytest.mark.parametrize('text,key',[('','empty'),('지우개','bare'),('그거','missing_item'),
                                     ('지우개랑 립밤 찾아줘','multiple')])
def test_rule_clarify_meaning_preserved(cfg,ontology,schema,text,key):
    doc=IntentParser(ontology,schema,cfg).parse(text)
    assert doc['intent']=='clarify' and doc['clarify_question']==cfg['clarify_prompts'][key]


def test_wake_threshold_uses_strict_greater(cfg):
    stop=threading.Event(); scores=iter([.663,.7,.701]); visited=[]
    def predict(_):
        score=next(scores); visited.append(score); return {'test':score}
    wake=object.__new__(WakeAudio); wake.cfg=cfg; wake.key='test'
    wake.model=SimpleNamespace(reset=lambda:None,predict=predict)
    stream=SimpleNamespace(read=lambda n:(b'\0\0'*n,False))
    assert cfg['wake_threshold']==.7 and wake.wait(stream,stop)
    assert visited==[.663,.7,.701] and wake.last_score==.701


@pytest.mark.parametrize('key,value',[('speech_vad_threshold',0),('speech_vad_threshold',True),
 ('speech_min_voiced_sec',float('nan')),('speech_min_voiced_sec',6),('speech_vad_model',''),
 ('clarify_prompts',{}),('clarify_prompts',{'general':None})])
def test_speech_prompt_config_validation(cfg,tmp_path,key,value):
    import yaml
    from ready2go_voice.core.config import load_config
    cfg[key]=value; p=tmp_path/'voice.yaml'; p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError): load_config(p)
