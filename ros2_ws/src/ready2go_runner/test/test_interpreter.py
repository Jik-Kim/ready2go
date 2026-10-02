from ready2go_runner.core.interpreter import ActionResult, Runner


class FakeBackend:
    """로봇 없이 원자 동작을 흉내 낸다. results 에 동작별 결과를 미리 넣어 두고, 호출 기록을 남긴다."""

    def __init__(self, results: dict[str, ActionResult] | None = None):
        self.results = results or {}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, action: str, params: dict) -> ActionResult:
        self.calls.append((action, params))
        return self.results.get(action, ActionResult(success=True))


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
    assert result.steps[-1] == {"id": "s3", "action": "drawer_control",
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
