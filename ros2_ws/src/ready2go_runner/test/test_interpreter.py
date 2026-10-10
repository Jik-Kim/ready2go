import pytest

from ready2go_runner.core.interpreter import ActionResult, Runner


class FakeClock:
    """테스트용 시계. 실제로 기다리지 않고 시간을 앞으로 돌린다."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeBackend:
    """로봇 없이 원자 동작을 흉내 낸다. results 에 동작별 결과를 미리 넣어 두고, 호출 기록을 남긴다.
    결과를 리스트로 주면 호출할 때마다 앞에서부터 하나씩 쓴다(마지막 값은 계속 유지).
    clock·durations 를 주면 동작마다 그 시간(초)만큼 시계를 앞으로 돌린다(리스트도 같은 방식)."""

    def __init__(self, results: dict | None = None, clock: FakeClock | None = None,
                 durations: dict | None = None):
        self.results = results or {}
        self.clock, self.durations = clock, durations or {}
        self.calls: list[tuple[str, dict]] = []
        self.timeouts: list[float | None] = []

    def __call__(self, action: str, params: dict, timeout_sec: float | None = None) -> ActionResult:
        self.calls.append((action, params))
        self.timeouts.append(timeout_sec)
        if self.clock:
            self.clock.now += _next(self.durations.get(action, 0.0))
        return _next(self.results.get(action, ActionResult(success=True)))


def _next(value):
    """리스트면 앞에서부터 하나씩 꺼내고 마지막 값은 유지, 아니면 그대로."""
    if isinstance(value, list):
        return value.pop(0) if len(value) > 1 else value[0]
    return value


SCAN = {"target_found": True, "target": {"id": "watch#1"}, "candidates": [], "visible_count": 1}

TASK = {
    "task_id": "find_visible",
    "inputs": {"target": "watch"},
    "sequence": [
        {"id": "s1", "action": "query_ontology", "params": {"item": "$inputs.target"}, "output": "loc"},
        {"id": "s2", "action": "speak", "params": {"text": "{{loc.name_ko|을}} 찾기 시작합니다"}},
        {"id": "s3", "action": "drawer_control", "params": {"drawer_id": "$loc.drawer_id", "state": "open"}},
        {"id": "s4", "action": "inspect_region",
         "params": {"region": "$loc.drawer_id", "search_target": "$inputs.target"}, "output": "scan"},
        {"id": "s5", "action": "pick_object", "params": {"object_id": "$scan.target.id"}},
    ],
}


def backend():
    return FakeBackend({
        "query_ontology": ActionResult(True, {"item": "watch", "name_ko": "시계", "drawer_id": "drawer_top"}),
        "inspect_region": ActionResult(True, SCAN),
    })


def test_sequence_runs_in_order_and_passes_outputs():
    fake = backend()
    result = Runner(fake).run(TASK)

    assert result.overall_status == "COMPLETED"
    assert fake.calls == [
        ("query_ontology", {"item": "watch"}),
        ("speak", {"text": "시계를 찾기 시작합니다"}),
        ("drawer_control", {"drawer_id": "drawer_top", "state": "open"}),
        ("inspect_region", {"region": "drawer_top", "search_target": "watch"}),
        ("pick_object", {"object_id": "watch#1"}),
    ]
    assert [s["status"] for s in result.steps] == ["SUCCESS"] * 5
    assert result.blackboard["scan"] == SCAN


def test_inputs_override_task_defaults():
    fake = backend()
    Runner(fake).run(TASK, inputs={"target": "wallet"})
    assert fake.calls[0] == ("query_ontology", {"item": "wallet"})


def test_set_var_is_handled_by_runner():
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "set_var", "params": {"name": "drawer", "value": "drawer_top"}},
        {"id": "s2", "action": "set_var", "params": {"name": "msg", "value": "{{drawer}} 열기"}},
        {"id": "s3", "action": "speak", "params": {"text": "$msg"}},
    ]}
    fake = FakeBackend()
    result = Runner(fake).run(task)
    assert fake.calls == [("speak", {"text": "drawer_top 열기"})]      # set_var 는 백엔드로 가지 않음
    assert result.blackboard["msg"] == "drawer_top 열기"


def test_action_failure_stops_sequence():
    fake = backend()
    fake.results["drawer_control"] = ActionResult(False, error_code="DRAWER_STUCK")
    result = Runner(fake).run(TASK)

    assert result.overall_status == "FAILED"
    assert result.error_code == "DRAWER_STUCK"
    assert [c[0] for c in fake.calls] == ["query_ontology", "speak", "drawer_control"]   # s4, s5 실행 안 함
    assert result.failed_step == "s3"
    assert result.steps[-1].pop("duration_sec") >= 0
    assert result.steps[-1].pop("started_at").endswith("Z")                 # 시작 시각 (UTC)
    assert result.steps[-1] == {"id": "s3", "action": "drawer_control", "attempts": 1,
                                "params": {"drawer_id": "drawer_top", "state": "open"},
                                "status": "FAILURE", "error_code": "DRAWER_STUCK"}


def test_failure_without_error_code():
    fake = FakeBackend({"speak": ActionResult(False)})
    result = Runner(fake).run({"task_id": "t", "sequence": [
        {"id": "s1", "action": "speak", "params": {"text": "안녕"}}]})
    assert result.error_code == "ACTION_FAILED"


def test_undefined_variable_fails_before_calling_backend():
    fake = FakeBackend()
    result = Runner(fake).run({"task_id": "t", "sequence": [
        {"id": "s1", "action": "pick_object", "params": {"object_id": "$scan.target.id"}}]})

    assert result.overall_status == "FAILED"
    assert result.error_code == "VAR_UNDEFINED"
    assert fake.calls == []                                            # 로봇에 잘못된 값이 가지 않음


# ---- 6단계: if ----

def if_task(found: bool) -> tuple[dict, FakeBackend]:
    """tasks/find_with_unpack.json s8 과 같은 모양: 찾았으면 집어서 전달, 못 찾았으면 안내만."""
    task = {"task_id": "t", "inputs": {"target": "watch"}, "sequence": [
        {"id": "s1", "action": "inspect_region", "params": {"region": "drawer_top"}, "output": "scan"},
        {"id": "s2", "action": "if",
         "cond": {"op": "==", "args": ["$scan.target_found", True]},
         "then": [
             {"id": "s2.1", "action": "pick_object", "params": {"object_id": "$scan.target.id"}},
             {"id": "s2.2", "action": "place_object", "params": {"location": "handover_zone"}}],
         "else": [
             {"id": "s2.3", "action": "speak", "params": {"text": "찾지 못했습니다"}}]},
        {"id": "s3", "action": "speak", "params": {"text": "끝"}},
    ]}
    scan = {"target_found": found, "target": {"id": "watch#1"} if found else None}
    return task, FakeBackend({"inspect_region": ActionResult(True, scan)})


def test_if_then_branch():
    task, fake = if_task(found=True)
    result = Runner(fake).run(task)
    assert result.overall_status == "COMPLETED"
    assert [c[0] for c in fake.calls] == ["inspect_region", "pick_object", "place_object", "speak"]
    assert [(s["id"], s["status"]) for s in result.steps] == [
        ("s1", "SUCCESS"), ("s2", "SUCCESS"), ("s2.1", "SUCCESS"), ("s2.2", "SUCCESS"), ("s3", "SUCCESS")]
    assert result.steps[1]["branch"] == "then"


def test_if_else_branch():
    task, fake = if_task(found=False)
    result = Runner(fake).run(task)
    assert fake.calls[1:] == [("speak", {"text": "찾지 못했습니다"}), ("speak", {"text": "끝"})]
    assert result.steps[1]["branch"] == "else"


def test_if_without_else_does_nothing_when_false():
    task, fake = if_task(found=False)
    del task["sequence"][1]["else"]
    result = Runner(fake).run(task)
    assert result.overall_status == "COMPLETED"
    assert [c[0] for c in fake.calls] == ["inspect_region", "speak"]


def test_nested_if():
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "set_var", "params": {"name": "n", "value": 2}},
        {"id": "s2", "action": "if", "cond": {"op": ">", "args": ["$n", 0]}, "then": [
            {"id": "s2.1", "action": "if", "cond": {"op": "==", "args": ["$n", 2]},
             "then": [{"id": "s2.1.1", "action": "speak", "params": {"text": "둘"}}],
             "else": [{"id": "s2.1.2", "action": "speak", "params": {"text": "둘 아님"}}]}]},
    ]}
    fake = FakeBackend()
    Runner(fake).run(task)
    assert fake.calls == [("speak", {"text": "둘"})]


def test_failure_inside_branch_fails_if_and_stops():
    task, fake = if_task(found=True)
    fake.results["pick_object"] = ActionResult(False, error_code="GRASP_FAILED")
    result = Runner(fake).run(task)
    assert result.overall_status == "FAILED"
    assert result.error_code == "GRASP_FAILED"
    assert [(s["id"], s["status"]) for s in result.steps] == [
        ("s1", "SUCCESS"), ("s2", "FAILURE"), ("s2.1", "FAILURE")]   # s2.2, s3 실행 안 함


def test_if_with_bad_condition_fails():
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "if", "cond": {"op": "==", "args": ["$scan.target_found"]}, "then": []}]}
    result = Runner(FakeBackend()).run(task)
    assert (result.overall_status, result.error_code) == ("FAILED", "BAD_CONDITION")


# ---- 7단계: on_failure (abort · retry · skip · safe_home) ----

FAIL = ActionResult(False, error_code="GRASP_FAILED")
OK = ActionResult(True)


def one_step_task(**step_fields) -> dict:
    return {"task_id": "t", "sequence": [
        {"id": "s1", "action": "pick_object", "params": {"object_id": "watch#1"}, **step_fields},
        {"id": "s2", "action": "speak", "params": {"text": "다음"}},
    ]}


def test_retry_succeeds_on_second_attempt():
    # tasks/find_with_unpack.json s7.1 과 같은 설정
    fake = FakeBackend({"pick_object": [FAIL, OK]})
    result = Runner(fake).run(one_step_task(on_failure="retry", retry=1))
    assert result.overall_status == "COMPLETED"
    assert [c[0] for c in fake.calls] == ["pick_object", "pick_object", "speak"]
    assert result.steps[0]["status"] == "SUCCESS"
    assert result.steps[0]["attempts"] == 2
    assert "error_code" not in result.steps[0]


def test_retry_exhausted_aborts():
    fake = FakeBackend({"pick_object": FAIL})
    result = Runner(fake).run(one_step_task(on_failure="retry", retry=2))
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "GRASP_FAILED", "s1")
    assert [c[0] for c in fake.calls] == ["pick_object"] * 3            # 1회 + 재시도 2회, speak 안 함
    assert result.steps[0]["attempts"] == 3


def test_retry_count_without_retry_policy_is_ignored():
    fake = FakeBackend({"pick_object": FAIL})
    Runner(fake).run(one_step_task(retry=2))                           # on_failure 기본값 abort
    assert [c[0] for c in fake.calls] == ["pick_object"]


def test_skip_records_failure_and_continues():
    fake = FakeBackend({"pick_object": FAIL})
    result = Runner(fake).run(one_step_task(on_failure="skip"))
    assert result.overall_status == "COMPLETED"
    assert [c[0] for c in fake.calls] == ["pick_object", "speak"]
    assert result.steps[0].pop("duration_sec") >= 0
    assert result.steps[0].pop("started_at").endswith("Z")
    assert result.steps[0] == {"id": "s1", "action": "pick_object", "attempts": 1,
                               "params": {"object_id": "watch#1"},
                               "status": "FAILURE", "error_code": "GRASP_FAILED", "on_failure": "skip"}


def test_safe_home_moves_home_then_aborts():
    fake = FakeBackend({"pick_object": FAIL})
    result = Runner(fake).run(one_step_task(on_failure="safe_home"))
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "GRASP_FAILED", "s1")
    assert fake.calls == [("pick_object", {"object_id": "watch#1"}),
                          ("move_to_named_pose", {"pose_name": "home"})]
    assert [(s["id"], s["status"]) for s in result.steps] == [("s1", "FAILURE"), ("s1.safe_home", "SUCCESS")]


def test_safe_home_failure_keeps_original_error():
    fake = FakeBackend({"pick_object": FAIL,
                        "move_to_named_pose": ActionResult(False, error_code="WORKSPACE_VIOLATION")})
    result = Runner(fake).run(one_step_task(on_failure="safe_home"))
    assert result.error_code == "GRASP_FAILED"
    assert result.steps[-1]["error_code"] == "WORKSPACE_VIOLATION"


def test_child_failure_in_if_follows_child_policy():
    # then 안의 집기는 skip → if 와 태스크는 계속 진행
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "if", "cond": {"op": "==", "args": [1, 1]}, "then": [
            {"id": "s1.1", "action": "pick_object", "params": {}, "on_failure": "skip"},
            {"id": "s1.2", "action": "speak", "params": {"text": "계속"}}]}]}
    fake = FakeBackend({"pick_object": FAIL})
    result = Runner(fake).run(task)
    assert result.overall_status == "COMPLETED"
    assert [(s["id"], s["status"]) for s in result.steps] == [
        ("s1", "SUCCESS"), ("s1.1", "FAILURE"), ("s1.2", "SUCCESS")]


# ---- 8단계: finally ----

def p1_task() -> dict:
    """P1 시나리오 모양: 서랍 열기 → 찍기 → 집기 → 전달, finally 로 서랍 닫기 → 홈."""
    return {"task_id": "p1", "inputs": {"target": "watch"}, "sequence": [
        {"id": "s1", "action": "query_ontology", "params": {"item": "$inputs.target"}, "output": "loc"},
        {"id": "s2", "action": "drawer_control", "params": {"drawer_id": "$loc.drawer_id", "state": "open"}},
        {"id": "s3", "action": "pick_object", "params": {"object_id": "watch#1"}},
        {"id": "s4", "action": "place_object", "params": {"location": "handover_zone"}},
    ], "finally": [
        {"id": "f1", "action": "drawer_control", "params": {"drawer_id": "$loc.drawer_id", "state": "close"}},
        {"id": "f2", "action": "move_to_named_pose", "params": {"pose_name": "home"}},
    ]}


def p1_backend(**overrides) -> FakeBackend:
    return FakeBackend({"query_ontology": ActionResult(True, {"name_ko": "시계", "drawer_id": "drawer_top"}),
                        **overrides})


def test_finally_runs_after_success():
    fake = p1_backend()
    result = Runner(fake).run(p1_task())
    assert result.overall_status == "COMPLETED"
    assert [s["id"] for s in result.steps] == ["s1", "s2", "s3", "s4", "f1", "f2"]
    assert fake.calls[-2:] == [("drawer_control", {"drawer_id": "drawer_top", "state": "close"}),
                               ("move_to_named_pose", {"pose_name": "home"})]   # sequence 변수($loc) 사용


def test_finally_runs_after_failure():
    # P1 완료 기준: 실패하면 finally 로 서랍을 닫고 홈으로 복귀
    fake = p1_backend(pick_object=ActionResult(False, error_code="GRASP_FAILED"))
    result = Runner(fake).run(p1_task())
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "GRASP_FAILED", "s3")
    assert [s["id"] for s in result.steps] == ["s1", "s2", "s3", "f1", "f2"]       # s4 는 건너뜀
    assert [c[0] for c in fake.calls] == ["query_ontology", "drawer_control", "pick_object",
                                          "drawer_control", "move_to_named_pose"]


def test_finally_failure_after_success_fails_task():
    fake = p1_backend(drawer_control=[OK, ActionResult(False, error_code="CLOSE_NOT_CONFIRMED")])
    result = Runner(fake).run(p1_task())
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "CLOSE_NOT_CONFIRMED", "f1")
    assert [s["id"] for s in result.steps][-1] == "f1"                         # 기본 abort → f2 실행 안 함


def test_both_fail_keeps_sequence_error():
    fake = p1_backend(pick_object=ActionResult(False, error_code="GRASP_FAILED"),
                      drawer_control=[OK, ActionResult(False, error_code="CLOSE_NOT_CONFIRMED")])
    result = Runner(fake).run(p1_task())
    assert (result.error_code, result.failed_step) == ("GRASP_FAILED", "s3")
    assert result.steps[-1]["error_code"] == "CLOSE_NOT_CONFIRMED"              # finally 실패도 기록에 남음


def test_finally_step_skip_continues_to_home():
    task = p1_task()
    task["finally"][0]["on_failure"] = "skip"
    fake = p1_backend(drawer_control=[OK, ActionResult(False, error_code="CLOSE_NOT_CONFIRMED")])
    result = Runner(fake).run(task)
    assert fake.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})
    assert result.overall_status == "COMPLETED"                                # skip 이라 태스크는 정상 종료


PLACED = {"slot": None, "placed_pose": {"frame": "drawer_top", "position": [0.06, 0.22, 0.0], "yaw": 1.5707}}


@pytest.mark.parametrize("code, status", [("LIFT_FAILED", "FAILED"), ("STOP_UNCONFIRMED", "ABORTED")])
def test_failed_action_output_is_logged_but_not_on_blackboard(code, status):
    """#166 D 리뷰 P1·B 요청: 그리퍼를 연 뒤 실패한 place_object 의 placed_pose 를 실행 기록에 남김.
    블랙보드(output 변수)에는 넣지 않음 — 실패 값을 뒤 스텝이 성공 값으로 쓰지 않게."""
    from ready2go_runner.core.logstore import MemoryLogStore
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "place_object", "params": {"location": "drawer_top"}, "output": "placed"}]}
    store = MemoryLogStore()
    result = Runner(FakeBackend({"place_object": ActionResult(False, PLACED, code)}), log_store=store).run(task)
    assert (result.overall_status, result.error_code) == (status, code)
    assert result.steps[0]["output"] == PLACED and "placed" not in result.blackboard
    saved = store.read_run(result.run_id)["steps"][0]
    assert saved["result"] == PLACED and saved["error"]["code"] == code
    from ready2go_runner.core import run_report
    assert f"{code}" in run_report.detail(saved) and "놓은 자리 (60, 220) mm" in run_report.detail(saved)


def test_failed_action_without_output_records_nothing():
    result = Runner(FakeBackend({"place_object": ActionResult(False, error_code="NOT_HOLDING")})).run(
        {"task_id": "t", "sequence": [{"id": "s1", "action": "place_object", "params": {"location": "drawer_top"}}]})
    assert "output" not in result.steps[0]


def test_backend_exception_becomes_step_failure_and_finally_runs():
    def broken(action, params, timeout_sec):
        if action == "pick_object":
            raise ConnectionError("액션 서버 응답 없음")
        return p1_backend()(action, params, timeout_sec)

    result = Runner(broken).run(p1_task())
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "BACKEND_ERROR", "s3")
    assert [s["id"] for s in result.steps][-2:] == ["f1", "f2"]


def test_task_without_finally():
    result = Runner(FakeBackend()).run({"task_id": "t", "sequence": [
        {"id": "s1", "action": "speak", "params": {"text": "안녕"}}]})
    assert result.overall_status == "COMPLETED"


# ---- 9단계: timeout_sec · 소요 시간 ----

def timed_task(**step_fields) -> dict:
    return {"task_id": "t", "sequence": [
        {"id": "s1", "action": "drawer_control", "params": {"drawer_id": "drawer_top", "state": "open"},
         "output": "drawer", **step_fields},
        {"id": "s2", "action": "speak", "params": {"text": "열었습니다"}},
    ], "finally": [
        {"id": "f1", "action": "move_to_named_pose", "params": {"pose_name": "home"}},
    ]}


def test_timeout_is_passed_to_backend():
    fake = FakeBackend()
    Runner(fake).run(timed_task(timeout_sec=30))
    assert fake.timeouts == [30, None, None]          # 제한이 있는 스텝만 값 전달


def test_within_timeout_succeeds_and_records_duration():
    clock = FakeClock()
    fake = FakeBackend(clock=clock, durations={"drawer_control": 12.5, "speak": 1.0})
    result = Runner(fake, clock=clock).run(timed_task(timeout_sec=30))
    assert result.overall_status == "COMPLETED"
    assert [s["duration_sec"] for s in result.steps] == [12.5, 1.0, 0.0]


def test_late_success_is_timeout_failure():
    # 백엔드가 제한을 무시하고 40초 뒤 성공으로 돌아와도 Runner 가 TIMEOUT 으로 판정
    clock = FakeClock()
    fake = FakeBackend({"drawer_control": ActionResult(True, {"drawer_displacement": 0.25})},
                       clock=clock, durations={"drawer_control": 40.0})
    result = Runner(fake, clock=clock).run(timed_task(timeout_sec=30))
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "TIMEOUT", "s1")
    assert "drawer" not in result.blackboard                          # 늦은 결과는 저장하지 않음
    assert [s["id"] for s in result.steps] == ["s1", "f1"]           # s2 건너뛰고 finally 실행


def test_backend_timeout_code_is_kept():
    # #10 백엔드가 직접 취소하고 TIMEOUT 으로 응답하는 경우
    fake = FakeBackend({"drawer_control": ActionResult(False, error_code="TIMEOUT")})
    result = Runner(fake).run(timed_task(timeout_sec=30))
    assert result.error_code == "TIMEOUT"


def test_late_success_is_not_retried():
    # PR #64 리뷰: 제한 시간 뒤 도착한 성공은 동작이 실제로 끝났을 수 있음 → 같은 동작을 다시 보내면 위험
    clock = FakeClock()
    fake = FakeBackend(clock=clock, durations={"drawer_control": [40.0, 10.0]})   # 40초 뒤 성공 도착 (제한 30초)
    result = Runner(fake, clock=clock).run(timed_task(timeout_sec=30, on_failure="retry", retry=1))
    assert (result.overall_status, result.error_code) == ("FAILED", "TIMEOUT")
    assert [a for a, _ in fake.calls] == ["drawer_control", "move_to_named_pose"]   # 서랍 명령은 한 번, 다음은 finally 홈
    assert result.steps[0]["attempts"] == 1
    assert result.steps[0]["retry_stopped"] == "LATE_RESULT"


def test_non_motion_timeout_is_retried():
    """인식은 팔을 움직이지 않으므로 백엔드 TIMEOUT·늦은 결과여도 다시 해도 됨 (#168 인식 실패 다시 찍기)."""
    task = {"task_id": "t", "sequence": [{"id": "s1", "action": "inspect_region", "params": {"region": "drawer_top"},
                                          "on_failure": "retry", "retry": 1, "timeout_sec": 30}]}
    fake = FakeBackend({"inspect_region": [ActionResult(False, error_code="TIMEOUT"), ActionResult(True, {})]})
    result = Runner(fake).run(task)
    assert result.overall_status == "COMPLETED" and result.steps[0]["attempts"] == 2
    clock = FakeClock()
    late = FakeBackend({"inspect_region": ActionResult(True, {})}, clock=clock, durations={"inspect_region": [31, 1]})
    result = Runner(late, clock=clock).run(task)
    assert result.overall_status == "COMPLETED" and result.steps[0]["attempts"] == 2


def test_backend_timeout_is_not_retried():
    # #10: Skill goal 에 제한 시간 칸이 없어 클라이언트가 시간 초과 시 취소 요청 후 TIMEOUT → 결과 불확실
    fake = FakeBackend({"drawer_control": [ActionResult(False, error_code="TIMEOUT"), ActionResult(True)]})
    result = Runner(fake).run(timed_task(timeout_sec=30, on_failure="retry", retry=1))
    assert (result.overall_status, result.error_code) == ("FAILED", "TIMEOUT")
    assert [a for a, _ in fake.calls].count("drawer_control") == 1
    assert result.steps[0]["retry_stopped"] == "TIMEOUT"


def test_backend_failure_is_still_retried_with_timeout():
    # 백엔드가 실패를 돌려준 경우(동작이 끝나지 않음)는 기존대로 재시도
    clock = FakeClock()
    fake = FakeBackend({"drawer_control": [ActionResult(False, error_code="DRAWER_STUCK"), ActionResult(True)]},
                       clock=clock, durations={"drawer_control": 10.0})
    result = Runner(fake, clock=clock).run(timed_task(timeout_sec=30, on_failure="retry", retry=1))
    assert result.overall_status == "COMPLETED"
    assert result.steps[0]["attempts"] == 2
    assert result.steps[0]["duration_sec"] == 20.0                    # 재시도 포함 전체 시간


def test_if_block_timeout_checked_after_children():
    clock = FakeClock()
    fake = FakeBackend(clock=clock, durations={"pick_object": 20.0, "place_object": 20.0})
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "if", "cond": {"op": "==", "args": [1, 1]}, "timeout_sec": 30, "then": [
            {"id": "s1.1", "action": "pick_object", "params": {}},
            {"id": "s1.2", "action": "place_object", "params": {}}]}]}
    result = Runner(fake, clock=clock).run(task)
    assert (result.error_code, result.failed_step) == ("TIMEOUT", "s1")
    assert [(s["id"], s["status"]) for s in result.steps] == [
        ("s1", "FAILURE"), ("s1.1", "SUCCESS"), ("s1.2", "SUCCESS")]


# ---- E-stop · halt (PR #27 리뷰: ABORTED 이면 finally 의 로봇 동작 금지) ----

ESTOP = ActionResult(False, error_code="ESTOP")


def estop_task(**step_fields) -> dict:
    return {"task_id": "t", "sequence": [
        {"id": "s1", "action": "pick_object", "params": {"object_id": "watch#1"}, **step_fields},
        {"id": "s2", "action": "place_object", "params": {"location": "handover_zone"}},
    ], "finally": [
        {"id": "f1", "action": "drawer_control", "params": {"drawer_id": "drawer_top", "state": "close"}},
        {"id": "f2", "action": "speak", "params": {"text": "비상정지로 멈췄습니다"}},
        {"id": "f3", "action": "move_to_named_pose", "params": {"pose_name": "home"}},
    ]}


def test_estop_aborts_and_skips_robot_actions_in_finally():
    # 리뷰 재현: 이전에는 FAILED + ['pick_object', ..., 'move_to_named_pose']
    fake = FakeBackend({"pick_object": ESTOP})
    result = Runner(fake).run(estop_task())
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "ESTOP", "s1")
    assert [c[0] for c in fake.calls] == ["pick_object", "speak"]          # 안내 음성만, 로봇 동작 0회
    assert [(s["id"], s["status"]) for s in result.steps] == [
        ("s1", "FAILURE"), ("f1", "SKIPPED"), ("f2", "SUCCESS"), ("f3", "SKIPPED")]
    assert result.steps[1]["skipped_reason"] == "ABORTED"


def test_estop_is_not_retried():
    fake = FakeBackend({"pick_object": ESTOP})
    result = Runner(fake).run(estop_task(on_failure="retry", retry=2))
    assert result.overall_status == "ABORTED"
    assert [c[0] for c in fake.calls] == ["pick_object", "speak"]          # 재시도 안 함
    assert result.steps[0]["attempts"] == 1


def test_estop_does_not_move_safe_home():
    fake = FakeBackend({"pick_object": ESTOP})
    result = Runner(fake).run(estop_task(on_failure="safe_home"))
    assert result.overall_status == "ABORTED"
    assert "move_to_named_pose" not in [c[0] for c in fake.calls]


def test_estop_is_not_skipped():
    fake = FakeBackend({"pick_object": ESTOP})
    result = Runner(fake).run(estop_task(on_failure="skip"))
    assert result.overall_status == "ABORTED"
    assert "place_object" not in [c[0] for c in fake.calls]               # 다음 스텝으로 넘어가지 않음


def test_estop_inside_if_aborts():
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "if", "cond": {"op": "==", "args": [1, 1]},
         "then": [{"id": "s1.1", "action": "pick_object", "params": {}}]}],
        "finally": [{"id": "f1", "action": "if", "cond": {"op": "==", "args": [1, 1]}, "then": [
            {"id": "f1.1", "action": "speak", "params": {"text": "멈춤"}},
            {"id": "f1.2", "action": "move_to_named_pose", "params": {"pose_name": "home"}}]}]}
    fake = FakeBackend({"pick_object": ESTOP})
    result = Runner(fake).run(task)
    assert (result.overall_status, result.failed_step) == ("ABORTED", "s1.1")
    assert [c[0] for c in fake.calls] == ["pick_object", "speak"]          # finally 의 if 안쪽 이동도 생략
    assert [(s["id"], s["status"]) for s in result.steps] == [
        ("s1", "FAILURE"), ("s1.1", "FAILURE"), ("f1", "SUCCESS"), ("f1.1", "SUCCESS"), ("f1.2", "SKIPPED")]


def test_estop_during_finally_after_normal_failure():
    # 집기 실패(GRASP_FAILED) → finally 서랍 닫기 중 E-stop → 나머지 로봇 동작 없이 ABORTED
    fake = FakeBackend({"pick_object": ActionResult(False, error_code="GRASP_FAILED"), "drawer_control": ESTOP})
    result = Runner(fake).run(estop_task())
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "ESTOP", "f1")
    assert [c[0] for c in fake.calls] == ["pick_object", "drawer_control"]


def test_halt_stops_before_next_step():
    # /runner/estop 서비스(다른 스레드)가 첫 동작 중에 halt() 를 부른 상황
    fake = FakeBackend()
    runner = Runner(fake)

    def backend(action, params, timeout_sec):
        if action == "pick_object":
            runner.halt()
        return fake(action, params, timeout_sec)

    runner.execute = backend
    result = runner.run(estop_task())
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "HALTED", "s2")
    assert [c[0] for c in fake.calls] == ["pick_object", "speak"]          # s2 놓기·finally 이동 없음


# ---- 코드 리뷰 A~E: 중단 확인 시점 · 중단 잠김(resume) ----

def halting_runner(results: dict, halt_on: str) -> tuple[Runner, FakeBackend]:
    """halt_on 동작이 실행되는 도중 /runner/estop(다른 스레드)이 halt() 를 부른 상황."""
    fake = FakeBackend(results)
    runner = Runner(fake)

    def backend(action, params, timeout_sec):
        if action == halt_on:
            runner.halt()
        return fake(action, params, timeout_sec)

    runner.execute = backend
    return runner, fake


def test_a_no_retry_after_halt_requested():
    runner, fake = halting_runner({"pick_object": FAIL}, halt_on="pick_object")
    result = runner.run(estop_task(on_failure="retry", retry=2))
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "HALTED", "s1")
    assert [c[0] for c in fake.calls] == ["pick_object", "speak"]          # 재시도 0회
    assert (result.steps[0]["status"], result.steps[0]["error_code"]) == ("FAILURE", "GRASP_FAILED")


def test_b_no_safe_home_after_halt_requested():
    runner, fake = halting_runner({"pick_object": FAIL}, halt_on="pick_object")
    result = runner.run(estop_task(on_failure="safe_home"))
    assert result.overall_status == "ABORTED"
    assert "move_to_named_pose" not in [c[0] for c in fake.calls]


def test_c_no_safe_home_in_finally_after_abort():
    task = {"task_id": "t", "sequence": [{"id": "s1", "action": "pick_object", "params": {}}],
            "finally": [{"id": "f1", "action": "speak", "params": {"text": "멈춤"}, "on_failure": "safe_home"}]}
    fake = FakeBackend({"pick_object": ESTOP, "speak": FAIL})
    result = Runner(fake).run(task)
    assert result.overall_status == "ABORTED"
    assert [c[0] for c in fake.calls] == ["pick_object", "speak"]          # 음성 실패해도 홈 이동 없음


def test_d_halt_before_run_refuses_until_resume():
    fake = FakeBackend()
    runner = Runner(fake)
    runner.halt()
    result = runner.run(estop_task())
    assert (result.overall_status, result.error_code) == ("ABORTED", "HALTED")
    assert fake.calls == [] and result.steps == [] and result.problems    # 로봇 0회, finally 도 없음
    runner.resume()
    assert runner.run(estop_task()).overall_status == "COMPLETED"


def test_e_backend_estop_stays_latched_until_resume():
    fake = FakeBackend({"pick_object": [ESTOP, OK]})
    runner = Runner(fake)
    assert runner.run(estop_task()).overall_status == "ABORTED"
    assert runner.halted
    fake.calls.clear()
    again = runner.run(estop_task())                                       # 사람 확인 없이 다시 명령
    assert (again.overall_status, again.error_code) == ("ABORTED", "ESTOP")  # 처음 멈춘 이유 유지
    assert fake.calls == []
    runner.resume()
    assert not runner.halted
    assert runner.run(estop_task()).overall_status == "COMPLETED"


def test_halt_code_keeps_first_reason():
    runner = Runner(FakeBackend())
    runner.halt("ESTOP")
    runner.halt()                                                          # 나중 요청이 원인을 덮지 않음
    assert runner.run(estop_task()).error_code == "ESTOP"


# ---- 코드 리뷰 ①②: 처음 멈춘 위치 유지 · 내부 에러에도 finally 보장 ----

def test_first_abort_location_is_kept():
    task = {"task_id": "t", "sequence": [{"id": "s1", "action": "pick_object", "params": {}}],
            "finally": [{"id": "f1", "action": "speak", "params": {"text": "멈춤"}}]}
    fake = FakeBackend({"pick_object": ESTOP, "speak": ESTOP})            # finally 의 음성도 ESTOP 응답
    result = Runner(fake).run(task)
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "ESTOP", "s1")


def internal_error_task(**step_fields) -> dict:
    # s3 의 set_var 이름이 객체로 치환되어 Runner 안에서 TypeError 가 나는 태스크
    return {"task_id": "t", "sequence": [
        {"id": "s1", "action": "query_ontology", "params": {}, "output": "loc"},
        {"id": "s2", "action": "drawer_control", "params": {"drawer_id": "drawer_top", "state": "open"}},
        {"id": "s3", "action": "set_var", "params": {"name": "$loc", "value": 1}, **step_fields},
        {"id": "s4", "action": "speak", "params": {"text": "다음"}}],
        "finally": [{"id": "f1", "action": "drawer_control", "params": {"drawer_id": "drawer_top", "state": "close"}}]}


def test_internal_error_still_runs_finally():
    fake = FakeBackend({"query_ontology": ActionResult(True, {"drawer_id": "drawer_top"})})
    result = Runner(fake).run(internal_error_task())
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "INTERNAL_ERROR", "s3")
    assert fake.calls[-1] == ("drawer_control", {"drawer_id": "drawer_top", "state": "close"})   # 서랍 닫힘
    assert result.steps[2]["internal_error"].startswith("TypeError")                               # 원인 기록


def test_internal_error_follows_on_failure_policy():
    fake = FakeBackend({"query_ontology": ActionResult(True, {"drawer_id": "drawer_top"})})
    result = Runner(fake).run(internal_error_task(on_failure="skip"))
    assert result.overall_status == "COMPLETED"
    assert ("speak", {"text": "다음"}) in fake.calls                     # skip 이라 다음 스텝 진행


def test_halt_during_last_action_ends_aborted():
    # 원자 동작도 같은 경계: 마지막 동작 중 halt() → 응답대로 SUCCESS 기록, 태스크는 ABORTED (COMPLETED 아님)
    def backend(action, params, timeout_sec):
        runner.halt()
        return ActionResult(True)

    runner = Runner(backend)
    result = runner.run({"task_id": "t", "sequence": [
        {"id": "s1", "action": "drawer_control", "params": {"drawer_id": "drawer_top", "state": "open"}}]})
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "HALTED", "s1")
    assert result.steps[0]["status"] == "SUCCESS"
    assert runner.halted


# ---- PR #74 리뷰: 중단 요청이 진행 중 동작 취소로 이어지고, 정지 확인 전에는 다음 동작을 보내지 않음 ----

STOP_TASK = {"task_id": "t", "sequence": [
    {"id": "s1", "action": "drawer_control", "params": {"drawer_id": "drawer_top", "state": "open"}}],
    "finally": [{"id": "f1", "action": "speak", "params": {"text": "멈췄습니다"}},
                {"id": "f2", "action": "move_to_named_pose", "params": {"pose_name": "home"}}]}


def test_halt_calls_on_halt_once_and_canceled_action_aborts_there():
    canceled = []

    def backend(action, params, timeout_sec):
        if action == "drawer_control":
            runner.halt()                                       # /runner/estop (다른 스레드라고 가정)
            return ActionResult(False, error_code="CANCELED")   # on_halt 로 취소된 동작의 최종 결과
        return ActionResult(True)

    runner = Runner(backend)
    runner.on_halt = lambda: canceled.append("cancel_all")
    result = runner.run(STOP_TASK)
    runner.halt()                                               # 두 번째 halt 는 다시 취소하지 않음
    assert canceled == ["cancel_all"]
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "HALTED", "s1")
    assert (result.steps[0]["status"], result.steps[0]["error_code"]) == ("FAILURE", "CANCELED")
    assert [(s["id"], s["status"]) for s in result.steps[1:]] == [("f1", "SUCCESS"), ("f2", "SKIPPED")]


def test_stop_unconfirmed_locks_runner_and_sends_no_motion():
    fake = FakeBackend({"drawer_control": ActionResult(False, error_code="STOP_UNCONFIRMED")})
    runner = Runner(fake)
    result = runner.run(STOP_TASK)
    assert (result.overall_status, result.error_code) == ("ABORTED", "STOP_UNCONFIRMED")
    assert runner.halted and runner.halt_code == "STOP_UNCONFIRMED"
    assert [a for a, _ in fake.calls] == ["drawer_control", "speak"]     # 홈 이동 안 보냄
    assert runner.run(STOP_TASK).overall_status == "ABORTED"             # 사람 확인(resume) 전 새 태스크 거절


@pytest.mark.parametrize("code", ["STATE_UNKNOWN", "MOVE_UNCONFIRMED", "LOCKED"])
def test_skill_server_lock_codes_abort_and_lock(code):
    # B 스킬 서버(PR #73)의 잠금 코드도 Runner 를 잠금 — 10/06 실물 확인 후 runner.md 표로 확정
    fake = FakeBackend({"drawer_control": ActionResult(False, error_code=code)})
    runner = Runner(fake)
    result = runner.run(STOP_TASK)
    assert (result.overall_status, result.error_code) == ("ABORTED", code)
    assert runner.halted and "move_to_named_pose" not in [a for a, _ in fake.calls]


def test_stop_requested_only_until_abort_is_handled():
    # 중단 요청 직후에는 새 동작을 막고(stop_requested), 중단 처리 뒤 finally 의 speak 는 보낼 수 있어야 함
    seen = []

    def backend(action, params, timeout_sec):
        if action == "drawer_control":
            runner.halt()
            seen.append(("after halt", runner.stop_requested))
            return ActionResult(False, error_code="CANCELED")
        seen.append((action, runner.stop_requested))
        return ActionResult(True)

    runner = Runner(backend)
    result = runner.run(STOP_TASK)
    assert result.overall_status == "ABORTED"
    assert seen == [("after halt", True), ("speak", False)]


# ---- VAR_NULL (#23): 백엔드 동작의 "$변수" 가 null 이면 보내지 않음 ----

def test_null_reference_is_not_sent_to_backend():
    sent = []
    runner = Runner(lambda a, p, t: sent.append(a) or ActionResult(True))
    task = {"task_id": "t", "sequence": [
        {"id": "s1", "action": "set_var", "params": {"name": "nudge", "value": {"target_after": None}}},
        {"id": "s2", "action": "set_var", "params": {"name": "copy", "value": "$nudge.target_after"}},   # set_var 은 허용
        {"id": "s3", "action": "pick_object", "params": {"target": "$nudge.target_after"}}]}
    result = runner.run(task)
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "VAR_NULL", "s3")
    assert sent == []
    assert result.blackboard["copy"] is None


# ---- 정지 기록 halts[] (#187 AC-SAF-02 C 몫: 요청 → 응답 시각·출처) ----

def _halt_run(execute, task, on_halt=None):
    from ready2go_runner.core.logstore import MemoryLogStore
    store = MemoryLogStore()
    runner = Runner(None, log_store=store)
    runner.execute = execute(runner)
    runner.on_halt = on_halt
    result = runner.run(task)
    return result, store.read_run(result.run_id)["run"]


MOVE = {"task_id": "t", "sequence": [{"id": "s1", "action": "move_to_named_pose", "params": {"pose_name": "home"}},
                                     {"id": "s2", "action": "speak", "params": {"text": "x"}}],
        "finally": [{"id": "f1", "action": "speak", "params": {"text": "끝"}}]}


def test_service_halt_is_recorded_with_source_and_reply():
    """/runner/estop(서비스)으로 멈춤 → halts[0]: 출처·요청 시각·취소한 동작 수·백엔드 응답(CANCELED)·응답 시각."""
    def execute(runner):
        def run(action, params, timeout=None):
            if action == "move_to_named_pose":
                runner.halt(source="service")
                return ActionResult(False, error_code="CANCELED")
            return ActionResult(True)
        return run
    result, run = _halt_run(execute, MOVE, on_halt=lambda: 1)
    assert result.overall_status == "ABORTED"
    halt = run["halts"][0]
    assert (halt["source"], halt["code"], halt["step"], halt["step_code"], halt["canceled_goals"]) == \
        ("service", "HALTED", "s1", "CANCELED", 1)
    assert halt["requested_at"] <= halt["stopped_at"] and halt["in_finally"] is False


def test_backend_estop_is_recorded_as_backend():
    result, run = _halt_run(lambda r: FakeBackend({"move_to_named_pose": ActionResult(False, error_code="ESTOP")}), MOVE)
    halt = run["halts"][0]
    assert (halt["source"], halt["code"], halt["step_code"]) == ("backend", "ESTOP", "ESTOP")


def test_halt_between_steps_and_in_finally_are_recorded():
    """끝난 스텝 뒤 음성 정지 → 다음 스텝 시작 전 멈춤(응답 = HALTED) / finally 중 멈춤도 기록 (in_finally)."""
    def between(runner):
        def run(action, params, timeout=None):
            if action == "move_to_named_pose":
                runner.halt(source="voice")
            return ActionResult(True)
        return run
    _, run = _halt_run(between, MOVE)
    assert [(h["source"], h["step"], h["step_code"]) for h in run["halts"]] == [("voice", "s2", "HALTED")]

    def in_finally(runner):
        def run(action, params, timeout=None):
            if params.get("text") == "끝":
                runner.halt(source="service")
                return ActionResult(False, error_code="CANCELED")
            return ActionResult(True)
        return run
    result, run = _halt_run(in_finally, MOVE)
    assert result.overall_status == "ABORTED"
    assert [(h["step"], h["in_finally"]) for h in run["halts"]] == [("f1", True)]


def test_report_shows_halt_request_and_reply():
    from ready2go_runner.core import run_report
    from ready2go_runner.core.logstore import MemoryLogStore
    store = MemoryLogStore()
    runner = Runner(None, log_store=store)

    def run(action, params, timeout=None):
        if action == "move_to_named_pose":
            runner.halt(source="voice")
            return ActionResult(False, error_code="CANCELED")
        return ActionResult(True)
    runner.execute = run
    result = runner.run(MOVE)
    text = run_report.to_text(store.read_run(result.run_id))
    assert "· HALTED · 음성 멈춰 · s1 · 응답 CANCELED +" in text and "→ 중단" in text


def test_halt_motion_codes_stop_atomic_finally_too():
    """#78 E 모의 반례 그대로: finally 에 원자 동작 닫기·홈을 둔 태스크에서 place_object 가 OBJECT_DROPPED →
    예전엔 place → drawer_control → move_to_named_pose, FAILED, 잠김 없음. 이제 ABORTED·잠금, 닫기·홈 안 보냄."""
    task = {"task_id": "t", "sequence": [{"id": "s1", "action": "place_object", "params": {"location": "handover_zone"}}],
            "finally": [{"id": "f1", "action": "drawer_control", "params": {"drawer_id": "drawer_top", "state": "close"}},
                        {"id": "f2", "action": "move_to_named_pose", "params": {"pose_name": "home"}}]}
    fake = FakeBackend({"place_object": ActionResult(False, error_code="OBJECT_DROPPED")})
    runner = Runner(fake)
    result = runner.run(task)
    assert (result.overall_status, result.error_code, runner.halted) == ("ABORTED", "OBJECT_DROPPED", True)
    assert [a for a, _ in fake.calls] == ["place_object"]
    assert runner.run({"task_id": "h", "sequence": [{"id": "s1", "action": "move_to_named_pose",
                                                     "params": {"pose_name": "home"}}]}).overall_status == "ABORTED"
    assert [a for a, _ in fake.calls] == ["place_object"]
