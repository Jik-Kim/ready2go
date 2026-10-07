"""#17 P1 태스크(tasks/find_item.json, tasks/p1_demo_eraser.json)를 실제 경로(연결표·query_ontology·E 공통 온톨로지)로 mock 실행.
완료 기준: mock 에서 성공·실패(파지 실패) 양쪽 모두 finally 까지 실행.
PR #82 리뷰: 놓기 실패로 물품을 쥔 채면 finally 에서 로봇 동작(닫기·홈)을 보내지 않음."""
import copy
import json
from pathlib import Path

import pytest

from ready2go_knowledge.core import ontology
from ready2go_runner.core.backend import INSPECT_SERVICE, SPEAK_ACTION, Reply, RosBackend
from ready2go_runner.core.interpreter import Runner
from ready2go_runner.core.logstore import MemoryLogStore
from ready2go_runner.core.validation import check_task

ROOT = Path(__file__).resolve().parents[4]
ONTOLOGY = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))
TASK = json.loads((ROOT / "tasks/find_item.json").read_text(encoding="utf-8"))
CHECK = json.loads((ROOT / "tasks/p1_demo_eraser.json").read_text(encoding="utf-8"))
NUDGE_DY = -0.0417                       # mock 끌기: y 로 옮기는 거리 (B 계산 예: 0.2895 → 약 0.2478)
# E 공통 pick (#122): 탑뷰 → 촬영 → 끌기 → 탑뷰 → 다시 촬영 → 다시 본 좌표로 집기
PICK_SENT = ["/skills/move_to_named_pose", INSPECT_SERVICE, "/skills/nudge_object",
             "/skills/move_to_named_pose", INSPECT_SERVICE, "/skills/pick_object"]

# C 원본 공통 pick 호출열 (d8823de, #118의 s3v 추가 전)
PICK_SENT = ["/skills/move_to_named_pose", INSPECT_SERVICE, "/skills/nudge_object",
             "/skills/move_to_named_pose", INSPECT_SERVICE, "/skills/pick_object"]


class MockRobot:
    """ROS 대신 call_action·call_service 를 받는 가짜 백엔드. fail: {동작: [코드, …]} 앞에서부터 하나씩."""

    def __init__(self, visible=True, fail=None, nudge_output=None, seen_y=None):
        self.visible, self.fail = visible, {k: list(v) for k, v in (fail or {}).items()}
        self.seen_y = list(seen_y or [])                  # 촬영마다 보이는 y (끌기 뒤 실제 위치 시험). 비면 0.2895
        self.nudge_output = nudge_output                  # nudge 성공 응답을 바꿔 줌 (target_after 누락 시험)
        self.sent: list[str] = []
        self.params: dict[str, list] = {}
        self.spoken: list[str] = []

    def call_action(self, name, params_json, timeout_sec):
        self.sent.append(name)
        action = name.rsplit("/", 1)[-1]
        params = json.loads(params_json)
        self.params.setdefault(action, []).append(params)
        if name == SPEAK_ACTION:
            self.spoken.append(params["text"])
        codes = self.fail.get(action)
        code = codes.pop(0) if codes else None                # None = 그 회차는 성공
        if code:
            return Reply(False, code)
        if action == "nudge_object" and self.nudge_output is not None:
            return Reply(True, "", json.dumps(self.nudge_output))
        if action == "nudge_object":                      # B #83: 성공일 때만 target_after
            after = copy.deepcopy(params["target"])
            after["pose"]["position"][1] = round(after["pose"]["position"][1] + NUDGE_DY, 4)
            return Reply(True, "", json.dumps({"pushed": True, "target_after": after}))
        return Reply(True)

    def call_service(self, name, region, search_target, timeout_sec):
        self.sent.append(name)
        visible = self.visible.pop(0) if isinstance(self.visible, list) else self.visible   # 목록이면 촬영마다
        if not visible:
            return Reply(True, "", json.dumps({"target_found": False, "target": None, "candidates": [], "visible_count": 0}))
        y = self.seen_y.pop(0) if self.seen_y else 0.2895
        target = {"id": f"{search_target}#1", "class": search_target,
                  "pose": {"frame": region, "position": [0.1769, y, 0.0], "yaw": 0.0, "yaw_valid": True},
                  "top_z": 0.0115}
        return Reply(True, "", json.dumps({"target_found": True, "target": target, "candidates": [], "visible_count": 1}))

    def motion_after(self, name):
        """name 을 마지막으로 보낸 뒤 보낸 로봇 동작(/skills/*)."""
        last = len(self.sent) - 1 - self.sent[::-1].index(name)
        return [n for n in self.sent[last + 1:] if n.startswith("/skills/")]


def run(robot, task=TASK, onto=ONTOLOGY, inputs=None):
    store = MemoryLogStore()
    runner = Runner(None, schema=SCHEMA, ontology=onto, log_store=store)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, onto["world"])
    result = runner.run(task, inputs)
    return runner, result, store.read_run(result.run_id)


def step(result, step_id):
    return next(s for s in result.steps if s["id"] == step_id)


def statuses(result, *ids):
    return [step(result, i)["status"] for i in ids]


# ---- 정식 find_item.json ----

def test_task_passes_validation_with_skills():
    assert check_task(TASK, SCHEMA, ONTOLOGY["skills"]) == []


def test_success_delivers_item_and_cleans_up():
    robot = MockRobot()
    runner, result, _ = run(robot)
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    assert robot.spoken == ["지우개를 찾아 올게요", "지우개를 앞쪽 트레이에 놓았어요"]
    assert robot.sent == [SPEAK_ACTION,
                          "/skills/move_to_named_pose", "/skills/drawer_control",           # s3 open_drawer
                          "/skills/move_to_named_pose",                                      # s3v 탑뷰 (열기 끝은 홈)
                          INSPECT_SERVICE,                                                   # s4 관측
                          *PICK_SENT,                                                        # s5.1 pick (E #122)
                          "/skills/place_object",                                            # s5.2 place
                          SPEAK_ACTION,
                          "/skills/drawer_control", "/skills/move_to_named_pose"]            # finally 닫기·홈
    state = runner.state
    assert state["located_in"]["eraser"] == "handover_zone"
    assert state["gripper"]["robot"] == "empty" and state["open"]["drawer_top"] is False


def test_success_picks_at_reobserved_position():
    """E #17: 끌기 뒤 다시 촬영한 좌표가 실제 pick 입력 (예상 target_after 가 아님)."""
    robot = MockRobot(seen_y=[0.2895, 0.2895, 0.2531])    # s4 관측 / pick 안 첫 촬영 / 끌기 뒤 다시 촬영
    _, result, _ = run(robot)
    assert result.overall_status == "COMPLETED"
    assert robot.params["pick_object"][0]["target"]["pose"]["position"][1] == 0.2531
    assert step(result, "s5.1.e3")["output"]["target_after"]["pose"]["position"][1] == 0.2478   # 예상값은 기록만
    assert step(result, "s3v")["params"] == {"pose_name": "drawer_top_view", "drawer_id": "drawer_top"}


def test_top_view_failure_does_not_inspect_or_pick():
    """E #17: 첫 탑뷰 이동이 실패하면 관측·끌기·집기를 보내지 않고 finally (닫기·홈)."""
    robot = MockRobot(fail={"move_to_named_pose": [None, "NOT_REACHED"]})    # s3.e1 성공, s3v 실패
    runner, result, _ = run(robot)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "NOT_REACHED", "s3v")
    assert INSPECT_SERVICE not in robot.sent
    assert "/skills/nudge_object" not in robot.sent and "/skills/pick_object" not in robot.sent
    assert statuses(result, "f2", "f3.1") == ["SUCCESS", "SUCCESS"]
    assert runner.state["located_in"]["eraser"] == "drawer_top"


@pytest.mark.parametrize("visible, failed, nudged", [([True, False], "s5.1.e3", False),        # pick 안 첫 촬영
                                                     ([True, True, False], "s5.1.e6", True)])  # 끌기 뒤 다시 촬영
def test_reobserve_not_found_does_not_pick(visible, failed, nudged):
    robot = MockRobot(visible=visible)
    runner, result, _ = run(robot)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "VAR_NULL", failed)
    assert ("/skills/nudge_object" in robot.sent) is nudged and "/skills/pick_object" not in robot.sent
    assert statuses(result, "f2", "f3.1") == ["SUCCESS", "SUCCESS"]
    assert (runner.state["located_in"]["eraser"], runner.state["gripper"]["robot"]) == ("drawer_top", "empty")


def test_grasp_failure_still_runs_finally():
    robot = MockRobot(fail={"pick_object": ["GRASP_FAILED"]})
    runner, result, _ = run(robot)
    assert (result.overall_status, result.error_code) == ("FAILED", "GRASP_FAILED")
    assert statuses(result, "f2", "f3.1") == ["SUCCESS", "SUCCESS"]               # 서랍 닫기·홈
    assert robot.sent.count("/skills/pick_object") == 1                            # 움직인 실패는 재시도 안 함
    assert runner.state["located_in"]["eraser"] == "drawer_top"                    # effect 없음
    assert runner.state["open"]["drawer_top"] is False


def test_not_found_announces_and_cleans_up():
    robot = MockRobot(visible=False)
    runner, result, _ = run(robot)
    assert result.overall_status == "COMPLETED"
    assert robot.spoken == ["지우개를 찾아 올게요", "지우개를 찾지 못했어요"]
    assert "/skills/pick_object" not in robot.sent
    assert statuses(result, "f2", "f3.1") == ["SUCCESS", "SUCCESS"]
    assert runner.state["open"]["drawer_top"] is False


def test_yaw_invalid_after_reobserve_is_not_retried():
    """E #122: pick 안에서 끌기 뒤 다시 촬영하므로, 그 뒤 YAW_INVALID 는 팔이 움직인 뒤라 다시 보내지 않고 finally."""
    robot = MockRobot(fail={"pick_object": ["YAW_INVALID"]})
    runner, result, _ = run(robot)
    assert (result.overall_status, result.error_code) == ("FAILED", "YAW_INVALID")
    assert robot.sent.count("/skills/pick_object") == 1 and robot.sent.count("/skills/nudge_object") == 1
    assert statuses(result, "f2", "f3.1") == ["SUCCESS", "SUCCESS"]
    assert runner.state["located_in"]["eraser"] == "drawer_top"


def test_drawer_stuck_skips_pick_and_still_goes_home():
    robot = MockRobot(fail={"drawer_control": ["DRAWER_STUCK"]})
    runner, result, _ = run(robot)
    assert (result.overall_status, result.error_code) == ("FAILED", "DRAWER_STUCK")
    assert "/skills/pick_object" not in robot.sent
    f2 = step(result, "f2")
    assert (f2["status"], f2["error_code"], f2.get("on_failure")) == ("FAILURE", "PRE_UNMET", "skip")   # 열리지 않음 → 닫기 생략
    assert statuses(result, "f3.1") == ["SUCCESS"]                                 # 빈 그리퍼 → 홈


def test_place_failed_while_holding_sends_no_more_motion():
    # PR #82 리뷰 P1: 물품을 쥔 채 열린 서랍 부근에서 홈 이동 금지 → 정지·사람 복구
    robot = MockRobot(fail={"place_object": ["PLACE_FAILED"]})
    runner, result, _ = run(robot)
    assert (result.overall_status, result.error_code) == ("FAILED", "PLACE_FAILED")
    assert robot.motion_after("/skills/place_object") == []                       # 닫기·홈 모두 안 보냄
    assert step(result, "f2")["error_code"] == "PRE_UNMET"
    assert step(result, "f3")["branch"] == "else" and step(result, "f3.2")["status"] == "SUCCESS"
    assert result.blackboard["stopped_holding"].startswith("물품을 쥔 채 정지")
    assert runner.state["gripper"]["robot"] == "eraser"


@pytest.mark.parametrize("item, name", [("car_key", "차키"), ("lip_balm", "립밤")])
def test_other_items_by_input(item, name):
    robot = MockRobot()
    runner, result, _ = run(robot, inputs={"target": item})
    assert result.overall_status == "COMPLETED"
    assert robot.spoken[0].startswith(name)
    assert runner.state["located_in"][item] == "handover_zone"


# ---- 말 없는 예비 p1_demo_eraser.json (P1 기준은 위 find_item.json, E #17): 공통 pick(끌기 뒤 다시 촬영) ----

def run_check(robot):
    return run(robot, task=CHECK)


def test_check_task_is_valid_with_common_ontology_and_has_no_speak():
    assert check_task(CHECK, SCHEMA, ONTOLOGY["skills"]) == []
    assert "speak" not in json.dumps(CHECK["sequence"] + CHECK["finally"])
    assert CHECK["trigger"]["targets"] == ["eraser"]


def test_check_success_picks_at_reobserved_position():
    """D #118 P1: 끌기 뒤 탑뷰에서 다시 촬영한 좌표로 집는다 (끌기의 예상 위치 target_after 가 아님)."""
    robot = MockRobot(seen_y=[0.2895, 0.2531])            # 끌기 전 / 끌기 뒤 실제(예상 0.2478 과 다름)
    runner, result, saved = run_check(robot)
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    assert robot.sent == ["/skills/move_to_named_pose", "/skills/drawer_control",   # s2 open_drawer
                          *PICK_SENT,                                              # s3 pick
                          "/skills/place_object",                                  # s4 place
                          "/skills/drawer_control", "/skills/move_to_named_pose"]  # finally 닫기·홈
    assert SPEAK_ACTION not in robot.sent
    nudged, picked = robot.params["nudge_object"][0], robot.params["pick_object"][0]
    assert nudged["target"]["pose"]["position"][1] == 0.2895                        # 첫 촬영 좌표로 끌기
    assert picked["target"]["pose"]["position"][1] == 0.2531                        # 다시 본 좌표로 집기
    assert step(result, "s3.e3")["output"]["target_after"]["pose"]["position"][1] == 0.2478   # 예상값은 기록만
    assert picked["approach_offset"] == [0, 0, 0.1]
    assert [step(result, f"s3.e{i}")["params"]["pose_name"] for i in (1, 4)] == ["drawer_top_view"] * 2
    state = runner.state
    assert (state["located_in"]["eraser"], state["gripper"]["robot"], state["open"]["drawer_top"]) == (
        "handover_zone", "empty", False)
    assert [s["id"] for s in saved["steps"]] == [s["id"] for s in result.steps]       # AC-LOG-01: 스텝 기록 누락 0


@pytest.mark.parametrize("visible, failed, nudged", [([False], "s3.e3", False),          # 첫 촬영에서 못 찾음
                                                     ([True, False], "s3.e6", True)])    # 끌기 뒤 다시 촬영에서 못 찾음
def test_check_not_found_does_not_pick(visible, failed, nudged):
    """B 제안(#23): 다시 촬영에서 못 찾으면 집지 않고 실패. 집기 effect 없음, finally 로 닫기·홈."""
    robot = MockRobot(visible=visible)
    runner, result, _ = run_check(robot)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "VAR_NULL", failed)
    assert ("/skills/nudge_object" in robot.sent) is nudged and "/skills/pick_object" not in robot.sent
    assert (runner.state["located_in"]["eraser"], runner.state["gripper"]["robot"]) == ("drawer_top", "empty")
    assert statuses(result, "f2", "f3.1") == ["SUCCESS", "SUCCESS"]


def test_check_top_view_failure_does_not_inspect_or_nudge():
    robot = MockRobot(fail={"move_to_named_pose": [None, "NOT_REACHED"]})    # 1번째(s2.e1)는 성공, 2번째(s3.e1) 실패
    runner, result, _ = run_check(robot)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "NOT_REACHED", "s3.e1")
    assert INSPECT_SERVICE not in robot.sent and "/skills/nudge_object" not in robot.sent
    assert statuses(result, "f2", "f3.1") == ["SUCCESS", "SUCCESS"]        # 열린 서랍은 닫고 홈


def test_check_nudge_failure_does_not_pick():
    robot = MockRobot(fail={"nudge_object": ["NO_PUSH_ACCESS"]})
    runner, result, saved = run_check(robot)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "NO_PUSH_ACCESS", "s3.e3")
    assert "/skills/pick_object" not in robot.sent
    assert (runner.state["located_in"]["eraser"], runner.state["gripper"]["robot"]) == ("drawer_top", "empty")
    assert statuses(result, "f2", "f3.1") == ["SUCCESS", "SUCCESS"]
    assert step(result, "s3")["attempts"] == 1                              # 재시도 없음
    assert saved["run"]["error"] == {"code": "NO_PUSH_ACCESS"}


@pytest.mark.parametrize("code", ["GRASP_FAILED", "YAW_INVALID"])
def test_check_no_whole_skill_retry_after_nudge_even_if_task_asks(code):
    """#23 C 검증 요청: 끌기로 물체를 옮긴 뒤 pick 이 실패하면, 태스크에 retry 가 있어도 pick 전체
    (끌기 포함)를 다시 보내지 않는다. YAW_INVALID 처럼 그 동작 자체는 안 움직인 실패라도 앞에서 팔이 움직였으므로."""
    task = copy.deepcopy(CHECK)
    pick = next(s for s in task["sequence"] if s["id"] == "s3")
    assert pick["skill"] == "pick"
    pick.update(on_failure="retry", retry=2)
    robot = MockRobot(fail={"pick_object": [code, code, code]})
    runner, result, _ = run(robot, task=task)
    assert result.overall_status == "FAILED" and result.error_code == code
    assert robot.sent.count("/skills/nudge_object") == 1 and robot.sent.count("/skills/pick_object") == 1
    assert step(result, "s3")["attempts"] == 1 and step(result, "s3")["retry_stopped"] in (
        "MOTION_UNCERTAIN", "NOT_RETRYABLE")
    assert runner.state["located_in"]["eraser"] == "drawer_top"


def test_check_grasp_failed_runs_finally_without_effect():
    robot = MockRobot(fail={"pick_object": ["GRASP_FAILED"]})
    runner, result, saved = run_check(robot)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "GRASP_FAILED", "s3.e6")
    assert statuses(result, "f2", "f3.1") == ["SUCCESS", "SUCCESS"]
    assert (runner.state["located_in"]["eraser"], runner.state["gripper"]["robot"]) == ("drawer_top", "empty")
    assert saved["run"]["failed_step"] == "s3.e6"


def test_check_place_failed_while_holding_sends_no_more_motion():
    robot = MockRobot(fail={"place_object": ["PLACE_FAILED"]})
    runner, result, _ = run_check(robot)
    assert (result.overall_status, result.error_code) == ("FAILED", "PLACE_FAILED")
    assert robot.motion_after("/skills/place_object") == []
    assert step(result, "f2")["error_code"] == "PRE_UNMET"                          # 닫힘 완료로 기록 안 됨
    assert step(result, "f3")["branch"] == "else"
    assert runner.state["gripper"]["robot"] == "eraser" and runner.state["open"]["drawer_top"] is True


@pytest.mark.parametrize("code", ["ESTOP", "STOP_UNCONFIRMED", "STATE_UNKNOWN", "MOVE_UNCONFIRMED", "LOCKED"])
@pytest.mark.parametrize("where", ["drawer_control", "nudge_object", "pick_object", "place_object"])
def test_check_safety_codes_abort_lock_and_send_no_motion(code, where):
    robot = MockRobot(fail={where: [code]})
    runner, result, saved = run_check(robot)
    assert (result.overall_status, result.error_code) == ("ABORTED", code)
    assert runner.halted
    assert robot.motion_after(f"/skills/{where}") == []                 # finally 의 닫기·홈 등 로봇 동작 없음
    assert step(result, "f2")["status"] == "SKIPPED"
    assert saved["run"]["overall_status"] == "ABORTED"


# ---- #23·#107 실행 사이 상태: Runner 를 켜 둔 채 연속 시연 (AC-DEMO-01 3회 연속, P1 find_item.json) ----
def demo_runner(robot):
    """음성 모드처럼 Runner 하나를 켜 둔 채 여러 번 실행 (run() 은 실행마다 새 Runner 라 여기서 따로 만듦)."""
    store = MemoryLogStore()
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY, log_store=store)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    return runner, store


def test_without_reset_second_run_treats_tray_as_drawer():
    """초기화 없이 연속 실행: 1회차 끝 '지우개 = handover_zone' 을 기억 → 2회차가 트레이를 서랍 자리에 넣음 (10/07 발견)."""
    runner, _ = demo_runner(MockRobot())
    assert runner.run(TASK).overall_status == "COMPLETED"
    second = runner.run(TASK)
    assert step(second, "s1")["output"]["drawer_id"] == "handover_zone"
    assert (second.overall_status, step(second, "s3")["error_code"]) == ("FAILED", "PRE_UNMET")   # s3 open_drawer


def test_reset_between_runs_gives_three_consecutive_demos():
    """시연 사이 사람이 원위치 확인 → reset_state() (/runner/reset_state) → 3회 연속, 매번 위 서랍."""
    robot = MockRobot()
    runner, _ = demo_runner(robot)
    initial = runner.state
    results = []
    for _ in range(3):
        results.append(runner.run(TASK))
        runner.reset_state()
        assert runner.state == initial
    assert [r.overall_status for r in results] == ["COMPLETED"] * 3
    assert [step(r, "s1")["output"]["drawer_id"] for r in results] == ["drawer_top"] * 3
    assert all(p["drawer_id"] == "drawer_top" for p in robot.params["drawer_control"])


def test_failed_run_is_not_reset_by_itself_and_next_request_sends_no_motion():
    """#107 D P1: 놓기 실패로 지우개를 쥔 채 끝나면 Runner 가 스스로 되돌리지 않는다 → 다음 요청은 로봇 동작 0건."""
    robot = MockRobot(fail={"place_object": ["PLACE_FAILED"]})
    runner, _ = demo_runner(robot)
    first = runner.run(TASK)
    assert (first.overall_status, first.error_code) == ("FAILED", "PLACE_FAILED")
    holding = runner.state
    assert holding["gripper"]["robot"] == "eraser"
    sent = len(robot.sent)
    second = runner.run(TASK)
    assert second.overall_status == "FAILED" and runner.state == holding
    assert [n for n in robot.sent[sent:] if n.startswith("/skills/")] == []      # 서랍·이동·파지 동작 없음


def test_reset_does_not_clear_halt_lock():
    """초기화는 상태만 — 비상정지 잠김은 그대로라 다음 실행은 거절, 로봇 동작 없음 (자동 재개 없음)."""
    robot = MockRobot()
    runner, _ = demo_runner(robot)
    runner.run(TASK)
    runner.halt("ESTOP")
    runner.reset_state()
    sent = len(robot.sent)
    assert runner.halted and runner.run(TASK).overall_status == "ABORTED" and len(robot.sent) == sent
