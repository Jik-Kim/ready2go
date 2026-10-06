"""#17 /voice/intent → 태스크 라우팅 규칙 (core/intent_router.py, ROS 비의존).
E 통합 공지(#23): find_item → P1 태스크, cancel/status, 모호·미지원 요청 보류, 중복 실행 처리."""
import json
from pathlib import Path

import pytest

from ready2go_knowledge.core import ontology
from ready2go_runner.core import intent_router as ir

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "contracts/intent.schema.json").read_text(encoding="utf-8"))
ITEMS = ontology.load(ROOT / "knowledge/robot_ontology_demo.jsonld")["world"]["items"]
FIND = json.loads((ROOT / "tasks/find_item.json").read_text(encoding="utf-8"))
CHECK = json.loads((ROOT / "tasks/p1_demo_eraser.json").read_text(encoding="utf-8"))
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
                        "intent_confidence": 0.93}
    assert d.summary()["stt_text"] == "지우개 찾아줘" and d.summary()["task_id"] == "find_item"


def test_other_registered_item_becomes_target():
    d = router().decide(intent(targets=["car_key"]), running=False, locked=False)
    assert d.kind == ir.RUN and d.inputs["target"] == "car_key"


@pytest.mark.parametrize("text, reason", [
    ("지우개 찾아줘", ir.BAD_INTENT),                                        # JSON 아님
    (json.dumps({"intent": "find_item", "targets": ["eraser"]}), ir.BAD_INTENT),   # confidence 없음
    (intent(intent="fly"), ir.BAD_INTENT),                                  # 허용값 밖
    (intent(confidence=1.5), ir.BAD_INTENT),
    (intent(intent="unknown", targets=[]), ir.NEEDS_CLARIFY),
    (intent(intent="clarify", clarify_question="어느 서랍요?"), ir.NEEDS_CLARIFY),
    (intent(intent="find_list", targets=["morning_kit"]), ir.UNSUPPORTED_INTENT),   # P3
    (intent(intent="achieve_goal"), ir.UNSUPPORTED_INTENT),                 # P2
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
    assert "targets" not in (FIND.get("trigger") or {})
    assert router().decide(intent(targets=["car_key"]), running=False, locked=False).kind == ir.RUN


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
