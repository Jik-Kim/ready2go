"""조건식 평가 — docs/runner.md 7.1 "조건식 (단일 형태)".

형태: {"op": "<연산자>", "args": [...]}
비교 ==, !=, <, >, <=, >= (args 2개) / 논리 and, or (2개 이상), not (1개) / 컬렉션 empty, not_empty (1개).
args 의 "$경로" 는 블랙보드 값으로 치환하고, {"op": ...} 객체는 중첩 조건으로 평가한다.
"""
from __future__ import annotations

import operator
from typing import Any

from .variables import resolve

_COMPARE = {"==": operator.eq, "!=": operator.ne, "<": operator.lt,
            ">": operator.gt, "<=": operator.le, ">=": operator.ge}


class BadCondition(Exception):
    code = "BAD_CONDITION"


def _is_cond(value: Any) -> bool:
    return isinstance(value, dict) and "op" in value


def _arg(value: Any, blackboard: dict) -> Any:
    """인자 하나: 중첩 조건이면 평가 결과, 아니면 변수 치환 값."""
    return evaluate(value, blackboard) if _is_cond(value) else resolve(value, blackboard)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)):
        return len(value) == 0
    raise BadCondition(f"empty/not_empty 는 리스트·객체·문자열에만 쓸 수 있음: {value!r}")


def evaluate(cond: dict, blackboard: dict) -> bool:
    """조건식을 평가해 True/False 를 반환."""
    if not _is_cond(cond):
        raise BadCondition(f"조건식 형식이 아님: {cond!r}")
    op, args = cond["op"], cond.get("args", [])

    if op in _COMPARE:
        if len(args) != 2:
            raise BadCondition(f"'{op}' 는 args 2개가 필요함: {args!r}")
        left, right = _arg(args[0], blackboard), _arg(args[1], blackboard)
        try:
            return bool(_COMPARE[op](left, right))
        except TypeError:
            raise BadCondition(f"비교할 수 없는 값: {left!r} {op} {right!r}") from None

    if op in ("and", "or"):
        if len(args) < 2:
            raise BadCondition(f"'{op}' 는 args 2개 이상이 필요함: {args!r}")
        # 제너레이터라서 결과가 정해지면 나머지 인자는 평가하지 않음 (and: 거짓, or: 참)
        values = (bool(_arg(a, blackboard)) for a in args)
        return all(values) if op == "and" else any(values)

    if op in ("not", "empty", "not_empty"):
        if len(args) != 1:
            raise BadCondition(f"'{op}' 는 args 1개가 필요함: {args!r}")
        value = _arg(args[0], blackboard)
        if op == "not":
            return not bool(value)
        return _is_empty(value) if op == "empty" else not _is_empty(value)

    raise BadCondition(f"알 수 없는 연산자: {op!r}")
