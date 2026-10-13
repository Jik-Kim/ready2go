"""#10-4 Runner 노드: mock 백엔드와 함께 띄워 태스크 실행·/runner/status·/robot_state·/runner/estop 을 ROS 로 확인.
rclpy·ready2go_interfaces 필요 → 호스트 pytest 는 건너뛰고 ros2-core 컨테이너·colcon test 에서 실행.
MongoDB 가 없으면 FallbackLogStore 가 JSONL(tmp_path)로 기록하는 것도 함께 확인된다."""
import json
import itertools
import threading
import time
from pathlib import Path

import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("ready2go_interfaces")

from rclpy.executors import MultiThreadedExecutor  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from std_msgs.msg import String  # noqa: E402
from std_srvs.srv import Trigger  # noqa: E402

from ready2go_runner.nodes.mock_backend import MockBackendNode  # noqa: E402
from ready2go_runner.nodes.runner_node import LATCHED, RunnerNode  # noqa: E402

# 시험마다 다른 Domain ID (파일마다 범위를 나눠, 앞 시험의 남은 서버와 섞이지 않게)
DOMAIN_IDS = itertools.count(200)
ROOT = Path(__file__).resolve().parents[4]
TASK_FILE = ROOT / "contracts/examples/task_skill_steps.json"


class Watcher:
    """다른 노드처럼 /runner/status·/robot_state 를 구독."""

    def __init__(self, node):
        self.status, self.state = None, None
        node.create_subscription(String, "/runner/status", lambda m: setattr(self, "status", json.loads(m.data)), LATCHED)
        node.create_subscription(String, "/robot_state", lambda m: setattr(self, "state", json.loads(m.data)), LATCHED)
        self.estop = node.create_client(Trigger, "/runner/estop")
        self.reset = node.create_client(Trigger, "/runner/reset_state")

    def call(self, client, timeout=5.0):
        assert client.wait_for_service(timeout_sec=timeout)
        done = threading.Event()
        future = client.call_async(Trigger.Request())
        future.add_done_callback(lambda _: done.set())
        assert done.wait(timeout)
        return future.result()

    def wait(self, check, timeout=20.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.status is not None and check(self):
                return True
            time.sleep(0.05)
        return False


@pytest.fixture
def thread_errors(monkeypatch):
    """작업 스레드 예외를 모은다 (PR #74 리뷰: 로그 등급 ValueError 가 스레드 안에서 나던 문제)."""
    errors = []
    monkeypatch.setattr(threading, "excepthook", lambda args: errors.append(args.exc_value))
    return errors


@pytest.fixture
def system(tmp_path, thread_errors):
    context = rclpy.Context()
    rclpy.init(context=context, domain_id=next(DOMAIN_IDS))
    mock = MockBackendNode(context=context, parameter_overrides=[Parameter("duration_sec", value=0.05)])
    runner = RunnerNode(context=context, parameter_overrides=[
        Parameter("schema_file", value=str(ROOT / "contracts/task.schema.json")),
        Parameter("intent_schema_file", value=str(ROOT / "contracts/intent.schema.json")),   # /contracts 마운트 없는 PC (#198 E 보고)
        Parameter("tasks_dir", value=str(ROOT / "tasks")),
        Parameter("ontology_file", value=str(ROOT / "knowledge/robot_ontology.jsonld")),
        Parameter("log_dir", value=str(tmp_path)),
        Parameter("task_file", value=str(TASK_FILE))])
    watcher_node = rclpy.create_node("watcher", context=context)
    watcher = Watcher(watcher_node)
    executor = MultiThreadedExecutor(context=context)
    for node in (mock, runner, watcher_node):
        executor.add_node(node)
    threading.Thread(target=executor.spin, daemon=True).start()
    yield runner, watcher, tmp_path
    executor.shutdown()
    rclpy.shutdown(context=context)


def test_task_file_runs_and_status_is_published(system):
    runner, watcher, log_dir = system
    assert watcher.wait(lambda w: (w.status.get("last") or {}).get("overall_status") is not None), watcher.status
    last = watcher.status["last"]
    assert last["overall_status"] == "COMPLETED", last
    assert watcher.status["phase"] == "idle" and watcher.status["log_store"] in ("mongo", "jsonl")
    assert watcher.wait(lambda w: w.state and w.state["located_in"]["car_key"] == "handover_zone")
    if watcher.status["log_store"] == "jsonl":                  # 이 시험 환경엔 보통 MongoDB 가 없음
        assert (log_dir / (last["run_id"].replace(":", "-") + ".jsonl")).exists()


def test_estop_halts_and_refuses_next_task(system):
    runner, watcher, _ = system
    assert watcher.wait(lambda w: (w.status.get("last") or {}).get("overall_status") == "COMPLETED")
    assert watcher.estop.wait_for_service(timeout_sec=5)
    done = threading.Event()
    future = watcher.estop.call_async(Trigger.Request())
    future.add_done_callback(lambda _: done.set())
    assert done.wait(5) and future.result().success
    assert watcher.wait(lambda w: w.status["phase"] == "halted" and w.status["halt_code"] == "HALTED")
    halt = watcher.status["halt"]               # 실행이 끝난 뒤 정지 요청 → 취소할 동작 없음 (계약안 halt.stop)
    assert (halt["source"], halt["canceled_goals"], halt["stop"], halt["locked"]) == ("service", 0, "none", True)

    task = json.loads(TASK_FILE.read_text(encoding="utf-8"))
    assert runner.start_task(task)
    assert watcher.wait(lambda w: w.status["last"]["overall_status"] == "ABORTED")   # 잠김: 로봇 동작 없이 거절
    assert watcher.status["last"]["problems"]


def test_success_then_aborted_run_has_no_thread_error(system, thread_errors):
    # 같은 노드에서 성공(info) 뒤 중단(warning) 로그 → 이전에는 rclpy ValueError 가 작업 스레드에서 남
    runner, watcher, _ = system
    assert watcher.wait(lambda w: (w.status.get("last") or {}).get("overall_status") == "COMPLETED")
    runner.runner.halt()
    assert runner.start_task(json.loads(TASK_FILE.read_text(encoding="utf-8")))
    assert watcher.wait(lambda w: w.status["last"]["overall_status"] == "ABORTED")
    time.sleep(0.3)
    assert thread_errors == []


def test_reset_state_service_restores_start_state_when_idle(system):
    """#23·#107: 사람이 원위치 확인 → /runner/reset_state → /robot_state 가 시작 상태로, status 에 시각."""
    runner, watcher, _ = system
    start = runner.runner._initial_state["located_in"]["car_key"]
    assert watcher.wait(lambda w: (w.status.get("last") or {}).get("overall_status") == "COMPLETED"
                        and w.status["phase"] == "idle")          # 끝난 뒤에만 (실행 중이면 거절)
    assert watcher.state["located_in"]["car_key"] == "handover_zone"
    assert watcher.status["state_reset_at"] is None
    reply = watcher.call(watcher.reset)
    assert reply.success, reply.message
    assert watcher.wait(lambda w: w.state["located_in"]["car_key"] == start and w.status["state_reset_at"])


def test_reset_state_is_refused_while_running(system):
    runner, watcher, _ = system
    assert watcher.wait(lambda w: (w.status.get("last") or {}).get("overall_status") == "COMPLETED")
    before = runner.runner.state
    assert runner.gate.try_start() == "started"   # 실행 중으로 고정 (짧은 mock 태스크와 경합하지 않게, #187 StartGate)
    try:
        reply = watcher.call(watcher.reset)
    finally:
        runner.gate.finish()
    assert not reply.success and "실행 중" in reply.message
    assert runner.runner.state == before



def _publish_intent(runner, payload, times=3):
    pub = runner.create_publisher(String, "/voice/intent", 10)
    for _ in range(times):                     # 첫 발행이 구독 연결 전에 사라지지 않게 몇 번 (같은 ID 라 한 번만 실행돼야 함)
        pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))
        time.sleep(0.2)


def test_request_id_run_id_resend_and_conflict(system):
    """계약07: 수락한 run_id 가 last_intent 와 최종 last 에 같게, 같은 ID 재전송은 재실행 없음, 같은 ID + 다른 내용도 실행 안 함."""
    runner, watcher, _ = system
    assert watcher.wait(lambda w: (w.status.get("last") or {}).get("overall_status") == "COMPLETED"
                        and w.status["phase"] == "idle")
    first_run = watcher.status["last"]["run_id"]
    request = {"intent": "find_item", "targets": ["eraser"], "confidence": 0.93, "request_id": "req-0007",
               "accept_text": "지우개를 찾아올게요.", "source": {"stt_text": "지우개 찾아줘"}}
    _publish_intent(runner, request)                                     # 3번 보냄 = 재전송 2번
    assert watcher.wait(lambda w: (w.status.get("last") or {}).get("run_id") not in (None, first_run)
                        and w.status["phase"] == "idle"), watcher.status
    accepted = watcher.status["last_intent"]
    assert (accepted["request_id"], accepted["decision"]) == ("req-0007", "run")
    assert accepted["run_id"] == watcher.status["last"]["run_id"]          # 수락 run = 최종 결과 run
    run_id = accepted["run_id"]
    _publish_intent(runner, {**request, "source": {"stt_text": "다른 내용"}})   # 충돌: 같은 ID, 다른 내용
    time.sleep(1.0)
    assert watcher.status["last"]["run_id"] == run_id and watcher.status["phase"] == "idle"
    assert watcher.status["last_intent"]["run_id"] == run_id               # 첫 결정 그대로
    _publish_intent(runner, {**request, "request_id": "req-0008"}, times=1)    # 새 ID 는 새 실행
    assert watcher.wait(lambda w: (w.status.get("last_intent") or {}).get("request_id") == "req-0008"
                        and w.status["last"]["run_id"] == w.status["last_intent"]["run_id"] != run_id), watcher.status


def _record_status(runner, monkeypatch):
    """실제로 발행된 /runner/status 의 last_intent 를 차례로 모은다."""
    sent, real = [], runner.status_pub.publish

    def publish(msg):
        sent.append(json.loads(msg.data)["last_intent"])
        real(msg)
    monkeypatch.setattr(runner.status_pub, "publish", publish)
    return sent


def _inject_once(runner, monkeypatch, payload, payload_for):
    """요청의 결정을 발행하려고 상태를 만드는 순간, 다른 스레드(다른 콜백)가 payload 인텐트를 보낸다.
    잠금이 없으면 그 콜백이 last_intent 를 먼저 바꿔 이 요청의 결정이 발행되지 않는다(#249 E 재현)."""
    real_status, threads = runner.status, []

    def status():                               # 이 요청의 결정을 발행하려는 순간에만 (주기 발행 등은 그냥 통과)
        if not threads and (runner._last_intent or {}).get("request_id") == payload_for:
            t = threading.Thread(target=runner._on_intent, args=(String(data=json.dumps(payload)),))
            threads.append(t)
            t.start()
            t.join(0.3)                         # 잠금이 없으면 이 사이에 끼어든 콜백이 끝남
        return real_status()
    monkeypatch.setattr(runner, "status", status)
    return threads


def test_each_request_decision_is_published_despite_concurrent_status_and_cancel(system, monkeypatch):
    """#249 E 리뷰: 첫 요청·같은 ID 재전송의 결정 발행 사이에 status·cancel 이 와도, 그 요청 자신의 결정
    (request_id·decision·run_id)이 실제 발행 메시지로 적어도 한 번 나가고, 재전송은 다시 실행하지 않는다."""
    runner, watcher, _ = system
    assert watcher.wait(lambda w: (w.status.get("last") or {}).get("overall_status") == "COMPLETED"
                        and w.status["phase"] == "idle")
    sent = _record_status(runner, monkeypatch)
    starts = []
    real_start = runner.start_task
    monkeypatch.setattr(runner, "start_task", lambda *a, **k: starts.append(a) or real_start(*a, **k))
    request = {"intent": "find_item", "targets": ["eraser"], "confidence": 0.93, "request_id": "req-race",
               "source": {"stt_text": "지우개 찾아줘"}}
    for injected in ({"intent": "status", "targets": [], "confidence": 0.9},     # 첫 요청 + status
                     {"intent": "cancel", "targets": [], "confidence": 0.9}):    # 같은 ID 재전송 + cancel
        sent.clear()
        threads = _inject_once(runner, monkeypatch, injected, "req-race")
        runner._on_intent(String(data=json.dumps(request, ensure_ascii=False)))
        threads[0].join(5)
        mine = [m for m in sent if m and m.get("request_id") == "req-race"]
        assert mine and (mine[0]["decision"], mine[0]["run_id"]) == ("run", runner.requests.lookup("req-race").summary["run_id"]), sent
        assert mine[0]["run_id"] is not None
        assert any(m and m["intent"] == injected["intent"] for m in sent), sent   # 끼어든 콜백도 자기 결정을 발행
    assert len(starts) == 1                     # 재전송은 재실행 없음


def test_cancel_does_not_wait_behind_request_lock(system):
    """정지 경로 보존: 요청 기억 잠금(긴 판단·계획 중)을 누가 잡고 있어도 cancel 은 바로 처리된다."""
    runner, watcher, _ = system
    assert watcher.wait(lambda w: (w.status.get("last") or {}).get("overall_status") == "COMPLETED")
    with runner.requests.lock:
        t = threading.Thread(target=runner._on_intent,
                             args=(String(data=json.dumps({"intent": "cancel", "targets": [], "confidence": 0.9})),))
        t.start()
        t.join(2)
        assert not t.is_alive()
    assert runner._last_intent["intent"] == "cancel"


def test_status_has_boot_id_and_seq_grows_only_on_change(system):
    """계약 W4 (#271): boot_id 는 이 Runner 기동 값, seq 는 바뀐 상태를 보낼 때만 +1 (0.5 s 주기 발행이 매번 늘리지 않음)."""
    runner, watcher, _ = system
    assert watcher.wait(lambda w: (w.status.get("last") or {}).get("overall_status") == "COMPLETED"
                        and w.status["phase"] == "idle")
    assert watcher.status["boot_id"] == runner.runner.boot_id and watcher.status["stamp"].endswith("Z")
    seq = watcher.status["seq"]
    time.sleep(1.5)                                  # 주기 발행 3번 — 내용이 같으면 보내지 않음
    assert watcher.status["seq"] == seq
    watcher.call(watcher.reset)                      # 상태가 바뀜 (state_reset_at) → seq +1 이상
    assert watcher.wait(lambda w: w.status["seq"] > seq and w.status["state_reset_at"])
