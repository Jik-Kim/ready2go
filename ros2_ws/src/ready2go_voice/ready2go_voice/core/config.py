"""패키지 내부 YAML 설정. 장비/팀 선택값은 params에서만 관리합니다."""
from pathlib import Path
import math
import yaml


def load_config(path, *, evaluation_mode=None):
    with Path(path).open(encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError('voice 설정 객체가 필요합니다')
    cfg.setdefault('evaluation_mode', False)
    if evaluation_mode is not None:
        if not isinstance(evaluation_mode, bool):
            raise ValueError('evaluation_mode: bool 필요')
        cfg['evaluation_mode'] = evaluation_mode
    prompts = cfg.get('clarify_prompts')
    keys = ('empty', 'multiple', 'bare', 'request', 'missing_item', 'unconfirmed',
            'general', 'audio_failure', 'no_speech', 'tts_failure')
    if not isinstance(prompts, dict) or any(not isinstance(prompts.get(k), str) or not prompts[k].strip() for k in keys):
        raise ValueError('clarify_prompts: 필수 고정 안내 설정 필요')
    value = cfg.get('speech_vad_threshold')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1:
        raise ValueError('speech_vad_threshold: 0초과 1이하 필요')
    value = cfg.get('speech_min_voiced_sec')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError('speech_min_voiced_sec: 양수 유한값 필요')
    if cfg.get('speech_vad_model') is not None and (not isinstance(cfg['speech_vad_model'], str) or not cfg['speech_vad_model'].strip()):
        raise ValueError('speech_vad_model: null 또는 경로 필요')
    cfg.setdefault('tts_engine', 'espeak')
    if cfg['tts_engine'] not in ('espeak', 'melotts'):
        raise ValueError('TTS 엔진 확인 필요')
    if cfg['tts_engine'] == 'melotts':
        for key in ('tts_melotts_python', 'tts_melotts_assets', 'tts_melotts_speaker', 'tts_melotts_warmup_text'):
            if not isinstance(cfg.get(key), str) or not cfg[key].strip():
                raise ValueError(f'{key}: 문자열 필요')
        for key in ('tts_melotts_speed', 'tts_melotts_startup_timeout_sec', 'tts_melotts_threads'):
            value = cfg.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{key}: 양수 유한값 필요')
        if not isinstance(cfg['tts_melotts_threads'], int):
            raise ValueError('tts_melotts_threads: 정수 필요')
    cfg.setdefault('tts_melotts_prefill_texts', [])
    if not isinstance(cfg['tts_melotts_prefill_texts'], list) or any(
            not isinstance(text, str) or not text.strip() for text in cfg['tts_melotts_prefill_texts']):
        raise ValueError('tts_melotts_prefill_texts: 문자열 배열 필요')
    cfg.setdefault('recording_mode', 'silence')
    cfg.setdefault('record_duration_sec', 5.0)
    cfg.setdefault('timing_mode', 'ac_budget')
    cfg.setdefault('diagnostic_detail', False)
    if cfg['recording_mode'] not in ('fixed', 'silence') or cfg['timing_mode'] not in ('commissioning', 'ac_budget'):
        raise ValueError('녹음/시간예산 모드 확인 필요')
    if cfg['recording_mode'] == 'fixed' and cfg['timing_mode'] != 'commissioning':
        raise ValueError('fixed 녹음은 발화 종료 미측정이므로 commissioning 모드가 필요합니다')
    for key in ('record_duration_sec', 'sample_rate', 'frame_samples', 'speech_rms', 'silence_sec',
                'speech_start_timeout_sec', 'max_record_sec', 'stt_timeout_sec',
                'llm_timeout_sec', 'confirmation_budget_sec', 'tts_reserve_sec',
                'tts_timeout_sec', 'tts_speed', 'duplicate_window_sec'):
        val = cfg.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val) or val <= 0:
            raise ValueError(f'{key}: 양수 유한값 필요')
    for key in ('sample_rate', 'frame_samples', 'tts_speed'):
        if not isinstance(cfg[key], int):
            raise ValueError(f'{key}: 정수 필요')
    if cfg['sample_rate'] != 16000 or cfg['frame_samples'] % 1280:
        raise ValueError('강의 웨이크 모델은 16kHz/1280의 배수 프레임을 사용합니다')
    for key in ('min_confidence', 'wake_threshold'):
        if not isinstance(cfg.get(key), (int, float)) or isinstance(cfg[key], bool) or not 0 <= cfg[key] <= 1:
            raise ValueError(f'{key}: 0~1 필요')
    if cfg.get('bare_item_policy') != 'clarify':
        raise ValueError('사용자 확정 정책: 대상 단독/모호 요청은 clarify로 보류합니다')
    if cfg['tts_reserve_sec'] >= cfg['confirmation_budget_sec']:
        raise ValueError('TTS 여유는 전체 확인 예산보다 작아야 합니다')
    if cfg['speech_min_voiced_sec'] > cfg['record_duration_sec']:
        raise ValueError('최소 음성 구간은 녹음 길이 이하여야 합니다')
    if cfg['recording_mode'] == 'fixed' and cfg['record_duration_sec'] >= cfg['max_record_sec']:
        raise ValueError('고정 녹음 시간은 녹음 보호 한도보다 짧아야 합니다')
    for key in ('diagnostic_detail', 'evaluation_mode', 'audio_enabled', 'confirmation_enabled'):
        if not isinstance(cfg.get(key), bool):
            raise ValueError(f'{key}: bool 필요')
    for key in ('request_patterns', 'unsupported_patterns', 'cancel_phrases', 'status_phrases'):
        if not isinstance(cfg.get(key), list) or not cfg[key] or any(not isinstance(s, str) or not s for s in cfg[key]):
            raise ValueError(f'{key}: 비어 있지 않은 문자열 배열 필요')
    for key in ('ontology_file', 'intent_schema_file', 'wake_model', 'stt_model',
                'llm_model', 'tts_executable', 'tts_voice'):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            raise ValueError(f'{key}: 문자열 필요')
    cfg.setdefault('dialogue_timeout_sec', None)
    timeout = cfg['dialogue_timeout_sec']
    if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError('dialogue_timeout_sec: null 또는 유한 양수 필요')
    defaults = {'response_max_chars': 160, 'diagnostic_max_bytes': 10485760,
                'diagnostic_backups': 3, 'diagnostic_queue_size': 128,
                'tts_prefill_progress_every': 8, 'tts_prefill_max_texts': 128, 'tts_prefill_max_chars': 160, 'tts_prefill_max_bytes': 65536,
                'tts_frequent_max_texts': 32, 'tts_frequent_min_uses': 2,
                'tts_frequent_max_bytes': 1048576}
    for key, default in defaults.items():
        cfg.setdefault(key, default)
        if type(cfg[key]) is not int or cfg[key] <= 0:
            raise ValueError(f'{key}: 양의 정수 필요')
    cfg.setdefault('diagnostic_file', 'logs/voice/diagnostic.jsonl')
    if not isinstance(cfg['diagnostic_file'], str) or not cfg['diagnostic_file'].strip():
        raise ValueError('diagnostic_file: 경로 필요')
    if 'place_answer_timeout_sec' in cfg:
        raise ValueError('place_answer_timeout_sec removed; use separate admission/STT settings')
    for key in ('resume_admission_window_sec', 'resume_stt_result_timeout_sec',
                'resume_register_ack_timeout_sec', 'resume_question_tts_timeout_sec',
                'resume_independent_request_timeout_sec', 'place_admission_window_sec',
                'place_stt_result_timeout_sec'):
        cfg.setdefault(key, None)
        value = cfg[key]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
            raise ValueError(f'{key}: null or finite positive number required')
    cfg.setdefault('place_max_reasks', None)
    if cfg['place_max_reasks'] is not None and (type(cfg['place_max_reasks']) is not int or cfg['place_max_reasks'] not in (0, 1)):
        raise ValueError('place_max_reasks: null, 0 or 1 required')
    cfg.setdefault('p2_goal_enabled', False)
    if type(cfg['p2_goal_enabled']) is not bool:
        raise ValueError('p2_goal_enabled: bool required')
    cfg.setdefault('p2_goal_catalog', [])
    if not isinstance(cfg['p2_goal_catalog'], list):
        raise ValueError('p2_goal_catalog: list required')
    for goals in cfg['p2_goal_catalog']:
        if not isinstance(goals, list) or not goals:
            raise ValueError('nonempty goal list required')
        for goal in goals:
            if (not isinstance(goal, dict) or set(goal) != {'predicate', 'subject', 'value'} or
                    not isinstance(goal['subject'], str) or not goal['subject'].strip() or
                    not ((goal['predicate'] == 'open' and type(goal['value']) is bool) or
                         (goal['predicate'] == 'located_in' and isinstance(goal['value'], str) and goal['value'].strip()))):
                raise ValueError('invalid P2 catalog goal')
    if cfg['p2_goal_enabled'] and not cfg['p2_goal_catalog']:
        raise ValueError('enabled P2 evaluation requires a nonempty selected catalog')
    cfg.setdefault('pick_verify_lower_bound_m', 0.010)
    value = cfg['pick_verify_lower_bound_m']
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('pick_verify_lower_bound_m: finite positive number required')
    return cfg
