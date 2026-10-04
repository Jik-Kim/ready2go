"""mock 백엔드 응답 규칙 (ROS 비의존) — BACKEND=mock 에서 B·E·A 서버 대신 같은 이름으로 답한다 (#10).

로봇 없이 태스크의 정상·실패 경로를 시험하기 위한 것 (FR-PLN-01 "mock 환경에서 정상·실패 경로 확인").
반환값 모양은 docs/runner.md 7.1 표, 인식 결과는 contracts/examples/inspect_region_result.json 을 따른다.
실패 지정: "동작=코드" 는 매번, "동작=코드*N" 은 처음 N번만 실패 (예: "pick_object=GRASP_FAILED*1").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SKILL_ACTIONS = ("move_to_named_pose", "drawer_control", "pick_object", "place_object", "nudge_object")


@dataclass
class MockReply:
    success: bool
    error_code: str = ""
    output: Any = None


def parse_failures(text: str) -> dict[str, list]:
    """"pick_object=GRASP_FAILED*1,drawer_control=DRAWER_STUCK" → {동작: [코드, 남은 횟수(None=계속)]}."""
    failures = {}
    for entry in filter(None, (part.strip() for part in text.split(","))):
        action, _, rule = entry.partition("=")
        code, _, times = rule.partition("*")
        if not action or not code:
            raise ValueError(f"실패 지정 형식은 동작=코드 또는 동작=코드*N: {entry!r}")
        failures[action.strip()] = [code.strip(), int(times) if times else None]
    return failures


class MockSkills:
    def __init__(self, failures: dict[str, list] | None = None, not_visible: set[str] | None = None):
        self.failures = failures or {}
        self.not_visible = not_visible or set()     # 이 물품은 inspect_region 에서 못 찾음 (target_found=false)

    def _fail(self, action: str) -> str | None:
        rule = self.failures.get(action)
        if rule is None or rule[1] == 0:
            return None
        if rule[1] is not None:
            rule[1] -= 1
        return rule[0]

    def respond(self, action: str, params: dict) -> MockReply:
        code = self._fail(action)
        if code:
            return MockReply(False, code)
        return MockReply(True, output=_output(action, params))

    def inspect(self, region: str, search_target: str) -> MockReply:
        code = self._fail("inspect_region")
        if code:
            return MockReply(False, code)
        if not search_target or search_target in self.not_visible:
            return MockReply(True, output={"target_found": False, "target": None, "candidates": [],
                                           "visible_count": 0})
        target = {"id": f"{search_target}#1", "class": search_target,
                  "pose": {"frame": region, "position": [0.1, 0.1, 0.0], "yaw": 0.0, "yaw_valid": True},
                  "top_z": 0.02}
        return MockReply(True, output={"target_found": True, "target": target, "candidates": [],
                                       "visible_count": 1})


def _output(action: str, params: dict) -> Any:
    if action == "drawer_control":
        opened = params.get("state") == "open"
        return {"drawer_displacement": 0.2 if opened else 0.0, "close_confirmed": not opened}
    if action == "pick_object":
        object_id = str(params.get("object_id", ""))
        return {"object_id": object_id, "class": object_id.split("#")[0], "pick_pose_drawer_frame": None,
                "grasp_ok": True}
    if action == "place_object":
        return {"slot": params.get("location"), "placed_pose": None}
    if action == "nudge_object":
        return {"pushed": not params.get("check_only", False)}
    return None                                     # move_to_named_pose·speak 은 반환값 없음
