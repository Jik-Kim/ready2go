"""#10 백엔드 (ROS 비의존 부분): 동작별 보낼 곳, JSON 변환, query_ontology."""
import json
from pathlib import Path

import pytest

from ready2go_knowledge.core import ontology
from ready2go_runner.core.backend import (ACTION, INSPECT_SERVICE, LOCAL, SERVICE, SPEAK_ACTION, Reply, RosBackend,
                                          route, skill_servers, to_result)
from ready2go_runner.core.interpreter import Runner
from ready2go_runner.core.ontology_query import query

ROOT = Path(__file__).resolve().parents[4]
ONTOLOGY = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))
WORLD = {"items": {"car_key": {"name_ko": "차키", "grip_force": None}, "eraser": {"name_ko": "지우개"}}}
STATE = {"open": {"drawer_top": False}, "located_in": {"car_key": "drawer_top"}}


# ---- 보낼 곳 (docs/interfaces.md 5장) ----

@pytest.mark.parametrize("action, kind, name", [
    ("drawer_control", ACTION, "/skills/drawer_control"),
    ("move_to_named_pose", ACTION, "/skills/move_to_named_pose"),
    ("pick_object", ACTION, "/skills/pick_object"),
    ("place_object", ACTION, "/skills/place_object"),
    ("nudge_object", ACTION, "/skills/nudge_object"),
    ("speak", ACTION, SPEAK_ACTION),
    ("inspect_region", SERVICE, INSPECT_SERVICE),
    ("query_ontology", LOCAL, "query_ontology"),
    ("update_ontology", LOCAL, "update_ontology"),
])
def test_route_follows_icd(action, kind, name):
    assert (route(action).kind, route(action).name) == (kind, name)


# ---- 응답 → ActionResult ----

@pytest.mark.parametrize("reply, expected", [
    (Reply(True, "", '{"slot": "s1"}'), (True, {"slot": "s1"}, None)),
    (Reply(True, "", ""), (True, None, None)),                          # 반환값 없는 동작 (speak 등)
    (Reply(False, "DRAWER_STUCK", ""), (False, None, "DRAWER_STUCK")),
    (Reply(False, "", ""), (False, None, None)),                        # 코드 없음 → Runner 가 ACTION_FAILED
    (Reply(True, "", "{broken"), (False, None, "BACKEND_ERROR")),       # 성공이라도 결과를 못 읽으면 실패
])
def test_reply_to_result(reply, expected):
    result = to_result(reply)
    assert (result.success, result.output, result.error_code) == expected


def test_params_sent_as_json_and_service_fields():
    sent = []
    backend = RosBackend(lambda name, params_json, t: sent.append((name, params_json, t)) or Reply(True),
                         lambda name, region, target, t: sent.append((name, region, target, t)) or Reply(True),
                         lambda: STATE, WORLD)
    backend("speak", {"text": "차키를 꺼내 올게요"}, None)
    backend("drawer_control", {"drawer_id": "drawer_top", "state": "open"}, 30)
    backend("inspect_region", {"region": "drawer_top", "search_target": "car_key"}, 5)
    backend("inspect_region", {"region": "drawer_top"}, None)               # search_target 없음 → 빈 문자열
    assert sent[0] == (SPEAK_ACTION, '{"text": "차키를 꺼내 올게요"}', None)  # 한글 그대로 (ensure_ascii=False)
    assert sent[1] == ("/skills/drawer_control", '{"drawer_id": "drawer_top", "state": "open"}', 30)
    assert sent[2] == (INSPECT_SERVICE, "drawer_top", "car_key", 5)
    assert sent[3] == (INSPECT_SERVICE, "drawer_top", "", None)


# ---- query_ontology (Runner 상태로 답함) ----

def test_query_item():
    result = query({"item": "car_key"}, STATE, WORLD)
    assert result.success
    assert result.output == {"item": "car_key", "name_ko": "차키", "drawer_id": "drawer_top", "grip_force": None}


@pytest.mark.parametrize("params, code", [
    ({"item": "watch"}, "UNKNOWN_ITEM"),            # world 에 없음
    ({"item": "eraser"}, "UNKNOWN_ITEM"),           # world 에는 있지만 위치를 모름
    ({"state": "open"}, "BAD_QUERY"),               # 경로는 predicate.subject
    ({}, "BAD_QUERY"),
    ({"list": "commute_set"}, "NOT_SUPPORTED"),     # 다중 조회는 P2 (for_each)
    ({"class": "Key"}, "NOT_SUPPORTED"),
])
def test_query_errors(params, code):
    result = query(params, STATE, WORLD)
    assert (result.success, result.error_code) == (False, code)


def test_query_state_path():
    assert query({"state": "open.drawer_top"}, STATE, WORLD).output == {"path": "open.drawer_top", "value": False}


def test_update_ontology_not_supported_in_p1():
    backend = RosBackend(None, None, lambda: STATE, WORLD)
    assert backend("update_ontology", {"item": "car_key", "drawer_id": "drawer_top"}, None).error_code == "NOT_SUPPORTED"


def test_query_uses_current_runner_state():
    # Runner 가 스킬 effect 로 바꾼 상태를 다음 조회가 그대로 봄 (상태의 단일 관리자)
    runner = Runner(lambda *a: None, ontology=ONTOLOGY)
    backend = RosBackend(None, None, lambda: runner.state, ONTOLOGY["world"])
    runner._state["located_in"]["car_key"] = "gripper"
    assert backend("query_ontology", {"item": "car_key"}, None).output["drawer_id"] == "gripper"


# ---- Runner + 백엔드: 예시 태스크가 ICD 이름 그대로 나가는지 ----

def test_example_task_through_backend():
    task = json.loads((ROOT / "contracts/examples/task_skill_steps.json").read_text(encoding="utf-8"))
    sent = []

    def call_action(name, params_json, timeout_sec):
        sent.append(name)
        return Reply(True)

    def call_service(name, region, search_target, timeout_sec):
        sent.append(name)
        return Reply(True, "", json.dumps({"target_found": True, "target": {"id": f"{search_target}#1"}}))

    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(call_action, call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(task)

    assert result.overall_status == "COMPLETED", result.steps
    drawer = ONTOLOGY["state"]["located_in"]["car_key"]
    assert sent == [SPEAK_ACTION,                                        # s1 query_ontology 는 프로세스 안
                    "/skills/move_to_named_pose", "/skills/drawer_control",   # s3 open_drawer
                    INSPECT_SERVICE, "/skills/pick_object",               # s4 pick
                    "/skills/place_object",                               # s5 place
                    SPEAK_ACTION,
                    "/skills/drawer_control", "/skills/move_to_named_pose"]   # finally
    assert result.steps[0]["output"]["drawer_id"] == drawer
    assert runner.state["located_in"]["car_key"] == "handover_zone"


# ---- #108 D P1: 실행 전 필요한 스킬 서버 확인 ----

def test_skill_servers_lists_robot_actions_of_task_and_skills():
    task = json.loads((ROOT / "tasks/find_item.json").read_text(encoding="utf-8"))
    names = skill_servers(task, ONTOLOGY["skills"])
    assert {"/skills/move_to_named_pose", "/skills/drawer_control", "/skills/pick_object",
            "/skills/place_object"} <= names                          # skill expand 안의 동작까지
    assert all(n.startswith("/skills/") for n in names)                # speak·inspect·query·if 는 아님
