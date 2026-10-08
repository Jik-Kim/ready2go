"""P2 제어 블록 (docs/runner.md 7.1): while(max_iter·LOOP_LIMIT) · for_each · push/pop(LIFO) · fallback.
Unpacking·역순 복구(FR-ACT-04, domain.md 8.2·8.3)에 필요한 Runner 쪽. 서랍 안 빈 자리·재식별 계약(#120·#109)과 무관하게
"옮길 때 원래 자리를 쌓고, 끝나면 거꾸로 꺼내 되돌린다"는 순서와 안전 규칙을 확인한다."""
import json
from pathlib import Path

from ready2go_runner.core import step_console
from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.logstore import MemoryLogStore

from test_interpreter import FakeBackend  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))


def scan(found, candidates=()):
    return ActionResult(True, {"target_found": found, "target": {"id": "watch#1"} if found else None,
                               "candidates": [{"id": c, "pose": {"position": [i * 0.1, 0.1, 0]}}
                                              for i, c in enumerate(candidates)], "visible_count": len(candidates)})


# 목표가 안 보이면 맨 위 후보를 옮기고 원래 자리를 쌓은 뒤 다시 본다 → 찾으면 전달 → finally 에서 거꾸로 복구
UNPACK = {
    "task_id": "unpack_test",
    "sequence": [
        {"id": "s1", "action": "inspect_region", "params": {"region": "drawer_top", "search_target": "watch"},
         "output": "scan"},
        {"id": "s2", "action": "while", "max_iter": 3,
         "cond": {"op": "==", "args": ["$scan.target_found", False]},
         "body": [
             {"id": "s2.1", "action": "pick_object", "params": {"target": "$scan.candidates[0]"}, "output": "picked"},
             {"id": "s2.2", "action": "place_object", "params": {"location": "drawer_top"}},
             {"id": "s2.3", "action": "push", "params": {"stack": "restore_stack",
                                                         "value": {"id": "$picked.object_id",
                                                                   "origin": "$scan.candidates[0].pose"}}},
             {"id": "s2.4", "action": "inspect_region", "params": {"region": "drawer_top", "search_target": "watch"},
              "output": "scan"}]},
        {"id": "s3", "action": "pick_object", "params": {"target": "$scan.target"}},
        {"id": "s4", "action": "place_object", "params": {"location": "handover_zone"}},
    ],
    "finally": [
        {"id": "f1", "action": "while", "max_iter": 8, "cond": {"op": "not_empty", "args": ["$restore_stack"]},
         "body": [
             {"id": "f1.1", "action": "pop", "params": {"stack": "restore_stack"}, "output": "item"},
             {"id": "f1.2", "action": "pick_object", "params": {"object_id": "$item.id"}},
             {"id": "f1.3", "action": "place_object", "params": {"pose": "$item.origin"}}]},
    ],
}


def picked(ids):
    return [ActionResult(True, {"object_id": i}) for i in ids]


def unpack_backend(**extra):
    return FakeBackend({"inspect_region": [scan(False, ["book#1", "box#1"]), scan(False, ["box#1"]), scan(True)],
                        "pick_object": picked(["book#1", "box#1", "watch#1", "box#1", "book#1"]), **extra})


def test_unpack_moves_obstacles_then_restores_in_reverse_order():
    backend = unpack_backend()
    store = MemoryLogStore()
    result = Runner(backend, schema=SCHEMA, log_store=store).run(UNPACK)
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    restores = [p for a, p in backend.calls if a == "place_object" and "pose" in p]
    # 옮긴 순서 book → box, 되돌리는 순서 box → book (LIFO), 원래 pose 그대로
    assert [p["pose"]["position"][0] for p in restores] == [0.0, 0.0]
    restored_ids = [p["object_id"] for a, p in backend.calls if a == "pick_object" and "object_id" in p]
    assert restored_ids == ["box#1", "book#1"]
    assert result.blackboard["restore_stack"] == []
    loop = next(s for s in result.steps if s["id"] == "s2")
    assert loop["iterations"] == 2
    assert [s.get("iteration") for s in result.steps if s["id"] == "s2.1"] == [1, 2]       # 같은 ID, 회차 기록
    saved = store.read_run(result.run_id)["steps"]
    assert [s["id"] for s in saved] == [s["id"] for s in result.steps]                     # 반복 회차도 빠짐없이 저장


def test_while_stops_with_loop_limit_and_finally_still_restores():
    backend = FakeBackend({"inspect_region": scan(False, ["book#1"]), "pick_object": ActionResult(True, {"object_id": "book#1"})})
    result = Runner(backend, schema=SCHEMA).run(UNPACK)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "LOOP_LIMIT", "s2")
    assert next(s for s in result.steps if s["id"] == "s2")["iterations"] == 3
    restores = [p for a, p in backend.calls if a == "place_object" and "pose" in p]
    assert len(restores) == 3 and result.blackboard["restore_stack"] == []                 # 옮긴 3개 모두 복구


def test_estop_skips_restore_loop_and_keeps_record_for_people():
    """비상정지 뒤 finally 의 복구 반복은 로봇을 움직이므로 통째로 건너뛰고, 복구 기록은 남겨 사람이 본다."""
    backend = unpack_backend(place_object=[ActionResult(True), ActionResult(False, error_code="ESTOP")])
    runner = Runner(backend, schema=SCHEMA)
    result = runner.run(UNPACK)
    assert result.overall_status == "ABORTED" and runner.halted
    assert next(s for s in result.steps if s["id"] == "f1")["status"] == "SKIPPED"
    assert len(result.blackboard["restore_stack"]) == 1                                   # 첫 장애물 원래 자리 보존
    actions = [a for a, _ in backend.calls]
    assert actions.count("place_object") == 2 and actions[-1] == "place_object"           # 비상정지 난 놓기가 마지막 호출


def test_pop_on_empty_stack_fails():
    task = {"task_id": "t", "sequence": [{"id": "s1", "action": "pop", "params": {"stack": "restore_stack"}, "output": "x"}]}
    result = Runner(FakeBackend(), schema=SCHEMA).run(task)
    assert (result.overall_status, result.error_code) == ("FAILED", "STACK_EMPTY")


def test_push_refuses_null_value():
    """복구할 원래 자리가 비어 있으면(null) 쌓지 않는다 — 나중에 엉뚱한 곳으로 되돌리지 않게."""
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "set_var", "params": {"name": "picked", "value": None}},
        {"id": "s2", "action": "push", "params": {"stack": "restore_stack", "value": "$picked"}}]}
    result = Runner(FakeBackend(), schema=SCHEMA).run(task)
    assert (result.overall_status, result.error_code) == ("FAILED", "VAR_NULL")


def test_for_each_visits_items_in_order_with_iteration():
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "set_var", "params": {"name": "drawers", "value": ["drawer_top", "drawer_bottom"]}},
        {"id": "s2", "action": "for_each", "in": "$drawers", "as": "d", "body": [
            {"id": "s2.1", "action": "drawer_control", "params": {"drawer_id": "$d", "state": "open"}}]}]}
    backend = FakeBackend()
    result = Runner(backend, schema=SCHEMA).run(task)
    assert result.overall_status == "COMPLETED"
    assert [p["drawer_id"] for a, p in backend.calls] == ["drawer_top", "drawer_bottom"]
    assert next(s for s in result.steps if s["id"] == "s2")["iterations"] == 2


def test_for_each_needs_a_list():
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "set_var", "params": {"name": "drawers", "value": "drawer_top"}},
        {"id": "s2", "action": "for_each", "in": "$drawers", "as": "d", "body": [{"id": "s2.1", "action": "speak"}]}]}
    assert Runner(FakeBackend(), schema=SCHEMA).run(task).error_code == "NOT_A_LIST"


FALLBACK = {"task_id": "t", "sequence": [{"id": "s1", "action": "fallback", "options": [
    [{"id": "s1.a", "action": "pick_object", "params": {"approach": "top"}}],
    [{"id": "s1.b", "action": "pick_object", "params": {"approach": "side"}}]]}]}


def test_fallback_tries_next_option_after_plain_failure():
    backend = FakeBackend({"pick_object": [ActionResult(False, error_code="GRASP_FAILED"), ActionResult(True)]})
    result = Runner(backend, schema=SCHEMA).run(FALLBACK)
    assert result.overall_status == "COMPLETED"
    assert [p["approach"] for _, p in backend.calls] == ["top", "side"]
    assert next(s for s in result.steps if s["id"] == "s1")["option"] == 2


def test_fallback_does_not_try_next_option_when_result_uncertain():
    """앞 대안이 TIMEOUT(결과 불확실)이면 다음 대안을 보내지 않음 — retry 와 같은 안전 규칙."""
    backend = FakeBackend({"pick_object": ActionResult(False, error_code="TIMEOUT")})
    result = Runner(backend, schema=SCHEMA).run(FALLBACK)
    assert (result.overall_status, result.error_code) == ("FAILED", "TIMEOUT")
    assert len(backend.calls) == 1
    assert next(s for s in result.steps if s["id"] == "s1")["fallback_stopped"] == "TIMEOUT"


def test_fallback_all_fail_reports_last_code():
    backend = FakeBackend({"pick_object": ActionResult(False, error_code="GRASP_FAILED")})
    result = Runner(backend, schema=SCHEMA).run(FALLBACK)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "GRASP_FAILED", "s1")
    assert len(backend.calls) == 2


def test_step_console_shows_loop_blocks():
    lines = []
    runner = Runner(unpack_backend(), schema=SCHEMA)
    runner.on_step = lambda e, r, i: lines.append(step_console.end_line(i["run_id"], r, i["finally"])[1]) if e == "end" else None
    runner.run(UNPACK)
    assert any("s2 " in line and "✅" in line for line in lines) and any("f1.1" in line for line in lines)


def test_report_groups_loop_iterations_and_skill_children():
    """보고서: 반복 안 같은 스텝 ID 를 회차로 구분하고, 반복 안 스킬의 하위 동작이 다른 회차와 섞이지 않음."""
    from ready2go_runner.core import run_report
    task = {"task_id": "t", "sequence": [{"id": "s1", "action": "for_each", "in": "$ds", "as": "d", "body": [
        {"id": "s1.1", "skill": "open_drawer", "params": {"drawer_id": "$d"}}]}]}
    onto = {"skills": {"open_drawer": {"kind": "primitive", "params": {"drawer_id": "Drawer"}, "pre": [], "effect": [],
                                       "expand": [{"action": "drawer_control", "params": {"drawer_id": "$drawer_id"}}]}},
            "state": {}}
    store = MemoryLogStore()
    runner = Runner(FakeBackend(), schema=SCHEMA, ontology=onto, log_store=store)
    task["sequence"].insert(0, {"id": "s0", "action": "set_var", "params": {"name": "ds", "value": ["a", "b"]}})
    result = runner.run(task)
    text = run_report.to_text(store.read_run(result.run_id))
    assert "[s1.1 · 1회차]" in text and "[s1.1 · 2회차]" in text
    assert text.count("[s1.1.e1 · 1회차]") == 1 and text.count("[s1.1.e1 · 2회차]") == 1          # 섞이지 않음
