"""#12 스킬 상태 추적: Runner 가 온톨로지(E)를 받아 pre 확인 → expand 실행 → effect 반영."""
import json
from pathlib import Path

import pytest

from ready2go_knowledge.core import ontology
from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.validation import check_task

ROOT = Path(__file__).resolve().parents[4]
ONTOLOGY = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))


def ok_backend(action, params, timeout_sec):
    return ActionResult(True)


# ---- 2단계: 온톨로지 받기 ----

def test_runner_holds_skills_and_initial_state():
    runner = Runner(ok_backend, ontology=ONTOLOGY)
    assert set(runner.skills) >= {"open_drawer", "close_drawer", "pick", "place"}
    assert runner.state["open"]["drawer_top"] is False
    assert runner.state["gripper"]["robot"] == "empty"


def test_runner_state_is_a_copy():
    runner = Runner(ok_backend, ontology=ONTOLOGY)
    runner.state["open"]["drawer_top"] = True            # 밖에서 꺼낸 값을 바꿔도
    assert runner.state["open"]["drawer_top"] is False   # Runner 상태는 그대로
    assert ONTOLOGY["state"]["open"]["drawer_top"] is False   # 원본 파일 내용도 그대로


def test_runner_without_ontology_works_as_before():
    runner = Runner(ok_backend)
    assert runner.skills == {} and runner.state == {}
    result = runner.run({"task_id": "t", "sequence": [{"id": "s1", "action": "speak", "params": {"text": "안녕"}}]})
    assert result.overall_status == "COMPLETED"


# ---- 3단계: skill 스텝 실행 ----

from test_interpreter import FakeBackend, FakeClock  # noqa: E402

FOUND_WATCH = ActionResult(True, {"target_found": True, "target": {"id": "watch#1"}})


def skill_task(*steps, final=()):
    return {"task_id": "skills", "sequence": list(steps), "finally": list(final)}


def test_open_drawer_runs_expand_and_applies_effect():
    backend = FakeBackend()
    runner = Runner(backend, ontology=ONTOLOGY)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}}))

    assert result.overall_status == "COMPLETED"
    assert backend.calls == [                                   # expand 순서대로, $drawer_id 치환
        ("move_to_named_pose", {"pose_name": "drawer_approach", "drawer_id": "drawer_top"}),
        ("drawer_control", {"drawer_id": "drawer_top", "state": "open"}),
    ]
    assert [(s["id"], s["action"], s["status"]) for s in result.steps] == [
        ("s1", "skill", "SUCCESS"), ("s1.e1", "move_to_named_pose", "SUCCESS"), ("s1.e2", "drawer_control", "SUCCESS")]
    assert result.steps[0]["skill"] == "open_drawer" and result.steps[1]["parent"] == "s1"
    assert result.steps[0]["state_diff"] == {"open.drawer_top": [False, True]}
    assert runner.state["open"]["drawer_top"] is True


def test_pre_unmet_does_not_move_robot():
    backend = FakeBackend()
    runner = Runner(backend, ontology=ONTOLOGY)
    # 위 서랍은 닫혀 있으므로 pick 의 pre(서랍 열림) 불충족
    result = runner.run(skill_task({"id": "s1", "skill": "pick", "params": {"item": "watch", "from": "drawer_top"}}))

    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "PRE_UNMET", "s1")
    assert backend.calls == []                                  # 로봇 동작 0회
    failed = [c for c in result.steps[0]["pre_check"] if not c["pass"]]
    assert failed == [{"subject": "drawer_top", "predicate": "open", "op": "==",
                       "value": True, "actual": False, "pass": False}]
    assert runner.state == ONTOLOGY["state"]                    # 상태 그대로


def test_failed_expand_keeps_state():
    backend = FakeBackend({"drawer_control": ActionResult(False, error_code="DRAWER_STUCK")})
    runner = Runner(backend, ontology=ONTOLOGY)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}}))

    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "DRAWER_STUCK", "s1.e2")
    assert [s["status"] for s in result.steps] == ["FAILURE", "SUCCESS", "FAILURE"]
    assert runner.state["open"]["drawer_top"] is False          # 실패하면 effect 없음


def test_state_carries_across_steps_and_tasks():
    backend = FakeBackend({"inspect_region": FOUND_WATCH})
    runner = Runner(backend, ontology=ONTOLOGY)
    first = runner.run(skill_task(
        {"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}},
        {"id": "s2", "skill": "pick", "params": {"item": "watch", "from": "drawer_top"}}))
    assert first.overall_status == "COMPLETED"
    assert ("pick_object", {"object_id": "watch#1", "approach_offset": [0, 0, 0.1]}) in backend.calls   # $scan 사용
    assert "scan" not in first.blackboard                      # 스킬 안 출력은 태스크 변수로 새지 않음

    # 다음 태스크: 앞 태스크가 남긴 상태(시계를 들고 있음)에서 이어짐
    second = runner.run(skill_task({"id": "s1", "skill": "place", "params": {"item": "watch", "to": "handover_zone"}}))
    assert second.overall_status == "COMPLETED"
    assert runner.state["gripper"]["robot"] == "empty"
    assert runner.state["located_in"]["watch"] == "handover_zone"


def test_skill_params_use_task_variables():
    backend = FakeBackend({"query_ontology": ActionResult(True, {"drawer_id": "drawer_bottom"})})
    runner = Runner(backend, ontology=ONTOLOGY)
    result = runner.run(skill_task(
        {"id": "s1", "action": "query_ontology", "params": {"item": "wallet"}, "output": "loc"},
        {"id": "s2", "skill": "open_drawer", "params": {"drawer_id": "$loc.drawer_id"}}))
    assert result.overall_status == "COMPLETED"
    assert result.steps[1]["params"] == {"drawer_id": "drawer_bottom"}
    assert runner.state["open"]["drawer_bottom"] is True


def test_retry_repeats_whole_skill():
    backend = FakeBackend({"drawer_control": [ActionResult(False, error_code="DRAWER_STUCK"), ActionResult(True)]})
    runner = Runner(backend, ontology=ONTOLOGY)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"},
                                    "on_failure": "retry", "retry": 1}))
    assert result.overall_status == "COMPLETED"
    assert [a for a, _ in backend.calls] == ["move_to_named_pose", "drawer_control"] * 2
    assert result.steps[0]["attempts"] == 2
    assert runner.state["open"]["drawer_top"] is True


def test_timeout_covers_whole_skill():
    clock = FakeClock()
    backend = FakeBackend(clock=clock, durations={"move_to_named_pose": 8.0, "drawer_control": 5.0})
    runner = Runner(backend, clock=clock, ontology=ONTOLOGY)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"},
                                    "timeout_sec": 10}))
    assert backend.timeouts == [10, 2]                         # 두 번째 동작엔 남은 시간만
    assert (result.overall_status, result.error_code) == ("FAILED", "TIMEOUT")
    assert runner.state["open"]["drawer_top"] is False


def test_estop_skips_skills_in_finally():
    backend = FakeBackend({"drawer_control": ActionResult(False, error_code="ESTOP")})
    runner = Runner(backend, ontology=ONTOLOGY)
    result = runner.run(skill_task(
        {"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}},
        final=[{"id": "f1", "skill": "close_drawer", "params": {"drawer_id": "drawer_top"}},
               {"id": "f2", "action": "speak", "params": {"text": "멈췄습니다"}}]))
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "ESTOP", "s1.e2")
    f1 = next(s for s in result.steps if s["id"] == "f1")
    assert (f1["status"], f1["skipped_reason"]) == ("SKIPPED", "ABORTED")   # 스킬도 로봇을 움직이므로 생략
    assert [a for a, _ in backend.calls] == ["move_to_named_pose", "drawer_control", "speak"]


def test_runtime_guard_when_validation_is_bypassed(monkeypatch):
    # 실행 전 검사(4단계)가 막지만, 검사를 거치지 않아도 실행 중 다시 확인해 로봇을 움직이지 않음
    monkeypatch.setattr("ready2go_runner.core.interpreter.check_task", lambda *a: [])
    backend = FakeBackend()
    runner = Runner(backend, ontology=ONTOLOGY)
    for params, skill, code in [({}, "open_drawr", "UNKNOWN_SKILL"),
                                ({"target": "watch"}, "fetch_with_unpack", "UNKNOWN_SKILL"),
                                ({"item": "watch"}, "pick", "BAD_SKILL_PARAMS")]:
        result = runner.run(skill_task({"id": "s1", "skill": skill, "params": params}))
        assert result.error_code == code
    assert backend.calls == []


# ---- 4단계: 실행 전 검사 ----

@pytest.mark.parametrize("step, expected", [
    ({"id": "s1", "skill": "open_drawr", "params": {"drawer_id": "drawer_top"}}, "없는 스킬 'open_drawr'"),
    ({"id": "s1", "skill": "fetch_with_unpack", "params": {"target": "watch"}}, "P1 미지원"),
    ({"id": "s1", "skill": "pick", "params": {"item": "watch"}}, "params.from 가 없음"),
    ({"id": "s1", "skill": "open_drawer", "params": {"drawer": "drawer_top"}}, "없는 파라미터 params.drawer"),
])
def test_invalid_skill_step_is_rejected_before_moving(step, expected):
    backend = FakeBackend()
    # 앞 스텝(말하기)도 실행되지 않아야 함: 시작 전에 거절
    task = skill_task({"id": "s0", "action": "speak", "params": {"text": "시작"}}, step,
                      final=[{"id": "f1", "action": "move_to_named_pose", "params": {"pose_name": "home"}}])
    result = Runner(backend, schema=SCHEMA, ontology=ONTOLOGY).run(task)
    assert (result.overall_status, result.error_code) == ("FAILED", "TASK_INVALID")
    assert any(expected in p for p in result.problems), result.problems
    assert backend.calls == [] and result.steps == []


def test_child_record_id_collision_is_rejected():
    task = skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}},
                      {"id": "s1.e2", "action": "speak", "params": {"text": "겹침"}})
    problems = check_task(task, SCHEMA, ONTOLOGY["skills"])
    assert any("'s1.e2'" in p and "중복" in p for p in problems)


def test_skill_example_passes_with_ontology():
    task = json.loads((ROOT / "contracts/examples/task_skill_steps.json").read_text(encoding="utf-8"))
    assert check_task(task, SCHEMA, ONTOLOGY["skills"]) == []


def test_skill_step_without_ontology_is_rejected():
    # 온톨로지 없이 만든 Runner 는 skill 스텝을 실행할 수 없음
    result = Runner(FakeBackend()).run(skill_task({"id": "s1", "skill": "open_drawer",
                                                   "params": {"drawer_id": "drawer_top"}}))
    assert result.error_code == "TASK_INVALID"
