"""대화 처리와 평가 게이트. 로봇 동작·실행 상태 저장은 하지 않습니다."""
from pathlib import Path
import tempfile
import time
from .deadline import DeadlineCall
from .intent import intent
from .conversation import Conversation
import uuid
from collections import deque
from copy import deepcopy


class VoiceSession:
    def __init__(self, parser, cfg, stt=None, clock=time.monotonic, progress=lambda **event: None, speech_gate=None):
        self.parser, self.cfg, self.stt, self.clock = parser, cfg, stt, clock
        self.progress = progress
        self.speech_gate = speech_gate
        self.stt_calls = DeadlineCall()
        self._last = None
        self._acceptance = None
        self.conversation = Conversation(cfg, clock)
        self._published_questions = deque(maxlen=cfg.get("tts_prefill_max_texts", 128))

    def text(self, text, generation=0, blocked=False, deadline=None, request_id=None):
        self._acceptance = None  # 새 요청은 이전 내부 문장의 소비 권한을 폐기합니다.
        previous = self.conversation.pending
        effective, qid, target = self.conversation.resolve(text, self.parser, generation, blocked)
        epoch = self.conversation.epoch
        doc = self.parser.parse(effective, deadline)
        # Public correlation fields come from E, never from an LLM candidate.
        doc.pop('request_id', None)
        doc.pop('accept_text', None)
        doc['source']['stt_text'] = text
        meta = doc.setdefault('_voice', {})
        meta['request_id'] = request_id or uuid.uuid4().hex
        meta['request_epoch'] = epoch
        if qid:
            meta.update(context_answer=True, question_id=qid, question_expires=previous.expires, context_generation=generation, context_epoch=previous.epoch,
                        effective_text=effective)
        if blocked and doc['intent'] == 'find_item':
            from .response import final_response
            doc.update(intent='clarify', targets=[], clarify_question=self.cfg['clarify_prompts']['general'])
            meta.pop('question_target', None)
            meta['reason'] = 'runner_busy_or_locked'
            doc['source']['execution_allowed'] = False
            final_response(self.parser, doc)
        self._prepare_acceptance(doc, generation)
        return doc

    @staticmethod
    def _acceptance_signature(doc):
        meta, source = doc.get('_voice', {}), doc.get('source', {})
        return deepcopy((doc.get('intent'), doc.get('targets'), doc.get('goals'), doc.get('confidence'),
            source.get('stt_text'), source.get('execution_allowed'),
            {key: meta.get(key) for key in ('request_id', 'request_epoch', 'final_text',
                'context_answer', 'context_generation', 'context_epoch', 'question_expires')}))

    def _prepare_acceptance(self, doc, generation):
        """기존 검증 문장을 E 메모리에만 보관합니다. C 수락/공개 전달은 미연결입니다."""
        self._acceptance = None
        meta = doc.get('_voice', {})
        if (doc.get('intent') != 'find_item' or len(doc.get('targets', [])) != 1
                or doc['targets'][0] not in self.parser.items
                or doc.get('source', {}).get('execution_allowed') is not True
                or not meta.get('request_id') or not self.valid_context(doc, generation)):
            return
        from .response import final_response
        # parser가 확정한 문장도 복사본에서 다시 검사하며 원본 진단을 덮지 않습니다.
        checked = deepcopy(doc)
        text = meta.get('final_text')
        if not isinstance(text, str) or final_response(self.parser, checked, text) != text:
            return
        self._acceptance = (doc, generation, self.conversation.epoch,
                            self._acceptance_signature(doc), text)

    def prepare_request_payload(self, doc, generation, *, request_id, blocked=False):
        """Prepare a detached contract07 candidate without publishing/consuming.

        Called under the node submit_lock with the actual queue identity. This
        grants neither C acceptance nor permission for TTS or robot motion.
        """
        pending = self._acceptance
        if (blocked or self.cfg['evaluation_mode'] or not isinstance(request_id, str)
                or not request_id.strip() or pending is None or pending[0] is not doc
                or pending[1] != generation or pending[2] != self.conversation.epoch
                or doc.get('_voice', {}).get('request_id') != request_id
                or not self.valid_context(doc, generation)
                or pending[3] != self._acceptance_signature(doc)
                or not self.should_publish(doc)):
            return None
        payload = deepcopy({key: value for key, value in doc.items()
                            if not key.startswith('_')})
        payload['request_id'], payload['accept_text'] = request_id, pending[4]
        return payload

    def consume_acceptance_text(self, doc, generation):
        """E 내부 일회성 조회. 반환은 C 수락·TTS 성공·첫 동작 허가를 증명하지 않습니다.

        TODO(E): 승인된 요청/run/boot/순서 계약과 실제 C 수락 핸들러 연결 후 사용.
        노드와 같은 submit_lock에서 호출해야 하며 현재 운영 소비 호출자는 없습니다.
        """
        pending = self._acceptance
        if pending is None or pending[0] is not doc:
            return None
        self._acceptance = None  # 유효성 실패를 포함해 같은 요청은 재시도하지 않습니다.
        if (pending[1] != generation or pending[2] != self.conversation.epoch
                or not self.valid_context(doc, generation)
                or pending[3] != self._acceptance_signature(doc)):
            return None
        return pending[4]

    def valid_context(self, doc, generation):
        meta = doc.get('_voice', {})
        if 'request_epoch' in meta and meta['request_epoch'] != self.conversation.epoch:
            return False
        return (not meta.get('context_answer') or
                (meta.get('context_generation') == generation and meta.get('context_epoch') == self.conversation.epoch and self.clock() < meta.get('question_expires', 0)))

    def audio(self, recording, cancel=None, paused=lambda: False, generation=0, blocked=False, request_id=None):
        self._acceptance = None
        local_request_id = request_id or uuid.uuid4().hex
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
                    if getattr(self.stt, 'supports_request_boundary', False):
                        def before_request(stamp):
                            self.progress(event='whisper_sdk_request', request_id=local_request_id,
                                          requested_monotonic=stamp)
                            return True  # P1 시각 증빙만. P2의10초창/사건 정책은 적용하지 않습니다.
                        return self.stt.transcribe(path, timeout, before_request=before_request)
                    return self.stt.transcribe(path, timeout)
            self.progress(event='whisper_requested')
            text = self.stt_calls.call(transcribe, timeout)
            self.progress(event='stt_result', text=text)
            doc = self.text(text, generation, blocked, None if commissioning else deadline - self.cfg['tts_reserve_sec'], request_id=local_request_id)
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
        doc.setdefault('_voice', {})['request_id'] = local_request_id
        doc['_voice']['recording_started_monotonic'] = recording.recording_started_monotonic
        doc['_voice']['recording_ended_monotonic'] = recording.recording_ended_monotonic
        return doc

    def _fingerprint(self, doc):
        return (doc['intent'], tuple(doc.get('targets', [])), doc.get('_voice', {}).get('question_id') or doc['source'].get('stt_text', ''))

    def is_duplicate(self, doc):
        """조회만 수행합니다. 호출자는 발행 성공 뒤 별도로 기록해야 합니다."""
        if self.cfg['evaluation_mode'] or doc['intent'] in ('cancel', 'status'):
            return False
        if doc.get('_voice', {}).get('question_id') in self._published_questions:
            return True
        return bool(self._last and self._last[0] == self._fingerprint(doc)
                    and self.clock() - self._last[1] < self.cfg['duplicate_window_sec'])

    def should_publish(self, doc):
        """평가 모드는 모든 발행 금지. 조회로 요청을 소비하지 않습니다."""
        if doc['intent'] == 'achieve_goal' or doc.get('_voice', {}).get('p2_goal_candidate'):
            return False  # phase-1 internal evaluation only, even when opt-in is true
        if doc['source'].get('record_error') in ('NO_SPEECH', 'SPEECH_CHECK_CANCELED', 'VAD_UNAVAILABLE_OR_FAILED'):
            return False
        return not self.cfg['evaluation_mode'] and not self.is_duplicate(doc)

    def mark_published(self, doc):
        """실제 발행 호출 성공 뒤에만 확정합니다. 노드는 submit_lock에서 호출합니다."""
        if not self.cfg['evaluation_mode'] and doc['intent'] not in ('cancel', 'status'):
            self._last = (self._fingerprint(doc), self.clock())
            qid = doc.get('_voice', {}).get('question_id')
            if qid and doc['intent'] == 'find_item' and doc.get('_voice', {}).get('context_answer'):
                self._published_questions.append(qid)
