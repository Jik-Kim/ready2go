"""STT 예외의 내부 진단 허용 목록. 원문/본문/헤더/전사는 저장하지 않습니다."""

from pathlib import Path
import yaml

PROMPT_KEYS = ('rate_limit', 'quota', 'unknown_429')


def _prompt_file():
    source = Path(__file__).resolve().parents[2] / 'params' / 'voice.yaml'
    if source.is_file():
        return source
    # setup.py data_files + package.xml의 기존 ament_index_python 의존성.
    from ament_index_python.packages import get_package_share_directory
    return Path(get_package_share_directory('ready2go_voice')) / 'params' / 'voice.yaml'


def error_prompts(cfg):
    """누락된 local/raw cfg에 YAML 단일 원본만 적용; 전체 config 재로딩은 하지 않습니다."""
    if 'stt_error_prompts' in cfg:
        prompts = cfg['stt_error_prompts']
    else:
        with _prompt_file().open(encoding='utf-8') as stream:
            base = yaml.safe_load(stream)
        prompts = base.get('stt_error_prompts') if isinstance(base, dict) else None
    if not isinstance(prompts, dict) or any(
            not isinstance(prompts.get(k), str) or not prompts[k].strip() for k in PROMPT_KEYS):
        raise ValueError('stt_error_prompts: 원인별 고정 안내 문자열 필요')
    return {k: prompts[k] for k in PROMPT_KEYS}


# 공식 API 오류 코드의 닫힌 목록입니다. 임의 문자열은 증빙으로 내보내지 않습니다.
RATE_CODES = frozenset(('rate_limit_exceeded', 'slow_down'))
QUOTA_CODES = frozenset(('insufficient_quota', 'organization_spend_limit_exceeded',
    'credit_balance_exhausted', 'project_spend_limit_exceeded', 'organization_usage_limit_exceeded'))
TYPES = frozenset(('rate_limit_error', 'insufficient_quota', 'requests', 'tokens'))


def _attribute(exc, key):
    try:
        return getattr(exc, key, None)
    except Exception:
        return None


def error_info(exc):
    """SDK 정규화 속성만 읽고 누락/이상값/속성 오류도 안전하게 처리합니다."""
    status = _attribute(exc, 'status_code')
    status = status if type(status) is int and 100 <= status <= 599 else None
    code, kind = _attribute(exc, 'code'), _attribute(exc, 'type')
    code = code if type(code) is str and code in RATE_CODES | QUOTA_CODES else None
    kind = kind if type(kind) is str and kind in TYPES else None
    category = 'other'
    if status == 429 or status is None and type(exc).__name__ == 'RateLimitError':
        rate = code in RATE_CODES or kind == 'rate_limit_error'
        quota = code in QUOTA_CODES or kind == 'insufficient_quota'
        category = 'rate_limit' if rate and not quota else 'quota' if quota and not rate else 'unknown_429'
    return dict(status=status, code=code, type=kind, category=category)
