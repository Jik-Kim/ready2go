"""실제 브라우저 렌더링으로 장치 상태 표시의 회귀를 검증한다."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from threading import Thread

import pytest
from werkzeug.serving import make_server

from ready2go_web.core.state_cache import StateCache
from ready2go_web.server import create_app


def _render_dashboard(
    tmp_path: Path,
    *,
    runtime_profile: str,
    camera_received: bool,
) -> str:
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
    app = create_app(state_cache=cache, runtime_profile=runtime_profile)
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
    return result.stdout


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
    rendered = _render_dashboard(
        tmp_path,
        runtime_profile=runtime_profile,
        camera_received=camera_received,
    )

    # aria-label은 화면 문자와 접근성 상태를 함께 나타내므로 실제 사용자 표시를 검증한다.
    assert f"카메라: {expected_status}." in rendered
