"""계약07 운영 (Runner 쪽) — 사용자(E) 승인 E-C-REQUEST-RUN-WIRE-20261011-07.
request_id 기억(재전송·충돌, 이번 기동만), 수락 때 run_id 고정, last_intent.request_id·run_id, accept_text 첫 안내 1회 →
안내가 성공해야 첫 동작, 없으면 P1 그대로. ROS 노드 연결은 test_runner_node.py."""
import copy
import json

from ready2go_runner.core import intent_router as ir
from ready2go_runner.core import planner as pl
from ready2go_runner.core.backend import RosBackend
from ready2go_runner.core.interpreter import Runner
from ready2go_runner.core.request_memory import RequestMemory

from test_tasks import MockRobot, ONTOLOGY, SCHEMA, TASK as FIND  # noqa: E402
from test_intent_router import router  # noqa: E402

BASE = {"intent": "find_item", "targets": ["eraser"], "confidence": 0.93, "source": {"stt_text": "지우개 찾아줘"}}


def text(**extra):
    return json.dumps({**BASE, **extra}, ensure_ascii=False)


# ---- 요청 기억 ----

def test_memory_keys_only_execution_requests_with_nonempty_id():
    m = RequestMemory()
    assert m.key(text())[0] is None                                    # ID 없음: P1 그대로
    assert m.key(text(request_id=None))[0] is None and m.key(text(request_id=""))[0] is None
    assert m.key(json.dumps({"intent": "cancel", "confidence": 1, "request_id": "r1"}))[0] is None   # 정지는 기억 안 함
    assert m.key("not json") == (None, None)
    rid, fp = m.key(text(request_id="r1"))
    assert rid == "r1" and fp == m.key(json.dumps(json.loads(text(request_id="r1")), sort_keys=True))[1]


def test_memory_keeps_first_decision():
    m = RequestMemory()
    m.remember("r1", "fp-a", {"decision": "run", "run_id": "X"})
    m.remember("r1", "fp-b", {"decision": "hold"})
    assert m.lookup("r1").summary == {"decision": "run", "run_id": "X"} and m.lookup("r1").fingerprint == "fp-a"
    assert RequestMemory().lookup("r1") is None                        # 새 기동 = 새 기억


# ---- 결정 요약·입력 ----

def test_summary_has_request_id_and_run_id_only_for_run():
    d = router().decide(text(request_id="r1", accept_text="지우개를 찾아올게요."), running=False, locked=False)
    assert d.kind == ir.RUN and d.summary()["run_id"] is None          # 노드가 수락할 때 정함
    d.run_id = "2026-10-11T08:00:00Z_aaaaaa"
    assert (d.summary()["request_id"], d.summary()["run_id"]) == ("r1", "2026-10-11T08:00:00Z_aaaaaa")
    busy = router().decide(text(request_id="r2"), running=True, locked=False)
    busy.run_id = "should-not-show"
    assert (busy.kind, busy.summary()["request_id"], busy.summary()["run_id"]) == (ir.REJECT, "r2", None)


def test_accept_text_input_only_when_nonempty_string():
    assert router().decide(text(accept_text="지우개를 찾아올게요."), False, False).inputs["accept_text"] == "지우개를 찾아올게요."
    for value in (None, "", "  "):
        assert "accept_text" not in router().decide(text(accept_text=value), False, False).inputs


# ---- 수락 안내 1회 → 성공해야 첫 동작 ----

def run_find(robot, inputs):
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    return runner.run(FIND, inputs, run_id="2026-10-11T08:00:00Z_fixed")


def test_accept_text_is_the_single_first_announcement():
    robot = MockRobot()
    result = run_find(robot, {"target": "eraser", "accept_text": "지우개를 찾아올게요."})
    assert result.overall_status == "COMPLETED" and result.run_id == "2026-10-11T08:00:00Z_fixed"
    assert robot.spoken[0] == "지우개를 찾아올게요." and "지우개를 찾아 올게요" not in robot.spoken   # 기존 s2 안내와 중복 없음
    assert robot.spoken.count("지우개를 찾아올게요.") == 1


def test_without_accept_text_old_announcement_p1_compatible():
    robot = MockRobot()
    assert run_find(robot, {"target": "eraser"}).overall_status == "COMPLETED"
    assert robot.spoken[0] == "지우개를 찾아 올게요"


def test_accept_announcement_failure_means_no_first_motion():
    """수락 안내 speak 실패(TTS 실패·시간 초과·취소) → 서랍 열기 등 첫 동작 없이 실패."""
    robot = MockRobot(fail={"speak": ["TTS_FAILED"]})
    result = run_find(robot, {"target": "eraser", "accept_text": "지우개를 찾아올게요."})
    assert (result.overall_status, result.failed_step) == ("FAILED", "s2.1")
    assert "/skills/drawer_control" not in robot.sent


def test_goal_plan_gets_accept_speak_before_first_skill():
    onto = copy.deepcopy(ONTOLOGY)
    result = pl.plan(onto["state"], onto, [{"predicate": "open", "subject": "drawer_top", "value": True}])
    task = ir.add_accept_speak(pl.to_task(result, "plan_drawer_top_true"), {"accept_text": "위 서랍을 열어 둘게요."})
    assert task["sequence"][1] == {"id": "pa", "action": "speak", "params": {"text": "$inputs.accept_text"}}
    assert task["sequence"][2].get("skill") == "open_drawer"
    plain = ir.add_accept_speak(pl.to_task(result, "plan_drawer_top_true"), {})
    assert all(s.get("id") != "pa" for s in plain["sequence"])
