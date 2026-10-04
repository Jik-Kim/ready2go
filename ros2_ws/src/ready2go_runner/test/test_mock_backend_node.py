"""#10-3 mock 백엔드 노드 + Runner + ROS 클라이언트를 실제 ROS 로 연결해 예시 태스크 실행.
rclpy·ready2go_interfaces 필요 → 호스트 pytest 는 건너뛰고 ros2-core 컨테이너·colcon test 에서 실행.
ICD 의 고정 이름(/skills/* 등)을 쓰므로 다른 시험·컨테이너와 섞이지 않게 별도 Domain ID 에서 돌린다."""
import json
import random
import threading
from pathlib import Path

import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("ready2go_interfaces")

from rclpy.executors import MultiThreadedExecutor  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402

from ready2go_knowledge.core import ontology  # noqa: E402
from ready2go_runner.adapters.ros_clients import RosClients  # noqa: E402
from ready2go_runner.core.backend import RosBackend  # noqa: E402
from ready2go_runner.core.interpreter import Runner  # noqa: E402
from ready2go_runner.nodes.mock_backend import MockBackendNode  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
ONTOLOGY = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))
TASK = json.loads((ROOT / "contracts/examples/task_skill_steps.json").read_text(encoding="utf-8"))


def run_with_mock(fail="", not_visible=""):
    context = rclpy.Context()
    rclpy.init(context=context, domain_id=random.randint(150, 230))
    mock = MockBackendNode(context=context, parameter_overrides=[
        Parameter("duration_sec", value=0.05), Parameter("fail", value=fail),
        Parameter("not_visible", value=not_visible)])
    client = rclpy.create_node("runner_test", context=context)
    executor = MultiThreadedExecutor(context=context)
    executor.add_node(mock)
    executor.add_node(client)
    threading.Thread(target=executor.spin, daemon=True).start()
    try:
        clients = RosClients(client, server_wait_sec=3.0)
        runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
        runner.execute = RosBackend(clients.call_action, clients.call_service, lambda: runner.state,
                                    ONTOLOGY["world"])
        return runner, runner.run(TASK)
    finally:
        executor.shutdown()
        rclpy.shutdown(context=context)


def test_example_task_completes_on_mock():
    runner, result = run_with_mock()
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    assert runner.state["located_in"]["car_key"] == "handover_zone"
    assert runner.state["open"][result.steps[0]["output"]["drawer_id"]] is False      # finally 로 닫힘
    assert next(s for s in result.steps if s["id"] == "s4.e2")["output"]["object_id"] == "car_key#1"


def test_grasp_failure_runs_finally_on_mock():
    runner, result = run_with_mock(fail="pick_object=GRASP_FAILED")
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "GRASP_FAILED", "s4.e2")
    assert [s["status"] for s in result.steps if s["id"] in ("f1", "f2")] == ["SUCCESS", "SUCCESS"]
    assert runner.state["located_in"]["car_key"] != "gripper"                      # 집기 실패 → effect 없음
