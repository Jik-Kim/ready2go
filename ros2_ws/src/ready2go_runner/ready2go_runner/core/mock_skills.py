"""mock 백엔드 응답 규칙 (ROS 비의존) — BACKEND=mock 에서 B·E·A 서버 대신 같은 이름으로 답한다 (#10).

로봇 없이 태스크의 정상·실패 경로를 시험하기 위한 것 (FR-PLN-01 "mock 환경에서 정상·실패 경로 확인").
반환값 모양은 docs/runner.md 7.1 표, 인식 결과는 contracts/examples/inspect_region_result.json 을 따른다.
실패 지정: "동작=코드" 는 매번, "동작=코드*N" 은 처음 N번만 실패 (예: "pick_object=GRASP_FAILED*1").
끌기(nudge) 성공 뒤 다시 인식하면 끌린 자리가 보이고(실물처럼), 집기 성공하면 처음 자리로 돌아간다(다음 회차).
scene 을 주면 여러 물체가 겹친 장면(core/mock_scene.py)으로 인식·집기·놓기·끌기를 답한다 (Unpacking 시험).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from .mock_scene import MockScene

SKILL_ACTIONS = ("move_to_named_pose", "drawer_control", "pick_object", "place_object", "nudge_object")
MOCK_NUDGE_DY = -0.04                   # mock 끌기: 서랍 옆(y)으로 옮기는 거리 (m). 실물 값은 B 계산 (10/07 PC2 40.1 mm)
MOCK_POSITION = [0.025, 0.292, 0.0]     # mock 인식 위치 (m, 서랍 기준) — P1 벽 배치 (10/07 PC2 실측 25, 292 mm)


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
    def __init__(self, failures: dict[str, list] | None = None, not_visible: set[str] | None = None,
                 scene: MockScene | None = None):
        self.failures = failures or {}
        self.scene = scene                          # 여러 물체 장면 (없으면 물체 1개 — P1 지우개)
        self.not_visible = not_visible or set()     # 이 물품은 inspect_region 에서 못 찾음 (target_found=false)
        self.moved: dict[str, dict] = {}            # 끌기로 옮겨진 물품 → 새 pose (다시 인식할 때 보임)

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
        if self.scene is not None and action in ("pick_object", "place_object", "nudge_object"):
            ok, code, output = getattr(self.scene, {"pick_object": "pick", "place_object": "place",
                                                    "nudge_object": "nudge"}[action])(params)
            return MockReply(ok, code, output)
        output = _output(action, params)
        target = params.get("target") if isinstance(params.get("target"), dict) else {}
        name = target.get("class") or str(target.get("id", "")).split("#")[0]
        if action == "nudge_object" and output.get("pushed") and name:
            self.moved[name] = output["target_after"]["pose"]
        elif action == "pick_object" and name:
            self.moved.pop(name, None)              # 집었으면 다음 회차는 처음 자리 (사람이 원위치)
        return MockReply(True, output=output)

    def inspect(self, region: str, search_target: str) -> MockReply:
        code = self._fail("inspect_region")
        if code:
            return MockReply(False, code)
        if self.scene is not None:
            return MockReply(True, output=self.scene.inspect(region, search_target))
        if not search_target or search_target in self.not_visible:
            return MockReply(True, output={"target_found": False, "target": None, "candidates": [],
                                           "visible_count": 0})
        pose = copy.deepcopy(self.moved.get(search_target)) or {
            "frame": region, "position": list(MOCK_POSITION), "yaw": 0.0, "yaw_valid": True}
        target = {"id": f"{search_target}#1", "class": search_target, "pose": pose, "top_z": 0.013}
        return MockReply(True, output={"target_found": True, "target": target, "candidates": [],
                                       "visible_count": 1})


def _output(action: str, params: dict) -> Any:
    if action == "drawer_control":
        opened = params.get("state") == "open"
        return {"drawer_displacement": 0.2 if opened else 0.0, "close_confirmed": not opened}
    if action == "pick_object":      # 서랍: target 통째로(PR #70), 트레이: object_id
        target = params.get("target") if isinstance(params.get("target"), dict) else {}
        object_id = str(target.get("id") or params.get("object_id", ""))
        return {"object_id": object_id, "class": target.get("class") or object_id.split("#")[0],
                "pick_pose_drawer_frame": None, "grasp_ok": True}
    if action == "place_object":
        return {"slot": params.get("location"), "placed_pose": None}
    if action == "nudge_object":      # B #83: target_after 는 성공일 때만, 끌지 않으면 위치 그대로
        target = params.get("target") if isinstance(params.get("target"), dict) else None
        if params.get("check_only") or target is None:
            return {"pushed": False, "push_vector_m": [0.0, 0.0], "target_after": target}
        after = copy.deepcopy(target)
        position = (after.get("pose") or {}).get("position")
        if isinstance(position, list) and len(position) > 1:
            position[1] = round(position[1] + MOCK_NUDGE_DY, 4)
        return {"pushed": True, "push_vector_m": [0.0, MOCK_NUDGE_DY], "target_after": after}
    return None                                     # move_to_named_pose·speak 은 반환값 없음
