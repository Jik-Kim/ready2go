"""초기 필수 안내와 빈번한 검증 문장의 bounded 선준비 선택. WAV 저장은 worker 책임."""
import json
from pathlib import Path
import threading
from .runner_notice import STATUS_PROMPTS
from .response import confirmation, question, UNSUPPORTED_ITEM, UNSUPPORTED_REQUEST
from .diagnostics import redact
from .stt_error import error_prompts
from .flow import settings as flow_settings

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


def prefill_texts(cfg, items, warning=lambda message: None, on_selection=lambda data: None, *, reference_state=None, places=None, item_names=None):
    items = list(items)
    texts = list(cfg.get('tts_melotts_prefill_texts', []))
    texts.extend(cfg['clarify_prompts'].values())
    texts.extend(error_prompts(cfg).values())
    flow = cfg.get('voice_flow') or flow_settings(cfg)
    texts.extend(flow['status_prompts'].values())
    texts.append(flow['empty_reply_prompt'])
    from .hotfix import prompts, open_state_value
    extra = prompts(cfg)
    texts.extend(extra[k] for k in ('no_work','no_end_work','control_held','unknown_state','unknown_recorded_state',
                                  'control_recover','control_resume','control_end','control_failed'))
    texts.extend(text for key, text in extra.items() if key.startswith(('runtime_', 'notice_')) or key.startswith('status_') and key != 'status_target')
    texts.append(extra['control_rejected'])
    for item in items:
        texts.append(extra['availability'].format(item=item['name_ko']))
    if reference_state is not None and places is not None:
        from .recovery_confirmation import _particle
        from ready2go_knowledge.core.ontology import get
        for item_key, item in reference_state.get('located_in', {}).items():
            name = (item_names or {}).get(item_key)
            place = places.get(item, {}).get('name_ko') if isinstance(item, str) else None
            if name and place:
                for key in ('initial_location','recorded_location'):
                    texts.append(extra[key].format(item=name,item_topic=_particle(name,'은','는'),place=place))
        for key, place in places.items():
            if place.get('class') == 'Drawer' and type(get(reference_state,'open',key)) is bool:
                for prompt in ('initial_open','recorded_open'):
                    opened = get(reference_state,'open',key)
                    texts.append(extra[prompt].format(place=place['name_ko'],place_topic=_particle(place['name_ko'],'은','는'),value=open_state_value(extra,prompt,opened)))
        # Runner memory may differ from the initial layout. Prepare the existing
        # read-only answers for registered items/places and both drawer states.
        for name in (item_names or {}).values():
            texts.append(extra['recorded_held'].format(item=name, item_topic=_particle(name,'은','는')))
            for place in places.values():
                texts.append(extra['recorded_location'].format(item=name,
                    item_topic=_particle(name,'은','는'),place=place['name_ko']))
        for place in places.values():
            if place.get('class') == 'Drawer':
                for value in ('open_true','open_false'):
                    texts.append(extra['recorded_open'].format(place=place['name_ko'],
                        place_topic=_particle(place['name_ko'],'은','는'),value=open_state_value(extra,'recorded_open',value=='open_true')))
    texts.extend((UNSUPPORTED_ITEM, UNSUPPORTED_REQUEST))
    for item in items:
        name = item['name_ko']
        code = ord(name[-1]) if name else 0
        has_jong = 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0
        target = name + ('을' if has_jong else '를')
        texts.append(extra['status_target'].format(item_object=target))
        texts.extend((confirmation(name), question(name),
                      target + ' 찾아 올게요', target + ' 앞쪽 트레이에 놓았어요', target + ' 찾지 못했어요',
                      target + ' 꺼내지 못했어요'))
    # Current P2 task failure/held-stop notices are required, not history-selected.
    texts.extend(('옮긴 물건 일부를 원래 자리로 못 돌려놨어요. 사람이 확인해 주세요',
                  '물건을 옮기다 멈췄어요. 사람이 확인해 주세요'))
    texts.append('서랍을 닫았어요')
    texts.extend(STATUS_PROMPTS.values())
    from .runner_speech import required_texts
    texts.extend(required_texts(cfg, items))
    result = list(dict.fromkeys(texts))
    max_count = cfg.get('tts_prefill_max_texts', 512)
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
