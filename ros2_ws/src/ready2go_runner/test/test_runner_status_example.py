"""contracts/examples/runner_status.json (계약07 E-C-REQUEST-RUN-WIRE-20261011-07) — 기존 칸은 지금 코드와 같고,
새 칸 last_intent.request_id·run_id 는 승인된 규칙대로인지. Runner 구현(운영 PR) 전이라 새 칸은 예시 규칙만 본다."""
import json
from pathlib import Path

from ready2go_runner.core.intent_router import Decision
from ready2go_runner.core.runner_status import build_status

EXAMPLE = json.loads((Path(__file__).resolve().parents[4] / "contracts/examples/runner_status.json").read_text(encoding="utf-8"))
NODE_KEYS = {"last_intent", "state_reset_at"}                      # runner_node 가 build_status 뒤에 붙이는 칸
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
