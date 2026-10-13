"""기존 web/ 정적 대시보드를 제공하는 Flask 애플리케이션.

이 모듈은 기존 HTML·CSS·JavaScript 목업을 Flask를 통해 동일하게 제공한다.
이슈 #267의 2단계에서는 실행 진입점이 전달한 ROS 상태 캐시를 보관하지만 아직
REST API로 공개하지 않는다. 다음 단계에서 같은 app factory에 읽기 전용 API를 추가한다.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from flask import Flask, abort, send_from_directory

from ready2go_web.core.state_cache import StateCache


# Python 패키지는 web/ready2go_web/에 있으므로 부모 폴더가 기존 정적 UI의 루트다.
DEFAULT_WEB_ROOT = Path(__file__).resolve().parents[1]

# 현재 index.html이 직접 요청하는 파일만 공개한다. 저장소의 다른 파일은 제공하지 않는다.
PUBLIC_ASSETS = frozenset(
    {
        "app.js",
        "demo-data.js",
        "styles.css",
    }
)


@dataclass(frozen=True)
class ServerSettings:
    """Flask 개발 서버 실행에 필요한 환경 설정."""

    host: str  # 127.0.0.1은 로컬 전용, 0.0.0.0은 같은 네트워크 접속 허용.
    port: int  # 브라우저가 접속할 TCP 포트.


def settings_from_env(environ: Mapping[str, str] | None = None) -> ServerSettings:
    """WEB_HOST와 WEB_PORT를 읽고 서버 시작 전에 형식을 검증한다."""
    # 시험에서는 별도 mapping을 주입하고 운영에서는 현재 프로세스 환경을 읽는다.
    values = os.environ if environ is None else environ

    # 기본 host는 외부에 노출되지 않는 localhost이며 공백 설정은 허용하지 않는다.
    host = values.get("WEB_HOST", "127.0.0.1").strip()
    if not host:
        raise ValueError("WEB_HOST는 비어 있지 않아야 합니다")

    # 환경변수는 문자열이므로 먼저 정수로 변환하고 사용 가능한 TCP 범위를 검사한다.
    raw_port = values.get("WEB_PORT", "4173").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("WEB_PORT는 정수여야 합니다") from exc
    if not 1 <= port <= 65535:
        raise ValueError("WEB_PORT는 1~65535 범위여야 합니다")

    # 검증된 불변 설정 객체만 Flask 실행 진입점에 전달한다.
    return ServerSettings(host=host, port=port)


def create_app(
    web_root: str | Path | None = None,
    *,
    state_cache: StateCache | None = None,
) -> Flask:
    """기존 UI를 제공하는 Flask app을 생성한다.

    ``web_root``는 시험에서만 임시 정적 파일 위치를 주입할 수 있게 한다. 기본값은
    저장소의 기존 ``web/`` 폴더다.
    """
    # resolve로 상대 경로를 절대 경로로 고정해 실행 cwd에 따라 파일 위치가 달라지지 않게 한다.
    static_root = Path(web_root or DEFAULT_WEB_ROOT).resolve()

    # Flask의 기본 static route는 폴더 전체를 공개하므로 끄고 명시한 파일만 제공한다.
    app = Flask(__name__, static_folder=None)

    # app.extensions는 Flask 확장과 실행 메타데이터를 저장하는 공식 애플리케이션 공간이다.
    # 후속 REST 구현과 시험이 실제 정적 루트를 확인할 수 있도록 문자열로 기록한다.
    app.extensions["ready2go_web"] = {
        "static_root": str(static_root),
        # 2단계에서는 서버와 ROS가 같은 객체를 공유하는지만 구성하고 외부로 노출하지 않는다.
        "state_cache": state_cache,
    }

    @app.get("/")
    def index():
        """대시보드 진입점인 기존 index.html을 반환한다."""
        # send_from_directory가 파일 경로 결합과 HTTP 응답 헤더를 안전하게 처리한다.
        return send_from_directory(static_root, "index.html")

    @app.get("/<path:asset_name>")
    def static_asset(asset_name: str):
        """현재 대시보드가 사용하는 공개 CSS·JavaScript 파일만 반환한다."""
        # allowlist에 없는 파일과 ../ 상위 경로 요청은 모두 같은 404로 처리한다.
        if asset_name not in PUBLIC_ASSETS:
            abort(404)
        # 허용된 이름만 send_from_directory에 전달해 저장소의 다른 파일이 노출되지 않게 한다.
        return send_from_directory(static_root, asset_name)

    # app factory를 사용하면 실제 서버 실행 없이 Flask test client로 검증할 수 있다.
    return app
