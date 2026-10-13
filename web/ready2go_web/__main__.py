"""``python -m ready2go_web`` 명령의 Flask 실행 진입점."""

from __future__ import annotations

from ready2go_web.runtime import RosBridgeRuntime
from ready2go_web.server import create_app, settings_from_env


def main() -> None:
    """환경 설정을 읽고 정적 UI용 Flask 서버를 한 번만 실행한다."""
    # host와 port는 코드 상수가 아니라 WEB_HOST·WEB_PORT 환경변수에서 검증해 가져온다.
    settings = settings_from_env()
    # ROS runtime이 /runner/status를 받는 별도 executor 스레드를 먼저 시작한다.
    runtime = RosBridgeRuntime()
    runtime.start()
    try:
        # Flask에는 ROS 콜백이 갱신하는 같은 캐시를 전달해 REST가 잠금 스냅샷을 읽게 한다.
        app = create_app(state_cache=runtime.cache)
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
