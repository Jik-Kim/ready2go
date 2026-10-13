"""E development fixtures only. These are not the Runner's public contract.

C integration must map authentic observations/registration/step results here.
"""
from dataclasses import dataclass
import json
from .skill_confirmation import PlaceWork
from .recovery_confirmation import finite
from .runner_notice import HALT_MOTION


@dataclass(frozen=True)
class PlaceInput:
    boot_id: str
    work: PlaceWork
    observation: str
    final_timeout_sec: float


def decode(raw):
    try:
        doc = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError, RecursionError):
        return None
    return doc if isinstance(doc, dict) else None


def identity(doc):
    if not isinstance(doc, dict):
        return None
    fields = ('boot_id', 'run_id', 'step_id')
    if not all(isinstance(doc.get(k), str) and doc[k].strip() for k in fields):
        return None
    return tuple(doc[k] for k in fields)


def question_input(doc):
    ident = identity(doc)
    if ident is None or doc.get('type') != 'question':
        return None
    items, budget = doc.get('items'), doc.get('final_timeout_sec')
    if (not isinstance(items, list) or not items
            or not all(isinstance(s, str) and s.strip() for s in items)
            or not isinstance(doc.get('destination'), str)
            or doc.get('observation') not in ('found', 'not_found', 'error', 'REGION_NOT_VISIBLE')
            or not finite(budget) or budget <= 0):
        return None
    boot, run, step = ident
    return PlaceInput(boot, PlaceWork(run, step, doc['destination'], tuple(items)),
                      doc['observation'], budget)


def registered(doc, envelope):
    if envelope is None or doc.get('type') != 'registered':
        return False
    work = envelope.question.work
    return (identity(doc) == (envelope.boot_id, work.run, work.step)
            and doc.get('question_id') == envelope.question_id
            and type(doc.get('attempt')) is int and doc['attempt'] == envelope.attempt)


def result_notice(doc, *, expected):
    """Same-step evidence is mandatory; overall FAILED alone proves no delivery."""
    if (doc.get('error_code') is not None and not isinstance(doc['error_code'], str)):
        return None
    if (doc.get('type') != 'result' or identity(doc) != expected
            or doc.get('overall_status') not in ('COMPLETED', 'FAILED')
            or doc.get('error_code') in HALT_MOTION | {'HALTED', 'CANCELED'}
            or doc.get('delivery_verified') is not True):
        return None
    restoration = doc.get('restoration_verified')
    if doc['overall_status'] == 'FAILED' and (restoration is False or restoration is None):
        return '물품은 전달했지만 원위치 복구를 완료하지 못했습니다.'
    if doc['overall_status'] == 'COMPLETED' and restoration is True:
        return '물품 전달과 원위치 복구를 완료했습니다.'
    return None
