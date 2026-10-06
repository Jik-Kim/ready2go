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


# ---- #22 1차 점검용 tasks/p1_check_eraser.json (#17 E 요청: speak 없음) ----

from ready2go_runner.core.logstore import MemoryLogStore  # noqa: E402

CHECK = json.loads((ROOT / "tasks/p1_check_eraser.json").read_text(encoding="utf-8"))


def run_check(robot):
    store = MemoryLogStore()
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY, log_store=store)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(CHECK)
    return runner, result, store.read_run(result.run_id)


def test_check_task_is_valid_and_has_no_speak():
    from ready2go_runner.core.validation import check_task
    assert check_task(CHECK, SCHEMA, ONTOLOGY["skills"]) == []
    assert "speak" not in json.dumps(CHECK["sequence"] + CHECK["finally"])


def test_check_success_effect_and_full_log():
    robot = MockRobot()
    runner, result, saved = run_check(robot)
    assert result.overall_status == "COMPLETED"
    assert SPEAK_ACTION not in robot.sent                                   # 음성 서버 없이 실행
    state = runner.state
    assert (state["located_in"]["eraser"], state["gripper"]["robot"], state["open"]["drawer_top"]) == (
        "handover_zone", "empty", False)
    assert saved["run"]["overall_status"] == "COMPLETED"
    assert [s["id"] for s in saved["steps"]] == [s["id"] for s in result.steps]   # AC-LOG-01: 스텝 기록 누락 0
    assert all(s.get("status") for s in saved["steps"])


def test_check_grasp_failed_runs_finally_without_effect():
    robot = MockRobot(fail={"pick_object": ["GRASP_FAILED"]})
    runner, result, saved = run_check(robot)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "GRASP_FAILED", "s3.e2")
    assert statuses(result, "f1", "f2") == ["SUCCESS", "SUCCESS"]
    assert (runner.state["located_in"]["eraser"], runner.state["gripper"]["robot"]) == ("drawer_top", "empty")
    assert saved["run"]["error"] == {"code": "GRASP_FAILED"} and saved["run"]["failed_step"] == "s3.e2"


def test_check_place_failed_while_holding_is_not_recorded_as_closed():
    # E 요청: 놓기 실패로 물품을 쥔 상태 → close_drawer pre(빈 그리퍼) 불충족. "닫힘 완료"로 기록하지 않음
    robot = MockRobot(fail={"place_object": ["PLACE_FAILED"]})
    runner, result, _ = run_check(robot)
    assert (result.overall_status, result.error_code) == ("FAILED", "PLACE_FAILED")
    f1 = next(s for s in result.steps if s["id"] == "f1")
    assert (f1["status"], f1["error_code"], f1["on_failure"]) == ("FAILURE", "PRE_UNMET", "skip")
    assert "/skills/drawer_control" not in robot.sent[robot.sent.index("/skills/place_object"):]   # 닫기 동작 안 보냄
    assert runner.state["gripper"]["robot"] == "eraser" and runner.state["open"]["drawer_top"] is True
    assert statuses(result, "f2") == ["SUCCESS"]                       # 현재: 쥔 채 홈 이동 → B·C·E 확인 중


@pytest.mark.parametrize("code", ["ESTOP", "STOP_UNCONFIRMED", "STATE_UNKNOWN", "MOVE_UNCONFIRMED", "LOCKED"])
@pytest.mark.parametrize("where", ["drawer_control", "pick_object", "place_object"])
def test_check_safety_codes_abort_lock_and_send_no_motion(code, where):
    robot = MockRobot(fail={where: [code]})
    runner, result, saved = run_check(robot)
    assert (result.overall_status, result.error_code) == ("ABORTED", code)
    assert runner.halted
    after = robot.sent[robot.sent.index(f"/skills/{where}") + 1:]
    assert after == []                                                  # finally 의 닫기·홈 등 로봇 동작 없음
    assert statuses(result, "f1", "f2") == ["SKIPPED", "SKIPPED"]
    assert saved["run"]["overall_status"] == "ABORTED"
