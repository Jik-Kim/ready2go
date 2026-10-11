"""강의 tflite 모델 읽기와 무음 종료 녹음. 자산 자동 다운로드는 하지 않습니다."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import math
import os
import time
import wave
import numpy as np


@dataclass
class Recording:
    pcm: bytes
    ended_monotonic: float | None
    ended_unix: float | None
    truncated: bool = False
    recording_mode: str = "silence"
    recording_ended_monotonic: float | None = None
    recording_ended_unix: float | None = None
    recording_started_monotonic: float | None = None


def resolve_input_device(cfg):
    """원본과 같은 환경 우선/16kHz 입력 선택. 웨이크·녹음에서 한 번 정한 값 공유."""
    import sounddevice as sd
    override = os.environ.get('VOICE_MIC_DEVICE')
    if override:
        return int(override) if override.isdigit() else override
    if cfg.get('input_device') is not None:
        return cfg['input_device']
    try:
        for idx, dev in enumerate(sd.query_devices()):
            if dev['max_input_channels'] > 0 and round(dev['default_samplerate']) == 16000:
                return idx
    except Exception:
        pass
    # 시스템 기본 장치도 웨이크/녹음 사이에 동일 번호를 고정합니다.
    return sd.default.device[0]


class Recorder:
    def __init__(self, cfg, clock=time.monotonic, wall=time.time):
        self.cfg, self.clock, self.wall = cfg, clock, wall

    def capture(self, stop, paused=lambda: False):
        """A question's new recording, without another wake-word round."""
        if self.cfg.get('recording_mode', 'silence') == 'fixed':
            return self.record_fixed(stop, paused)
        import sounddevice as sd
        if stop.is_set() or paused():
            raise InterruptedError('녹음 중단')
        with sd.RawInputStream(samplerate=self.cfg['sample_rate'], channels=1, dtype='int16',
                               blocksize=self.cfg['frame_samples'],
                               device=resolve_input_device(self.cfg)) as stream:
            return self.record(stream, stop, paused)

    def record_fixed(self, stop, paused=lambda: False):
        """원본 sd.rec→sd.wait 고정 녹음. 발화 종료 시각은 측정하지 않습니다."""
        import sounddevice as sd
        if stop.is_set() or paused():
            raise InterruptedError('녹음 중단')
        frames = int(self.cfg['record_duration_sec'] * self.cfg['sample_rate'])
        stream = None
        started = self.clock()
        try:
            audio = sd.rec(frames, samplerate=self.cfg['sample_rate'], channels=1,
                           dtype='int16', device=self.cfg['input_device'], blocking=False)
            stream = sd.get_stream()
            deadline = self.clock() + self.cfg['max_record_sec']
            while stream.active:
                if stop.is_set() or paused():
                    raise InterruptedError('녹음 중단')
                if self.clock() >= deadline:
                    raise TimeoutError('RECORD_LIMIT')
                stop.wait(.02)
            status = sd.wait()
            if status:
                raise RuntimeError('AUDIO_OVERFLOW')
            if stop.is_set() or paused():
                raise InterruptedError('녹음 중단')
            if audio.shape != (frames, 1) or audio.dtype != np.int16:
                raise ValueError('RECORD_FORMAT')
            return Recording(audio.tobytes(), None, None, recording_mode='fixed',
                             recording_ended_monotonic=self.clock(), recording_ended_unix=self.wall(),
                             recording_started_monotonic=started)
        finally:
            if stream is not None:
                try:
                    sd.stop()
                finally:
                    stream.close()

    def record(self, stream, stop, paused=lambda: False):
        started = self.clock()
        chunks, last_voice, ended_wall = [], None, None
        while not stop.is_set():
            if paused():
                raise InterruptedError('TTS_DURING_RECORDING')
            data, overflow = stream.read(self.cfg['frame_samples'])
            if overflow:
                raise RuntimeError('AUDIO_OVERFLOW')
            pcm = bytes(data)
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
            rms = math.sqrt(float(np.mean(samples * samples))) if samples.size else 0
            now = self.clock()
            if rms >= self.cfg['speech_rms']:
                last_voice, ended_wall = now, self.wall()
            if last_voice is not None:
                chunks.append(pcm)
                if now - last_voice >= self.cfg['silence_sec']:
                    return Recording(b''.join(chunks), last_voice, ended_wall,
                                     recording_started_monotonic=started,
                                     recording_ended_monotonic=now, recording_ended_unix=self.wall())
            elif now - started >= self.cfg['speech_start_timeout_sec']:
                raise TimeoutError('NO_SPEECH')
            if now - started >= self.cfg['max_record_sec']:
                # 잘린 명령은 해석·실행하지 않습니다.
                raise TimeoutError('RECORD_LIMIT')
        raise InterruptedError('녹음 중단')


class WakeAudio:
    def __init__(self, cfg):
        from openwakeword.model import Model
        path = Path(cfg['wake_model'])
        if not path.is_file():
            raise FileNotFoundError('웨이크 모델 경로 확인 필요')
        self.cfg = cfg
        self.cfg['input_device'] = resolve_input_device(cfg)
        self.last_score = None
        self.model = Model(wakeword_models=[str(path)], inference_framework='tflite')
        self.key = path.stem

    @contextmanager
    def stream(self):
        import sounddevice as sd
        with sd.RawInputStream(samplerate=self.cfg['sample_rate'], channels=1, dtype='int16',
                               blocksize=self.cfg['frame_samples'], device=self.cfg['input_device']) as stream:
            yield stream

    def wait(self, stream, stop, paused=lambda: False):
        self.model.reset()
        while not stop.is_set():
            if paused():
                return None
            data, overflow = stream.read(self.cfg['frame_samples'])
            if overflow:
                raise RuntimeError('AUDIO_OVERFLOW')
            scores = self.model.predict(np.frombuffer(bytes(data), dtype=np.int16))
            score = float(scores.get(self.key, 0))
            if score > self.cfg['wake_threshold']:
                self.last_score = score
                self.model.reset()
                return True
        return False


def write_wav(path, recording, sample_rate):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(recording.pcm)
