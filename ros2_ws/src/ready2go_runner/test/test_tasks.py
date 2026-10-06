"""#17 P1 태스크 tasks/find_item.json 을 실제 경로(연결표·query_ontology·E 온톨로지)로 mock 실행.
완료 기준: mock 에서 성공·실패(파지 실패) 양쪽 모두 finally 까지 실행."""
import json
from pathlib import Path

import pytest

from ready2go_knowledge.core import ontology
from ready2go_runner.core.backend import INSPECT_SERVICE, SPEAK_ACTION, Reply, RosBackend
from ready2go_runner.core.interpreter import Runner

ROOT = Path(__file__).resolve().parents[4]
ONTOLOGY = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))
TASK = json.loads((ROOT / "tasks/find_item.json").read_text(encoding="utf-8"))


class MockRobot:
    """ROS 대신 call_action·call_service 를 받는 가짜 백엔드. fail: {동작: [코드, …]} 앞에서부터 하나씩."""

    def __init__(self, visible=True, fail=None):
        self.visible, self.fail = visible, {k: list(v) for k, v in (fail or {}).items()}
        self.sent: list[str] = []
        self.spoken: list[str] = []

    def call_action(self, name, params_json, timeout_sec):
        self.sent.append(name)
        action = name.rsplit("/", 1)[-1]
        if name == SPEAK_ACTION:
            self.spoken.append(json.loads(params_json)["text"])
        codes = self.fail.get(action)
        if codes:
            return Reply(False, codes.pop(0))
        return Reply(True)

    def call_service(self, name, region, search_target, timeout_sec):
        self.sent.append(name)
        if not self.visible:
            return Reply(True, "", json.dumps({"target_found": False, "target": None, "candidates": [], "visible_count": 0}))
        target = {"id": f"{search_target}#1", "class": search_target,
                  "pose": {"frame": region, "position": [0.1, 0.1, 0.0], "yaw": 0.0, "yaw_valid": True}, "top_z": 0.01}
        return Reply(True, "", json.dumps({"target_found": True, "target": target, "candidates": [], "visible_count": 1}))


def run(robot, inputs=None):
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    return runner, runner.run(TASK, inputs)


def statuses(result, *ids):
    return [next(s for s in result.steps if s["id"] == i)["status"] for i in ids]


def test_task_passes_validation_with_skills():
    from ready2go_runner.core.validation import check_task
    assert check_task(TASK, SCHEMA, ONTOLOGY["skills"]) == []


def test_success_delivers_item_and_cleans_up():
    robot = MockRobot()
    runner, result = run(robot)
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    assert robot.spoken == ["지우개를 찾아 올게요", "지우개를 앞쪽 트레이에 놓았어요"]
    assert robot.sent == [SPEAK_ACTION,
                          "/skills/move_to_named_pose", "/skills/drawer_control",           # s3 open_drawer
                          INSPECT_SERVICE,                                                   # s4 관측
                          INSPECT_SERVICE, "/skills/pick_object",                            # s5.1 pick
                          "/skills/place_object",                                            # s5.2 place
                          SPEAK_ACTION,
                          "/skills/drawer_control", "/skills/move_to_named_pose"]            # finally
    state = runner.state
    assert state["located_in"]["eraser"] == "handover_zone"
    assert state["gripper"]["robot"] == "empty" and state["open"]["drawer_top"] is False


def test_grasp_failure_still_runs_finally():
    robot = MockRobot(fail={"pick_object": ["GRASP_FAILED"]})
    runner, result = run(robot)
    assert (result.overall_status, result.error_code) == ("FAILED", "GRASP_FAILED")
    assert statuses(result, "f1", "f2") == ["SUCCESS", "SUCCESS"]                  # 서랍 닫기·홈
    assert robot.sent.count("/skills/pick_object") == 1                            # 움직인 실패는 재시도 안 함
    assert runner.state["located_in"]["eraser"] == "drawer_top"                    # effect 없음
    assert runner.state["open"]["drawer_top"] is False


def test_not_found_announces_and_cleans_up():
    robot = MockRobot(visible=False)
    runner, result = run(robot)
    assert result.overall_status == "COMPLETED"
    assert robot.spoken == ["지우개를 찾아 올게요", "지우개를 찾지 못했어요"]
    assert "/skills/pick_object" not in robot.sent
    assert statuses(result, "f1", "f2") == ["SUCCESS", "SUCCESS"]
    assert runner.state["open"]["drawer_top"] is False


def test_yaw_invalid_reinspects_once():
    robot = MockRobot(fail={"pick_object": ["YAW_INVALID"]})
    runner, result = run(robot)
    assert result.overall_status == "COMPLETED"
    assert robot.sent.count("/skills/pick_object") == 2
    assert next(s for s in result.steps if s["id"] == "s5.1")["attempts"] == 2


def test_drawer_stuck_skips_pick_and_still_goes_home():
    robot = MockRobot(fail={"drawer_control": ["DRAWER_STUCK"]})
    runner, result = run(robot)
    assert (result.overall_status, result.error_code) == ("FAILED", "DRAWER_STUCK")
    assert "/skills/pick_object" not in robot.sent
    f1 = next(s for s in result.steps if s["id"] == "f1")
    assert (f1["status"], f1["error_code"], f1.get("on_failure")) == ("FAILURE", "PRE_UNMET", "skip")   # 열리지 않음 → 닫기 생략
    assert statuses(result, "f2") == ["SUCCESS"]


@pytest.mark.parametrize("item, name", [("car_key", "차키"), ("lip_balm", "립밤")])
def test_other_items_by_input(item, name):
    robot = MockRobot()
    runner, result = run(robot, {"target": item})
    assert result.overall_status == "COMPLETED"
    assert robot.spoken[0].startswith(name)
    assert runner.state["located_in"][item] == "handover_zone"
