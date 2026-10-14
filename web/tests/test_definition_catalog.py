"""이슈 #267 5단계 등록 정의 로딩과 스냅샷 경계를 검증한다."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from ready2go_web.core.definition_catalog import (
    DEFAULT_ONTOLOGY_FILE,
    DEFAULT_TASKS_DIR,
    DefinitionSettings,
    load_definition_snapshot,
    settings_from_env,
)


# 이 시험 파일에서 저장소 루트까지 세 단계 위다.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_default_definition_settings_match_runner_container_paths() -> None:
    """환경변수가 없으면 Runner가 사용하는 컨테이너 기본 경로와 일치한다."""

    # 빈 환경 mapping을 주입해 호스트 설정의 영향을 제거한다.
    settings = settings_from_env({})

    # 온톨로지는 Runner launch의 RUNNER_ONTOLOGY_FILE 기본값과 같아야 한다.
    assert settings.ontology_file == Path(DEFAULT_ONTOLOGY_FILE)
    # 태스크는 Runner 노드의 tasks_dir 기본값과 같아야 한다.
    assert settings.tasks_dir == Path(DEFAULT_TASKS_DIR)


def test_definition_settings_accept_local_repository_paths() -> None:
    """호스트 수동 실행에서는 저장소의 실제 원본 경로를 명시할 수 있다."""

    # 상대 경로를 넣어도 로더가 실제 절대 경로로 고정해야 한다.
    settings = settings_from_env(
        {
            "RUNNER_ONTOLOGY_FILE": "knowledge/robot_ontology.jsonld",
            "WEB_TASKS_DIR": "tasks",
        }
    )

    # 현재 시험 cwd가 저장소 루트이므로 manifest 절대 경로와 일치한다.
    assert settings.ontology_file == REPOSITORY_ROOT / "knowledge/robot_ontology.jsonld"
    # 태스크 폴더도 같은 저장소 루트를 기준으로 고정된다.
    assert settings.tasks_dir == REPOSITORY_ROOT / "tasks"


@pytest.mark.parametrize("key", ["RUNNER_ONTOLOGY_FILE", "WEB_TASKS_DIR"])
def test_definition_settings_reject_empty_paths(key: str) -> None:
    """빈 원본 경로를 현재 디렉터리로 오해하지 않는다."""

    # 검사 대상 하나만 공백으로 덮고 나머지는 기본값을 사용한다.
    with pytest.raises(ValueError, match=key):
        settings_from_env({key: "   "})


def test_real_registered_definitions_are_loaded_with_common_ontology_loader() -> None:
    """실제 manifest·tasks에서 물품·목록·스킬·태스크와 출처를 함께 만든다."""

    # Runner가 사용하는 실제 저장소 원본을 명시한다.
    settings = DefinitionSettings(
        ontology_file=REPOSITORY_ROOT / "knowledge/robot_ontology.jsonld",
        tasks_dir=REPOSITORY_ROOT / "tasks",
    )
    # loaded_at을 재현 가능하게 검증하기 위해 UTC 시계를 주입한다.
    fixed_now = lambda: datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)

    # 공통 ontology.load와 태스크 요약을 한 번 실행한다.
    snapshot = load_definition_snapshot(settings, utcnow=fixed_now)

    # 응답 형식과 웹 파일 스냅샷 경계를 먼저 확인한다.
    assert snapshot["schema_version"] == 1
    assert snapshot["snapshot_kind"] == "web_file_snapshot"
    assert snapshot["loaded_at"] == "2026-10-13T10:00:00Z"
    assert snapshot["runner_hot_reload_applied"] is False

    # 원본 경로와 내용 해시가 있어 다른 배포 파일과 대조할 수 있어야 한다.
    manifest = snapshot["sources"]["ontology_manifest"]
    assert manifest["path"] == str(settings.ontology_file)
    assert len(manifest["sha256"]) == 64
    assert snapshot["sources"]["tasks_dir"]["path"] == str(settings.tasks_dir)

    # 실제 등록 원본의 대표 ID가 각 구역에 포함됐는지 확인한다.
    definitions = snapshot["definitions"]
    assert "car_key" in {item["id"] for item in definitions["items"]}
    assert "drawer_top" in {place["id"] for place in definitions["places"]}
    assert "commute_set" in {entry["id"] for entry in definitions["lists"]}
    assert "pick" in {skill["id"] for skill in definitions["skills"]}
    assert "find_item" in {task["id"] for task in definitions["tasks"]}

    # 현재 상태는 /robot_state의 책임이므로 등록 정의 응답에 섞이지 않아야 한다.
    assert "state" not in definitions
    # 집계값은 실제 응답 배열 길이와 각각 일치해야 한다.
    for name, count in snapshot["counts"].items():
        assert count == len(definitions[name])


def test_duplicate_task_ids_are_rejected(tmp_path: Path) -> None:
    """서로 다른 파일의 같은 task_id를 임의로 하나 선택하지 않는다."""

    # 공통 온톨로지는 실제 원본을 사용하고 태스크 폴더만 격리한다.
    first = {"task_id": "duplicate", "sequence": []}
    # 두 파일이 같은 task_id를 가지도록 첫 번째 원본을 쓴다.
    (tmp_path / "a.json").write_text(json.dumps(first), encoding="utf-8")
    # 두 번째 파일도 같은 ID를 사용해 충돌 상황을 만든다.
    (tmp_path / "b.json").write_text(json.dumps(first), encoding="utf-8")
    # 시험용 설정은 실제 manifest와 임시 태스크 폴더를 결합한다.
    settings = DefinitionSettings(
        ontology_file=REPOSITORY_ROOT / "knowledge/robot_ontology.jsonld",
        tasks_dir=tmp_path,
    )

    # 어느 파일을 등록할지 추정하지 않고 명시적인 오류를 내야 한다.
    with pytest.raises(ValueError, match="중복 task_id"):
        load_definition_snapshot(settings)


def test_missing_definition_sources_are_reported(tmp_path: Path) -> None:
    """존재하지 않는 manifest와 태스크 디렉터리를 빈 정의로 처리하지 않는다."""

    # 먼저 manifest가 없는 설정을 만든다.
    missing_manifest = DefinitionSettings(
        ontology_file=tmp_path / "missing.jsonld",
        tasks_dir=REPOSITORY_ROOT / "tasks",
    )
    # 누락 경로가 FileNotFoundError로 드러나야 한다.
    with pytest.raises(FileNotFoundError, match="manifest"):
        load_definition_snapshot(missing_manifest)

    # 다음에는 실제 manifest와 존재하지 않는 태스크 폴더를 조합한다.
    missing_tasks = DefinitionSettings(
        ontology_file=REPOSITORY_ROOT / "knowledge/robot_ontology.jsonld",
        tasks_dir=tmp_path / "missing-tasks",
    )
    # 태스크 누락도 정상 빈 목록 대신 오류로 반환해야 한다.
    with pytest.raises(FileNotFoundError, match="태스크 디렉터리"):
        load_definition_snapshot(missing_tasks)
