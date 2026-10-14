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
        def walk(value):
            if isinstance(value, dict):
                if isinstance(value.get('id'), str) and isinstance(value.get('action'), str):
                    steps[value['id']] = value
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        walk(doc)
        result[doc['task_id']] = steps
    return result


def failure_texts():
    return set(filter(None, [failure_speech.text(code, action)
        for code in (*failure_speech.BY_CODE, 'TIMEOUT', None)
        for action in (*failure_speech.ACTION_KO, None)]))


def required_texts(cfg, items):
    texts = list(failure_texts())
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
