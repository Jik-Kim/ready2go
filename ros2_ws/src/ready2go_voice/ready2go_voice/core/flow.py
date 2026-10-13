"""P1 음성 흐름 설정. 값·문구·문형의 단일 원본은 params/voice.yaml입니다."""
from copy import deepcopy
import math
import re
import yaml
from .stt_error import _prompt_file


def settings(cfg):
    with _prompt_file().open(encoding='utf-8') as stream:
        defaults = yaml.safe_load(stream)['voice_flow']
    supplied = cfg.get('voice_flow', {})
    if not isinstance(supplied, dict):
        raise ValueError('voice_flow: mapping 필요')
    value = deepcopy(defaults)
    for key, item in supplied.items():
        if key not in value:
            raise ValueError('voice_flow: 지원하지 않는 설정')
        value[key] = item
    for key in ('wake_cue_enabled', 'capture_save_wav', 'capture_trim', 'stt_context_hint_enabled', 'dummy_auto_complete'):
        if type(value[key]) is not bool:
            raise ValueError('voice_flow: bool 필요')
    for key in ('cue_rate_hz', 'cue_tone_sec', 'cue_gap_sec', 'cue_gain', 'cue_guard_sec', 'cue_timeout_sec', 'trim_padding_sec'):
        n = value[key]
        if type(n) not in (int, float) or not math.isfinite(n) or n <= 0:
            raise ValueError('voice_flow: 유한 양수 필요')
    if type(value['cue_rate_hz']) is not int or value['cue_gain'] > 1:
        raise ValueError('voice_flow: PCM rate/gain 확인 필요')
    tones = value['cue_tones_hz']
    if not isinstance(tones, list) or not tones or any(type(n) not in (int, float) or not math.isfinite(n) or not 0 < n < value['cue_rate_hz']/2 for n in tones):
        raise ValueError('voice_flow: tone 필요')
    if len(tones)*(value['cue_tone_sec']+value['cue_gap_sec']) + value['cue_guard_sec'] >= value['cue_timeout_sec']:
        raise ValueError('voice_flow: cue timeout 확인 필요')
    if value['capture_dir'] is not None and (not isinstance(value['capture_dir'], str) or not value['capture_dir'].strip()):
        raise ValueError('voice_flow.capture_dir: null 또는 경로 필요')
    if value['capture_save_wav'] and value['capture_dir'] is None:
        raise ValueError('voice_flow.capture_dir: 시험 저장 폴더 필요')
    for key in ('context_reply_pattern', 'stt_hint_template', 'empty_reply_prompt'):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError('voice_flow: 문구/문형 필요')
    re.compile(value['context_reply_pattern'])
    value['stt_hint_template'].format(item='물품')
    if not isinstance(value['status_prompts'], dict) or any(not isinstance(value['status_prompts'].get(k), str) or not value['status_prompts'][k].strip() for k in ('running','locked','unconfirmed')):
        raise ValueError('voice_flow.status_prompts: 상태 문구 필요')
    return value


def blocked_prompt(cfg, state=None):
    key = 'running' if state == 'running' else 'locked' if state in ('halted','locked') else 'unconfirmed'
    return (cfg.get('voice_flow') or settings(cfg))['status_prompts'][key]
