"""격리된 CPU Melo worker. 실패/취소/기한 초과는 재생으로 이어지지 않습니다."""
import base64
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from .tts import PCMTTS


class MeloTTS(PCMTTS):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.lifecycle = threading.Lock()
        self.runtime = None
        self.closed = False
        self._ensure_worker()

    def _ensure_worker(self):
        with self.lifecycle:
            if self.closed:
                raise RuntimeError('TTS_CLOSED')
            if self.runtime and self.runtime['process'].poll() is None:
                return self.runtime
            python = Path(self.cfg['tts_melotts_python']).expanduser().absolute()
            assets = Path(self.cfg['tts_melotts_assets']).expanduser().resolve()
            if not python.is_file() or not (assets / 'model_manifest.json').is_file():
                raise RuntimeError('MELOTTS_RUNTIME_MISSING')
            env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR') if k in os.environ}
            for key in ('PYTHONPATH', 'PYTHONHOME', 'OPENAI_API_KEY', 'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'):
                env.pop(key, None)
            env.update(HF_HOME=str(assets / 'hf'), HF_HUB_CACHE=str(assets / 'hf'),
                       HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                       HF_HUB_DISABLE_IMPLICIT_TOKEN='1', NLTK_DATA=str(assets / 'nltk'),
                       NUMBA_CACHE_DIR=str(assets / 'numba'))
            worker = str(Path(__file__).with_name('melotts_worker.py'))
            log = assets / 'worker.log'
            with log.open('ab') as stderr:
                process = subprocess.Popen([str(python), '-u', worker], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=stderr, text=True, encoding='utf-8', env=env)
            state = {'process': process, 'ready': threading.Event(), 'responses': queue.Queue(),
                     'error': None, 'boot_deadline': time.monotonic() + self.cfg['tts_melotts_startup_timeout_sec']}
            self.runtime = state
            config = {k: self.cfg[k] for k in ('tts_melotts_speaker', 'tts_melotts_speed',
                      'tts_melotts_threads', 'tts_melotts_warmup_text')}
            config['assets'] = str(assets)
            config['prefill_texts'] = self.cfg.get('_tts_prefill_texts', self.cfg.get('tts_melotts_prefill_texts', []))
            try:
                process.stdin.write(json.dumps(config, ensure_ascii=False) + '\n')
                process.stdin.flush()
                threading.Thread(target=self._read, args=(state,), daemon=True).start()
                threading.Thread(target=self._watch_boot, args=(state,), daemon=True).start()
                print('MeloTTS 준비 중 (모델·고정 안내 캐시)', flush=True)
            except BaseException:
                self._stop(state)
                raise
            return state

    @classmethod
    def _watch_boot(cls, state):
        if not state['ready'].wait(max(0, state['boot_deadline'] - time.monotonic())):
            state['error'] = 'MELOTTS_PREPARE_TIMEOUT'
            cls._stop(state)
            state['ready'].set()

    def prepare(self):
        state = self._ensure_worker()
        try:
            state['ready'].wait(max(0, state['boot_deadline'] - time.monotonic()))
            if not state['ready'].is_set() or state['error']:
                raise RuntimeError('MELOTTS_PREPARE_FAILED')
        except BaseException:  # __init__의 Ctrl+C도 main의 node.close 전에 정리
            self._stop(state)
            raise

    @staticmethod
    def _read(state):
        try:
            for line in state['process'].stdout:
                message = json.loads(line)
                if message.get('ready'):
                    if state['error']:
                        continue
                    state['ready'].set()
                    print('MeloTTS 준비 완료 (고정 안내 캐시 완료)', flush=True)
                elif 'error' in message and not state['ready'].is_set():
                    state['error'] = message['error']
                    print('MeloTTS 준비 실패: ' + state['error'], flush=True)
                    state['ready'].set()
                else:
                    state['responses'].put(message)
        except Exception as exc:
            state['error'] = type(exc).__name__
        finally:
            state['error'] = state['error'] or 'MELOTTS_WORKER_EXITED'
            state['ready'].set()
            state['responses'].put({'error': state['error']})
            state['process'].stdout.close()

    @staticmethod
    def _stop(state):
        with state.setdefault('stop_lock', threading.Lock()):
            process = state['process']
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=.5)
            if process.stdin and not process.stdin.closed:
                process.stdin.close()

    def _synthesize(self, text, deadline, cancel):
        state = self._ensure_worker()
        process = state['process']
        def check():
            if cancel and cancel.is_set():
                raise InterruptedError('TTS_CANCELED')
            if time.monotonic() >= deadline:
                raise TimeoutError('TTS_START_TIMEOUT')
            if not state['ready'].is_set() and time.monotonic() >= state['boot_deadline']:
                raise TimeoutError('MELOTTS_PREPARE_TIMEOUT')
        try:
            while not state['ready'].wait(.01):
                check()
            check()
            if state['error']:
                raise RuntimeError('MELOTTS_PREPARE_FAILED:' + state['error'])
            print('TTS 준비: 캐시 확인 / 필요 시 합성', flush=True)
            process.stdin.write(json.dumps({'text': text}, ensure_ascii=False) + '\n')
            process.stdin.flush()
            while True:
                check()
                try:
                    response = state['responses'].get(timeout=.01)
                    break
                except queue.Empty:
                    pass
            check()
            if 'error' in response:
                raise RuntimeError('MELOTTS_SYNTH_FAILED:' + response['error'])
            print('TTS 준비 완료: ' + ('캐시 사용' if response.get('cache_hit') else '새 합성'), flush=True)
            self.last_synthesis = {'cache_hit': response.get('cache_hit'), 'synth_sec': response.get('synth_sec')}
            return base64.b64decode(response['wav'], validate=True)
        except Exception:
            # Terminate unfinished synthesis; a late response cannot reach a later request.
            self._stop(state)
            raise

    def close(self):
        with self.lifecycle:
            self.closed = True
            if self.runtime:
                self._stop(self.runtime)
