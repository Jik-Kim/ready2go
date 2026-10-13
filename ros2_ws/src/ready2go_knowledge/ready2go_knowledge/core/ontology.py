"""로봇 온톨로지 core (ROS 비의존) — docs/ontology.md 7.5, 7.8.

Phase 1 범위: 로딩, 상태 읽기/쓰기, 스킬 조건(pre) 확인, 결과(effect) 반영, 목록 참조 검사.
Phase 2: verify·hold, 관측 우선 갱신 / Phase 3: 클래스 추론, 시작 시 전체 정합성 검사.
상태 형태: state[predicate][subject] = value
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

_OPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b}



GRASP_REQUIRED = {"grip_force", "grasp_verified"}
# 선택: RG2 로 실제로 잡은 폭(m) → 비교할 size_m 칸 (짧은 변 잡기 1, 긴 변 양끝 잡기 0)
GRASP_WIDTHS = {"grasp_width_m": 1, "grasp_width_long_m": 0}

def _json_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"중복 JSON 키: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = json.load(f, object_pairs_hook=_json_object)
    if not isinstance(data, dict):
        raise ValueError(f"JSON 객체가 필요합니다: {path}")
    return data


def _section(data: dict, key: str, path: Path) -> dict:
    section = data.get(key)
    if not isinstance(section, dict):
        raise ValueError(f"{path}: {key} 객체가 필요합니다")
    return section


def _source(base: Path, reference: Any) -> Path:
    if not isinstance(reference, str) or not reference:
        raise ValueError("참조 경로는 비어 있지 않은 문자열이어야 합니다")
    return (base / reference).resolve()


def _read_places(path: Path) -> dict:
    # PyYAML은 선언된 실행 의존성. safe loader에 중복 키 검사만 추가한다.
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        pass

    def unique_mapping(loader, node):
        loader.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=True)
            if key in result:
                raise ValueError(f"중복 YAML 키: {key}")
            result[key] = loader.construct_object(value_node, deep=True)
        return result

    UniqueLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
    )
    with path.open(encoding="utf-8") as f:
        settings = yaml.load(f, Loader=UniqueLoader)
    if not isinstance(settings, dict):
        raise ValueError(f"장소 설정 객체가 필요합니다: {path}")
    return settings


def load(path: str | Path, *, snapshot: str | Path | None = None) -> dict:
    """진입점의 참조를 읽어 기존 classes/world/state/skills 구조로 반환.

    상대 경로는 진입점 파일의 폴더 기준이다. state는 초기화용 프리셋이며
    실제 로봇 상태 확인이나 Runner 현재 상태 덮어쓰기를 수행하지 않는다.
    snapshot은 선택 초기 상태 파일이며 상대 경로는 진입점 폴더 기준이다.
    생략하면 sources.initial_state를 사용한다. 선택 결과는 새로운 조회 구조일 뿐
    C 기동/reset·실제 현재 상태에 자동 적용하지 않는다.
    단일 파일 형식도 기존 호출자·외부 테스트 데이터용으로 계속 읽을 수 있다.
    """
    path = Path(path).resolve()
    manifest = _read_json(path)
    if "sources" not in manifest:
        if snapshot is not None:
            raise ValueError("snapshot 선택은 sources manifest 진입점이 필요합니다")
        return manifest
    sources = _section(manifest, "sources", path)
    required = {"classes", "world", "skills", "initial_state", "places", "item_grasp"}
    if set(sources) != required:
        raise ValueError(f"sources 키는 {sorted(required)}여야 합니다")
    classes_path = _source(path.parent, sources["classes"])
    world_path = _source(path.parent, sources["world"])
    if snapshot is not None and not isinstance(snapshot, (str, Path)):
        raise ValueError("snapshot은 파일 경로 문자열 또는 Path여야 합니다")
    state_path = _source(path.parent, sources["initial_state"] if snapshot is None else str(snapshot))
    classes = _section(_read_json(classes_path), "classes", classes_path)
    world = _section(_read_json(world_path), "world", world_path)
    state = _section(_read_json(state_path), "state", state_path)
    references = sources["skills"]
    if not isinstance(references, list) or not references:
        raise ValueError("sources.skills는 비어 있지 않은 파일 경로 배열이어야 합니다")
    skills = {}
    for reference in references:
        skill_path = _source(path.parent, reference)
        definitions = _section(_read_json(skill_path), "skills", skill_path)
        for name, definition in definitions.items():
            if name in skills:
                raise ValueError(f"중복 스킬 식별자: {name}")
            if not isinstance(definition, dict):
                raise ValueError(f"스킬 정의 객체가 필요합니다: {name}")
            skills[name] = definition

    places = _section(world, "places", world_path)
    items = _section(world, "items", world_path)
    _section(world, "lists", world_path)
    # 장소 물리 값은 YAML 한 곳에만 작성. 누락·이중 정의는 추측하지 않는다.
    settings = _read_places(_source(path.parent, sources["places"]))
    for name, definition in places.items():
        if not isinstance(definition, dict):
            raise ValueError(f"장소 정의 객체가 필요합니다: {name}")
        physical = settings.get(name)
        if not isinstance(physical, dict):
            raise ValueError(f"장소 설정이 없습니다: {name}")
        overlap = definition.keys() & physical.keys()
        if overlap:
            raise ValueError(f"world와 YAML의 중복 설정: {name}.{sorted(overlap)}")
        # 미측정 null은 그대로 보존한다. 동작에 필요한 값의 준비 여부는
        # 사용자가 이 장소를 실행할 때 확인해야 한다.
        definition.update(physical)
    grasp = _read_places(_source(path.parent, sources["item_grasp"]))
    if set(grasp) != set(items):
        raise ValueError("물품과 파지 설정의 식별자가 일치하지 않습니다")
    for name, item in items.items():
        if not isinstance(item, dict):
            raise ValueError(f"물품 정의 객체가 필요합니다: {name}")
        size = item.get("size_m")
        if not isinstance(size, list) or len(size) != 3 or any(
            isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v) or v <= 0 for v in size
        ):
            raise ValueError(f"size_m은 양수 유한값 3개여야 합니다: {name}")
        config = grasp[name]
        if not isinstance(config, dict) or not GRASP_REQUIRED <= set(config) <= GRASP_REQUIRED | GRASP_WIDTHS.keys():
            raise ValueError(f"물품 파지 설정 형식 오류: {name}")
        for key, side in GRASP_WIDTHS.items():          # 실제로 잡은 폭(선택) — 그 변(외접 박스) 이하 양수 [B 실측]
            if key in config:
                w = config[key]
                if isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) or not 0 < w <= size[side]:
                    raise ValueError(f"{key}는 0 초과·size_m[{side}] 이하 유한값이어야 합니다: {name}")
        if not isinstance(config["grasp_verified"], bool):
            raise ValueError(f"grasp_verified는 bool이어야 합니다: {name}")
        force = config["grip_force"]
        if force is not None and (
            isinstance(force, bool) or not isinstance(force, (int, float))
            or not math.isfinite(force) or force <= 0
        ):
            raise ValueError(f"grip_force는 null 또는 양수 유한값이어야 합니다: {name}")
        if config["grasp_verified"] and force is None:
            raise ValueError(f"검증 완료 물품의 파지 힘이 없습니다: {name}")
        if item.keys() & config.keys():
            raise ValueError(f"world와 YAML의 중복 파지 설정: {name}")
        item.update(config)
    for group in (items, places):
        for name, definition in group.items():
            if not isinstance(definition, dict) or definition.get("class") not in classes:
                raise ValueError(f"정의되지 않은 종류를 참조합니다: {name}")
    onto = {
        "@context": manifest.get("@context", {}),
        "classes": classes, "world": world, "state": state, "skills": skills,
    }
    locations = _section(state, "located_in", state_path)
    for item, place in locations.items():
        if item not in items or place not in places:
            raise ValueError(f"초기 위치의 물품/장소 참조가 없습니다: {item} -> {place}")
    errors = list_reference_errors(onto)
    if errors:
        raise ValueError("; ".join(errors))
    return onto

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


def require_grasp_settings(onto: dict, item: str) -> dict:
    """실물 실행 전 사용할 검증된 파지 설정. 미확정 힘을 기본값으로 바꾸지 않는다.

    호출 자체는 로봇을 움직이지 않는다. B/C가 파지·밀기·복구 경로에 연결해야 한다.
    """
    definition = onto["world"]["items"][item]
    if definition.get("grasp_verified") is not True or definition.get("grip_force") is None:
        raise ValueError(f"파지 설정 미확정: {item}")
    return {"grip_force": definition["grip_force"]}
