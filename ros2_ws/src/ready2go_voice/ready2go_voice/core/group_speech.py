"""C factory sentences validated and cached as bounded sentence fragments.

Only actual registered catalog subsets are used; never a Cartesian product of
item failures. This validates wording, not independent physical outcome proof.
"""
import re
from itertools import combinations
from ready2go_runner.core import item_group as group


def sentences(text):
    return [part.strip() for part in re.split(r'(?<=[.!?])\s+', text.strip()) if part.strip()]


def item_intros(targets, items):
    factory = getattr(group, 'item_start_text', None)
    if factory is None:
        return set()  # Existing C still uses the task's ordinary item sentence.
    # C #383: index is zero-based; excluded members do not count. A larger
    # requested catalog can have only one runnable member, so include that
    # factory form as well as first/next (at most three forms per actual item).
    return {factory(items[key]['name_ko'], index, total)
            for key in targets for total in {1, len(targets)} for index in range(min(2, total))}


def ordered_not_run(part, targets, items):
    """Validate C's runtime drawer order without pre-caching permutations."""
    ordered = sorted((key for key in targets if items[key]['name_ko'] in part),
                     key=lambda key: part.index(items[key]['name_ko']))
    if not ordered:
        return None
    outcomes = [group.ItemOutcome(key, items[key]['name_ko'], status=group.NOT_RUN) for key in ordered]
    actual = sentences(group.summary_text(group.GroupResult('FAILED', None, outcomes), None))[1:]
    canonical = factory_match(part, actual)
    if canonical is None:
        return None
    pieces = canonical.split(', ')
    return [piece + ',' for piece in pieces[:-1]] + [pieces[-1]]


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
                allowed.update(sentences(group.start_text([], excluded, accepted=True)))
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
        if count > 1:
            other = next(k for k in targets if k != key)
            outcomes = [group.ItemOutcome(k, items[k]['name_ko'], status=group.NOT_RUN) for k in (key, other)]
            clause = sentences(group.summary_text(group.GroupResult('FAILED', None, outcomes), None))[1]
            allowed.add(clause.split(', ')[0] + ',')
    return allowed


def factory_match(text, allowed):
    # Only whitespace and a terminal full stop; return the cached factory text.
    def key(value):
        return re.sub(r'\s+', ' ', value.strip()).rstrip('.')
    matches = {value for value in allowed if key(value) == key(text)}
    return next(iter(matches)) if len(matches) == 1 else None


def classify(text, pending, items, cfg):
    """Return (parts, is_summary), or None. Caller binds run/boot/source first."""
    from .runner_speech import required_texts
    task_texts = set(required_texts(cfg, items.values()))
    canonical = factory_match(text, task_texts | item_intros(pending['targets'], items))
    if canonical is not None:
        return [canonical], False
    allowed = fragments(pending['targets'], items)
    parts = [factory_match(part, allowed) or re.sub(r'\s+', ' ', part.strip()) for part in sentences(text)]
    if (not parts or len(parts) > len(pending['targets']) + 3
            or len(parts) != len(set(parts))):
        return None
    playback = []
    for part in parts:
        if part in allowed:
            playback.append(part)
        else:
            validated = ordered_not_run(part, pending['targets'], items)
            if validated is None or any(piece not in allowed for piece in validated):
                return None
            playback.extend(validated)
    # Summary always starts with a factory count/result head; start/exclusion
    # sentences do not count as final-result playback evidence.
    heads = set()
    for got in range(len(pending['targets']) + 1):
        outcomes = [group.ItemOutcome(k, items[k]['name_ko'],
            status=group.DELIVERED if n < got else group.NOT_RUN) for n, k in enumerate(pending['targets'])]
        result = group.GroupResult('COMPLETED' if got == len(outcomes) else 'FAILED', None, outcomes)
        heads.add(sentences(group.summary_text(result, None))[0])
    summary = parts[0] in heads
    if any(p in heads for p in parts[1:]) or not summary and (len(parts) != 1 or not parts[0].endswith('빼고 가져올게요.')):
        return None
    return playback, summary


def required_texts(cfg, items, runtime=None):
    from .semantic_requests import entries
    return sorted({text for _, result in entries(cfg, items, runtime)
                   for text in fragments(result['items'], items) | item_intros(result['items'], items)})
