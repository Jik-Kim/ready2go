"""실제 브라우저 렌더링으로 장치 상태 표시의 회귀를 검증한다."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
from threading import Thread

import pytest
from flask import request
from werkzeug.serving import make_server

from ready2go_web.core.overlay_cache import OverlayCache
from ready2go_web.core.state_cache import StateCache
from ready2go_web.server import VISION_OVERLAY_IMAGE_API_PATH, create_app


def _render_dashboard(
    tmp_path: Path,
    *,
    runtime_profile: str,
    camera_received: bool,
    overlay_cache: OverlayCache | None = None,
    utcnow: Callable[[], datetime] | None = None,
    on_first_image_request: Callable[[], None] | None = None,
) -> tuple[str, int]:
    """주입한 REST 상태를 실제 headless Chrome으로 렌더링해 DOM을 반환한다."""
    # 제품 JavaScript를 실행하지 않는 정적 문자열 검사는 분기 회귀를 잡지 못하므로,
    # 설치된 Chrome으로 실제 Flask·fetch·DOM 갱신 경로를 통과시킨다.
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if chrome is None:
        pytest.skip("headless Chrome을 사용할 수 없어 브라우저 회귀 시험을 생략합니다")

    # 상태 API가 요구하는 다섯 source를 실제 runtime과 같은 timeout으로 준비한다.
    cache = StateCache(
        {"runner": None, "robot_state": None, "robot": 2.0, "camera": 2.0, "voice": None}
    )
    # runtime의 첫 graph 조회가 끝난 상태처럼 publisher 부재를 명시해 null(조회 전)과 구분한다.
    cache.set_publisher_present("camera", False)
    if camera_received:
        # 과거 수신 뒤 publisher가 사라진 상태를 만들어 최초 미발행과 구분한다.
        cache.set_publisher_present("camera", True)
        cache.record_message("camera", {"frame_id": "wrist_cam", "width": 1280, "height": 720})
        cache.set_publisher_present("camera", False)

    # 운영 정적 파일과 상태 REST를 같은 origin으로 제공하되 사용 가능한 임의 포트를 쓴다.
    app = create_app(
        state_cache=cache,
        overlay_cache=overlay_cache,
        runtime_profile=runtime_profile,
        **({"utcnow": utcnow} if utcnow is not None else {}),
    )
    image_request_count = 0

    @app.before_request
    def count_overlay_image_requests() -> None:
        """revision 중복 조회와 409 뒤 재시도를 실제 HTTP 요청 수로 검증한다."""
        nonlocal image_request_count
        if request.path != VISION_OVERLAY_IMAGE_API_PATH:
            return
        image_request_count += 1
        if image_request_count == 1 and on_first_image_request is not None:
            on_first_image_request()
    server = make_server("127.0.0.1", 0, app)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        # virtual time을 주어 첫 상태 polling이 끝난 DOM을 dump하고 외부 네트워크는 사용하지 않는다.
        result = subprocess.run(
            [
                chrome,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                f"--user-data-dir={tmp_path / 'chrome-profile'}",
                "--virtual-time-budget=2500",
                "--dump-dom",
                f"http://127.0.0.1:{server.server_port}/",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    finally:
        # 성공·실패와 관계없이 포트와 서버 스레드를 시험 안에서 정리한다.
        server.shutdown()
        server_thread.join(timeout=5)

    # Chrome 자체 실패를 빈 DOM이나 UI 실패로 오해하지 않게 진단 출력을 함께 제공한다.
    assert result.returncode == 0, result.stderr
    return result.stdout, image_request_count


@pytest.mark.parametrize(
    ("runtime_profile", "camera_received", "expected_status"),
    [
        pytest.param("dev", False, "확인 전(시뮬레이션)", id="dev-never-published"),
        pytest.param("sim", False, "확인 전(시뮬레이션)", id="sim-never-published"),
        pytest.param("dev", True, "카메라 정보 수신 끊김", id="dev-disconnected-after-receive"),
        pytest.param("real", False, "카메라 정보 수신 끊김", id="real-never-published"),
    ],
)
def test_camera_badge_distinguishes_simulation_absence_from_disconnect(
    tmp_path: Path,
    runtime_profile: str,
    camera_received: bool,
    expected_status: str,
) -> None:
    """sim/dev 최초 미발행만 확인 전이며 실제 단절과 real 미발행은 끊김이다."""
    rendered, _image_request_count = _render_dashboard(
        tmp_path,
        runtime_profile=runtime_profile,
        camera_received=camera_received,
    )

    # aria-label은 화면 문자와 접근성 상태를 함께 나타내므로 실제 사용자 표시를 검증한다.
    assert f"카메라: {expected_status}." in rendered


def _overlay_cache_with_capture(captured_at: datetime, now: datetime) -> OverlayCache:
    """고정 UTC 시각의 JPEG 한 장을 가진 브라우저 시험용 캐시를 만든다."""
    cache = OverlayCache(utcnow=lambda: now)
    cache.update(
        b"\xff\xd8browser-overlay\xff\xd9",
        int(captured_at.timestamp()),
        captured_at.microsecond * 1_000,
        now,
        "wrist_cam_color_optical_frame",
    )
    return cache


def test_recent_capture_keeps_empty_state_without_image_request(tmp_path: Path) -> None:
    """정상 캐시에 사진이 없으면 JPEG를 요청하지 않고 아직 촬영 없음으로 남는다."""
    now = datetime(2026, 10, 15, 1, 10, 7, tzinfo=timezone.utc)
    overlay_cache = OverlayCache(utcnow=lambda: now)

    rendered, image_request_count = _render_dashboard(
        tmp_path,
        runtime_profile="dev",
        camera_received=False,
        overlay_cache=overlay_cache,
        utcnow=lambda: now,
    )

    assert image_request_count == 0
    assert '<strong>아직 촬영 없음</strong>' in rendered
    assert '<dd id="captureTime">확인 전</dd>' in rendered
    assert '<dd id="captureAge">확인 전</dd>' in rendered


def test_recent_capture_renders_matching_revision_once_with_kst_time(
    tmp_path: Path,
) -> None:
    """같은 revision은 한 번만 내려받고 촬영 UTC 시각과 서버 나이를 표시한다."""
    now = datetime(2026, 10, 15, 1, 10, 7, tzinfo=timezone.utc)
    captured_at = datetime(2026, 10, 15, 1, 10, 5, tzinfo=timezone.utc)
    overlay_cache = _overlay_cache_with_capture(captured_at, now)

    rendered, image_request_count = _render_dashboard(
        tmp_path,
        runtime_profile="dev",
        camera_received=False,
        overlay_cache=overlay_cache,
        utcnow=lambda: now,
    )

    assert image_request_count == 1
    assert 'id="captureImage" alt="최근 촬영한 분할 결과" src="blob:' in rendered
    assert '<dd id="captureTime">10:10:05 KST</dd>' in rendered
    assert '<dd id="captureAge">2초 전</dd>' in rendered
    # 오버레이 사진 존재 여부가 camera_info 기반 상단 배지를 정상으로 바꾸면 안 된다.
    assert "카메라: 확인 전(시뮬레이션)." in rendered


def test_recent_capture_retries_new_revision_after_409(tmp_path: Path) -> None:
    """사진 조회 중 revision이 바뀌면 다음 polling의 새 revision으로 다시 결합한다."""
    now = datetime(2026, 10, 15, 1, 10, 7, tzinfo=timezone.utc)
    first_capture = datetime(2026, 10, 15, 1, 10, 5, tzinfo=timezone.utc)
    second_capture = datetime(2026, 10, 15, 1, 10, 6, tzinfo=timezone.utc)
    overlay_cache = _overlay_cache_with_capture(first_capture, now)

    def publish_newer_capture() -> None:
        # 첫 revision JPEG 요청 직전에 최신 사진을 교체해 서버의 409 경로를 만든다.
        overlay_cache.update(
            b"\xff\xd8newer-browser-overlay\xff\xd9",
            int(second_capture.timestamp()),
            second_capture.microsecond * 1_000,
            now,
            "wrist_cam_color_optical_frame",
        )

    rendered, image_request_count = _render_dashboard(
        tmp_path,
        runtime_profile="dev",
        camera_received=False,
        overlay_cache=overlay_cache,
        utcnow=lambda: now,
        on_first_image_request=publish_newer_capture,
    )

    # revision 1은 409, 다음 상태 polling의 revision 2는 JPEG 200으로 각각 한 번 요청한다.
    assert image_request_count == 2
    assert '<dd id="captureTime">10:10:06 KST</dd>' in rendered
    assert '<dd id="captureAge">1초 전</dd>' in rendered
    assert 'id="captureImage" alt="최근 촬영한 분할 결과" src="blob:' in rendered
