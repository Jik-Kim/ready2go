"""contracts/examples/runner_status.json (계약07 E-C-REQUEST-RUN-WIRE-20261011-07) — 기존 칸은 지금 코드와 같고,
새 칸 last_intent.request_id·run_id 는 승인된 규칙대로인지. Runner 구현(운영 PR) 전이라 새 칸은 예시 규칙만 본다."""
import json
from pathlib import Path

from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.intent_router import Decision
from ready2go_runner.core.runner_status import build_status

EXAMPLE = json.loads((Path(__file__).resolve().parents[4] / "contracts/examples/runner_status.json").read_text(encoding="utf-8"))
NODE_KEYS = {"last_intent", "accepted", "state_reset_at", "boot_id", "seq", "stamp"}   # runner_node 가 붙이는 칸 (boot_id·seq·stamp 계약 W4, accepted #376)
NEW_INTENT_KEYS = {"request_id", "run_id"}                          # 계약07


def cases():
    return {c["case"]: c["status"] for c in EXAMPLE["cases"]}


def test_existing_fields_match_current_code():
    keys = set(build_status(False, False, None, None, None, None, None, False)) | NODE_KEYS
    summary = set(Decision(kind="hold").summary())
    for name, status in cases().items():
        assert set(status) == keys, name
        if status["last_intent"] is not None:
            assert set(status["last_intent"]) == summary | NEW_INTENT_KEYS, name


def test_run_id_only_for_accepted_and_fixed_through_fast_completion():
    c = cases()
    for name, status in c.items():
        intent = status["last_intent"]
        assert (intent["run_id"] is not None) == (intent["decision"] == "run"), name
    done = c["accepted_fast_completed"]
    assert done["phase"] == "idle" and done["last"]["run_id"] == done["last_intent"]["run_id"]
    assert c["accepted_running"]["last_intent"]["run_id"] == done["last_intent"]["run_id"]


def test_busy_request_does_not_take_the_running_run_id():
    busy = cases()["reject_busy_while_other_run"]
    assert busy["phase"] == "running" and busy["last_intent"]["reason"] == "BUSY"
    assert busy["last_intent"]["request_id"] and busy["last_intent"]["run_id"] is None


def test_legacy_request_without_id_still_runs():
    legacy = cases()["legacy_without_request_id"]["last_intent"]
    assert legacy["request_id"] is None and legacy["decision"] == "run" and legacy["run_id"]


def test_request_id_null_input_is_bad_intent_but_missing_is_legacy():
    """입력 request_id: 없으면 기존 동작(상태 null), null·빈 문자열은 스키마 위반 → hold BAD_INTENT. accept_text 는 null 허용."""
    import jsonschema
    from ready2go_runner.core import intent_router as ir
    root = Path(__file__).resolve().parents[4]
    schema = json.loads((root / "contracts/intent.schema.json").read_text(encoding="utf-8"))
    router = ir.IntentRouter(schema, {"find_item": {"task_id": "find_item"}}, {"eraser": {}}, 0.6)
    base = {"intent": "find_item", "targets": ["eraser"], "confidence": 0.9}
    assert router.decide(json.dumps(base), False, False).kind == "run"
    for bad in (None, ""):
        decision = router.decide(json.dumps({**base, "request_id": bad}), False, False)
        assert (decision.kind, decision.reason) == ("hold", "BAD_INTENT")
    jsonschema.validate({**base, "request_id": "r-1", "accept_text": None}, schema)


def test_halt_cases_match_code_and_separate_request_from_stop_confirmation():
    """halt 계약안(#152·#187): 칸은 Runner.halt_summary 와 같고, 요청(requested)과 실제 정지 확인을 섞지 않는다."""
    runner = Runner(lambda a, p, t: ActionResult(True))
    runner.halt()
    keys = set(runner.halt_summary)
    seen = set()
    for name, status in cases().items():
        halt = status["halt"]
        assert (halt is not None) == name.startswith(("stop_", "halted_", "suspended_")), name
        if halt is None:
            continue
        assert set(halt) == keys and halt["stop"] in {"requested", "confirmed", "unconfirmed", "none"}, name
        seen.add(halt["stop"])
        if halt["stop"] == "requested":         # 백엔드 최종 결과 전 — 실행은 아직 running, 결과 칸 없음
            assert status["phase"] == "running" and halt["response_code"] is None and halt["response_received_at"] is None, name
        if halt["stop"] in ("confirmed", "unconfirmed") and not name.startswith("suspended_"):
            assert status["phase"] == "halted", name    # 재개 대기는 잠금이 풀려 idle (W4 halt.resume)
        if halt["stop"] == "confirmed":         # 백엔드 최종 결과를 받았을 때만 (#259 E P1)
            assert halt["response_received_at"], name
        if halt["stop"] == "unconfirmed":       # B 의 미확인 코드(시각 있음) 또는 결과 없음(둘 다 null)
            assert (halt["response_code"] in {"STOP_UNCONFIRMED", "STATE_UNKNOWN", "MOVE_UNCONFIRMED"}
                    and halt["response_received_at"]) or (halt["response_code"], halt["response_received_at"]) == (None, None), name
        if halt["stop"] == "none":
            assert halt["canceled_goals"] == 0, name
        assert halt["locked"] == (status["phase"] == "halted" or halt["stop"] == "requested"), name
        assert halt["boot_id"] and (halt["run_id"] is None) == (halt["source"] == "service" and halt["stop"] == "none"), name
    refused = cases()["stop_confirmed_then_refused_new_request"]   # 잠긴 동안 새 요청: last 는 거절 실행, halt 는 그대로
    assert refused["last"]["run_id"] != refused["halt"]["run_id"]
    assert refused["halt"] == cases()["stop_confirmed_halted"]["halt"]
    assert seen == {"requested", "confirmed", "unconfirmed", "none"}
    lost = cases()["stop_no_backend_result"]["halt"]
    assert (lost["stop"], lost["response_code"], lost["response_received_at"]) == ("unconfirmed", None, None)


def test_w4_boot_seq_and_resume_offer():
    """계약 W4 (#271): 모든 상태에 boot_id·seq·stamp, halt.boot_id 와 최상위 boot_id 같음, halt.resume 은 재개 대기에만 —
    offered 면 잠금 풀림(locked false), 질문·요청은 재개 질문·답 구현 전 null."""
    for name, status in cases().items():
        assert status["boot_id"] and isinstance(status["seq"], int) and status["stamp"], name
        halt = status["halt"]
        if halt:
            assert halt["boot_id"] == status["boot_id"], name
            assert (halt["resume"] is not None) == name.startswith("suspended_"), name
    offer = cases()["suspended_resume_offered"]["halt"]
    assert offer["resume"]["offered"] and not offer["locked"] and offer["resume"]["question"] is None


FAILURE_KEYS = {"run_id", "boot_id", "code", "step", "action", "case_id", "strategy", "text"}


def test_last_failure_and_accepted_shape_match_code():
    """#376: last 에 failure(FAILED 만, 그 밖 null) — 칸은 코드(build_status·failure_record)와 같음. accepted 는 run 결정 요청."""
    from ready2go_runner.core.interpreter import RunResult, StepFailed, failure_record
    code_last = build_status(False, False, None, None, None, RunResult("COMPLETED", {}, run_id="r"), "t", False)["last"]
    sample = failure_record(StepFailed("s1", "X"), [], "r", "b")
    for name, status in cases().items():
        if status["last"] is not None:
            assert set(status["last"]) == set(code_last), name
            failure = status["last"]["failure"]
            assert (failure is not None) == (status["last"]["overall_status"] == "FAILED"), name
            if failure is not None:
                assert set(failure) == set(sample) == FAILURE_KEYS, name
                assert failure["run_id"] == status["last"]["run_id"] and failure["boot_id"] == status["boot_id"], name
                assert (failure["case_id"] is None) == (failure["strategy"] is None), name
                assert failure["strategy"] in (None, "impossible"), name
        accepted = status["accepted"]
        if status["last_intent"] and status["last_intent"]["decision"] == "run":
            assert accepted["run_id"] == status["last_intent"]["run_id"], name


def test_status_question_does_not_move_accepted():
    """'왜 멈췄어?' 상태 질문이 last_intent 를 덮어도 accepted·last.failure 는 그대로 — 최신 결정과 최근 수락 요청을 구분 (#376 E)."""
    c = cases()
    failed, asked = c["failed_with_refusal_reason"], c["status_question_after_failure"]
    assert asked["last_intent"]["decision"] == "status" and asked["last_intent"]["run_id"] is None
    assert asked["accepted"] == failed["accepted"] and asked["last"] == failed["last"]
    assert asked["accepted"]["run_id"] == asked["last"]["failure"]["run_id"]
