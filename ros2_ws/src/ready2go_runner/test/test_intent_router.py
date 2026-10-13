"""#17 /voice/intent → 태스크 라우팅 규칙 (core/intent_router.py, ROS 비의존).
E 통합 공지(#23): find_item → P1 태스크, cancel/status, 모호·미지원 요청 보류, 중복 실행 처리."""
import json
from pathlib import Path

import jsonschema
import pytest

from ready2go_knowledge.core import ontology
from ready2go_runner.core import intent_router as ir

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "contracts/intent.schema.json").read_text(encoding="utf-8"))
ITEMS = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")["world"]["items"]
FIND = json.loads((ROOT / "tasks/find_item.json").read_text(encoding="utf-8"))
CHECK = json.loads((ROOT / "tasks/p1_demo_eraser.json").read_text(encoding="utf-8"))
TASK_SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))
EXAMPLE = (ROOT / "contracts/examples/intent_find_item.json").read_text(encoding="utf-8")


def router(tasks=None, min_confidence=0.6):
    return ir.IntentRouter(SCHEMA, tasks if tasks is not None else {"find_item": FIND}, ITEMS, min_confidence)


def intent(**fields):
    return json.dumps({"intent": "find_item", "targets": ["eraser"], "confidence": 0.9, **fields},
                      ensure_ascii=False)


def test_contract_example_runs_find_item_with_target_and_voice_inputs():
    d = router().decide(EXAMPLE, running=False, locked=False)
    assert d.kind == ir.RUN and d.task is FIND
    assert d.inputs == {"target": "eraser", "source": "voice", "stt_text": "지우개 찾아줘",
                        "intent_confidence": 0.93, "accept_text": "지우개를 찾아올게요."}   # 계약07 예시
    assert d.summary()["stt_text"] == "지우개 찾아줘" and d.summary()["task_id"] == "find_item"
    assert d.summary()["request_id"] == "example-find-07" and d.summary()["run_id"] is None   # run_id 는 노드가 수락할 때


@pytest.mark.parametrize("item", ["car_key", "masking_tape", "lip_balm"])
def test_p1_find_item_holds_other_items_before_any_motion(item):
    """10/07 P1 음성 실행은 지우개만 (E #17 사용자 결정): 정식 find_item 에 다른 등록 물품 → 서랍 열기 전에 보류."""
    assert FIND["trigger"]["targets"] == ["eraser"]
    d = router().decide(intent(targets=[item]), running=False, locked=False)
    assert (d.kind, d.reason, d.task) == (ir.HOLD, ir.UNSUPPORTED_ITEM, None)


def test_other_registered_item_becomes_target_when_task_has_no_targets():
    find_any = {**FIND, "trigger": {k: v for k, v in FIND["trigger"].items() if k != "targets"}}
    d = router({"find_item": find_any}).decide(intent(targets=["car_key"]), running=False, locked=False)
    assert d.kind == ir.RUN and d.inputs["target"] == "car_key"


@pytest.mark.parametrize("text, reason", [
    ("지우개 찾아줘", ir.BAD_INTENT),                                        # JSON 아님
    (json.dumps({"intent": "find_item", "targets": ["eraser"]}), ir.BAD_INTENT),   # confidence 없음
    (intent(intent="fly"), ir.BAD_INTENT),                                  # 허용값 밖
    (intent(confidence=1.5), ir.BAD_INTENT),
    (intent(intent="unknown", targets=[]), ir.NEEDS_CLARIFY),
    (intent(intent="clarify", clarify_question="어느 서랍요?"), ir.NEEDS_CLARIFY),
    (intent(intent="find_list", targets=["morning_kit"]), ir.UNSUPPORTED_INTENT),   # P3
    (intent(intent="achieve_goal"), ir.NO_GOAL),                            # P2 목표형인데 goals 없음 (#150)
    (intent(confidence=0.3), ir.LOW_CONFIDENCE),
    (intent(targets=[]), ir.NO_TARGET),
    (intent(targets=None), ir.BAD_INTENT),
    (json.dumps({"intent": "find_item", "confidence": 0.9}), ir.NO_TARGET),
    (intent(targets=["eraser", "car_key"]), ir.MULTI_TARGET),               # P1 은 물품 하나
    (intent(targets=["phone"]), ir.UNKNOWN_ITEM),                           # 온톨로지에 없음
])
def test_hold_does_not_run(text, reason):
    d = router().decide(text, running=False, locked=False)
    assert (d.kind, d.reason, d.task) == (ir.HOLD, reason, None)


def test_confidence_at_threshold_runs():
    assert router(min_confidence=0.6).decide(intent(confidence=0.6), False, False).kind == ir.RUN


def test_duplicate_while_running_is_rejected_not_queued():
    d = router().decide(intent(), running=True, locked=False)
    assert (d.kind, d.reason, d.task) == (ir.REJECT, ir.BUSY, None)


def test_locked_rejects_new_task():
    d = router().decide(intent(), running=False, locked=True)
    assert (d.kind, d.reason) == (ir.REJECT, ir.LOCKED)


def test_hold_reason_wins_over_busy():
    """실행 중에 들어온 모호한 요청은 BUSY 가 아니라 보류 이유로 남긴다 (음성 평가에서 해석 결과를 보도록)."""
    assert router().decide(intent(intent="unknown"), running=True, locked=False).reason == ir.NEEDS_CLARIFY


@pytest.mark.parametrize("running, reason", [(True, None), (False, ir.NOT_RUNNING)])
def test_cancel_regardless_of_confidence(running, reason):
    d = router().decide(json.dumps({"intent": "cancel", "confidence": 0.1}), running=running, locked=False)
    assert (d.kind, d.reason) == (ir.CANCEL, reason)


def test_cancel_while_locked_is_still_cancel():
    d = router().decide(json.dumps({"intent": "cancel", "confidence": 0.9}), running=True, locked=True)
    assert d.kind == ir.CANCEL


def test_status():
    d = router().decide(json.dumps({"intent": "status", "confidence": 0.9}), running=True, locked=False)
    assert d.kind == ir.STATUS


# ---- 인텐트 → 태스크 표 ----

def test_tasks_by_intent_uses_trigger():
    table = ir.tasks_by_intent([FIND, CHECK])           # p1_demo_eraser 는 trigger.intent 가 없음 (targets 만)
    assert table["find_item"] is FIND and len([t for t in table.values() if t is CHECK]) == 0


def test_override_replaces_trigger_task_for_demo():
    """10/08 시연: 벽 배치·nudge → find_item 음성을 p1_demo_eraser 로 (E 통합 공지)."""
    table = ir.tasks_by_intent([FIND, CHECK], {"find_item": CHECK})
    assert table["find_item"] is CHECK
    d = router(table).decide(EXAMPLE, running=False, locked=False)
    assert d.task is CHECK and d.inputs["target"] == "eraser"


@pytest.mark.parametrize("item", ["car_key", "masking_tape"])
def test_demo_task_holds_other_items_before_any_motion(item):
    """#89 PM·D P1: 지우개 전용 시연 태스크에 다른 등록 물품 → 실행하지 않고 보류 (서랍 열기 전에)."""
    assert CHECK["trigger"]["targets"] == ["eraser"]
    table = ir.tasks_by_intent([FIND, CHECK], {"find_item": CHECK})
    d = router(table).decide(intent(targets=[item]), running=False, locked=False)
    assert (d.kind, d.reason, d.task) == (ir.HOLD, ir.UNSUPPORTED_ITEM, None)
    assert d.summary()["decision"] == ir.HOLD and d.summary()["reason"] == ir.UNSUPPORTED_ITEM


def test_task_without_targets_accepts_any_registered_item():
    find_any = {**FIND, "trigger": {"intent": "find_item"}}
    assert router({"find_item": find_any}).decide(intent(targets=["car_key"]), running=False, locked=False).kind == ir.RUN


BAD_TARGETS = ["car_key_eraser", 1, {"car_key": True}, [], [1], ["eraser", "eraser"], [""]]


@pytest.mark.parametrize("bad", BAD_TARGETS)
def test_task_schema_rejects_malformed_trigger_targets(bad):
    """#89 D P1: trigger.targets 는 계약상 물품 키 문자열 배열(1개 이상, 중복 없음)."""
    jsonschema.validate(CHECK, TASK_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(dict(CHECK, trigger={"targets": bad}), TASK_SCHEMA)


@pytest.mark.parametrize("bad", ["car_key_eraser", {"car_key": True}, ("car_key",)])
def test_malformed_targets_hold_instead_of_substring_match(bad):
    """스키마 검사를 거치지 않은 태스크라도 목록이 아니면 부분 문자열로 통과시키지 않고 보류."""
    task = dict(CHECK, trigger={"targets": bad})
    d = router({"find_item": task}).decide(intent(targets=["car_key"]), running=False, locked=False)
    assert (d.kind, d.reason, d.task) == (ir.HOLD, ir.UNSUPPORTED_ITEM, None)


def test_duplicate_trigger_without_override_is_error():
    other = dict(FIND, task_id="find_item_copy")
    with pytest.raises(ValueError, match="둘 이상"):
        ir.tasks_by_intent([FIND, other])
    assert ir.tasks_by_intent([FIND, other], {"find_item": CHECK})["find_item"] is CHECK


def test_repository_tasks_have_unique_triggers():
    tasks = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "tasks").glob("*.json"))]
    assert ir.tasks_by_intent(tasks)["find_item"]["task_id"] == "find_item"


def test_parse_overrides():
    assert ir.parse_overrides(" find_item=/tasks/p1_demo_eraser.json , ") == {
        "find_item": "/tasks/p1_demo_eraser.json"}
    assert ir.parse_overrides("") == {}
    with pytest.raises(ValueError):
        ir.parse_overrides("find_item")


# ---- #150 achieve_goal → 플래너 (P2, FR-PLN-02) ----

GOAL = json.loads((ROOT / "contracts/examples/intent_goal.json").read_text(encoding="utf-8"))


def test_achieve_goal_goes_to_planner_with_goals_and_voice_inputs():
    d = router().decide(json.dumps(GOAL, ensure_ascii=False), running=False, locked=False)
    assert d.kind == ir.PLAN and d.goals == GOAL["goals"] and d.task is None
    assert d.inputs["goals"] == GOAL["goals"] and d.inputs["source"] == "voice"
    assert d.inputs["stt_text"] == GOAL["source"]["stt_text"]


@pytest.mark.parametrize("change, kind, reason", [
    ({"confidence": 0.2}, ir.HOLD, ir.LOW_CONFIDENCE),
    ({"goals": []}, ir.HOLD, ir.NO_GOAL),
    ({"goals": [{"predicate": "located_in", "subject": "phone", "value": "drawer_top"}]}, ir.HOLD, ir.UNKNOWN_ITEM),
])
def test_achieve_goal_hold_before_planning(change, kind, reason):
    d = router().decide(json.dumps({**GOAL, **change}, ensure_ascii=False), running=False, locked=False)
    assert (d.kind, d.reason, d.task) == (kind, reason, None)


@pytest.mark.parametrize("running, locked, reason", [(True, False, ir.BUSY), (False, True, ir.LOCKED)])
def test_achieve_goal_rejected_when_busy_or_locked(running, locked, reason):
    d = router().decide(json.dumps(GOAL, ensure_ascii=False), running=running, locked=locked)
    assert (d.kind, d.reason) == (ir.REJECT, reason)


def test_registered_achieve_goal_task_still_wins():
    """tasks/ 에 trigger.intent=achieve_goal 태스크를 두면 그 태스크 (플래너 대신, P3 레지스트리 호환)."""
    custom = {"task_id": "custom_goal", "trigger": {"intent": "achieve_goal"}, "sequence": []}
    d = router({"achieve_goal": custom}).decide(json.dumps(GOAL, ensure_ascii=False), running=False, locked=False)
    assert d.kind == ir.RUN and d.task is custom



END_TASK = {"intent": "end_task", "targets": [], "confidence": 0.3, "request_id": "e-1", "boot_id": "b", "run_id": "r"}


@pytest.mark.parametrize("running, locked", [(True, False), (False, True), (False, False)])
def test_end_task_is_accepted_regardless_of_confidence_and_lock(running, locked):
    """계약 W3 end_task (#271, E3): 정지처럼 신뢰도·잠김과 상관없이 END — 대상 확인·정지·폐기는 노드가 (잠금 해제 아님)."""
    d = router().decide(json.dumps(END_TASK), running=running, locked=locked)
    assert (d.kind, d.reason) == (ir.END, None) and d.summary()["decision"] == "end"


def test_end_task_without_required_fields_is_bad_intent():
    for drop in ("boot_id", "run_id", "request_id"):
        doc = {k: v for k, v in END_TASK.items() if k != drop}
        assert router().decide(json.dumps(doc), running=True, locked=False).reason == ir.BAD_INTENT, drop
