"""태스크 변수 치환 — docs/runner.md 7.1 "변수 문법".

값 전체 참조: "$scan.target.id", "$scan.candidates[0].id" → 원래 타입 그대로 치환.
문자열 보간: "{{loc.name_ko}} 찾기를 시작합니다" → 문자열로 치환.
조사 필터: "{{loc.name_ko|을}}" → "시계를"/"지갑을", "{{list|목록|을}}" → "차키, 지갑, 시계를".
eval 을 쓰지 않고 경로를 직접 해석하며, 없는 변수는 VAR_UNDEFINED.
"""
from __future__ import annotations

import re
from typing import Any

# "scan.candidates[0].id" → 이름(scan, candidates, id) 또는 인덱스([0]) 토큰
_TOKEN = re.compile(r"\.?([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")
# "{{ loc.name_ko|을 }}" → 중괄호 안의 경로와 필터
_PLACEHOLDER = re.compile(r"\{\{\s*(.*?)\s*\}\}")

# 조사 쌍 (받침 있음, 받침 없음). 어느 쪽으로 적어도 같은 쌍으로 처리
_PARTICLES = [("을", "를"), ("이", "가"), ("은", "는"), ("과", "와"), ("으로", "로")]
_PARTICLE_PAIR = {p: pair for pair in _PARTICLES for p in pair}
_HANGUL_FIRST, _HANGUL_LAST = 0xAC00, 0xD7A3   # "가" ~ "힣"
_JONG_RIEUL = 8                                # 받침 ㄹ 의 종성 번호


class VarUndefined(Exception):
    code = "VAR_UNDEFINED"


class BadFilter(Exception):
    code = "BAD_FILTER"


def get_path(blackboard: dict, path: str) -> Any:
    """블랙보드에서 'a.b[0].c' 경로의 값을 꺼낸다."""
    if not path:
        raise VarUndefined("변수 이름이 비어 있음: $")
    value: Any = blackboard
    pos = 0
    while pos < len(path):
        m = _TOKEN.match(path, pos)
        if not m or (pos == 0 and path.startswith(".")):
            raise VarUndefined(f"잘못된 변수 경로: ${path}")
        name, index = m.group(1), m.group(2)
        try:
            value = value[name] if name is not None else value[int(index)]
        except (KeyError, IndexError, TypeError):
            raise VarUndefined(f"정의되지 않은 변수: ${path}") from None
        pos = m.end()
    return value


def _final_jong(word: str) -> int:
    """마지막 글자의 종성 번호. 0 = 받침 없음. 한글 음절이 아니면(영문·숫자 등) 0."""
    if not word:
        return 0
    code = ord(word[-1])
    if not _HANGUL_FIRST <= code <= _HANGUL_LAST:
        return 0
    return (code - _HANGUL_FIRST) % 28


def attach_particle(word: str, particle: str) -> str:
    """받침 유무로 조사를 골라 붙인다. 예: ("시계", "을") → "시계를"."""
    if particle not in _PARTICLE_PAIR:
        raise BadFilter(f"알 수 없는 필터: |{particle}")
    with_jong, without_jong = _PARTICLE_PAIR[particle]
    jong = _final_jong(word)
    if with_jong == "으로" and jong == _JONG_RIEUL:   # ㄹ 받침은 "로" (칼로, 연필로)
        return word + without_jong
    return word + (with_jong if jong else without_jong)


def _render(expr: str, blackboard: dict) -> str:
    """"경로|필터|필터" 하나를 문자열로 만든다. 필터: 목록(쉼표로 잇기), 조사."""
    path, *filters = [part.strip() for part in expr.split("|")]
    value = get_path(blackboard, path)
    for f in filters:
        if f == "목록":
            if not isinstance(value, list):
                raise BadFilter(f"|목록 은 리스트에만 쓸 수 있음: {path}")
            value = ", ".join(str(v) for v in value)
        else:
            value = attach_particle(str(value), f)
    return str(value)


def interpolate(text: str, blackboard: dict) -> str:
    """문장 속 "{{경로}}"·"{{경로|조사}}" 를 모두 블랙보드 값의 문자열로 치환."""
    return _PLACEHOLDER.sub(lambda m: _render(m.group(1), blackboard), text)


def resolve(value: Any, blackboard: dict) -> Any:
    """params 값 안의 "$경로"·"{{경로}}" 를 블랙보드 값으로 치환. dict·list 는 안쪽까지 치환."""
    if isinstance(value, str) and value.startswith("$"):
        return get_path(blackboard, value[1:])
    if isinstance(value, str) and "{{" in value:
        return interpolate(value, blackboard)
    if isinstance(value, dict):
        return {k: resolve(v, blackboard) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, blackboard) for v in value]
    return value
