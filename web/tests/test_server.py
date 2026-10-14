"""이슈 #267 Flask 정적 UI와 3단계 읽기 전용 REST 경계를 검증한다."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ready2go_web.core.state_cache import StateCache
from ready2go_web.server import (
    API_SCHEMA_VERSION,
    DEFINITIONS_API_PATH,
    POLL_INTERVAL_MS,
    PUBLIC_ASSETS,
    STATUS_API_PATH,
    create_app,
    settings_from_env,
)


@pytest.fixture
def client():
    """실제 TCP 포트를 열지 않는 Flask 시험 클라이언트를 만든다."""
    # 기본 web/ 루트를 사용하는 실제 app factory를 생성한다.
    app = create_app()
    # 시험 예외를 숨기지 않고 바로 pytest 실패로 전달하도록 설정한다.
    app.config.update(TESTING=True)
    # context manager가 요청 context와 client 자원을 시험 뒤 정리한다.
    with app.test_client() as test_client:
        yield test_client


def test_root_serves_existing_dashboard_html(client) -> None:
    """루트 요청이 기존 대시보드 HTML과 모바일 viewport를 반환한다."""
    response = client.get("/")

    # 정상 HTTP 응답과 HTML MIME 타입을 먼저 확인한다.
    assert response.status_code == 200
    assert response.mimetype == "text/html"

    # 기존 UI의 제목·viewport·목업 안내 요소가 Flask 제공 뒤에도 유지돼야 한다.
    body = response.get_data(as_text=True)
    assert "ROKEY · 출근 준비 도우미" in body
    assert 'name="viewport"' in body
    assert 'id="mockDataNotice"' in body
    assert '<script src="./status-api.js" defer></script>' in body

    # 읽기 전용 범위에서 제거한 작업 중단 버튼이 다시 나타나면 안 된다.
    assert 'id="stopTask"' not in body


@pytest.mark.parametrize(
    ("asset_name", "expected_mimetype"),
    [
        ("styles.css", "text/css"),
        ("app.js", "text/javascript"),
        ("demo-data.js", "text/javascript"),
        ("status-api.js", "text/javascript"),
    ],
)
def test_public_assets_are_served_with_expected_mimetype(
    client,
    asset_name: str,
    expected_mimetype: str,
) -> None:
    """allowlist의 CSS·JavaScript 파일이 비어 있지 않은 올바른 응답으로 제공된다."""
    response = client.get(f"/{asset_name}")

    # 브라우저가 파일을 실행·적용할 수 있도록 상태와 MIME 타입이 맞아야 한다.
    assert response.status_code == 200
    assert response.mimetype == expected_mimetype
    # 빈 200 응답은 화면을 구성할 수 없으므로 실제 내용도 확인한다.
    assert response.get_data()


def test_public_asset_allowlist_matches_current_dashboard_dependencies() -> None:
    """정적 공개 범위가 현재 HTML의 네 의존성으로 제한돼 있는지 확인한다."""
    assert PUBLIC_ASSETS == frozenset(
        {"app.js", "demo-data.js", "status-api.js", "styles.css"}
    )


@pytest.mark.parametrize(
    "path",
    [
        "/not-found",
        "/README.md",
        "/ready2go_web/server.py",
        "/../README.md",
        "/%2e%2e/README.md",
    ],
)
def test_unknown_and_private_paths_are_not_served(client, path: str) -> None:
    """존재하지 않는 파일·백엔드 코드·상위 경로 접근을 모두 404로 차단한다."""
    response = client.get(path)

    # 파일 존재 여부나 내부 경로 정보를 구분해 노출하지 않고 동일한 404를 반환한다.
    assert response.status_code == 404


def test_default_server_settings_are_local_only() -> None:
    """환경변수가 없으면 외부 공개 없이 기존 목업 포트 4173을 사용한다."""
    settings = settings_from_env({})

    assert settings.host == "127.0.0.1"
    assert settings.port == 4173


def test_server_settings_accept_explicit_mobile_access_values() -> None:
    """휴대폰 접속용 host와 포트를 환경변수로 변경할 수 있다."""
    settings = settings_from_env({"WEB_HOST": "0.0.0.0", "WEB_PORT": "5173"})

    assert settings.host == "0.0.0.0"
    assert settings.port == 5173


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"WEB_HOST": "   "}, "WEB_HOST"),
        ({"WEB_PORT": "not-a-number"}, "WEB_PORT는 정수"),
        ({"WEB_PORT": "0"}, "1~65535"),
        ({"WEB_PORT": "65536"}, "1~65535"),
    ],
)
def test_invalid_server_settings_are_rejected(environ: dict[str, str], message: str) -> None:
    """빈 host와 잘못된 포트는 Flask 실행 전에 명시적으로 실패한다."""
    with pytest.raises(ValueError, match=message):
        settings_from_env(environ)


def test_custom_web_root_can_be_injected_without_exposing_other_files(tmp_path: Path) -> None:
    """시험용 정적 루트를 주입해도 allowlist 밖 파일은 제공하지 않는다."""
    # 최소 정적 파일과 공개하면 안 되는 private 파일을 같은 임시 폴더에 만든다.
    (tmp_path / "index.html").write_text("<h1>temporary dashboard</h1>", encoding="utf-8")
    for asset_name in PUBLIC_ASSETS:
        (tmp_path / asset_name).write_text(f"/* {asset_name} */", encoding="utf-8")
    (tmp_path / "private.txt").write_text("secret", encoding="utf-8")

    # 주입한 루트의 index는 보이지만 allowlist 밖 private 파일은 404여야 한다.
    app = create_app(tmp_path)
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        assert test_client.get("/").get_data(as_text=True) == "<h1>temporary dashboard</h1>"
        assert test_client.get("/private.txt").status_code == 404


def test_status_api_returns_consistent_runner_and_robot_state_snapshots() -> None:
    """REST가 Runner와 세 장치 진단을 같은 스냅샷으로 반환한다."""
    cache = StateCache(
        {"runner": None, "robot_state": None, "robot": 2.0, "camera": 2.0, "voice": None}
    )
    cache.set_publisher_present("runner", True)
    cache.record_message(
        "runner",
        {"phase": "running", "task_id": "manual_test", "current_step": "open_drawer"},
        received_at=datetime(2026, 10, 13, 6, 30, tzinfo=timezone.utc),
    )
    robot_state_data = {
        "robot_pose": {"robot": "home"},
        "gripper": {"robot": "empty"},
        # 전달 트레이 상태도 REST 원본에는 보존하고 UI의 서랍 요약에서만 제외한다.
        "open": {
            "drawer_top": False,
            "drawer_bottom": True,
            "handover_zone": True,
        },
        "located_in": {"car_key": "drawer_top", "wallet": "drawer_bottom"},
    }
    cache.record_message(
        "robot_state",
        robot_state_data,
        received_at=datetime(2026, 10, 13, 6, 30, 1, tzinfo=timezone.utc),
    )
    # JointState 콜백이 만든 최소 연결 메타데이터를 REST 원본에 함께 넣는다.
    cache.record_message(
        "robot",
        {"joint_count": 6, "joint_names": [f"joint_{index}" for index in range(1, 7)]},
        received_at=datetime(2026, 10, 13, 6, 30, 2, tzinfo=timezone.utc),
    )
    # 카메라는 최근 CameraInfo 수신을, Voice는 publisher endpoint만 기록한다.
    cache.record_message(
        "camera",
        {"frame_id": "wrist_cam", "width": 1280, "height": 720},
        received_at=datetime(2026, 10, 13, 6, 30, 3, tzinfo=timezone.utc),
    )
    cache.set_publisher_present("voice", True)
    fixed_now = lambda: datetime(2026, 10, 13, 6, 31, tzinfo=timezone.utc)

    # app factory가 runtime과 같은 캐시를 보관하고 요청 때마다 snapshot을 읽는다.
    app = create_app(
        state_cache=cache,
        runtime_profile="dev",
        robot_topic="/test/joint_states",
        utcnow=fixed_now,
    )
    assert app.extensions["ready2go_web"]["state_cache"] is cache

    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        response = test_client.get(STATUS_API_PATH)

    # 성공·형식·재사용 금지 헤더가 브라우저 polling 계약과 일치해야 한다.
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert payload["schema_version"] == API_SCHEMA_VERSION
    assert payload["served_at"] == "2026-10-13T06:31:00Z"
    assert payload["poll_interval_ms"] == POLL_INTERVAL_MS
    assert payload["status"] == "ok"
    assert payload["runtime_profile"] == "dev"
    assert payload["robot_topic"] == "/test/joint_states"

    # 의미 변환 전 원본 Runner JSON과 연결 진단이 손실 없이 함께 반환돼야 한다.
    runner = payload["sources"]["runner"]
    assert runner["connection_state"] == "receiving"
    assert runner["publisher_present"] is True
    assert runner["last_received_at"] == "2026-10-13T06:30:00Z"
    assert runner["data"] == {
        "phase": "running",
        "task_id": "manual_test",
        "current_step": "open_drawer",
    }
    robot_state = payload["sources"]["robot_state"]
    assert robot_state["connection_state"] == "receiving"
    assert robot_state["message_valid"] is True
    assert robot_state["last_received_at"] == "2026-10-13T06:30:01Z"
    assert robot_state["data"] == robot_state_data
    robot = payload["sources"]["robot"]
    assert robot["connection_state"] == "receiving"
    assert robot["freshness_timeout_sec"] == 2.0
    assert robot["data"]["joint_count"] == 6
    camera = payload["sources"]["camera"]
    assert camera["connection_state"] == "receiving"
    assert camera["freshness_timeout_sec"] == 2.0
    assert camera["data"]["frame_id"] == "wrist_cam"
    voice = payload["sources"]["voice"]
    assert voice["publisher_present"] is True
    assert voice["message_received"] is False
    assert voice["connection_state"] == "waiting"


def test_status_api_reports_missing_runtime_cache_as_service_unavailable(client) -> None:
    """ROS 캐시 없이 만든 앱은 빈 정상값 대신 안정된 JSON 503을 반환한다."""
    response = client.get(STATUS_API_PATH)

    assert response.status_code == 503
    assert response.mimetype == "application/json"
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "STATE_CACHE_UNAVAILABLE"
    assert "sources" not in payload


def test_definitions_api_returns_startup_snapshot_without_mutating_it() -> None:
    """5단계 REST가 서버 시작 시 읽은 정의 스냅샷을 별도 경로로 반환한다."""

    # 실제 로더와 같은 최소 스냅샷 구조를 시험에 주입한다.
    definition_snapshot = {
        "schema_version": 1,
        "snapshot_kind": "web_file_snapshot",
        "loaded_at": "2026-10-13T10:00:00Z",
        "runner_hot_reload_applied": False,
        "sources": {"ontology_manifest": {"path": "/knowledge/robot_ontology.jsonld"}},
        "counts": {"items": 1, "places": 1, "lists": 0, "skills": 1, "tasks": 1},
        "definitions": {
            "classes": [],
            "items": [{"id": "car_key", "name_ko": "차 키"}],
            "places": [{"id": "drawer_top", "name_ko": "위 서랍"}],
            "lists": [],
            "skills": [{"id": "pick", "name_ko": "집기"}],
            "tasks": [{"id": "find_item", "source_file": "find_item.json"}],
        },
    }
    # 요청 생성 시각과 파일 로딩 시각이 서로 다른 의미임을 확인할 고정 시계를 만든다.
    fixed_now = lambda: datetime(2026, 10, 13, 10, 1, tzinfo=timezone.utc)
    # ROS cache 없이도 정의 전용 API는 독립적으로 제공되어야 한다.
    app = create_app(definition_snapshot=definition_snapshot, utcnow=fixed_now)
    # 시험 예외를 바로 실패로 전달한다.
    app.config.update(TESTING=True)

    # Flask 시험 클라이언트로 정의 경로만 호출한다.
    with app.test_client() as test_client:
        response = test_client.get(DEFINITIONS_API_PATH)

    # 읽기 전용 JSON 응답과 재사용 금지 헤더를 확인한다.
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert response.headers["Cache-Control"] == "no-store"
    # served_at은 요청 시각이고 snapshot.loaded_at은 파일 로딩 시각이어야 한다.
    payload = response.get_json()
    assert payload["served_at"] == "2026-10-13T10:01:00Z"
    assert payload["status"] == "ok"
    assert payload["snapshot"] == definition_snapshot
    assert payload["snapshot"]["loaded_at"] == "2026-10-13T10:00:00Z"


def test_definitions_api_reports_startup_loading_error() -> None:
    """정의 원본 오류를 빈 정상 목록이나 목업 데이터로 바꾸지 않는다."""

    # 시작 코드가 포착한 파일 오류를 Flask app에 전달한다.
    app = create_app(definition_error="FileNotFoundError: manifest missing")
    # 시험 중 예외를 숨기지 않는다.
    app.config.update(TESTING=True)

    # 정의 경로를 호출해 상태 API와 독립된 실패 응답을 확인한다.
    with app.test_client() as test_client:
        response = test_client.get(DEFINITIONS_API_PATH)

    # 서비스는 살아 있지만 정의만 준비되지 않았으므로 503이어야 한다.
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    # 안정된 오류 코드와 시작 시 받은 원인을 반환한다.
    payload = response.get_json()
    assert payload["status"] == "error"
    assert payload["error"] == {
        "code": "DEFINITIONS_UNAVAILABLE",
        "message": "FileNotFoundError: manifest missing",
    }


def test_status_api_hides_internal_snapshot_exception() -> None:
    """캐시 읽기 예외는 내부 상세를 노출하지 않는 JSON 500으로 변환한다."""

    class BrokenCache:
        """REST 예외 경계만 검증하기 위해 snapshot에서 실패하는 시험 대역."""

        def snapshot(self):
            """실제 오류 문자열이 응답에 새지 않는지 확인할 예외를 발생시킨다."""
            raise RuntimeError("private implementation detail")

    # Python 타입은 다르지만 공개 snapshot 경계를 가진 실패 대역을 의도적으로 주입한다.
    app = create_app(state_cache=BrokenCache())  # type: ignore[arg-type]
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        response = test_client.get(STATUS_API_PATH)

    assert response.status_code == 500
    payload = response.get_json()
    assert payload["error"]["code"] == "STATE_SNAPSHOT_FAILED"
    assert "private implementation detail" not in response.get_data(as_text=True)
