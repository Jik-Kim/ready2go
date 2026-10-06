"""espeak-ng WAV → PortAudio. 첫 DAC 재생 시각은 장치가 보고한 시각으로 기록합니다."""
import io
import shutil
import subprocess
import threading
import time
import wave


class EspeakTTS:
    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.Lock()

    def speak(self, text, cancel=None, on_start=None, timeout=None, start_deadline=None):
        import sounddevice as sd
        timeout = self.cfg['tts_timeout_sec'] if timeout is None else timeout
        deadline = time.monotonic() + timeout
        if timeout <= 0 or not self.lock.acquire(timeout=max(0, timeout)):
            raise TimeoutError('TTS_BUSY')
        try:
            if cancel and cancel.is_set():
                raise InterruptedError('TTS_CANCELED')
            exe = shutil.which(self.cfg['tts_executable'])
            if not exe:
                raise RuntimeError('TTS_EXECUTABLE_MISSING')
            synth_deadline = min(deadline, start_deadline) if start_deadline is not None else deadline
            if time.monotonic() >= synth_deadline:
                raise TimeoutError('TTS_START_TIMEOUT')
            result = subprocess.run([exe, '-v', self.cfg['tts_voice'], '-s', str(self.cfg['tts_speed']),
                                     '--stdout', '--stdin'], input=text.encode('utf-8'),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                                    timeout=max(.001, synth_deadline - time.monotonic()))
            with wave.open(io.BytesIO(result.stdout), 'rb') as wav:
                channels, rate, width = wav.getnchannels(), wav.getframerate(), wav.getsampwidth()
                if width != 2 or channels != 1 or rate <= 0:
                    raise ValueError('TTS_PCM_FORMAT')
                pcm = wav.readframes(wav.getnframes())
            if not pcm:
                raise ValueError('TTS_EMPTY_AUDIO')
            finished = threading.Event()
            state = {'position': 0, 'stamp': None, 'error': None}

            def callback(outdata, frames, times, status):
                outdata[:] = b'\0' * len(outdata)
                if cancel and cancel.is_set():
                    state['error'] = InterruptedError('TTS_CANCELED')
                    raise sd.CallbackAbort
                if status:
                    state['error'] = RuntimeError('TTS_STREAM_STATUS')
                    raise sd.CallbackAbort
                if state['stamp'] is None:
                    delta = max(0, times.outputBufferDacTime - times.currentTime)
                    mono = time.monotonic() + delta
                    if mono >= deadline or (start_deadline is not None and mono >= start_deadline):
                        state['error'] = TimeoutError('TTS_START_TIMEOUT')
                        raise sd.CallbackAbort
                    state['stamp'] = {'tts_started_unix': time.time() + delta,
                        'tts_started_monotonic': mono, 'tts_start_basis': 'portaudio_first_dac', 'tts_mock': False}
                begin = state['position']
                end = min(begin + frames * width, len(pcm))
                outdata[:end - begin] = pcm[begin:end]
                state['position'] = end
                if end == len(pcm):
                    raise sd.CallbackStop  # 재생 버퍼를 비운 후 finished_callback

            announced = False
            with sd.RawOutputStream(samplerate=rate, channels=channels, dtype='int16', blocksize=512,
                    device=self.cfg['output_device'], callback=callback, finished_callback=finished.set) as output:
                while True:
                    if cancel and cancel.is_set():
                        output.abort()
                        raise InterruptedError('TTS_CANCELED')
                    if state['error']:
                        raise state['error']
                    if time.monotonic() >= deadline:
                        output.abort()
                        raise TimeoutError('TTS_TIMEOUT')
                    stamp = state['stamp']
                    if stamp and not announced and time.monotonic() >= stamp['tts_started_monotonic']:
                        if on_start:
                            on_start(stamp)
                        announced = True
                    if finished.wait(.01) and announced:
                        break
            if cancel and cancel.is_set():
                raise InterruptedError('TTS_CANCELED')
            return state['stamp']
        finally:
            self.lock.release()
