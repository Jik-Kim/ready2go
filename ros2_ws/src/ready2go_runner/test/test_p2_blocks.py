"""P2 제어 블록 (docs/runner.md 7.1): while(max_iter·LOOP_LIMIT) · for_each · push/pop(LIFO) · fallback.
Unpacking·역순 복구(FR-ACT-04, domain.md 8.2·8.3)에 필요한 Runner 쪽. 서랍 안 빈 자리·재식별 계약(#120·#109)과 무관하게
"옮길 때 원래 자리를 쌓고, 끝나면 거꾸로 꺼내 되돌린다"는 순서와 안전 규칙을 확인한다."""
import json

import pytest
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


def fallback_record(result):
    return next(s for s in result.steps if s["id"] == "s1")


def test_fallback_tries_next_option_after_failure_without_motion():
    """YAW_INVALID = 움직이기 전 거절(NO_MOTION_BY_ACTION) → 로봇이 안 움직였으니 다음 대안."""
    backend = FakeBackend({"pick_object": [ActionResult(False, error_code="YAW_INVALID"), ActionResult(True)]})
    result = Runner(backend, schema=SCHEMA).run(FALLBACK)
    assert result.overall_status == "COMPLETED"
    assert [p["approach"] for _, p in backend.calls] == ["top", "side"]
    assert fallback_record(result)["option"] == 2


PLACE_ASIDE = {"task_id": "t", "sequence": [{"id": "s1", "action": "fallback", "options": [
    [{"id": "s1.a", "action": "place_object", "params": {"location": "drawer_top", "slot": "aside_1"}}],
    [{"id": "s1.b", "action": "place_object", "params": {"location": "drawer_top", "slot": "aside_2"}}]]}]}


def test_place_blocked_tries_other_slot():
    """#168·#166: 놓을 자리 막힘(PLACE_BLOCKED, 움직이기 전 거부) → 다른 고정 자리로 1회."""
    backend = FakeBackend({"place_object": [ActionResult(False, {"blocked_by": "eraser#1"}, "PLACE_BLOCKED"),
                                            ActionResult(True)]})
    result = Runner(backend, schema=SCHEMA).run(PLACE_ASIDE)
    assert result.overall_status == "COMPLETED"
    assert [p["slot"] for _, p in backend.calls] == ["aside_1", "aside_2"]


def test_place_failure_after_motion_does_not_try_other_slot():
    backend = FakeBackend({"place_object": [ActionResult(False, error_code="NOT_REACHED"), ActionResult(True)]})
    result = Runner(backend, schema=SCHEMA).run(PLACE_ASIDE)
    assert (result.overall_status, result.error_code) == ("FAILED", "NOT_REACHED") and len(backend.calls) == 1
    assert fallback_record(result)["fallback_stopped"] == "MOTION_UNCERTAIN"


@pytest.mark.parametrize("code, tries", [("WALL_TOO_CLOSE", 2), ("NOT_ON_FLOOR", 2), ("TOOL_NOT_SET", 2),
                                         ("GRASP_FAILED", 1), ("NOT_REACHED", 1)])
def test_pick_pre_motion_codes_allow_next_option(code, tries):
    """공통 표 "움직이기 전 거부" 코드면 다음 대안, 움직인 뒤 실패면 멈춤."""
    backend = FakeBackend({"pick_object": [ActionResult(False, error_code=code), ActionResult(True)]})
    Runner(backend, schema=SCHEMA).run(FALLBACK)
    assert len(backend.calls) == tries


def test_code_counts_as_no_motion_only_for_its_action():
    """PLACE_BLOCKED 는 place_object 표의 코드 — 다른 동작(drawer_control)이 같은 코드를 내도 움직였을 수 있다고 봄."""
    task = {"task_id": "t", "sequence": [{"id": "s1", "action": "fallback", "options": [
        [{"id": "s1.a", "action": "drawer_control", "params": {"drawer_id": "drawer_top", "state": "open"}}],
        [{"id": "s1.b", "action": "speak", "params": {"text": "x"}}]]}]}
    backend = FakeBackend({"drawer_control": ActionResult(False, error_code="PLACE_BLOCKED")})
    result = Runner(backend, schema=SCHEMA).run(task)
    assert result.overall_status == "FAILED" and len(backend.calls) == 1


def test_fallback_tries_next_option_after_non_motion_failure():
    """인식만 하고 실패(팔을 움직이지 않는 동작) → 다음 대안."""
    task = {"task_id": "t", "sequence": [{"id": "s1", "action": "fallback", "options": [
        [{"id": "s1.a", "action": "inspect_region", "params": {"region": "drawer_top"}}],
        [{"id": "s1.b", "action": "move_to_named_pose", "params": {"pose_name": "top_view"}}]]}]}
    backend = FakeBackend({"inspect_region": ActionResult(False, error_code="NOT_VISIBLE")})
    result = Runner(backend, schema=SCHEMA).run(task)
    assert result.overall_status == "COMPLETED"
    assert [a for a, _ in backend.calls] == ["inspect_region", "move_to_named_pose"]


def test_fallback_stops_after_motion_failure():
    """집기를 보낸 뒤 GRASP_FAILED — 팔이 움직였으므로 다른 방향으로 다시 집으러 가지 않음 (#159 E 리뷰 P1)."""
    backend = FakeBackend({"pick_object": [ActionResult(False, error_code="GRASP_FAILED"), ActionResult(True)]})
    result = Runner(backend, schema=SCHEMA).run(FALLBACK)
    assert (result.overall_status, result.error_code) == ("FAILED", "GRASP_FAILED")
    assert len(backend.calls) == 1
    assert fallback_record(result)["fallback_stopped"] == "MOTION_UNCERTAIN"


def test_fallback_stops_after_response_lost():
    """집기 전송 뒤 응답 유실(백엔드 예외) → 집었는지 모름 → 다음 대안 없음, 태스크 실패 (E 반례 그대로)."""
    calls = []

    def lost_then_ok(action, params, timeout_sec=None):
        calls.append(params.get("approach"))
        if len(calls) == 1:
            raise ConnectionError("전송 후 응답 유실")
        return ActionResult(True)

    result = Runner(lost_then_ok, schema=SCHEMA).run(FALLBACK)
    assert (result.overall_status, result.error_code) == ("FAILED", "BACKEND_ERROR")
    assert calls == ["top"]
    assert fallback_record(result)["fallback_stopped"] == "RESPONSE_LOST"
    record = fallback_record(result)
    assert "다음 대안 안 보냄(RESPONSE_LOST)" in step_console.end_line(result.run_id, record, False)[1]


def test_fallback_stops_after_successful_move_then_failure():
    """앞 대안에서 이동은 성공 → 인식 실패: 이미 팔을 움직였으므로 다음 대안의 이동을 보내지 않음 (E 반례 그대로)."""
    task = {"task_id": "t", "sequence": [{"id": "s1", "action": "fallback", "options": [
        [{"id": "s1.a1", "action": "move_to_named_pose", "params": {"pose_name": "view_a"}},
         {"id": "s1.a2", "action": "inspect_region", "params": {"region": "drawer_top"}}],
        [{"id": "s1.b1", "action": "move_to_named_pose", "params": {"pose_name": "view_b"}}]]}]}
    backend = FakeBackend({"inspect_region": ActionResult(False, error_code="NOT_VISIBLE")})
    result = Runner(backend, schema=SCHEMA).run(task)
    assert (result.overall_status, result.error_code) == ("FAILED", "NOT_VISIBLE")
    assert [p.get("pose_name") for a, p in backend.calls if a == "move_to_named_pose"] == ["view_a"]
    assert fallback_record(result)["fallback_stopped"] == "MOTION_UNCERTAIN"


def test_fallback_step_retry_does_not_rerun_after_motion():
    """fallback 스텝에 retry 가 있어도 팔을 움직인 실패면 처음 대안부터 다시 보내지 않음."""
    task = {"task_id": "t", "sequence": [{**FALLBACK["sequence"][0], "on_failure": "retry", "retry": 2}]}
    backend = FakeBackend({"pick_object": ActionResult(False, error_code="GRASP_FAILED")})
    result = Runner(backend, schema=SCHEMA).run(task)
    assert result.overall_status == "FAILED" and len(backend.calls) == 1


def test_fallback_all_fail_reports_last_code():
    backend = FakeBackend({"pick_object": ActionResult(False, error_code="YAW_INVALID")})
    result = Runner(backend, schema=SCHEMA).run(FALLBACK)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "YAW_INVALID", "s1")
    assert len(backend.calls) == 2


def test_motion_backend_exception_is_not_retried():
    """팔을 움직이는 동작의 백엔드 예외 = 보낸 뒤 끊겼을 수 있음 → retry 가 있어도 다시 보내지 않음."""
    task = {"task_id": "t", "sequence": [{"id": "s1", "action": "move_to_named_pose", "params": {"pose_name": "home"},
                                          "on_failure": "retry", "retry": 2}]}
    calls = []

    def broken(action, params, timeout_sec=None):
        calls.append(action)
        raise ConnectionError("응답 끊김")

    result = Runner(broken, schema=SCHEMA).run(task)
    assert (result.overall_status, result.error_code, len(calls)) == ("FAILED", "BACKEND_ERROR", 1)
    assert result.steps[0]["retry_stopped"] == "RESPONSE_LOST"


def lists(**values):
    """for_each 의 in 은 "$변수" 만 받으므로 리스트를 set_var 스텝으로 먼저 만든다."""
    return [{"id": f"v_{k}", "action": "set_var", "params": {"name": k, "value": v}} for k, v in values.items()]


def test_for_each_restores_previous_value_of_as_variable():
    """as 변수는 루프 안에서만 — 루프 전 값 복구, 없던 이름은 지움 (#159 E 리뷰 P2)."""
    task = {"task_id": "t", "sequence": [
        *lists(ab=["a", "b"], xs=["x"]),
        {"id": "s0", "action": "set_var", "params": {"name": "d", "value": "original"}},
        {"id": "s1", "action": "for_each", "in": "$ab", "as": "d", "body": [
            {"id": "s1.1", "action": "speak", "params": {"text": "{{d}}"}}]},
        {"id": "s2", "action": "for_each", "in": "$xs", "as": "fresh", "body": [{"id": "s2.1", "action": "speak"}]}]}
    backend = FakeBackend()
    result = Runner(backend, schema=SCHEMA).run(task)
    assert result.overall_status == "COMPLETED"
    assert [p.get("text") for _, p in backend.calls] == ["a", "b", None]
    assert result.blackboard["d"] == "original" and "fresh" not in result.blackboard


def test_nested_for_each_same_name_restores_outer_value_even_on_failure():
    task = {"task_id": "t", "sequence": [*lists(outer=["o1", "o2"], inner=["i1"], zs=["z"]),
        {"id": "s1", "action": "for_each", "in": "$outer", "as": "d", "body": [
        {"id": "s1.1", "action": "for_each", "in": "$inner", "as": "d", "body": [{"id": "s1.1.1", "action": "speak"}]},
        {"id": "s1.2", "action": "speak", "params": {"text": "{{d}}"}}]},
        {"id": "s2", "action": "for_each", "in": "$zs", "as": "d", "body": [
            {"id": "s2.1", "action": "pick_object"}]}]}
    backend = FakeBackend({"pick_object": ActionResult(False, error_code="GRASP_FAILED")})
    result = Runner(backend, schema=SCHEMA).run(task)
    assert [p["text"] for a, p in backend.calls if a == "speak" and "text" in p] == ["o1", "o2"]   # 바깥 값 그대로
    assert result.overall_status == "FAILED" and "d" not in result.blackboard                       # 실패해도 복구


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


def test_report_nested_loops_attach_each_child_once():
    """중첩 반복 2×2 의 스킬 하위 동작 4개가 보고서에도 정확히 4개, 실제 부모 밑에 (#159 E 리뷰 P2)."""
    from ready2go_runner.core import run_report
    task = {"task_id": "t", "sequence": [*lists(outer=["a", "b"], inner=["x", "y"]),
        {"id": "s1", "action": "for_each", "in": "$outer", "as": "o", "body": [
        {"id": "s1.1", "action": "for_each", "in": "$inner", "as": "i", "body": [
            {"id": "s1.1.1", "skill": "open_drawer", "params": {"drawer_id": "{{o}}{{i}}"}}]}]}]}
    onto = {"skills": {"open_drawer": {"kind": "primitive", "params": {"drawer_id": "Drawer"}, "pre": [], "effect": [],
                                       "expand": [{"action": "drawer_control", "params": {"drawer_id": "$drawer_id"}}]}},
            "state": {}}
    store = MemoryLogStore()
    result = Runner(FakeBackend(), schema=SCHEMA, ontology=onto, log_store=store).run(task)
    saved = store.read_run(result.run_id)
    assert sum(1 for s in saved["steps"] if s.get("parent")) == 4
    skills = [row for row in run_report.rows(saved["steps"]) if row.step.get("id") == "s1.1.1"]
    assert len(skills) == 4 and all(len(row.children) == 1 for row in skills)
    assert [row.step["params"]["drawer_id"] for row in skills] == ["ax", "ay", "bx", "by"]
    assert [row.children[0].step["params"]["drawer_id"] for row in skills] == ["ax", "ay", "bx", "by"]
