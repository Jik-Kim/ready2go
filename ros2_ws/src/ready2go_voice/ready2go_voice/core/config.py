"""패키지 내부 YAML 설정. 장비/팀 선택값은 params에서만 관리합니다."""
from pathlib import Path
import math
import yaml


def load_config(path):
    with Path(path).open(encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError('voice 설정 객체가 필요합니다')
    for key in ('sample_rate', 'frame_samples', 'speech_rms', 'silence_sec',
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
    if cfg.get('bare_item_policy') not in ('clarify', 'unknown'):
        raise ValueError('대상 단독 발화는 clarify 또는 unknown으로 보류합니다')
    if cfg['tts_reserve_sec'] >= cfg['confirmation_budget_sec']:
        raise ValueError('TTS 여유는 전체 확인 예산보다 작아야 합니다')
    for key in ('evaluation_mode', 'audio_enabled', 'confirmation_enabled'):
        if not isinstance(cfg.get(key), bool):
            raise ValueError(f'{key}: bool 필요')
    for key in ('request_patterns', 'unsupported_patterns', 'cancel_phrases', 'status_phrases'):
        if not isinstance(cfg.get(key), list) or not cfg[key] or any(not isinstance(s, str) or not s for s in cfg[key]):
            raise ValueError(f'{key}: 비어 있지 않은 문자열 배열 필요')
    for key in ('ontology_file', 'intent_schema_file', 'wake_model', 'stt_model',
                'llm_model', 'tts_executable', 'tts_voice'):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            raise ValueError(f'{key}: 문자열 필요')
    return cfg
