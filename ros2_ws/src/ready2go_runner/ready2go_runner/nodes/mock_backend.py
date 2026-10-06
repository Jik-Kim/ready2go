"""mock 백엔드 노드 (BACKEND=mock) — 로봇·음성·비전 없이 Runner 를 ROS 위에서 끝까지 시험 (#10).

ICD(docs/interfaces.md) 와 같은 이름으로 답한다: /skills/<동작>(Skill 액션), /voice/speak(Skill 액션),
/vision/inspect_region(InspectRegion 서비스). B·E·A 의 실제 서버와 이름·형식이 같으므로
Runner 코드는 그대로 두고 백엔드만 바꿔 끼운다. 취소 요청을 받으면 멈추고 CANCELED 로 끝낸다 (실제 서버의 본보기).

파라미터
- duration_sec: 동작마다 걸리는 시간 (기본 0.5)
- fail: 실패 지정 "pick_object=GRASP_FAILED*1,drawer_control=DRAWER_STUCK" (core/mock_skills.py)
- not_visible: inspect_region 에서 못 찾을 물품 "car_key,eraser"
"""
from __future__ import annotations

import json
import time

import rclpy
from rclpy.action import ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from ready2go_interfaces.action import Skill
from ready2go_interfaces.srv import InspectRegion

from ..core.mock_skills import SKILL_ACTIONS, MockSkills, parse_failures

CANCELED = "CANCELED"
STEP_SEC = 0.05                                 # 취소 요청을 확인하는 간격


class MockBackendNode(Node):
    def __init__(self, prefix: str = "", **node_kwargs):
        super().__init__("mock_backend", **node_kwargs)
        self.duration = float(self.declare_parameter("duration_sec", 0.5).value)
        fail = self.declare_parameter("fail", "").value
        hidden = self.declare_parameter("not_visible", "").value
        self.skills = MockSkills(parse_failures(fail), {s.strip() for s in hidden.split(",") if s.strip()})
        group = ReentrantCallbackGroup()
        self._servers = [
            ActionServer(self, Skill, f"{prefix}/skills/{action}", self._executor_for(action),
                         callback_group=group, cancel_callback=lambda _: CancelResponse.ACCEPT)
            for action in SKILL_ACTIONS
        ]
        self._servers.append(ActionServer(self, Skill, f"{prefix}/voice/speak", self._executor_for("speak"),
                                          callback_group=group, cancel_callback=lambda _: CancelResponse.ACCEPT))
        self.create_service(InspectRegion, f"{prefix}/vision/inspect_region", self._inspect, callback_group=group)
        self.get_logger().info(f"mock 백엔드 준비: /skills/{{{','.join(SKILL_ACTIONS)}}}, /voice/speak, "
                               f"/vision/inspect_region (동작 {self.duration}s, 실패 {fail or '없음'}, "
                               f"못 찾음 {hidden or '없음'})")

    def _executor_for(self, action: str):
        def execute(goal):
            params = json.loads(goal.request.params_json or "{}")
            if action == "speak":
                self.get_logger().info(f"[speak] {params.get('text', '')}")
            else:
                self.get_logger().info(f"[{action}] {params}")
            goal.publish_feedback(Skill.Feedback(stage="mock"))
            waited = 0.0
            while waited < self.duration:               # 실제 로봇처럼 시간이 걸리고, 그동안 취소를 받음
                if goal.is_cancel_requested:
                    goal.canceled()
                    self.get_logger().warning(f"[{action}] 취소됨")
                    return Skill.Result(success=False, error_code=CANCELED)
                time.sleep(STEP_SEC)
                waited += STEP_SEC
            reply = self.skills.respond(action, params)
            if reply.success:
                goal.succeed()
            else:
                goal.abort()
                self.get_logger().warning(f"[{action}] 실패 지정: {reply.error_code}")
            return Skill.Result(success=reply.success, error_code=reply.error_code,
                                output_json="" if reply.output is None else json.dumps(reply.output,
                                                                                        ensure_ascii=False))
        return execute

    def _inspect(self, request, response):
        reply = self.skills.inspect(request.region, request.search_target)
        self.get_logger().info(f"[inspect_region] {request.region} / {request.search_target or '-'} → "
                               f"{reply.output.get('target_found') if reply.success else reply.error_code}")
        response.success, response.error_code = reply.success, reply.error_code
        response.result_json = json.dumps(reply.output, ensure_ascii=False) if reply.success else ""
        return response


def main():
    rclpy.init()
    node = MockBackendNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
