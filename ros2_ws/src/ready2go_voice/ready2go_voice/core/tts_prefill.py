"""P1 고정 안내 캐시 입력. 태스크 실행/성공 판정은 Runner 책임입니다."""

from .runner_notice import STATUS_PROMPTS


def prefill_texts(cfg, items):
    texts = list(cfg.get('tts_melotts_prefill_texts', []))
    texts.extend(cfg['clarify_prompts'].values())
    for item in items:
        name = item['name_ko']
        # Runner core.variables의 |을 규칙: 마지막 한글 종성, 비한글은 받침 없음.
        code = ord(name[-1]) if name else 0
        has_jong = 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0
        target = name + ('을' if has_jong else '를')
        texts.extend((name + ' 가져다드리겠습니다.',
                      target + ' 찾아 올게요',
                      target + ' 앞쪽 트레이에 놓았어요',
                      target + ' 찾지 못했어요'))
    texts.append('서랍을 닫았어요')
    texts.extend(STATUS_PROMPTS.values())
    return list(dict.fromkeys(texts))
