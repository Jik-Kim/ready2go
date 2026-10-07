"""공통 pick + 정식 find_item + Runner의 ROS 비의존 연결 검사.

실물 대신 좌표를 바꾸는 스텁으로 재관측 값과 이동량 기반 예상값을 구분합니다.
실제 비전 정확도·B 공간 판단이나 로봇 이동 성공의 증빙은 아닙니다.
"""
import copy
import json
from pathlib import Path

import pytest

from ready2go_knowledge.core import ontology
from ready2go_runner.core.backend import Reply, RosBackend
from ready2go_runner.core.interpreter import Runner
from ready2go_runner.core.validation import check_task


ROOT = Path(__file__).resolve().parents[4]
TASK = json.loads((ROOT / "tasks/find_item.json").read_text())
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text())


class ObservationStub:
    """ROS 입출력만 치환합니다. query/state/effect/retry/null 검사는 실제 Runner입니다."""

    def __init__(self, pushed=True, failure=None, null_scan=None, absent_scan=None):
        self.pushed = pushed
        self.failure = failure             # ("nudge" / "pick" / "post_nudge_view" / "scan2" / "scan3", code)
        self.null_scan = null_scan
        self.absent_scan = absent_scan
        self.scans = 0
        self.nudged = False
        self.calls = []
        self.states_before_pick = []
        self.runner = None
        self.initial = self.target(0.2895)
        self.predicted = self.target(0.2478)
        self.observed = self.target(0.2391)  # 모의 새 관측이며 예상값과 의도적으로 다릅니다.

    @staticmethod
    def target(y):
        return {"id": "eraser#1", "class": "eraser",
                "pose": {"frame": "drawer_top", "position": [0.1769, y, 0.0],
                         "yaw": 0.0, "yaw_valid": True}, "top_z": 0.0115}

    def call_action(self, name, params_json, timeout):
        action = name.rsplit("/", 1)[-1]
        params = json.loads(params_json)
        self.calls.append((action, params))
        stage = {"nudge_object": "nudge", "pick_object": "pick"}.get(action)
        if action == "move_to_named_pose" and params.get("pose_name") == "drawer_top_view" and self.nudged:
            stage = "post_nudge_view"
            self.nudged = False
        if action == "pick_object":
            self.states_before_pick.append(copy.deepcopy(self.runner.state))
        if self.failure and self.failure[0] == stage:
            return Reply(False, self.failure[1])
        if action == "nudge_object":
            self.nudged = True
            return Reply(True, payload_json=json.dumps({
                "pushed": self.pushed,
                "target_after": self.predicted if self.pushed else self.initial}))
        return Reply(True)

    def call_service(self, name, region, search_target, timeout):
        self.scans += 1
        self.calls.append(("inspect_region", {"region": region, "search_target": search_target}))
        if self.failure and self.failure[0] == f"scan{self.scans}":
            return Reply(False, self.failure[1])
        absent = self.scans == self.absent_scan
        target = self.observed if self.scans == 3 else self.initial
        if absent or self.scans == self.null_scan:
            target = None
        return Reply(True, payload_json=json.dumps({
            "target_found": not absent, "target": target,
            "candidates": [], "visible_count": 0 if absent else 1}))


def run(stub):
    onto = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")
    assert check_task(TASK, SCHEMA, onto["skills"]) == []
    runner = Runner(None, schema=SCHEMA, ontology=onto)
    stub.runner = runner
    runner.execute = RosBackend(stub.call_action, stub.call_service,
                                lambda: runner.state, onto["world"])
    result = runner.run(TASK)
    return runner, result


def record(result, step_id):
    return next(step for step in result.steps if step["id"] == step_id)


def calls(stub, action):
    return [params for name, params in stub.calls if name == action]


@pytest.mark.parametrize("pushed", [False, True])
def test_common_pick_uses_new_observation_and_applies_effect_only_after_success(pushed):
    stub = ObservationStub(pushed=pushed)
    runner, result = run(stub)
    assert result.overall_status == "COMPLETED"
    expanded = [step for step in result.steps if step.get("parent") == "s5.1"]
    assert [step["action"] for step in expanded] == [
        "move_to_named_pose", "inspect_region", "nudge_object",
        "move_to_named_pose", "inspect_region", "pick_object"]
    assert all(step["status"] == "SUCCESS" for step in expanded)
    assert [step["params"] for step in (expanded[0], expanded[3])] == [
        {"pose_name": "drawer_top_view", "drawer_id": "drawer_top"}] * 2
    assert stub.scans == 3  # 태스크 최초 관측 + pick 최초/재관측
    assert calls(stub, "nudge_object") == [{"target": stub.initial, "drawer_id": "drawer_top"}]
    assert calls(stub, "pick_object") == [{"target": stub.observed, "approach_offset": [0, 0, 0.1]}]
    assert stub.observed != stub.predicted and stub.observed != stub.initial
    assert record(result, "s5.1.e2")["output"]["target"] == stub.initial
    assert record(result, "s5.1.e5")["output"]["target"] == stub.observed
    assert record(result, "s5.1.e6")["params"]["target"] == stub.observed
    assert record(result, "s5.1.e2")["output"] != record(result, "s5.1.e5")["output"]
    assert record(result, "s5.1.e3")["output"]["pushed"] is pushed
    assert stub.states_before_pick[0]["gripper"]["robot"] == "empty"
    assert stub.states_before_pick[0]["located_in"]["eraser"] == "drawer_top"
    assert record(result, "s5.1")["state_diff"] == {
        "gripper.robot": ["empty", "eraser"], "located_in.eraser": ["drawer_top", "gripper"]}
    assert runner.state["located_in"]["eraser"] == "handover_zone"
    assert runner.state["gripper"]["robot"] == "empty"


@pytest.mark.parametrize("stage,code,failed_child", [
    ("scan2", "DEPTH_INVALID", "e2"),
    ("nudge", "NO_PUSH_ACCESS", "e3"),
    ("nudge", "NO_OBJECT_CONTACT", "e3"),
    ("nudge", "PUSH_BLOCKED", "e3"),
    ("nudge", "YAW_INVALID", "e3"),
    ("post_nudge_view", "POSE_NOT_TAUGHT", "e4"),
    ("post_nudge_view", "MOVE_REJECTED", "e4"),
    ("scan3", "RESULT_INVALID", "e5"),
    ("pick", "GRASP_FAILED", "e6"),
    ("pick", "WALL_TOO_CLOSE", "e6"),
    ("pick", "YAW_INVALID", "e6"),
])
def test_failures_propagate_without_effect_or_retry_after_motion(stage, code, failed_child):
    stub = ObservationStub(failure=(stage, code))
    runner, result = run(stub)
    assert (result.overall_status, result.error_code, result.failed_step) == (
        "FAILED", code, f"s5.1.{failed_child}")
    parent = record(result, "s5.1")
    assert parent["attempts"] == 1 and parent["retry_stopped"] == "MOTION_UNCERTAIN"
    assert "state_diff" not in parent
    assert runner.state["gripper"]["robot"] == "empty"
    assert runner.state["located_in"]["eraser"] == "drawer_top"
    assert len(calls(stub, "pick_object")) == (1 if stage == "pick" else 0)
    assert len(calls(stub, "nudge_object")) <= 1
    assert not calls(stub, "place_object")


@pytest.mark.parametrize("scan", [2, 3])
@pytest.mark.parametrize("absent", [False, True])
def test_null_or_missed_observation_blocks_next_motion(scan, absent):
    stub = ObservationStub(**{("absent_scan" if absent else "null_scan"): scan})
    runner, result = run(stub)
    assert (result.overall_status, result.error_code) == ("FAILED", "VAR_NULL")
    assert result.failed_step == ("s5.1.e3" if scan == 2 else "s5.1.e6")
    assert len(calls(stub, "nudge_object")) == (0 if scan == 2 else 1)
    assert not calls(stub, "pick_object")
    assert "state_diff" not in record(result, "s5.1")
    assert record(result, "s5.1")["attempts"] == 1
    assert runner.state["located_in"]["eraser"] == "drawer_top"


def test_initial_task_miss_keeps_existing_notice_branch_without_pick():
    stub = ObservationStub(absent_scan=1)
    runner, result = run(stub)
    assert result.overall_status == "COMPLETED"
    assert stub.scans == 1
    assert not calls(stub, "nudge_object") and not calls(stub, "pick_object")
    assert runner.state["located_in"]["eraser"] == "drawer_top"


@pytest.mark.parametrize("code", ["ESTOP", "LOCKED"])
def test_abort_does_not_send_finally_robot_motion(code):
    stub = ObservationStub(failure=("nudge", code))
    runner, result = run(stub)
    assert (result.overall_status, result.error_code) == ("ABORTED", code)
    index = next(i for i, (name, _) in enumerate(stub.calls) if name == "nudge_object")
    assert not any(name in {"move_to_named_pose", "drawer_control", "pick_object", "place_object"}
                   for name, _ in stub.calls[index + 1:])
    assert "state_diff" not in record(result, "s5.1")
    assert runner.state["gripper"]["robot"] == "empty"
