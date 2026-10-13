"""``python -m ready2go_web`` 명령의 Flask 실행 진입점."""

from __future__ import annotations

from ready2go_web.core.definition_catalog import (
    load_definition_snapshot,
    settings_from_env as definition_settings_from_env,
)
from ready2go_web.nodes.dashboard_bridge import BridgeTopics
from ready2go_web.runtime import RosBridgeRuntime, settings_from_env as runtime_settings_from_env
from ready2go_web.server import create_app, settings_from_env


def _load_definitions_for_startup():
    """정의 설정·파일 오류를 상태 서버와 분리해 성공값 또는 오류로 반환한다."""
    # 정의 설정 해석부터 실제 파일 로딩까지 같은 실패 경계 안에서 처리한다.
    try:
        # Runner와 같은 온톨로지 manifest 및 태스크 원본 경로를 설정 객체로 고정한다.
        definition_settings = definition_settings_from_env()
        # 서버 시작 시 딱 한 번 공통 ontology.load와 태스크 로더로 파일 스냅샷을 만든다.
        return load_definition_snapshot(definition_settings), None
    except Exception as exc:
        # 잘못된 환경변수와 파일·형식 오류 모두 정의 API의 독립된 503 원인으로 전달한다.
        return None, f"{type(exc).__name__}: {exc}"


def main() -> None:
    """환경 설정과 등록 정의를 읽고 Flask·ROS 브리지를 한 번만 실행한다."""
    # host와 port는 코드 상수가 아니라 WEB_HOST·WEB_PORT 환경변수에서 검증해 가져온다.
    settings = settings_from_env()
    # B 로봇 연결 기준과 real/sim/dev 표시를 코드 상수가 아닌 환경 설정에서 읽는다.
    runtime_settings = runtime_settings_from_env()
    # 정의 설정·로딩 오류가 있어도 ROS 상태 화면을 시작할 수 있도록 결과를 분리한다.
    definition_snapshot, definition_error = _load_definitions_for_startup()
    # ROS runtime이 /runner/status를 받는 별도 executor 스레드를 먼저 시작한다.
    runtime = RosBridgeRuntime(
        topics=BridgeTopics(robot_connection=runtime_settings.robot_topic),
        robot_timeout_sec=runtime_settings.robot_timeout_sec,
    )
    runtime.start()
    try:
        # Flask에는 ROS 캐시와 시작 시 고정한 정의 결과를 각각의 REST 원본으로 전달한다.
        app = create_app(
            state_cache=runtime.cache,
            definition_snapshot=definition_snapshot,
            definition_error=definition_error,
            runtime_profile=runtime_settings.profile,
            robot_topic=runtime_settings.robot_topic,
        )
        # reloader를 끄면 개발 서버가 프로세스를 복제해 ROS 노드를 두 개 만들지 않는다.
        app.run(
            host=settings.host,
            port=settings.port,
            debug=False,
            use_reloader=False,
        )
    finally:
        # Ctrl+C와 서버 예외 모두 executor·노드·context 정리 경로를 통과한다.
        runtime.stop()


# 모듈을 import할 때 서버가 자동 실행되지 않고 -m으로 직접 실행할 때만 시작한다.
if __name__ == "__main__":
    main()
