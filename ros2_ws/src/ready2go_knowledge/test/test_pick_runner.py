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

    def __init__(self, pushed=True, failure=None, null_scan=None, absent_scan=None,
                 wall_first=False, stop_at=None, failure_output=None):
        self.pushed = pushed
        self.wall_first = wall_first
        self.stop_at = stop_at
        self.failure_output = failure_output
        self.picks = 0
        self.failure = failure             # (nudge / pick / pick2 / post_nudge_view / scan2 / scan3, code)
        self.null_scan = null_scan
        self.absent_scan = absent_scan
        self.scans = 0
        self.nudged = False
        self.calls = []
        self.states_before_pick = []
        self.runner = None
        self.task_seen = self.target(0.3100)
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
            self.picks += 1
            self.states_before_pick.append(copy.deepcopy(self.runner.state))
            if self.wall_first and self.picks == 1:
                return Reply(False, "WALL_TOO_CLOSE")
            if self.picks == 2:
                stage = "pick2"
        if self.failure and self.failure[0] == stage:
            return Reply(False, self.failure[1], json.dumps(self.failure_output) if self.failure_output else "")
        if action == "nudge_object":
            self.nudged = True
            if self.stop_at == "nudge":
                self.runner.halt("ESTOP")
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
        target = {1: self.task_seen, 2: self.initial, 3: self.observed}.get(self.scans, self.initial)
        if self.stop_at == f"scan{self.scans}":
            self.runner.halt("ESTOP")
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


def test_pick_first_uses_new_scan_without_unconditional_nudge_or_second_look():
    stub = ObservationStub()
    runner, result = run(stub)
    assert result.overall_status == "COMPLETED"
    assert stub.scans == 2  # 태스크 1회 + skill 1회; caller scan 존재만으로 재사용하지 않음
    assert not calls(stub, "nudge_object")
    assert calls(stub, "pick_object")[0]["target"] == stub.initial != stub.task_seen
    assert calls(stub, "pick_object")[0]["scan"] == record(result, "s5.1.e2")["output"]
    assert record(result, "s5.1.e3")["option"] == 1
    assert record(result, "s5.1.e1")["same_pose"] is True  # C 자세 중복 억제; 관측 유효성 증거 아님
    assert record(result, "s5.1")["state_diff"] == {
        "gripper.robot": ["empty", "eraser"], "located_in.eraser": ["drawer_top", "gripper"]}
    assert runner.state["located_in"]["eraser"] == "handover_zone"


@pytest.mark.parametrize("pushed", [False, True])
def test_wall_only_nudges_once_then_uses_new_target_and_whole_scan(pushed):
    stub = ObservationStub(pushed=pushed, wall_first=True)
    runner, result = run(stub)
    assert result.overall_status == "COMPLETED"
    assert [s["action"] for s in result.steps if s.get("parent") == "s5.1"] == [
        "move_to_named_pose", "inspect_region", "fallback", "pick_object", "nudge_object",
        "move_to_named_pose", "inspect_region", "pick_object"]
    assert record(result, "s5.1.e3.o1.1")["error_code"] == "WALL_TOO_CLOSE"
    assert record(result, "s5.1.e3")["option"] == 2
    assert stub.scans == 3
    assert calls(stub, "nudge_object") == [{"target": stub.initial, "drawer_id": "drawer_top",
                                            "scan": record(result, "s5.1.e2")["output"]}]
    first, second = calls(stub, "pick_object")
    assert first["target"] == first["scan"]["target"] == stub.initial
    assert second == {"target": stub.observed, "scan": record(result, "s5.1.e3.o2.3")["output"],
                      "approach_offset": [0, 0, 0.1]}
    assert second["target"] == second["scan"]["target"] != stub.predicted
    assert record(result, "s5.1.e3.o2.1")["output"]["pushed"] is pushed
    assert all(s["gripper"]["robot"] == "empty" for s in stub.states_before_pick)
    assert record(result, "s5.1")["state_diff"]["gripper.robot"] == ["empty", "eraser"]
    assert runner.state["gripper"]["robot"] == "empty"


@pytest.mark.parametrize("code", ["YAW_INVALID", "NEIGHBOR_TOO_CLOSE", "NOT_ON_FLOOR", "BAD_PARAMS",
                                  "GRASP_FAILED", "TIMEOUT"])
def test_other_pick_refusals_never_nudge_or_repick(code):
    stub = ObservationStub(failure=("pick", code))
    runner, result = run(stub)
    assert (result.overall_status, result.error_code) == ("FAILED", code)
    assert len(calls(stub, "pick_object")) == 1 and not calls(stub, "nudge_object")
    assert record(result, "s5.1.e3")["fallback_stopped"] in ("NOT_IN_NEXT_ON", "TIMEOUT", "MOTION_UNCERTAIN")
    assert "state_diff" not in record(result, "s5.1")
    assert runner.state["gripper"]["robot"] == "empty"


@pytest.mark.parametrize("stage,code,failed_child", [
    ("scan2", "DEPTH_INVALID", "e2"),
    ("nudge", "NO_PUSH_ACCESS", "e3.o2.1"),
    ("nudge", "PUSH_BLOCKED", "e3.o2.1"),
    ("post_nudge_view", "POSE_NOT_TAUGHT", "e3.o2.2"),
    ("scan3", "RESULT_INVALID", "e3.o2.3"),
    ("pick2", "WALL_TOO_CLOSE", "e3.o2.4"),
])
def test_fallback_failure_stops_without_effect_or_more_pick(stage, code, failed_child):
    stub = ObservationStub(wall_first=True, failure=(stage, code))
    runner, result = run(stub)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", code, f"s5.1.{failed_child}")
    assert record(result, "s5.1")["attempts"] == 1
    assert "state_diff" not in record(result, "s5.1")
    assert runner.state["gripper"]["robot"] == "empty"
    assert len(calls(stub, "pick_object")) == (0 if stage == "scan2" else 2 if stage == "pick2" else 1)
    assert len(calls(stub, "nudge_object")) == (0 if stage == "scan2" else 1)
    assert not calls(stub, "place_object")


@pytest.mark.parametrize("scan", [2, 3])
@pytest.mark.parametrize("absent", [False, True])
def test_null_or_missed_observation_blocks_next_pick(scan, absent):
    stub = ObservationStub(wall_first=True, **{("absent_scan" if absent else "null_scan"): scan})
    runner, result = run(stub)
    assert (result.overall_status, result.error_code) == ("FAILED", "VAR_NULL")
    assert result.failed_step == ("s5.1.e3.o1.1" if scan == 2 else "s5.1.e3.o2.4")
    assert len(calls(stub, "pick_object")) == (0 if scan == 2 else 1)
    assert len(calls(stub, "nudge_object")) == (0 if scan == 2 else 1)
    assert "state_diff" not in record(result, "s5.1")
    assert runner.state["located_in"]["eraser"] == "drawer_top"


def test_initial_task_miss_keeps_existing_notice_branch_without_pick():
    stub = ObservationStub(absent_scan=1)
    runner, result = run(stub)
    assert result.overall_status == "COMPLETED"
    assert stub.scans == 1
    assert not calls(stub, "nudge_object") and not calls(stub, "pick_object")
    assert runner.state["located_in"]["eraser"] == "drawer_top"


@pytest.mark.parametrize("stage", ["pick", "nudge", "scan3"])
@pytest.mark.parametrize("code", ["ESTOP", "LOCKED"])
def test_abort_does_not_send_later_pick_or_finally_motion(stage, code):
    stub = ObservationStub(failure=(stage, code), wall_first=stage != "pick")
    runner, result = run(stub)
    assert (result.overall_status, result.error_code) == ("ABORTED", code)
    trigger = {"pick": "pick_object", "nudge": "nudge_object", "scan3": "inspect_region"}[stage]
    index = max(i for i, (name, _) in enumerate(stub.calls) if name == trigger)
    assert not any(name in {"move_to_named_pose", "drawer_control", "pick_object", "place_object"}
                   for name, _ in stub.calls[index + 1:])
    assert "state_diff" not in record(result, "s5.1")
    assert runner.state["gripper"]["robot"] == "empty"


@pytest.mark.parametrize("stop_at", ["nudge", "scan3"])
def test_explicit_stop_after_success_prevents_remaining_motion(stop_at):
    stub = ObservationStub(wall_first=True, stop_at=stop_at)
    _, result = run(stub)
    assert result.overall_status == "ABORTED"
    assert len(calls(stub, "pick_object")) == 1
    assert "state_diff" not in record(result, "s5.1")


def test_uncertain_hand_even_on_wall_code_never_enters_nudge():
    stub = ObservationStub(failure=("pick", "WALL_TOO_CLOSE"), failure_output={"hand": "unknown"})
    _, result = run(stub)
    assert result.overall_status == "ABORTED"
    assert not calls(stub, "nudge_object") and len(calls(stub, "pick_object")) == 1
    assert "state_diff" not in record(result, "s5.1")


def test_common_card_completes_formal_unpacking_with_one_direct_pick_view(monkeypatch):
    """C 기존 SceneRobot/MockSkills만 재사용; 카드/태스크/Runner를 대체하지 않습니다."""
    monkeypatch.syspath_prepend(str(ROOT / "ros2_ws/src/ready2go_runner/test"))
    from test_unpack_task import run as run_unpack
    runner, robot, result = run_unpack("occluded_top", "toy_wrench")
    assert result.overall_status == "COMPLETED"
    assert robot.picked() == ["car_key", "caramel_box", "toy_wrench", "caramel_box"]
    assert robot.placed() == ["aside_1", "aside_2", "handover_zone", "origin"]
    view = [s for s in result.steps if s.get("parent") == "s8.t1" and s["action"] == "move_to_named_pose"]
    assert [s.get("same_pose", False) for s in view] == [True]
    assert robot.skills.scene.delivered == ["toy_wrench"] and robot.skills.scene.held is None
    assert robot.skills.scene.objects["caramel_box"]["xy"][1] == 0.14
    assert robot.skills.scene.objects["car_key"]["xy"][1] == 0.045  # aside ≠ 원위치 복구
    assert runner.state["located_in"]["toy_wrench"] == "handover_zone"
    assert runner.state["open"]["drawer_top"] is False
    assert result.blackboard["restore_stack"] == [] and result.blackboard["holding"] is False
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})
