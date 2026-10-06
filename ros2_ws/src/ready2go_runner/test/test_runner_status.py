"""#10-4 /runner/status 내용 (ROS 비의존)."""
from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.runner_status import build_status


def test_idle_before_any_run():
    assert build_status(False, False, None, None, None, None, None, False) == {
        "phase": "idle", "task_id": None, "current_step": None, "halt_code": None, "log_store": "mongo", "last": None}


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
