"""#10-3 mock 백엔드 노드 + Runner + ROS 클라이언트를 실제 ROS 로 연결해 예시 태스크 실행.
rclpy·ready2go_interfaces 필요 → 호스트 pytest 는 건너뛰고 ros2-core 컨테이너·colcon test 에서 실행.
ICD 의 고정 이름(/skills/* 등)을 쓰므로 다른 시험·컨테이너와 섞이지 않게 별도 Domain ID 에서 돌린다."""
import json
import itertools
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

# 시험마다 다른 Domain ID (파일마다 범위를 나눠, 앞 시험의 남은 서버와 섞이지 않게)
DOMAIN_IDS = itertools.count(180)
ROOT = Path(__file__).resolve().parents[4]
ONTOLOGY = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))
TASK = json.loads((ROOT / "contracts/examples/task_skill_steps.json").read_text(encoding="utf-8"))
P1_TASK = json.loads((ROOT / "tasks/find_item.json").read_text(encoding="utf-8"))   # #17


def run_with_mock(fail="", not_visible="", task=TASK, onto=ONTOLOGY):
    context = rclpy.Context()
    rclpy.init(context=context, domain_id=next(DOMAIN_IDS))
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
        runner = Runner(None, schema=SCHEMA, ontology=onto)
        runner.execute = RosBackend(clients.call_action, clients.call_service, lambda: runner.state,
                                    onto["world"])
        return runner, runner.run(task)
    finally:
        executor.shutdown()
        rclpy.shutdown(context=context)


def test_example_task_completes_on_mock():
    runner, result = run_with_mock()
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    assert runner.state["located_in"]["car_key"] == "handover_zone"
    assert runner.state["open"][result.steps[0]["output"]["drawer_id"]] is False      # finally 로 닫힘
    assert next(s for s in result.steps if s["id"] == "s4.e6")["output"]["object_id"] == "car_key#1"   # E #122 pick 6번째 = 집기


def test_grasp_failure_runs_finally_on_mock():
    runner, result = run_with_mock(fail="pick_object=GRASP_FAILED")
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "GRASP_FAILED", "s4.e6")
    assert [s["status"] for s in result.steps if s["id"] in ("f1", "f2")] == ["SUCCESS", "SUCCESS"]
    assert runner.state["located_in"]["car_key"] != "gripper"                      # 집기 실패 → effect 없음


# ---- #17 P1 태스크 (tasks/find_item.json): mock 에서 성공·파지 실패·미발견 모두 finally 까지 ----

def test_p1_task_completes_on_mock():
    runner, result = run_with_mock(task=P1_TASK)
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    assert runner.state["located_in"]["eraser"] == "handover_zone"
    assert runner.state["open"]["drawer_top"] is False


def test_p1_task_grasp_failure_runs_finally_on_mock():
    runner, result = run_with_mock(fail="pick_object=GRASP_FAILED", task=P1_TASK)
    assert (result.overall_status, result.error_code) == ("FAILED", "GRASP_FAILED")
    assert [s["status"] for s in result.steps if s["id"] in ("f2", "f3.1")] == ["SUCCESS", "SUCCESS"]
    assert runner.state["open"]["drawer_top"] is False


def test_p1_task_not_visible_on_mock():
    runner, result = run_with_mock(not_visible="eraser", task=P1_TASK)
    assert result.overall_status == "COMPLETED"
    assert any(s["id"] == "s5.4" and s["status"] == "SUCCESS" for s in result.steps)     # "찾지 못했어요"
    assert runner.state["located_in"]["eraser"] == "drawer_top"


# ---- P1 지우개 tasks/p1_demo_eraser.json (speak 없음, 공통 pick: 끌기 뒤 다시 촬영한 좌표로 집기, E #122) ----

CHECK_TASK = json.loads((ROOT / "tasks/p1_demo_eraser.json").read_text(encoding="utf-8"))


def test_check_task_completes_on_mock():
    runner, result = run_with_mock(task=CHECK_TASK)
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    assert runner.state["located_in"]["eraser"] == "handover_zone" and runner.state["open"]["drawer_top"] is False
    picked = next(s for s in result.steps if s["id"] == "s3.e6")["params"]["target"]
    reobserved = next(s for s in result.steps if s["id"] == "s3.e5")["output"]["target"]
    assert picked == reobserved                                         # 끌기 뒤 다시 촬영한 결과로 집기


def test_check_task_nudge_failure_does_not_pick_on_mock():
    runner, result = run_with_mock(fail="nudge_object=NO_PUSH_ACCESS", task=CHECK_TASK)
    assert (result.overall_status, result.error_code) == ("FAILED", "NO_PUSH_ACCESS")
    assert not any(s["id"] == "s3.e6" for s in result.steps)         # pick_object 안 보냄
    assert runner.state["located_in"]["eraser"] == "drawer_top"


def test_check_task_grasp_failure_runs_finally_on_mock():
    runner, result = run_with_mock(fail="pick_object=GRASP_FAILED", task=CHECK_TASK)
    assert (result.overall_status, result.error_code) == ("FAILED", "GRASP_FAILED")
    assert [s["status"] for s in result.steps if s["id"] in ("f2", "f3.1")] == ["SUCCESS", "SUCCESS"]
