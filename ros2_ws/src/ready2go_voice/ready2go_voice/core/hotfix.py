"""기존 읽기 전용 위치/개폐 질의와 안내. 상태 쓰기·공통 query wire는 없습니다."""
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
    for key, field in (('initial_location', 'item'), ('recorded_location', 'item'), ('recorded_held', 'item'), ('initial_open', 'place'), ('recorded_open', 'place')):
        value[key] = value[key].replace('{' + field + '}은', '{' + field + '_topic}')
    if any(not isinstance(text,str) or not text.strip() for text in value.values()):
        raise ValueError('voice_hotfix: 안내 문자열 필요')
    return value



def control_notice(cfg, kind, *, runtime=False, reason=None, operation=None):
    """C result wording stays separate from explicit dummy fixtures."""
    key = 'control_' + kind
    if runtime:
        key = 'runtime_' + kind
        if kind == 'failed':
            if reason in ('EXTERNAL_FORCE', 'EXTERNAL_FORCE_UNKNOWN'):
                return prompts(cfg)['runtime_external_force' + ('_unknown' if reason.endswith('UNKNOWN') else '')]
            if reason == 'STOPPED_DURING_RECOVER':
                key = 'runtime_restopped'
            elif reason in ('B_RECOVER_UNAVAILABLE', 'B_RECOVER_FAILED', 'B_CHECK_UNAVAILABLE'):
                key = 'runtime_service_failed'
            elif operation == 'recover':
                key = 'runtime_recover_failed'
    return prompts(cfg)[key]


STATUS_QUERIES = frozenset({'지금뭐하고있어', '지금뭐하고있나요', '현재상태', '현재상태알려줘'})


def is_status_query(parser, text):
    value = ''.join(str(text).split()).rstrip('.!?？')
    return value in STATUS_QUERIES | {''.join(p.split()).rstrip('.!?？') for p in parser.cfg['status_phrases']}


def status_answer(parser):
    from .recovery_confirmation import _particle
    p = prompts(parser.cfg)
    provider = getattr(parser, 'status_provider', None)
    try:
        view = provider() if provider is not None else None
    except Exception:
        view = None
    if not isinstance(view, dict) or not isinstance(view.get('status'), dict):
        return p['status_unknown']
    status = view['status']
    if view.get('recovering') is True:
        return p['status_recovering']
    halt = status.get('halt') or {}
    resume = halt.get('resume') or {}
    if (resume.get('question') or {}).get('state') == 'registered':
        return p['status_resume_wait']
    if resume.get('offered') is True:
        return p['status_resume_ready']
    phase = status.get('phase')
    if phase == 'running':
        item = parser.items.get(view.get('target'))
        return p['status_target'].format(item_object=_particle(item['name_ko'], '을', '를')) if item else p['status_running']
    return p['status_idle' if phase == 'idle' else 'status_halted' if phase == 'halted' else 'status_unknown']


def open_state_value(p, prompt, opened):
    # Keep an explicitly supplied old noun-state template grammatical. Do not
    # replace the user's template or force a short answer over an override.
    prefix = 'recorded_open_' if prompt == 'recorded_open' and '{value} 상태' not in p[prompt] else 'open_'
    return p[prefix + ('true' if opened else 'false')]


def reference_query(parser, text):
    from ready2go_knowledge.core.ontology import get
    from .recovery_confirmation import _particle
    value = ''.join(str(text).split()).rstrip('.!?？')
    p = prompts(parser.cfg)
    if is_status_query(parser, text):
        return status_answer(parser)
    keys = parser.mentioned(text)
    provider = getattr(parser, 'state_provider', None)
    def read(predicate, subject):
        try:
            state = parser.reference_state if provider is None else provider()
            if not isinstance(state, dict):
                return None
            return get(state, predicate, subject)
        except Exception:
            return None  # 연결 실패/누락을 초기 프리셋으로 대체하지 않습니다.
    location_prompt = p['initial_location'] if provider is None else p['recorded_location']
    open_prompt = p['initial_open'] if provider is None else p['recorded_open']
    unknown = p['unknown_state'] if provider is None else p['unknown_recorded_state']

    if len(keys) == 1 and re.fullmatch(r'.+(?:어딨어|어디있어|어디에있어|어디에있나요|위치알려줘)', value):
        key = next(iter(keys)); place = read('located_in', key)
        if place == 'gripper' and provider is not None:
            return p['recorded_held'].format(item=parser.items[key]['name_ko'],
                item_topic=_particle(parser.items[key]['name_ko'], '은', '는'))
        name = parser.places.get(place, {}).get('name_ko') if isinstance(place,str) else None
        return location_prompt.format(item=parser.items[key]['name_ko'], item_topic=_particle(parser.items[key]['name_ko'], '은', '는'), place=name) if name else unknown
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
            opened = read('open', places[0])
            if type(opened) is bool:
                return open_prompt.format(place=parser.places[places[0]]['name_ko'], place_topic=_particle(parser.places[places[0]]['name_ko'], '은', '는'), value=open_state_value(p, 'recorded_open' if provider is not None else 'initial_open', opened))
            return unknown
    return None
