"""Read-only explanations; case evidence never grants motion permission."""
import json
from pathlib import Path


def _document(path=None):
    if path is None:
        path = Path(__file__).resolve().parents[5] / 'knowledge/refusal_reasons.json'
        if not path.is_file():
            from ament_index_python.packages import get_package_share_directory
            path = Path(get_package_share_directory('ready2go_knowledge')) / 'knowledge/refusal_reasons.json'
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load(path=None):
    doc = _document(path)
    result = {}
    for case in doc['cases']:
        key = case['id']
        if (not isinstance(key, str) or not key or key in result
                or case.get('strategy') != 'impossible'
                or not isinstance(case.get('text_ko'), str) or not case['text_ko'].strip()
                or case.get('status') not in {'verified_real', 'unconfirmed', 'sim_only', 'layout_rule'}
                or not isinstance(case.get('evidence'), dict)):
            raise ValueError('Invalid refusal reason catalog')
        result[key] = dict(case)
    return result


def text(case_id, strategy, *, catalog=None):
    """Only an explicitly classified impossible case supplies a phrase.

    Caller must verify freshness and run/boot identity before using this lookup.
    Unknown or absent classification returns None for the existing fallback.
    """
    if strategy != 'impossible' or not isinstance(case_id, str):
        return None
    case = (load() if catalog is None else catalog).get(case_id)
    return case['text_ko'] if case is not None else None


def texts():
    return sorted({case['text_ko'] for case in load().values()} | {unknown_text()})


def unknown_text():
    return _document()['unknown_text_ko']
