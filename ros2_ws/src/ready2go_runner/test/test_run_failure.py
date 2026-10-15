"""#376 last.failure — FAILED 의 처음 원인 기록 (C 형식·B 보완·E 확인 10/15).

확인: B make_room 거부(strategy impossible)의 case_id 보존 / impossible 아니면 case_id null / 정리 중 오류가 처음 원인을 덮지 않음 /
정지·성공·시작 전 거절은 null / task_error(NO_FREE_SPACE) 경로 / E 문장 → 없으면 failure_speech 폴백 / runs 문서에도 남김.
"""
import importlib
import sys
import types

import pytest

from ready2go_runner.core import failure_speech, interpreter
from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.logstore import MemoryLogStore

from test_tasks import ONTOLOGY, SCHEMA  # noqa: E402

ROOM_REFUSED = {"pushed": False, "push_vector_m": [0.0, 0.0], "target_after": None,
                "make_room": {"action": "fail", "moved_id": None, "ready_to_pick": False, "reason": "벌린 손가락 자리에 eraser#1",
                              "pushed_ids": [], "pushed_after": [], "case_id": "cluster_front_wall", "strategy": "impossible"}}


def task(finally_steps=None):
    return {"task_id": "t_room", "inputs": {"target": "car_key"},
            "sequence": [{"id": "m1", "action": "nudge_object",
                          "params": {"drawer_id": "drawer_top", "target": {"id": "car_key#1"}, "make_room": True}}],
            "finally": finally_steps if finally_steps is not None else
            [{"id": "f1", "action": "move_to_named_pose", "params": {"pose_name": "home"}}]}


def make(respond):
    store = MemoryLogStore()
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY, log_store=store)
    runner.execute = lambda action, params, timeout=None: respond(runner, action, params) or ActionResult(True, {})
    return runner, store


def refuse_room(output=ROOM_REFUSED, code="NEIGHBOR_TOO_CLOSE"):
    return lambda runner, action, params: ActionResult(False, output, code) if action == "nudge_object" else None


def test_impossible_make_room_refusal_keeps_case_and_falls_back_to_current_sentence(monkeypatch):
    """B make_room 이 움직이기 전 거부(strategy impossible) → case_id·strategy 보존. E 문장이 없으면(조회 None 을 명시 주입 —
    E 원본 설치 여부와 무관, #379 E 리뷰) 지금 정리 전 안내 문장."""
    monkeypatch.setattr(interpreter, "_refusal_text", lambda case_id, strategy: None)
    runner, store = make(refuse_room())
    result = runner.run(task())
    assert (result.overall_status, result.error_code) == ("FAILED", "NEIGHBOR_TOO_CLOSE")
    assert result.failure == {"run_id": result.run_id, "boot_id": runner.boot_id, "code": "NEIGHBOR_TOO_CLOSE",
                              "step": "m1", "action": "nudge_object", "case_id": "cluster_front_wall",
                              "strategy": "impossible", "text": failure_speech.text("NEIGHBOR_TOO_CLOSE", "nudge_object")}
    assert store.read_run(result.run_id)["run"]["failure"] == result.failure          # runs 문서에도


@pytest.mark.parametrize("strategy", ["make_room", "nudge", "remove_top", None])
def test_case_id_only_when_strategy_is_impossible(strategy):
    """[B 보완] 밀다 막힘·미리보기 등 strategy 가 impossible 이 아니면 난제 이름을 실패 이유로 가져오지 않음."""
    output = {**ROOM_REFUSED, "make_room": {**ROOM_REFUSED["make_room"], "strategy": strategy, "action": "sweep"}}
    runner, _ = make(refuse_room(output, "PUSH_BLOCKED"))
    failure = runner.run(task()).failure
    assert (failure["code"], failure["case_id"], failure["strategy"]) == ("PUSH_BLOCKED", None, None)


def test_e_refusal_sentence_is_used_when_registered(monkeypatch):
    """E 원본(ready2go_knowledge.core.refusal_reasons.text)이 문장을 주면 그 문장, None 이면 failure_speech 로."""
    fake = types.ModuleType("ready2go_knowledge.core.refusal_reasons")
    fake.text = lambda case_id, strategy: "손잡이 쪽 벽에 물건이 몰려 있어 꺼낼 수 없어요" \
        if (case_id, strategy) == ("cluster_front_wall", "impossible") else None
    monkeypatch.setitem(sys.modules, "ready2go_knowledge.core.refusal_reasons", fake)
    runner, _ = make(refuse_room())
    assert runner.run(task()).failure["text"] == "손잡이 쪽 벽에 물건이 몰려 있어 꺼낼 수 없어요"
    unknown = {**ROOM_REFUSED, "make_room": {**ROOM_REFUSED["make_room"], "case_id": "not_registered"}}
    runner2, _ = make(refuse_room(unknown))
    failure = runner2.run(task()).failure
    assert failure["case_id"] == "not_registered"                                     # B 가 준 이름은 그대로 기록
    assert failure["text"] == failure_speech.text("NEIGHBOR_TOO_CLOSE", "nudge_object")   # 문장은 폴백


def test_with_the_real_e_catalog_the_registered_sentence_is_used():
    """[#379 E 리뷰] E 원본(#378 knowledge/refusal_reasons.json)이 설치된 조합 — 실제 E text(case_id, "impossible") 결과를 그대로 씀
    (등록 문장이면 그 문장, None 이면 failure_speech). E 원본이 없으면(머지 전) 건너뜀."""
    try:
        reasons = importlib.import_module("ready2go_knowledge.core.refusal_reasons")
    except ImportError:
        pytest.skip("E #378 (refusal_reasons) 머지 전")
    runner, _ = make(refuse_room())
    expected = reasons.text("cluster_front_wall", "impossible") or failure_speech.text("NEIGHBOR_TOO_CLOSE", "nudge_object")
    assert runner.run(task()).failure["text"] == expected


def test_cleanup_error_does_not_replace_the_first_cause():
    """정리(finally) 중 다른 오류가 나도 처음 거부(sequence) 원인을 남김."""
    def respond(runner, action, params):
        if action == "nudge_object":
            return ActionResult(False, ROOM_REFUSED, "NEIGHBOR_TOO_CLOSE")
        if action == "move_to_named_pose":
            return ActionResult(False, None, "MOVE_FAILED")
        return None
    runner, _ = make(respond)
    result = runner.run(task())
    assert (result.error_code, result.failure["code"], result.failure["step"]) == \
        ("NEIGHBOR_TOO_CLOSE", "NEIGHBOR_TOO_CLOSE", "m1")


def test_stop_success_and_rejection_have_no_failure():
    """정지·비상정지(ABORTED)·성공·시작 전 거절은 failure null — 정지를 배치 거부로 설명하지 않음."""
    def stop(runner, action, params):
        if action == "nudge_object":
            runner.halt(source="voice")
            return ActionResult(False, ROOM_REFUSED, "CANCELED")
        return None
    runner, store = make(stop)
    aborted = runner.run(task())
    assert aborted.overall_status == "ABORTED" and aborted.failure is None
    assert "failure" not in store.read_run(aborted.run_id)["run"]
    ok_runner, _ = make(lambda r, a, p: None)
    assert ok_runner.run(task()).failure is None
    bad = ok_runner.run({"task_id": "bad", "sequence": [{"id": "x", "action": "no_such_action"}]})
    assert bad.overall_status == "FAILED" and bad.failure is None                    # TASK_INVALID — 스텝 원인 없음


def test_task_error_no_free_space_path_is_kept_without_case():
    """실제 find_with_unpack — 치울 물건을 놓을 자리 없음(task_error NO_FREE_SPACE @ s7.0c)도 failure 에.
    그 스텝(place check_only) 결과에 impossible 난제가 없으면 case_id·strategy null, text null(E 코드 안내)."""
    from test_unpack_task import NoRoomScene, _run_with
    runner, _, result = _run_with(NoRoomScene("plate_over_eraser"), "eraser")
    assert (result.overall_status, result.error_code) == ("FAILED", "NO_FREE_SPACE")
    assert result.failure == {"run_id": result.run_id, "boot_id": runner.boot_id, "code": "NO_FREE_SPACE", "step": "s7.0c",
                              "action": "place_object", "case_id": None, "strategy": None, "text": None}


def test_new_run_replaces_the_old_failure_and_boot_differs():
    """다음 실행 결과로 바뀜(성공이면 null) — 지난 실패를 지금 실패처럼 보이지 않게. 새 Runner(재기동)는 boot_id 가 다름."""
    runner, _ = make(refuse_room())
    first = runner.run(task())
    runner.execute = lambda action, params, timeout=None: ActionResult(True, {})
    second = runner.run(task())
    assert first.failure["run_id"] == first.run_id and second.failure is None
    other, _ = make(refuse_room())
    assert other.run(task()).failure["boot_id"] != first.failure["boot_id"]


def test_real_unpack_flow_make_room_refusal_reaches_failure_through_backend():
    """실제 find_with_unpack — 차키 집기 전 판단이 NEIGHBOR_TOO_CLOSE → 공간 만들기(s8.m5)를 B 가 움직이기 전 거부
    (strategy impossible, case_id cluster_front_wall) → mock ROS 백엔드(RosBackend)를 거친 실패 결과 JSON 에서 case_id 보존 →
    정리(닫기·홈) 뒤에도 처음 원인은 s8.m5."""
    from test_unpack_task import NeighborScene, _run_with

    class Refuses(NeighborScene):
        def nudge(self, params):
            if not params.get("make_room"):
                return super().nudge(params)
            return False, "NEIGHBOR_TOO_CLOSE", {**ROOM_REFUSED, "make_room": {**ROOM_REFUSED["make_room"]}}
    runner, robot, result = _run_with(Refuses(), "car_key")
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "NEIGHBOR_TOO_CLOSE", "s8.m5")
    assert (result.failure["step"], result.failure["action"], result.failure["case_id"], result.failure["strategy"]) == \
        ("s8.m5", "nudge_object", "cluster_front_wall", "impossible")
    assert any(a == "drawer_control" and p.get("state") == "close" for a, p in robot.calls)   # 정리는 그대로
    assert robot.skills.scene.delivered == []
