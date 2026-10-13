"""Flask 프로세스 안에서 ROS 웹 브리지를 별도 executor로 실행한다.

이 모듈은 이슈 #267의 2~4단계 실행 수명주기를 담당한다. Flask 요청 스레드는
``rclpy.spin``을 호출하지 않으며, 전용 스레드가 단일 ``DashboardBridge`` 노드를
처리한다. 4단계의 기본 활성 소스는 ``/runner/status``와 ``/robot_state``다.
"""

from __future__ import annotations

import threading
from typing import Final

import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor

from ready2go_web.core.state_cache import StateCache
from ready2go_web.nodes.dashboard_bridge import (
    BridgeTopics,
    DashboardBridge,
    ROBOT_STATE_SOURCE,
    RUNNER_SOURCE,
)


# executor 스레드 이름은 시험·장애 조사 때 프로세스 스레드를 식별하는 근거다.
EXECUTOR_THREAD_NAME: Final = "ready2go-web-ros-executor"


class RosBridgeRuntime:
    """하나의 ROS context, 노드, executor와 스레드의 수명주기를 소유한다."""

    def __init__(
        self,
        *,
        topics: BridgeTopics | None = None,
        node_name: str = "ready2go_web_bridge",
    ) -> None:
        # 토픽과 노드 이름은 실제 실행뿐 아니라 격리된 통합시험에서도 주입할 수 있다.
        self._topics = topics
        self._node_name = node_name

        # start·stop이 다른 스레드에서 동시에 호출돼도 중복 ROS 자원을 만들지 않게 한다.
        self._lifecycle_lock = threading.RLock()

        # 아래 자원은 start가 성공한 뒤에만 채워지고 stop에서 역순으로 해제된다.
        self._context: Context | None = None
        self._bridge: DashboardBridge | None = None
        self._executor: SingleThreadedExecutor | None = None
        self._thread: threading.Thread | None = None

    @property
    def cache(self) -> StateCache:
        """실행 중인 브리지가 갱신하는 공유 캐시를 반환한다."""
        # 시작 전 캐시 접근은 서버 조립 순서 오류이므로 빈 값을 조용히 반환하지 않는다.
        with self._lifecycle_lock:
            if self._bridge is None:
                raise RuntimeError("ROS 브리지가 시작되지 않았습니다")
            return self._bridge.cache

    @property
    def is_running(self) -> bool:
        """executor 스레드가 현재 살아 있는지 반환한다."""
        with self._lifecycle_lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Runner 상태 두 종류를 받는 DashboardBridge와 별도 executor를 시작한다."""
        with self._lifecycle_lock:
            # 같은 runtime의 이중 시작은 노드명·구독 endpoint 중복을 만들므로 거절한다.
            if self._context is not None:
                raise RuntimeError("ROS 브리지가 이미 시작되었습니다")

            # 전역 기본 context와 분리하면 이 runtime이 자신이 만든 ROS 자원만 종료한다.
            context = Context()
            bridge: DashboardBridge | None = None
            executor: SingleThreadedExecutor | None = None
            try:
                rclpy.init(args=None, context=context)

                # 4단계에서는 Runner 연결 상태와 기억 상태를 함께 켠다. 카메라·Voice·
                # 로봇 드라이버 연결 판정은 담당 기준이 확정된 후속 단계로 유지한다.
                bridge = DashboardBridge(
                    topics=self._topics,
                    node_name=self._node_name,
                    enabled_sources={RUNNER_SOURCE, ROBOT_STATE_SOURCE},
                    context=context,
                )

                # 단일 노드에는 SingleThreadedExecutor면 충분하며 캐시가 Flask와의 경계를 맡는다.
                executor = SingleThreadedExecutor(context=context)
                executor.add_node(bridge)

                # daemon은 비정상 인터프리터 종료의 최후 안전망이고 정상 종료는 stop이 담당한다.
                thread = threading.Thread(
                    target=self._spin,
                    args=(executor, bridge),
                    name=EXECUTOR_THREAD_NAME,
                    daemon=True,
                )

                # 모든 자원 참조를 먼저 게시한 뒤 스레드를 시작해 stop과의 경합을 막는다.
                self._context = context
                self._bridge = bridge
                self._executor = executor
                self._thread = thread
                thread.start()
            except Exception:
                # 부분 초기화 실패도 executor·노드·context를 역순으로 정리한다.
                if executor is not None:
                    executor.shutdown(timeout_sec=0.5)
                if bridge is not None:
                    bridge.destroy_node()
                if context.ok():
                    context.shutdown()
                self._context = None
                self._bridge = None
                self._executor = None
                self._thread = None
                raise

    @staticmethod
    def _spin(executor: SingleThreadedExecutor, bridge: DashboardBridge) -> None:
        """전용 스레드에서 ROS 콜백을 처리하고 예외를 캐시에 기록한다."""
        try:
            # shutdown이 호출될 때까지 subscription과 graph timer 콜백을 처리한다.
            executor.spin()
        except Exception as exc:
            # 스레드 예외는 두 source 모두 수신할 수 없게 하므로 각각 같은 브리지
            # 오류를 남겨 REST가 한 source만 정상인 것처럼 보이지 않게 한다.
            error = f"ROS executor failed: {type(exc).__name__}"
            bridge.cache.record_bridge_error(RUNNER_SOURCE, error)
            bridge.cache.record_bridge_error(ROBOT_STATE_SOURCE, error)

    def stop(self) -> None:
        """executor를 깨우고 스레드·노드·context를 안전한 순서로 정리한다."""
        with self._lifecycle_lock:
            # 시작되지 않았거나 이미 종료된 runtime의 stop은 반복 호출해도 안전하다.
            if self._context is None:
                return

            context = self._context
            bridge = self._bridge
            executor = self._executor
            thread = self._thread

            # 먼저 executor를 종료해 spin을 깨운 뒤 스레드가 끝날 때까지 제한 시간만 기다린다.
            if executor is not None:
                executor.shutdown(timeout_sec=2.0)
            if thread is not None:
                thread.join(timeout=2.0)
                if thread.is_alive():
                    raise RuntimeError("ROS executor 스레드가 제한 시간 안에 종료되지 않았습니다")

            # 콜백 스레드가 끝난 뒤 executor와 노드의 연결 및 DDS endpoint를 제거한다.
            if executor is not None and bridge is not None:
                executor.remove_node(bridge)
            if bridge is not None:
                bridge.destroy_node()

            # 이 runtime이 만든 전용 context만 마지막에 종료한다.
            if context.ok():
                context.shutdown()

            # stop 완료 뒤 같은 객체를 다시 시작할 수 있도록 자원 참조를 초기화한다.
            self._context = None
            self._bridge = None
            self._executor = None
            self._thread = None
