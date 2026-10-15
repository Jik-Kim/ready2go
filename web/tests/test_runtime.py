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
from sensor_msgs.msg import CameraInfo, CompressedImage, JointState
from std_msgs.msg import String

from ready2go_web.nodes.dashboard_bridge import BridgeTopics
from ready2go_web.runtime import RosBridgeRuntime, settings_from_env


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


def test_runtime_receives_all_enabled_sources_on_its_own_executor_thread() -> None:
    """활성화한 다섯 source가 전용 executor를 거쳐 공유 캐시에 도착한다."""
    prefix = f"/test_ready2go_runtime_{uuid.uuid4().hex}"
    topics = BridgeTopics(
        runner_status=f"{prefix}/runner/status",
        robot_state=f"{prefix}/robot_state",
        camera_info=f"{prefix}/camera_info",
        inspect_overlay=f"{prefix}/vision/inspect_overlay",
        voice_intent=f"{prefix}/voice/intent",
        robot_connection=f"{prefix}/joint_states",
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
    runner_publisher = publisher_node.create_publisher(
        String,
        topics.runner_status,
        RUNNER_PUBLISHER_QOS,
    )
    robot_state_publisher = publisher_node.create_publisher(
        String,
        topics.robot_state,
        RUNNER_PUBLISHER_QOS,
    )
    # 시험용 RELIABLE/VOLATILE/depth10 발행자로 sensor-data 구독의 호환성을 확인한다.
    # PC2의 실제 publisher QoS는 담당 실측 회신 전이므로 이 시험값과 구분한다.
    robot_publisher_qos = QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=10,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
    )
    robot_publisher = publisher_node.create_publisher(
        JointState,
        topics.robot_connection,
        robot_publisher_qos,
    )
    # 카메라도 sensor-data subscriber와 호환되는 VOLATILE 시험 publisher를 사용한다.
    camera_publisher = publisher_node.create_publisher(
        CameraInfo,
        topics.camera_info,
        robot_publisher_qos,
    )
    overlay_publisher = publisher_node.create_publisher(
        CompressedImage,
        topics.inspect_overlay,
        RUNNER_PUBLISHER_QOS,
    )
    # Voice는 intent 내용을 보내지 않고 publisher endpoint 존재만 제공한다.
    voice_publisher = publisher_node.create_publisher(String, topics.voice_intent, 10)

    try:
        runtime.start()
        assert runtime.is_running is True

        # runtime은 다섯 상태 source를 한 노드와 캐시에서 함께 관리한다.
        assert set(runtime.cache.snapshot()) == {
            "runner",
            "robot_state",
            "robot",
            "camera",
            "voice",
        }

        # DDS discovery 뒤 두 String 상태와 두 주기 센서 수신 경로를 확인한다.
        assert _wait_until(lambda: publisher_node.count_subscribers(topics.runner_status) == 1)
        assert _wait_until(lambda: publisher_node.count_subscribers(topics.robot_state) == 1)
        assert _wait_until(lambda: publisher_node.count_subscribers(topics.robot_connection) == 1)
        assert _wait_until(lambda: publisher_node.count_subscribers(topics.camera_info) == 1)
        assert _wait_until(lambda: publisher_node.count_subscribers(topics.inspect_overlay) == 1)
        runner_payload = {"phase": "running", "task_id": "demo_task", "current_step": "open"}
        robot_state_payload = {
            "robot_pose": {"robot": "home"},
            "gripper": {"robot": "empty"},
            "open": {"drawer_top": True},
            "located_in": {"car_key": "drawer_top"},
        }
        runner_publisher.publish(String(data=json.dumps(runner_payload)))
        robot_state_publisher.publish(String(data=json.dumps(robot_state_payload)))
        robot_message = JointState()
        robot_message.name = [f"joint_{index}" for index in range(1, 7)]
        camera_message = CameraInfo()
        camera_message.header.frame_id = "wrist_cam"
        camera_message.width = 1280
        camera_message.height = 720
        overlay_message = CompressedImage()
        overlay_message.header.frame_id = "wrist_cam_color_optical_frame"
        overlay_message.header.stamp.sec = 100
        overlay_message.format = "jpeg"
        overlay_message.data = b"runtime-overlay-jpeg"
        overlay_publisher.publish(overlay_message)

        def publish_periodic_sources_until_received() -> bool:
            """VOLATILE JointState·CameraInfo를 실제 주기 발행처럼 반복한다."""
            # subscriber 수가 보여도 DDS 데이터 경로 매칭이 끝나기 전일 수 있으므로,
            # 한 번만 발행해 생기는 경합 대신 제한 시간 동안 20ms 간격으로 재발행한다.
            snapshot = runtime.cache.snapshot()
            if snapshot["robot"]["message_valid"] and snapshot["camera"]["message_valid"]:
                return True
            robot_publisher.publish(robot_message)
            camera_publisher.publish(camera_message)
            return False

        # 주기 source의 지속 발행 조건에서 두 VOLATILE 메시지 전달을 확인한다.
        assert _wait_until(publish_periodic_sources_until_received)
        assert _wait_until(
            lambda: runtime.cache.snapshot()["runner"]["message_valid"]
            and runtime.cache.snapshot()["robot_state"]["message_valid"]
            and runtime.cache.snapshot()["voice"]["publisher_present"] is True
        )
        assert _wait_until(lambda: runtime.overlay_cache.get_latest() is not None)

        runner = runtime.cache.snapshot()["runner"]
        assert runner["publisher_present"] is True
        assert runner["data"] == runner_payload
        robot_state = runtime.cache.snapshot()["robot_state"]
        assert robot_state["publisher_present"] is True
        assert robot_state["data"] == robot_state_payload
        robot = runtime.cache.snapshot()["robot"]
        assert robot["publisher_present"] is True
        assert robot["connection_state"] == "receiving"
        assert robot["data"]["joint_count"] == 6
        camera = runtime.cache.snapshot()["camera"]
        assert camera["publisher_present"] is True
        assert camera["connection_state"] == "receiving"
        assert camera["freshness_timeout_sec"] == 2.0
        assert camera["data"]["frame_id"] == "wrist_cam"
        voice = runtime.cache.snapshot()["voice"]
        assert voice["publisher_present"] is True
        assert voice["message_received"] is False
        assert voice["connection_state"] == "waiting"
        assert voice_publisher is not None
        assert runtime.overlay_cache.get_latest().jpeg == b"runtime-overlay-jpeg"

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


def test_runtime_settings_use_b_defaults_and_accept_profile_overrides() -> None:
    """B 기본 토픽·timeout과 sim/dev 실행 프로필을 환경 설정으로 변경할 수 있다."""
    defaults = settings_from_env({})
    assert defaults.robot_topic == "/dsr01/joint_states"
    assert defaults.robot_timeout_sec == 2.0
    assert defaults.profile == "real"

    configured = settings_from_env(
        {
            "WEB_ROBOT_TOPIC": "/test/joint_states",
            "WEB_ROBOT_TIMEOUT_SEC": "3.5",
            "WEB_RUNTIME_PROFILE": "SIM",
        }
    )
    assert configured.robot_topic == "/test/joint_states"
    assert configured.robot_timeout_sec == 3.5
    assert configured.profile == "sim"


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"WEB_ROBOT_TOPIC": "relative"}, "WEB_ROBOT_TOPIC"),
        ({"WEB_ROBOT_TOPIC": "/"}, "WEB_ROBOT_TOPIC"),
        ({"WEB_ROBOT_TIMEOUT_SEC": "none"}, "숫자"),
        ({"WEB_ROBOT_TIMEOUT_SEC": "0"}, "0보다"),
        ({"WEB_ROBOT_TIMEOUT_SEC": "nan"}, "0보다"),
        ({"WEB_RUNTIME_PROFILE": "stage"}, "real, sim, dev"),
    ],
)
def test_invalid_runtime_settings_are_rejected(environ: dict[str, str], message: str) -> None:
    """잘못된 로봇 토픽·timeout·프로필을 ROS 노드 생성 전에 거절한다."""
    with pytest.raises(ValueError, match=message):
        settings_from_env(environ)
