"""#152 재개 대기 (계약안 v0, 승인 전 제안): 중단 → 실행 보존(SUSPENDED) → 복구(resume) → 같은 정지 사건으로
resume_run → 중단된 스텝부터 이어 실행. 앞 스텝은 다시 보내지 않고, 중단된 스킬의 effect 는 한 번만 반영된다.
거절(과거·중복·만료·복구 전·관측 불일치) 때는 로봇 동작 없음. 실물·계약 연결 전 core 동작만 확인한다."""
import pytest

from ready2go_runner.core.backend import RosBackend
from ready2go_runner.core.interpreter import (ActionResult, ResumeRejected, Runner, HALT_EVENT_MISMATCH,
                                              NOT_RECOVERED, NOTHING_TO_RESUME, RESUME_EXPIRED, RESUME_PENDING)
from ready2go_runner.core.logstore import MemoryLogStore

from test_interpreter import FakeBackend, FakeClock  # noqa: E402
from test_tasks import ONTOLOGY, PICK_SENT, SCHEMA, SPEAK_ACTION, TASK, MockRobot  # noqa: E402

FOUND = "지우개를 찾아 올게요"


def suspended_at_pick(clock=None):
    """find_item 의 집기(s5.1, if s5 안)에서 비상정지 → 재개 대기."""
    robot = MockRobot(fail={"pick_object": ["ESTOP"]})
    store = MemoryLogStore()
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY, log_store=store, resumable=True,
                    **({"clock": clock} if clock else {}))
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(TASK)
    return runner, robot, store, result


def test_estop_keeps_run_suspended_without_finally():
    runner, robot, store, result = suspended_at_pick()
    assert (result.overall_status, result.error_code) == ("SUSPENDED", "ESTOP")
    assert runner.halted and runner.halt_event_id
    assert runner.suspended == {"run_id": result.run_id, "task_id": "find_item", "event_id": runner.halt_event_id,
                                "code": "ESTOP", "from_step": "s5.1", "recovered": False}
    assert robot.sent[-1] == "/skills/pick_object"                       # finally(닫기·홈) 안 보냄
    assert not any(s["id"].startswith("f") for s in result.steps)
    run = store.read_run(result.run_id)["run"]
    assert run["overall_status"] == "SUSPENDED" and run["halts"][0]["step"] == "s5.1"


def test_resume_reruns_interrupted_skill_then_continues_and_finishes():
    runner, robot, store, first = suspended_at_pick()
    event, before = runner.halt_event_id, len(robot.sent)
    runner.resume()                                                     # 복구 (B 복구 성공 뒤 잠금 해제)
    assert runner.suspended["recovered"] is True
    result = runner.resume_run(event)
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    assert result.run_id == first.run_id                                 # 같은 실행을 이어 감
    resumed = robot.sent[before:]
    assert resumed == [*PICK_SENT, "/skills/place_object", SPEAK_ACTION,  # 집기 처음부터 → 놓기 → 안내
                       "/skills/drawer_control", SPEAK_ACTION, "/skills/move_to_named_pose"]   # finally
    assert robot.sent.count("/skills/drawer_control") == 2               # 열기 1번(중단 전) + 닫기 1번 — 다시 안 엶
    assert robot.spoken.count(FOUND) == 1                                # 앞 스텝 다시 안 보냄
    state = runner.state
    assert state["located_in"]["eraser"] == "handover_zone" and state["gripper"]["robot"] == "empty"
    assert state["open"]["drawer_top"] is False
    assert runner.suspended is None and runner.halt_event_id is None
    saved = store.read_run(result.run_id)
    assert saved["run"]["overall_status"] == "COMPLETED" and "resumed_at" in saved["run"]["halts"][0]
    assert [s["seq"] for s in saved["steps"]] == list(range(len(saved["steps"])))   # 이어서 기록, 빠짐 없음
    assert [s["id"] for s in saved["steps"]].count("s5.1") == 2          # 중단된 시도 + 재개 시도
    from ready2go_runner.core import run_report
    text = run_report.to_text(saved)
    assert "✅ 성공" in text and "ESTOP · s5.1 → 재개" in text


def test_resume_before_recovery_is_rejected_and_kept():
    runner, robot, _, _ = suspended_at_pick()
    before = len(robot.sent)
    with pytest.raises(ResumeRejected) as e:
        runner.resume_run(runner.halt_event_id)
    assert e.value.reasons == [NOT_RECOVERED]
    assert len(robot.sent) == before and runner.suspended is not None


def test_stale_event_and_halt_again_after_recovery_are_rejected():
    runner, robot, _, _ = suspended_at_pick()
    old = runner.halt_event_id
    runner.resume()
    runner.halt("ESTOP")                                                # 복구 뒤 다시 멈춤 → 새 사건
    assert runner.halt_event_id != old
    with pytest.raises(ResumeRejected) as e:
        runner.resume_run(old)
    assert e.value.reasons == [HALT_EVENT_MISMATCH, NOT_RECOVERED]
    runner.resume()
    assert runner.resume_run(runner.halt_event_id).overall_status == "COMPLETED"   # 새 사건으로 복구·재개하면 됨


def test_resume_after_window_expires_is_rejected():
    clock = FakeClock()
    runner, robot, _, _ = suspended_at_pick(clock)
    runner.resume()
    clock.now += 31                                                     # 기본 30 s [팀 확정 필요]
    with pytest.raises(ResumeRejected) as e:
        runner.resume_run(runner.halt_event_id)
    assert e.value.reasons == [RESUME_EXPIRED]


def test_duplicate_resume_after_resumed_has_nothing_to_resume():
    runner, robot, _, _ = suspended_at_pick()
    event = runner.halt_event_id
    runner.resume()
    runner.resume_run(event)
    before = len(robot.sent)
    with pytest.raises(ResumeRejected) as e:
        runner.resume_run(event)
    assert e.value.reasons == [NOTHING_TO_RESUME] and len(robot.sent) == before


def test_observation_blockers_reject_without_motion():
    """호출 쪽(노드)이 관측으로 상태 불일치를 찾으면 거절 — 로봇 동작 없음, 보존 유지."""
    runner, robot, _, _ = suspended_at_pick()
    runner.resume()
    before = len(robot.sent)
    with pytest.raises(ResumeRejected) as e:
        runner.resume_run(runner.halt_event_id, blockers=["STATE_MISMATCH"])
    assert e.value.reasons == ["STATE_MISMATCH"] and len(robot.sent) == before
    assert runner.suspended is not None


def test_interrupted_skill_pre_is_rechecked_before_resume():
    """보존 중 상태가 바뀌어 중단된 스킬의 pre 가 안 맞으면 거절 (예: 상태 초기화로 서랍 닫힘)."""
    runner, robot, _, _ = suspended_at_pick()
    runner.resume()
    runner.reset_state()
    with pytest.raises(ResumeRejected) as e:
        runner.resume_run(runner.halt_event_id)
    assert e.value.reasons == ["PRE_UNMET"]


def test_new_task_while_suspended_is_refused():
    runner, robot, _, _ = suspended_at_pick()
    runner.resume()
    before = len(robot.sent)
    result = runner.run(TASK)
    assert (result.overall_status, result.error_code) == ("ABORTED", RESUME_PENDING)
    assert len(robot.sent) == before and runner.suspended is not None


def test_discard_ends_aborted_without_motion_then_new_task_runs():
    runner, robot, store, first = suspended_at_pick()
    runner.resume()
    before = len(robot.sent)
    result = runner.discard_suspended()
    assert (result.overall_status, result.error_code, result.run_id) == ("ABORTED", "ESTOP", first.run_id)
    assert [n for n in robot.sent[before:] if n.startswith("/skills/") and n != SPEAK_ACTION] == []   # 닫기·홈 없음
    assert next(s for s in result.steps if s["id"] == "f2")["status"] == "SKIPPED"
    assert "discarded_at" in store.read_run(first.run_id)["run"]["halts"][0]
    assert runner.suspended is None and runner.discard_suspended() is None


def test_halt_between_steps_resumes_from_next_step():
    """끝난 스텝 뒤 중단 요청 → 다음 스텝 시작 전에 멈춤 → 재개는 그 다음 스텝부터 (끝난 안내 다시 안 함)."""
    robot = MockRobot()
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY, resumable=True)
    send = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])

    def execute(action, params, timeout):
        reply = send(action, params, timeout)
        if action == "speak" and params.get("text") == FOUND:
            runner.halt()                                               # 음성 "멈춰"
        return reply
    runner.execute = execute
    first = runner.run(TASK)
    assert first.overall_status == "SUSPENDED" and runner.suspended["from_step"] == "s3"
    runner.resume()
    assert runner.resume_run(runner.halt_event_id).overall_status == "COMPLETED"
    assert robot.spoken.count(FOUND) == 1


def test_halt_inside_loop_is_not_kept_for_resume():
    """반복 안에서 멈추면 재개 위치를 보장할 수 없으므로 보존하지 않고 지금처럼 ABORTED."""
    task = {"task_id": "t", "sequence": [
        {"id": "s0", "action": "set_var", "params": {"name": "xs", "value": ["a", "b"]}},
        {"id": "s1", "action": "for_each", "in": "$xs", "as": "x", "body": [{"id": "s1.1", "action": "pick_object"}]}]}
    runner = Runner(FakeBackend({"pick_object": ActionResult(False, error_code="ESTOP")}), schema=SCHEMA,
                    resumable=True)
    result = runner.run(task)
    assert (result.overall_status, result.error_code) == ("ABORTED", "ESTOP") and runner.suspended is None


def test_default_runner_does_not_suspend():
    robot = MockRobot(fail={"pick_object": ["ESTOP"]})
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    assert runner.run(TASK).overall_status == "ABORTED" and runner.suspended is None
