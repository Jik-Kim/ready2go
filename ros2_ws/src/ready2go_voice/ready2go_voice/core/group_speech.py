"""C factory sentences validated and cached as bounded sentence fragments.

Only actual registered catalog subsets are used; never a Cartesian product of
item failures. This validates wording, not independent physical outcome proof.
"""
import re
import inspect
from itertools import combinations
from ready2go_runner.core import item_group as group


def sentences(text):
    return [part.strip() for part in re.split(r'(?<=[.!?])\s+', text.strip()) if part.strip()]


def fragments(targets, items):
    if not targets:
        return set()
    names = [items[key]['name_ko'] for key in targets]
    allowed = set()
    count = len(targets)
    for got in range(count + 1):
        outcomes = [group.ItemOutcome(key, name, status=group.DELIVERED if n < got else group.NOT_RUN)
                    for n, (key, name) in enumerate(zip(targets, names))]
        result = group.GroupResult('COMPLETED' if got == count else 'FAILED', None, outcomes)
        allowed.update(sentences(group.summary_text(result, None)))
    for size in range(1, count + 1):
        for subset in combinations(targets, size):
            outcomes = [group.ItemOutcome(key, items[key]['name_ko'], status=group.NOT_RUN) for key in subset]
            result = group.GroupResult('FAILED', None, outcomes)
            allowed.update(sentences(group.summary_text(result, None)))
            for code in (group.UNKNOWN_ITEM, 'NOT_IN_DRAWER', None):
                excluded = [group.ItemOutcome(key, items[key]['name_ko'], status=group.EXCLUDED,
                            error_code=code) for key in subset]
                if 'accepted' in inspect.signature(group.start_text).parameters:
                    allowed.update(sentences(group.start_text([], excluded, accepted=True)))
                else:
                    # Before #381 merge only the exclusion sentence is shared;
                    # no new wire request passes the old intent schema.
                    allowed.update(sentences(group.start_text([], excluded))[1:])
    for key, name in zip(targets, names):
        for code in (*group.REASON_KO, None):
            outcome = group.ItemOutcome(key, name, status=group.NOT_DELIVERED, error_code=code)
            for stop in (None, 'halted', 'failed'):
                result = group.GroupResult('FAILED', code, [outcome])
                # The first sentence is the group count; singleton count heads
                # are not valid for a larger requested catalog.
                allowed.update(sentences(group.summary_text(result, stop))[1:])
            outcome.restore_incomplete = True
            allowed.update(sentences(group.summary_text(group.GroupResult('FAILED', code, [outcome]), 'failed'))[1:])
    return allowed


def classify(text, pending, items, cfg):
    """Return (parts, is_summary), or None. Caller binds run/boot/source first."""
    from .runner_speech import required_texts
    task_texts = set(required_texts(cfg, items.values()))
    if text in task_texts:
        return [text], False
    allowed = fragments(pending['targets'], items)
    parts = sentences(text)
    if (not parts or len(parts) > len(pending['targets']) + 3
            or len(parts) != len(set(parts)) or any(p not in allowed for p in parts)):
        return None
    # Summary always starts with a factory count/result head; start/exclusion
    # sentences do not count as final-result playback evidence.
    heads = set()
    for got in range(len(pending['targets']) + 1):
        outcomes = [group.ItemOutcome(k, items[k]['name_ko'],
            status=group.DELIVERED if n < got else group.NOT_RUN) for n, k in enumerate(pending['targets'])]
        result = group.GroupResult('COMPLETED' if got == len(outcomes) else 'FAILED', None, outcomes)
        heads.add(sentences(group.summary_text(result, None))[0])
    summary = parts[0] in heads
    if any(p in heads for p in parts[1:]) or not summary and (len(parts) != 1 or not text.endswith('빼고 가져올게요.')):
        return None
    return parts, summary


def required_texts(cfg, items):
    from .semantic_requests import entries
    return sorted({text for _, result in entries(cfg, items) for text in fragments(result['items'], items)})
