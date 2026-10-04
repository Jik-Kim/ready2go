"""ROS 액션·서비스 클라이언트 (rclpy) — core/backend.py 의 call_action·call_service 구현 (#10).

- 액션: /skills/<동작>, /voice/speak (Skill: goal params_json / result success·error_code·output_json)
- 서비스: /vision/inspect_region (InspectRegion: region·search_target / success·error_code·result_json)

Runner 는 블로킹으로 실행되므로, 노드는 다른 스레드의 executor 가 돌리고(nodes/runner_node.py)
여기서는 future 가 끝나기를 threading.Event 로 기다린다.
멈춤 보장 (NFR-SAF-02, PR #74 리뷰):
- Skill goal 에는 제한 시간 칸이 없으므로 timeout_sec 이 지나면 여기서 취소를 요청한다.
- /runner/estop 등으로 Runner 가 멈추면 cancel_all() 이 진행 중인 goal 에 즉시 취소를 요청한다.
- 어느 경우든 백엔드가 멈추고 최종 결과(canceled)를 줄 때까지 기다린 뒤에만 돌아간다 → 다음 동작(finally 등)이
  앞 동작과 겹치지 않는다. CANCEL_CONFIRM_SEC 안에 최종 결과가 없으면 STOP_UNCONFIRMED (Runner 가 잠금).
시간 초과로 끝난 동작은 어디까지 됐는지 모르므로 Runner 는 재시도하지 않는다 (runner.md 7.1, PR #64 리뷰).
"""
from __future__ import annotations

import threading

from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node

from ready2go_interfaces.action import Skill
from ready2go_interfaces.srv import InspectRegion

from ..core.backend import BACKEND_ERROR, Reply

TIMEOUT = "TIMEOUT"
STOP_UNCONFIRMED = "STOP_UNCONFIRMED"   # 취소 후 백엔드의 정지 확인(최종 결과)이 없음 → Runner 잠금 (HALT_CODES)
CANCELED = "CANCELED"
CANCEL_CONFIRM_SEC = 5.0                # 취소 요청 뒤 최종 결과를 기다리는 최대 시간 [추정, 실측 후 조정]
SERVER_WAIT_SEC = 2.0                   # 서버를 찾는 최대 시간 [추정, 실측 후 조정]. 없으면 BACKEND_ERROR (동작 안 함)
GOAL_ACCEPT_SEC = 5.0                   # goal 수락 응답을 기다리는 최대 시간 [추정]


class RosClients:
    def __init__(self, node: Node, server_wait_sec: float = SERVER_WAIT_SEC,
                 goal_accept_sec: float = GOAL_ACCEPT_SEC, cancel_confirm_sec: float = CANCEL_CONFIRM_SEC,
                 stopping=lambda: False):
        self.node = node
        self.server_wait_sec, self.goal_accept_sec = server_wait_sec, goal_accept_sec
        self.cancel_confirm_sec = cancel_confirm_sec
        self.stopping = stopping                # Runner 가 멈춘 상태인지 (goal 수락과 중단 요청이 엇갈릴 때 확인)
        self._group = ReentrantCallbackGroup()
        self._actions: dict[str, ActionClient] = {}
        self._services: dict[str, object] = {}
        self._lock = threading.Lock()
        self._active: dict[int, tuple] = {}     # 진행 중인 goal: id → (handle, 깨우기 Event, 취소 요청 여부 [bool])

    def cancel_all(self) -> int:
        """진행 중인 모든 goal 에 취소를 요청한다 (/runner/estop·halt). 기다림은 각 call_action 이 한다."""
        with self._lock:
            active = list(self._active.values())
        for handle, wake, canceled in active:
            if not canceled[0]:
                canceled[0] = True
                handle.cancel_goal_async()
            wake.set()
        return len(active)

    def call_action(self, name: str, params_json: str, timeout_sec: float | None) -> Reply:
        client = self._actions.get(name)
        if client is None:
            client = self._actions[name] = ActionClient(self.node, Skill, name, callback_group=self._group)
        if not client.wait_for_server(timeout_sec=self.server_wait_sec):
            self.node.get_logger().error(f"{name}: 액션 서버 없음")
            return Reply(False, BACKEND_ERROR)

        sent = client.send_goal_async(Skill.Goal(params_json=params_json))
        if not _wait(sent, self.goal_accept_sec) or sent.result() is None:
            return Reply(False, BACKEND_ERROR)
        handle = sent.result()
        if not handle.accepted:
            self.node.get_logger().error(f"{name}: goal 거절")
            return Reply(False, BACKEND_ERROR)

        done = handle.get_result_async()
        wake, canceled = threading.Event(), [False]
        done.add_done_callback(lambda _: wake.set())
        key = id(handle)
        with self._lock:
            self._active[key] = (handle, wake, canceled)
        try:
            if self.stopping():                 # 보내는 사이에 중단 요청이 들어옴
                self.cancel_all()
            wake.wait(timeout_sec)              # 결과, 시간 초과, 또는 cancel_all() 이 깨움
            if done.done() and not canceled[0]:
                result = done.result().result
                return Reply(result.success, result.error_code, result.output_json)
            timed_out = not canceled[0]
            if timed_out:
                canceled[0] = True
                handle.cancel_goal_async()
                self.node.get_logger().warning(f"{name}: {timeout_sec}초 초과 → 취소 요청, 정지 확인 대기")
            if not _wait(done, self.cancel_confirm_sec):   # 백엔드가 멈추고 최종 결과를 줄 때까지
                self.node.get_logger().error(f"{name}: 취소 뒤 {self.cancel_confirm_sec}초 안에 정지 확인 없음")
                return Reply(False, STOP_UNCONFIRMED)
            if timed_out:
                return Reply(False, TIMEOUT)
            result = done.result().result         # 중단 요청으로 취소됨 (또는 직전에 끝남)
            return Reply(result.success, result.error_code or ("" if result.success else CANCELED),
                         result.output_json)
        finally:
            with self._lock:
                self._active.pop(key, None)

    def call_service(self, name: str, region: str, search_target: str, timeout_sec: float | None) -> Reply:
        client = self._services.get(name)
        if client is None:
            client = self._services[name] = self.node.create_client(InspectRegion, name, callback_group=self._group)
        if not client.wait_for_service(timeout_sec=self.server_wait_sec):
            self.node.get_logger().error(f"{name}: 서비스 없음")
            return Reply(False, BACKEND_ERROR)
        done = client.call_async(InspectRegion.Request(region=region, search_target=search_target))
        if not _wait(done, timeout_sec):
            return Reply(False, TIMEOUT)        # 인식은 로봇을 움직이지 않으므로 취소할 것이 없음
        response = done.result()
        if response is None:
            return Reply(False, BACKEND_ERROR)
        return Reply(response.success, response.error_code, response.result_json)


def _wait(future, timeout_sec: float | None) -> bool:
    """future 가 끝나면 True, 제한 시간이 지나면 False. timeout_sec=None 이면 끝날 때까지 기다림."""
    finished = threading.Event()
    future.add_done_callback(lambda _: finished.set())
    return finished.wait(timeout_sec)
