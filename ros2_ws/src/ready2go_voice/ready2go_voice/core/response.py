"""내부 후보 응답의 의미 검사. 최종 문장은 콘솔과 실제 TTS가 공유합니다."""
import re
from .intent import normalize


UNSUPPORTED_ITEM = '그 물품은 지원하지 않습니다.'
UNSUPPORTED_REQUEST = '그 요청은 지원하지 않습니다.'


def confirmation(name):
    return name + ' 가져오기 요청으로 이해했어요.'


def question(name):
    return name + ' 가져오기 요청이 맞나요?'


def goal_confirmation(parser, goals):
    parts = []
    for goal in goals:
        if goal['predicate'] == 'open':
            parts.append(parser.places[goal['subject']]['name_ko'] + (' 열림' if goal['value'] else ' 닫힘'))
        else:
            parts.append(parser.items[goal['subject']]['name_ko'] + ' ' + parser.places[goal['value']]['name_ko'] + ' 놓기')
    return ', '.join(parts) + ' 목표 요청으로 이해했어요.'


def final_response(parser, doc, candidate=None):
    kind = doc['intent']
    if kind == 'achieve_goal':
        default = goal_confirmation(parser, doc['goals'])
        doc.setdefault('_voice', {}).update(final_text=default, response_candidate=candidate,
            response_replacement_reason=None if candidate in (None, default) else 'response_goal_mismatch_or_promise')
        doc.pop('clarify_question', None)
        return default
    if kind != 'clarify':
        doc.pop('clarify_question', None)
    meta = doc.setdefault('_voice', {})
    key = doc.get('targets', [None])[0] if doc.get('targets') else meta.get('question_target')
    name = parser.items[key]['name_ko'] if key in parser.items else None
    if meta.get('availability'):
        from .hotfix import prompts
        default = prompts(parser.cfg)['availability'].format(item=name) if name else UNSUPPORTED_ITEM
    elif kind == 'cancel':
        default = '취소 요청으로 이해했어요.'
    elif kind == 'status':
        default = '상태 확인 요청으로 이해했어요.'
    elif kind == 'find_item':
        default = confirmation(name)
    elif kind == 'clarify':
        default = question(name) if name else (doc.get('clarify_question') if doc.get('clarify_question') in parser.cfg['clarify_prompts'].values() else parser.cfg['clarify_prompts']['general'])
    else:
        default = UNSUPPORTED_ITEM if meta.get('reason') == 'unregistered_item' else UNSUPPORTED_REQUEST
    reason = None
    if candidate is not None:
        if not isinstance(candidate, str) or not candidate.strip() or len(candidate) > parser.cfg.get('response_max_chars', 160):
            reason = 'response_type_or_length'
        else:
            candidate = candidate.strip()
            named = parser.mentioned(candidate)
            # Unknown nouns, execution promises and mismatched actions must not leak into TTS.
            promises = r'시작(?:했|합|하겠)|완료|성공|가져다드리겠|찾아올|찾아올게|놓았|실행하겠|실행합니다'
            bad_action = r'정리|던져|반납|손에|책상|열어|닫아|번역'
            if re.search(promises + '|' + bad_action, normalize(candidate)):
                reason = 'response_action_or_promise'
            elif name and named != {key}:
                reason = 'response_target_mismatch'
            elif kind == 'clarify' and not name:
                if not re.fullmatch(r'(?:어떤물품을(?:가져다드릴까요|찾으시나요)|어떤물품이필요하신가요|'
                                    r'(?:원하는)?물품이름을(?:말씀해|알려)주시겠어요)\?', normalize(candidate)):
                    reason = 'response_not_current_question'
                else:
                    meta['asks_delivery_target'] = True
            elif kind in ('clarify', 'find_item') and not meta.get('availability'):
                # 대상명을 제외한 문장도 요청 확인/질문 의미의 제한된 문법이어야 합니다.
                # 미등록 명사나 부정·추가 행동을 끼워 넣는 후보는 전체 일치에 실패합니다.
                aliases = [alias for alias, keys in parser.aliases.items() if keys == {key}]
                target = '(?:' + '|'.join(re.escape(a) for a in aliases) + ')'
                if kind == 'clarify':
                    body = (r'(?:(?:가져다|찾아)드릴까요|가져올까요|가져(?:오기|오는)요청이맞(?:나요|습니까)|'
                            r'가져오(?:길|기를)원하시(?:나요|는건가요)|가져다달라는말씀이맞나요)\?')
                else:
                    body = (r'(?:가져오기|가져오는|가져다달라는|찾아달라는|찾는|받고싶다는)'
                            r'(?:요청|말씀)(?:으로|을)?(?:이해|확인)(?:했어요|했습니다)[.!]?')
                if not name or not re.fullmatch(target + r'(?:을|를|은|는)?' + body, normalize(candidate)):
                    reason = 'response_not_current_question' if kind == 'clarify' else 'response_not_request_ack'
            elif candidate != default:
                reason = 'response_unsupported_or_availability'
    meta.update(response_candidate=candidate, response_replacement_reason=reason,
                final_text=default if candidate is None or reason else candidate)
    if kind == 'clarify' and not meta.get('availability'):
        doc['clarify_question'] = meta['final_text']
    return meta['final_text']
