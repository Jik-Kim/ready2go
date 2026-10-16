"""등록 온톨로지·태스크·스킬을 웹용 읽기 전용 스냅샷으로 만든다.

이 모듈은 이슈 #267의 5단계 경계만 담당한다. 온톨로지는 Runner와 같은
``ready2go_knowledge.core.ontology.load``를 사용하고, 웹이 읽은 파일을 Runner가
실행 중 hot reload한 것처럼 표현하지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ready2go_knowledge.core import ontology
from ready2go_web.core.step_labels import task_step_labels


# 정의 API의 형식 버전은 ROS 계약이나 상태 API 버전과 독립적으로 관리한다.
DEFINITION_SCHEMA_VERSION = 1

# Runner launch가 사용하는 온톨로지 기본 경로와 같은 값을 웹 기본값으로 쓴다.
DEFAULT_ONTOLOGY_FILE = "/knowledge/robot_ontology.jsonld"

# Runner의 tasks_dir 기본값과 같은 컨테이너 경로를 웹 기본값으로 쓴다.
DEFAULT_TASKS_DIR = "/tasks"


@dataclass(frozen=True)
class DefinitionSettings:
    """웹이 한 번 읽을 등록 정의 원본 경로다."""

    # manifest는 classes·world·state·skills·장소·파지 원본을 결합하는 진입점이다.
    ontology_file: Path
    # 태스크는 Runner와 같은 디렉터리의 모든 JSON 정의를 읽는다.
    tasks_dir: Path


def settings_from_env(
    environ: Mapping[str, str] | None = None,
) -> DefinitionSettings:
    """Runner 온톨로지 경로와 웹 태스크 경로를 환경변수에서 읽는다."""

    # 시험은 별도 mapping을 주입하고 실제 실행은 현재 프로세스 환경을 사용한다.
    values = os.environ if environ is None else environ

    # Runner와 웹이 같은 manifest를 가리키도록 기존 RUNNER_ONTOLOGY_FILE을 재사용한다.
    ontology_text = values.get("RUNNER_ONTOLOGY_FILE", DEFAULT_ONTOLOGY_FILE).strip()
    # tasks_dir는 Runner의 ROS parameter이므로 웹에는 명시적인 경로 변수를 둔다.
    tasks_text = values.get("WEB_TASKS_DIR", DEFAULT_TASKS_DIR).strip()

    # 빈 경로는 실행 위치에 따라 현재 폴더를 뜻할 수 있으므로 명시적으로 거절한다.
    if not ontology_text:
        raise ValueError("RUNNER_ONTOLOGY_FILE은 비어 있지 않아야 합니다")
    # 태스크 경로도 같은 이유로 비어 있는 문자열을 허용하지 않는다.
    if not tasks_text:
        raise ValueError("WEB_TASKS_DIR은 비어 있지 않아야 합니다")

    # resolve로 cwd가 달라져도 REST에 기록할 실제 절대 경로를 고정한다.
    ontology_file = Path(ontology_text).expanduser().resolve()
    # 태스크 폴더 역시 같은 규칙으로 절대 경로를 만든다.
    tasks_dir = Path(tasks_text).expanduser().resolve()

    # 검증된 불변 설정만 시작 코드와 로더에 전달한다.
    return DefinitionSettings(ontology_file=ontology_file, tasks_dir=tasks_dir)


def _utc_now() -> datetime:
    """웹 정의를 읽은 시각을 시간대가 포함된 UTC로 만든다."""

    # 서버 로컬 시간대와 무관한 절대 시각을 기록한다.
    return datetime.now(timezone.utc)


def _isoformat_utc(value: datetime) -> str:
    """시간대가 있는 datetime을 REST용 UTC ISO 8601 문자열로 변환한다."""

    # 시간대 없는 값은 PC별로 다르게 해석되므로 시험 주입값도 거절한다.
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("정의 로딩 시각은 timezone-aware datetime이어야 합니다")
    # 브라우저가 바로 처리할 수 있도록 UTC의 +00:00 표기를 Z로 정규화한다.
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    """원본 파일 내용을 식별하는 SHA-256을 계산한다."""

    # 파일을 이진 모드로 읽어 줄바꿈 변환 없이 실제 배포 내용을 해시한다.
    digest = hashlib.sha256()
    # 큰 파일도 한꺼번에 메모리에 올리지 않도록 고정 크기 블록으로 읽는다.
    with path.open("rb") as stream:
        # 빈 bytes가 반환될 때까지 반복한다.
        for block in iter(lambda: stream.read(64 * 1024), b""):
            # 읽은 블록을 순서대로 해시에 반영한다.
            digest.update(block)
    # REST와 문서에서 비교할 수 있는 소문자 16진수 문자열을 반환한다.
    return digest.hexdigest()


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """태스크 JSON의 중복 키를 조용히 덮어쓰지 않는 객체 hook이다."""

    # 표준 json.loads가 만들 객체를 직접 구성한다.
    result: dict[str, Any] = {}
    # 원본에 등장한 순서대로 모든 키와 값을 확인한다.
    for key, value in pairs:
        # 같은 키가 두 번 나오면 어느 정의를 쓸지 추정하지 않고 실패한다.
        if key in result:
            raise ValueError(f"중복 JSON 키: {key}")
        # 처음 본 키만 결과 객체에 보존한다.
        result[key] = value
    # 완성된 JSON 객체를 json 모듈에 반환한다.
    return result


def _read_task(path: Path) -> dict[str, Any]:
    """태스크 파일 하나를 JSON 객체로 읽는다."""

    # UTF-8을 명시해 운영체제 기본 인코딩 차이를 제거한다.
    with path.open(encoding="utf-8") as stream:
        # 중복 키 검사 hook과 함께 JSON을 해석한다.
        value = json.load(stream, object_pairs_hook=_json_object)
    # 태스크 최상위는 계약상 객체여야 하므로 배열·문자열을 거절한다.
    if not isinstance(value, dict):
        raise ValueError(f"태스크 JSON 객체가 필요합니다: {path}")
    # 호출자가 원본을 바꾸지 못하도록 새 객체를 반환한다.
    return value


def _require_mapping(container: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """공통 로더 결과에서 필요한 객체 구역을 안전하게 꺼낸다."""

    # classes·world·skills 중 요청한 구역을 읽는다.
    value = container.get(key)
    # 누락되거나 객체가 아니면 빈 정의로 추정하지 않고 로딩 오류로 처리한다.
    if not isinstance(value, Mapping):
        raise ValueError(f"온톨로지 {key} 객체가 필요합니다")
    # 검증된 mapping만 다음 요약 단계에 전달한다.
    return value


def _count_step_nodes(value: Any) -> int:
    """분기·반복 내부까지 태스크의 식별된 단계 수를 센다."""

    # 객체는 자신이 step id를 가지는지 확인하고 모든 자식도 순회한다.
    if isinstance(value, Mapping):
        # 비어 있지 않은 문자열 id가 있을 때만 실행 단계 한 개로 센다.
        own = 1 if isinstance(value.get("id"), str) and value["id"].strip() else 0
        # params 같은 중첩 객체에 id가 있어도 동일 규칙으로 안전하게 합산한다.
        return own + sum(_count_step_nodes(child) for child in value.values())
    # 배열은 분기 본문·sequence·finally의 각 원소를 같은 방식으로 순회한다.
    if isinstance(value, list):
        return sum(_count_step_nodes(child) for child in value)
    # 문자열·숫자·null은 실행 단계가 아니다.
    return 0


def _summarize_classes(classes: Mapping[str, Any]) -> list[dict[str, Any]]:
    """클래스 ID와 표시명·상위 클래스만 브라우저에 제공한다."""

    # ID 순서가 파일 순서나 플랫폼에 좌우되지 않도록 정렬한다.
    summaries: list[dict[str, Any]] = []
    # 각 클래스 정의를 독립적으로 검증하고 요약한다.
    for class_id in sorted(classes):
        # 클래스 정의는 객체여야 한다.
        definition = classes[class_id]
        # 잘못된 형식을 화면에서 추정하지 않고 로딩 오류로 만든다.
        if not isinstance(definition, Mapping):
            raise ValueError(f"클래스 정의 객체가 필요합니다: {class_id}")
        # UI에 필요한 식별자·한국어 이름·상위 클래스만 복사한다.
        summaries.append(
            {
                "id": class_id,
                "name_ko": definition.get("name_ko"),
                "subclass_of": definition.get("subClassOf"),
            }
        )
    # 정렬된 읽기 전용 응답용 목록을 반환한다.
    return summaries


def _summarize_named_world_section(
    section: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """물품·장소 정의의 표시 필드를 원본 ID와 함께 요약한다."""

    # 브라우저가 사용할 정의 목록을 ID 순서로 만든다.
    summaries: list[dict[str, Any]] = []
    # 등록된 모든 개체를 빠뜨리지 않고 순회한다.
    for definition_id in sorted(section):
        # 개별 정의 객체를 가져온다.
        definition = section[definition_id]
        # 객체가 아니면 이름이나 클래스를 추측할 수 없으므로 실패한다.
        if not isinstance(definition, Mapping):
            raise ValueError(f"등록 정의 객체가 필요합니다: {definition_id}")
        # UI 표시와 등록 여부 확인에 필요한 필드만 깊은 복사한다.
        summaries.append(
            {
                "id": definition_id,
                "name_ko": definition.get("name_ko"),
                "class": definition.get("class"),
                "aliases_ko": copy.deepcopy(definition.get("aliases_ko", [])),
                "roles": copy.deepcopy(definition.get("roles", [])),
            }
        )
    # 파일 객체와 독립된 요약 목록을 반환한다.
    return summaries


def _summarize_lists(lists: Mapping[str, Any]) -> list[dict[str, Any]]:
    """목록 요청에 사용하는 등록 목록과 구성 물품 ID를 요약한다."""

    # 목록도 재현 가능한 ID 순서로 제공한다.
    summaries: list[dict[str, Any]] = []
    # 세계 정의에 등록된 모든 목록을 확인한다.
    for list_id in sorted(lists):
        # 개별 목록 정의를 읽는다.
        definition = lists[list_id]
        # 이름과 items를 가진 객체가 아니면 잘못된 등록 원본이다.
        if not isinstance(definition, Mapping):
            raise ValueError(f"목록 정의 객체가 필요합니다: {list_id}")
        # 구성 물품은 UI가 등록 준비물로 사용할 수 있도록 원본 배열을 복사한다.
        item_ids = definition.get("items")
        # 물품 ID 목록이 아니면 빈 목록으로 바꾸지 않고 오류로 알린다.
        if not isinstance(item_ids, list) or not all(isinstance(item, str) for item in item_ids):
            raise ValueError(f"목록 items 문자열 배열이 필요합니다: {list_id}")
        # 등록 목록의 식별·표시 필드를 응답에 추가한다.
        summaries.append(
            {
                "id": list_id,
                "name_ko": definition.get("name_ko"),
                "aliases_ko": copy.deepcopy(definition.get("aliases_ko", [])),
                "item_ids": list(item_ids),
            }
        )
    # 검증된 목록 요약을 반환한다.
    return summaries


def _summarize_skills(skills: Mapping[str, Any]) -> list[dict[str, Any]]:
    """스킬 표시명과 실제 사전 조건·효과를 읽기 전용으로 요약한다."""

    # 스킬 ID 순서로 안정된 응답을 만든다.
    summaries: list[dict[str, Any]] = []
    # 공통 ontology.load가 결합한 모든 스킬을 순회한다.
    for skill_id in sorted(skills):
        # 개별 스킬 정의를 읽는다.
        definition = skills[skill_id]
        # 스킬은 params·pre·effect 등을 가진 객체여야 한다.
        if not isinstance(definition, Mapping):
            raise ValueError(f"스킬 정의 객체가 필요합니다: {skill_id}")
        # 문자열 ID 목록으로 보여줄 수 있도록 params 객체의 키만 정렬한다.
        params = definition.get("params", {})
        # params가 객체가 아니면 스킬 계약을 잘못 해석하지 않고 실패한다.
        if not isinstance(params, Mapping):
            raise ValueError(f"스킬 params 객체가 필요합니다: {skill_id}")
        # UI가 실제 조건과 효과 개수를 표시하도록 원본 값을 깊은 복사한다.
        summaries.append(
            {
                "id": skill_id,
                "name_ko": definition.get("name_ko"),
                "kind": definition.get("kind"),
                "parameter_ids": sorted(params),
                "pre": copy.deepcopy(definition.get("pre", [])),
                "effect": copy.deepcopy(definition.get("effect")),
            }
        )
    # 파일 객체와 분리된 스킬 요약을 반환한다.
    return summaries


def _summarize_tasks(task_paths: list[Path], skills: Mapping[str, Any]) -> list[dict[str, Any]]:
    """태스크 디렉터리의 모든 JSON 파일을 등록 태스크 목록으로 만든다."""

    # 중복 task_id를 탐지하기 위한 집합이다.
    seen_ids: set[str] = set()
    # 브라우저에 전달할 태스크 요약을 파일 이름 순서로 만든다.
    summaries: list[dict[str, Any]] = []
    # glob 결과를 이미 정렬해 전달받으므로 그대로 순회한다.
    for path in task_paths:
        # 태스크 JSON 객체를 중복 키 검사와 함께 읽는다.
        definition = _read_task(path)
        # Runner가 식별에 사용하는 task_id를 가져온다.
        task_id = definition.get("task_id")
        # 비어 있거나 문자열이 아니면 파일명을 태스크 ID로 추정하지 않는다.
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError(f"비어 있지 않은 task_id가 필요합니다: {path}")
        # 같은 ID가 두 파일에 있으면 어떤 태스크가 등록됐는지 모호하므로 실패한다.
        if task_id in seen_ids:
            raise ValueError(f"중복 task_id: {task_id}")
        # 다음 파일과의 중복 검사를 위해 현재 ID를 기록한다.
        seen_ids.add(task_id)
        # trigger는 없는 태스크도 있으므로 null을 그대로 보존한다.
        trigger = definition.get("trigger")
        # 등록 태스크의 식별·대조에 필요한 필드만 응답에 추가한다.
        # 긴 운영 설명 전체는 관리자 UI가 사용하지 않으므로 REST payload에 복제하지 않는다.
        summaries.append(
            {
                "id": task_id,
                "trigger": copy.deepcopy(trigger),
                "step_labels": task_step_labels(definition, skills),
                "step_count": _count_step_nodes(
                    [definition.get("sequence", []), definition.get("finally", [])]
                ),
                "source_file": path.name,
                "sha256": _sha256(path),
            }
        )
    # ID 중복이 없는 태스크 요약 목록을 반환한다.
    return summaries


def load_definition_snapshot(
    settings: DefinitionSettings,
    *,
    utcnow: Callable[[], datetime] = _utc_now,
) -> dict[str, Any]:
    """공통 로더와 태스크 원본으로 웹 시작 시점의 정의 스냅샷을 만든다."""

    # 누락된 manifest를 공통 로더의 간접 오류로 숨기지 않고 명확히 알린다.
    if not settings.ontology_file.is_file():
        raise FileNotFoundError(f"온톨로지 manifest가 없습니다: {settings.ontology_file}")
    # 태스크 경로가 없거나 파일이면 빈 등록으로 추정하지 않고 실패한다.
    if not settings.tasks_dir.is_dir():
        raise FileNotFoundError(f"태스크 디렉터리가 없습니다: {settings.tasks_dir}")

    # Runner와 같은 공통 로더가 manifest의 classes·world·skills·설정을 결합한다.
    loaded = ontology.load(settings.ontology_file)
    # 결합 결과의 필수 최상위 구역을 각각 검증한다.
    classes = _require_mapping(loaded, "classes")
    # world에는 등록 물품·장소·목록이 들어 있다.
    world = _require_mapping(loaded, "world")
    # skills에는 manifest가 가리킨 모든 스킬 정의가 합쳐져 있다.
    skills = _require_mapping(loaded, "skills")
    # world의 물품 구역을 별도로 검증한다.
    items = _require_mapping(world, "items")
    # world의 장소 구역을 별도로 검증한다.
    places = _require_mapping(world, "places")
    # world의 목록 구역을 별도로 검증한다.
    lists = _require_mapping(world, "lists")

    # Runner와 동일하게 tasks_dir 바로 아래 JSON 파일만 등록 대상으로 본다.
    task_paths = sorted(settings.tasks_dir.glob("*.json"))
    # 등록 태스크가 하나도 없으면 정상 빈 목록으로 오해하지 않게 실패한다.
    if not task_paths:
        raise ValueError(f"등록 태스크 JSON이 없습니다: {settings.tasks_dir}")
    # 각 태스크를 검증하고 화면용 요약으로 변환한다.
    task_summaries = _summarize_tasks(task_paths, skills)
    # 나머지 온톨로지 구역도 같은 시점의 요약으로 만든다.
    class_summaries = _summarize_classes(classes)
    # 등록 물품의 ID·표시명·분류를 추출한다.
    item_summaries = _summarize_named_world_section(items)
    # 등록 장소의 ID·표시명·분류를 추출한다.
    place_summaries = _summarize_named_world_section(places)
    # P3 목록 요청용 등록 목록과 구성 물품을 추출한다.
    list_summaries = _summarize_lists(lists)
    # 실제 pre/effect가 포함된 스킬 요약을 추출한다.
    skill_summaries = _summarize_skills(skills)

    # 이 객체는 Runner 내부 snapshot이 아니라 웹이 파일에서 읽은 시점의 별도 스냅샷이다.
    return {
        "schema_version": DEFINITION_SCHEMA_VERSION,
        "snapshot_kind": "web_file_snapshot",
        "loaded_at": _isoformat_utc(utcnow()),
        "runner_hot_reload_applied": False,
        "sources": {
            "ontology_manifest": {
                "path": str(settings.ontology_file),
                "sha256": _sha256(settings.ontology_file),
            },
            "tasks_dir": {
                "path": str(settings.tasks_dir),
                "files": [summary["source_file"] for summary in task_summaries],
            },
        },
        "counts": {
            "classes": len(class_summaries),
            "items": len(item_summaries),
            "places": len(place_summaries),
            "lists": len(list_summaries),
            "skills": len(skill_summaries),
            "tasks": len(task_summaries),
        },
        "definitions": {
            "classes": class_summaries,
            "items": item_summaries,
            "places": place_summaries,
            "lists": list_summaries,
            "skills": skill_summaries,
            "tasks": task_summaries,
        },
    }
