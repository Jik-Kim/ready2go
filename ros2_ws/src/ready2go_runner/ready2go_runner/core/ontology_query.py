"""query_ontology·update_ontology 원자 동작 (ROS 비의존) — docs/runner.md 7.1 ②, docs/interfaces.md.

ICD 상 ROS 인터페이스 없이 ros2-core 프로세스 안에서 처리한다. 현재 상태는 Runner 가 단일 관리자이므로
(ontology.md 7.8) Runner 상태와 온톨로지 world 로 답한다. 상태를 바꾸는 것은 스킬 effect 뿐이다.

Phase 1 범위: 물품 하나 조회(item), 상태 경로 조회(state).
P1 미지원: list·class 다중 조회(번들 요청은 for_each 가 필요한 P2), update_ontology(P1 시나리오에 없음).
"""
from __future__ import annotations

from ready2go_knowledge.core import ontology

from .interpreter import ActionResult
from .unpack import find_moved, select_obstacle

# select_obstacle·find_moved: Unpacking 판단 (core/unpack.py, #120·#109) — 로봇 동작 없음
LOCAL_ACTIONS = {"query_ontology", "update_ontology", "select_obstacle", "find_moved"}
UNKNOWN_ITEM = "UNKNOWN_ITEM"           # world 에 없는 물품이거나 위치(located_in)를 모름
BAD_QUERY = "BAD_QUERY"                 # 조회 파라미터 형식 오류 (state 경로는 "predicate.subject")
NOT_SUPPORTED = "NOT_SUPPORTED"         # P1 에서 지원하지 않는 조회·동작


def local_action(action: str, params: dict, state: dict, world: dict) -> ActionResult:
    if action == "query_ontology":
        return query(params, state, world)
    if action == "select_obstacle":
        return select_obstacle(params, world)
    if action == "find_moved":
        return find_moved(params, world)
    return ActionResult(False, error_code=NOT_SUPPORTED)


def query(params: dict, state: dict, world: dict) -> ActionResult:
    if "item" in params:
        item = params["item"]
        info = world.get("items", {}).get(item)
        drawer = ontology.get(state, "located_in", item)
        if not isinstance(info, dict) or drawer is None:
            return ActionResult(False, error_code=UNKNOWN_ITEM)
        return ActionResult(True, {"item": item, "name_ko": info.get("name_ko", item),
                                   "drawer_id": drawer, "grip_force": info.get("grip_force")})
    if "state" in params:                       # 경로 형식은 state_diff 키와 같음 (예: "open.drawer_top")
        path = params["state"]
        predicate, _, subject = path.partition(".") if isinstance(path, str) else ("", "", "")
        if not predicate or not subject:
            return ActionResult(False, error_code=BAD_QUERY)
        return ActionResult(True, {"path": path, "value": ontology.get(state, predicate, subject)})
    if "list" in params or "class" in params:
        return ActionResult(False, error_code=NOT_SUPPORTED)
    return ActionResult(False, error_code=BAD_QUERY)
