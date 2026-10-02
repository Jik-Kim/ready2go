"""로봇 온톨로지 core (ROS 비의존) — docs/ontology.md 7.5, 7.8.

Phase 1 범위: 로딩, 상태 읽기/쓰기, 스킬 조건(pre) 확인, 결과(effect) 반영, 목록 참조 검사.
Phase 2: verify·hold, 관측 우선 갱신 / Phase 3: 클래스 추론, 시작 시 전체 정합성 검사.
상태 형태: state[predicate][subject] = value
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

_OPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b}


def load(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve(value: Any, binding: dict) -> Any:
    """'$name' 을 binding 값으로 치환. 그 외 값은 그대로."""
    if isinstance(value, str) and value.startswith("$"):
        return binding[value[1:]]
    return value


def get(state: dict, predicate: str, subject: str) -> Any:
    return state.get(predicate, {}).get(subject)


def check(state: dict, records: list[dict], binding: dict) -> list[dict]:
    """조건 레코드별 결과 [{subject, predicate, op, value, actual, pass}] (로그 pre_check 용)."""
    results = []
    for r in records:
        subject = resolve(r["subject"], binding)
        expected = resolve(r["value"], binding)
        actual = get(state, r["predicate"], subject)
        ok = _OPS[r.get("op", "==")](actual, expected)
        results.append({"subject": subject, "predicate": r["predicate"], "op": r.get("op", "=="),
                        "value": expected, "actual": actual, "pass": ok})
    return results


def apply(state: dict, records: list[dict], binding: dict) -> tuple[dict, dict]:
    """결과 레코드를 반영한 새 상태와 diff {"predicate.subject": [이전, 이후]} 를 반환."""
    new = copy.deepcopy(state)
    diff = {}
    for r in records:
        subject = resolve(r["subject"], binding)
        value = resolve(r["value"], binding)
        before = get(new, r["predicate"], subject)
        new.setdefault(r["predicate"], {})[subject] = value
        if before != value:
            diff[f"{r['predicate']}.{subject}"] = [before, value]
    return new, diff


def list_reference_errors(onto: dict) -> list[str]:
    """world.lists 의 items 가 world.items 에 모두 정의되어 있는지 (로딩 시 검사)."""
    items = onto.get("world", {}).get("items", {})
    errors = []
    for name, lst in onto.get("world", {}).get("lists", {}).items():
        errors += [f"lists.{name}: 정의되지 않은 물품 {i}" for i in lst.get("items", []) if i not in items]
    return errors
