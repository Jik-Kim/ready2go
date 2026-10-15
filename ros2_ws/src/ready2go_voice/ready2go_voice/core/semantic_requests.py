"""P3 registered semantic requests and list contents share one validated TTL."""
import re
from pathlib import Path
from ready2go_knowledge.core.semantic_query import load_ttl

KINDS = ('find_list', 'find_class')
DEFAULT_QUERIES = [{'kind': 'list', 'id': 'commute_set'}, {'kind': 'class', 'id': 'Valuables'}]


def catalog(cfg, items):
    configured = cfg.get('semantic_catalog_file', 'auto')
    if configured != 'auto':
        path = Path(configured).expanduser().resolve()
    else:
        path = Path(cfg['ontology_file']).resolve().parent / 'semantics.ttl'
        if not path.is_file():
            path = Path(__file__).resolve().parents[5] / 'knowledge/semantics.ttl'
        if not path.is_file():
            from ament_index_python.packages import get_package_share_directory
            path = Path(get_package_share_directory('ready2go_knowledge')) / 'knowledge/semantics.ttl'
    retired = Path(cfg['ontology_file']).resolve().parent.parent / 'config/yolo_retired_classes.txt'
    if not retired.is_file():
        retired = Path(__file__).resolve().parents[5] / 'config/yolo_retired_classes.txt'
    if not retired.is_file():
        from ament_index_python.packages import get_package_share_directory
        retired = Path(get_package_share_directory('ready2go_knowledge')) / 'config/yolo_retired_classes.txt'
    return load_ttl(path, active_items=items, retired_items=retired.read_text().splitlines())


def entries(cfg, items):
    knowledge = catalog(cfg, items)
    result = []
    for entry in cfg.get('semantic_queries', DEFAULT_QUERIES):
        kind, key = entry['kind'], entry['id']
        query = knowledge.query_list if kind == 'list' else knowledge.query_class
        result.append((knowledge.names(kind, key), query(key)))
    return result


def acceptance(result):
    return result['source']['name_ko'] + ' 가져오기 요청으로 이해했어요.'


def contents(result, items):
    from .recovery_confirmation import _particle
    names = ', '.join(items[key]['name_ko'] for key in result['items'])
    return _particle(result['source']['name_ko'], '은', '는') + ' ' + (_particle(names, '이에요.', '예요.') if names else '등록된 물품이 없어요.')


def select(parser, text):
    """Returns (result, readonly), False for a mixed/unsupported group request,
    or None when this is unrelated to registered semantic names.
    """
    value = re.sub(r'\s+', '', str(text)).rstrip('.!?？')
    matched = []
    touched = False
    for names, result in entries(parser.cfg, parser.items):
        for name in names:
            name = re.sub(r'\s+', '', name)
            if name and name in value:
                touched = True
                rest = value.replace(name, '', 1)
                readonly = re.fullmatch(r'(?:은|는|에(?:는)?)?(?:뭐야|뭐예요|뭔지알려줘|뭐가들어있어|뭐가들어있어요|뭐가있어|목록알려줘|알려줘)', rest)
                execution = re.fullmatch(r'(?:을|를)?(?:가져와|가져와줘|가져다줘|가져다주세요|가져와주세요|찾아줘)', rest)
                if readonly or execution:
                    matched.append((result, bool(readonly)))
    unique = {(r['source']['kind'], r['source']['id'], read): (r, read) for r, read in matched}
    if len(unique) == 1:
        return next(iter(unique.values()))
    return False if touched or re.search(r'준비물|목록|분류|귀중품', value) else None


def validate(parser, doc):
    if doc.get('intent') not in KINDS:
        raise ValueError('semantic intent required')
    result = next((result for _, result in entries(parser.cfg, parser.items)
                   if result['source'] == doc.get('semantic', {}).get('source')), None)
    if (result is None or not result['items'] or doc.get('targets') != result['items']
            or doc.get('semantic') != {'source': result['source'], 'evidence': result['evidence']}
            or doc['intent'] != 'find_' + result['source']['kind']):
        raise ValueError('semantic catalog mismatch')
    parser.validator.validate({k: v for k, v in doc.items() if not k.startswith('_')})
    return result


def parse(parser, text):
    selected = select(parser, text)
    if selected is None:
        return None
    from .intent import intent
    if selected is False or selected[1]:
        return None if selected is not False else held(parser, text)
    result = selected[0]
    if not parser.cfg.get('request_run_enabled'):
        return held(parser, text)
    doc = intent('find_' + result['source']['kind'], result['items'])
    doc['semantic'] = {key: result[key] for key in ('source', 'evidence')}
    try:
        validate(parser, doc)
    except Exception:
        return held(parser, text)
    doc['_voice'] = {'semantic_candidate': True, 'final_text': acceptance(result)}
    doc['source'] = dict(stt_text=text, input_kind='text', llm_called=False,
        llm_validation='not_called', fallback_used=False, execution_allowed=True)
    return doc


def held(parser, text):
    from .intent import intent
    doc = intent('clarify', question=parser.cfg['clarify_prompts']['general'])
    doc['_voice'] = {'reason': 'semantic_mixed_or_unconfirmed', 'final_text': doc['clarify_question']}
    doc['source'] = dict(stt_text=text, input_kind='text', llm_called=False,
        llm_validation='not_called', fallback_used=False, execution_allowed=False)
    return doc


def reference(parser, text):
    selected = select(parser, text)
    if selected is False:
        return parser.cfg['clarify_prompts']['general']
    if selected is not None and selected is not False and selected[1]:
        return contents(selected[0], parser.items)
    return None


def required_texts(cfg, items):
    return sorted({text for _, result in entries(cfg, items)
                   for text in (acceptance(result), contents(result, items))})
