import copy
import json
from pathlib import Path

import pytest

from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.validation import check_task

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))

P1_TASK = {
    "task_id": "find_visible",
    "inputs": {"target": "watch"},
    "sequence": [
        {"id": "s1", "action": "query_ontology", "params": {"item": "$inputs.target"}, "output": "loc"},
        {"id": "s2", "action": "drawer_control", "params": {"drawer_id": "$loc.drawer_id", "state": "open"},
         "timeout_sec": 30},
        {"id": "s3", "action": "inspect_region", "params": {"region": "$loc.drawer_id"}, "output": "scan"},
        {"id": "s4", "action": "if", "cond": {"op": "==", "args": ["$scan.target_found", True]},
         "then": [{"id": "s4.1", "action": "pick_object", "params": {"object_id": "$scan.target.id"},
                   "on_failure": "retry", "retry": 1}],
         "else": [{"id": "s4.2", "action": "speak", "params": {"text": "{{loc.name_ko|을}} 찾지 못했습니다"}}]},
    ],
    "finally": [
        {"id": "f1", "action": "drawer_control", "params": {"drawer_id": "$loc.drawer_id", "state": "close"},
         "on_failure": "skip"},
        {"id": "f2", "action": "move_to_named_pose", "params": {"pose_name": "home"}},
    ],
}


def task_with(change) -> dict:
    task = copy.deepcopy(P1_TASK)
    change(task)
    return task


def test_p1_task_passes():
    assert check_task(P1_TASK, SCHEMA) == []


@pytest.mark.parametrize("change, expected", [
    (lambda t: t["sequence"][0].update(action="query_ontolgy"), "sequence/0/action"),     # 동작 이름 오타
    (lambda t: t["sequence"][1].pop("id"), "sequence/1"),                                # id 없음
    (lambda t: t["sequence"][1].update(on_failure="again"), "sequence/1/on_failure"),    # 없는 정책
    (lambda t: t["sequence"][1].update(timeout_sec=0), "sequence/1/timeout_sec"),        # 0초 제한
    (lambda t: t.pop("sequence"), "(최상위)"),                                           # sequence 없음
])
def test_schema_errors(change, expected):
    problems = check_task(task_with(change), SCHEMA)
    assert problems and expected in problems[0]


def test_p2_example_task_is_rejected():
    # 저장소의 tasks/find_with_unpack.json 은 while·push·pop 을 쓰는 P2 예시
    task = json.loads((ROOT / "tasks/find_with_unpack.json").read_text(encoding="utf-8"))
    problems = check_task(task, SCHEMA)
    assert any("'while'" in p for p in problems)
    assert any("'push'" in p for p in problems)
    assert any("'pop'" in p for p in problems)          # finally 안쪽(while 의 body)까지 검사


@pytest.mark.parametrize("change, expected", [
    (lambda t: t.update(on_halt=[{"id": "h1", "action": "speak", "params": {"text": "멈춤"}}]), "'on_halt'"),
    (lambda t: t["sequence"][1].update(recovery=[{"id": "r1", "action": "speak"}]), "'recovery'"),
    (lambda t: t["sequence"][3]["then"].append(
        {"id": "s4.3", "action": "for_each", "in": "$scan.candidates", "as": "c", "body": []}), "'for_each'"),
])
def test_p2_features_are_rejected(change, expected):
    problems = check_task(task_with(change), SCHEMA)
    assert any("P1 미지원" in p and expected in p for p in problems)


@pytest.mark.parametrize("change, expected", [
    (lambda t: t["sequence"].append({"id": "s9", "action": "set_var", "params": {"value": 1}}), "params.name"),
    (lambda t: t["sequence"][3].pop("cond"), "cond"),
    (lambda t: t["finally"][1].update(id="s4.1"), "중복"),                       # then 안쪽 ID 와 겹침
    (lambda t: t["sequence"][3]["then"][0].pop("retry"), "retry 1 이상"),
])
def test_runner_level_errors(change, expected):
    problems = check_task(task_with(change), SCHEMA)
    assert any(expected in p for p in problems)


def test_without_schema_still_checks_p1_scope():
    task = task_with(lambda t: t["sequence"].append({"id": "s9", "action": "while", "max_iter": 1, "body": []}))
    assert any("'while'" in p for p in check_task(task, None))


def test_runner_refuses_invalid_task_before_moving():
    calls = []

    def backend(action, params, timeout_sec):
        calls.append(action)
        return ActionResult(True)

    task = task_with(lambda t: t["sequence"][1].update(action="drawer_contorl"))
    result = Runner(backend, schema=SCHEMA).run(task)
    assert (result.overall_status, result.error_code) == ("FAILED", "TASK_INVALID")
    assert result.problems and "drawer_contorl" in result.problems[0]
    assert calls == []                                  # 로봇 동작 0회, finally 도 실행 안 함
    assert result.steps == []


def test_runner_runs_valid_task_with_schema():
    outputs = {"query_ontology": {"name_ko": "시계", "drawer_id": "drawer_top"},
               "inspect_region": {"target_found": True, "target": {"id": "watch#1"}}}
    result = Runner(lambda a, p, t: ActionResult(True, outputs.get(a)), schema=SCHEMA).run(P1_TASK)
    assert result.overall_status == "COMPLETED"
    assert [s["id"] for s in result.steps] == ["s1", "s2", "s3", "s4", "s4.1", "f1", "f2"]


# ---- #12: skill 스텝 (스키마) ----

def test_schema_accepts_skill_step():
    task = task_with(lambda t: t["sequence"].insert(
        1, {"id": "s1.5", "skill": "open_drawer", "params": {"drawer_id": "$loc.drawer_id"}}))
    assert check_task(task, SCHEMA) == []


def test_schema_rejects_step_with_both_or_neither():
    both = task_with(lambda t: t["sequence"][1].update(skill="open_drawer"))          # action + skill
    neither = task_with(lambda t: t["sequence"][1].pop("action"))                     # 둘 다 없음
    assert check_task(both, SCHEMA) and check_task(neither, SCHEMA)


def test_skill_example_task_is_valid():
    task = json.loads((ROOT / "contracts/examples/task_skill_steps.json").read_text(encoding="utf-8"))
    assert check_task(task, SCHEMA) == []
