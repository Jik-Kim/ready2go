"""DashboardBridge의 JSON 처리, QoS, 그래프 관찰과 실제 ROS 수신을 검증한다."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
import uuid

import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo
from std_msgs.msg import String

from ready2go_web.nodes.dashboard_bridge import (
    BridgeTopics,
    DashboardBridge,
    RUNNER_SOURCE,
)


# 시험 publisher가 Runner와 같은 latched 상태 QoS로 메시지를 보낼 때 사용한다.
PUBLISHER_STATUS_QOS = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)


@pytest.fixture
def ros_context():
    """각 시험에서 rclpy를 시작하고 노드를 모두 제거한 뒤 확실히 종료한다."""
    # 전역 기본 context를 사용하되 이미 다른 시험이 시작한 경우 중복 init하지 않는다.
    if not rclpy.ok():
        rclpy.init()
    try:
        yield
    finally:
        # 이 파일의 시험 뒤 다음 실행에 context가 남지 않도록 종료한다.
        if rclpy.ok():
            rclpy.shutdown()


def unique_topics() -> BridgeTopics:
    """실행 중인 실제 ready2go 토픽과 충돌하지 않는 시험 전용 이름을 만든다."""
    # 한 pytest 프로세스 안의 시험끼리도 DDS endpoint가 겹치지 않게 UUID를 붙인다.
    prefix = f"/test_ready2go_web_{uuid.uuid4().hex}"
    return BridgeTopics(
        runner_status=f"{prefix}/runner/status",
        robot_state=f"{prefix}/robot_state",
        camera_info=f"{prefix}/camera_info",
        voice_intent=f"{prefix}/voice/intent",
        robot_connection=None,
    )


def spin_until(executor: SingleThreadedExecutor, predicate, timeout_sec: float = 3.0) -> bool:
    """DDS 발견과 콜백이 비동기로 도착할 때까지 짧게 spin하며 조건을 확인한다."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        # 한 번에 오래 막지 않아 predicate와 제한 시간을 자주 다시 확인한다.
        executor.spin_once(timeout_sec=0.05)
        if predicate():
            return True
    return False


def test_json_callbacks_distinguish_valid_object_and_invalid_json(ros_context) -> None:
    """Runner JSON 객체는 저장하고 깨진 JSON은 오류와 마지막 정상 데이터를 함께 남긴다."""
    topics = unique_topics()
    bridge = DashboardBridge(topics=topics, node_name=f"web_bridge_{uuid.uuid4().hex}")
    try:
        # 실제 subscription 없이 callback을 직접 호출해 JSON 해석 경계만 빠르게 검증한다.
        bridge._on_runner_status(String(data=json.dumps({"phase": "idle"})))
        valid = bridge.cache.snapshot()["runner"]
        assert valid["message_valid"] is True
        assert valid["data"] == {"phase": "idle"}

        # 다음 깨진 JSON은 error가 되지만 마지막 정상 idle 데이터는 보존돼야 한다.
        bridge._on_runner_status(String(data="{not-json"))
        invalid = bridge.cache.snapshot()["runner"]
        assert invalid["message_valid"] is False
        assert invalid["connection_state"] == "error"
        assert invalid["last_error_kind"] == "message"
        assert invalid["data"] == {"phase": "idle"}

        # JSON 문법이 맞더라도 최상위 배열이면 상태 계약의 객체가 아니므로 거절한다.
        bridge._on_runner_status(String(data="[]"))
        non_object = bridge.cache.snapshot()["runner"]
        assert non_object["message_valid"] is False
        assert non_object["message_error"] == "JSON object required"
        assert non_object["data"] == {"phase": "idle"}
    finally:
        # executor에 넣지 않은 노드도 명시적으로 파괴해 DDS endpoint를 정리한다.
        bridge.destroy_node()


def test_runner_boot_id_change_replaces_payload_without_gid_observation(ros_context) -> None:
    """MessageInfo가 없어도 Runner boot_id 변경을 추가 기동 경계로 사용한다."""
    bridge = DashboardBridge(topics=unique_topics(), node_name=f"boot_bridge_{uuid.uuid4().hex}")
    try:
        # 첫 기동의 실행 상태를 GID 정보 없이 직접 콜백에 전달한다.
        bridge._on_runner_status(
            String(data=json.dumps({"boot_id": "boot-a", "phase": "running", "task_id": "old"})),
        )
        # 새 기동은 같은 콜백 경로에서 다른 boot_id와 idle 상태를 보낸다.
        bridge._on_runner_status(
            String(data=json.dumps({"boot_id": "boot-b", "phase": "idle", "task_id": None})),
        )

        # GID 교체 관찰이 없어도 캐시는 새 Runner 기동의 payload만 반환해야 한다.
        state = bridge.cache.snapshot()[RUNNER_SOURCE]
        assert state["connection_state"] == "receiving"
        assert state["data"] == {"boot_id": "boot-b", "phase": "idle", "task_id": None}
    finally:
        # 시험 노드의 DDS endpoint를 다음 시험 전에 명시적으로 정리한다.
        bridge.destroy_node()


def test_runner_only_stage_does_not_connect_later_sources(ros_context) -> None:
    """2단계 설정은 단일 노드에서 Runner 외 후속 source를 활성화하지 않는다."""
    topics = unique_topics()
    bridge = DashboardBridge(
        topics=topics,
        enabled_sources={RUNNER_SOURCE},
        node_name=f"runner_only_bridge_{uuid.uuid4().hex}",
    )
    try:
        # 캐시와 ROS graph 관찰표 모두 이번 단계의 runner 한 항목만 가져야 한다.
        assert set(bridge.cache.snapshot()) == {RUNNER_SOURCE}
        assert bridge._publisher_topics == {RUNNER_SOURCE: topics.runner_status}

        # 후속 단계의 실제 subscription 객체도 아직 생성되지 않았음을 확인한다.
        assert bridge._runner_subscription is not None
        assert bridge._robot_state_subscription is None
        assert bridge._camera_subscription is None
    finally:
        bridge.destroy_node()


@pytest.mark.parametrize("enabled_sources", [set(), {"unknown_source"}])
def test_invalid_enabled_sources_fail_before_ros_node_creation(enabled_sources: set[str]) -> None:
    """빈 단계 설정과 오타 source는 ROS endpoint 생성 전에 즉시 거절한다."""
    with pytest.raises(ValueError):
        DashboardBridge(enabled_sources=enabled_sources)


def test_camera_callback_keeps_only_connection_metadata(ros_context) -> None:
    """CameraInfo 전체 배열 대신 연결 화면에 필요한 작은 메타데이터만 캐시한다."""
    bridge = DashboardBridge(topics=unique_topics(), node_name=f"web_bridge_{uuid.uuid4().hex}")
    try:
        message = CameraInfo()
        message.header.frame_id = "wrist_cam_color_optical_frame"
        message.header.stamp.sec = 10
        message.header.stamp.nanosec = 20
        message.width = 1280
        message.height = 720
        # 보정 행렬 값을 넣어도 대시보드 연결 캐시에는 복제하지 않아야 한다.
        message.k = [1.0] * 9

        bridge._on_camera_info(message)

        state = bridge.cache.snapshot()["camera"]
        assert state["message_valid"] is True
        assert state["freshness_timeout_sec"] == 2.0
        assert state["data"] == {
            "frame_id": "wrist_cam_color_optical_frame",
            "stamp": {"sec": 10, "nanosec": 20},
            "width": 1280,
            "height": 720,
        }
        assert "k" not in state["data"]
    finally:
        bridge.destroy_node()


@pytest.mark.parametrize(
    ("argument", "value", "message"),
    [
        ("camera_timeout_sec", 0, "camera_timeout_sec"),
        ("camera_timeout_sec", True, "camera_timeout_sec"),
        ("graph_poll_period_sec", -1, "graph_poll_period_sec"),
        ("graph_poll_period_sec", True, "graph_poll_period_sec"),
    ],
)
def test_invalid_runtime_settings_fail_before_ros_node_creation(argument: str, value: object, message: str) -> None:
    """잘못된 timeout과 graph 주기를 ROS endpoint 생성 전에 명시적으로 거절한다."""
    # 검증이 super().__init__보다 먼저 실행되므로 rclpy context 없이도 설정 오류를 잡을 수 있다.
    with pytest.raises(ValueError, match=message):
        DashboardBridge(**{argument: value})  # type: ignore[arg-type]


def test_graph_error_recovery_keeps_message_error(ros_context, monkeypatch: pytest.MonkeyPatch) -> None:
    """그래프 조회 장애가 회복돼도 별도로 발생한 JSON 오류는 사라지지 않는다."""
    bridge = DashboardBridge(topics=unique_topics(), node_name=f"web_bridge_{uuid.uuid4().hex}")
    try:
        # 먼저 깨진 Runner JSON을 넣어 message 종류 오류를 만든다.
        bridge._on_runner_status(String(data="{invalid"))
        assert bridge.cache.snapshot()["runner"]["message_error"] is not None

        # get_publishers_info_by_topic이 모든 source에서 실패하는 graph 장애를 주입한다.
        with monkeypatch.context() as patch:
            def fail_graph_query(_node, _topic):
                """시험에서만 ROS 그래프 조회 실패를 강제로 발생시킨다."""
                raise RuntimeError("graph unavailable")

            patch.setattr(DashboardBridge, "get_publishers_info_by_topic", fail_graph_query)
            bridge._poll_publishers()

        failed = bridge.cache.snapshot()["runner"]
        assert failed["bridge_error"] == "ROS graph query failed: RuntimeError"
        assert failed["message_error"] is not None
        assert failed["last_error_kind"] == "bridge"

        # monkeypatch가 복구된 뒤 정상 그래프 조회는 bridge 오류만 해제해야 한다.
        bridge._poll_publishers()
        recovered = bridge.cache.snapshot()["runner"]
        assert recovered["bridge_error"] is None
        assert recovered["message_error"] is not None
        assert recovered["last_error_kind"] == "message"
    finally:
        bridge.destroy_node()


def test_endpoint_gid_change_invalidates_old_payload_without_graph_gap(
    ros_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """publisher count가 계속 1이어도 GID가 바뀌면 이전 세대 상태를 비운다."""
    topics = unique_topics()
    bridge = DashboardBridge(
        topics=topics,
        node_name=f"endpoint_generation_bridge_{uuid.uuid4().hex}",
        enabled_sources={RUNNER_SOURCE},
    )
    try:
        # 첫 publisher의 메시지와 GID가 이미 관찰된 상태를 만든다.
        old_gid = bytes(range(16))
        bridge._on_runner_status(
            String(data='{"boot":"old"}'),
            SimpleNamespace(publisher_gid=old_gid),
        )
        bridge._publisher_observations[RUNNER_SOURCE] = (
            frozenset({old_gid}),
            bridge.cache.message_revision(RUNNER_SOURCE),
        )

        # graph 공백 없이 publisher GID만 교체된 결과를 주입한다.
        new_gid = bytes(range(1, 17))
        monkeypatch.setattr(
            bridge,
            "get_publishers_info_by_topic",
            lambda _topic: [SimpleNamespace(endpoint_gid=new_gid)],
        )
        bridge._poll_publishers()

        waiting = bridge.cache.snapshot()[RUNNER_SOURCE]
        assert waiting["publisher_present"] is True
        assert waiting["connection_state"] == "waiting"
        assert waiting["data"] is None

        # 새 publisher 콜백이 graph 확인보다 먼저 온 경우에는 그 새 값을 지우지 않는다.
        bridge._on_runner_status(
            String(data='{"boot":"new"}'),
            SimpleNamespace(publisher_gid=new_gid),
        )
        bridge._publisher_observations[RUNNER_SOURCE] = (
            frozenset({old_gid}),
            bridge.cache.message_revision(RUNNER_SOURCE) - 1,
        )
        bridge._poll_publishers()
        receiving = bridge.cache.snapshot()[RUNNER_SOURCE]
        assert receiving["connection_state"] == "receiving"
        assert receiving["data"] == {"boot": "new"}
    finally:
        bridge.destroy_node()


def test_optional_robot_topic_is_only_added_when_configured(ros_context) -> None:
    """B 기준이 주어진 경우에만 로봇 publisher 관찰 항목을 활성화한다."""
    base = unique_topics()
    # 아직 타입을 추측해 구독하지 않고 별도 graph 확인용 토픽 이름만 제공한다.
    topics = BridgeTopics(
        runner_status=base.runner_status,
        robot_state=base.robot_state,
        camera_info=base.camera_info,
        voice_intent=base.voice_intent,
        robot_connection=f"{base.runner_status}/robot_connection",
    )
    bridge = DashboardBridge(topics=topics, node_name=f"robot_graph_bridge_{uuid.uuid4().hex}")
    try:
        # 설정한 이름이 source→topic 그래프 관찰표에 정확히 들어가야 한다.
        assert bridge._publisher_topics["robot"] == topics.robot_connection
        # publisher가 아직 없으므로 추측 없이 disconnected로 확인된다.
        assert bridge.cache.snapshot()["robot"]["publisher_present"] is False
    finally:
        bridge.destroy_node()


def test_real_ros_delivery_and_publisher_discovery(ros_context) -> None:
    """격리된 실제 rclpy executor에서 상태·카메라 수신과 Voice publisher 발견을 확인한다."""
    topics = unique_topics()
    bridge = DashboardBridge(
        topics=topics,
        graph_poll_period_sec=0.05,
        node_name=f"web_bridge_{uuid.uuid4().hex}",
    )
    publisher_node = Node(f"web_bridge_publishers_{uuid.uuid4().hex}")
    executor = SingleThreadedExecutor()
    try:
        # Runner 두 토픽은 운영 노드와 같은 RELIABLE/TRANSIENT_LOCAL/depth1로 발행한다.
        runner_pub = publisher_node.create_publisher(String, topics.runner_status, PUBLISHER_STATUS_QOS)
        state_pub = publisher_node.create_publisher(String, topics.robot_state, PUBLISHER_STATUS_QOS)

        # 카메라 발행자는 A 실측과 같은 RELIABLE/VOLATILE/depth10을 사용한다.
        camera_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        camera_pub = publisher_node.create_publisher(CameraInfo, topics.camera_info, camera_qos)

        # Voice는 메시지를 발행하지 않고 publisher endpoint 존재만 제공한다.
        voice_pub = publisher_node.create_publisher(String, topics.voice_intent, 10)

        # 한 executor에서 브리지 구독 콜백과 publisher 노드의 DDS 처리를 함께 진행한다.
        executor.add_node(bridge)
        executor.add_node(publisher_node)

        # DDS discovery가 끝날 때까지 publisher 수가 보이는 조건을 기다린다.
        discovered = spin_until(
            executor,
            lambda: all(
                publisher_node.count_publishers(topic) > 0
                for topic in (
                    topics.runner_status,
                    topics.robot_state,
                    topics.camera_info,
                    topics.voice_intent,
                )
            ),
        )
        assert discovered

        # 실제 ROS 직렬화·전달 경로를 통해 세 구독 메시지를 발행한다.
        runner_pub.publish(String(data=json.dumps({"phase": "running", "current_step": "s1"})))
        state_pub.publish(String(data=json.dumps({"drawer": {"top": "open"}})))
        camera_message = CameraInfo()
        camera_message.header.frame_id = "wrist_cam"
        camera_message.width = 1280
        camera_message.height = 720
        camera_pub.publish(camera_message)

        # 세 메시지 수신과 graph timer의 Voice publisher 확인을 모두 기다린다.
        received = spin_until(
            executor,
            lambda: (
                bridge.cache.snapshot()["runner"]["message_valid"]
                and bridge.cache.snapshot()["robot_state"]["message_valid"]
                and bridge.cache.snapshot()["camera"]["message_valid"]
                and bridge.cache.snapshot()["voice"]["publisher_present"] is True
            ),
        )
        assert received

        snapshot = bridge.cache.snapshot()
        # Runner와 robot_state는 JSON 객체가 손실 없이 캐시에 들어가야 한다.
        assert snapshot["runner"]["data"]["current_step"] == "s1"
        assert snapshot["robot_state"]["data"] == {"drawer": {"top": "open"}}
        # Voice는 메시지 없이도 publisher 존재만 확인하며 message_received는 false다.
        assert snapshot["voice"]["publisher_present"] is True
        assert snapshot["voice"]["message_received"] is False
        assert snapshot["voice"]["connection_state"] == "waiting"
        # B 토픽은 설정하지 않았으므로 추측 없이 확인 전 상태를 유지한다.
        assert snapshot["robot"]["publisher_present"] is None
        assert snapshot["robot"]["connection_state"] == "unknown"

        # 변수 참조를 유지해 publisher가 시험 중간에 가비지 컬렉션되지 않게 한다.
        assert voice_pub is not None
    finally:
        # executor에서 노드를 먼저 제거한 뒤 endpoint와 context를 정리한다.
        executor.remove_node(bridge)
        executor.remove_node(publisher_node)
        bridge.destroy_node()
        publisher_node.destroy_node()
        executor.shutdown()


def test_late_bridge_receives_transient_local_runner_status(ros_context) -> None:
    """Runner가 먼저 발행한 latched 상태를 나중에 시작한 웹 브리지도 수신한다."""
    topics = unique_topics()
    publisher_node = Node(f"late_status_publisher_{uuid.uuid4().hex}")
    executor = SingleThreadedExecutor()
    bridge = None
    try:
        # 웹 브리지보다 먼저 Runner 역할의 TRANSIENT_LOCAL publisher를 만든다.
        runner_pub = publisher_node.create_publisher(String, topics.runner_status, PUBLISHER_STATUS_QOS)
        executor.add_node(publisher_node)

        # subscriber가 아직 없는 상태에서 마지막 Runner 상태를 한 번 발행한다.
        runner_pub.publish(String(data=json.dumps({"phase": "idle", "task_id": None})))
        for _ in range(3):
            executor.spin_once(timeout_sec=0.05)

        # 발행이 끝난 뒤 웹 브리지를 생성해 late subscription 상황을 만든다.
        bridge = DashboardBridge(
            topics=topics,
            graph_poll_period_sec=0.05,
            node_name=f"late_web_bridge_{uuid.uuid4().hex}",
        )
        executor.add_node(bridge)

        # TRANSIENT_LOCAL QoS라면 새 발행 없이도 저장된 마지막 상태가 도착해야 한다.
        received = spin_until(
            executor,
            lambda: bridge.cache.snapshot()["runner"]["message_valid"],
        )
        assert received
        assert bridge.cache.snapshot()["runner"]["data"] == {"phase": "idle", "task_id": None}
    finally:
        # 생성에 실패한 경우에도 이미 만든 publisher 노드와 executor는 정리한다.
        if bridge is not None:
            executor.remove_node(bridge)
            bridge.destroy_node()
        executor.remove_node(publisher_node)
        publisher_node.destroy_node()
        executor.shutdown()


def test_voice_publisher_disappearance_and_restart_are_observed(ros_context) -> None:
    """간헐 발행 Voice는 메시지가 아니라 publisher 종료와 재생성으로 상태가 바뀐다."""
    topics = unique_topics()
    bridge = DashboardBridge(
        topics=topics,
        graph_poll_period_sec=0.05,
        node_name=f"voice_graph_bridge_{uuid.uuid4().hex}",
    )
    publisher_node = Node(f"voice_graph_publisher_{uuid.uuid4().hex}")
    executor = SingleThreadedExecutor()
    try:
        executor.add_node(bridge)
        executor.add_node(publisher_node)

        # 첫 Voice publisher를 만들되 intent 메시지는 발행하지 않는다.
        voice_pub = publisher_node.create_publisher(String, topics.voice_intent, 10)
        appeared = spin_until(
            executor,
            lambda: bridge.cache.snapshot()["voice"]["publisher_present"] is True,
        )
        assert appeared
        assert bridge.cache.snapshot()["voice"]["message_received"] is False

        # endpoint를 제거하면 graph timer가 publisher 부재를 감지해야 한다.
        publisher_node.destroy_publisher(voice_pub)
        disappeared = spin_until(
            executor,
            lambda: bridge.cache.snapshot()["voice"]["publisher_present"] is False,
        )
        assert disappeared
        assert bridge.cache.snapshot()["voice"]["connection_state"] == "disconnected"

        # 같은 토픽에 publisher를 다시 만들면 메시지 없이도 존재 상태가 회복돼야 한다.
        replacement = publisher_node.create_publisher(String, topics.voice_intent, 10)
        reappeared = spin_until(
            executor,
            lambda: bridge.cache.snapshot()["voice"]["publisher_present"] is True,
        )
        assert reappeared
        assert bridge.cache.snapshot()["voice"]["connection_state"] == "waiting"

        # replacement 참조를 유지해 재발견 직후 가비지 컬렉션되는 것을 막는다.
        assert replacement is not None
    finally:
        executor.remove_node(bridge)
        executor.remove_node(publisher_node)
        bridge.destroy_node()
        publisher_node.destroy_node()
        executor.shutdown()


def test_bridge_can_be_created_and_destroyed_repeatedly(ros_context) -> None:
    """Flask 재시작 전 단계로 노드 생성·정리를 반복해 endpoint 누적 오류를 확인한다."""
    # 같은 context에서 여러 번 만들고 파괴해 destroy_node 경로가 다음 생성을 막지 않는지 본다.
    for index in range(5):
        bridge = DashboardBridge(
            topics=unique_topics(),
            node_name=f"lifecycle_bridge_{index}_{uuid.uuid4().hex}",
        )
        # 생성 직후 다섯 source가 모두 한 번씩 등록됐는지 확인한다.
        assert set(bridge.cache.snapshot()) == {"runner", "robot_state", "camera", "voice", "robot"}
        bridge.destroy_node()
