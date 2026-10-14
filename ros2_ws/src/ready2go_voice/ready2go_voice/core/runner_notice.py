"""Runner 상태의 읽기 전용 P1 음성 정책. 로봇 제어/상태 쓰기 없음."""
from dataclasses import dataclass
import json
from pathlib import Path
from .runner_speech import task_steps, failure_texts

STATUS_PROMPTS = {
    'estop': '비상정지가 보고됐어요. 로봇의 실제 정지와 상태를 확인해 주세요.',
    'dropped': '물품 놓침이 보고됐어요. 로봇의 실제 정지와 물품 상태를 확인해 주세요.',
    'sensor': '센서값 이상이 보고됐어요. 로봇의 실제 정지와 센서·물품 상태를 확인해 주세요.',
    'halted': '작업 중단이 요청됐어요. 상태를 확인해 주세요.',
    'unconfirmed': '로봇 상태를 확인할 수 없어요. 직접 확인해 주세요.',
    'timeout': '제한 시간 안에 작업을 완료하지 못했어요. 상태를 확인해 주세요.',
    'vision': '물품을 확인하지 못했어요. 카메라와 작업 공간을 확인해 주세요.',
    'grasp': '물품을 잡지 못했어요. 물품과 그리퍼 상태를 확인해 주세요.',
    'failure': '작업을 완료하지 못했어요. 상태를 확인해 주세요.',
}
# New cause wording comes from the same YAML prompts consumed by prefill.
from .hotfix import prompts as feedback_prompts
CAUSE_KINDS = ('camera', 'coordinates', 'region', 'interference', 'no_space', 'recovery', 'vision_timeout', 'restore', 'speech')
STATUS_PROMPTS.update({kind: feedback_prompts({})['notice_' + kind] for kind in CAUSE_KINDS})


def vision_steps(cfg, action='inspect_region'):
    """Only exact requested-action steps of the two current task definitions.

    Unknown/custom task definitions are not a reason to call TIMEOUT vision.
    """
    result = {}
    root = Path(cfg['ontology_file']).resolve().parent.parent / 'tasks'
    for name in ('find_item.json', 'find_with_unpack.json'):
        try:
            doc = json.loads((root / name).read_text())
            selected = set()
            def walk(value):
                if isinstance(value, dict):
                    if value.get('action') == action and isinstance(value.get('id'), str):
                        selected.add(value['id'])
                    for child in value.values(): walk(child)
                elif isinstance(value, list):
                    for child in value: walk(child)
            walk(doc)
            if isinstance(doc.get('task_id'), str): result[doc['task_id']] = selected
        except (OSError, ValueError, TypeError, RecursionError):
            continue
    return result

UNCONFIRMED = {'STOP_UNCONFIRMED', 'STATE_UNKNOWN', 'MOVE_UNCONFIRMED', 'LOCKED'}
# E-local classification only; never a Runner lock or a resume allowlist.
HALT_MOTION = frozenset({'OBJECT_DROPPED', 'ESTOP', 'SENSOR_INVALID', *UNCONFIRMED})
VISION_ERRORS = {'DEPTH_INVALID', 'RESULT_INVALID', 'UNKNOWN_REGION', 'STUB_NOT_READY'}


def warning_kind(code, *, halted=False, aborted=False, vision_step=False, speech_step=False):
    if code == 'ESTOP': return 'estop', 0
    if code in UNCONFIRMED: return 'unconfirmed', 1
    if code == 'OBJECT_DROPPED': return 'dropped', 1
    if code == 'SENSOR_INVALID': return 'sensor', 1
    if code in ('HALTED', 'CANCELED'): return 'halted', 2
    if halted or aborted: return 'unconfirmed', 1
    if code in ('TIMEOUT', 'LATE_RESULT'): return ('vision_timeout' if vision_step else 'timeout'), 3
    if code == 'CAMERA_TIMEOUT': return 'camera', 3
    if code in ('TF_UNAVAILABLE', 'DEPTH_INVALID'): return 'coordinates', 3
    if code == 'REGION_NOT_VISIBLE': return 'region', 3
    if code in ('WALL_TOO_CLOSE', 'NEIGHBOR_TOO_CLOSE'): return 'interference', 3
    if code == 'NO_FREE_SPACE': return 'no_space', 3
    if code == 'RESTORE_INCOMPLETE': return 'restore', 3
    if code in ('B_RECOVER_UNAVAILABLE', 'B_RECOVER_FAILED', 'B_CHECK_UNAVAILABLE'): return 'recovery', 3
    if code in VISION_ERRORS: return 'vision', 3
    if code == 'BACKEND_ERROR' and speech_step: return 'speech', 3
    if code == 'GRASP_FAILED': return 'grasp', 3
    return 'failure', 3


@dataclass(frozen=True)
class Notice:
    kind: str
    text: str
    priority: int
    revision: int
    generation: object = None
    guard: object = None


class RunnerNoticePolicy:
    def __init__(self, cfg=None):
        self.vision_steps = vision_steps(cfg) if cfg is not None else {}
        self.speech_steps = vision_steps(cfg, 'speak') if cfg is not None else {}
        self.task_steps = task_steps(cfg) if cfg is not None else {}
        self.failure_texts = failure_texts()
        self.prompts = dict(STATUS_PROMPTS)
        if cfg is not None:
            self.prompts.update({kind: feedback_prompts(cfg)['notice_' + kind] for kind in CAUSE_KINDS})
        self.initialized = False
        self.phase = None
        self.previous_halt = None
        self.active_task = None
        self.awaiting_result = False
        self.seen_runs = set()
        self.warned_priority = float('inf')
        self.warned_kind = None
        self.blocked = False  # 오래된 정상 음성만 억제; Runner/로봇 제어 게이트 아님.
        self.revision = 0

    def observe(self, raw, *, cause=None):
        try:
            doc = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError, RecursionError): return None
        if not isinstance(doc, dict) or doc.get('phase') not in ('idle', 'running', 'halted'): return None
        phase, code, last = doc['phase'], doc.get('halt_code'), doc.get('last')
        task = doc.get('task_id')
        if code is not None and not isinstance(code, str): return None
        if last is not None and not isinstance(last, dict): return None
        if phase == 'running' and (not isinstance(task, str) or not task): return None
        halt = code or ('STATE_UNKNOWN' if phase == 'halted' else None)
        run_id = last.get('run_id') if last else None
        if not isinstance(run_id, str) or not run_id: run_id = None
        if not self.initialized:
            self.initialized = True
            self.phase, self.previous_halt = phase, halt
            self.blocked = bool(halt)
            self.awaiting_result = phase == 'running'
            self.active_task = task
            if halt: self.warned_kind, self.warned_priority = warning_kind(halt, halted=True)
            if run_id: self.seen_runs.add(run_id)
            return None  # 첫 latched 상태/과거 결과는 재생하지 않음.
        if phase == 'running' and (self.phase != 'running' or task != self.active_task):
            self.active_task, self.awaiting_result = task, True
            self.warned_priority, self.blocked = float('inf'), False
            self.warned_kind = None
            self.revision += 1  # 이전 회차 대기/재생 경고를 무효화.
        if self.previous_halt and not halt:
            self.blocked, self.warned_priority = False, float('inf')
            self.warned_kind = None
            if phase != 'running': self.awaiting_result = False
            self.revision += 1
        candidates = [warning_kind(halt, halted=True)] if halt else []
        if run_id and run_id not in self.seen_runs:
            eligible = (phase != 'running' and self.awaiting_result
                        and last.get('task_id') == self.active_task)
            self.seen_runs.add(run_id)
            if eligible:
                self.awaiting_result = False
                outcome, error = last.get('overall_status'), last.get('error_code')
                if outcome in ('FAILED', 'ABORTED'):
                    warning = warning_kind(error if isinstance(error, str) else None,
                                                   aborted=outcome == 'ABORTED',
                                                   vision_step=isinstance(last.get('failed_step'), str) and last['failed_step'] in self.vision_steps.get(last.get('task_id'), set()),
                                                   speech_step=isinstance(last.get('failed_step'), str) and last['failed_step'] in self.speech_steps.get(last.get('task_id'), set()))
                    if not (outcome == 'FAILED' and warning[1] == 3
                            and isinstance(cause, tuple) and len(cause) == 3
                            and cause[:2] == (run_id, last.get('task_id'))
                            and cause[2] in self.failure_texts):
                        candidates.append(warning)
        self.phase, self.previous_halt = phase, halt
        self.blocked = bool(halt)
        if not candidates: return None
        kind, priority = min(candidates, key=lambda item: item[1])
        # A new cause at the same severity must replace the old cause's speech.
        # It still cannot downgrade ESTOP or infer physical stop/target evidence.
        changed_cause = (priority == self.warned_priority and kind != self.warned_kind
                         and kind in ('dropped', 'sensor', 'unconfirmed'))
        if priority >= self.warned_priority and not changed_cause: return None
        self.warned_kind, self.warned_priority = kind, priority
        self.revision += 1
        return Notice(kind, self.prompts[kind], priority, self.revision)
