"""현재 C 태스크/실패 문장 원본을 사용하는 E 읽기 전용 연결."""
import json
from pathlib import Path
from ready2go_runner.core import failure_speech
from ready2go_runner.core.variables import interpolate


def task_steps(cfg):
    root = Path(cfg['ontology_file']).resolve().parent.parent / 'tasks'
    if not root.is_dir():
        # Source invocation and installed ROS invocation use the same original
        # task files; setup.py installs these two originals without redefining them.
        source_root = Path(__file__).resolve().parents[5] / 'tasks'
        if source_root.is_dir():
            root = source_root
        else:
            from ament_index_python.packages import get_package_share_directory
            root = Path(get_package_share_directory('ready2go_voice')) / 'tasks'
    result = {}
    for name in ('find_item.json', 'find_with_unpack.json'):
        doc = json.loads((root / name).read_text())
        steps = {}
        def walk(value, in_finally=False):
            if isinstance(value, dict):
                if isinstance(value.get('id'), str) and (
                        isinstance(value.get('action'), str) or isinstance(value.get('skill'), str)):
                    step = dict(value, _in_finally=in_finally)
                    step.setdefault('action', 'skill')
                    steps[value['id']] = step
                for key, child in value.items(): walk(child, in_finally or key == 'finally')
            elif isinstance(value, list):
                for child in value: walk(child, in_finally)
        walk(doc)
        result[doc['task_id']] = steps
    return result


def unavailable_work_text(status, steps, prompts, *, operation='resume', recovered=False, run_id=None):
    """검증된 C 상태에서 재개 불가 사유만 안내한다. 실행·상태는 변경하지 않는다."""
    if (not isinstance(status, dict) or status.get('phase') != 'idle'
            or 'halt' not in status or status['halt'] is not None):
        return None
    last = status.get('last') or {}
    if not isinstance(last, dict) or last.get('overall_status') == 'SUSPENDED':
        return None
    if run_id is not None and last.get('run_id') != run_id:
        return None
    if not recovered and operation == 'recover':
        return prompts['runtime_no_recover_work']
    if not recovered and operation != 'resume':
        return None
    prefix = 'runtime_recover_' if recovered else 'runtime_resume_'
    failed = last.get('failed_step')
    task_id = last.get('task_id')
    task = steps.get(task_id, {}) if isinstance(task_id, str) else {}
    matches = [key for key in task if isinstance(failed, str)
               and (failed == key or failed.startswith(key + '.e'))]
    step = task[max(matches, key=len)] if matches else {}
    if last.get('overall_status') == 'ABORTED' and step.get('_in_finally') is True:
        close = (step.get('skill') == 'close_drawer' or
                 step.get('action') == 'drawer_control' and step.get('params', {}).get('state') == 'close')
        return prompts[prefix + ('finally_close' if close else 'finally')]
    return prompts[prefix + 'no_work']


def failure_texts():
    return set(filter(None, [failure_speech.text(code, action)
        for code in (*failure_speech.BY_CODE, 'TIMEOUT', None)
        for action in (*failure_speech.ACTION_KO, None)]))


def refusal_answer(status):
    """Read only the latest accepted run's confirmed FAILED snapshot (#379).

    Source/sequence freshness is enforced by VoiceNode's existing status view.
    Arbitrary remote text is never added to playback or the bounded cache.
    """
    from ready2go_knowledge.core.refusal_reasons import text as reason_text
    if not isinstance(status, dict) or status.get('phase') not in ('idle', 'halted'):
        return None
    last, accepted = status.get('last'), status.get('accepted')
    if not isinstance(last, dict) or not isinstance(accepted, dict):
        return None
    failure = last.get('failure')
    run, boot = last.get('run_id'), status.get('boot_id')
    if (last.get('overall_status') != 'FAILED' or not isinstance(failure, dict)
            or not isinstance(run, str) or not run.strip()
            or not isinstance(boot, str) or not boot.strip()
            or failure.get('run_id') != run or accepted.get('run_id') != run
            or failure.get('boot_id') != boot):
        return None
    said = reason_text(failure.get('case_id'), failure.get('strategy'))
    if said is not None:
        return said
    # Only the existing C factory's finite sentences may be used as fallback.
    supplied = failure.get('text')
    if isinstance(supplied, str) and supplied in failure_texts():
        return supplied
    code, action = failure.get('code'), failure.get('action')
    if code is not None and not isinstance(code, str) or action is not None and not isinstance(action, str):
        return None
    return failure_speech.text(code, action)


def required_texts(cfg, items):
    from ready2go_knowledge.core.refusal_reasons import texts as refusal_texts
    texts = list(failure_texts())
    texts.extend(refusal_texts())
    # C의 실제 물품별 no_room 안내 템플릿과 조사 구현을 그대로 사용합니다.
    for steps in task_steps(cfg).values():
        step = steps.get('s8.n1')
        if step and step['action'] == 'speak':
            template = step['params']['text']
            texts.extend(interpolate(template, {'loc': item}) for item in items)
    return sorted(set(texts))


def final_failure_text(steps, last):
    step = steps.get(last.get('task_id'), {}).get(last.get('failed_step'))
    if step is None:
        return None
    action = step['action']
    if action == 'skill':
        action = step.get('skill')
    return failure_speech.text(last.get('error_code'), action)
