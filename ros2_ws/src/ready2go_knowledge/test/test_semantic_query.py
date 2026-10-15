"""#302 TTL 의미 조회. 실제 C 위치 조회를 대조하되 C 실행은 변경하지 않는다."""
from copy import deepcopy
from pathlib import Path

import pytest
from rdflib import Graph, Literal, RDF, RDFS

from ready2go_knowledge.core import ontology
from ready2go_knowledge.core.semantic_query import NS, SemanticCatalog, load_ttl

ROOT = Path(__file__).resolve().parents[4]
TTL = ROOT / "knowledge/examples/p3_semantics.ttl"


def catalog(path=TTL):
    onto = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")
    retired = (ROOT / "config/yolo_retired_classes.txt").read_text().splitlines()
    return load_ttl(path, active_items=onto["world"]["items"], retired_items=retired)


def test_class_inheritance_and_source():
    result = catalog().query_class("귀중품")
    assert result["items"] == ["car_key"]
    assert result["source"]["id"] == "Valuables"
    assert result["source"]["kind"] == "class"
    assert len(result["source"]["sha256"]) == 64
    assert result["evidence"] == {"car_key": {"class_paths": [["Key", "Valuables"]]}}
    assert catalog().query_class("Key")["items"] == ["car_key"]
    assert catalog().query_class("Item")["items"] == ["airpods_case", "car_key", "lip_balm"]


def test_list_alias_deduplication_and_result_isolation(tmp_path):
    path = tmp_path / "duplicate.ttl"
    path.write_text(TTL.read_text() + "\nr2g:commute_set r2g:hasItem r2g:car_key .\n")
    index = catalog(path)
    result = index.query_list("출근 세트")
    assert result["items"] == ["airpods_case", "car_key", "lip_balm"]
    assert result["source"]["id"] == "commute_set"
    assert result["evidence"]["car_key"] == {"list": "commute_set"}
    result["items"].clear()
    result["source"]["id"] = "changed"
    assert index.query_list("commute_set")["source"]["id"] == "commute_set"
    assert len(index.query_list("commute_set")["items"]) == 3


@pytest.mark.parametrize("tail, error", [
    ("r2g:carrot_pen a r2g:Item .", "은퇴 물품"),
    ("r2g:missing_item a r2g:Item .", "미등록"),
    ("r2g:car_key a r2g:MissingClass .", "종류 참조"),
    ("r2g:Key rdfs:subClassOf r2g:MissingClass .", "상위 분류"),
    ("r2g:Item rdfs:subClassOf r2g:Key .", "분류 순환"),
    ("r2g:commute_set r2g:hasItem r2g:missing_item .", "목록의 물품 참조"),
    ("r2g:commute_set r2g:hasItem r2g:commute_set .", "목록의 물품 참조"),
    ("r2g:car_key a rdfs:Class .", "선언 충돌"),
    ("r2g:car_key r2g:located_in r2g:drawer_top .", "허용하지 않은 관계"),
    ("r2g:drawer_top r2g:open true .", "허용하지 않은 관계"),
    ("r2g:car_key rdfs:label r2g:Key .", "이름·별칭"),
    ("r2g:car_key rdfs:label 42 .", "이름·별칭"),
    ("r2g:unknown rdfs:label '알 수 없음' .", "종류 선언"),
])
def test_reject_invalid_semantics(tmp_path, tail, error):
    path = tmp_path / "bad.ttl"
    path.write_text(TTL.read_text() + "\n" + tail + "\n")
    with pytest.raises(ValueError, match=error):
        catalog(path)


def test_unknown_and_ambiguous_queries_fail(tmp_path):
    path = tmp_path / "alias.ttl"
    path.write_text(TTL.read_text() + '\nr2g:Key r2g:alias_ko "귀중품" .\n')
    index = catalog(path)
    for kind, query in (("class", "귀중품"), ("class", "없는 분류"),
                        ("list", "없는 목록"), ("list", ""), ("class", None)):
        with pytest.raises(ValueError):
            getattr(index, "query_" + kind)(query)
    assert index.query_class("Valuables")["items"] == ["car_key"]


def test_multiple_inheritance_and_empty_class():
    graph = Graph().parse(TTL, format="turtle")
    graph.add((NS.Other, RDF.type, RDFS.Class))
    graph.add((NS.Key, RDFS.subClassOf, NS.Other))
    graph.add((NS.Empty, RDF.type, RDFS.Class))
    active = ["car_key", "airpods_case", "lip_balm"]
    index = SemanticCatalog(graph, active_items=active, digest="fixture")
    assert index.query_class("Other")["evidence"]["car_key"]["class_paths"] == [["Key", "Other"]]
    assert index.query_class("Empty")["items"] == []
    graph.add((NS.Empty, RDFS.label, Literal("나중에 변경")))
    assert index.query_class("Empty")["source"]["name_ko"] == "Empty"


def test_meaning_and_c_item_query_keep_runner_state_separate():
    from ready2go_runner.core.ontology_query import query

    onto = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")
    before = deepcopy(onto)
    index = catalog()
    result = index.query_list("commute_set")
    # 등록됐지만 초기 위치가 없는 물품도 E는 반환. 제외·안내는 C 정책이다.
    assert "airpods_case" in result["items"]
    unknown = query({"item": "airpods_case"}, onto["state"], onto["world"])
    assert unknown.error_code == "UNKNOWN_ITEM"
    state = deepcopy(onto["state"])
    state["located_in"]["car_key"] = "drawer_bottom"
    answer = query({"item": "car_key"}, state, onto["world"])
    assert answer.success and answer.output["drawer_id"] == "drawer_bottom"
    assert index.query_list("commute_set") == result
    assert onto == before
    assert query({"list": "commute_set"}, state, onto["world"]).error_code == "NOT_SUPPORTED"
    assert query({"class": "Valuables"}, state, onto["world"]).error_code == "NOT_SUPPORTED"
