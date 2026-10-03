"""Runner ↔ LogStore 연결 (#12 로그 6단계): 스텝이 끝날 때마다 저장, 실행 시작·끝 기록, 기록 실패에도 실행 계속."""
from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.logstore import FallbackLogStore, JsonlLogStore, MemoryLogStore

OK = ActionResult(True)


def backend(results: dict | None = None, on_call=None):
    results = results or {}

    def execute(action, params, timeout_sec):
        if on_call:
            on_call(action)
        return results.get(action, OK)
    return execute


TASK = {"task_id": "find_visible", "inputs": {"target": "watch"}, "sequence": [
    {"id": "s1", "action": "drawer_control", "params": {"drawer_id": "drawer_top", "state": "open"}},
    {"id": "s2", "action": "pick_object", "params": {"object_id": "watch#1"}},
    {"id": "s3", "action": "place_object", "params": {"location": "handover_zone"}},
], "finally": [
    {"id": "f1", "action": "move_to_named_pose", "params": {"pose_name": "home"}},
]}


def test_successful_run_is_logged():
    store = MemoryLogStore()
    result = Runner(backend(), log_store=store).run(TASK, inputs={"target": "watch"},
                                                     meta={"backend": "mock", "stt_text": "시계 찾아줘"})
    saved = store.read_run(result.run_id)
    run = saved["run"]
    assert run["task_id"] == "find_visible" and run["inputs"] == {"target": "watch"}       # 입력 명령
    assert run["stt_text"] == "시계 찾아줘" and run["backend"] == "mock"                  # 헤더에 덧붙인 값
    assert run["overall_status"] == "COMPLETED" and "error" not in run
    assert run["started_at"] <= run["ended_at"] and run["total_duration_sec"] >= 0
    assert [(s["seq"], s["id"], s["status"]) for s in saved["steps"]] == [
        (0, "s1", "SUCCESS"), (1, "s2", "SUCCESS"), (2, "s3", "SUCCESS"), (3, "f1", "SUCCESS")]
    assert all(s["started_at"].endswith("Z") and s["run_id"] == result.run_id for s in saved["steps"])
    assert result.log_errors == []


def test_failed_run_logs_error_code_and_finally():
    store = MemoryLogStore()
    result = Runner(backend({"pick_object": ActionResult(False, error_code="GRASP_FAILED")}),
                    log_store=store).run(TASK)
    saved = store.read_run(result.run_id)
    assert saved["run"]["overall_status"] == "FAILED"
    assert saved["run"]["error"] == {"code": "GRASP_FAILED"} and saved["run"]["failed_step"] == "s2"
    assert [(s["id"], s["status"]) for s in saved["steps"]] == [
        ("s1", "SUCCESS"), ("s2", "FAILURE"), ("f1", "SUCCESS")]                       # s3 건너뜀, finally 기록
    assert saved["steps"][1]["error"] == {"code": "GRASP_FAILED"}


def test_steps_are_saved_while_running():
    # 스텝이 끝날 때마다 저장 → 실행 도중(프로그램이 죽어도) 앞 스텝 기록이 남아 있음
    store = MemoryLogStore()
    seen = {}

    def peek(action):
        if action == "place_object":
            run_id = next(iter(store.runs))
            seen["steps"] = [s["id"] for s in store.read_run(run_id)["steps"]]
            seen["status"] = store.read_run(run_id)["run"].get("overall_status")
    Runner(backend(on_call=peek), log_store=store).run(TASK)
    assert seen == {"steps": ["s1", "s2"], "status": None}                              # s3 실행 중, 아직 끝나지 않음


def test_if_children_keep_start_order():
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "if", "cond": {"op": "==", "args": [1, 1]}, "then": [
            {"id": "s1.1", "action": "pick_object", "params": {}},
            {"id": "s1.2", "action": "place_object", "params": {}}]},
        {"id": "s2", "action": "speak", "params": {"text": "끝"}}]}
    store = MemoryLogStore()
    result = Runner(backend(), log_store=store).run(task)
    # if(s1) 는 안쪽 스텝보다 늦게 끝나지만 seq 는 시작 순서
    assert [s["id"] for s in store.read_run(result.run_id)["steps"]] == ["s1", "s1.1", "s1.2", "s2"]
    assert store.read_run(result.run_id)["steps"][0]["branch"] == "then"


def test_safe_home_and_skipped_steps_are_logged():
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "pick_object", "params": {}, "on_failure": "safe_home"}],
        "finally": [{"id": "f1", "action": "drawer_control", "params": {}}]}
    store = MemoryLogStore()
    result = Runner(backend({"pick_object": ActionResult(False, error_code="ESTOP")}), log_store=store).run(task)
    steps = store.read_run(result.run_id)["steps"]
    assert [(s["id"], s["status"]) for s in steps] == [("s1", "FAILURE"), ("f1", "SKIPPED")]  # E-stop: 홈 이동 없음
    assert store.read_run(result.run_id)["run"]["overall_status"] == "ABORTED"

    store2 = MemoryLogStore()
    result2 = Runner(backend({"pick_object": ActionResult(False, error_code="GRASP_FAILED")}),
                     log_store=store2).run(task)
    assert [s["id"] for s in store2.read_run(result2.run_id)["steps"]] == ["s1", "s1.safe_home", "f1"]


def test_refused_runs_are_logged():
    store = MemoryLogStore()
    runner = Runner(backend(), log_store=store)
    invalid = runner.run({"task_id": "bad", "sequence": [{"id": "s1", "action": "while", "max_iter": 1, "body": []}]})
    saved = store.read_run(invalid.run_id)
    assert saved["run"]["overall_status"] == "FAILED" and saved["run"]["error"] == {"code": "TASK_INVALID"}
    assert saved["run"]["problems"] and saved["steps"] == []                            # 왜 안 움직였는지 남음

    runner.halt("ESTOP")
    locked = runner.run(TASK)
    assert store.read_run(locked.run_id)["run"]["overall_status"] == "ABORTED"


def test_log_failure_does_not_stop_run():
    class BrokenStore(MemoryLogStore):
        def write_step(self, doc):
            raise OSError("디스크 가득 참")

    calls = []
    result = Runner(backend(on_call=calls.append), log_store=BrokenStore()).run(TASK)
    assert result.overall_status == "COMPLETED"                                        # 로봇 동작은 끝까지
    assert calls == ["drawer_control", "pick_object", "place_object", "move_to_named_pose"]
    assert len(result.log_errors) == 4 and "OSError" in result.log_errors[0]


def test_db_down_mid_run_falls_back_to_jsonl(tmp_path):
    class DyingDb(MemoryLogStore):
        def __init__(self):
            super().__init__()
            self.writes = 0

        def write_step(self, doc):
            self.writes += 1
            if self.writes > 1:
                raise ConnectionError("DB 연결 끊김")
            super().write_step(doc)

    store = FallbackLogStore(DyingDb(), JsonlLogStore(tmp_path))
    result = Runner(backend(), log_store=store).run(TASK)
    assert result.overall_status == "COMPLETED" and result.log_errors == []           # 폴백은 오류가 아님
    assert store.degraded
    saved = JsonlLogStore(tmp_path).read_run(result.run_id)                             # 파일 하나에 실행 전체
    assert [s["id"] for s in saved["steps"]] == ["s1", "s2", "s3", "f1"]
    assert saved["run"]["overall_status"] == "COMPLETED"


def test_without_log_store_nothing_changes():
    result = Runner(backend()).run(TASK)
    assert result.overall_status == "COMPLETED" and result.run_id and result.log_errors == []
