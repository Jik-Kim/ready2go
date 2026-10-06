"""원자 동작을 ROS 인터페이스로 보내는 백엔드 (ROS 비의존 부분) — docs/interfaces.md 5장, docs/runner.md 7.1.

Runner 의 execute(action, params, timeout_sec) 자리에 들어간다(#10). 동작마다 보낼 곳을 정하고(route),
params 를 JSON 문자열로 바꿔 보낸 뒤, 응답의 JSON 문자열을 파이썬 값으로 바꿔 ActionResult 로 돌려준다.
실제 ROS 호출(액션·서비스 클라이언트)은 adapters/ 가 call_action·call_service 로 넘겨준다.
같은 코드가 mock·real 백엔드 어느 쪽과도 동작한다 (보내는 이름·형식이 ICD 로 같으므로).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .interpreter import ActionResult
from .ontology_query import LOCAL_ACTIONS, local_action

ACTION = "action"                       # Skill 액션 (goal params_json / result success·error_code·output_json)
SERVICE = "service"                     # InspectRegion 서비스 (req region·search_target / res success·error_code·result_json)
LOCAL = "local"                         # ROS 없이 ros2-core 프로세스 안에서 처리 (ICD "ROS 인터페이스가 아닌 호출")

SKILL_PREFIX = "/skills/"               # 로봇 원자 동작 → B 백엔드 (real·sim·mock)
SPEAK_ACTION = "/voice/speak"           # TTS → voice (E)
INSPECT_SERVICE = "/vision/inspect_region"   # 인식 → vision (A)
BACKEND_ERROR = "BACKEND_ERROR"         # 응답 JSON 이 깨짐 등 백엔드 쪽 문제 (runner.md 7.1 에러 코드)


@dataclass(frozen=True)
class Route:
    kind: str                           # ACTION / SERVICE / LOCAL
    name: str                           # ROS 이름 (액션·서비스) 또는 LOCAL 동작 이름


@dataclass
class Reply:
    """Skill 액션 result 와 InspectRegion 응답의 공통 모양. payload_json = output_json 또는 result_json."""
    success: bool
    error_code: str = ""
    payload_json: str = ""


CallAction = Callable[[str, str, "float | None"], Reply]        # (액션 이름, params_json, timeout_sec)
CallService = Callable[[str, str, str, "float | None"], Reply]  # (서비스 이름, region, search_target, timeout_sec)


def route(action: str) -> Route:
    """동작 이름 → 보낼 곳. 목록에 없는 로봇 동작은 모두 /skills/<동작> (새 동작도 B 가 서버만 만들면 됨)."""
    if action == "speak":
        return Route(ACTION, SPEAK_ACTION)
    if action == "inspect_region":
        return Route(SERVICE, INSPECT_SERVICE)
    if action in LOCAL_ACTIONS:
        return Route(LOCAL, action)
    return Route(ACTION, SKILL_PREFIX + action)


def to_result(reply: Reply) -> ActionResult:
    """응답 → ActionResult. 실패면 error_code 그대로(빈 문자열이면 Runner 가 ACTION_FAILED), 성공이면 JSON 해석."""
    if not reply.success:
        return ActionResult(False, error_code=reply.error_code or None)
    if not reply.payload_json:
        return ActionResult(True)
    try:
        return ActionResult(True, json.loads(reply.payload_json))
    except json.JSONDecodeError:
        return ActionResult(False, error_code=BACKEND_ERROR)    # 성공이라도 결과를 읽을 수 없으면 쓰지 않음


class RosBackend:
    """Runner 의 execute. call_action·call_service 는 adapters 의 ROS 클라이언트(시험에서는 가짜)."""

    def __init__(self, call_action: CallAction, call_service: CallService,
                 state: Callable[[], dict], world: dict):
        self.call_action, self.call_service = call_action, call_service
        self.state = state                      # Runner 현재 상태를 돌려주는 함수 (query_ontology 용)
        self.world = world                      # 온톨로지 world (물품 이름 등)

    def __call__(self, action: str, params: dict, timeout_sec: float | None) -> ActionResult:
        target = route(action)
        if target.kind == LOCAL:
            return local_action(action, params, self.state(), self.world)
        if target.kind == SERVICE:
            return to_result(self.call_service(target.name, _text(params.get("region")),
                                               _text(params.get("search_target")), timeout_sec))
        return to_result(self.call_action(target.name, json.dumps(params, ensure_ascii=False), timeout_sec))


def _text(value: Any) -> str:
    return "" if value is None else str(value)
