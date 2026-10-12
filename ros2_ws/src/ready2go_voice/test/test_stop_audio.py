"""단일 입력/독립 정지의 모의 경계. 실제 마이크·Whisper·물리 정지 증거가 아닙니다."""
from contextlib import contextmanager
from types import SimpleNamespace
import sys
import queue
import threading
import numpy as np
import pytest
from ready2go_voice.adapters.audio import SharedInput, Recorder, Recording
from ready2go_voice.core.session import VoiceSession
from test_voice_ux_node import node_class, node


@pytest.fixture
def microphone(cfg, monkeypatch):
    clock = [100.0]
    native = []
    class Input:
        def __init__(self, **kw):
            native.append(self)
            self.callback = kw['callback']
            self.started = self.aborted = self.closed = False
        def start(self): self.started = True
        def abort(self): self.aborted = True
        def close(self): self.closed = True
    cfg['input_device'] = 1
    monkeypatch.delenv('VOICE_MIC_DEVICE', raising=False)
    monkeypatch.setitem(sys.modules, 'sounddevice', SimpleNamespace(RawInputStream=Input))
    shared = SharedInput(cfg, clock=lambda:clock[0], wall=lambda:clock[0]+1000)
    shared.start()
    def feed(value=1000, *, at=None, invalid=False):
        if at is not None: clock[0] = at
        size = cfg['frame_samples']
        period = size / cfg['sample_rate']
        stamp = SimpleNamespace(inputBufferAdcTime=0 if invalid else 10., currentTime=10.+2*period)
        native[0].callback((np.resize(np.array([1,-1],dtype=np.int16),size)*value).tobytes(),size,stamp,False)
    yield shared, clock, feed, native
    shared.close()


def test_single_native_input_independent_consumers_fresh_cutoff_and_format(cfg,microphone):
    shared,clock,feed,native = microphone
    with shared.stream() as first, shared.stream() as second:
        feed(at=100.04)  # ADC 시작이 소비자 등록보다 앞섭니다.
        assert first.frames.empty() and second.frames.empty()
        feed(at=100.4)
        assert first.read(cfg['frame_samples'])[0] == second.read(cfg['frame_samples'])[0]
        clock[0]=101.
        assert first.discard()==101.
        feed(at=101.04)
        assert first.frames.empty() and not second.frames.empty()
        feed(at=101.4)
        assert first.read(cfg['frame_samples'])[1] is False
        with pytest.raises(ValueError): first.read(1)
    assert len(native)==1 and native[0].started


def test_input_overflow_and_unconfirmed_adc_fail_closed(cfg,microphone):
    shared,clock,feed,_=microphone
    with shared.stream() as bad:
        feed(at=100.4,invalid=True)
        assert bad.read(cfg['frame_samples'])[1] is True
        clock[0]=101.
        native=shared._stream
        native.callback(b'\0',cfg['frame_samples'],SimpleNamespace(inputBufferAdcTime=10.,currentTime=10.16),False)
        assert bad.read(cfg['frame_samples'])[1] is True
    cfg['max_record_sec']=cfg['frame_samples']/cfg['sample_rate']
    with shared.stream() as slow:
        feed(at=101.4);feed(at=101.8)
        with pytest.raises(RuntimeError,match='AUDIO_OVERFLOW'):slow.read(cfg['frame_samples'])


def test_cancel_and_close_release_waiting_read(cfg,microphone):
    shared,_,_,native=microphone
    with shared.stream() as reader:
        cancel=threading.Event();cancel.set();reader.interrupted=cancel.is_set
        with pytest.raises(InterruptedError):reader.read(cfg['frame_samples'])
        reader.interrupted=lambda:False
        outcome=[];entered=threading.Event()
        def read():
            entered.set()
            try:reader.read(cfg['frame_samples'])
            except InterruptedError:outcome.append('closed')
        worker=threading.Thread(target=read);worker.start()
        assert entered.wait(1)
        shared.close();worker.join(1)
        assert not worker.is_alive() and outcome==['closed']
    assert native[0].aborted and native[0].closed


@pytest.mark.parametrize('fixed',[False,True])
def test_recording_cutoff_drops_inflight_old_frame_and_uses_same_start(cfg,microphone,fixed):
    shared,clock,feed,_=microphone
    cfg.update(silence_sec=.2,record_duration_sec=cfg['frame_samples']/cfg['sample_rate']*2)
    recorder=Recorder(cfg,clock=lambda:clock[0],shared_input=shared)
    with shared.stream() as reader:
        feed(3000,at=100.4)
        clock[0]=101.
        reset=threading.Event();original=reader.discard
        def discard():
            value=original();reset.set();return value
        reader.discard=discard
        result=[]
        def record():
            result.append(recorder._fixed_shared(reader,threading.Event(),lambda:False) if fixed
                          else recorder.record(reader,threading.Event()))
        worker=threading.Thread(target=record);worker.start()
        assert reset.wait(1)
        feed(3000,at=101.04)  # 기준 갱신 전부터 진행 중인 ADC 프레임
        feed(1000,at=101.4);feed(0,at=101.8)
        worker.join(1)
        assert not worker.is_alive() and len(result)==1
        recording=result[0]
        assert recording.recording_started_monotonic==101.
        assert np.frombuffer(recording.pcm,dtype=np.int16)[0]==1000
        assert 3000 not in np.frombuffer(recording.pcm,dtype=np.int16)
        if fixed:assert len(recording.pcm)==cfg['frame_samples']*4


class STT:
    supports_request_boundary=True
    def __init__(self,text='멈춰',hook=lambda:None):self.text,self.hook,self.calls=text,hook,0
    def transcribe(self,path,timeout,*,before_request):
        self.calls+=1
        assert path.is_file() and before_request(100.)
        self.hook()
        return self.text


def recording():
    return Recording(b'\x01\x00'*1280,99.5,123.,recording_started_monotonic=99.,recording_ended_monotonic=100.)


@pytest.mark.parametrize('text',['멈추지 마','멈춰라고 말했어','"멈춰"','아마 멈춰','재개해'])
def test_stop_rejects_negation_quote_ambiguity_and_other_commands(cfg,text):
    session=VoiceSession(None,cfg,STT(text),clock=lambda:100.)
    assert session.stop_audio(recording()) is None


def test_stop_has_separate_stt_slot_no_llm_and_self_speech_guard(cfg):
    stt=STT();session=VoiceSession(None,cfg,stt,clock=lambda:100.)
    session.stt_calls._lock.acquire()  # 처리 중 P1 STT 슬롯을 모델링합니다.
    try:
        assert session.stop_audio(recording())['intent']=='cancel'
        assert session.stop_audio(recording(),spoken_texts={'“멈춰”라고 말씀해 주세요.'}) is None
        assert stt.calls==2
    finally:session.stt_calls._lock.release()


def test_network_failure_and_generation_change_do_not_return_stop(cfg):
    def fail():raise OSError('network unavailable')
    session=VoiceSession(None,cfg,STT(hook=fail),clock=lambda:100.)
    assert session.stop_audio(recording()) is None
    stale=[False];session.stt=STT(hook=lambda:stale.__setitem__(0,True))
    assert session.stop_audio(recording(),paused=lambda:stale[0]) is None


def test_stop_late_sdk_result_is_discarded_and_slot_recovers(cfg):
    cfg['stt_timeout_sec']=.01
    release=threading.Event();ended=threading.Event()
    class Slow(STT):
        def transcribe(self,*args,**kw):
            release.wait(1)
            try:return super().transcribe(*args,**kw)
            finally:ended.set()
    session=VoiceSession(None,cfg,Slow(),clock=lambda:100.)
    try:assert session.stop_audio(recording()) is None
    finally:release.set()
    assert ended.wait(1)
    assert session.stop_stt_calls._lock.acquire(timeout=1)
    session.stop_stt_calls._lock.release()
    session.stt=STT()
    assert session.stop_audio(recording())['intent']=='cancel'


def test_actual_stop_listener_bypasses_tts_and_p1_slot_and_suppresses_question_duplicate(node,microphone):
    shared,clock,feed,_=microphone
    node.cfg.update(silence_sec=.2)
    node.now=clock;node.place_clock=lambda:clock[0];node.session.clock=lambda:clock[0]
    node.shared_input=shared;node.session.stt=STT()
    node.busy.set();node.tts.lock.acquire();node.session.stt_calls._lock.acquire()
    old_cancel=node.safety_cancel
    ready=threading.Event();original=shared.stream
    @contextmanager
    def stream():
        with original() as reader:
            old=reader.discard
            def discard():
                value=old();ready.set();return value
            reader.discard=discard
            yield reader
    shared.stream=stream
    publish=node._publish
    node._publish=lambda doc:(publish(doc),node.stop_event.set())
    worker=threading.Thread(target=node._stop_listen);worker.start()
    try:
        assert ready.wait(1)
        feed(at=100.4);feed(0,at=100.8)
        worker.join(1)
        assert not worker.is_alive()
        assert [doc['intent'] for doc in node.published]==['cancel']
        assert node.tts.lock.locked() and node.session.stt_calls._lock.locked()
        assert node.generation==1 and old_cancel.is_set()
        node.stop_event.clear()  # 종료 조건이 아닌 오래된 cancel/세대 검사로 중복을 거절해야 합니다.
        node._safety_result_locked(dict(intent='cancel'),old_cancel,lambda *a:None)
        assert len(node.published)==1 and not node._stop_locked(dict(intent='cancel'),0)
    finally:
        node.stop_event.set();shared.close();worker.join(1)
        node.tts.lock.release();node.session.stt_calls._lock.release()


def test_evaluation_cancel_clears_work_without_publication(node):
    node.cfg['evaluation_mode']=True
    with node.submit_lock:node._stop_locked(dict(intent='cancel',source={'stt_text':'멈춰','execution_allowed':False}),0)
    assert node.request_cancel.is_set() and node.generation==1 and not node.published


@pytest.mark.parametrize('diagnostic_failure',[False,'held','capture'])
def test_overflow_discards_reader_and_pcm_then_fresh_stop_reaches_publisher(node,microphone,diagnostic_failure,capsys):
    shared,clock,feed,_=microphone
    node.cfg.update(silence_sec=.08,max_record_sec=.5)
    node.place_clock=lambda:clock[0];node.session.clock=lambda:clock[0]
    node.shared_input=shared;node.busy.set()
    diagnostics=[];readers=[];second_ready=threading.Event();received=[]
    def diagnostic(doc):
        diagnostics.append(doc)
        if (diagnostic_failure=='held' and doc.get('reason')=='AUDIO_OVERFLOW'
                or diagnostic_failure=='capture' and doc['event'].startswith('stop_capture')):
            raise OSError('diagnostic unavailable')
    node._diagnostic=diagnostic
    class FreshSTT(STT):
        def transcribe(self,path,*args,**kwargs):
            import wave
            with wave.open(str(path),'rb') as wav:
                received.append(np.frombuffer(wav.readframes(wav.getnframes()),dtype=np.int16))
            self.calls+=1
            assert kwargs['before_request'](clock[0])
            return self.text
    node.session.stt=FreshSTT()
    original=shared.stream
    @contextmanager
    def stream():
        with original() as reader:
            readers.append(reader)
            if len(readers)==1:
                read=reader.read
                def overflow(frames):
                    # 정상 callback으로 실제 reader 큐를 넘칩니다. 손상 PCM은 STT에 가지 않습니다.
                    for i in range(reader.frames.maxsize+1):feed(7000,at=100.4+i*.01)
                    return read(frames)
                reader.read=overflow
            else:
                discard=reader.discard
                def fresh():
                    stamp=discard();second_ready.set();return stamp
                reader.discard=fresh
            yield reader
    shared.stream=stream
    publish=node._publish
    node._publish=lambda doc:(publish(doc),node.stop_event.set())
    worker=threading.Thread(target=node._stop_listen);worker.start()
    try:
        assert second_ready.wait(1)
        assert readers[0].closed and readers[0] not in shared._readers
        assert node.session.stt.calls==0 and not node.published
        feed(1000,at=100.8);feed(0,at=101.)
        worker.join(1);node.stop_processor.join(1)
        assert not worker.is_alive() and not node.stop_processor.is_alive()
        assert [d['intent'] for d in node.published]==['cancel']
        assert node.session.stt.calls==1 and len(received)==1
        assert 7000 not in received[0] and 1000 in received[0]
        assert node.stop_spoken is None and not shared._readers
        assert any(d.get('reason')=='AUDIO_OVERFLOW' for d in diagnostics)
        assert any(d['event']=='stop_capture_diagnostic_failed' for d in diagnostics)==bool(diagnostic_failure)
        if diagnostic_failure=='capture':
            assert 'voice_diagnostic_failed' in capsys.readouterr().out
    finally:
        node.stop_event.set();shared.close();worker.join(1);node.stop_processor.join(1)


def test_pending_stop_replacement_keeps_fresh_capture_when_diagnostic_fails(node,capsys):
    node.stop_captures=queue.Queue(maxsize=1)
    old=recording();fresh=recording()
    def fail(doc):raise OSError('diagnostic unavailable')
    node._diagnostic=fail
    assert node._queue_stop_capture(old,0,())
    assert node._queue_stop_capture(fresh,0,())
    value=node.stop_captures.get_nowait()
    assert value[0] is fresh and node.stop_captures.empty()
    assert node.stop_captures.unfinished_tasks==1
    node.stop_captures.task_done()
    assert 'voice_diagnostic_failed' in capsys.readouterr().out


@pytest.mark.parametrize('failure',['close','stop','unready','device','runtime','interrupted'])
def test_stop_listener_exits_for_shutdown_or_unrecoverable_input_without_retry(node,microphone,failure):
    shared,clock,_,_=microphone
    node.shared_input=shared;node.place_clock=lambda:clock[0];node.busy.set()
    attempts=[];original=shared.stream
    @contextmanager
    def stream():
        attempts.append(1)
        if failure=='close':shared.close()
        if failure=='unready':shared._stream=None
        if failure=='device':raise OSError('device unavailable')
        if failure=='runtime':raise RuntimeError('different input error')
        if failure=='interrupted':raise InterruptedError('unexpected device interruption')
        with original() as reader:
            if failure=='stop':node.stop_event.set()
            yield reader
    shared.stream=stream
    worker=threading.Thread(target=node._stop_listen);worker.start()
    try:
        worker.join(1)
        assert not worker.is_alive() and attempts==[1]
        assert not node.published and node.stop_captures.empty()
        assert node.stop_spoken is None and not shared._readers
        assert any(d['event']=='stop_input_unavailable' for d in node.diagnostics)==(
            failure in ('device','runtime','interrupted'))
    finally:
        node.stop_event.set();shared.close();worker.join(1);node.stop_processor.join(1)
