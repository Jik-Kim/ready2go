"""고정 녹음 후 로컬 Silero 음성 구간 검사. 발화 종료 시각 추정은 하지 않습니다."""
from pathlib import Path
import threading
import numpy as np


class SpeechPresence:
    FRAME_SAMPLES = 480  # 설치된 openwakeword Silero 입력: 30ms, 16kHz

    def __init__(self, cfg, detector=None):
        self.cfg, self.detector = cfg, detector
        self.lock = threading.Lock()

    def _load(self):
        if self.detector is None:
            try:
                import openwakeword.vad as vad
                path = self.cfg.get('speech_vad_model') or str(Path(vad.__file__).parent / 'resources/models/silero_vad.onnx')
                if not Path(path).is_file():
                    raise FileNotFoundError(path)
                self.detector = vad.VAD(model_path=path, n_threads=1)
            except Exception as exc:
                raise RuntimeError('VAD_UNAVAILABLE') from exc
        return self.detector

    def check(self, recording, cancel=None, paused=lambda: False):
        def interrupted():
            if (cancel and cancel.is_set()) or paused():
                raise InterruptedError('SPEECH_CHECK_CANCELED')
        interrupted()
        if self.cfg['sample_rate'] != 16000 or len(recording.pcm) % 2:
            raise ValueError('VAD_PCM_FORMAT')
        samples = np.frombuffer(recording.pcm, dtype='<i2')
        if not samples.size:
            return False
        with self.lock:
            detector = self._load()
            detector.reset_states()
            voiced = 0
            required = self.cfg['speech_min_voiced_sec'] * self.cfg['sample_rate']
            try:
                for begin in range(0, samples.size, self.FRAME_SAMPLES):
                    interrupted()
                    frame = samples[begin:begin+self.FRAME_SAMPLES]
                    rms = float(np.sqrt(np.mean(frame.astype(np.float64)**2)))
                    # Low amplitude alone cannot establish speech; VAD confidence is also required.
                    data = np.pad(frame, (0, self.FRAME_SAMPLES-len(frame)))
                    score = float(detector.predict(data, frame_size=self.FRAME_SAMPLES))
                    if not np.isfinite(score) or not 0 <= score <= 1:
                        raise ValueError('VAD_SCORE_INVALID')
                    voiced = voiced + len(frame) if rms >= self.cfg['speech_rms'] and score >= self.cfg['speech_vad_threshold'] else 0
                    if voiced >= required:
                        interrupted()
                        return True
                interrupted()
                return False
            except InterruptedError:
                raise
            except Exception as exc:
                raise RuntimeError('VAD_FAILED') from exc
            finally:
                detector.reset_states()
