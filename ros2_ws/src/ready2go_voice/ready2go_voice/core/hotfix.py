"""E 읽기 전용 초기 배치 질의와 안내. 상태 쓰기·공통 query wire는 없습니다."""
import re
import yaml
from .stt_error import _prompt_file


def prompts(cfg):
    with _prompt_file().open(encoding='utf-8') as stream:
        value = yaml.safe_load(stream)['voice_hotfix']
    supplied = cfg.get('voice_hotfix', {})
    if not isinstance(supplied, dict):
        raise ValueError('voice_hotfix: mapping 필요')
    value.update(supplied)
    if any(not isinstance(text,str) or not text.strip() for text in value.values()):
        raise ValueError('voice_hotfix: 안내 문자열 필요')
    return value



def reference_query(parser, text):
    from ready2go_knowledge.core.ontology import get
    value = ''.join(str(text).split()).rstrip('.!?？')
    p = prompts(parser.cfg)
    keys = parser.mentioned(text)
    if len(keys) == 1 and re.fullmatch(r'.+(?:어딨어|어디있어|어디에있어|어디에있나요|위치알려줘)', value):
        key = next(iter(keys)); place = get(parser.reference_state, 'located_in', key)
        name = parser.places.get(place, {}).get('name_ko')
        return p['initial_location'].format(item=parser.items[key]['name_ko'], place=name) if name else p['unknown_state']
    if re.fullmatch(r'.+(?:열려있어|열려있나요|닫혀있어|닫혀있나요)', value):
        places = []
        for key, definition in parser.places.items():
            names = [definition.get('name_ko',''), *(definition.get('aliases_ko') or [])]
            forms = {''.join(name.split()) for name in names if name}
            # 실제 이름 위 서랍의 방향 수식만 정규화합니다. 새 장소/원본 별칭은 추가하지 않습니다.
            forms.update(re.sub(r'^위(?=서랍$)', '위쪽', name) for name in list(forms))
            if any(name in value for name in forms):
                places.append(key)
        if len(places) == 1:
            opened = get(parser.reference_state, 'open', places[0])
            if type(opened) is bool:
                return p['initial_open'].format(place=parser.places[places[0]]['name_ko'], value=p['open_true' if opened else 'open_false'])
            return p['unknown_state']
    return None
