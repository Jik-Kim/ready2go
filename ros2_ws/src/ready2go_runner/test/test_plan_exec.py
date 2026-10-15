"""플래너 묶음 스킬 + 구간 실행 (#302 E 결정 10/15 — C 권고 2안). E 온톨로지 PR 전이라 E 제안 형식 그대로
handover_with_unpack 에 params {target, from}·pre·plan_effect 를 넣은 온톨로지 복사본으로 시험 (저장소 온톨로지는 안 바꿈).

완료 근거(E): E 데이터 정의 → 실제 planner 선택 → 기존 find_with_unpack mock 실행 → 실제 상태 확인 → 재계획 → 최종 목표.
"""
import copy
import json
from pathlib import Path

import pytest

from ready2go_runner.core import planner
from ready2go_runner.core.backend import RosBackend
from ready2go_runner.core.interpreter import ActionResult, Runner, RunResult
from ready2go_runner.core.logstore import MemoryLogStore
from ready2go_runner.core.mock_scene import MockScene
from ready2go_runner.core.mock_skills import MockSkills
from ready2go_runner.core.plan_exec import PLAN_EFFECT_UNMET, PLAN_NO_PROGRESS, run_plan

from start_states import P2_SINGLE, start_state, with_state  # noqa: E402
from test_item_group import NO_ROOM_THEN_RESTORE_FAIL, Robot  # noqa: E402
from test_tasks import ONTOLOGY, SCHEMA  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
LIMITS = planner.parse_limits(planner.DEFAULT_PLAN_LIMITS)
DELIVER = {"predicate": "located_in", "subject": "eraser", "value": "handover_zone"}
TOP_OPEN = {"predicate": "open", "subject": "drawer_top", "value": True}


def e_onto(located=P2_SINGLE):
    """E 제안(#302 10/15): 실제 effect 'sensing'·task 유지 + 계획 전용 plan_effect, from 은 pick 관례대로 매개변수."""
    onto = with_state(ONTOLOGY, located)
    skill = onto["skills"]["handover_with_unpack"]
    assert skill["kind"] == "composite" and skill["effect"] == "sensing"
    skill.pop("plan_effect", None)
    skill.update(params={"target": "Item", "from": "Drawer"},
                 pre=[{"subject": "robot", "predicate": "gripper", "op": "==", "value": "empty"},
                      {"subject": "$target", "predicate": "located_in", "op": "==", "value": "$from"},
                      {"subject": "$from", "predicate": "open", "op": "==", "value": False}],
                 plan_effect=[{"subject": "$target", "predicate": "located_in", "value": "handover_zone"}])
    return onto


def load_task(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def setup(onto, scene=None, **robot_kw):
    robot = Robot(**robot_kw)
    if scene is not None:
        robot.skills = MockSkills(robot_kw.get("failures") or {}, scene=scene)
    runner = Runner(None, schema=SCHEMA, ontology=onto, log_store=MemoryLogStore())
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, onto["world"])
    return runner, robot


def labels(result):
    return [s.label() for s in result.steps]


# ---- 플래너 ----

def test_planner_chooses_unpack_composite_only_when_allowed():
    """'지우개 갖다주고 위 서랍 열어 둬' — composites=True 이면 묶음(언패킹) → 위 서랍 열기 2단계, 기본(False)은 지금 그대로
    일반 pick 5단계. plan_effect 없는 composite(effect 'sensing' 만)는 composites=True 여도 후보로 안 씀 — 저장소 파일에
    E #375 가 들어오든 말든 같은 결과가 되도록 복사본에서 plan_effect 를 빼서 확인."""
    onto = e_onto()
    both = planner.plan(start_state(P2_SINGLE), onto, [DELIVER, TOP_OPEN], limits=LIMITS, composites=True)
    assert labels(both) == ["handover_with_unpack(eraser, drawer_bottom)", "open_drawer(drawer_top)"]
    assert both.steps[0].task == "tasks/find_with_unpack.json" and both.steps[1].task is None
    assert "목표 located_in.eraser" in both.steps[0].reasons[0]
    plain = planner.plan(start_state(P2_SINGLE), onto, [DELIVER, TOP_OPEN], limits=LIMITS)
    assert labels(plain) == ["open_drawer(drawer_bottom)", "pick(eraser, drawer_bottom)", "place(eraser, handover_zone)",
                             "close_drawer(drawer_bottom)", "open_drawer(drawer_top)"]
    sensing_only = e_onto()
    del sensing_only["skills"]["handover_with_unpack"]["plan_effect"]
    no_plan = planner.plan(start_state(P2_SINGLE), sensing_only, [DELIVER, TOP_OPEN], limits=LIMITS, composites=True)
    assert labels(no_plan) == labels(plain)


def test_repo_ontology_when_e_plan_effect_lands_matches_the_proposal():
    """저장소 handover_with_unpack 에 E plan_effect(#375)가 있으면 이 시험이 쓰는 E 제안 형식과 같아야 함 — 없으면(머지 전) 건너뜀."""
    repo = ONTOLOGY["skills"]["handover_with_unpack"]
    if "plan_effect" not in repo:
        pytest.skip("E #375 (handover_with_unpack plan_effect) 머지 전")
    proposal = e_onto()["skills"]["handover_with_unpack"]
    assert {k: repo.get(k) for k in ("kind", "params", "pre", "effect", "task", "plan_effect")} == \
        {k: proposal[k] for k in ("kind", "params", "pre", "effect", "task", "plan_effect")}


def test_composite_obeys_one_drawer_at_a_time():
    """다른 서랍이 열려 있으면 묶음에 들어가지 않음(안에서 서랍을 엶) — 먼저 닫는 계획."""
    st = start_state(P2_SINGLE)
    st["open"]["drawer_top"] = True
    result = planner.plan(st, e_onto(), [DELIVER], limits=LIMITS, composites=True)
    assert labels(result) == ["close_drawer(drawer_top)", "handover_with_unpack(eraser, drawer_bottom)"]


def test_to_task_refuses_composite_steps():
    result = planner.plan(start_state(P2_SINGLE), e_onto(), [DELIVER], limits=LIMITS, composites=True)
    with pytest.raises(ValueError):
        planner.to_task(result)


# ---- 구간 실행 ----

def test_compound_goal_unpacks_with_real_task_then_replans_and_opens_top():
    """판 밑 지우개(mock 장면) — 묶음 = find_with_unpack 단독 실행(판 치우기·전달·판 원위치·닫기) → 실제 상태 확인 →
    재계획 → 위 서랍 열기. 최종 목표(지우개 트레이·위 서랍 열림·아래 서랍 닫힘) 만족."""
    onto = e_onto()
    runner, robot = setup(onto, scene=MockScene("plate_over_eraser", "drawer_bottom"))
    out = run_plan(runner, onto, [DELIVER, TOP_OPEN], load_task, limits=LIMITS)
    assert (out.overall_status, out.error_code) == ("COMPLETED", None), out
    assert [(s.kind, s.skills) for s in out.segments] == [
        ("composite", ["handover_with_unpack(eraser, drawer_bottom)"]), ("primitive", ["open_drawer(drawer_top)"])]
    assert robot.skills.scene.delivered == ["eraser"]
    picks = [p["target"]["class"] for a, p in robot.calls if a == "pick_object"]
    assert picks == ["cover_plate", "eraser", "cover_plate"]                     # 판 치우기 → 지우개 → 판 원위치 (언패킹)
    state = runner.state
    assert state["located_in"]["eraser"] == "handover_zone"
    assert (state["open"]["drawer_top"], state["open"]["drawer_bottom"]) == (True, False)
    assert robot.drawer_moves() == [("drawer_bottom", "open"), ("drawer_bottom", "close"), ("drawer_top", "open")]


def test_composite_success_flag_alone_does_not_advance():
    """묶음이 COMPLETED 여도 실제 상태에 전달이 없으면 다음 구간(위 서랍 열기) 안 함 — plan_effect 를 상태에 미리 쓰지 않음."""
    onto = e_onto()
    runner, robot = setup(onto)
    nothing = {"task_id": "noop", "sequence": [{"id": "n1", "action": "set_var", "params": {"name": "x", "value": 1}}]}
    out = run_plan(runner, onto, [DELIVER, TOP_OPEN], lambda path: nothing, limits=LIMITS)
    assert (out.overall_status, out.error_code) == ("FAILED", PLAN_EFFECT_UNMET)
    assert runner.state["located_in"]["eraser"] == "drawer_bottom" and robot.drawer_moves() == []


def test_composite_failure_sends_no_followup():
    onto = e_onto()
    runner, robot = setup(onto, not_visible={"eraser"})
    out = run_plan(runner, onto, [DELIVER, TOP_OPEN], load_task, limits=LIMITS)
    assert out.overall_status == "FAILED" and out.error_code == "TARGET_NOT_FOUND"
    assert ("drawer_top", "open") not in robot.drawer_moves()
    failure = out.segments[0].failure                                                # #376: 구간의 처음 원인을 묶음까지 들고 옴
    assert (failure["code"], failure["step"], failure["run_id"]) == ("TARGET_NOT_FOUND", "s8", out.segments[0].run_id)


def test_halt_inside_composite_aborts_keeps_lock_and_nothing_suspended():
    onto = e_onto()
    runner, robot = setup(onto)
    runner.resumable = True

    def stop_at_pick(action, params):
        if action == "pick_object":
            runner.halt(source="voice")
            return ActionResult(False, error_code="CANCELED")
        return None
    robot.hook = stop_at_pick
    out = run_plan(runner, onto, [DELIVER, TOP_OPEN], load_task, limits=LIMITS)
    assert (out.overall_status, out.error_code) == ("ABORTED", "HALTED")
    assert runner.suspended is None and runner.halted is True and runner.resumable is True
    assert ("drawer_top", "open") not in robot.drawer_moves()


def test_restore_failure_hidden_behind_allowed_code_stops():
    onto = e_onto()
    runner, robot = setup(onto, failures={"place_object": ["NO_FREE_SPACE", None]})
    out = run_plan(runner, onto, [DELIVER, TOP_OPEN], lambda path: NO_ROOM_THEN_RESTORE_FAIL, limits=LIMITS)
    assert out.segments[0].error_code == "NO_FREE_SPACE"
    assert (out.overall_status, out.error_code) == ("FAILED", "RESTORE_INCOMPLETE")
    assert ("drawer_top", "open") not in robot.drawer_moves()


def test_delivery_kept_when_followup_fails():
    """전달 뒤 위 서랍 열기 실패 — 전달 상태·기록 그대로, 전체 FAILED + 그 코드."""
    onto = e_onto()
    runner, robot = setup(onto)

    def top_stuck(action, params):
        if action == "drawer_control" and params.get("drawer_id") == "drawer_top" and params.get("state") == "open":
            return ActionResult(False, error_code="DRAWER_STUCK")
        return None
    robot.hook = top_stuck
    out = run_plan(runner, onto, [DELIVER, TOP_OPEN], load_task, limits=LIMITS)
    assert [s.kind for s in out.segments] == ["composite", "primitive"]
    assert out.overall_status == "FAILED" and out.error_code
    assert runner.state["located_in"]["eraser"] == "handover_zone"


def test_plain_primitive_goal_and_already_satisfied():
    onto = e_onto()
    runner, _ = setup(onto)
    out = run_plan(runner, onto, [TOP_OPEN], load_task, limits=LIMITS)
    assert (out.overall_status, [s.kind for s in out.segments]) == ("COMPLETED", ["primitive"])
    again = run_plan(runner, onto, [TOP_OPEN], load_task, limits=LIMITS)
    assert (again.overall_status, again.segments) == ("COMPLETED", [])            # 이미 만족 — 동작 없음


def test_no_progress_is_finite(monkeypatch):
    """구간이 '성공'했다는데 상태가 그대로면 같은 계획을 반복하지 않고 PLAN_NO_PROGRESS."""
    onto = e_onto()
    runner, _ = setup(onto)
    monkeypatch.setattr(runner, "run", lambda task, inputs=None, **kw: RunResult("COMPLETED", {}, run_id="r"))
    out = run_plan(runner, onto, [TOP_OPEN], load_task, limits=LIMITS)
    assert (out.overall_status, out.error_code, len(out.segments)) == ("FAILED", PLAN_NO_PROGRESS, 1)


def test_goal_met_on_the_last_allowed_segment_is_completed():
    """[#373 E 리뷰] 구간 상한(max_rounds)의 마지막 구간에서 목표를 다 이루면 COMPLETED — PLAN_NO_PROGRESS 로 오기록하지 않음.
    상한 안에 못 이루면 그대로 PLAN_NO_PROGRESS."""
    onto = e_onto()
    runner, _ = setup(onto)
    out = run_plan(runner, onto, [TOP_OPEN], load_task, limits=LIMITS, max_rounds=1)
    assert (out.overall_status, out.error_code, len(out.segments)) == ("COMPLETED", None, 1)
    runner2, _ = setup(onto, scene=MockScene("plate_over_eraser", "drawer_bottom"))
    short = run_plan(runner2, onto, [DELIVER, TOP_OPEN], load_task, limits=LIMITS, max_rounds=1)
    assert (short.overall_status, short.error_code) == ("FAILED", PLAN_NO_PROGRESS)   # 묶음만 하고 위 서랍은 못 엶
    assert runner2.state["located_in"]["eraser"] == "handover_zone"                  # 한 일은 그대로


def test_halt_right_after_the_last_allowed_segment_is_aborted(monkeypatch):
    """[#373 E 재리뷰] 마지막 허용 구간이 끝난 직후 정지가 들어오면 ABORTED + 정지 코드 — '목표 미달성'(PLAN_NO_PROGRESS)이 아님.
    한 일(위 서랍 열림)은 그대로, 잠금 유지."""
    onto = e_onto()
    runner, _ = setup(onto)
    real_run = runner.run

    def run_then_halt(task, inputs=None, **kw):
        result = real_run(task, inputs, **kw)
        runner.halt(source="voice")          # 구간 결과가 돌아온 직후 정지 도착
        return result
    monkeypatch.setattr(runner, "run", run_then_halt)
    out = run_plan(runner, onto, [TOP_OPEN], load_task, limits=LIMITS, max_rounds=1)
    assert (out.overall_status, out.error_code) == ("ABORTED", "HALTED")
    assert runner.halted is True and runner.state["open"]["drawer_top"] is True
