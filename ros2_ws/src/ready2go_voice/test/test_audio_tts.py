import io
import threading
import time
import wave
from types import SimpleNamespace
import numpy as np
import pytest
from ready2go_voice.adapters.audio import Recorder
from ready2go_voice.adapters.tts import EspeakTTS


class Clock:
    now = 0
    def __call__(self):
        self.now += .1
        return self.now


class Input:
    def __init__(self, values):
        self.values = iter(values)
    def read(self, size):
        return (np.ones(size, dtype=np.int16) * next(self.values, 0)).tobytes(), False


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
