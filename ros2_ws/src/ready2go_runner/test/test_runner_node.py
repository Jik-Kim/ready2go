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

