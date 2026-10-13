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
    assert (during["stop"], during["response_code"], during["response_received_at"], during["locked"]) == ("requested", None, None, True)
    assert (during["code"], during["cause"], during["source"], during["canceled_goals"]) == ("HALTED", "stop", "voice", 1)
    assert (after["stop"], after["response_code"]) == ("confirmed", "CANCELED") and after["response_received_at"]
    assert after["event_id"] == during["event_id"] and after["requested_at"] == during["requested_at"]
    assert result.overall_status == "ABORTED"


def test_no_stop_confirmation_is_unconfirmed_not_confirmed():
    _, after, _ = stop_during_move("STOP_UNCONFIRMED")
    assert (after["stop"], after["response_code"], after["code"], after["locked"]) == (
        "unconfirmed", "STOP_UNCONFIRMED", "HALTED", True)


def test_halt_while_idle_has_nothing_to_stop():
    runner = Runner(lambda a, p, t: ActionResult(True))
    runner.on_halt = lambda: 0
    runner.halt(source="service")
    summary = runner.halt_summary
    assert (summary["stop"], summary["canceled_goals"], summary["response_code"], summary["source"]) == (
        "none", 0, None, "service")


def test_halt_between_steps_has_nothing_to_stop():
    def backend(action, params, timeout_sec):
        runner.halt(source="voice")             # speak 가 끝난 뒤(취소할 goal 없음) → 다음 스텝 전에 멈춤
        return ActionResult(True)

    runner = Runner(backend)
    runner.on_halt = lambda: 0
    runner.run({"task_id": "t", "sequence": [SPEAK, MOVE]})
    assert (runner.halt_summary["stop"], runner.halt_summary["response_code"]) == ("none", None)   # Runner 안 확인은 백엔드 응답 아님


def test_backend_safety_stop_is_confirmed_with_its_cause():
    for code, cause in (("ESTOP", "estop"), ("OBJECT_DROPPED", "halt_motion")):
        runner = Runner(lambda a, p, t, code=code: ActionResult(a != "move_to_named_pose", error_code=code))
        runner.on_halt = lambda: 0              # 백엔드가 이미 끝낸 뒤 잠금 → 취소할 goal 없음
        runner.run({"task_id": "t", "sequence": [SPEAK, MOVE]})
        summary = runner.halt_summary
        assert (summary["source"], summary["code"], summary["cause"], summary["stop"], summary["response_code"]) == (
            "backend", code, cause, "confirmed", code)


def test_halt_is_null_after_unlock_and_passed_through_status():
    _, after, result = stop_during_move("CANCELED")
    assert build_status(False, True, "HALTED", None, None, result, "t", False, halt=after)["halt"] == after
    runner = Runner(lambda a, p, t: ActionResult(True))
    runner.halt()
    runner.resume()
    assert runner.halt_summary is None


def test_halt_belongs_to_this_boot_run_and_event():
    """E #152 야간 검토: 같은 기동(boot_id)·실행(run_id)·사건(event_id)의 응답만. 실행 사이 요청은 run_id null."""
    during, after, result = stop_during_move("CANCELED")
    assert during["run_id"] == after["run_id"] == result.run_id and during["boot_id"] == after["boot_id"]
    idle = Runner(lambda a, p, t: ActionResult(True))
    idle.halt(source="service")
    assert idle.halt_summary["run_id"] is None and idle.halt_summary["boot_id"] != after["boot_id"]   # 새 기동 = 새 boot_id


def test_restop_refused_request_and_late_events_do_not_change_the_answer():
    """다시 정지·잠긴 동안 새 요청(거절 실행)·같은 사건의 두 번째 기록은 첫 사건·첫 응답을 바꾸지 않음 —
    confirmed·unconfirmed 는 늦은 응답으로 뒤집히지 않는다(늦은 백엔드 결과는 RosClients 가 이미 STOP_UNCONFIRMED 로 끝낸 뒤라 오지 않음)."""
    def backend(action, params, timeout_sec):
        if action == "move_to_named_pose":
            runner.halt(source="voice")
            return ActionResult(False, error_code="STOP_UNCONFIRMED")
        return ActionResult(True)

    runner = Runner(backend)
    runner.on_halt = lambda: 1
    runner.run({"task_id": "t", "sequence": [SPEAK, MOVE]})
    first = runner.halt_summary
    runner.halt(source="voice")                 # 다시 "멈춰" (잠긴 채) → 같은 사건
    refused = runner.run({"task_id": "t2", "sequence": [SPEAK]})   # 잠긴 동안 새 요청 → 로봇 동작 없이 거절
    assert refused.overall_status == "ABORTED" and refused.run_id != first["run_id"]
    assert runner.halt_summary == first and first["stop"] == "unconfirmed"


def stop_then(reply, steps=(SPEAK, MOVE)):
    """move 진행 중 정지 요청 → reply() 가 백엔드 결과(또는 예외). 끝난 뒤 halt 요약."""
    def backend(action, params, timeout_sec):
        if action == "move_to_named_pose":
            runner.halt(source="voice")
            return reply()
        return ActionResult(True)

    runner = Runner(backend)
    runner.on_halt = lambda: 1
    result = runner.run({"task_id": "t", "sequence": list(steps), "finally": [{"id": "f1", "action": "speak",
                                                                              "params": {"text": "멈췄어요"}}]})
    return runner.halt_summary, result


def test_no_backend_result_is_never_confirmed():
    """#259 E 리뷰 P1: 백엔드 최종 결과 없이 Runner 안에서 멈춘 기록은 confirmed·수신 시각을 만들지 않는다."""
    def lost():
        raise ConnectionError("응답 유실")
    adapter_timeout = lambda: ActionResult(False, {"no_backend_result": True}, error_code="STOP_UNCONFIRMED")   # noqa: E731
    for reply, steps in ((lost, (SPEAK, MOVE)),                 # E 재현: 진행 중 동작에서 통신 예외
                         (lost, (MOVE,)),                       # 마지막 스텝 예외 → finally 진입 전 확인
                         (adapter_timeout, (SPEAK, MOVE))):     # 어댑터가 5 s 안에 결과를 못 받음
        halt, result = stop_then(reply, steps)
        assert result.overall_status == "ABORTED"
        assert (halt["stop"], halt["response_code"], halt["response_received_at"]) == ("unconfirmed", None, None), halt


def test_backend_final_results_are_answers():
    """백엔드가 돌려준 최종 결과만 응답: CANCELED → confirmed, B 의 STOP_UNCONFIRMED → unconfirmed(코드·시각 있음),
    취소 직전에 성공으로 끝남 → confirmed(코드 null)."""
    for reply, stop, code in ((lambda: ActionResult(False, error_code="CANCELED"), "confirmed", "CANCELED"),
                              (lambda: ActionResult(False, error_code="STOP_UNCONFIRMED"), "unconfirmed", "STOP_UNCONFIRMED"),
                              (lambda: ActionResult(True), "confirmed", None)):
        halt, _ = stop_then(reply)
        assert (halt["stop"], halt["response_code"]) == (stop, code) and halt["response_received_at"], halt


def test_tts_cancel_is_not_a_robot_stop_answer():
    """#259 D 리뷰 P1: 말하는 중(speak) 정지 → TTS 의 CANCELED 는 로봇 정지 응답이 아님. 취소한 로봇 goal 0 → none."""
    def backend(action, params, timeout_sec):
        if action == "speak":
            runner.halt(source="voice")
            return ActionResult(False, error_code="CANCELED")
        return ActionResult(True)

    runner = Runner(backend)
    runner.on_halt = lambda: 0                  # RosClients.cancel_all: 음성 goal 은 취소하되 세지 않음
    result = runner.run({"task_id": "t", "sequence": [SPEAK, MOVE]})
    halt = runner.halt_summary
    assert result.overall_status == "ABORTED"
    assert (halt["stop"], halt["response_code"], halt["response_received_at"]) == ("none", None, None), halt


def test_backend_original_code_survives_timeout_path():
    """#259 E 리뷰: 시간 초과로 취소를 기다리던 중 정지 요청 → B 최종 CANCELED·성공은 halt 에 원래 코드로,
    실행 기록 코드는 지금처럼 TIMEOUT. 최종 결과가 없으면 null·unconfirmed."""
    cases = (({"backend_code": "CANCELED", "backend_success": False}, "confirmed", "CANCELED"),
             ({"backend_code": "", "backend_success": True}, "confirmed", None),
             ({"no_backend_result": True}, "unconfirmed", None))
    for output, stop, code in cases:
        halt, result = stop_then(lambda o=output: ActionResult(False, o, error_code="TIMEOUT"))
        assert (halt["stop"], halt["response_code"]) == (stop, code), (output, halt)
        assert bool(halt["response_received_at"]) == (stop == "confirmed") and halt["locked"]
        move = next(s for s in result.steps if s["id"] == "s2")
        assert move["error_code"] == "TIMEOUT"   # 실행 기록 정책은 그대로


def test_halt_for_run_id_only_stops_that_run():
    """end_task 대상 확인 뒤 그 실행이 끝나고 새 실행이 시작됐으면 새 실행을 멈추지 않음 (#285 E 리뷰 P2)."""
    seen = {}

    def backend(action, params, timeout_sec):
        seen["other"] = runner.halt(source="voice", run_id="old-run")        # 이미 끝난 실행 대상
        seen["locked_after_other"] = runner.halted
        seen["this"] = runner.halt(source="voice", run_id=runner.active_run_id)
        return ActionResult(True)

    runner = Runner(backend)
    result = runner.run({"task_id": "t", "sequence": [SPEAK]})
    assert (seen["other"], seen["locked_after_other"], seen["this"]) == (False, False, True)
    assert result.overall_status == "ABORTED" and runner.halted
    assert runner.halt(source="voice", run_id=result.run_id) is False      # 실행 사이: 대상 없음


def test_stop_settled_only_when_stop_confirmed_or_nothing_was_moving():
    """보존 작업 폐기 조건 (#285 E 리뷰 P2): confirmed·none 만. unconfirmed 면 폐기 보류."""
    def suspended_after(final_code):
        def backend(action, params, timeout_sec):
            if action == "move_to_named_pose":
                runner.halt(source="voice")
                return ActionResult(False, error_code=final_code)
            return ActionResult(True)
        runner = Runner(backend, resumable=True)
        runner.on_halt = lambda: 1
        result = runner.run({"task_id": "t", "sequence": [SPEAK, MOVE]})
        return runner, result

    runner, result = suspended_after("STOP_UNCONFIRMED")
    assert result.overall_status == "SUSPENDED" and runner.halt_summary["stop"] == "unconfirmed"
    assert runner.stop_settled is False
    runner, result = suspended_after("CANCELED")
    assert result.overall_status == "SUSPENDED" and runner.stop_settled is True
