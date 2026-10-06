"""대화 처리와 평가 게이트. 로봇 동작·실행 상태 저장은 하지 않습니다."""
from pathlib import Path
import tempfile
import time
from .deadline import DeadlineCall
from .intent import intent


class VoiceSession:
    def __init__(self, parser, cfg, stt=None, clock=time.monotonic):
        self.parser, self.cfg, self.stt, self.clock = parser, cfg, stt, clock
        self.stt_calls = DeadlineCall()
        self._last = None

    def audio(self, recording):
        from ..adapters.audio import write_wav
        deadline = recording.ended_monotonic + self.cfg['confirmation_budget_sec']
        timeout = min(self.cfg['stt_timeout_sec'], deadline - self.clock() - self.cfg['tts_reserve_sec'])
        try:
            if recording.truncated or self.stt is None:
                raise ValueError('STT_UNAVAILABLE')
            # 디렉터리는 늦은 호출이 읽는 파일을 고려해 호출자/작업자가 나눠 소유하지 않음:
            # STT 작업자 안에서 파일 생성·삭제, 늦게 끝나도 finally 정리합니다.
            def transcribe():
                with tempfile.TemporaryDirectory(prefix='ready2go_voice_') as directory:
                    path = Path(directory) / 'speech.wav'
                    write_wav(path, recording, self.cfg['sample_rate'])
                    return self.stt.transcribe(path, timeout)
            text = self.stt_calls.call(transcribe, timeout)
            doc = self.parser.parse(text, deadline - self.cfg['tts_reserve_sec'])
        except Exception as exc:
            doc = intent('clarify', question='음성을 처리하지 못했습니다. 다시 말씀해 주세요.')
            doc['source'] = {'stt_text': '', 'stt_error': type(exc).__name__, 'llm_called': False,
                             'llm_validation': 'not_called', 'fallback_used': False, 'execution_allowed': False}
        doc['source'].update(input_kind='audio', speech_ended_unix=recording.ended_unix,
                             speech_ended_monotonic=recording.ended_monotonic)
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
        return not self.cfg['evaluation_mode'] and not self.is_duplicate(doc)

    def mark_published(self, doc):
        """실제 발행 호출 성공 뒤에만 확정합니다. 노드는 submit_lock에서 호출합니다."""
        if not self.cfg['evaluation_mode'] and doc['intent'] not in ('cancel', 'status'):
            self._last = (self._fingerprint(doc), self.clock())
