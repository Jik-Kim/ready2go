"""Flask와 분리된 ROS executor 수명주기와 Runner 실제 수신 경로를 검증한다."""

from __future__ import annotations

import json
import time
import uuid

import pytest
import rclpy
from rclpy.context import Context
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from ready2go_web.nodes.dashboard_bridge import BridgeTopics
from ready2go_web.runtime import RosBridgeRuntime


# 실제 Runner와 동일한 late-joiner용 상태 발행 QoS를 시험 publisher에도 적용한다.
RUNNER_PUBLISHER_QOS = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)


def _wait_until(predicate, timeout_sec: float = 3.0) -> bool:
    """별도 executor 스레드의 비동기 결과를 짧게 확인하며 제한 시간까지 기다린다."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if predicate():
            return True
        # 긴 sleep 한 번보다 짧은 간격으로 확인해 성공한 시험을 불필요하게 지연하지 않는다.
        time.sleep(0.02)
    return False


def test_runtime_receives_runner_status_on_its_own_executor_thread() -> None:
    """실제 DDS 메시지가 runtime 전용 executor를 거쳐 공유 캐시에 도착한다."""
    prefix = f"/test_ready2go_runtime_{uuid.uuid4().hex}"
    topics = BridgeTopics(
        runner_status=f"{prefix}/runner/status",
        robot_state=f"{prefix}/robot_state",
        camera_info=f"{prefix}/camera_info",
        voice_intent=f"{prefix}/voice/intent",
    )
    runtime = RosBridgeRuntime(
        topics=topics,
        node_name=f"runtime_bridge_{uuid.uuid4().hex}",
    )

    # 발행자는 runtime의 전용 context와 다른 context를 써 실제 프로세스 간 경계처럼 검증한다.
    publisher_context = Context()
    rclpy.init(args=None, context=publisher_context)
    publisher_node = Node(
        f"runtime_publisher_{uuid.uuid4().hex}",
        context=publisher_context,
    )
    publisher = publisher_node.create_publisher(
        String,
        topics.runner_status,
        RUNNER_PUBLISHER_QOS,
    )

    try:
        runtime.start()
        assert runtime.is_running is True

        # 2단계 runtime은 후속 source 없이 runner 캐시 하나만 만든다.
        assert set(runtime.cache.snapshot()) == {"runner"}

        # DDS discovery 뒤 실제 String JSON을 발행해 executor 콜백 수신을 확인한다.
        assert _wait_until(lambda: publisher_node.count_subscribers(topics.runner_status) == 1)
        payload = {"phase": "running", "task_id": "demo_task", "current_step": "open"}
        publisher.publish(String(data=json.dumps(payload)))
        assert _wait_until(lambda: runtime.cache.snapshot()["runner"]["message_valid"])

        runner = runtime.cache.snapshot()["runner"]
        assert runner["publisher_present"] is True
        assert runner["data"] == payload

        # 동일 객체의 이중 시작은 구독 노드를 중복 생성하지 않고 명시적으로 실패한다.
        with pytest.raises(RuntimeError, match="이미 시작"):
            runtime.start()
    finally:
        # runtime을 먼저 멈춰 subscriber를 제거한 뒤 시험 publisher context를 정리한다.
        runtime.stop()
        publisher_node.destroy_node()
        if publisher_context.ok():
            publisher_context.shutdown()

    # 정상 종료 후 executor 스레드가 남지 않고 stop 반복 호출도 안전해야 한다.
    assert runtime.is_running is False
    runtime.stop()
    with pytest.raises(RuntimeError, match="시작되지"):
        _ = runtime.cache
