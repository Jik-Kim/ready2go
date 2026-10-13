"""기존 web/ 정적 대시보드를 제공하는 Flask 애플리케이션.

이 모듈은 기존 HTML·CSS·JavaScript 목업을 Flask를 통해 동일하게 제공한다.
이슈 #267의 3~4단계에서는 실행 진입점이 전달한 ROS 상태 캐시의 일관된 복사본을
읽기 전용 REST로 제공한다. 5단계에서는 시작 시 읽은 등록 정의 스냅샷도 별도
REST로 제공한다. 브라우저는 같은 origin의 응답만 읽고 ROS나 원본 파일에 직접
접속하지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Mapping

from flask import Flask, abort, jsonify, send_from_directory

from ready2go_web.core.state_cache import StateCache


# Python 패키지는 web/ready2go_web/에 있으므로 부모 폴더가 기존 정적 UI의 루트다.
DEFAULT_WEB_ROOT = Path(__file__).resolve().parents[1]

# 이번 웹 내부 REST 형식의 버전이다. ROS wire 계약 버전과는 별개다.
API_SCHEMA_VERSION = 1

# 브라우저가 같은 origin에서 조회할 읽기 전용 상태 경로다.
STATUS_API_PATH = "/api/status"

# 브라우저가 시작할 때 한 번 조회할 등록 정의 스냅샷 경로다.
DEFINITIONS_API_PATH = "/api/definitions"

# 이 값은 이슈 #267에서 정한 브라우저 권장 조회 간격이며 ROS 발행 주기가 아니다.
POLL_INTERVAL_MS = 1_000

# 현재 index.html이 직접 요청하는 파일만 공개한다. 저장소의 다른 파일은 제공하지 않는다.
PUBLIC_ASSETS = frozenset(
    {
        "app.js",
        "demo-data.js",
        "status-api.js",
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


def _utc_now() -> datetime:
    """REST 응답 생성 시각을 시간대가 포함된 UTC로 만든다."""
    # 서버 PC의 로컬 시간대 설정과 무관한 절대 시각을 제공한다.
    return datetime.now(timezone.utc)


def _isoformat_utc(value: datetime) -> str:
    """시간대가 있는 시각만 REST용 UTC ISO 8601 문자열로 변환한다."""
    # naive datetime은 PC마다 다르게 해석될 수 있으므로 시험 주입값도 허용하지 않는다.
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("REST 응답 시각은 timezone-aware datetime이어야 합니다")
    # 브라우저 Date가 바로 처리할 수 있도록 UTC의 +00:00을 Z로 정규화한다.
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def create_app(
    web_root: str | Path | None = None,
    *,
    state_cache: StateCache | None = None,
    definition_snapshot: Mapping[str, object] | None = None,
    definition_error: str | None = None,
    runtime_profile: str = "real",
    robot_topic: str = "/dsr01/joint_states",
    utcnow: Callable[[], datetime] = _utc_now,
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
        # REST 핸들러는 요청마다 이 같은 캐시에서 잠금 스냅샷만 가져온다.
        "state_cache": state_cache,
        # 정의는 서버 시작 때 한 번 읽은 웹 파일 스냅샷이며 요청마다 다시 읽지 않는다.
        "definition_snapshot": definition_snapshot,
        # 정의 로딩 실패도 상태 REST와 정적 UI를 중단하지 않고 별도 오류로 제공한다.
        "definition_error": definition_error,
        # UI가 sim/dev의 의도된 미발행을 실물 단절로 오해하지 않게 실행 프로필을 제공한다.
        "runtime_profile": runtime_profile,
        # 환경변수로 바꾼 실제 관절 토픽을 UI 문구도 그대로 사용하게 보존한다.
        "robot_topic": robot_topic,
    }

    def api_response(payload: Mapping[str, object], status_code: int = 200):
        """모든 API 응답에 JSON MIME과 재사용 금지 헤더를 동일하게 적용한다."""
        # Flask jsonify는 Content-Type을 application/json으로 설정하고 안전하게 직렬화한다.
        response = jsonify(payload)
        # 상태 화면이 브라우저·프록시 캐시에 남아 현재값처럼 재사용되지 않게 한다.
        response.headers["Cache-Control"] = "no-store"
        return response, status_code

    def response_envelope() -> dict[str, object]:
        """성공·오류 응답이 공유하는 버전·시각·조회 간격 필드를 만든다."""
        return {
            "schema_version": API_SCHEMA_VERSION,
            "served_at": _isoformat_utc(utcnow()),
            "poll_interval_ms": POLL_INTERVAL_MS,
        }

    @app.get(STATUS_API_PATH)
    def status_api():
        """ROS 상태 캐시의 한 시점 복사본을 읽기 전용 JSON으로 반환한다."""
        # 정적 UI만 만든 시험/오구성 앱은 빈 정상 응답 대신 명시적인 503을 반환한다.
        if state_cache is None:
            payload = response_envelope()
            payload.update(
                {
                    "status": "error",
                    "error": {
                        "code": "STATE_CACHE_UNAVAILABLE",
                        "message": "ROS 상태 캐시를 사용할 수 없습니다.",
                    },
                }
            )
            return api_response(payload, 503)

        try:
            # StateCache.snapshot이 잠금 안에서 모든 source를 깊은 복사한다.
            sources = state_cache.snapshot()
        except Exception:
            # 내부 예외 상세는 브라우저에 노출하지 않고 안정된 오류 코드만 반환한다.
            payload = response_envelope()
            payload.update(
                {
                    "status": "error",
                    "error": {
                        "code": "STATE_SNAPSHOT_FAILED",
                        "message": "상태 스냅샷을 만들 수 없습니다.",
                    },
                }
            )
            return api_response(payload, 500)

        # 성공 시에는 가공하지 않은 source 진단과 마지막 정상 payload를 함께 제공한다.
        payload = response_envelope()
        payload.update(
            {
                "status": "ok",
                "runtime_profile": runtime_profile,
                "robot_topic": robot_topic,
                "sources": sources,
            }
        )
        return api_response(payload)

    @app.get(DEFINITIONS_API_PATH)
    def definitions_api():
        """웹 시작 시 읽은 등록 정의 스냅샷을 파일 재조회 없이 반환한다."""
        # 로딩에 실패했거나 정의가 주입되지 않은 앱은 목업을 정상 정의처럼 반환하지 않는다.
        if definition_snapshot is None:
            # 상태 API와 같은 공통 envelope에 정의 전용 오류를 추가한다.
            payload = response_envelope()
            # 브라우저가 설정 누락과 정상 빈 정의를 구분할 수 있는 안정된 오류 형식이다.
            payload.update(
                {
                    "status": "error",
                    "error": {
                        "code": "DEFINITIONS_UNAVAILABLE",
                        "message": definition_error or "등록 정의를 사용할 수 없습니다.",
                    },
                }
            )
            # 정의 오류가 있어도 상태 API는 계속 제공하므로 이 경로만 503으로 응답한다.
            return api_response(payload, 503)

        # 로더가 만든 스냅샷과 요청 시각을 섞지 않도록 새 응답 객체를 만든다.
        payload = response_envelope()
        # status는 HTTP 성공을, snapshot은 서버 시작 때 고정된 정의를 뜻한다.
        payload.update({"status": "ok", "snapshot": definition_snapshot})
        # 등록 정의도 브라우저 캐시가 이전 기동 값을 재사용하지 않도록 no-store로 반환한다.
        return api_response(payload)

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
