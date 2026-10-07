"""대화 처리와 평가 게이트. 로봇 동작·실행 상태 저장은 하지 않습니다."""
from pathlib import Path
import tempfile
import time
from .deadline import DeadlineCall
from .intent import intent


class VoiceSession:
    def __init__(self, parser, cfg, stt=None, clock=time.monotonic, progress=lambda **event: None, speech_gate=None):
        self.parser, self.cfg, self.stt, self.clock = parser, cfg, stt, clock
        self.progress = progress
        self.speech_gate = speech_gate
        self.stt_calls = DeadlineCall()
        self._last = None

    def audio(self, recording, cancel=None, paused=lambda: False):
        from ..adapters.audio import write_wav
        commissioning = self.cfg.get('timing_mode', 'ac_budget') == 'commissioning'
        held = None
        if recording.recording_mode == 'fixed' and not recording.truncated:
            try:
                if self.speech_gate is None:
                    from ..adapters.speech import SpeechPresence
                    self.speech_gate = SpeechPresence(self.cfg)
                self.progress(event='speech_check_started')
                if not self.speech_gate.check(recording, cancel=cancel, paused=paused):
                    held = 'NO_SPEECH'
                    self.progress(event='no_speech')
            except Exception as exc:
                held = 'SPEECH_CHECK_CANCELED' if isinstance(exc, InterruptedError) else 'VAD_UNAVAILABLE_OR_FAILED'
                self.progress(event='speech_check_failed', error_type=type(exc).__name__)
        if (cancel and cancel.is_set()) or paused():
            held = 'SPEECH_CHECK_CANCELED'
        deadline = None if commissioning else recording.ended_monotonic + self.cfg['confirmation_budget_sec']
        timeout = self.cfg['stt_timeout_sec'] if commissioning else min(
            self.cfg['stt_timeout_sec'], deadline - self.clock() - self.cfg['tts_reserve_sec'])
        try:
            if held:
                raise ValueError(held)
            if recording.truncated or self.stt is None:
                raise ValueError('STT_UNAVAILABLE')
            # 디렉터리는 늦은 호출이 읽는 파일을 고려해 호출자/작업자가 나눠 소유하지 않음:
            # STT 작업자 안에서 파일 생성·삭제, 늦게 끝나도 finally 정리합니다.
            def transcribe():
                if (cancel and cancel.is_set()) or paused():
                    raise InterruptedError('SPEECH_CHECK_CANCELED')
                with tempfile.TemporaryDirectory(prefix='ready2go_voice_') as directory:
                    path = Path(directory) / 'speech.wav'
                    write_wav(path, recording, self.cfg['sample_rate'])
                    return self.stt.transcribe(path, timeout)
            self.progress(event='whisper_requested')
            text = self.stt_calls.call(transcribe, timeout)
            self.progress(event='stt_result', text=text)
            doc = self.parser.parse(text, None if commissioning else deadline - self.cfg['tts_reserve_sec'])
        except Exception as exc:
            if not held:
                self.progress(event='stt_failed', error_type=type(exc).__name__)
            doc = intent('clarify', question=self.cfg['clarify_prompts']['no_speech' if held == 'NO_SPEECH' else 'audio_failure'])
            doc['source'] = {'stt_text': '', 'llm_called': False,
                             'llm_validation': 'not_called', 'fallback_used': False, 'execution_allowed': False}
            doc['source']['record_error' if held else 'stt_error'] = held or type(exc).__name__
        doc['source'].update(input_kind='audio', speech_ended_unix=recording.ended_unix,
                             speech_ended_monotonic=recording.ended_monotonic,
                             recording_mode=recording.recording_mode, timing_mode=self.cfg.get('timing_mode', 'ac_budget'),
                             recording_ended_monotonic=recording.recording_ended_monotonic,
                             recording_ended_unix=recording.recording_ended_unix,
                             latency_measurement='not_measured' if commissioning else 'estimated_speech_end',
                             confirmation_latency_ms=None)
        return doc

    def _fingerprint(self, doc):
        return (doc['intent'], tuple(doc.get('targets', [])), doc['source'].get('stt_text', ''))

    def is_duplicate(self, doc):
        """조회만 수행합니다. 호출자는 발행 성공 뒤 별도로 기록해야 합니다."""
        if self.cfg['evaluation_mode'] or doc['intent'] in ('cancel', 'status'):
            return False
        return bool(self._last and self._last[0] == self._fingerprint(doc)
                    and self.clock() - self._last[1] < self.cfg['duplicate_window_sec'])

    def should_publish(self, doc):
        """평가 모드는 모든 발행 금지. 조회로 요청을 소비하지 않습니다."""
        if doc['source'].get('record_error') in ('NO_SPEECH', 'SPEECH_CHECK_CANCELED', 'VAD_UNAVAILABLE_OR_FAILED'):
            return False
        return not self.cfg['evaluation_mode'] and not self.is_duplicate(doc)

    def mark_published(self, doc):
        """실제 발행 호출 성공 뒤에만 확정합니다. 노드는 submit_lock에서 호출합니다."""
        if not self.cfg['evaluation_mode'] and doc['intent'] not in ('cancel', 'status'):
            self._last = (self._fingerprint(doc), self.clock())
