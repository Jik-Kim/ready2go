"""읽기 전용 웹 대시보드용 단일 rclpy 구독 노드.

이 노드는 ROS 데이터를 브라우저 형식으로 직접 렌더링하지 않는다. 확정된 ROS
토픽을 구독하고 최소한으로 해석한 뒤 :class:`StateCache`에 기록한다. Flask는
후속 단계에서 같은 캐시의 스냅샷만 읽는다. 기준: GitHub issue #267.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Collection
from typing import Final

from rclpy.context import Context
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from sensor_msgs.msg import CameraInfo
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

    robot_connection은 B의 실제 연결 기준이 확정되기 전까지 ``None``이다. 값이
    주어져도 메시지 형식을 추측해 구독하지 않고 ROS 그래프의 publisher 존재만
    확인한다.
    """

    runner_status: str = "/runner/status"  # C Runner 실행·요청·결과 상태 JSON.
    robot_state: str = "/robot_state"  # C Runner가 기억하는 현재 상태 JSON.
    camera_info: str = "/wrist_cam/color/camera_info"  # A가 실측한 카메라 연결 근거.
    voice_intent: str = "/voice/intent"  # E VoiceNode의 간헐적 intent 발행 토픽.
    robot_connection: str | None = None  # TODO(B): 실제 로봇 연결 판정 토픽 확정 뒤 설정.


class DashboardBridge(Node):
    """ROS 구독과 publisher 관찰 결과를 하나의 StateCache에 기록한다."""

    def __init__(
        self,
        *,
        topics: BridgeTopics | None = None,
        camera_timeout_sec: float = 2.0,
        graph_poll_period_sec: float = 1.0,
        node_name: str = "ready2go_web_bridge",
        enabled_sources: Collection[str] | None = None,
        context: Context | None = None,
    ) -> None:
        # bool은 int의 하위 타입이므로 True가 1초 설정으로 들어오는 경우도 막는다.
        if isinstance(camera_timeout_sec, bool) or camera_timeout_sec <= 0:
            raise ValueError("camera_timeout_sec은 0보다 커야 합니다")
        # 주기가 0 이하면 timer 폭주를 만들므로 ROS 노드를 만들기 전에 거절한다.
        if isinstance(graph_poll_period_sec, bool) or graph_poll_period_sec <= 0:
            raise ValueError("graph_poll_period_sec은 0보다 커야 합니다")

        # None은 기존 전체 브리지 시험과 최종 구성을 뜻한다. 실행 진입점은 이슈의
        # 단계 순서를 지키기 위해 이번 단계에서 runner 하나만 명시적으로 전달한다.
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
        # 카메라만 A 실측에 따른 설정 가능한 2초 기본 freshness timeout을 사용한다.
        source_timeouts = {
            RUNNER_SOURCE: None,
            ROBOT_STATE_SOURCE: None,
            CAMERA_SOURCE: camera_timeout_sec,
            VOICE_SOURCE: None,
            ROBOT_SOURCE: None,
        }
        self.cache = StateCache(
            {source: source_timeouts[source] for source in active_sources}
        )

        # 구독 객체를 속성에 보관해 노드가 살아 있는 동안 가비지 컬렉션되지 않게 한다.
        self._runner_subscription = None
        self._robot_state_subscription = None
        self._camera_subscription = None

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

        # B가 로봇 연결 근거를 정한 경우에만 선택 토픽을 publisher 관찰 대상에 넣는다.
        if ROBOT_SOURCE in active_sources and self.topics.robot_connection:
            self._publisher_topics[ROBOT_SOURCE] = self.topics.robot_connection

        # 메시지 주기와 별개로 publisher 존재를 확인하는 저빈도 graph timer다.
        self._graph_timer = self.create_timer(graph_poll_period_sec, self._poll_publishers)

        # timer의 첫 호출을 기다리는 동안도 초기 그래프 상태를 빨리 제공하도록 한 번 조회한다.
        self._poll_publishers()

    def _on_runner_status(self, message: String) -> None:
        """Runner 상태 JSON을 객체로 해석해 runner source에 기록한다."""
        self._record_json_message(RUNNER_SOURCE, message.data)

    def _on_robot_state(self, message: String) -> None:
        """Runner 저장 상태 JSON을 객체로 해석해 robot_state source에 기록한다."""
        self._record_json_message(ROBOT_STATE_SOURCE, message.data)

    def _record_json_message(self, source: str, raw: str) -> None:
        """String 메시지를 JSON 객체로 제한하고 정상·오류를 캐시에 분리한다."""
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

        # 정상 객체는 깊은 복사와 시각 기록을 StateCache에 맡긴다.
        self.cache.record_message(source, parsed)

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
            # publisher 존재와 유효 메시지 수신 여부는 StateCache의 서로 다른 필드다.
            self.cache.set_publisher_present(source, bool(publishers))
