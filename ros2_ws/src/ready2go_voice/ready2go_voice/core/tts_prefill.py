"""초기 필수 안내와 빈번한 검증 문장의 bounded 선준비 선택. WAV 저장은 worker 책임."""
import json
from pathlib import Path
import threading
from .runner_notice import STATUS_PROMPTS
from .response import confirmation, question, UNSUPPORTED_ITEM, UNSUPPORTED_REQUEST
from .diagnostics import redact

_LOCK = threading.Lock()


def _history_path(cfg):
    return Path(cfg['tts_melotts_assets']).expanduser() / 'validated_phrases.json'


def _history(cfg):
    path = _history_path(cfg)
    if not path.exists():
        return []
    if path.stat().st_size > cfg['tts_frequent_max_bytes']:
        raise ValueError('PREFILL_HISTORY_SIZE')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, list) or any(not isinstance(x, dict) or set(x) != {'text', 'uses'} or
        not isinstance(x['text'], str) or type(x['uses']) is not int or x['uses'] <= 0 or
        len(x['text']) > cfg['tts_prefill_max_chars'] for x in data):
        raise ValueError('PREFILL_HISTORY_INVALID')
    return data[:cfg['tts_frequent_max_texts']]


def remember_text(cfg, text, warning=lambda message: None):
    """유효 최종 문장 TTS 성공 뒤 호출. 과거 질문 상태나 원본 LLM을 저장하지 않습니다."""
    if len(text) > cfg['tts_prefill_max_chars'] or redact(text) != text:
        return
    with _LOCK:
        try:
            data = _history(cfg)
            entries = {x['text']: x['uses'] for x in data}
            entries[text] = entries.get(text, 0) + 1
            data = [{'text': t, 'uses': n} for t, n in sorted(entries.items(), key=lambda x: -x[1])]
            data = data[:cfg['tts_frequent_max_texts']]
            raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
            if len(raw) > cfg['tts_frequent_max_bytes']:
                raise ValueError('PREFILL_HISTORY_SIZE')
            path = _history_path(cfg)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(raw)
            temporary.replace(path)
        except Exception as exc:
            warning('빈번한 안내 기록 실패: ' + type(exc).__name__)


def prefill_texts(cfg, items, warning=lambda message: None, on_selection=lambda data: None):
    texts = list(cfg.get('tts_melotts_prefill_texts', []))
    texts.extend(cfg['clarify_prompts'].values())
    texts.extend((UNSUPPORTED_ITEM, UNSUPPORTED_REQUEST))
    for item in items:
        name = item['name_ko']
        code = ord(name[-1]) if name else 0
        has_jong = 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0
        target = name + ('을' if has_jong else '를')
        texts.extend((confirmation(name), question(name),
                      target + ' 찾아 올게요', target + ' 앞쪽 트레이에 놓았어요', target + ' 찾지 못했어요'))
    texts.append('서랍을 닫았어요')
    texts.extend(STATUS_PROMPTS.values())
    result = list(dict.fromkeys(texts))
    max_count = cfg.get('tts_prefill_max_texts', 128)
    max_chars = cfg.get('tts_prefill_max_chars', 160)
    max_bytes = cfg.get('tts_prefill_max_bytes', 65536)
    warmup = cfg.get('tts_melotts_warmup_text', '')
    if len(result) + 1 > max_count or any(len(t) > max_chars for t in [*result, warmup]) or sum(len(t.encode()) for t in [*result, warmup]) > max_bytes:
        raise ValueError('PREFILL_REQUIRED_LIMIT')
    required_count = len(result)
    try:
        history = _history(cfg)
        for entry in sorted(history, key=lambda x: -x['uses']):
            text = entry['text']
            if entry['uses'] < cfg['tts_frequent_min_uses'] or text in result:
                continue
            if len(result) + 1 < max_count and sum(len(t.encode()) for t in [*result, warmup]) + len(text.encode()) <= max_bytes:
                result.append(text)
    except Exception as exc:
        warning('빈번한 안내 선준비 보류: ' + type(exc).__name__)
    on_selection({'required_count': required_count, 'frequent_count': len(result) - required_count,
                  'text_count': len(result), 'warmup_count': 1, 'text_bytes': sum(len(t.encode()) for t in [*result, warmup])})
    return result
