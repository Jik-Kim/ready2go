import io
import threading
import time
import wave
from types import SimpleNamespace
import numpy as np
import pytest
from ready2go_voice.adapters.audio import Recorder
from ready2go_voice.adapters.tts import EspeakTTS


def test_fixed_shared_wav_preserves_last_sample_and_full_window(cfg, tmp_path):
    from ready2go_voice.adapters.audio import write_wav
    frames = int(cfg['record_duration_sec'] * cfg['sample_rate'])
    pcm = (np.arange(frames + cfg['frame_samples']) % 30000).astype(np.int16).tobytes()
    class SharedReader:
        offset = 0
        last_frame_monotonic = 6.
        last_frame_unix = 100.
        def discard(self): return 1.
        def read(self, count):
            start = self.offset
            self.offset += count * 2
            return pcm[start:self.offset], False
    recording = Recorder(cfg, clock=lambda: 1.)._fixed_shared(SharedReader(), threading.Event(), lambda: False)
    assert recording.pcm == pcm[:frames * 2]
    path = tmp_path/'fixed.wav'
    write_wav(path, recording, cfg['sample_rate'])
    with wave.open(str(path)) as wav:
        assert wav.getnframes() == frames and wav.getnchannels() == 1 and wav.getsampwidth() == 2
        assert wav.getframerate() == cfg['sample_rate']
        assert wav.readframes(frames) == pcm[:frames * 2]


class Clock:
    now = 0
    def __call__(self):
        self.now += .1
        return self.now


class Input:
    def __init__(self, values):
        self.values = iter(values)
    def read(self, size):
        return (np.resize(np.array([-1, 1], dtype=np.int16), size) * next(self.values, 0)).tobytes(), False


def test_silence_end_is_last_speech_not_fixed_duration(cfg):
    cfg['silence_sec'] = .2
    recorder = Recorder(cfg, Clock(), lambda: 123)
    result = recorder.record(Input([0, 1000, 1000, 0, 0, 0]), threading.Event())
    assert result.ended_unix == 123 and result.ended_monotonic < 1


@pytest.mark.parametrize('mode', ['silent', 'continuous', 'paused'])
def test_record_limits_hold_incomplete_speech(cfg, mode):
    cfg['max_record_sec'] = .3
    cfg['speech_start_timeout_sec'] = .2
    values = [1000] * 10 if mode == 'continuous' else [0] * 10
    with pytest.raises((TimeoutError, InterruptedError)):
        Recorder(cfg, Clock()).record(Input(values), threading.Event(), lambda: mode == 'paused')


def wav_bytes():
    data = io.BytesIO()
    with wave.open(data, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050)
        wav.writeframes(b'\0\0' * 1000)
    return data.getvalue()


@pytest.fixture
def playback(monkeypatch):
    sounddevice = pytest.importorskip('sounddevice')
    events = []
    class Output:
        def __init__(self, **kwargs):
            events.append(('format', kwargs))
            self.callback = kwargs['callback']
            self.finished = kwargs['finished_callback']
        def __enter__(self):
            events.append('stream_started')
            out = bytearray(2000)
            try:
                self.callback(out, 1000, SimpleNamespace(currentTime=10, outputBufferDacTime=10), False)
            except (sounddevice.CallbackStop, sounddevice.CallbackAbort):
                pass
            events.append(('pcm', len(out)))
            self.finished()
            return self
        def __exit__(self, *args):
            events.append('stream_closed')
        def write(self, pcm):
            events.append(('pcm', len(pcm))); return False
        def abort(self):
            events.append('abort')
    monkeypatch.setattr(sounddevice, 'RawOutputStream', Output)
    monkeypatch.setattr('shutil.which', lambda _: '/test/espeak')
    monkeypatch.setattr('subprocess.run', lambda *a, **k: SimpleNamespace(stdout=wav_bytes()))
    return events


def test_tts_start_after_synthesis_and_stream_open(cfg, playback):
    result = EspeakTTS(cfg).speak('지우개', on_start=lambda stamp: playback.append(('start', stamp)))
    assert playback.index('stream_started') < next(i for i, e in enumerate(playback) if isinstance(e, tuple) and e[0] == 'start')
    assert playback[0][1]['samplerate'] == 22050 and playback[0][1]['channels'] == 1
    assert result['tts_start_basis'] == 'portaudio_first_dac'
    # 이 검사 자체는 가짜 장치, 실제 오디오 3초 기준 통과 근거가 아님.


def test_expired_confirmation_has_no_pcm(cfg, playback):
    with pytest.raises(TimeoutError):
        EspeakTTS(cfg).speak('지우개', start_deadline=time.monotonic() - 1)
    assert not any(isinstance(e, tuple) and e[0] == 'pcm' for e in playback)


def test_tts_cancellation_stops_pcm_and_releases_lock(cfg, playback):
    cancel = threading.Event()
    tts = EspeakTTS(cfg)
    with pytest.raises(InterruptedError):
        tts.speak('지우개', cancel=cancel, on_start=lambda _: cancel.set())
    assert not tts.lock.locked()


def test_output_device_error_not_success(cfg, playback, monkeypatch):
    import sounddevice
    def fail(**kwargs):
        raise RuntimeError('device missing')
    monkeypatch.setattr(sounddevice, 'RawOutputStream', fail)
    starts = []
    with pytest.raises(RuntimeError):
        EspeakTTS(cfg).speak('지우개', on_start=starts.append)
    assert not starts


@pytest.fixture
def fixed_input(monkeypatch):
    sd = pytest.importorskip('sounddevice')
    events = []
    class Stream:
        active = False
        def close(self): events.append('close')
    stream = Stream()
    def rec(frames, **kwargs):
        events.append(('rec', frames, kwargs))
        return np.zeros((frames, 1), dtype=np.int16)
    monkeypatch.setattr(sd, 'rec', rec)
    monkeypatch.setattr(sd, 'get_stream', lambda: stream)
    monkeypatch.setattr(sd, 'wait', lambda: events.append('wait'))
    monkeypatch.setattr(sd, 'stop', lambda: events.append('stop'))
    return sd, stream, events


def test_fixed_five_seconds_format_and_unknown_speech_end(cfg, fixed_input):
    _, _, events = fixed_input
    cfg['input_device'] = 4
    recording = Recorder(cfg).record_fixed(threading.Event())
    assert events[0][1] == 80000
    assert events[0][2]['samplerate'] == 16000 and events[0][2]['channels'] == 1
    assert events[0][2]['dtype'] == 'int16' and events[0][2]['device'] == 4
    assert events[-3:] == ['wait', 'stop', 'close']
    assert len(recording.pcm) == 160000
    assert recording.ended_monotonic is recording.ended_unix is None
    assert recording.recording_ended_monotonic and recording.recording_mode == 'fixed'


@pytest.mark.parametrize('failure', ['overflow', 'cancel', 'timeout'])
def test_fixed_failure_always_stops_and_closes(cfg, fixed_input, failure):
    sd, stream, events = fixed_input
    if failure == 'overflow':
        sd.wait = lambda: True
    else:
        stream.active = True
    stopped = threading.Event()
    checks = [False, True]
    paused = (lambda: checks.pop(0)) if failure == 'cancel' else lambda: False
    clock = Clock()
    if failure == 'timeout': cfg['max_record_sec'] = .01
    with pytest.raises((InterruptedError, RuntimeError, TimeoutError)):
        Recorder(cfg, clock).record_fixed(stopped, paused)
    assert events[-2:] == ['stop', 'close']


def test_input_selection_environment_then_auto_then_default(cfg, monkeypatch):
    sd = pytest.importorskip('sounddevice')
    from ready2go_voice.adapters.audio import resolve_input_device
    monkeypatch.setenv('VOICE_MIC_DEVICE', '3')
    assert resolve_input_device(cfg) == 3
    monkeypatch.delenv('VOICE_MIC_DEVICE')
    cfg['input_device'] = None
    monkeypatch.setattr(sd, 'query_devices', lambda: [dict(max_input_channels=1, default_samplerate=16000)])
    assert resolve_input_device(cfg) == 0
    monkeypatch.setattr(sd, 'query_devices', lambda: [])
    assert resolve_input_device(cfg) == sd.default.device[0]
