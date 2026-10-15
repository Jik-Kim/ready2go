"""#302 P3 의미 조회. Runner 현재 상태와 실행 정책은 다루지 않는다.

TTL은 명시한 로컬 파일에서만 읽는다. 기존 JSON-LD load()나 운영 manifest에
자동 연결하지 않으며, RDF 파싱 뒤 명시적으로 상위 분류 경로를 탐색한다.
"""
from __future__ import annotations

from collections import deque
from hashlib import sha256
from pathlib import Path
import re

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef, XSD

NS = Namespace("https://ready2go.local/onto#")
_PREDICATES = {RDF.type, RDFS.subClassOf, RDFS.label, NS.alias_ko, NS.hasItem}


def _key(node) -> str:
    value = str(node)
    key = value[len(str(NS)):]
    if not isinstance(node, URIRef) or not value.startswith(str(NS)) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        raise ValueError(f"프로젝트 의미 ID가 필요합니다: {node}")
    return key


def _keys(values, name):
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name}는 물품 키 모음이어야 합니다")
    result = frozenset(values)
    if any(not isinstance(key, str) or not key for key in result):
        raise ValueError(f"{name}의 물품 키가 올바르지 않습니다")
    return result


def load_ttl(path: str | Path, *, active_items, retired_items=()) -> SemanticCatalog:
    """활성 등록부를 대조해 TTL 의미 카탈로그를 읽는다. 위치는 입력받지 않는다."""
    raw = Path(path).read_bytes()
    graph = Graph().parse(data=raw.decode("utf-8"), format="turtle", publicID=str(NS))
    return SemanticCatalog(graph, active_items=active_items, retired_items=retired_items,
                           digest=sha256(raw).hexdigest())


class SemanticCatalog:
    """검증한 의미 지식의 읽기 전용 조회. 반환 dict는 매번 새로 만든다."""

    def __init__(self, graph: Graph, *, active_items, retired_items=(), digest: str):
        active = _keys(active_items, "active_items")
        retired = _keys(retired_items, "retired_items")
        self._graph = Graph()
        for triple in graph:
            self._graph.add(triple)
        self._digest = digest
        self._classes = set(graph.subjects(RDF.type, RDFS.Class))
        self._lists = set(graph.subjects(RDF.type, NS.ItemList))
        self._items = set(graph.subjects(RDF.type)) - self._classes - self._lists
        declared = self._classes | self._lists | self._items
        for node in declared:
            _key(node)
        for subject, predicate, value in graph:
            if predicate not in _PREDICATES:
                raise ValueError(f"의미 그래프에 허용하지 않은 관계: {predicate}")
            if subject not in declared:
                raise ValueError(f"종류 선언이 없는 참조: {subject}")
            if predicate in {RDFS.label, NS.alias_ko} and (
                not isinstance(value, Literal) or not str(value).strip()
                or value.datatype not in {None, XSD.string, RDF.langString}
            ):
                raise ValueError(f"이름·별칭은 비어 있지 않은 문자열이어야 합니다: {subject}")
        for node in self._classes:
            if set(graph.objects(node, RDF.type)) != {RDFS.Class}:
                raise ValueError(f"클래스/물품/목록 선언 충돌: {_key(node)}")
        for node in self._lists:
            if set(graph.objects(node, RDF.type)) != {NS.ItemList}:
                raise ValueError(f"클래스/물품/목록 선언 충돌: {_key(node)}")
        for node in self._items:
            key = _key(node)
            if key in retired or key not in active:
                raise ValueError(f"미등록 또는 은퇴 물품: {key}")
            if not set(graph.objects(node, RDF.type)) <= self._classes:
                raise ValueError(f"정의되지 않은 종류 참조: {key}")
        for child, parent in graph.subject_objects(RDFS.subClassOf):
            if child not in self._classes or parent not in self._classes:
                raise ValueError("정의되지 않은 상위 분류 참조")
        for group, member in graph.subject_objects(NS.hasItem):
            if group not in self._lists or member not in self._items:
                raise ValueError(f"목록의 물품 참조가 없습니다: {group} -> {member}")
        self._parents = {node: sorted(graph.objects(node, RDFS.subClassOf), key=str)
                         for node in self._classes}
        visiting, visited = set(), set()

        def visit(node):
            if node in visiting:
                raise ValueError(f"분류 순환: {_key(node)}")
            if node in visited:
                return
            visiting.add(node)
            for parent in self._parents[node]:
                visit(parent)
            visiting.remove(node)
            visited.add(node)

        for node in sorted(self._classes, key=str):
            visit(node)

    def _name(self, node):
        labels = sorted(self._graph.objects(node, RDFS.label),
                        key=lambda label: (label.language != "ko", str(label)))
        return str(labels[0]) if labels else _key(node)

    def _select(self, query, nodes):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("조회 이름이 필요합니다")
        query = query.strip()
        exact = [node for node in nodes if _key(node) == query]
        matches = exact or [node for node in nodes if query in {
            str(value) for predicate in (RDFS.label, NS.alias_ko)
            for value in self._graph.objects(node, predicate)}]
        if len(matches) != 1:
            raise ValueError(f"조회 대상이 없거나 모호합니다: {query}")
        return matches[0]

    def _path(self, start, goal):
        queue = deque([[start]])
        seen = {start}
        while queue:
            path = queue.popleft()
            if path[-1] == goal:
                return [_key(node) for node in path]
            for parent in self._parents[path[-1]]:
                if parent not in seen:
                    seen.add(parent)
                    queue.append(path + [parent])
        return None

    def _result(self, kind, node, evidence):
        return {"items": sorted(evidence),
                "source": {"kind": kind, "id": _key(node), "name_ko": self._name(node),
                           "sha256": self._digest},
                "evidence": evidence}

    def query_class(self, query: str) -> dict:
        """분류 키·이름·별칭 조회. 상속 경로를 근거로 반환한다."""
        target = self._select(query, self._classes)
        evidence = {}
        for item in sorted(self._items, key=str):
            paths = [path for cls in sorted(self._graph.objects(item, RDF.type), key=str)
                     if (path := self._path(cls, target)) is not None]
            if paths:
                evidence[_key(item)] = {"class_paths": paths}
        return self._result("class", target, evidence)

    def query_list(self, query: str) -> dict:
        """목록의 중복을 제거해 기존 물품 키·출처를 반환한다. 실행 순서가 아니다."""
        target = self._select(query, self._lists)
        evidence = {_key(item): {"list": _key(target)}
                    for item in sorted(self._graph.objects(target, NS.hasItem), key=str)}
        return self._result("list", target, evidence)

    def names(self, kind: str, query: str) -> list[str]:
        """등록부의 키·이름·별칭. 음성 선택지는 동일 그래프에서만 얻는다."""
        if kind not in ('list', 'class'):
            raise ValueError('목록 또는 분류가 필요합니다')
        node = self._select(query, self._lists if kind == 'list' else self._classes)
        return sorted({_key(node), *(str(value) for predicate in (RDFS.label, NS.alias_ko)
                       for value in self._graph.objects(node, predicate))})
