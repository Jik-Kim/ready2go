"""#150 FR-PLN-02 자동 스킬 플래너: 온톨로지 pre·effect 만으로 목표 → 최단 스킬 순서 (docs/planner.md 7.7)."""
import copy
import json
from pathlib import Path

import pytest

from ready2go_knowledge.core import ontology
from ready2go_runner.core import planner as pl
from ready2go_runner.core.backend import RosBackend
from ready2go_runner.core.interpreter import Runner
from ready2go_runner.core.logstore import MemoryLogStore
from ready2go_runner.core.validation import check_task

from test_tasks import MockRobot  # noqa: E402  (mock 로봇: 실제 연결표·RosBackend 경로)

ROOT = Path(__file__).resolve().parents[4]
ONTO = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))


def state(**located):
    s = copy.deepcopy(ONTO["state"])
    s["located_in"].update(located)
    return s


def goal(subject, value, predicate="located_in"):
    return {"predicate": predicate, "subject": subject, "value": value}


def labels(result):
    return [s.label() for s in result.steps]


# ---- 계획 ----

def test_planner_md_example_lip_balm_from_tray_into_bottom_drawer():
    """docs/planner.md 7.7 예: 립밤은 전달 트레이, 아래 서랍 닫힘, 그리퍼 빔 → 열기 → 집기 → 놓기 → 닫기."""
    r = pl.plan(state(lip_balm="handover_zone"), ONTO, [goal("lip_balm", "drawer_bottom")])
    assert r.status == pl.PLANNED
    assert labels(r) == ["open_drawer(drawer_bottom)", "pick(lip_balm, handover_zone)",
                         "place(lip_balm, drawer_bottom)", "close_drawer(drawer_bottom)"]
    reasons = [s.reasons for s in r.steps]
    assert reasons[0] == ["3번 place 의 조건 open.drawer_bottom = true"]           # place 가 열린 서랍을 요구
    assert reasons[1] == ['3번 place 의 조건 gripper.robot = "lip_balm"']
    assert 'located_in.lip_balm = "drawer_bottom"' in reasons[2][-1]
    assert reasons[3] == ["자동 목표(연 서랍 닫기) open.drawer_bottom = false"]


def test_p1_delivery_is_derived_not_hardcoded():
    """P1 find_item 흐름(열기 → 집기 → 놓기 → 닫기)을 목표 하나에서 도출."""
    r = pl.plan(state(), ONTO, [goal("eraser", "handover_zone")])
    assert labels(r) == ["open_drawer(drawer_top)", "pick(eraser, drawer_top)",
                         "place(eraser, handover_zone)", "close_drawer(drawer_top)"]


def test_move_between_drawers_opens_target_first_and_closes_both():
    """쥔 채로는 서랍을 못 열므로(open_drawer 조건 gripper empty) 놓을 서랍을 집기 전에 연다."""
    r = pl.plan(state(), ONTO, [goal("eraser", "drawer_bottom")])
    names = labels(r)
    assert names.index("open_drawer(drawer_bottom)") < names.index("pick(eraser, drawer_top)")
    assert {"close_drawer(drawer_top)", "close_drawer(drawer_bottom)"} <= set(names) and len(names) == 6


def test_explicit_open_goal_overrides_auto_close():
    r = pl.plan(state(), ONTO, [goal("drawer_top", True, "open")])
    assert labels(r) == ["open_drawer(drawer_top)"]                                  # 열어 두라는 목표 → 닫지 않음


def test_already_satisfied_returns_zero_steps_with_reason():
    r = pl.plan(state(), ONTO, [goal("eraser", "drawer_top")])
    assert (r.status, r.steps) == (pl.SATISFIED, []) and "eraser" in r.reason


@pytest.mark.parametrize("goals, words", [
    ([goal("phone", "drawer_top")], "모르는 대상: phone"),
    ([goal("eraser", "kitchen")], "모르는 장소: kitchen"),
    ([goal("robot", "drawer_approach", "robot_pose")], "어떤 스킬도 바꾸지 못하는 상태: robot_pose"),
    ([], "목표가 없음"),
    (["eraser"], "목표 형식 오류"),
])
def test_unplannable_explains_why(goals, words):
    r = pl.plan(state(), ONTO, goals)
    assert r.status == pl.UNPLANNABLE and words in r.reason and r.steps == []


def test_depth_limit_reports_unplannable():
    r = pl.plan(state(lip_balm="handover_zone"), ONTO, [goal("lip_balm", "drawer_bottom")], max_depth=3)
    assert r.status == pl.UNPLANNABLE and "깊이 3" in r.reason


def test_holding_item_is_put_down_before_other_work():
    """쥔 물품이 있으면 먼저 내려놓아야 서랍을 열 수 있다 — 쥔 물품도 후보에 넣어 계획."""
    s = state(eraser="gripper")
    s["gripper"]["robot"] = "eraser"
    r = pl.plan(s, ONTO, [goal("lip_balm", "handover_zone")])
    assert r.status == pl.PLANNED and r.steps[0].skill == "place" and r.steps[0].params["item"] == "eraser"


def test_goal_to_hold_item_uses_tray_as_staging_to_close_drawer():
    """'립밤을 쥔 채로 끝내기': 쥔 채로는 서랍을 못 닫으므로 트레이에 잠깐 놓고 서랍을 닫은 뒤 다시 집는 순서를 스스로 찾음."""
    r = pl.plan(state(), ONTO, [goal("lip_balm", "gripper")])
    assert labels(r) == ["open_drawer(drawer_top)", "pick(lip_balm, drawer_top)", "place(lip_balm, handover_zone)",
                         "close_drawer(drawer_top)", "pick(lip_balm, handover_zone)"]


def test_no_skill_closes_a_tray_so_unplannable():
    r = pl.plan(state(), ONTO, [goal("handover_zone", False, "open")])
    assert r.status == pl.UNPLANNABLE and "깊이 8" in r.reason


def test_deterministic_and_input_state_unchanged():
    s = state(lip_balm="handover_zone")
    before = copy.deepcopy(s)
    first = pl.plan(s, ONTO, [goal("lip_balm", "drawer_bottom")])
    second = pl.plan(s, ONTO, [goal("lip_balm", "drawer_bottom")])
    assert labels(first) == labels(second) and s == before


def test_plan_reaches_goal_when_effects_applied():
    s = state(lip_balm="handover_zone")
    r = pl.plan(s, ONTO, [goal("lip_balm", "drawer_bottom")])
    for step in r.steps:
        skill = ONTO["skills"][step.skill]
        assert all(c["pass"] for c in ontology.check(s, skill["pre"], step.params))        # 매 스텝 조건 충족
        s, _ = ontology.apply(s, skill["effect"], step.params)
    assert s["located_in"]["lip_balm"] == "drawer_bottom" and s["open"]["drawer_bottom"] is False


# ---- 계획 → 태스크 → Runner(mock) 실행 ----

def run_plan(robot, result, initial):
    runner = Runner(None, schema=SCHEMA, ontology={**ONTO, "state": initial}, log_store=MemoryLogStore())
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTO["world"])
    return runner, runner.run(pl.to_task(result, "plan_test", {"pick": 60, "place": 60}))


def test_task_from_plan_is_valid_and_runs_on_mock():
    initial = state()
    r = pl.plan(initial, ONTO, [goal("eraser", "handover_zone")])
    task = pl.to_task(r, "plan_eraser", {"open_drawer": 60, "pick": 60})
    assert check_task(task, SCHEMA, ONTO["skills"]) == []
    assert [s["id"] for s in task["sequence"]] == ["p1", "p2", "p3", "p4"]
    assert task["sequence"][1]["timeout_sec"] == 60 and "timeout_sec" not in task["sequence"][2]
    assert "2번 pick" in task["description"] or "pick(eraser, drawer_top)" in task["description"]
    runner, result = run_plan(MockRobot(), r, initial)
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    assert runner.state["located_in"]["eraser"] == "handover_zone" and runner.state["open"]["drawer_top"] is False


def test_plan_failure_runs_safe_finally():
    """집기 실패 → 이번 계획이 연 서랍 닫기(finally) → 빈손이라 홈. 실패한 스킬의 효과는 반영 안 됨."""
    initial = state()
    r = pl.plan(initial, ONTO, [goal("eraser", "handover_zone")])
    robot = MockRobot(fail={"pick_object": ["GRASP_FAILED"]})
    runner, result = run_plan(robot, r, initial)
    assert (result.overall_status, result.error_code) == ("FAILED", "GRASP_FAILED")
    final = {s["id"]: s.get("status") for s in result.steps if s["id"].startswith("f")}
    assert final["f2"] == "SUCCESS" and final["fh.1"] == "SUCCESS"                       # 서랍 닫기·홈
    assert runner.state["open"]["drawer_top"] is False and runner.state["located_in"]["eraser"] == "drawer_top"


def test_plan_estop_sends_no_more_motion():
    initial = state()
    r = pl.plan(initial, ONTO, [goal("eraser", "handover_zone")])
    robot = MockRobot(fail={"nudge_object": ["ESTOP"]})
    runner, result = run_plan(robot, r, initial)
    assert result.overall_status == "ABORTED" and runner.halted
    assert robot.motion_after("/skills/nudge_object") == []


def test_to_task_rejects_non_planned():
    with pytest.raises(ValueError):
        pl.to_task(pl.plan(state(), ONTO, [goal("eraser", "drawer_top")]))
