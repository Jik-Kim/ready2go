"""#10-4 /runner/status 내용 (ROS 비의존)."""
from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.runner_status import build_status


def test_idle_before_any_run():
    assert build_status(False, False, None, None, None, None, None, False) == {
        "phase": "idle", "task_id": None, "current_step": None, "halt_code": None, "log_store": "mongo", "last": None,
        "halt": None}


def test_running_shows_task_and_current_step():
    status = build_status(True, False, None, "fetch", "s3.e2", None, None, True)
    assert (status["phase"], status["task_id"], status["current_step"], status["log_store"]) == (
        "running", "fetch", "s3.e2", "jsonl")


def test_halted_after_estop_with_last_result():
    seen = {}

    def backend(action, params, timeout_sec):
        seen["step"] = runner.current_step                       # 실행 중 현재 스텝
        runner.halt()
        return ActionResult(True)

    runner = Runner(backend)
    result = runner.run({"task_id": "t", "sequence": [{"id": "s1", "action": "speak", "params": {"text": "x"}}]})
    status = build_status(False, runner.halted, "HALTED", None, runner.current_step, result, "t", False)
    assert seen["step"] == "s1"
    assert (status["phase"], status["halt_code"]) == ("halted", "HALTED")
    assert status["last"]["overall_status"] == "ABORTED" and status["last"]["run_id"] == result.run_id


# ---- halt: 정지 요청과 실제 정지 확인 구분 (계약안, #152·#187·FR-SAF-01) ----
SPEAK = {"id": "s1", "action": "speak", "params": {"text": "x"}}
MOVE = {"id": "s2", "action": "move_to_named_pose", "params": {"pose_name": "home"}}


def stop_during_move(final_code, source="voice"):
    """move 가 진행 중일 때 정지 요청 → 백엔드가 final_code 로 끝냄. 요청 직후·끝난 뒤 halt 요약을 돌려준다."""
    seen = {}

    def backend(action, params, timeout_sec):
        if action == "move_to_named_pose":
            runner.halt(source=source)
            seen["during"] = runner.halt_summary
            return ActionResult(False, error_code=final_code)
        return ActionResult(True)

    runner = Runner(backend)
    runner.on_halt = lambda: 1                  # 진행 중이던 goal 1개에 취소 요청 (RosClients.cancel_all)
    result = runner.run({"task_id": "t", "sequence": [SPEAK, MOVE]})
    return seen["during"], runner.halt_summary, result


def test_voice_stop_is_requested_then_confirmed_by_backend_cancel():
    during, after, result = stop_during_move("CANCELED")
    assert (during["stop"], during["stop_code"], during["stopped_at"], during["locked"]) == ("requested", None, None, True)
    assert (during["code"], during["cause"], during["source"], during["canceled_goals"]) == ("HALTED", "stop", "voice", 1)
    assert (after["stop"], after["stop_code"]) == ("confirmed", "CANCELED") and after["stopped_at"]
    assert after["event_id"] == during["event_id"] and after["requested_at"] == during["requested_at"]
    assert result.overall_status == "ABORTED"


def test_no_stop_confirmation_is_unconfirmed_not_confirmed():
    _, after, _ = stop_during_move("STOP_UNCONFIRMED")
    assert (after["stop"], after["stop_code"], after["code"], after["locked"]) == (
        "unconfirmed", "STOP_UNCONFIRMED", "HALTED", True)


def test_halt_while_idle_has_nothing_to_stop():
    runner = Runner(lambda a, p, t: ActionResult(True))
    runner.on_halt = lambda: 0
    runner.halt(source="service")
    summary = runner.halt_summary
    assert (summary["stop"], summary["canceled_goals"], summary["stop_code"], summary["source"]) == (
        "none", 0, None, "service")


def test_halt_between_steps_has_nothing_to_stop():
    def backend(action, params, timeout_sec):
        runner.halt(source="voice")             # speak 가 끝난 뒤(취소할 goal 없음) → 다음 스텝 전에 멈춤
        return ActionResult(True)

    runner = Runner(backend)
    runner.on_halt = lambda: 0
    runner.run({"task_id": "t", "sequence": [SPEAK, MOVE]})
    assert (runner.halt_summary["stop"], runner.halt_summary["stop_code"]) == ("none", "HALTED")


def test_backend_safety_stop_is_confirmed_with_its_cause():
    for code, cause in (("ESTOP", "estop"), ("OBJECT_DROPPED", "halt_motion")):
        runner = Runner(lambda a, p, t, code=code: ActionResult(a != "move_to_named_pose", error_code=code))
        runner.on_halt = lambda: 0              # 백엔드가 이미 끝낸 뒤 잠금 → 취소할 goal 없음
        runner.run({"task_id": "t", "sequence": [SPEAK, MOVE]})
        summary = runner.halt_summary
        assert (summary["source"], summary["code"], summary["cause"], summary["stop"], summary["stop_code"]) == (
            "backend", code, cause, "confirmed", code)


def test_halt_is_null_after_unlock_and_passed_through_status():
    _, after, result = stop_during_move("CANCELED")
    assert build_status(False, True, "HALTED", None, None, result, "t", False, halt=after)["halt"] == after
    runner = Runner(lambda a, p, t: ActionResult(True))
    runner.halt()
    runner.resume()
    assert runner.halt_summary is None
