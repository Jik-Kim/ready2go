"""#10-2 ROS 클라이언트: 같은 프로세스에 가짜 Skill 액션·InspectRegion 서버를 띄워 실제 ROS 메시지로 시험.
rclpy·ready2go_interfaces 가 필요 → 호스트 pytest 에서는 건너뛰고 ros2-core 컨테이너·colcon test 에서 실행."""
import json
import threading
import time
import uuid

import pytest

rclpy = pytest.importorskip("rclpy")
pytest.importorskip("ready2go_interfaces")

from rclpy.action import ActionServer, CancelResponse  # noqa: E402
from rclpy.callback_groups import ReentrantCallbackGroup  # noqa: E402
from rclpy.executors import MultiThreadedExecutor  # noqa: E402

from ready2go_interfaces.action import Skill  # noqa: E402
from ready2go_interfaces.srv import InspectRegion  # noqa: E402
from ready2go_runner.adapters.ros_clients import RosClients  # noqa: E402

PREFIX = f"/test_{uuid.uuid4().hex[:6]}"         # 다른 시험·컨테이너의 서버와 이름이 겹치지 않게


class FakeServers:
    def __init__(self, node):
        group = ReentrantCallbackGroup()
        self.cancel_requested = threading.Event()
        self.received = []
        ActionServer(node, Skill, f"{PREFIX}/skills/ok", self._ok, callback_group=group)
        ActionServer(node, Skill, f"{PREFIX}/skills/fail", self._fail, callback_group=group)
        ActionServer(node, Skill, f"{PREFIX}/skills/slow", self._slow, callback_group=group,
                     cancel_callback=self._cancel)
        node.create_service(InspectRegion, f"{PREFIX}/vision/inspect_region", self._inspect, callback_group=group)

    def _ok(self, goal):
        self.received.append(json.loads(goal.request.params_json))
        goal.succeed()
        return Skill.Result(success=True, output_json=json.dumps({"slot": "handover_zone"}))

    def _fail(self, goal):
        goal.abort()
        return Skill.Result(success=False, error_code="DRAWER_STUCK")

    def _cancel(self, goal):
        self.cancel_requested.set()
        return CancelResponse.ACCEPT

    def _slow(self, goal):
        for _ in range(50):                             # 최대 5초
            if goal.is_cancel_requested:
                goal.canceled()
                return Skill.Result(success=False, error_code="CANCELED")
            time.sleep(0.1)
        goal.succeed()
        return Skill.Result(success=True)

    def _inspect(self, request, response):
        response.success = True
        response.result_json = json.dumps({"target_found": True, "region": request.region,
                                           "target": {"id": f"{request.search_target}#1"}})
        return response


@pytest.fixture(scope="module")
def ros():
    rclpy.init()
    server_node, client_node = rclpy.create_node("fake_servers"), rclpy.create_node("runner_clients_test")
    servers = FakeServers(server_node)
    executor = MultiThreadedExecutor()
    executor.add_node(server_node)
    executor.add_node(client_node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()
    yield RosClients(client_node, server_wait_sec=1.0), servers
    executor.shutdown()
    rclpy.shutdown()


def test_action_success_sends_params_and_returns_output(ros):
    clients, servers = ros
    reply = clients.call_action(f"{PREFIX}/skills/ok", '{"location": "handover_zone"}', 5)
    assert (reply.success, json.loads(reply.payload_json)) == (True, {"slot": "handover_zone"})
    assert servers.received[-1] == {"location": "handover_zone"}


def test_action_failure_code_passes_through(ros):
    clients, _ = ros
    reply = clients.call_action(f"{PREFIX}/skills/fail", "{}", 5)
    assert (reply.success, reply.error_code) == (False, "DRAWER_STUCK")


def test_action_timeout_requests_cancel(ros):
    clients, servers = ros
    started = time.monotonic()
    reply = clients.call_action(f"{PREFIX}/skills/slow", "{}", 0.5)
    assert (reply.success, reply.error_code) == (False, "TIMEOUT")
    assert time.monotonic() - started < 2.0                     # 5초짜리 동작을 끝까지 기다리지 않음
    assert servers.cancel_requested.wait(2.0)                   # 서버가 취소 요청을 받음


def test_missing_action_server_is_backend_error(ros):
    clients, _ = ros
    started = time.monotonic()
    reply = clients.call_action(f"{PREFIX}/skills/none", "{}", 5)
    assert (reply.success, reply.error_code) == (False, "BACKEND_ERROR")
    assert time.monotonic() - started < 3.0                     # 서버 찾기 제한(1초) 안에 포기


def test_inspect_region_service(ros):
    clients, _ = ros
    reply = clients.call_service(f"{PREFIX}/vision/inspect_region", "drawer_top", "car_key", 5)
    assert reply.success
    assert json.loads(reply.payload_json)["target"]["id"] == "car_key#1"


def test_missing_service_is_backend_error(ros):
    clients, _ = ros
    reply = clients.call_service(f"{PREFIX}/vision/none", "drawer_top", "", 5)
    assert (reply.success, reply.error_code) == (False, "BACKEND_ERROR")
