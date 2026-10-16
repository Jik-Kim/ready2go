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


def _evaluate_runner_model(tmp_path: Path, cases: list[dict], *, expression: str | None = None) -> list[dict]:
    """제품 JavaScript 파서에 입력 목록을 전달하고 직렬화된 결과를 반환한다."""
    # 저장소에 Node.js 의존성이 없으므로 실제 지원 브라우저에서 순수 파서 함수를 실행한다.
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
    if chrome is None:
        pytest.skip("headless Chrome을 사용할 수 없어 Runner 모델 단위시험을 생략합니다")

    # JSON 문자열은 Python이 만들고 JavaScript는 제품 모듈의 공개 함수만 호출한다.
    encoded_cases = json.dumps(cases, ensure_ascii=False).replace("</", "<\\/")
    # 순수 파서뿐 아니라 순서·상세 토큰·취소 동작도 동일한 실제 브라우저에서 검증한다.
    evaluation = expression or "cases.map((entry) => window.ROKEY_RUNNER_STATUS_MODEL.parseRunnerRecords(entry))"
    harness = f"""<!doctype html>
<meta charset=\"utf-8\">
<script src=\"/runner-status-model.js\"></script>
<script src=\"/status-api.js\"></script>
<pre id=\"result\"></pre>
<script>
  (async () => {{
  const cases = {encoded_cases};
  const before = JSON.stringify(cases);
  const outputs = await ({evaluation});
  document.getElementById("result").textContent = JSON.stringify({{
    outputs,
    inputUnchanged: before === JSON.stringify(cases),
  }});
  }})();
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
        "connection": {
            "status": "linked",
            "reason": None,
            "value": {
                "runId": "run-001",
                "request": {
                    "intent": "find_item",
                    "targets": ["wallet"],
                    "decision": "run",
                    "reason": None,
                    "taskId": "find_item",
                    "requestId": "request-001",
                    "runId": "run-001",
                },
                "result": {
                    "taskId": "find_item",
                    "runId": "run-001",
                    "overallStatus": "COMPLETED",
                    "errorCode": None,
                    "failedStep": None,
                },
            },
        },
    }
    # 요청과 결과가 아직 없다는 사실은 형식 오류와 다르게 absent로 보존한다.
    assert outputs[1]["status"] == "valid"
    assert outputs[1]["lastIntent"]["status"] == "absent"
    assert outputs[1]["lastResult"]["status"] == "absent"
    assert outputs[1]["connection"] == {
        "status": "absent", "reason": "records_absent", "value": None,
    }
    # 잘못된 targets는 요청 전체를 invalid로 만들고 결과 null은 absent로 유지한다.
    assert outputs[2]["status"] == "invalid"
    assert outputs[2]["lastIntent"]["invalidFields"] == ["targets"]
    assert outputs[2]["lastIntent"]["value"] is None
    assert outputs[2]["lastResult"]["status"] == "absent"
    assert outputs[2]["connection"]["reason"] == "invalid_record"
    # 누락 필드와 잘못된 결과 필드를 모두 수집해 화면의 확인 전 근거로 제공한다.
    assert outputs[3]["lastIntent"]["invalidFields"] == ["reason"]
    assert outputs[3]["lastResult"]["invalidFields"] == ["failed_step", "run_id"]
    assert outputs[3]["connection"]["status"] == "invalid"
    # Runner data 자체가 잘못되면 과거 요청·결과를 부분적으로 남기지 않는다.
    assert outputs[4]["status"] == "invalid"
    assert outputs[4]["lastIntent"]["invalidFields"] == ["runner"]
    assert outputs[4]["lastResult"]["invalidFields"] == ["runner"]


def test_runner_records_link_only_an_accepted_request_with_matching_ids(tmp_path: Path) -> None:
    """같은 실행·태스크 ID만 연결하고 불일치·누락·비실행 결정을 분리한다."""
    # 각 사례는 실제 Runner 필드 전체를 넣어 파싱과 연결 판정을 한 번에 검증한다.
    def intent(decision: str, run_id: str | None, task_id: str | None = "find_item") -> dict:
        # 요청별로 달라지는 결정·실행 ID·태스크 ID 외 필드는 정상 계약값으로 고정한다.
        return {
            "intent": "find_item",
            "targets": ["wallet"],
            "decision": decision,
            "reason": None,
            "task_id": task_id,
            "request_id": "request-link-test",
            "run_id": run_id,
        }

    def result(run_id: str, task_id: str = "find_item") -> dict:
        # 결과는 연결 판정에 필요한 두 ID와 현재 Runner 완료 필드를 모두 제공한다.
        return {
            "task_id": task_id,
            "run_id": run_id,
            "overall_status": "COMPLETED",
            "error_code": None,
            "failed_step": None,
        }

    cases = [
        # 실행 수락 요청과 결과의 ID가 같을 때만 연결된다.
        {"last_intent": intent("run", "run-001"), "last": result("run-001")},
        # 서로 다른 ID는 각각 유효해도 같은 실행으로 묶지 않는다.
        {"last_intent": intent("run", "run-002"), "last": result("run-previous")},
        # 실행 ID가 같아도 태스크가 다르면 모순된 결과이므로 연결하지 않는다.
        {"last_intent": intent("run", "run-002"), "last": result("run-002", "different_task")},
        # 양쪽 task_id가 모두 null이어도 동일 태스크라는 근거가 없으므로 연결하지 않는다.
        {"last_intent": intent("run", "run-003", None), "last": result("run-003", None)},
        # 한쪽 task_id만 null인 두 방향도 값 불일치보다 누락으로 먼저 분류한다.
        {"last_intent": intent("run", "run-004", None), "last": result("run-004")},
        {"last_intent": intent("run", "run-005"), "last": result("run-005", None)},
        # run 결정에 ID가 없으면 결과 ID를 현재 요청에 추정해 넣지 않는다.
        {"last_intent": intent("run", None), "last": result("run-006")},
        # hold와 reject는 과거 결과 ID가 우연히 같아도 실행 결과로 연결하지 않는다.
        {"last_intent": intent("hold", None), "last": result("run-007")},
        {"last_intent": intent("reject", None), "last": result("run-008")},
        # 수락된 실행이 진행 중이라 결과가 없으면 요청만 유지한다.
        {"last_intent": intent("run", "run-009"), "last": None},
    ]

    outputs = _evaluate_runner_model(tmp_path, cases)

    # 첫 사례만 연결되며 결합 모델도 같은 실행 ID와 두 내부 레코드를 보존한다.
    assert outputs[0]["connection"]["status"] == "linked"
    assert outputs[0]["connection"]["reason"] is None
    assert outputs[0]["connection"]["value"]["runId"] == "run-001"
    # 나머지는 구체적인 분리 이유를 남겨 화면이 완료 결과로 오인하지 않게 한다.
    assert [output["connection"]["reason"] for output in outputs[1:]] == [
        "run_id_mismatch",
        "task_id_mismatch",
        "task_id_missing",
        "task_id_missing",
        "task_id_missing",
        "run_id_missing",
        "non_run_decision",
        "non_run_decision",
        "last_result_absent",
    ]
    assert all(output["connection"]["status"] == "unlinked" for output in outputs[1:])
    assert all(output["connection"]["value"] is None for output in outputs[1:])


def test_runner_result_accepts_only_contract_overall_status_values(tmp_path: Path) -> None:
    """Runner 결과 enum 네 값만 정상으로 받고 임의 문자열 결과는 연결하지 않는다."""
    # 같은 정상 요청에 결과 상태만 바꿔 파서의 enum 경계를 직접 확인한다.
    intent = {
        "intent": "find_item",
        "targets": ["wallet"],
        "decision": "run",
        "reason": None,
        "task_id": "find_item",
        "request_id": "request-status-test",
        "run_id": "run-status-test",
    }

    def result(overall_status: str) -> dict:
        # 결과의 다른 필드는 유효하게 고정해 overall_status만 시험 원인이 되게 한다.
        return {
            "task_id": "find_item",
            "run_id": "run-status-test",
            "overall_status": overall_status,
            "error_code": None,
            "failed_step": None,
        }

    statuses = ["COMPLETED", "FAILED", "ABORTED", "SUSPENDED", "SUCCESS"]
    outputs = _evaluate_runner_model(
        tmp_path,
        [{"last_intent": intent, "last": result(status)} for status in statuses],
    )

    # 계약과 Runner 구현에 있는 네 상태는 파싱과 연결이 모두 정상이어야 한다.
    assert [output["lastResult"]["status"] for output in outputs[:4]] == ["valid"] * 4
    assert [output["connection"]["status"] for output in outputs[:4]] == ["linked"] * 4
    # 계약 밖 문자열은 결과 전체를 invalid로 만들어 같은 ID여도 연결하지 않는다.
    assert outputs[4]["lastResult"]["status"] == "invalid"
    assert outputs[4]["lastResult"]["invalidFields"] == ["overall_status"]
    assert outputs[4]["connection"]["reason"] == "invalid_record"


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


def test_status_guard_rejects_old_boot_and_sequence(tmp_path: Path) -> None:
    """재기동 역전·낮은 seq·중복·동일 seq 변조·잘못된 순서 필드를 구분한다."""
    cases = [
        {"boot_id": "a", "seq": 2}, {"boot_id": "a", "seq": 1},
        {"boot_id": "a", "seq": 2}, {"boot_id": "a", "seq": 2, "phase": "idle"},
        {"boot_id": "b", "seq": 0}, {"boot_id": "a", "seq": 100},
        {"boot_id": "b", "seq": "3"}, {"boot_id": "b", "seq": -1},
        {"boot_id": "", "seq": 3}, {"boot_id": "b", "seq": 3},
    ]
    output = _evaluate_runner_model(tmp_path, cases, expression="""(() => {
      const guard = window.ROKEY_RUNNER_STATUS_MODEL.createStatusGuard();
      return cases.map(value => guard.accept(value));
    })()""")
    assert [entry["status"] for entry in output] == [
        "valid", "stale", "valid", "invalid", "valid", "stale", "invalid", "invalid", "invalid", "valid",
    ]
    assert output[4]["restarted"] is True


def test_detail_guard_invalidates_inflight_identity(tmp_path: Path) -> None:
    """run 전환·재기동·단절 후 같은 run 복귀에도 이전 상세 토큰은 폐기한다."""
    output = _evaluate_runner_model(tmp_path, [], expression="""(() => {
      const guard = window.ROKEY_STATUS_API.createDetailGuard();
      const result = [guard.capture() === null];
      guard.setContext('a', 'r1');
      const token = guard.capture();
      result.push(guard.matches(token, {bootId:'a', runId:'r1'}));
      result.push(guard.matches(token, {bootId:'a', runId:'r2'}));
      guard.setContext('a', 'r2');
      result.push(guard.matches(token, {bootId:'a', runId:'r1'}));
      guard.setContext('b', 'r1');
      result.push(guard.matches(token, {bootId:'b', runId:'r1'}));
      const second = guard.capture();
      guard.setContext(null, null);
      guard.setContext('b', 'r1');
      result.push(guard.matches(second, {bootId:'b', runId:'r1'}));
      return result;
    })()""")
    assert output == [True, True, False, False, False, False]


def test_stopped_poller_ignores_late_failure(tmp_path: Path) -> None:
    """fetch가 취소 신호를 무시하고 늦게 실패해도 종료된 화면의 콜백은 호출하지 않는다."""
    output = _evaluate_runner_model(tmp_path, [], expression="""(async () => {
      let rejectFetch, signal;
      const calls = [];
      const poller = window.ROKEY_STATUS_API.createPoller({
        fetchStatus: (_, options) => { signal = options.signal; return new Promise((_, reject) => { rejectFetch = reject; }); },
        onSuccess: () => calls.push('success'), onFailure: () => calls.push('failure'),
        schedule: () => calls.push('scheduled'), cancelSchedule: () => {},
      });
      poller.start();
      poller.stop();
      rejectFetch(new Error('late response'));
      await Promise.resolve();
      return [signal.aborted, calls.length];
    })()""")
    assert output == [True, 0]


def test_current_task_uses_only_reported_phase_and_step(tmp_path: Path) -> None:
    """대기·잠김은 지난 단계가 남아 있어도 지우고 현재 단계로 이력을 만들지 않는다."""
    cases = [
        {"phase": "running", "task_id": "task", "current_step": "s4"},
        {"phase": "idle", "task_id": "old", "current_step": "s4"},
        {"phase": "halted", "task_id": "old", "current_step": "s4"},
        {"phase": "future", "task_id": "old", "current_step": "s4"},
        {"phase": "running", "task_id": [], "current_step": {}},
    ]
    output = _evaluate_runner_model(tmp_path, cases, expression=
        "cases.map(value => window.ROKEY_RUNNER_STATUS_MODEL.currentTaskView(value))")
    assert len(output[0]["steps"]) == 1
    assert output[0]["steps"][0]["id"] == "s4"
    assert output[0]["steps"][0]["status"] == "current"
    assert all(not view["steps"] for view in output[1:])
    assert "old" not in str(output[1:])
    assert output[3]["title"] == "현재 작업 확인 전"


def test_stopped_poller_ignores_late_success(tmp_path: Path) -> None:
    """JSON 파싱 중 종료되어도 정상 응답이 과거 화면을 복원하지 않는다."""
    output = _evaluate_runner_model(tmp_path, [], expression="""(async () => {
      const payload = await fetch('/api/status').then(response => response.json());
      let resolveJson;
      const calls = [];
      const poller = window.ROKEY_STATUS_API.createPoller({
        fetchStatus: async () => ({ok: true, json: () => new Promise(resolve => { resolveJson = resolve; })}),
        onSuccess: () => calls.push('success'), onFailure: () => calls.push('failure'),
        schedule: () => calls.push('scheduled'), cancelSchedule: () => {},
      });
      poller.start();
      await Promise.resolve();
      poller.stop();
      resolveJson(payload);
      await Promise.resolve();
      return calls;
    })()""")
    assert output == []


def test_current_step_name_requires_exact_task_and_id(tmp_path: Path) -> None:
    """등록 이름만 사용하고 group/미등록/비슷한 ID는 이름 확인 전으로 남긴다."""
    output = _evaluate_runner_model(tmp_path, [], expression="""(() => {
      const definitions = [{id: 'find_with_unpack', step_labels: {'s8.t2.e1': '전달 트레이에 물품 놓기'}}];
      return [['find_with_unpack', 's8.t2.e1'], ['find_with_unpack', 's8.t2.e10'],
        ['group_commute', 's8.t2.e1']].map(([task_id, current_step]) =>
        window.ROKEY_RUNNER_STATUS_MODEL.currentTaskView({phase: 'running', task_id, current_step}, definitions));
    })()""")
    assert output[0]['steps'][0]['label'] == '전달 트레이에 물품 놓기'
    assert all('단계명 확인 전' in row['steps'][0]['label'] for row in output[1:])
    assert all(len(row['steps']) == 1 and row['steps'][0]['status'] == 'current' for row in output)



def test_reported_step_does_not_claim_active_execution(tmp_path: Path) -> None:
    """현재 상태만으로 단계의 종료 직후와 실행 중을 구분할 수 없음을 표시한다."""
    output = _evaluate_runner_model(tmp_path, [], expression="""(() => {
      const model = window.ROKEY_RUNNER_STATUS_MODEL;
      return [model.currentTaskView({phase:'running', task_id:'task', current_step:'s1'}),
        model.currentTaskView({phase:'idle', task_id:'task', current_step:'s1'})];
    })()""")
    assert output[0]['steps'][0]['statusLabel'] == 'Runner 보고 단계 · 완료 여부 확인 전'
    assert '진행 중' not in output[0]['steps'][0]['label']
    assert output[1]['steps'] == []
