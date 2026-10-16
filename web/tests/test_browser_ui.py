"""실제 브라우저 렌더링으로 장치 상태 표시의 회귀를 검증한다."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from html import unescape
import json
import re
from pathlib import Path
import shutil
import subprocess
from threading import Thread

import pytest
from flask import abort, request
from werkzeug.serving import make_server

from ready2go_web.core.overlay_cache import OverlayCache
from ready2go_web.core.state_cache import StateCache
from ready2go_web.server import VISION_OVERLAY_IMAGE_API_PATH, create_app


def _render_dashboard(
    tmp_path: Path,
    *,
    runtime_profile: str,
    camera_received: bool,
    scenario: str = "default",
    overlay_cache: object | None = None,
    utcnow: Callable[[], datetime] | None = None,
    on_first_image_request: Callable[[], None] | None = None,
    on_first_image_response: Callable[[], None] | None = None,
    runner_payloads: list[dict | None] | None = None,
    interaction_script: str | None = None,
    viewport_width: int = 1280,
    robot_state_payload: dict | None = None,
    definition_snapshot=None,
    definition_delay_ms: int = 0,
    status_poll_interval_ms: int | None = None,
    execution_reader=None,
    enable_deferred_detail: bool = False,
    on_detail_request: Callable[[], None] | None = None,
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

    # 조회 서랍 전환 시험에는 실제 기억 상태 형식의 독립 source를 주입한다.
    if robot_state_payload is not None:
        cache.record_message("robot_state", robot_state_payload)

    # 운영 정적 파일과 상태 REST를 같은 origin으로 제공하되 사용 가능한 임의 포트를 쓴다.
    app = create_app(
        state_cache=cache,
        execution_reader=execution_reader,
        definition_snapshot=definition_snapshot,
        overlay_cache=overlay_cache,
        runtime_profile=runtime_profile,
        **({"utcnow": utcnow} if utcnow is not None else {}),
    )
    status_request_count = 0

    @app.before_request
    def runner_sequence():
        nonlocal status_request_count
        if request.path.startswith("/api/execution-detail/") and on_detail_request is not None:
            on_detail_request()
        if request.path != "/api/status" or runner_payloads is None:
            return None
        payload = runner_payloads[min(status_request_count, len(runner_payloads) - 1)]
        status_request_count += 1
        if payload is None:
            abort(503)
        cache.record_message("runner", payload)
        return None

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

    @app.after_request
    def switch_after_first_overlay_response(response):
        """첫 JPEG가 만들어진 뒤 서버 캐시 교체를 재현할 시험 hook이다."""
        if (
            request.path == VISION_OVERLAY_IMAGE_API_PATH
            and image_request_count == 1
            and on_first_image_response is not None
        ):
            on_first_image_response()
        return response
    @app.after_request
    def inject_test_interaction(response):
        # 응답 순서 회귀: 제품 fetch 경로는 유지하고 시험 HTML에서 정의 응답 전달만 늦춘다.
        if request.path == "/" and definition_delay_ms:
            response.direct_passthrough = False
            script = "<script>const originalFetch = window.fetch.bind(window); window.fetch = async (...args) => { const response = await originalFetch(...args); if (String(args[0]).includes('/api/definitions')) await new Promise(resolve => setTimeout(resolve, " + str(definition_delay_ms) + ")); return response; };</script>"
            response.set_data(response.get_data(as_text=True).replace("<head>", "<head>" + script))
        if request.path == "/api/status" and status_poll_interval_ms is not None and response.status_code == 200:
            payload = response.get_json()
            payload["poll_interval_ms"] = status_poll_interval_ms
            response.set_data(json.dumps(payload))
        # 보존한 후속 상세 기능의 기존 시험만 전용 응답에서 활성화한다. 제품/URL 설정은 아니다.
        if request.path == "/app.js" and enable_deferred_detail:
            response.direct_passthrough = False
            source = response.get_data(as_text=True)
            assert "const executionDetailEnabled = false;" in source
            response.set_data(source.replace("const executionDetailEnabled = false;",
                                             "const executionDetailEnabled = true;"))
        # 시험 응답에만 사용자 동작과 DOM 스냅샷 코드를 추가한다.
        if request.path == "/" and interaction_script is not None:
            response.direct_passthrough = False
            response.set_data(response.get_data(as_text=True).replace(
                "</body>",
                '<script>window.addEventListener("load", () => {'
                + interaction_script + '});</script></body>',
            ))
        return response

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
                f"--window-size={viewport_width},900",
                "--dump-dom",
                f"http://127.0.0.1:{server.server_port}/?scenario={scenario}",
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


class _SwitchableOverlayCache:
    """Flask 객체는 유지한 채 새 Python 프로세스의 사진 캐시로 전환한다."""

    def __init__(self, active: OverlayCache) -> None:
        self.active = active

    @property
    def cache_id(self) -> str:
        return self.active.cache_id

    def get_latest(self):
        return self.active.get_latest()

    def get_metadata(self, *args, **kwargs):
        return self.active.get_metadata(*args, **kwargs)


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


def test_mock_current_task_uses_eraser_copy_and_shared_item_image(tmp_path: Path) -> None:
    """현재 작업 목업의 물품·문구·근거가 지우개로 같이 렌더링된다."""
    rendered, _image_request_count = _render_dashboard(
        tmp_path,
        runtime_profile="dev",
        camera_received=False,
        scenario="preview",
    )

    assert 'id="taskHeadingIcon"' in rendered
    assert 'src="assets/items/eraser.svg"' in rendered
    assert 'id="currentAction" aria-live="polite">지우개의 전달 결과를 확인하는 중</strong>' in rendered
    assert '<span class="step-label">지우개 확인·집기</span>' in rendered
    assert '<dd id="currentStepReason">지우개가 전달 위치에 놓였는지 확인</dd>' in rendered


def test_mock_request_and_verifying_supply_match_current_item(tmp_path: Path) -> None:
    """고정 목업의 요청·준비물·현재 작업이 서로 다른 물품을 가리키지 않는다."""
    from html.parser import HTMLParser

    class VisibleText(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)

    # long은 기본 목업을 상속하고 요청 문구를 덮어쓰므로 두 데이터 경로를 함께 검증한다.
    rendered, _ = _render_dashboard(
        tmp_path, runtime_profile="dev", camera_received=False, scenario="long"
    )
    parser = VisibleText()
    parser.feed(rendered)
    text = " ".join(parser.parts)
    assert "차 키·지우개·업무용 손목시계 및 교통카드 케이스를 찾아 전달합니다." in text
    assert "지우개의 전달 결과를 확인하는 중" in text
    # 준비물 한 행 안에서 물품명과 확인 중 상태가 함께 표시되는지 확인한다.
    supply_rows = rendered.split('class="supply-item"')[1:]
    verifying_rows = [row.split('</article>', 1)[0] for row in supply_rows
                      if "결과 확인 중" in row.split('</article>', 1)[0]]
    assert len(verifying_rows) == 1
    assert "지우개" in verifying_rows[0]
    assert "지갑" not in verifying_rows[0]


def test_recent_capture_explains_frame_id_rejection_without_image_request(
    tmp_path: Path,
) -> None:
    """사진이 없고 frame_id가 달라 거부됐다면 단순 미촬영으로 표시하지 않는다."""
    now = datetime(2026, 10, 15, 1, 10, 7, tzinfo=timezone.utc)
    overlay_cache = OverlayCache(utcnow=lambda: now)
    overlay_cache.record_rejection(
        "frame_id_mismatch",
        frame_id="unexpected_frame",
        rejected_at=now,
    )

    rendered, image_request_count = _render_dashboard(
        tmp_path,
        runtime_profile="dev",
        camera_received=False,
        overlay_cache=overlay_cache,
        utcnow=lambda: now,
    )

    assert image_request_count == 0
    assert '<strong>촬영 사진 확인 전</strong>' in rendered
    assert '<span>카메라 프레임 불일치</span>' in rendered
    assert '<strong>아직 촬영 없음</strong>' not in rendered


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


def test_recent_capture_refetches_same_revision_after_server_process_changes(
    tmp_path: Path,
) -> None:
    """열린 브라우저가 새 서버의 같은 revision 사진을 이전 사진으로 오해하지 않는다."""
    now = datetime(2026, 10, 15, 1, 10, 7, tzinfo=timezone.utc)
    first_capture = datetime(2026, 10, 15, 1, 10, 5, tzinfo=timezone.utc)
    second_capture = datetime(2026, 10, 15, 1, 10, 6, tzinfo=timezone.utc)
    first = OverlayCache(utcnow=lambda: now, cache_id="first-process")
    second = OverlayCache(utcnow=lambda: now, cache_id="second-process")
    first.update(
        b"\xff\xd8first-process-overlay\xff\xd9",
        int(first_capture.timestamp()),
        0,
        now,
        "wrist_cam_color_optical_frame",
    )
    second.update(
        b"\xff\xd8second-process-overlay\xff\xd9",
        int(second_capture.timestamp()),
        0,
        now,
        "wrist_cam_color_optical_frame",
    )
    proxy = _SwitchableOverlayCache(first)

    rendered, image_request_count = _render_dashboard(
        tmp_path,
        runtime_profile="dev",
        camera_received=False,
        overlay_cache=proxy,
        utcnow=lambda: now,
        on_first_image_response=lambda: setattr(proxy, "active", second),
    )

    # 두 프로세스 모두 revision 1이지만 cache_id가 달라 새 JPEG를 다시 요청해야 한다.
    assert image_request_count == 2
    assert '<dd id="captureTime">10:10:06 KST</dd>' in rendered
    assert '<dd id="captureAge">1초 전</dd>' in rendered
    assert 'id="captureImage" alt="최근 촬영한 분할 결과" src="blob:' in rendered


def _request_result(decision="run", reason=None, result_run="r1", result_status="COMPLETED"):
    """요청과 결과를 독립 변경할 수 있는 동일 기동·순서의 최소 시험 상태다."""
    return {
        "boot_id": "boot-1", "seq": 1,
        "phase": "idle", "task_id": None, "current_step": None,
        "last_intent": {"intent": "find_item", "targets": ["eraser"],
                        "decision": decision, "reason": reason, "task_id": "find_item",
                        "request_id": "request1", "run_id": "r1" if decision == "run" else None},
        "last": {"task_id": "find_item", "run_id": result_run,
                 "overall_status": result_status, "error_code": None, "failed_step": None},
    }


@pytest.mark.parametrize("scenario", ["default", "unknown"])
def test_normal_page_never_uses_example_execution(tmp_path: Path, scenario: str) -> None:
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False,
                                    scenario=scenario, runner_payloads=[None])
    assert "지우개의 전달 결과를 확인하는 중" not in rendered
    assert "차 키·지우개·시계를 찾아 전달합니다." not in rendered
    assert "1 / 3 전달 완료" not in rendered
    assert 'class="task-item-button"' not in rendered
    assert '<p id="understoodText">확인 전</p>' in rendered
    assert "현재 작업 확인 전" in rendered


@pytest.mark.parametrize(("decision", "reason", "result_run", "expected"), [
    ("run", None, "r1", "실행 완료"),
    ("hold", "LOW_CONFIDENCE", "r1", "보류 · 사유 코드: LOW_CONFIDENCE"),
    ("reject", "BUSY", "r1", "거절 · 사유 코드: BUSY"),
    ("run", None, "other-run", "수락된 요청의 실행 결과 확인 전"),
])
def test_command_uses_only_linked_request_result(tmp_path: Path, decision, reason, result_run, expected) -> None:
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False,
                                    runner_payloads=[_request_result(decision, reason, result_run)])
    assert "인텐트: find_item · eraser" in rendered
    assert expected in rendered
    if decision != "run" or result_run != "r1":
        assert "실행 완료" not in rendered
    else:
        # 실행 성공은 물품 전달 검증 또는 단계 상세를 만들지 않는다.
        assert "전달 완료" not in rendered
        assert "현재 실행 없음 · 대기" in rendered
        assert 'class="task-item-button"' not in rendered
    # PC·모바일은 같은 명령 모델을 사용한다.
    assert 'id="mobileUnderstoodText">인텐트: find_item · eraser</dd>' in rendered


@pytest.mark.parametrize("next_state", ["reject", "http-error", "invalid"])
def test_previous_result_is_cleared_after_rejection_or_failure(tmp_path: Path, next_state: str) -> None:
    next_payload = None if next_state == "http-error" else _request_result("reject", "BUSY")
    if next_payload is not None:
        next_payload["seq"] = 2
    if next_state == "invalid":
        next_payload = {"last_intent": {"intent": "find_item"}, "last": None}
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False,
                                    runner_payloads=[_request_result(), next_payload])
    assert "실행 완료" not in rendered
    assert "지우개의 전달 결과를 확인하는 중" not in rendered
    if next_state == "reject":
        assert "거절 · 사유 코드: BUSY" in rendered
        assert "이 요청의 실행은 수락되지 않음" in rendered
    else:
        assert '<p id="understoodText">확인 전</p>' in rendered
        assert "처리 결과 확인 전" in rendered
def test_empty_inventory_keeps_current_task_preview(tmp_path: Path) -> None:
    """empty는 조회용 물품·준비물만 비우고 실행 단계·근거는 유지한다."""
    rendered, _ = _render_dashboard(
        tmp_path, runtime_profile="dev", camera_received=False, scenario="empty",
    )
    assert "요청된 준비물이 없습니다." in rendered
    assert 'class="supply-item"' not in rendered
    assert 'id="inventoryTableBody"></tbody>' in rendered
    assert "지우개의 전달 결과를 확인하는 중" in rendered
    assert '<span class="step-label">지우개 확인·집기</span>' in rendered
    assert '<dd id="currentStepReason">지우개가 전달 위치에 놓였는지 확인</dd>' in rendered
    assert rendered.count('class="task-item-button"') == 3


@pytest.mark.parametrize("viewport_width", [1280, 390])
def test_preview_item_selection_changes_only_selected_detail(tmp_path: Path, viewport_width: int) -> None:
    """실제 버튼을 눌러 단계·근거 전환과 현재 작업·조회 선택 보존을 확인한다."""
    rendered, _ = _render_dashboard(
        tmp_path, runtime_profile="dev", camera_received=False, scenario="preview",
        viewport_width=viewport_width,
        interaction_script="""
          const read = () => ({
            title: document.getElementById('currentAction').textContent,
            location: document.getElementById('taskLocation').textContent,
            drawer: document.getElementById('drawerSelector').querySelector('[aria-pressed="true"]').getAttribute('data-drawer-id'),
            selection: document.getElementById('taskItemSelection').textContent,
            steps: document.getElementById('progressSteps').textContent,
            reason: document.getElementById('currentStepReason').textContent,
            observation: document.getElementById('currentStepObservation').textContent,
            pressed: [...document.querySelectorAll('.task-item-button')].map(b => b.getAttribute('aria-pressed')),
          });
          const snapshots = [read()];
          for (const index of [0, 2, 1]) {
            document.querySelectorAll('.task-item-button')[index].click();
            snapshots.push(read());
          }
          const result = document.createElement('pre');
          result.id = 'selection-test-result';
          result.textContent = JSON.stringify(snapshots);
          document.body.append(result);
        """,
    )
    match = re.search(r'<pre id="selection-test-result">(.*?)</pre>', rendered, re.DOTALL)
    assert match is not None, rendered
    initial, key, watch, eraser = json.loads(unescape(match.group(1)))
    assert "선택 물품: 지우개" in initial["selection"]
    assert "선택 물품: 차 키" in key["selection"]
    assert "차 키 집기" in key["steps"]
    assert key["observation"] == "예시 · 복구 완료"
    assert key["reason"] == "예시 · 작업 정리"
    assert key["pressed"] == ["true", "false", "false"]
    assert "선택 물품: 시계" in watch["selection"]
    assert "미실행" in watch["steps"]
    assert watch["observation"] == "관측 결과 없음"
    assert watch["pressed"] == ["false", "false", "true"]
    assert eraser == initial
    for snapshot in [key, watch, eraser]:
        for field in ["title", "location", "drawer"]:
            assert snapshot[field] == initial[field]


@pytest.mark.parametrize(("decision", "label"), [
    ("recover", "복구 요청 처리"), ("resume", "재개 요청 처리"),
    ("end", "작업 종료 처리"), ("registered", "재개 질문·요청 등록"),
    ("closed", "재개 대기 종료"), ("future_decision", "접수 상태 확인 전"),
])
def test_control_decisions_do_not_inherit_execution_success(tmp_path: Path, decision, label) -> None:
    payload = _request_result(decision)
    # ID가 같더라도 비실행 결정에 지난 완료 결과를 붙이지 않는다.
    payload["last_intent"]["run_id"] = "r1"
    payload["last_intent"]["intent"] = "future_intent"
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False,
                                    runner_payloads=[payload])
    assert label in rendered
    assert "인텐트: future_intent · eraser" in rendered
    assert "처리 결과 확인 전" in rendered
    assert "실행 완료" not in rendered
    assert "전달 완료" not in rendered
    assert f'id="mobileUnderstoodText">인텐트: future_intent · eraser</dd>' in rendered


@pytest.mark.parametrize("change", ["older-seq", "old-boot", "restart", "invalid-seq", "disconnect"])
def test_live_task_reboot_and_ordering(tmp_path: Path, change: str) -> None:
    """현재 단계 수신 뒤 늦은 상태·재기동·단절이 요청/실행을 잘못 살리지 않는지 검증한다."""
    first = _request_result()
    first.update(phase="running", task_id="current_task", current_step="step_live", seq=8)
    following = _request_result()
    following.update(boot_id="boot-2", seq=1, last_intent=None, last=None)
    payloads = [first, following]
    if change == "older-seq":
        following.update(boot_id="boot-1", seq=7)
    elif change == "old-boot":
        payloads.append(first)
    elif change == "invalid-seq":
        following["seq"] = "9"
    elif change == "disconnect":
        payloads[1] = None
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False,
                                    runner_payloads=payloads)
    assert "작업 장소 확인 전 → 목적지 확인 전" in rendered
    assert "전달 완료" not in rendered
    if change == "older-seq":
        assert "실행 중 · 태스크: current_task · 단계: 단계명 확인 전" in rendered
        assert "Runner 보고 단계 · 완료 여부 확인 전" in rendered
    else:
        assert "step_live" not in rendered
        assert "실행 완료" not in rendered
        assert '<p id="understoodText">확인 전</p>' in rendered
        assert "현재 작업 확인 전" in rendered if change in ("invalid-seq", "disconnect") else "현재 실행 없음 · 대기" in rendered


@pytest.mark.parametrize("viewport_width", [1280, 390])
def test_live_drawer_selection_does_not_change_execution(tmp_path: Path, viewport_width: int) -> None:
    """PC·모바일 조회 서랍 변경은 현재 실행 제목·현재 단계·미확정 작업 위치를 바꾸지 않는다."""
    payload = _request_result("reject", "BUSY")
    payload.update(phase="running", task_id="actual_task", current_step="actual_step")
    rendered, _ = _render_dashboard(
        tmp_path, runtime_profile="dev", camera_received=False, runner_payloads=[payload],
        viewport_width=viewport_width,
        robot_state_payload={"robot_pose": {"robot": "home"}, "gripper": {"robot": "empty"},
                             "open": {"drawer_top": False, "drawer_bottom": True},
                             "located_in": {"eraser": "drawer_top"}},
        interaction_script="""
          setTimeout(() => {
            const read = () => [document.getElementById('currentAction').textContent,
              document.getElementById('taskLocation').textContent,
              document.getElementById('progressSteps').textContent];
            const before = read();
            document.querySelector('#drawerSelector [data-drawer-id="drawer_bottom"]').click();
            const output = document.createElement('pre');
            output.id = 'live-selection-result';
            output.textContent = JSON.stringify([before, read()]);
            document.body.append(output);
          }, 500);
        """,
    )
    match = re.search(r'<pre id="live-selection-result">(.*?)</pre>', rendered, re.DOTALL)
    assert match is not None, rendered
    before, after = json.loads(unescape(match.group(1)))
    assert before == after
    assert "actual_task" in before[0] and "단계명 확인 전" in before[2]
    assert before[1] == "작업 장소 확인 전 → 목적지 확인 전"
    # 빈 아래 서랍을 선택했으므로 물품 행 대신 공통 출처 안내로 기억 상태 표시를 확인한다.
    assert "Runner 기억 상태" in rendered
    assert "거절 · 사유 코드: BUSY" in rendered
    assert "실행 완료" not in rendered


@pytest.mark.parametrize("viewport_width", [1280, 390])
def test_finished_execution_detail_reads_actual_records(tmp_path: Path, viewport_width: int) -> None:
    """종료 물품 순서/전달 집계/선택 단계는 기록에서 읽고 현재 작업 제목에는 섞지 않는다."""
    from ready2go_web.adapters.execution_reader import JsonlExecutionReader
    records = {
        "r1": [("runs", {"run_id": "r1", "task_id": "find_item", "overall_status": "FAILED",
            "ended_at": "2026-10-15T00:00:00Z", "inputs": {"semantic": {"items": ["watch", "eraser"],
                "evidence": {"eraser": {"list": "commute_set"}}}},
            "items": [{"item": "eraser", "run_id": "child", "status": "DELIVERED"},
                      {"item": "watch", "run_id": None, "status": "NOT_RUN"}]})],
        "child": [("runs", {"run_id": "child", "parent_run_id": "r1"}),
                  ("steps", {"run_id": "child", "seq": 0, "id": "recorded_pick", "status": "SUCCESS",
                             "result": {"verified": True}})],
    }
    for run_id, entries in records.items():
        (tmp_path / f"{run_id}.jsonl").write_text("".join(
            json.dumps({"collection": collection, "doc": doc}) + "\n" for collection, doc in entries))
    rendered, _ = _render_dashboard(
        tmp_path, runtime_profile="dev", camera_received=False, viewport_width=viewport_width,
        runner_payloads=[_request_result(result_status="FAILED")],
        execution_reader=JsonlExecutionReader(tmp_path), enable_deferred_detail=True,
        interaction_script="""
          setTimeout(() => {
            const buttons = document.querySelectorAll('.task-item-button');
            const first = document.getElementById('progressSteps').textContent;
            const reason = document.getElementById('currentStepReason').textContent;
            buttons[1].click();
            const second = document.getElementById('progressSteps').textContent;
            const output = document.createElement('pre');
            output.id = 'record-test-result';
            output.textContent = JSON.stringify([first, reason, second]);
            document.body.append(output);
          }, 700);
        """,
    )
    match = re.search(r'<pre id="record-test-result">(.*?)</pre>', rendered, re.DOTALL)
    assert match is not None, rendered
    first, reason, second = json.loads(unescape(match.group(1)))
    assert "recorded_pick" in first and "단계 성공" in first
    assert "semantic.evidence" in reason and "commute_set" in reason
    assert second == ""
    assert "1 / 2 전달 완료 · 종료 기록 기준" in rendered
    assert "현재 실행 없음 · 대기" in rendered
    assert "종료 기록 조회 · 현재 실행 상세 아님" in rendered
    assert "작업 장소 확인 전 → 목적지 확인 전" in rendered


@pytest.mark.parametrize("transition", ["reboot", "reject", "disconnect", "other-run"])
def test_finished_detail_is_cleared_when_identity_changes(tmp_path: Path, transition: str) -> None:
    """기록을 표시한 뒤 기동·요청·연결이 달라지면 이전 단계/전달 수를 남기지 않는다."""
    from ready2go_web.adapters.execution_reader import JsonlExecutionReader
    run = {"run_id": "r1", "task_id": "find_item", "overall_status": "COMPLETED",
           "ended_at": "2026-10-15T00:00:00Z", "inputs": {},
           "items": [{"item": "eraser", "run_id": None, "status": "DELIVERED"}]}
    (tmp_path / "r1.jsonl").write_text(json.dumps({"collection": "runs", "doc": run}) + "\n")
    first = _request_result()
    second = _request_result("reject", "BUSY")
    second["seq"] = 2
    if transition == "reboot":
        second.update(boot_id="boot-2", seq=1, last_intent=None, last=None)
    elif transition == "disconnect":
        second = None
    elif transition == "other-run":
        second = _request_result(result_run="other")
        second["seq"] = 2
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False,
        runner_payloads=[first, second], execution_reader=JsonlExecutionReader(tmp_path), enable_deferred_detail=True)
    assert "1 / 1 전달 완료" not in rendered
    assert "종료 기록 조회 · 현재 실행 상세 아님" not in rendered
    assert 'class="task-item-button"' not in rendered


@pytest.mark.parametrize("scenario", ["default", "unknown"])
def test_no_example_task_in_normal_scenario(tmp_path: Path, scenario: str) -> None:
    """일반/미정의 접속에서는 예시 버튼·단계·제목이 남지 않는다."""
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False, scenario=scenario)
    assert 'class="task-item-button"' not in rendered
    assert "지우개의 전달 결과를 확인하는 중" not in rendered
    assert "차 키 집기" not in rendered


@pytest.mark.parametrize("viewport_width", [1280, 390])
def test_collapsed_selection_opens_details_without_replacing_button(tmp_path: Path, viewport_width: int) -> None:
    """접힌 상태에서 선택하면 상세가 열리고 버튼/제목 DOM·키보드 포커스는 보존된다."""
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False,
        scenario="preview", viewport_width=viewport_width, interaction_script="""
          document.getElementById('taskDetailsToggle').click();
          const button = document.querySelector('.task-item-button');
          const heading = document.getElementById('taskHeadingIcon');
          button.focus(); button.click();
          const out = document.createElement('pre'); out.id = 'focus-result';
          out.textContent = JSON.stringify([
            !document.getElementById('taskDetails').hidden,
            document.getElementById('taskDetailsToggle').getAttribute('aria-expanded'),
            button === document.querySelector('.task-item-button'),
            heading === document.getElementById('taskHeadingIcon'),
            document.activeElement === button]);
          document.body.append(out);
        """)
    match = re.search(r'<pre id="focus-result">(.*?)</pre>', rendered)
    assert match is not None
    assert json.loads(unescape(match.group(1))) == [True, "true", True, True, True]


@pytest.mark.parametrize("scenario", ["error", "long"])
def test_preview_labels_are_consistent(tmp_path: Path, scenario: str) -> None:
    """시나리오가 준비물·실행 항목에 동일한 이름/오류 어휘를 적용한다."""
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False, scenario=scenario)
    if scenario == "error":
        assert "지우개 · 오류" in rendered
        assert "지우개 · 확인 불가" not in rendered
    else:
        assert rendered.count("업무용 손목시계 및 교통카드 케이스") >= 2



def test_finished_detail_is_cached_and_excluded_items_do_not_take_numbers(tmp_path: Path) -> None:
    """동일 key의 종료 기록은 한 번만 읽고 제외 항목 다음 실행 번호는 연속이다."""
    class Reader:
        def __init__(self):
            self.calls = 0

        def read_run(self, run_id):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("a repeated lookup would fail")
            return {"run": {"run_id": "r1", "task_id": "find_item", "overall_status": "COMPLETED",
                "ended_at": "2026-10-15T00:00:00Z", "inputs": {}, "items": [
                    {"item": "eraser", "run_id": None, "status": "DELIVERED"},
                    {"item": "excluded", "run_id": None, "status": "EXCLUDED"},
                    {"item": "watch", "run_id": None, "status": "DELIVERED"}]}, "steps": []}

    reader = Reader()
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False,
        runner_payloads=[_request_result()], execution_reader=reader, enable_deferred_detail=True)
    assert reader.calls == 1
    assert "2 / 2 전달 완료" in rendered
    assert "제외 excluded" in rendered
    assert "2. watch" in rendered and "3. watch" not in rendered


@pytest.mark.parametrize("viewport_width", [1280, 390])
@pytest.mark.parametrize("mode", ["completed", "running", "rejected"])
def test_demo_scope_never_requests_execution_detail(tmp_path, viewport_width, mode):
    """운영 응답 그대로 시험: 종료/실행/다른 요청 거절에도 상세 HTTP 요청과 예시 진행은 없다."""
    requested = []
    payload = _request_result("reject", "BUSY") if mode == "rejected" else _request_result()
    if mode != "completed":
        payload.update(phase="running", task_id="live_task", current_step="live_step")
    rendered, _ = _render_dashboard(
        tmp_path, runtime_profile="dev", camera_received=False,
        viewport_width=viewport_width, runner_payloads=[payload],
        on_detail_request=lambda: requested.append(True))
    assert requested == []
    assert 'class="task-item-button"' not in rendered
    assert "물품별 진행 정보 미연결" in rendered
    assert "물품별 전달 결과 확인 전" in rendered
    assert "종료 기록 조회 · 현재 실행 상세 아님" not in rendered
    assert "작업 장소 확인 전 → 목적지 확인 전" in rendered
    if mode != "completed":
        assert "실행 중 · 태스크: live_task · 단계: 단계명 확인 전" in rendered
        assert "Runner 보고 단계 · 완료 여부 확인 전" in rendered
    if mode == "rejected":
        assert "거절 · 사유 코드: BUSY" in rendered
        assert "실행 완료" not in rendered
    elif mode == "completed":
        assert "실행 완료" in rendered  # 같은 요청의 처리 결과는 상세 비활성화와 무관하게 유지한다.


@pytest.mark.parametrize("viewport_width", [1280, 390])
def test_current_step_uses_registered_name(tmp_path, viewport_width):
    """실제 태스크/스킬 정의로 사진의 ID를 한국어 단계로 표시하되 결과를 추정하지 않는다."""
    from ready2go_web.core.definition_catalog import DefinitionSettings, load_definition_snapshot
    root = Path(__file__).resolve().parents[2]
    snapshot = load_definition_snapshot(DefinitionSettings(root / "knowledge/robot_ontology.jsonld", root / "tasks"))
    payload = _request_result()
    payload.update(phase="running", task_id="find_with_unpack", current_step="s8.t2.e1")
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False,
        viewport_width=viewport_width, runner_payloads=[payload], definition_snapshot=snapshot)
    assert "전달 트레이에 물품 놓기" in rendered
    assert "단계: s8.t2.e1" not in rendered
    assert "단계 ID: s8.t2.e1" in rendered
    assert "Runner 보고 단계 · 완료 여부 확인 전" in rendered
    assert "물품별 전달 결과 확인 전" in rendered


@pytest.mark.parametrize("transition", ["same", "disconnect", "restart", "invalid"])
def test_late_definitions_refresh_only_valid_current_task(tmp_path, transition):
    """정의가 늦게 도착하면 즉시 이름 갱신, 단절/기동 변경/오류 뒤에는 이전 작업 복원 금지."""
    from ready2go_web.core.definition_catalog import DefinitionSettings, load_definition_snapshot
    root = Path(__file__).resolve().parents[2]
    snapshot = load_definition_snapshot(DefinitionSettings(root / "knowledge/robot_ontology.jsonld", root / "tasks"))
    first = _request_result()
    first.update(phase="running", task_id="find_with_unpack", current_step="s8.t2.e1")
    second = dict(first)
    if transition == "disconnect":
        second = None
    elif transition == "restart":
        second.update(boot_id="new-boot", phase="idle", task_id=None, current_step=None)
    elif transition == "invalid":
        second["seq"] = "invalid"
    rendered, _ = _render_dashboard(tmp_path, runtime_profile="dev", camera_received=False,
        runner_payloads=[first, second], definition_snapshot=snapshot, definition_delay_ms=1500,
        status_poll_interval_ms=10000 if transition == "same" else 1000)
    if transition == "same":
        assert "전달 트레이에 물품 놓기" in rendered
        assert "Runner 보고 단계 · 완료 여부 확인 전" in rendered
    else:
        assert "전달 트레이에 물품 놓기" not in rendered
        assert "단계 ID: s8.t2.e1" not in rendered
        assert "현재 실행 없음 · 대기" in rendered if transition == "restart" else "현재 작업 확인 전" in rendered
