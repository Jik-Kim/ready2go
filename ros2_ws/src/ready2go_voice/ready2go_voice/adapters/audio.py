"""강의 tflite 모델 읽기와 무음 종료 녹음. 자산 자동 다운로드는 하지 않습니다."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import math
import os
import time
import wave
import queue
import threading
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


class SharedInput:
    """웨이크/질문/정지 청취가 공유하는 단일 물리 입력. 과거 프레임은 재전송하지 않습니다."""
    def __init__(self, cfg, clock=time.monotonic, wall=time.time):
        self.cfg, self.clock, self.wall = cfg, clock, wall
        self._lock = threading.Lock()
        self._readers = set()
        self._stream = None
        self._closed = False

    def start(self):
        import sounddevice as sd
        self.cfg['input_device'] = resolve_input_device(self.cfg)
        with self._lock:
            if self._closed:
                raise InterruptedError('입력 종료')
            stream = sd.RawInputStream(
                samplerate=self.cfg['sample_rate'], channels=1, dtype='int16',
                blocksize=self.cfg['frame_samples'], device=self.cfg['input_device'],
                callback=self._receive)
            self._stream = stream
        try:
            stream.start()
        except Exception:
            self.close()
            raise

    def _receive(self, data, frames, stamp, status):
        # 콜백에서는 모델/STT를 호출하지 않습니다. 느린 소비자는 오류로 폐기합니다.
        now, wall = self.clock(), self.wall()
        adc, current = stamp.inputBufferAdcTime, stamp.currentTime
        valid = (all(type(t) in (int, float) and math.isfinite(t) for t in (adc, current))
                 and adc > 0 and current - adc >= frames / self.cfg['sample_rate']
                 and frames == self.cfg['frame_samples'] and len(data) == frames * 2)
        start = now - (current - adc) if valid else now
        end = start + frames / self.cfg['sample_rate'] if valid else now
        item = (bytes(data), bool(status) or not valid, end, wall - (now - end))
        with self._lock:
            for reader in self._readers:
                current_item = item
                if valid and start < reader.started_at:
                    if not reader.capture_mode or end <= reader.started_at:
                        continue
                    offset = min(frames, math.ceil((reader.started_at-start)*self.cfg['sample_rate']))
                    current_item = (bytes(data)[offset*2:], item[1], end, item[3])
                try:
                    reader.frames.put_nowait(current_item)
                except queue.Full:
                    reader.overflow = True

    @contextmanager
    def stream(self):
        reader = _InputReader(self)
        with self._lock:
            if self._closed or self._stream is None:
                raise InterruptedError('입력 미준비/종료')
            self._readers.add(reader)
        try:
            yield reader
        finally:
            with self._lock:
                self._readers.discard(reader)
            reader.closed = True

    def close(self):
        with self._lock:
            self._closed = True
            stream, self._stream = self._stream, None
            for reader in self._readers:
                reader.closed = True
        if stream is not None:
            try:
                stream.abort()
            finally:
                stream.close()


class _InputReader:
    def __init__(self, owner):
        self.owner = owner
        cfg = owner.cfg
        self.started_at = owner.clock()
        # 기존 최대 녹음량으로만 제한하며 별도 보관/재전송 구간을 만들지 않습니다.
        self.frames = queue.Queue(maxsize=max(1, math.ceil(
            cfg['max_record_sec'] * cfg['sample_rate'] / cfg['frame_samples'])))
        self.capture_mode = False
        self.closed = self.overflow = False
        self.last_frame_monotonic = self.last_frame_unix = None
        self.interrupted = lambda: False

    def discard(self):
        with self.owner._lock:
            if self.overflow:
                raise RuntimeError('AUDIO_OVERFLOW')
            self.started_at = self.owner.clock()
            while not self.frames.empty():
                self.frames.get_nowait()
            return self.started_at

    def begin_capture(self, after=None):
        # cue 실제 종료 뒤 정상 샘플은 guard 동안 쌓여도 보존합니다. 경계를 걸친 프레임은 샘플 단위로 자릅니다.
        with self.owner._lock:
            if self.overflow:
                raise RuntimeError('AUDIO_OVERFLOW')
            boundary = self.owner.clock() if after is None else after
            if type(boundary) not in (int,float) or not math.isfinite(boundary):
                raise ValueError('CAPTURE_BOUNDARY')
            self.capture_mode = True
            self.started_at = max(self.started_at, boundary)
            retained = []
            while not self.frames.empty():
                data, overflow, end, wall = self.frames.get_nowait()
                if overflow:
                    raise RuntimeError('AUDIO_OVERFLOW')
                start = end - len(data)/2/self.owner.cfg['sample_rate']
                if end > self.started_at:
                    offset = max(0, math.ceil((self.started_at-start)*self.owner.cfg['sample_rate']))
                    retained.append((data[offset*2:],overflow,end,wall))
            for item in retained:
                self.frames.put_nowait(item)
            return self.started_at

    def read(self, frames):
        if frames != self.owner.cfg['frame_samples']:
            raise ValueError('RECORD_FRAME_FORMAT')
        interval = frames / self.owner.cfg['sample_rate']
        started = self.owner.clock()
        while not self.closed and not self.owner._closed:
            if self.interrupted():
                raise InterruptedError('녹음 중단')
            if self.owner.clock() - started >= self.owner.cfg['max_record_sec']:
                raise TimeoutError('AUDIO_INPUT_TIMEOUT')
            if self.overflow:
                raise RuntimeError('AUDIO_OVERFLOW')
            try:
                data, overflow, self.last_frame_monotonic, self.last_frame_unix = self.frames.get(timeout=interval)
                return data, overflow
            except queue.Empty:
                continue
        raise InterruptedError('입력 종료')


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
    def __init__(self, cfg, clock=time.monotonic, wall=time.time, shared_input=None):
        self.cfg, self.clock, self.wall = cfg, clock, wall
        self.shared_input = shared_input

    def capture(self, stop, paused=lambda: False):
        """A question's new recording, without another wake-word round."""
        if self.cfg.get('recording_mode', 'silence') == 'fixed':
            return self.record_fixed(stop, paused)
        if self.shared_input is not None:
            with self.shared_input.stream() as stream:
                return self.record(stream, stop, paused)
        import sounddevice as sd
        if stop.is_set() or paused():
            raise InterruptedError('녹음 중단')
        with sd.RawInputStream(samplerate=self.cfg['sample_rate'], channels=1, dtype='int16',
                               blocksize=self.cfg['frame_samples'],
                               device=resolve_input_device(self.cfg)) as stream:
            return self.record(stream, stop, paused)

    def record_fixed(self, stop, paused=lambda: False):
        """원본 sd.rec→sd.wait 고정 녹음. 발화 종료 시각은 측정하지 않습니다."""
        if self.shared_input is not None:
            with self.shared_input.stream() as stream:
                return self._fixed_shared(stream, stop, paused)
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

    def _fixed_shared(self, stream, stop, paused, *, prepared_at=None):
        stream.interrupted = lambda: stop.is_set() or paused()
        count = int(self.cfg['record_duration_sec'] * self.cfg['sample_rate']) * 2
        started, chunks, size = stream.discard() if prepared_at is None else prepared_at, [], 0
        while size < count:
            if stop.is_set() or paused():
                raise InterruptedError('녹음 중단')
            if self.clock() - started >= self.cfg['max_record_sec']:
                raise TimeoutError('RECORD_LIMIT')
            data, overflow = stream.read(self.cfg['frame_samples'])
            if overflow:
                raise RuntimeError('AUDIO_OVERFLOW')
            chunk = bytes(data)[:count - size]
            chunks.append(chunk)
            size += len(chunk)
        if stop.is_set() or paused():
            raise InterruptedError('녹음 중단')
        return Recording(b''.join(chunks), None, None, recording_mode='fixed',
                         recording_started_monotonic=started,
                         recording_ended_monotonic=stream.last_frame_monotonic,
                         recording_ended_unix=stream.last_frame_unix)

    def record(self, stream, stop, paused=lambda: False, *, prepared_at=None):
        started = self.clock()
        if isinstance(stream, _InputReader):
            started = stream.discard() if prepared_at is None else prepared_at  # 한 번 확정한 새 캡처 경계
            stream.interrupted = lambda: stop.is_set() or paused()
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
            now = getattr(stream, 'last_frame_monotonic', None) or self.clock()
            if rms >= self.cfg['speech_rms']:
                last_voice, ended_wall = now, getattr(stream, 'last_frame_unix', None) or self.wall()
            if last_voice is not None:
                chunks.append(pcm)
                if now - last_voice >= self.cfg['silence_sec']:
                    return Recording(b''.join(chunks), last_voice, ended_wall,
                                     recording_started_monotonic=started,
                                     recording_ended_monotonic=now,
                                     recording_ended_unix=getattr(stream, 'last_frame_unix', None) or self.wall())
            elif now - started >= self.cfg['speech_start_timeout_sec']:
                raise TimeoutError('NO_SPEECH')
            if now - started >= self.cfg['max_record_sec']:
                # 잘린 명령은 해석·실행하지 않습니다.
                raise TimeoutError('RECORD_LIMIT')
        raise InterruptedError('녹음 중단')


class WakeAudio:
    def __init__(self, cfg, shared_input=None):
        from openwakeword.model import Model
        path = Path(cfg['wake_model'])
        if not path.is_file():
            raise FileNotFoundError('웨이크 모델 경로 확인 필요')
        self.cfg = cfg
        if shared_input is None:
            self.cfg['input_device'] = resolve_input_device(cfg)
        self.last_score = None
        self.model = Model(wakeword_models=[str(path)], inference_framework='tflite')
        self.key = path.stem
        self.shared_input = shared_input

    @contextmanager
    def stream(self):
        if self.shared_input is not None:
            with self.shared_input.stream() as stream:
                yield stream
            return
        import sounddevice as sd
        with sd.RawInputStream(samplerate=self.cfg['sample_rate'], channels=1, dtype='int16',
                               blocksize=self.cfg['frame_samples'], device=self.cfg['input_device']) as stream:
            yield stream

    def wait(self, stream, stop, paused=lambda: False):
        self.model.reset()
        if isinstance(stream, _InputReader):
            stream.interrupted = lambda: stop.is_set() or paused()
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
