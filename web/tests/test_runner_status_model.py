"""Runner 요청·결과 JavaScript 내부 모델을 브라우저에서 단위 검증한다."""

from __future__ import annotations

from html import unescape
import json
from pathlib import Path
import re
import shutil
import subprocess
from threading import Thread

import pytest
from flask import Response
from werkzeug.serving import make_server

from ready2go_web.server import create_app


def _evaluate_runner_model(tmp_path: Path, cases: list[dict]) -> list[dict]:
    """제품 JavaScript 파서에 입력 목록을 전달하고 직렬화된 결과를 반환한다."""
    # 저장소에 Node.js 의존성이 없으므로 실제 지원 브라우저에서 순수 파서 함수를 실행한다.
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if chrome is None:
        pytest.skip("headless Chrome을 사용할 수 없어 Runner 모델 단위시험을 생략합니다")

    # JSON 문자열은 Python이 만들고 JavaScript는 제품 모듈의 공개 함수만 호출한다.
    encoded_cases = json.dumps(cases, ensure_ascii=False).replace("</", "<\\/")
    harness = f"""<!doctype html>
<meta charset=\"utf-8\">
<script src=\"/runner-status-model.js\"></script>
<pre id=\"result\"></pre>
<script>
  const cases = {encoded_cases};
  const before = JSON.stringify(cases);
  const outputs = cases.map((entry) => window.ROKEY_RUNNER_STATUS_MODEL.parseRunnerRecords(entry));
  document.getElementById("result").textContent = JSON.stringify({{
    outputs,
    inputUnchanged: before === JSON.stringify(cases),
  }});
</script>"""

    # 시험 전용 경로만 추가하고 제품 Flask의 실제 정적 allowlist로 파서 파일을 제공한다.
    app = create_app()

    @app.get("/__test__/runner-status-model")
    def runner_status_model_harness() -> Response:
        # 브라우저가 실행할 최소 HTML이며 제품 화면이나 REST 상태에는 영향을 주지 않는다.
        return Response(harness, mimetype="text/html")

    # 사용 가능한 임의 로컬 포트에서 시험 서버를 실행한다.
    server = make_server("127.0.0.1", 0, app)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        # DOM dump 전에 동기 파서와 결과 직렬화가 끝날 만큼의 가상 시간을 제공한다.
        result = subprocess.run(
            [
                chrome,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                f"--user-data-dir={tmp_path / 'chrome-profile'}",
                "--virtual-time-budget=500",
                "--dump-dom",
                f"http://127.0.0.1:{server.server_port}/__test__/runner-status-model",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    finally:
        # 성공·실패와 무관하게 시험 서버와 포트를 정리한다.
        server.shutdown()
        server_thread.join(timeout=5)

    # Chrome 실행 실패와 JavaScript 실행 실패를 빈 결과로 오해하지 않는다.
    assert result.returncode == 0, result.stderr
    match = re.search(r'<pre id="result">(.*?)</pre>', result.stdout, flags=re.DOTALL)
    assert match is not None, result.stdout
    decoded = json.loads(unescape(match.group(1)))
    # 파서가 입력 객체나 targets 배열을 직접 수정하지 않았는지 함께 검사한다.
    assert decoded["inputUnchanged"] is True
    return decoded["outputs"]


def test_runner_records_distinguish_valid_absent_and_invalid_values(tmp_path: Path) -> None:
    """정상·미수신·형식 오류를 구분하고 정상 필드 일부만 재사용하지 않는다."""
    cases = [
        {
            "last_intent": {
                "intent": "find_item",
                "targets": ["wallet"],
                "decision": "run",
                "reason": None,
                "task_id": "find_item",
                "request_id": "request-001",
                "run_id": "run-001",
                "stt_text": "지갑 찾아줘",
            },
            "last": {
                "task_id": "find_item",
                "run_id": "run-001",
                "overall_status": "COMPLETED",
                "error_code": None,
                "failed_step": None,
                "problems": [],
            },
        },
        # null 두 값은 아직 요청·결과가 없는 정상 상태다.
        {"last_intent": None, "last": None},
        # targets에 문자열 이외 항목이 있으면 요청 전체가 invalid다.
        {
            "last_intent": {
                "intent": "find_item",
                "targets": ["wallet", 1],
                "decision": "run",
                "reason": None,
                "task_id": "find_item",
                "request_id": "request-002",
                "run_id": "run-002",
            },
            "last": None,
        },
        # 필드 누락과 빈 실행 ID를 각각 진단하되 정상 요청과 결합하지 않는다.
        {
            "last_intent": {
                "intent": "find_item",
                "targets": [],
                "decision": "hold",
                "task_id": None,
                "request_id": "request-003",
                "run_id": None,
            },
            "last": {
                "task_id": "find_item",
                "run_id": " ",
                "overall_status": "FAILED",
                "error_code": "TASK_INVALID",
            },
        },
        # source.data 자체가 객체가 아니면 두 하위 기록을 모두 확인 전으로 둔다.
        None,
    ]

    outputs = _evaluate_runner_model(tmp_path, cases)

    # 정상 입력은 화면용 camelCase 복사본으로 변환하고 사용하지 않는 필드는 제외한다.
    assert outputs[0] == {
        "status": "valid",
        "lastIntent": {
            "status": "valid",
            "value": {
                "intent": "find_item",
                "targets": ["wallet"],
                "decision": "run",
                "reason": None,
                "taskId": "find_item",
                "requestId": "request-001",
                "runId": "run-001",
            },
            "invalidFields": [],
        },
        "lastResult": {
            "status": "valid",
            "value": {
                "taskId": "find_item",
                "runId": "run-001",
                "overallStatus": "COMPLETED",
                "errorCode": None,
                "failedStep": None,
            },
            "invalidFields": [],
        },
    }
    # 요청과 결과가 아직 없다는 사실은 형식 오류와 다르게 absent로 보존한다.
    assert outputs[1]["status"] == "valid"
    assert outputs[1]["lastIntent"]["status"] == "absent"
    assert outputs[1]["lastResult"]["status"] == "absent"
    # 잘못된 targets는 요청 전체를 invalid로 만들고 결과 null은 absent로 유지한다.
    assert outputs[2]["status"] == "invalid"
    assert outputs[2]["lastIntent"]["invalidFields"] == ["targets"]
    assert outputs[2]["lastIntent"]["value"] is None
    assert outputs[2]["lastResult"]["status"] == "absent"
    # 누락 필드와 잘못된 결과 필드를 모두 수집해 화면의 확인 전 근거로 제공한다.
    assert outputs[3]["lastIntent"]["invalidFields"] == ["reason"]
    assert outputs[3]["lastResult"]["invalidFields"] == ["failed_step", "run_id"]
    # Runner data 자체가 잘못되면 과거 요청·결과를 부분적으로 남기지 않는다.
    assert outputs[4]["status"] == "invalid"
    assert outputs[4]["lastIntent"]["invalidFields"] == ["runner"]
    assert outputs[4]["lastResult"]["invalidFields"] == ["runner"]


def test_runner_records_accept_every_checked_in_contract_example(tmp_path: Path) -> None:
    """공동 Runner 상태 예시의 요청·결과 형식이 웹 내부 모델과 계속 맞는지 확인한다."""
    # 시험 파일에서 저장소 루트를 찾고 실행 계약의 원본 예시를 직접 읽는다.
    repository_root = Path(__file__).resolve().parents[2]
    contract_path = repository_root / "contracts" / "examples" / "runner_status.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    # 설명용 _comment는 제외하고 실제 status 객체만 브라우저 파서 입력으로 전달한다.
    statuses = [case["status"] for case in contract["cases"]]
    outputs = _evaluate_runner_model(tmp_path, statuses)

    # 계약 예시가 바뀌었는데 웹 파서를 갱신하지 않은 경우 해당 case 이름을 함께 보여준다.
    invalid_cases = [
        case["case"]
        for case, output in zip(contract["cases"], outputs, strict=True)
        if output["status"] != "valid"
    ]
    assert invalid_cases == []
