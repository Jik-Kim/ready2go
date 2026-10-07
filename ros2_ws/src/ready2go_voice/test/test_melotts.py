import base64
import io
import json
import queue
import threading
import time
from types import SimpleNamespace

import pytest
from ready2go_voice.adapters.melotts import MeloTTS
from ready2go_voice.adapters.tts import PCMTTS, create_tts
from ready2go_voice.core.config import load_config
from test_audio_tts import playback, wav_bytes


@pytest.fixture
def runtime(cfg):
    adapter = object.__new__(MeloTTS)
    PCMTTS.__init__(adapter, cfg)
    replies = queue.Queue()
    class Input(io.StringIO):
        def write(self, text):
            request = json.loads(text)
            assert 'text' in request
            replies.put({'wav': base64.b64encode(wav_bytes()).decode()})
            return super().write(text)
    process = SimpleNamespace(stdin=Input(), dead=False)
    process.poll = lambda: 0 if process.dead else None
    process.terminate = lambda: setattr(process, 'dead', True)
    process.wait = lambda **kwargs: 0
    process.kill = process.terminate
    ready = threading.Event(); ready.set()
    state = dict(process=process, responses=replies, ready=ready, error=None,
                 boot_deadline=time.monotonic()+1)
    adapter._ensure_worker = lambda: state
    return adapter, state


def test_melo_uses_shared_pcm_dac_and_releases_lock(runtime, playback):
    adapter, state = runtime
    starts = []
    result = adapter.speak('안녕하세요.', on_start=starts.append)
    assert result['tts_start_basis'] == 'portaudio_first_dac'
    assert result['tts_mock'] is False and len(starts) == 1
    assert not adapter.lock.locked() and not state['process'].dead


@pytest.mark.parametrize('failure', ['canceled', 'expired', 'worker_error', 'invalid_audio'])
def test_melo_failure_never_opens_playback(runtime, playback, failure):
    adapter, state = runtime
    cancel = threading.Event()
    if failure == 'canceled': cancel.set()
    if failure == 'worker_error': state['responses'].put({'error': 'ModelError'})
    if failure == 'invalid_audio': state['responses'].put({'wav': '!'})
    deadline = time.monotonic()-1 if failure == 'expired' else time.monotonic()+1
    with pytest.raises(Exception):
        adapter.speak('안녕하세요.', cancel=cancel, start_deadline=deadline)
    assert not playback and not adapter.lock.locked()


def test_boot_timeout_terminates_worker(runtime):
    adapter, state = runtime
    state['ready'].clear(); state['boot_deadline'] = time.monotonic()-1
    adapter._watch_boot(state)
    assert state['process'].dead and state['ready'].is_set()
    assert state['error'] == 'MELOTTS_PREPARE_TIMEOUT'


def test_prepare_failure_does_not_fallback(runtime):
    adapter, state = runtime
    state['error'] = 'MissingModel'
    with pytest.raises(RuntimeError, match='MELOTTS_PREPARE_FAILED'):
        adapter.prepare()
    assert state['process'].dead


def test_missing_melo_assets_is_explicit_failure(cfg, tmp_path):
    cfg['tts_melotts_assets'] = str(tmp_path)
    with pytest.raises(RuntimeError, match='MELOTTS_RUNTIME_MISSING'):
        create_tts(cfg)


def test_legacy_config_keeps_explicit_espeak(cfg, tmp_path):
    import yaml
    from ready2go_voice.adapters.tts import EspeakTTS
    cfg.pop('tts_engine')
    path=tmp_path/'voice.yaml'; path.write_text(yaml.safe_dump(cfg))
    legacy=load_config(path)
    assert legacy['tts_engine']=='espeak'
    assert isinstance(create_tts(legacy), EspeakTTS)


@pytest.mark.parametrize('key,value', [('tts_engine','unknown'),('tts_melotts_threads',True),
    ('tts_melotts_threads',1.5),('tts_melotts_speed',0),('tts_melotts_speed',float('nan')),
    ('tts_melotts_startup_timeout_sec',-1),('tts_melotts_python',''),
    ('tts_melotts_prefill_texts',[None])])
def test_invalid_melo_config_rejected(cfg, tmp_path, key, value):
    import yaml
    cfg[key]=value
    path=tmp_path/'voice.yaml'; path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError): load_config(path)


def test_keyboard_interrupt_during_prepare_reaps_child(runtime, monkeypatch):
    adapter, state = runtime
    def interrupt(*args):
        raise KeyboardInterrupt()
    monkeypatch.setattr(state['ready'], 'wait', interrupt)
    with pytest.raises(KeyboardInterrupt): adapter.prepare()
    assert state['process'].dead and state['process'].stdin.closed
    adapter._stop(state)  # prepare/close/watchdog 간 중복 종료도 안전


@pytest.mark.parametrize('failure', ['cancel', 'timeout'])
def test_pending_synthesis_is_terminated_without_late_playback(runtime, playback, monkeypatch, failure):
    adapter, state = runtime
    monkeypatch.setattr(state['process'].stdin, 'write', lambda text: len(text))
    cancel = threading.Event()
    timer = threading.Timer(.03, cancel.set) if failure == 'cancel' else None
    if timer: timer.start()
    try:
        deadline = time.monotonic() + (.03 if failure == 'timeout' else 1)
        with pytest.raises((InterruptedError, TimeoutError)):
            adapter.speak('안녕하세요.', cancel=cancel, start_deadline=deadline)
        assert state['process'].dead and state['process'].stdin.closed
        assert not playback and not adapter.lock.locked()
    finally:
        if timer: timer.join()
