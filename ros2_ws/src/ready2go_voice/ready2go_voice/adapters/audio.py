"""강의 tflite 모델 읽기와 무음 종료 녹음. 자산 자동 다운로드는 하지 않습니다."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import math
import time
import wave
import numpy as np


@dataclass
class Recording:
    pcm: bytes
    ended_monotonic: float
    ended_unix: float
    truncated: bool = False


class Recorder:
    def __init__(self, cfg, clock=time.monotonic, wall=time.time):
        self.cfg, self.clock, self.wall = cfg, clock, wall

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
                    return Recording(b''.join(chunks), last_voice, ended_wall)
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
            if scores.get(self.key, 0) >= self.cfg['wake_threshold']:
                self.model.reset()
                return True
        return False


def write_wav(path, recording, sample_rate):
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(recording.pcm)
