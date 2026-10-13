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
- 취소 뒤 받은 최종 결과의 안전 코드(ESTOP·STOP_UNCONFIRMED 등, interpreter.HALT_CODES)는 TIMEOUT 으로
  덮지 않고 그대로 넘긴다 → Runner 가 잠금 (PR #74 E 리뷰).
- goal 을 보내기 직전에 중단 상태를 다시 확인하고, 수락 응답이 GOAL_ACCEPT_SEC 안에 오지 않으면 "보내지 않음"으로
  보지 않는다: 늦게 수락되면 즉시 취소하고 정지 확인까지 기다리며, 확인이 안 되면 STOP_UNCONFIRMED (PR #74 D 리뷰).
시간 초과로 끝난 동작은 어디까지 됐는지 모르므로 Runner 는 재시도하지 않는다 (runner.md 7.1, PR #64 리뷰).
"""
from __future__ import annotations

import json
import threading

from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node

from ready2go_interfaces.action import Skill
from ready2go_interfaces.srv import InspectRegion

from ..core.backend import BACKEND_ERROR, Reply
from ..core.interpreter import HALTED, HALT_CODES

TIMEOUT = "TIMEOUT"
STOP_UNCONFIRMED = "STOP_UNCONFIRMED"   # 취소 후 백엔드의 정지 확인(최종 결과)이 없음 → Runner 잠금 (HALT_CODES)
CANCELED = "CANCELED"
# 어댑터가 스스로 만든 실패(서버 없음·거절·보내지 않음·정지 확인 시간 초과) 표시 — 백엔드 최종 결과가 아님.
# Runner 는 이 응답을 /runner/status halt 의 "백엔드 응답 받음"으로 세지 않는다 (#259 E 리뷰 P1)
NO_BACKEND_RESULT = json.dumps({"no_backend_result": True})
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
        self.stopping = stopping                # 중단 요청이 처리 전인지 (Runner.stop_requested). 보내기 직전·수락 직후 확인
        self._group = ReentrantCallbackGroup()
        self._actions: dict[str, ActionClient] = {}
        self._services: dict[str, object] = {}
        self._lock = threading.Lock()
        self._active: dict[int, tuple] = {}     # 진행 중인 goal: id → (handle, 깨우기 Event, 취소 요청 여부 [bool])

    def cancel_all(self) -> int:
        """진행 중인 모든 goal 에 취소를 요청한다 (/runner/estop·halt). 기다림은 각 call_action 이 한다.
        돌려주는 수 = 취소를 보낸 **로봇 스킬**(/skills/*) goal 수 — 음성(/voice/speak) 등은 취소하되 세지 않음
        (/runner/status halt.canceled_goals·실행 기록 halts[], #259 D 리뷰: TTS 취소를 로봇 정지로 보지 않게)."""
        with self._lock:
            active = list(self._active.values())
        for handle, wake, canceled, _ in active:
            if not canceled[0]:
                canceled[0] = True
                handle.cancel_goal_async()
            wake.set()
        return sum(1 for *_, name in active if "/skills/" in name)

    def _action_client(self, name: str) -> ActionClient:
        client = self._actions.get(name)
        if client is None:
            client = self._actions[name] = ActionClient(self.node, Skill, name, callback_group=self._group)
        return client

    def missing_actions(self, names) -> list[str]:
        """아직 서버가 안 뜬 액션 이름 (기다리지 않음). 실행 전 확인용 (#108 D P1)."""
        return sorted(n for n in names if not self._action_client(n).server_is_ready())

    def call_action(self, name: str, params_json: str, timeout_sec: float | None) -> Reply:
        client = self._action_client(name)
        if not client.wait_for_server(timeout_sec=self.server_wait_sec):
            self.node.get_logger().error(f"{name}: 액션 서버 없음")
            return Reply(False, BACKEND_ERROR, NO_BACKEND_RESULT)
        if self.stopping():                     # 서버를 찾는 사이 중단 요청 → 보내지 않음
            return Reply(False, HALTED, NO_BACKEND_RESULT)

        sent = client.send_goal_async(Skill.Goal(params_json=params_json))
        if not _wait(sent, self.goal_accept_sec):
            return self._settle_late_goal(name, sent)
        handle = sent.result()
        if handle is None or not handle.accepted:
            self.node.get_logger().error(f"{name}: goal 거절")
            return Reply(False, BACKEND_ERROR, NO_BACKEND_RESULT)
        return self._follow(name, handle, timeout_sec)

    def _settle_late_goal(self, name: str, sent) -> Reply:
        """수락 응답이 늦음 = 실행 여부를 모름. 늦게라도 수락되면 즉시 취소하고, 정지 확인 뒤에만 돌아간다."""
        self.node.get_logger().error(f"{name}: {self.goal_accept_sec}초 안에 수락 응답 없음 → 늦게 수락되면 즉시 취소")

        def cancel_if_accepted(future):
            handle = future.result()
            if handle is not None and handle.accepted:
                handle.cancel_goal_async()
        sent.add_done_callback(cancel_if_accepted)          # 여기서 포기한 뒤에 수락돼도 취소됨
        if not _wait(sent, self.cancel_confirm_sec):
            return Reply(False, STOP_UNCONFIRMED, NO_BACKEND_RESULT)   # 끝내 수락 여부를 모름 → 잠금
        handle = sent.result()
        if handle is None or not handle.accepted:
            return Reply(False, BACKEND_ERROR, NO_BACKEND_RESULT)   # 거절 = 움직이지 않음
        done = handle.get_result_async()
        if not _wait(done, self.cancel_confirm_sec):
            return Reply(False, STOP_UNCONFIRMED, NO_BACKEND_RESULT)
        return _timeout_reply(done.result().result)

    def _follow(self, name: str, handle, timeout_sec: float | None) -> Reply:
        """수락된 goal 의 결과를 기다림. 시간 초과·중단이면 취소 후 정지 확인까지."""
        done = handle.get_result_async()
        wake, canceled = threading.Event(), [False]
        done.add_done_callback(lambda _: wake.set())
        key = id(handle)
        with self._lock:
            self._active[key] = (handle, wake, canceled, name)
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
                return Reply(False, STOP_UNCONFIRMED, NO_BACKEND_RESULT)
            if timed_out:                       # 결과가 왔다고 정지 성공은 아님: 안전 코드는 그대로 (E 리뷰)
                return _timeout_reply(done.result().result)
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


def _keep_safety_code(code: str, otherwise: str) -> str:
    """취소 뒤 최종 결과의 코드가 Runner 잠금 대상(HALT_CODES)이면 그대로, 아니면 otherwise."""
    return code if code in HALT_CODES else otherwise


def _timeout_reply(result) -> Reply:
    """시간 초과로 취소한 뒤 백엔드가 준 최종 결과. 실행 코드는 지금처럼 TIMEOUT(안전 코드는 그대로)이고,
    백엔드 원래 코드·성공 여부는 결과 JSON backend_code·backend_success 로 따로 넘김 — 그 사이 정지 요청이 있었으면
    Runner 가 /runner/status halt.response_code 에 원래 코드를 씀 (#259 E 리뷰: CANCELED 가 TIMEOUT 으로 바뀌던 것)."""
    try:
        output = json.loads(result.output_json) if result.output_json else {}
    except ValueError:
        output = {}
    output = output if isinstance(output, dict) else {}
    output.update(backend_code=result.error_code or "", backend_success=bool(result.success))
    return Reply(False, _keep_safety_code(result.error_code, TIMEOUT), json.dumps(output))


def _wait(future, timeout_sec: float | None) -> bool:
    """future 가 끝나면 True, 제한 시간이 지나면 False. timeout_sec=None 이면 끝날 때까지 기다림."""
    finished = threading.Event()
    future.add_done_callback(lambda _: finished.set())
    return finished.wait(timeout_sec)
