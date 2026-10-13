"""웹 시작 시 등록 정의 오류가 상태 서버 시작을 막지 않는지 검증한다."""

from __future__ import annotations

from ready2go_web.__main__ import _load_definitions_for_startup


def test_invalid_definition_environment_isolated_from_server_startup(monkeypatch) -> None:
    """빈 정의 경로를 Flask 전체 예외 대신 정의 API 오류값으로 변환한다."""

    # 설정 해석 단계에서 실패하도록 온톨로지 환경변수에 공백만 지정한다.
    monkeypatch.setenv("RUNNER_ONTOLOGY_FILE", "   ")
    # 태스크 경로의 기본값 여부와 관계없이 첫 설정 오류가 안정적으로 포착돼야 한다.
    monkeypatch.setenv("WEB_TASKS_DIR", "/tasks")

    # 실제 main이 사용하는 시작 보조 함수를 호출해 ROS runtime 시작 전 경계를 확인한다.
    snapshot, error = _load_definitions_for_startup()

    # 정의는 준비되지 않았지만 호출 자체는 예외를 내지 않아 상태 서버가 계속 시작할 수 있다.
    assert snapshot is None
    # 정의 API가 원인을 구분할 수 있도록 오류 종류와 설정 이름을 보존한다.
    assert error is not None
    assert error.startswith("ValueError:")
    assert "RUNNER_ONTOLOGY_FILE" in error
