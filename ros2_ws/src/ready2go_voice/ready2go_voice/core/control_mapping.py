"""Opt-in E W3/W4 mapping. No ROS, C clock comparison, unlock or robot command.

The caller serializes receive/send with its submission lock. A verified producer
binding is required independently of JSON/ROS metadata. Public offered/needs and
B success/empty are never robot evidence. Missing typed proof holds recovery TTS.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import uuid
from jsonschema import Draft7Validator
from .recovery_confirmation import (Evidence, IndependentRequest, Question,
    StoppedWork, TaskEndCandidate, finite)
from .safety_exchange import RecoveryRequest


def identity(value):
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class SafetyProof:
    """Trusted adapter output for exactly one status; deadline uses Voice clock.

    The adapter must establish B/C safety/freshness and clock validity itself.
    This type does not verify observations or turn internal mock flags into proof.
    """
    work: StoppedWork
    revision: int
    evidence: Evidence
    valid_until: float


class ControlMapper:
    def __init__(self, *, boot, publisher_gid, source_check, enabled, schema,
                 clock, cfg, publish, exchange, proof_provider=None):
        if not identity(boot) or not callable(source_check):
            raise ValueError('verified current producer binding required')
        if not isinstance(publisher_gid, bytes) or not publisher_gid or not any(publisher_gid):
            raise ValueError('verified nonzero ROS publisher GID required')
        self.boot, self.publisher_gid = boot, publisher_gid
        self.source_check, self.enabled, self.clock = source_check, enabled, clock
        self.cfg, self.publish, self.exchange = cfg, publish, exchange
        self.validator = Draft7Validator(deepcopy(schema))
        self.proof_provider = proof_provider
        self.binding_valid = True
        self.seq = -1
        self.status = self.work = self.proof = None
        self.same_work = False
        self.question = self.independent = None
        self.pending = None
        self.sent = set()
        self.closed_questions = set()
        self.reason = None
        self.publishing = None

    def connected(self):
        try:
            return self.binding_valid and self.enabled() is True and self.source_check() is True
        except Exception:
            return False

    def invalidate(self):
        self.work = self.proof = self.status = None
        self.question = self.independent = self.pending = None
        self.exchange.cancel()
        if self.exchange.policy is not None:
            self.exchange.policy.current_state_confirmed = False

    def accept(self, raw, publisher_gid):
        """Only increasing status from the bound current source reaches E policies."""
        self.reason = None
        if not self.connected():
            self.invalidate()
            self.reason = 'source_unconfirmed'
            return False
        if publisher_gid != self.publisher_gid:
            self.reason = 'publisher_not_bound'
            return False
        try:
            doc = json.loads(raw) if isinstance(raw, str) else deepcopy(raw)
        except (ValueError, TypeError, RecursionError):
            self.reason = 'invalid_status'
            return False
        if isinstance(doc, dict) and doc.get('boot_id') != self.boot:
            self.binding_valid = False
            self.invalidate()
            self.reason = 'producer_boot_changed'
            return False
        if (not isinstance(doc, dict) or doc.get('boot_id') != self.boot
                or type(doc.get('seq')) is not int or doc['seq'] < 0
                or doc['seq'] <= self.seq):
            self.reason = 'boot_or_sequence_not_current'
            return False
        # Consume the ordering boundary before inspecting newer semantic conflicts.
        self.seq = doc['seq']
        halt, last = doc.get('halt'), doc.get('last')
        valid = (doc.get('phase') in ('idle', 'running', 'halted')
            and 'halt' in doc and (last is None or isinstance(last, dict))
            and (doc.get('last_intent') is None or isinstance(doc['last_intent'], dict)))
        if halt is not None:
            valid = valid and isinstance(halt, dict)
            if valid:
                resume = halt.get('resume')
                valid = (halt.get('boot_id') == self.boot and identity(halt.get('event_id'))
                    and (halt.get('run_id') is None or identity(halt['run_id']))
                    and halt.get('stop') in ('requested', 'confirmed', 'unconfirmed', 'none')
                    and type(halt.get('locked')) is bool and 'resume' in halt
                    and (resume is None or isinstance(resume, dict)))
                if valid and resume is not None:
                    valid = (type(resume.get('offered')) is bool and identity(resume.get('from_step'))
                        and all(resume.get(k) is None or isinstance(resume[k], dict) for k in ('question','request'))
                        and all(resume.get(k) is None or (identity(resume[k].get('id'))
                            and identity(resume[k].get('state'))) for k in ('question','request')))
        if not valid:
            self.invalidate()
            self.reason = 'invalid_current_status'
            return False
        old = self.work
        work = None
        if halt is not None and identity(halt.get('run_id')):
            resume = halt.get('resume')
            step = resume.get('from_step') if resume else None
            if not step and isinstance(last, dict) and last.get('run_id') == halt['run_id']:
                step = last.get('failed_step')
            if identity(step) and identity(halt.get('code')):
                work = StoppedWork(self.boot, halt['event_id'], halt['run_id'], step, halt['code'])
        self.same_work = (old is not None and old == work and self.status is not None
                          and self.status.get('phase') == doc.get('phase'))
        if old != work:
            self.question = self.independent = self.pending = None
            self.exchange.cancel()
        self.work, self.status, self.proof = work, doc, None
        if work is not None and halt['stop'] in ('confirmed', 'none') and callable(self.proof_provider):
            try:
                proof = self.proof_provider(deepcopy(doc), work, self.clock())
                if (isinstance(proof, SafetyProof) and proof.work == work and proof.revision == self.seq
                        and isinstance(proof.evidence, Evidence) and proof.evidence.verified()
                        and finite(proof.valid_until) and proof.valid_until > self.clock()):
                    self.proof = proof
            except Exception:
                self.reason = 'proof_provider_failed'
        return True

    def evidence(self):
        if self.proof is not None and self.clock() < self.proof.valid_until:
            return self.proof.evidence
        halt = (self.status or {}).get('halt') or {}
        return Evidence(stopped=halt.get('stop') == 'confirmed')

    def dispatch(self, node):
        """Called after legacy notice observation, under the same Node lock."""
        work, doc = self.work, self.status
        halt = doc.get('halt') or {}
        evidence = self.evidence()
        if work is None or not evidence.stopped:
            ending = getattr(node, 'task_end_request', None)
            awaiting = (ending is not None and ending['generation'] == node.generation
                and ending['boot'] == self.boot and ending['run'] == halt.get('run_id')
                and halt.get('stop') == 'requested' and node._task_end_source_current())
            node._cancel_safety_locked()
            if self.exchange.policy is not None:
                self.exchange.policy.current_state_confirmed = False
            if awaiting:
                # Stop requested is not confirmation. Preserve only the pinned
                # END intention while awaiting this run's backend stop result.
                node.task_end_request = node.task_end_source = ending
            return
        resume = halt.get('resume')
        if self.exchange.policy is not None and self.exchange.policy.question is not None and not evidence.verified():
            node._cancel_safety_locked()
        if not node.safety_stopped(work, self.seq, valid_state=True, evidence=evidence):
            return
        if resume is not None:
            q = resume.get('question') or {}; r = resume.get('request') or {}
            if self.question is not None and q.get('id') == self.question.question_id and q.get('state') == 'registered':
                node.safety_registered(self.question, work, self.seq, valid_state=True)
            if self.independent is not None and r.get('id') == self.independent.request_id and r.get('state') == 'registered':
                target = self.independent
                self.independent = None  # ACK consumed once, before callback may publish
                node.safety_independent_registered(target, work, self.seq, valid_state=True, evidence=evidence)
            if (resume.get('offered') is True and halt['locked'] is False and self.proof is not None and evidence.verified()
                    and self.exchange.policy.question is None and self.exchange.policy.independent is None):
                node.safety_offer(work, self.seq, evidence, valid_state=True, valid_until=self.proof.valid_until)
        # END decision alone is only admission. Require current stopped run,
        # explicit no preserved resume, terminal ABORTED and this E request echo.
        pending = self.pending
        decision = doc.get('last_intent') or {}; last = doc.get('last') or {}
        if (pending is not None and pending[0] == 'end_task' and pending[2].work == work
                and decision.get('intent') == 'end_task' and decision.get('decision') == 'end'
                and decision.get('request_id') == pending[1] and resume is None
                and last.get('run_id') == work.task and last.get('overall_status') == 'ABORTED'):
            node.safety_feedback(work, 'end', candidate=pending[2])
        elif (pending is not None and pending[0] in ('resume','resume_answer') and resume is not None):
            key, expected = ('request', pending[1]) if pending[0] == 'resume' else ('question', pending[1])
            echo = resume.get(key) or {}
            if echo.get('id') == expected and echo.get('state') == 'resumed' and evidence.verified():
                node.safety_feedback(work, 'resume', candidate=pending[2])

    def _context(self, value):
        last = self.exchange.last_candidate
        matches = last is value or isinstance(last, RecoveryRequest) and last.work is value
        return self.exchange.last_context if matches else None

    def _timely(self, context, now):
        if context is None or not all(finite(v) for v in (now, context.captured_at,
                context.ended_at, context.started_at, context.result_at, context.classified_at)):
            return False
        if not context.captured_at <= context.ended_at <= context.started_at <= context.result_at <= context.classified_at <= now:
            return False
        if context.result_at - context.started_at > self.cfg['resume_stt_result_timeout_sec']:
            return False
        target = context.target
        if target.work != self.work:
            return False
        if isinstance(target, IndependentRequest):
            return now - context.captured_at <= self.cfg['resume_independent_request_timeout_sec']
        return (isinstance(target, Question) and finite(context.tts_finished_at)
            and context.tts_finished_at <= context.captured_at
            and context.started_at - context.tts_finished_at <= self.cfg['resume_admission_window_sec']
            and now < target.valid_until)

    def publish_guard(self, payload):
        """Last check after Node serialization, immediately before ROS publish."""
        frame = self.publishing
        if frame is None or frame[0] is not payload or not self.connected() or frame[1] != self.work:
            return False
        context = frame[2]
        evidence = self.evidence()
        if not evidence.stopped:
            return False
        if payload['intent'] in ('resume_register','resume') or payload.get('answer') == 'resume':
            if not evidence.verified() and not (payload.get('phase') == 'register' and evidence.stopped):
                return False
        now = self.clock()
        return (context is None or self._timely(context, now)) and (
            payload['intent'] != 'resume_register' or now < frame[3].valid_until)

    def send(self, kind, value):
        """Map only current internal objects; validate + consume once before publish."""
        self.reason = None
        if not self.connected() or self.work is None or self.status is None:
            self.reason = 'source_or_work_unconfirmed'
            return False
        policy = self.exchange.policy
        if policy is None or policy.work != self.work or not policy.current_state_confirmed:
            self.reason = 'current_stop_unconfirmed'
            return False
        if kind == 'feedback_delivered':
            return False  # Node wrapper verifies terminal correlation/TTS below.
        work = getattr(value, 'work', value)
        if work != self.work:
            self.reason = 'work_not_current'
            return False
        payload = dict(confidence=1.0, boot_id=work.session, event_id=work.stop, run_id=work.task)
        context = self._context(value)
        target = context.target if context is not None else None
        key = (kind, target if context is not None else value)
        if kind == 'register_question' and isinstance(value, Question) and self.exchange.current(value):
            if value.mode != 'resume' or not self.evidence().verified() or self.clock() >= value.valid_until:
                return False
            payload.update(intent='resume_register', question_id=value.question_id)
        elif kind == 'register_independent' and isinstance(value, IndependentRequest) and self.exchange.current(value):
            context = self.exchange.last_context
            if context is None or context.target is not value:
                return False
            payload.update(intent='resume', phase='register', request_id=value.request_id)
        elif kind == 'declined' and isinstance(value, Question):
            context = self.exchange.last_context
            if context is None or context.target is not value:
                return False
            payload.update(intent='resume_answer', question_id=value.question_id, answer='decline')
        elif kind == 'expired' and isinstance(value, Question):
            echo = (self.status['halt'].get('resume') or {}).get('question') or {}
            if (self.question is not value or value in self.closed_questions
                    or echo.get('id') != value.question_id or echo.get('state') != 'registered'):
                return False
            context = None  # closure is not a resume/audio admission proof
            payload.update(intent='resume_answer', question_id=value.question_id, answer='expired',
                answer_reason='voice_question_closed_without_answer')
        elif kind == 'recover':
            payload.update(intent='recover', request_id=uuid.uuid4().hex)
        elif kind == 'candidate' and isinstance(value, TaskEndCandidate):
            payload.update(intent='end_task', request_id=uuid.uuid4().hex)
        elif kind == 'candidate' and isinstance(value, StoppedWork) and context is not None:
            if not self.evidence().verified():
                return False
            if isinstance(target, Question) and self.question is target:
                echo = (self.status['halt'].get('resume') or {}).get('question') or {}
                if echo.get('id') != target.question_id or echo.get('state') != 'registered':
                    return False
                payload.update(intent='resume_answer', question_id=target.question_id, answer='resume',
                    evidence=dict(rec_start_after_tts_s=context.captured_at-context.tts_finished_at,
                        rec_end_after_tts_s=context.ended_at-context.tts_finished_at,
                        request_after_tts_s=context.started_at-context.tts_finished_at,
                        stt_s=context.result_at-context.started_at))
            elif isinstance(target, IndependentRequest):
                echo = (self.status['halt'].get('resume') or {}).get('request') or {}
                if echo.get('id') != target.request_id or echo.get('state') != 'registered':
                    return False
                payload.update(intent='resume', phase='request', request_id=target.request_id,
                    evidence=dict(rec_end_s=context.ended_at-context.captured_at,
                        request_s=context.started_at-context.captured_at,
                        stt_s=context.result_at-context.started_at))
            else:
                return False
        else:
            self.reason = 'unsupported_internal_control'
            return False
        # Current installed public schema is authoritative. Main without W3
        # support blocks publication; tests inject an explicitly mock schema.
        try:
            self.validator.validate(payload)
        except Exception:
            self.reason = 'public_contract_unavailable'
            return False
        now = self.clock()
        if not self.evidence().stopped:
            self.reason = 'stop_not_confirmed'
            return False
        if kind == 'candidate' and isinstance(target, IndependentRequest) and payload['intent'] != 'end_task':
            echo = (self.status['halt'].get('resume') or {}).get('request') or {}
            if (echo.get('id') != target.request_id or echo.get('state') != 'registered'
                    or not finite(context.registered_at) or context.registered_at > now):
                self.reason = 'registration_not_current'
                return False
        if (key in self.sent or not self.connected() or work != self.work
                or context is not None and not self._timely(context, now)):
            self.reason = 'replayed_or_expired_control'
            return False
        if (payload['intent'] == 'resume' or payload['intent'] == 'resume_answer' and payload['answer'] == 'resume') and self.status['halt'].get('locked') is not False:
            self.reason = 'runner_still_locked'
            return False
        if (payload['intent'] in ('resume_register','resume') or payload['intent'] == 'resume_answer' and payload['answer'] == 'resume') and not self.evidence().verified():
            # Registration is not resume permission; consumption needs B/C proof.
            if not (kind == 'register_independent' and self.evidence().stopped):
                self.reason = 'recovery_evidence_unconfirmed'
                return False
        self.sent.add(key)  # no retry/replay even if transport raises
        if kind in ('declined','expired'):
            self.closed_questions.add(value)
        elif kind == 'candidate' and isinstance(target, Question):
            self.closed_questions.add(target)
        if kind == 'register_question':
            self.question = value
        elif kind == 'register_independent':
            self.independent = value
        elif kind == 'candidate':
            self.pending = (payload['intent'], payload.get('question_id', payload.get('request_id')), value)
        self.publishing = (payload, work, context, value)
        try:
            if not self.publish_guard(payload) or self.publish(payload) is False:
                self.reason = 'publish_boundary_unconfirmed_or_expired'
                if kind == 'candidate':
                    self.pending = None
                return False
            return True
        finally:
            self.publishing = None
