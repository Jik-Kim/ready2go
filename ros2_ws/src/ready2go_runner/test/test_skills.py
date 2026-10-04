"""#12 스킬 상태 추적: Runner 가 온톨로지(E)를 받아 pre 확인 → expand 실행 → effect 반영."""
import json
import threading
from pathlib import Path

import pytest

from ready2go_knowledge.core import ontology
from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.validation import check_task

ROOT = Path(__file__).resolve().parents[4]
REAL = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")   # E 의 실제 온톨로지 (물품·배치는 E 가 바꿀 수 있음)
# 스킬 규칙(pre·effect·expand)은 E 파일 그대로 쓰고, 물품 이름·위치는 시험용으로 고정한다.
# E 가 실측 물품이나 초기 배치를 바꿔도(PR #46 등) Runner 시험이 깨지지 않게 하기 위함.
TEST_ITEMS = {"watch": {"name_ko": "시계"}, "wallet": {"name_ko": "지갑"}, "car_key": {"name_ko": "차키"}}
TEST_STATE = {
    "robot_pose": {"robot": "home"}, "gripper": {"robot": "empty"},
    "open": {"drawer_top": False, "drawer_bottom": False, "staging_tray": True, "handover_zone": True},
    "located_in": {"watch": "drawer_top", "car_key": "drawer_top", "wallet": "drawer_bottom"},
}
ONTOLOGY = {**REAL, "world": {**REAL["world"], "items": TEST_ITEMS}, "state": TEST_STATE}
COMPOSITE = next(name for name, skill in REAL["skills"].items() if skill.get("kind") == "composite")
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))


def ok_backend(action, params, timeout_sec):
    return ActionResult(True)


# ---- 2단계: 온톨로지 받기 ----

def test_runner_holds_skills_and_initial_state():
    runner = Runner(ok_backend, ontology=ONTOLOGY)
    assert set(runner.skills) >= {"open_drawer", "close_drawer", "pick", "place"}
    assert runner.state["open"]["drawer_top"] is False
    assert runner.state["gripper"]["robot"] == "empty"


def test_runner_state_is_a_copy():
    runner = Runner(ok_backend, ontology=ONTOLOGY)
    runner.state["open"]["drawer_top"] = True            # 밖에서 꺼낸 값을 바꿔도
    assert runner.state["open"]["drawer_top"] is False   # Runner 상태는 그대로
    assert ONTOLOGY["state"]["open"]["drawer_top"] is False   # 원본 파일 내용도 그대로


def test_runner_without_ontology_works_as_before():
    runner = Runner(ok_backend)
    assert runner.skills == {} and runner.state == {}
    result = runner.run({"task_id": "t", "sequence": [{"id": "s1", "action": "speak", "params": {"text": "안녕"}}]})
    assert result.overall_status == "COMPLETED"


# ---- 3단계: skill 스텝 실행 ----

from test_interpreter import FakeBackend, FakeClock  # noqa: E402

FOUND_WATCH = ActionResult(True, {"target_found": True, "target": {"id": "watch#1"}})


def skill_task(*steps, final=()):
    return {"task_id": "skills", "sequence": list(steps), "finally": list(final)}


def test_open_drawer_runs_expand_and_applies_effect():
    backend = FakeBackend()
    runner = Runner(backend, ontology=ONTOLOGY)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}}))

    assert result.overall_status == "COMPLETED"
    assert backend.calls == [                                   # expand 순서대로, $drawer_id 치환
        ("move_to_named_pose", {"pose_name": "drawer_approach", "drawer_id": "drawer_top"}),
        ("drawer_control", {"drawer_id": "drawer_top", "state": "open"}),
    ]
    assert [(s["id"], s["action"], s["status"]) for s in result.steps] == [
        ("s1", "skill", "SUCCESS"), ("s1.e1", "move_to_named_pose", "SUCCESS"), ("s1.e2", "drawer_control", "SUCCESS")]
    assert result.steps[0]["skill"] == "open_drawer" and result.steps[1]["parent"] == "s1"
    assert result.steps[0]["state_diff"] == {"open.drawer_top": [False, True]}
    assert runner.state["open"]["drawer_top"] is True


def test_pre_unmet_does_not_move_robot():
    backend = FakeBackend()
    runner = Runner(backend, ontology=ONTOLOGY)
    # 위 서랍은 닫혀 있으므로 pick 의 pre(서랍 열림) 불충족
    result = runner.run(skill_task({"id": "s1", "skill": "pick", "params": {"item": "watch", "from": "drawer_top"}}))

    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "PRE_UNMET", "s1")
    assert backend.calls == []                                  # 로봇 동작 0회
    failed = [c for c in result.steps[0]["pre_check"] if not c["pass"]]
    assert failed == [{"subject": "drawer_top", "predicate": "open", "op": "==",
                       "value": True, "actual": False, "pass": False}]
    assert runner.state == ONTOLOGY["state"]                    # 상태 그대로


def test_failed_expand_keeps_state():
    backend = FakeBackend({"drawer_control": ActionResult(False, error_code="DRAWER_STUCK")})
    runner = Runner(backend, ontology=ONTOLOGY)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}}))

    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "DRAWER_STUCK", "s1.e2")
    assert [s["status"] for s in result.steps] == ["FAILURE", "SUCCESS", "FAILURE"]
    assert runner.state["open"]["drawer_top"] is False          # 실패하면 effect 없음


def test_state_carries_across_steps_and_tasks():
    backend = FakeBackend({"inspect_region": FOUND_WATCH})
    runner = Runner(backend, ontology=ONTOLOGY)
    first = runner.run(skill_task(
        {"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}},
        {"id": "s2", "skill": "pick", "params": {"item": "watch", "from": "drawer_top"}}))
    assert first.overall_status == "COMPLETED"
    assert ("pick_object", {"target": {"id": "watch#1"}, "approach_offset": [0, 0, 0.1]}) in backend.calls   # $scan.target 통째로 (runner.md 7.1 v5.13)
    assert "scan" not in first.blackboard                      # 스킬 안 출력은 태스크 변수로 새지 않음

    # 다음 태스크: 앞 태스크가 남긴 상태(시계를 들고 있음)에서 이어짐
    second = runner.run(skill_task({"id": "s1", "skill": "place", "params": {"item": "watch", "to": "handover_zone"}}))
    assert second.overall_status == "COMPLETED"
    assert runner.state["gripper"]["robot"] == "empty"
    assert runner.state["located_in"]["watch"] == "handover_zone"


def test_skill_params_use_task_variables():
    backend = FakeBackend({"query_ontology": ActionResult(True, {"drawer_id": "drawer_bottom"})})
    runner = Runner(backend, ontology=ONTOLOGY)
    result = runner.run(skill_task(
        {"id": "s1", "action": "query_ontology", "params": {"item": "wallet"}, "output": "loc"},
        {"id": "s2", "skill": "open_drawer", "params": {"drawer_id": "$loc.drawer_id"}}))
    assert result.overall_status == "COMPLETED"
    assert result.steps[1]["params"] == {"drawer_id": "drawer_bottom"}
    assert runner.state["open"]["drawer_bottom"] is True


def test_skill_retry_is_rejected_before_moving():
    # PR #64 리뷰: P1 은 물리 결과 확인(verify)이 없으므로 스킬 전체 재실행을 시작 전에 거절
    backend = FakeBackend()
    result = Runner(backend, schema=SCHEMA, ontology=ONTOLOGY).run(skill_task(
        {"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}, "on_failure": "retry", "retry": 1}))
    assert (result.overall_status, result.error_code) == ("FAILED", "TASK_INVALID")
    assert any("skill 스텝의 retry" in p for p in result.problems)
    assert backend.calls == []


def test_late_success_does_not_resend_skill(monkeypatch):
    # PR #64 리뷰 재현: open_drawer(timeout 1, retry 1), drawer_control 이 2초 뒤 성공 → 이전에는 동작 4번 전송
    monkeypatch.setattr("ready2go_runner.core.interpreter.check_task", lambda *a: [])   # 실행 중 안전장치만 시험
    clock = FakeClock()
    backend = FakeBackend(clock=clock, durations={"drawer_control": 2.0})
    runner = Runner(backend, clock=clock, ontology=ONTOLOGY)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"},
                                    "timeout_sec": 1, "on_failure": "retry", "retry": 1}))
    assert [a for a, _ in backend.calls] == ["move_to_named_pose", "drawer_control"]   # 한 번만
    assert (result.overall_status, result.error_code) == ("FAILED", "TIMEOUT")
    assert result.steps[0]["attempts"] == 1
    assert runner.state["open"]["drawer_top"] is False         # 확인 전이라 effect 도 없음


def test_backend_failure_does_not_resend_skill(monkeypatch):
    # 응답이 실패여도 앞 동작(접근 이동)은 이미 실행됨 → P1 에서는 스킬을 다시 보내지 않음
    monkeypatch.setattr("ready2go_runner.core.interpreter.check_task", lambda *a: [])
    backend = FakeBackend({"drawer_control": [ActionResult(False, error_code="DRAWER_STUCK"), ActionResult(True)]})
    result = Runner(backend, ontology=ONTOLOGY).run(skill_task(
        {"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}, "on_failure": "retry", "retry": 1}))
    assert [a for a, _ in backend.calls] == ["move_to_named_pose", "drawer_control"]
    assert (result.overall_status, result.error_code) == ("FAILED", "DRAWER_STUCK")


def test_timeout_covers_whole_skill():
    clock = FakeClock()
    backend = FakeBackend(clock=clock, durations={"move_to_named_pose": 8.0, "drawer_control": 5.0})
    runner = Runner(backend, clock=clock, ontology=ONTOLOGY)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"},
                                    "timeout_sec": 10}))
    assert backend.timeouts == [10, 2]                         # 두 번째 동작엔 남은 시간만
    assert (result.overall_status, result.error_code) == ("FAILED", "TIMEOUT")
    assert runner.state["open"]["drawer_top"] is False


def test_estop_skips_skills_in_finally():
    backend = FakeBackend({"drawer_control": ActionResult(False, error_code="ESTOP")})
    runner = Runner(backend, ontology=ONTOLOGY)
    result = runner.run(skill_task(
        {"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}},
        final=[{"id": "f1", "skill": "close_drawer", "params": {"drawer_id": "drawer_top"}},
               {"id": "f2", "action": "speak", "params": {"text": "멈췄습니다"}}]))
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "ESTOP", "s1.e2")
    f1 = next(s for s in result.steps if s["id"] == "f1")
    assert (f1["status"], f1["skipped_reason"]) == ("SKIPPED", "ABORTED")   # 스킬도 로봇을 움직이므로 생략
    assert [a for a, _ in backend.calls] == ["move_to_named_pose", "drawer_control", "speak"]
    assert runner.state["open"]["drawer_top"] is False         # 열기 도중 멈춤 → effect 없음


def test_halt_during_skill_stops_before_next_action():
    # 사용자 "멈춰"·/runner/estop: 진행 중 동작은 백엔드가 끊고, Runner 는 다음 원자 동작을 보내지 않음
    calls = []

    def backend(action, params, timeout_sec):
        calls.append(action)
        if action == "move_to_named_pose":
            runner.halt()
        return ActionResult(True)

    runner = Runner(backend, ontology=ONTOLOGY)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}}))
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "HALTED", "s1.e2")
    assert calls == ["move_to_named_pose"]                     # 서랍 열기는 보내지 않음
    assert runner.state["open"]["drawer_top"] is False


@pytest.mark.parametrize("final", [[], [{"id": "f1", "action": "speak", "params": {"text": "멈췄습니다"}},
                                       {"id": "f2", "action": "move_to_named_pose", "params": {"pose_name": "home"}}]])
def test_halt_during_last_action_does_not_apply_effect(final):
    # PR #64 E 리뷰 재현: 마지막 expand 동작(drawer_control) 중 halt() → 이전에는 effect 반영, finally 없으면 COMPLETED
    calls = []

    def backend(action, params, timeout_sec):
        calls.append(action)
        if action == "drawer_control":
            runner.halt()                                      # 동작은 끝났고 응답은 성공
        return ActionResult(True)

    runner = Runner(backend, ontology=ONTOLOGY)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}},
                                   final=final))
    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "HALTED", "s1")
    assert runner.state["open"]["drawer_top"] is False         # effect 미반영 → 사람이 확인 후 재개
    s1 = result.steps[0]
    assert (s1["status"], s1["error_code"]) == ("FAILURE", "HALTED") and "state_diff" not in s1   # 스킬 성공 기록 없음
    assert result.steps[2]["id"] == "s1.e2" and result.steps[2]["status"] == "SUCCESS"            # 하위 동작은 응답대로
    if final:
        assert calls[-1] == "speak"                            # 비동작만 실행, 홈 이동은 SKIPPED
        assert [s["status"] for s in result.steps if s["id"] in ("f1", "f2")] == ["SUCCESS", "SKIPPED"]


def test_halt_waits_while_effect_is_applied(monkeypatch):
    # 다른 스레드(#10 ROS 서비스)의 halt() 가 반영 도중 들어오면 반영이 끝날 때까지 기다림 → 반영 후 중단으로 처리
    real_apply, seen = ontology.apply, {}

    def apply_while_halting(state, records, binding):
        halter = threading.Thread(target=runner.halt)
        halter.start()
        halter.join(0.2)
        seen["halt_blocked"] = halter.is_alive()               # 잠금 때문에 halt() 가 아직 못 끝남
        seen["halter"] = halter
        return real_apply(state, records, binding)

    monkeypatch.setattr(ontology, "apply", apply_while_halting)
    runner = Runner(FakeBackend(), ontology=ONTOLOGY)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}}))
    seen["halter"].join(1)
    assert seen["halt_blocked"] is True
    assert runner.state["open"]["drawer_top"] is True           # 중단보다 먼저 끝난 반영은 유지
    assert result.steps[0]["status"] == "SUCCESS" and "state_diff" in result.steps[0]
    assert runner.halted                                        # 중단 요청은 반영 뒤에 적용되어 잠김 유지
    # 태스크 결과(ABORTED/COMPLETED)는 halt() 스레드가 실행 끝 확인보다 먼저 도착했는지에 달려 단정하지 않음


def test_real_ontology_file_runs_open_drawer():
    # 시험용 배치가 아니라 E 의 실제 파일 그대로: 스킬 4종과 초기 상태로 서랍 열기 1회
    primitives = {name: sorted(s.get("params", {})) for name, s in REAL["skills"].items()
                  if s.get("kind") == "primitive"}
    assert primitives == {"open_drawer": ["drawer_id"], "close_drawer": ["drawer_id"],
                          "pick": ["from", "item"], "place": ["item", "to"]}
    drawer = next(d for d, is_open in REAL["state"]["open"].items() if is_open is False)
    runner = Runner(FakeBackend(), schema=SCHEMA, ontology=REAL)
    result = runner.run(skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": drawer}}))
    assert result.overall_status == "COMPLETED"
    assert runner.state["open"][drawer] is True


def test_runtime_guard_when_validation_is_bypassed(monkeypatch):
    # 실행 전 검사(4단계)가 막지만, 검사를 거치지 않아도 실행 중 다시 확인해 로봇을 움직이지 않음
    monkeypatch.setattr("ready2go_runner.core.interpreter.check_task", lambda *a: [])
    backend = FakeBackend()
    runner = Runner(backend, ontology=ONTOLOGY)
    for params, skill, code in [({}, "open_drawr", "UNKNOWN_SKILL"),
                                ({"target": "watch"}, COMPOSITE, "UNKNOWN_SKILL"),
                                ({"item": "watch"}, "pick", "BAD_SKILL_PARAMS")]:
        result = runner.run(skill_task({"id": "s1", "skill": skill, "params": params}))
        assert result.error_code == code
    assert backend.calls == []


# ---- 4단계: 실행 전 검사 ----

@pytest.mark.parametrize("step, expected", [
    ({"id": "s1", "skill": "open_drawr", "params": {"drawer_id": "drawer_top"}}, "없는 스킬 'open_drawr'"),
    ({"id": "s1", "skill": COMPOSITE, "params": {"target": "watch"}}, "P1 미지원"),
    ({"id": "s1", "skill": "pick", "params": {"item": "watch"}}, "params.from 가 없음"),
    ({"id": "s1", "skill": "open_drawer", "params": {"drawer": "drawer_top"}}, "없는 파라미터 params.drawer"),
])
def test_invalid_skill_step_is_rejected_before_moving(step, expected):
    backend = FakeBackend()
    # 앞 스텝(말하기)도 실행되지 않아야 함: 시작 전에 거절
    task = skill_task({"id": "s0", "action": "speak", "params": {"text": "시작"}}, step,
                      final=[{"id": "f1", "action": "move_to_named_pose", "params": {"pose_name": "home"}}])
    result = Runner(backend, schema=SCHEMA, ontology=ONTOLOGY).run(task)
    assert (result.overall_status, result.error_code) == ("FAILED", "TASK_INVALID")
    assert any(expected in p for p in result.problems), result.problems
    assert backend.calls == [] and result.steps == []


def test_child_record_id_collision_is_rejected():
    task = skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}},
                      {"id": "s1.e2", "action": "speak", "params": {"text": "겹침"}})
    problems = check_task(task, SCHEMA, ONTOLOGY["skills"])
    assert any("'s1.e2'" in p and "중복" in p for p in problems)


def test_skill_example_passes_with_ontology():
    task = json.loads((ROOT / "contracts/examples/task_skill_steps.json").read_text(encoding="utf-8"))
    assert check_task(task, SCHEMA, ONTOLOGY["skills"]) == []


def test_skill_step_without_ontology_is_rejected():
    # 온톨로지 없이 만든 Runner 는 skill 스텝을 실행할 수 없음
    result = Runner(FakeBackend()).run(skill_task({"id": "s1", "skill": "open_drawer",
                                                   "params": {"drawer_id": "drawer_top"}}))
    assert result.error_code == "TASK_INVALID"


# ---- 5단계: 스킬 기록 저장 (메모리·JSONL·MongoDB·폴백) ----

from test_logstore import store  # noqa: E402,F401  (저장소 4종 fixture)


def test_skill_and_child_records_are_saved_in_order(store):  # noqa: F811
    backend = FakeBackend({"inspect_region": FOUND_WATCH})
    result = Runner(backend, ontology=ONTOLOGY, log_store=store).run(skill_task(
        {"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}},
        {"id": "s2", "skill": "pick", "params": {"item": "watch", "from": "drawer_top"}}))
    steps = store.read_run(result.run_id)["steps"]

    # 스킬은 하위 동작보다 늦게 끝나지만 seq 는 시작 순서
    assert [(s["seq"], s["id"], s.get("parent")) for s in steps] == [
        (0, "s1", None), (1, "s1.e1", "s1"), (2, "s1.e2", "s1"),
        (3, "s2", None), (4, "s2.e1", "s2"), (5, "s2.e2", "s2")]
    s1, s2 = steps[0], steps[3]
    assert (s1["action"], s1["skill"], s1["params"]) == ("skill", "open_drawer", {"drawer_id": "drawer_top"})
    assert all(c["pass"] for c in s1["pre_check"])
    assert s1["state_diff"] == {"open.drawer_top": [False, True]}
    assert s2["state_diff"] == {"gripper.robot": ["empty", "watch"], "located_in.watch": ["drawer_top", "gripper"]}
    assert steps[4]["result"] == FOUND_WATCH.output                       # 하위 동작 출력도 저장


def test_pre_unmet_reason_is_saved(store):  # noqa: F811
    result = Runner(FakeBackend(), ontology=ONTOLOGY, log_store=store).run(
        skill_task({"id": "s1", "skill": "close_drawer", "params": {"drawer_id": "drawer_top"}}))  # 이미 닫힘
    saved = store.read_run(result.run_id)
    assert saved["run"]["error"] == {"code": "PRE_UNMET"} and saved["run"]["failed_step"] == "s1"
    (s1,) = saved["steps"]                                                # 하위 동작 기록 없음 (로봇 안 움직임)
    assert s1["error"] == {"code": "PRE_UNMET"} and "state_diff" not in s1
    assert [c for c in s1["pre_check"] if not c["pass"]] == [
        {"subject": "drawer_top", "predicate": "open", "op": "==", "value": True, "actual": False, "pass": False}]


def test_failed_child_is_saved(store):  # noqa: F811
    backend = FakeBackend({"drawer_control": ActionResult(False, error_code="DRAWER_STUCK")})
    result = Runner(backend, ontology=ONTOLOGY, log_store=store).run(
        skill_task({"id": "s1", "skill": "open_drawer", "params": {"drawer_id": "drawer_top"}},
                   final=[{"id": "f1", "action": "move_to_named_pose", "params": {"pose_name": "home"}}]))
    saved = store.read_run(result.run_id)
    assert saved["run"]["failed_step"] == "s1.e2"
    assert [(s["id"], s["status"], s.get("error")) for s in saved["steps"]] == [
        ("s1", "FAILURE", {"code": "DRAWER_STUCK"}), ("s1.e1", "SUCCESS", None),
        ("s1.e2", "FAILURE", {"code": "DRAWER_STUCK"}), ("f1", "SUCCESS", None)]
    assert "state_diff" not in saved["steps"][0]


# ---- 6단계: 예시 태스크(contracts/examples/task_skill_steps.json) 끝까지 실행 ----

EXAMPLE = json.loads((ROOT / "contracts/examples/task_skill_steps.json").read_text(encoding="utf-8"))
WORLD = ONTOLOGY["world"]


class FakeRobot:
    """로봇·지식 노드 흉내. query_ontology 는 Runner 의 현재 상태와 온톨로지 world 로 답한다."""

    def __init__(self, visible=True, fail=None):
        self.visible, self.fail = visible, fail or {}     # fail: {동작: 에러 코드}
        self.runner: Runner | None = None
        self.calls: list[str] = []
        self.spoken: list[str] = []

    def __call__(self, action, params, timeout_sec):
        self.calls.append(action)
        if action in self.fail:
            return ActionResult(False, error_code=self.fail[action])
        if action == "speak":
            self.spoken.append(params["text"])
        if action == "query_ontology":
            item = params["item"]
            return ActionResult(True, {"name_ko": WORLD["items"][item]["name_ko"],
                                       "drawer_id": self.runner.state["located_in"][item]})
        if action == "inspect_region":                    # ICD: 못 찾아도 success, target_found=false
            found = {"target_found": True, "target": {"id": f"{params['search_target']}#1"}}
            return ActionResult(True, found if self.visible else {"target_found": False})
        return ActionResult(True)


def robot_runner(robot, **kw):
    runner = Runner(robot, schema=SCHEMA, ontology=ONTOLOGY, **kw)
    robot.runner = runner
    return runner


def test_example_fetch_car_key_end_to_end():
    robot = FakeRobot()
    runner = robot_runner(robot)
    result = runner.run(EXAMPLE)

    assert result.overall_status == "COMPLETED"
    assert robot.spoken == ["차키를 꺼내 올게요", "차키를 앞쪽 트레이에 놓았어요"]
    assert [(s["id"], s.get("state_diff")) for s in result.steps if "skill" in s] == [
        ("s3", {"open.drawer_top": [False, True]}),
        ("s4", {"gripper.robot": ["empty", "car_key"], "located_in.car_key": ["drawer_top", "gripper"]}),
        ("s5", {"gripper.robot": ["car_key", "empty"], "located_in.car_key": ["gripper", "handover_zone"]}),
        ("f1", {"open.drawer_top": [True, False]}),
    ]
    assert robot.calls == ["query_ontology", "speak",
                           "move_to_named_pose", "drawer_control",          # s3 open_drawer
                           "inspect_region", "pick_object",                 # s4 pick
                           "place_object",                                  # s5 place
                           "speak",
                           "drawer_control", "move_to_named_pose"]          # f1 close_drawer, f2 홈
    state = runner.state
    assert state["open"]["drawer_top"] is False and state["gripper"]["robot"] == "empty"
    assert state["located_in"]["car_key"] == "handover_zone"


def test_example_with_other_item_uses_bottom_drawer():
    robot = FakeRobot()
    runner = robot_runner(robot)
    result = runner.run(EXAMPLE, inputs={"target": "wallet"})
    assert result.overall_status == "COMPLETED"
    assert robot.spoken[0] == "지갑을 꺼내 올게요"
    assert next(s for s in result.steps if s["id"] == "s3")["params"] == {"drawer_id": "drawer_bottom"}
    assert runner.state["located_in"]["wallet"] == "handover_zone"
    assert runner.state["open"]["drawer_bottom"] is False


def test_example_item_not_visible_still_closes_drawer():
    robot = FakeRobot(visible=False)
    runner = robot_runner(robot)
    result = runner.run(EXAMPLE)

    assert result.overall_status == "FAILED"
    # 현재 동작: pick 의 expand 가 $scan.target.id 를 쓰므로 못 찾으면 변수 없음으로 실패 (아래 "확인 필요" 참고)
    assert (result.error_code, result.failed_step) == ("VAR_UNDEFINED", "s4.e2")
    assert robot.calls.count("inspect_region") == 1 and "pick_object" not in robot.calls   # 재시도 없음, 집기 안 함
    assert runner.state["open"]["drawer_top"] is False                 # finally 에서 서랍 닫음
    assert runner.state["located_in"]["car_key"] == "drawer_top"       # 차키는 그대로


def test_example_estop_during_pick_keeps_drawer_open_in_state():
    robot = FakeRobot(fail={"pick_object": "ESTOP"})
    runner = robot_runner(robot)
    result = runner.run(EXAMPLE)

    assert (result.overall_status, result.error_code, result.failed_step) == ("ABORTED", "ESTOP", "s4.e2")
    assert [(s["id"], s["status"]) for s in result.steps if s["id"] in ("f1", "f2")] == [
        ("f1", "SKIPPED"), ("f2", "SKIPPED")]                         # 비상정지 후 서랍 닫기·홈 이동 안 함
    assert runner.state["open"]["drawer_top"] is True                  # 실제처럼 서랍은 열린 채
    assert runner.state["gripper"]["robot"] == "empty"                 # 집기 실패 → effect 없음
    assert runner.halted


def test_example_rerun_after_estop_stops_at_open_drawer():
    # 비상정지로 서랍이 열린 채 남은 뒤 사람이 resume() 하고 같은 태스크를 다시 실행하면
    robot = FakeRobot(fail={"pick_object": "ESTOP"})
    runner = robot_runner(robot)
    runner.run(EXAMPLE)
    runner.resume()
    robot.fail = {}
    result = runner.run(EXAMPLE)

    # 현재 동작: open_drawer 의 pre(서랍 닫힘) 불충족 → 로봇 동작 없이 실패, finally 의 서랍 닫기·홈은 실행
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "PRE_UNMET", "s3")
    assert runner.state["open"]["drawer_top"] is False
