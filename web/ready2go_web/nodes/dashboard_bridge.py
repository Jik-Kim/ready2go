"""읽기 전용 웹 대시보드용 단일 rclpy 구독 노드.

이 노드는 ROS 데이터를 브라우저 형식으로 직접 렌더링하지 않는다. 확정된 ROS
토픽을 구독하고 최소한으로 해석한 뒤 :class:`StateCache`에 기록한다. Flask는
후속 단계에서 같은 캐시의 스냅샷만 읽는다. 기준: GitHub issue #267.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Collection
from typing import Any, Final

from rclpy.context import Context
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from sensor_msgs.msg import CameraInfo, JointState
from std_msgs.msg import String

from ready2go_web.core.state_cache import StateCache


# Runner가 현재 사용하는 latched 상태 토픽과 동일한 구독 QoS다.
# 늦게 시작한 웹 브리지도 마지막 상태를 받을 수 있도록 TRANSIENT_LOCAL을 사용한다.
LATCHED_STATUS_QOS: Final = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)

# StateCache와 REST 응답에서 사용할 source 이름을 한곳에 고정한다.
RUNNER_SOURCE: Final = "runner"
ROBOT_STATE_SOURCE: Final = "robot_state"
CAMERA_SOURCE: Final = "camera"
VOICE_SOURCE: Final = "voice"
ROBOT_SOURCE: Final = "robot"

# 단계별 연결에서 사용할 수 있는 source 이름을 한곳에서 검증한다.
ALL_SOURCES: Final = frozenset(
    {
        RUNNER_SOURCE,
        ROBOT_STATE_SOURCE,
        CAMERA_SOURCE,
        VOICE_SOURCE,
        ROBOT_SOURCE,
    }
)


@dataclass(frozen=True)
class BridgeTopics:
    """웹 브리지가 관찰할 토픽 이름 모음.

    robot_connection은 B가 #267에서 정한 관절 상태 토픽이다. 이름은 실물과
    에뮬레이터가 같고, 실행 프로필별 발행자 유무는 화면 어댑터가 구분한다.
    """

    runner_status: str = "/runner/status"  # C Runner 실행·요청·결과 상태 JSON.
    robot_state: str = "/robot_state"  # C Runner가 기억하는 현재 상태 JSON.
    camera_info: str = "/wrist_cam/color/camera_info"  # A가 실측한 카메라 연결 근거.
    voice_intent: str = "/voice/intent"  # E VoiceNode의 간헐적 intent 발행 토픽.
    robot_connection: str = "/dsr01/joint_states"  # B가 확인한 관절 상태 수신 근거.


class DashboardBridge(Node):
    """ROS 구독과 publisher 관찰 결과를 하나의 StateCache에 기록한다."""

    def __init__(
        self,
        *,
        topics: BridgeTopics | None = None,
        camera_timeout_sec: float = 2.0,
        robot_timeout_sec: float = 2.0,
        graph_poll_period_sec: float = 1.0,
        node_name: str = "ready2go_web_bridge",
        enabled_sources: Collection[str] | None = None,
        context: Context | None = None,
    ) -> None:
        # bool은 int의 하위 타입이므로 True가 1초 설정으로 들어오는 경우도 막는다.
        if isinstance(camera_timeout_sec, bool) or camera_timeout_sec <= 0:
            raise ValueError("camera_timeout_sec은 0보다 커야 합니다")
        # B의 2초 제안값은 환경 설정으로 주입하며 0 이하이면 단절 판정이 무의미하다.
        if isinstance(robot_timeout_sec, bool) or robot_timeout_sec <= 0:
            raise ValueError("robot_timeout_sec은 0보다 커야 합니다")
        # 주기가 0 이하면 timer 폭주를 만들므로 ROS 노드를 만들기 전에 거절한다.
        if isinstance(graph_poll_period_sec, bool) or graph_poll_period_sec <= 0:
            raise ValueError("graph_poll_period_sec은 0보다 커야 합니다")

        # None은 전체 source를 쓰는 브리지 시험을 뜻한다. 실행 진입점은 현재 합의된
        # Runner·로봇·카메라·Voice 다섯 source를 명시해 새 source가 자동 활성화되지 않게 한다.
        active_sources = ALL_SOURCES if enabled_sources is None else frozenset(enabled_sources)
        unknown_sources = active_sources - ALL_SOURCES
        if unknown_sources:
            unknown_list = ", ".join(sorted(unknown_sources))
            raise ValueError(f"지원하지 않는 source입니다: {unknown_list}")
        if not active_sources:
            raise ValueError("enabled_sources에는 source가 하나 이상 필요합니다")

        # 같은 프로세스에서 Flask와 공유할 단 하나의 rclpy Node를 초기화한다.
        # context를 주입하면 웹 브리지가 전역 ROS context를 소유하지 않고 자체
        # executor 수명주기 안에서 안전하게 시작·종료될 수 있다.
        super().__init__(node_name, context=context)

        # 호출자가 토픽을 주지 않으면 이슈 #267에서 확인한 운영 기본값을 사용한다.
        self.topics = topics or BridgeTopics()

        # Runner 두 상태와 Voice는 메시지 나이만으로 끊김을 판정하지 않는다.
        # 카메라와 로봇 관절 상태는 각각 설정 가능한 freshness timeout을 사용한다.
        source_timeouts = {
            RUNNER_SOURCE: None,
            ROBOT_STATE_SOURCE: None,
            CAMERA_SOURCE: camera_timeout_sec,
            VOICE_SOURCE: None,
            ROBOT_SOURCE: robot_timeout_sec,
        }
        self.cache = StateCache(
            {source: source_timeouts[source] for source in active_sources}
        )

        # 구독 객체를 속성에 보관해 노드가 살아 있는 동안 가비지 컬렉션되지 않게 한다.
        self._runner_subscription = None
        self._robot_state_subscription = None
        self._camera_subscription = None
        self._robot_subscription = None
        # 상태 콜백의 MessageInfo에서 실제 발행자 GID를 기록한다. graph GID 교체를
        # 확인할 때 새 publisher의 메시지가 먼저 도착했는지 직접 구분하는 근거다.
        self._message_publisher_gids: dict[str, bytes] = {}

        # /runner/status는 std_msgs/String JSON이며 Runner의 latched QoS와 맞춘다.
        if RUNNER_SOURCE in active_sources:
            self._runner_subscription = self.create_subscription(
                String,
                self.topics.runner_status,
                self._on_runner_status,
                LATCHED_STATUS_QOS,
            )

        # /robot_state도 std_msgs/String JSON이며 같은 latched QoS를 사용한다.
        if ROBOT_STATE_SOURCE in active_sources:
            self._robot_state_subscription = self.create_subscription(
                String,
                self.topics.robot_state,
                self._on_robot_state,
                LATCHED_STATUS_QOS,
            )

        # A 실측과 기존 비전 구독자에 맞춰 CameraInfo는 sensor-data QoS로 받는다.
        if CAMERA_SOURCE in active_sources:
            self._camera_subscription = self.create_subscription(
                CameraInfo,
                self.topics.camera_info,
                self._on_camera_info,
                qos_profile_sensor_data,
            )

        # B가 정한 JointState는 100 Hz 전체 값을 보존하지 않고 최근 유효 수신만 판정한다.
        if ROBOT_SOURCE in active_sources and self.topics.robot_connection:
            self._robot_subscription = self.create_subscription(
                JointState,
                self.topics.robot_connection,
                self._on_robot_joint_state,
                qos_profile_sensor_data,
            )

        # source와 topic의 대응을 한곳에 두고 같은 timer에서 ROS 그래프를 확인한다.
        # Voice는 최근 메시지가 없어도 정상일 수 있어 구독하지 않고 publisher만 본다.
        candidate_topics: dict[str, str] = {
            RUNNER_SOURCE: self.topics.runner_status,
            ROBOT_STATE_SOURCE: self.topics.robot_state,
            CAMERA_SOURCE: self.topics.camera_info,
            VOICE_SOURCE: self.topics.voice_intent,
        }
        self._publisher_topics = {
            source: topic
            for source, topic in candidate_topics.items()
            if source in active_sources
        }

        # 활성화된 로봇 source의 JointState 토픽도 같은 graph timer에서 관찰한다.
        if ROBOT_SOURCE in active_sources and self.topics.robot_connection:
            self._publisher_topics[ROBOT_SOURCE] = self.topics.robot_connection

        # source별 마지막 endpoint GID 집합과 당시 메시지 revision을 함께 보관한다.
        # publisher 수가 계속 1이어도 GID가 바뀌면 Runner 재기동으로 판정할 수 있다.
        self._publisher_observations: dict[str, tuple[frozenset[bytes], int]] = {}

        # 메시지 주기와 별개로 publisher 존재를 확인하는 저빈도 graph timer다.
        self._graph_timer = self.create_timer(graph_poll_period_sec, self._poll_publishers)

        # timer의 첫 호출을 기다리는 동안도 초기 그래프 상태를 빨리 제공하도록 한 번 조회한다.
        self._poll_publishers()

    def _on_runner_status(self, message: String, message_info: Any = None) -> None:
        """Runner 상태 JSON을 객체로 해석해 runner source에 기록한다."""
        self._record_json_message(RUNNER_SOURCE, message.data, message_info=message_info)

    def _on_robot_state(self, message: String, message_info: Any = None) -> None:
        """Runner 저장 상태 JSON을 객체로 해석해 robot_state source에 기록한다."""
        self._record_json_message(ROBOT_STATE_SOURCE, message.data, message_info=message_info)

    def _record_json_message(self, source: str, raw: str, *, message_info: Any = None) -> None:
        """String 메시지를 JSON 객체로 제한하고 정상·오류를 캐시에 분리한다."""
        # 실제 rclpy 콜백은 MessageInfo에 publisher GID를 제공한다. 직접 호출 단위
        # 시험처럼 정보가 없는 경우에는 revision 비교 경로를 사용한다.
        publisher_gid = getattr(message_info, "publisher_gid", None)
        if publisher_gid is not None:
            self._message_publisher_gids[source] = bytes(publisher_gid)
        try:
            # std_msgs/String의 data 전체를 JSON으로 해석하며 부분 성공은 허용하지 않는다.
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            # 원문 전체를 오류에 넣지 않고 위치만 남겨 로그/API의 불필요한 정보 노출을 피한다.
            self.cache.record_invalid_message(
                source,
                f"JSON decode failed at line {exc.lineno}, column {exc.colno}",
            )
            return

        # 두 상태 계약은 최상위 JSON 객체이므로 배열·문자열·숫자는 유효 상태로 받지 않는다.
        if not isinstance(parsed, dict):
            self.cache.record_invalid_message(source, "JSON object required")
            return

        # 현재 Runner가 제공하는 비어 있지 않은 boot_id만 추가 기동 구분 근거로 쓴다.
        # 이전 Runner나 다른 JSON source에는 이 필드가 없어도 기존 수신 동작을 유지한다.
        boot_id = parsed.get("boot_id") if source == RUNNER_SOURCE else None
        generation_id = boot_id if isinstance(boot_id, str) and boot_id.strip() else None
        # 깊은 복사·시각 기록과 boot_id 변경 시 이전 기동 초기화를 캐시에 맡긴다.
        self.cache.record_message(source, parsed, generation_id=generation_id)

    def _on_camera_info(self, message: CameraInfo) -> None:
        """고주기 CameraInfo에서 연결 진단에 필요한 작은 메타데이터만 보관한다."""
        # 전체 보정 행렬은 이번 연결 유무 화면에 필요 없으므로 캐시 크기를 늘리지 않는다.
        summary = {
            "frame_id": message.header.frame_id,
            "stamp": {
                "sec": message.header.stamp.sec,
                "nanosec": message.header.stamp.nanosec,
            },
            "width": message.width,
            "height": message.height,
        }
        # 실제 메시지 콜백이 실행됐을 때만 카메라를 정상 수신으로 기록한다.
        self.cache.record_message(CAMERA_SOURCE, summary)

    def _on_robot_joint_state(self, message: JointState) -> None:
        """고주기 JointState에서 관절 상태 수신 판정에 필요한 메타데이터만 저장한다."""
        # 위치·속도·토크 배열은 화면 기능 범위가 아니므로 캐시에 복사하지 않는다.
        summary = {
            "joint_count": len(message.name),
            "joint_names": list(message.name),
            "frame_id": message.header.frame_id,
            "stamp": {
                "sec": message.header.stamp.sec,
                "nanosec": message.header.stamp.nanosec,
            },
        }
        # 이 수신은 관절 상태 발행만 뜻하며 제어기·E-stop·모션 가능 판정으로 확장하지 않는다.
        self.cache.record_message(ROBOT_SOURCE, summary)

    def _poll_publishers(self) -> None:
        """ROS 그래프에서 source별 publisher 존재를 확인하고 캐시와 분리해 기록한다."""
        for source, topic in self._publisher_topics.items():
            try:
                # 한 개 이상 endpoint가 있으면 해당 토픽의 publisher가 존재한다.
                publishers = self.get_publishers_info_by_topic(topic)
            except Exception as exc:  # rclpy graph 구현별 예외를 bridge 오류로 변환한다.
                # 그래프 조회 실패는 메시지 파싱 실패와 다른 bridge 종류 오류다.
                self.cache.record_bridge_error(
                    source,
                    f"ROS graph query failed: {type(exc).__name__}",
                )
                continue

            # 그래프 조회가 다시 성공하면 앞서 기록한 bridge 오류만 선택적으로 해제한다.
            self.cache.clear_bridge_error(source)
            # endpoint 수가 끊김 없이 유지돼도 GID 집합이 바뀌면 publisher 세대가
            # 교체된 것이다. 이전 graph 관찰 뒤 콜백이 없었던 경우에만 옛 payload를
            # 지워, 새 publisher 메시지가 graph 조회보다 먼저 온 경합에서는 새 값을 보존한다.
            endpoint_ids = frozenset(bytes(info.endpoint_gid) for info in publishers)
            previous = self._publisher_observations.get(source)
            if (
                previous is not None
                and previous[0]
                and endpoint_ids
                and previous[0] != endpoint_ids
            ):
                # 새 endpoint GID가 메시지 콜백에도 확인되면 그 payload는 새 세대다.
                # MessageInfo가 없는 경로는 이전 graph 관찰 뒤 revision 증가 여부로
                # 보수적으로 판단한다.
                new_message_already_received = (
                    self._message_publisher_gids.get(source) in endpoint_ids
                )
                expected_revision = (
                    self.cache.message_revision(source)
                    if self._message_publisher_gids.get(source) is not None
                    else previous[1]
                )
                if not new_message_already_received:
                    self.cache.reset_for_publisher_change(
                        source,
                        expected_revision=expected_revision,
                    )
            # publisher 존재와 유효 메시지 수신 여부는 StateCache의 서로 다른 필드다.
            self.cache.set_publisher_present(source, bool(publishers))
            # set_publisher_present의 false→true 초기화와 동시 콜백까지 반영한 revision을
            # 다음 graph 비교 기준으로 저장한다.
            self._publisher_observations[source] = (
                endpoint_ids,
                self.cache.message_revision(source),
            )
