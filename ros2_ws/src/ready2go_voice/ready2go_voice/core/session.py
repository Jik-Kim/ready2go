"""대화 처리와 평가 게이트. 로봇 동작·실행 상태 저장은 하지 않습니다."""
from pathlib import Path
from .stt_error import error_info, error_prompts, PROMPT_KEYS
import tempfile
import time
from .deadline import DeadlineCall
from .intent import intent
from .response import question
from .conversation import Conversation
from .flow import settings as flow_settings, blocked_prompt
import uuid
from collections import deque
from copy import deepcopy


class VoiceSession:
    def __init__(self, parser, cfg, stt=None, clock=time.monotonic, progress=lambda **event: None, speech_gate=None):
        self.parser, self.cfg, self.stt, self.clock = parser, cfg, stt, clock
        self.flow = cfg.get('voice_flow') or flow_settings(cfg)
        cfg['voice_flow'] = self.flow
        self.progress = progress
        self.speech_gate = speech_gate
        self.stt_calls = DeadlineCall()
        self.stop_stt_calls = DeadlineCall()  # 일반 STT/LLM 작업 종료를 기다리지 않습니다.
        self._last = None
        self._acceptance = None
        self.conversation = Conversation(cfg, clock)
        self._published_questions = deque(maxlen=cfg.get("tts_prefill_max_texts", 256))

    def text(self, text, generation=0, blocked=False, deadline=None, request_id=None, *, preserve_empty=False, runner_state=None):
        self._acceptance = None  # 새 요청은 이전 내부 문장의 소비 권한을 폐기합니다.
        from .recovery_confirmation import safety_utterance, task_end_utterance
        from .hotfix import prompts
        control = safety_utterance(text)
        ending = task_end_utterance(text)
        if control in ('recover','resume','new_start') or ending:
            self.conversation.invalidate()
            doc = intent('unknown')
            final_text = prompts(self.cfg)['no_end_work' if ending else 'no_work']
            if ending and runner_state != 'idle':
                final_text = self.flow['status_prompts']['unconfirmed']
            doc['_voice'] = {'safety_control': 'task_end' if ending else control, 'final_text': final_text}
            doc['source'] = {'stt_text':text, 'input_kind':'text', 'llm_called':False, 'llm_validation':'not_called', 'fallback_used':False, 'execution_allowed':False}
            return doc
        previous = self.conversation.pending
        effective, qid, target = self.conversation.resolve(text, self.parser, generation, blocked, preserve_empty=preserve_empty)
        epoch = self.conversation.epoch
        context = {'target': target, 'reply': text, 'question_id': qid,
                   'question': question(self.parser.items[target]['name_ko'])} if qid else None
        doc = self.parser.parse(effective, deadline, context=context)
        if qid and doc['intent'] == 'find_item' and not self.conversation.consume(previous, generation):
            doc.update(intent='clarify', targets=[], clarify_question=self.cfg['clarify_prompts']['missing_item'])
            doc['source']['execution_allowed'] = False
            doc['_voice'] = {'reason':'question_no_longer_current', 'final_text':doc['clarify_question']}
            qid = None
        elif qid and doc['intent'] != 'find_item':
            if doc['intent'] == 'clarify' and not doc['source'].get('llm_error') and self.conversation.pending is previous:
                doc.setdefault('_voice', {}).update(preserve_question_id=previous.id, original_question_expires=previous.expires)
            else:
                self.conversation.consume(previous, generation)
        # Public correlation fields come from E, never from an LLM candidate.
        doc.pop('request_id', None)
        doc.pop('accept_text', None)
        doc['source']['stt_text'] = text
        meta = doc.setdefault('_voice', {})
        meta['request_id'] = request_id or uuid.uuid4().hex
        meta['request_epoch'] = epoch
        if qid:
            meta.update(context_answer=doc['intent'] == 'find_item', question_id=qid, question_expires=previous.expires, context_generation=generation, context_epoch=previous.epoch,
                        effective_text=effective)
        if preserve_empty and previous is not None and self.conversation.pending is previous:
            meta.update(preserve_question_id=previous.id, original_question_expires=previous.expires,
                        final_text=self.flow['empty_reply_prompt'])
            doc['clarify_question'] = meta['final_text']
        if blocked and doc['intent'] in ('find_item','clarify'):
            meta['original_interpretation'] = {k: deepcopy(doc[k]) for k in ('intent','targets','goals','confidence') if k in doc}
            meta['original_final_text'] = meta.get('final_text')
            doc.update(intent='clarify', targets=[], clarify_question=blocked_prompt(self.cfg, runner_state))
            meta.pop('question_target', None); meta.pop('asks_delivery_target', None)
            meta.update(reason='runner_busy_or_locked', execution_hold_reason='runner_busy_or_locked',
                        final_text=doc['clarify_question'])
            doc['source']['execution_allowed'] = False
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
        """현재 요청의 검증 문장을 보관합니다. C 수락은 status에서 별도 확인합니다."""
        self._acceptance = None
        meta = doc.get('_voice', {})
        goal = doc.get('intent') == 'achieve_goal'
        if goal:
            try:
                self.parser._validate_goal(doc, doc.get('source', {}).get('stt_text', ''))
            except Exception:
                return
        if (doc.get('intent') not in ('find_item', 'achieve_goal')
                or not goal and (len(doc.get('targets', [])) != 1 or doc['targets'][0] not in self.parser.items)
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

        Called under the node submit_lock with the actual queue identity. Opt-in
        delivery publishes this candidate after registering local correlation. This
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

    def audio(self, recording, cancel=None, paused=lambda: False, generation=0, blocked=False, request_id=None, runner_state=None):
        self._acceptance = None
        local_request_id = request_id or uuid.uuid4().hex
        from ..adapters.audio import write_wav
        from .signal import prepare
        original_recording = recording
        held = None
        try:
            recording = prepare(recording, self.cfg, local_request_id, self.progress)
        except Exception as exc:
            held = 'RECORD_PCM_FORMAT'
            self.progress(event='capture_invalid', error_type=type(exc).__name__)
        commissioning = self.cfg.get('timing_mode', 'ac_budget') == 'commissioning'
        if held is None and recording.recording_mode == 'fixed' and not recording.truncated:
            try:
                if self.speech_gate is None:
                    from ..adapters.speech import SpeechPresence
                    self.speech_gate = SpeechPresence(self.cfg)
                self.progress(event='speech_check_started')
                if not self.speech_gate.check(original_recording, cancel=cancel, paused=paused):
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
                            if (cancel and cancel.is_set()) or paused():
                                return False
                            self.progress(event='whisper_sdk_request', request_id=local_request_id,
                                          requested_monotonic=stamp)
                            return True  # P1 시각 증빙만. P2의10초창/사건 정책은 적용하지 않습니다.
                        def current_hint():
                            q = self.conversation.pending
                            if (self.flow['stt_context_hint_enabled'] and not blocked and q and q.target in self.parser.items
                                    and q.generation == generation and self.clock() < q.expires):
                                self.progress(event='stt_context_hint', request_id=local_request_id, question_id=q.id, target=q.target, applied=True)
                                return self.flow['stt_hint_template'].format(item=self.parser.items[q.target]['name_ko'])
                            return None
                        if getattr(self.stt, 'supports_context_hint', False):
                            return self.stt.transcribe(path, timeout, before_request=before_request, context_hint=current_hint)
                        return self.stt.transcribe(path, timeout, before_request=before_request)
                    return self.stt.transcribe(path, timeout)
            self.progress(event='whisper_requested')
            text = self.stt_calls.call(transcribe, timeout)
            self.progress(event='stt_result', text=text)
            doc = self.text(text, generation, blocked, None if commissioning else deadline - self.cfg['tts_reserve_sec'], request_id=local_request_id, preserve_empty=isinstance(text,str) and not text.strip(), runner_state=runner_state)
        except Exception as exc:
            self.conversation.invalidate()
            info = error_info(exc) if not held else None
            if not held:
                self.progress(event='stt_failed', error_type=type(exc).__name__, api_error=info)
            prompt = self.cfg['clarify_prompts']['no_speech' if held == 'NO_SPEECH' else 'audio_failure']
            if info and info['category'] in PROMPT_KEYS:
                try:
                    prompt = error_prompts(self.cfg)[info['category']]
                except Exception as prompt_exc:
                    # 불완전한 raw cfg/패키지 배치도 기존 오류 안내로 안전하게 보류합니다.
                    self.progress(event='stt_prompt_unavailable', error_type=type(prompt_exc).__name__)
            doc = intent('clarify', question=prompt)
            if info is not None:
                doc['_voice'] = {'stt_failure': info, 'final_text': prompt}
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

    def _control_capture(self, recording, kind):
        """안전 입력의 원음 증빙만 기존 opt-in 경로에 저장합니다. trim/VAD/재사용 없음."""
        from .signal import prepare
        ident = kind + '_' + uuid.uuid4().hex
        def emit(**data):
            self.progress(**dict(data, control_capture_id=ident, capture_kind=kind))
        cfg = dict(self.cfg, voice_flow=dict(self.flow, capture_trim=False))
        try:
            prepare(recording, cfg, ident, emit)
        except Exception as exc:
            emit(event='capture_invalid', error_type=type(exc).__name__)
        return emit

    def stop_audio(self, recording, *, paused=lambda: False, spoken_texts=()):
        """새 무음 종료 녹음의 좁은 정지 판별. LLM·대화 문맥·일반 STT 슬롯은 사용하지 않습니다."""
        from ..adapters.audio import write_wav
        from .recovery_confirmation import finite, safety_utterance, task_end_utterance
        emit = self._control_capture(recording, 'stop')
        start, end = recording.recording_started_monotonic, recording.recording_ended_monotonic
        if (paused() or recording.truncated or not recording.pcm
                or recording.recording_mode != 'silence' or self.stt is None
                or not all(finite(t) for t in (start, end)) or not start <= end <= self.clock()):
            emit(event='stop_audio_held', reason='capture_unconfirmed')
            return None
        timeout = self.cfg['stt_timeout_sec']
        try:
            def transcribe():
                if paused():
                    raise InterruptedError('STOP_CANCELED')
                with tempfile.TemporaryDirectory(prefix='ready2go_stop_') as directory:
                    path = Path(directory) / 'speech.wav'
                    write_wav(path, recording, self.cfg['sample_rate'])
                    if getattr(self.stt, 'supports_request_boundary', False):
                        def before_request(stamp):
                            if paused():
                                return False
                            emit(event='stop_sdk_request', requested_monotonic=stamp)
                            return True
                        extra = {'control': True} if getattr(self.stt, 'supports_control_hint', False) else {}
                        return self.stt.transcribe(path, timeout, before_request=before_request, **extra)
                    return self.stt.transcribe(path, timeout)
            text = self.stop_stt_calls.call(transcribe, timeout)
            emit(event='stop_sdk_result', result_monotonic=self.clock(), empty=not isinstance(text,str) or not text.strip())
            if not isinstance(text,str) or not text.strip():
                emit(event='stop_audio_held', reason='empty_transcript')
                return None
            # 기존 정확 문구 분류는 부정·인용·전언·모호 표현을 수용하지 않습니다.
            normalized_control = self.parser.control(text) if self.parser is not None else None
            emit(event='stop_stt_result', text=text)
            ending = task_end_utterance(text)
            if paused() or not (ending or safety_utterance(text) == 'stop' or normalized_control and normalized_control['intent'] == 'cancel'):
                emit(event='stop_audio_held', reason='canceled' if paused() else 'not_explicit_stop')
                return None
            normalized = ''.join(text.split()).rstrip('.!?')
            if any(normalized in ''.join(reference.split()) for reference in spoken_texts):
                emit(event='stop_audio_held', reason='overlapping_self_speech')
                return None
            doc = intent('cancel')
            if ending:
                doc['_voice'] = {'safety_control':'task_end'}  # E 내부 라우팅만; 공개 종료 enum 아님
            doc['source'] = dict(input_kind='audio', stt_text=text, execution_allowed=False,
                                 llm_called=False, fallback_used=False)
            return doc
        except Exception as exc:
            emit(event='stop_audio_held', reason=type(exc).__name__, api_error=error_info(exc))
            return None  # 네트워크 실패/늦은 결과는 로봇 정지 완료 증거가 아닙니다.

    def confirm_audio(self, exchange, envelope, recording, *, cancel=None, paused=lambda: False):
        """Independent #43 STT/classification, no LLM or publication.

        The caller must connect authentic C registration and real TTS completion.
        Results are E exchange candidates, never C effects/final confirmation.
        """
        from ..adapters.audio import write_wav
        from .recovery_confirmation import finite
        capture = exchange.reserve_audio(envelope)
        if capture is None:
            return None  # duplicate/old audio must not invalidate an active capture.

        def interrupted():
            return (cancel is not None and cancel.is_set()) or paused()

        try:
            if interrupted():
                raise InterruptedError('CONFIRM_CANCELED')
            start, end = recording.recording_started_monotonic, recording.recording_ended_monotonic
            if (recording.truncated or not recording.pcm or not all(finite(t) for t in (start, end))
                    or not exchange.policy.finished_at <= start <= end
                    or self.stt is None or not getattr(self.stt, 'supports_request_boundary', False)):
                raise ValueError('CONFIRM_AUDIO_UNCONFIRMED')
            if recording.recording_mode == 'fixed':
                if self.speech_gate is None:
                    from ..adapters.speech import SpeechPresence
                    self.speech_gate = SpeechPresence(self.cfg)
                if not self.speech_gate.check(recording, cancel=cancel, paused=paused):
                    raise ValueError('NO_SPEECH')
            budget = exchange.audio_budget(envelope, now=self.clock())
            if budget is None or budget <= 0:
                raise TimeoutError('CONFIRM_EXPIRED')
            def transcribe():
                if interrupted() or not exchange.current(envelope):
                    raise InterruptedError('CONFIRM_CANCELED')
                with tempfile.TemporaryDirectory(prefix='ready2go_confirm_') as directory:
                    path = Path(directory) / 'speech.wav'
                    write_wav(path, recording, self.cfg['sample_rate'])
                    receipt = None
                    def before_request(stamp):
                        nonlocal receipt
                        if interrupted() or not exchange.current(envelope):
                            return False
                        receipt = exchange.admit(envelope, capture, captured_at=start,
                                                 ended_at=end, started_at=stamp)
                        if receipt is not None:
                            self.progress(event='confirm_sdk_request', question_id=envelope.question_id,
                                          requested_monotonic=stamp)
                        return receipt is not None
                    text = self.stt.transcribe(path, exchange.policy.stt_result_timeout_sec,
                                               before_request=before_request)
                    return text, receipt
            text, receipt = self.stt_calls.call(transcribe, budget)
            if interrupted():
                raise InterruptedError('CONFIRM_CANCELED')
            if not isinstance(text, str) or not text.strip():
                raise ValueError('NO_SPEECH')
            if receipt is None:
                raise ValueError('CONFIRM_REQUEST_UNCONFIRMED')
            from .recovery_confirmation import safety_utterance
            control = self.parser.control(text) if self.parser is not None else None
            if safety_utterance(text) == 'stop' or control and control['intent'] == 'cancel':
                from .place_exchange import PlaceReply
                exchange.invalidate()
                control = intent('cancel')
                control['source'] = dict(input_kind='audio', stt_text=text, execution_allowed=False,
                                         llm_called=False, fallback_used=False)
                return PlaceReply(control)
            return exchange.answer(envelope, text, captured_at=start, now=self.clock(), request=receipt)
        except InterruptedError:
            if exchange.current(envelope):
                exchange.invalidate()
            return None  # halt/cancel never becomes a yes/expired response.
        except Exception as exc:
            if interrupted():
                if exchange.current(envelope):
                    exchange.invalidate()
                return None
            self.progress(event='confirm_audio_failed', question_id=envelope.question_id,
                          error_type=type(exc).__name__, api_error=error_info(exc))
            return exchange.fail(envelope, answer='expired' if isinstance(exc, TimeoutError) else 'error')

    def safety_audio(self, exchange, target, recording, *, cancel=None, paused=lambda: False, on_failure=None):
        """현재 질문/새 독립 요청의 STT. 결과는 내부 후보이며 재개 wire가 아닙니다."""
        from ..adapters.audio import write_wav
        from .recovery_confirmation import finite, safety_utterance, task_end_utterance
        emit = self._control_capture(recording, 'safety')
        capture = exchange.reserve(target)
        if capture is None:
            emit(event='safety_audio_held', reason='capture_not_current_or_already_reserved')
            return None
        stage = 'capture_validation'
        interrupted = lambda: (cancel is not None and cancel.is_set()) or paused()
        try:
            start, end = recording.recording_started_monotonic, recording.recording_ended_monotonic
            if (interrupted() or recording.truncated or not recording.pcm
                    or not all(finite(t) for t in (start, end)) or start > end
                    or self.stt is None or not getattr(self.stt, 'supports_request_boundary', False)):
                raise ValueError('SAFETY_AUDIO_UNCONFIRMED')
            if recording.recording_mode == 'fixed':
                stage = 'speech_check'
                if self.speech_gate is None:
                    from ..adapters.speech import SpeechPresence
                    self.speech_gate = SpeechPresence(self.cfg)
                if not self.speech_gate.check(recording, cancel=cancel, paused=paused):
                    raise ValueError('NO_SPEECH')
            stage = 'admission'
            budget = exchange.budget(target, now=self.clock(), captured_at=start)
            if budget is None or budget <= 0:
                raise TimeoutError('SAFETY_EXPIRED')
            def transcribe():
                if interrupted() or not exchange.current(target):
                    raise InterruptedError('SAFETY_CANCELED')
                with tempfile.TemporaryDirectory(prefix='ready2go_safety_') as directory:
                    path = Path(directory) / 'speech.wav'
                    write_wav(path, recording, self.cfg['sample_rate'])
                    receipt = None
                    def before_request(stamp):
                        nonlocal receipt
                        if interrupted() or not exchange.current(target):
                            return False
                        receipt = exchange.admit(target, capture, captured_at=start, ended_at=end, started_at=stamp)
                        if receipt is not None:
                            emit(event='safety_sdk_request', requested_monotonic=stamp)
                        return receipt is not None
                    extra = {'control': True} if getattr(self.stt, 'supports_control_hint', False) else {}
                    text = self.stt.transcribe(path, exchange.policy.stt_result_timeout_sec,
                                               before_request=before_request, **extra)
                    return text, receipt, self.clock()  # actual normal SDK return, before classification
            stage = 'sdk'
            text, receipt, result_at = self.stt_calls.call(transcribe, budget)
            emit(event='safety_sdk_result', result_monotonic=result_at, empty=not isinstance(text,str) or not text.strip(), request_admitted=receipt is not None)
            if interrupted() or not exchange.current(target):
                raise InterruptedError('SAFETY_CANCELED')
            emit(event='safety_stt_result', text=text if isinstance(text,str) else '', result_monotonic=self.clock())
            if receipt is None:
                raise ValueError('SAFETY_STT_UNCONFIRMED')
            if not isinstance(text,str) or not text.strip():
                raise ValueError('NO_SPEECH')
            stage = 'classification'
            control = self.parser.control(text) if self.parser is not None else None
            if not task_end_utterance(text) and (safety_utterance(text) == 'stop' or control and control['intent'] == 'cancel'):
                exchange.cancel()
                doc = intent('cancel')
                doc['source'] = dict(input_kind='audio', stt_text=text, execution_allowed=False,
                                     llm_called=False, fallback_used=False)
                return doc
            current = exchange.current(target)
            result = exchange.answer(target, text, captured_at=start, now=self.clock(), request=receipt, result_at=result_at)
            if result is None:
                exchange.fail(target)  # 현재 요청만 정리; work와 새 사건은 보존합니다.
                if current and not interrupted() and on_failure is not None:
                    on_failure(exchange.last_rejection_reason or 'unrecognized_or_conditions_not_met')
                emit(event='safety_audio_held', reason=exchange.last_rejection_reason or 'unrecognized_or_conditions_not_met', stage=stage)
            else:
                emit(event='safety_audio_result', candidate_type=type(result).__name__)
            return result
        except Exception as exc:
            current = exchange.current(target)
            exchange.fail(target)
            allowed = {'SAFETY_AUDIO_UNCONFIRMED','NO_SPEECH','SAFETY_EXPIRED','SAFETY_CANCELED','SAFETY_STT_UNCONFIRMED','STT_REQUEST_NOT_ADMITTED','VAD_PCM_FORMAT','VAD_UNAVAILABLE','VAD_FAILED','SPEECH_CHECK_CANCELED','예산 소진','이전 호출 정리 중','호출 시간 초과'}
            reason = str(exc) if str(exc) in allowed else type(exc).__name__
            emit(event='safety_audio_failed', reason=reason, stage=stage, error_type=type(exc).__name__, api_error=error_info(exc))
            if current and not interrupted() and on_failure is not None:
                on_failure(reason)
            return None

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
            # Node additionally requires a verified current C connection before sending.
            if not self.cfg.get('p2_goal_enabled') or not self.cfg.get('request_run_enabled'):
                return False
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
