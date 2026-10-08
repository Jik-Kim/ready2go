"""Unpacking 판단 원자 동작 (core/unpack.py): select_obstacle 치울 순서 (#120 C 회신 표, A 동의) ·
find_moved 재식별 (#109 C 수락). 로봇 동작 없음 — 촬영 결과와 치운 기록만 보고 답한다."""
import pytest

from ready2go_runner.core.backend import LOCAL, route
from ready2go_runner.core.unpack import find_moved, select_obstacle

WORLD = {"items": {"eraser": {"size_m": [0.06, 0.02, 0.012]}, "toy_hammer": {"size_m": [0.12, 0.04, 0.02]},
                   "car_key": {"size_m": [0.05, 0.03, 0.01]}, "lip_balm": {"size_m": [0.07, 0.02, 0.02]},
                   "cover_plate": {"size_m": [0.10, 0.08, 0.003]}}}
TOL = 0.02                                  # 시험용 값 — 실제 tol_m 은 놓기 오차 실측 뒤 [팀 확정 필요]


def obj(oid, x, y, top_z=0.01, yaw=0.0, **extra):
    return {"id": oid, "class": oid.split("#")[0], "top_z": top_z,
            "pose": {"frame": "drawer_top", "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True}, **extra}


def scan(target=None, *candidates):
    return {"target_found": target is not None, "target": target, "candidates": list(candidates),
            "visible_count": len(candidates) + (target is not None)}


def pick(params):
    result = select_obstacle(params, WORLD)
    assert result.success
    return result.output


def test_follows_occluders_up_to_the_top_one():
    """렌치(목표)를 망치가 덮고, 망치를 차키가 덮음 → 차키부터 (E #109 위 서랍 배치)."""
    s = scan(obj("eraser#1", 0.1, 0.1, occluded_by=["toy_hammer#1"]),
             obj("car_key#1", 0.1, 0.12, 0.03, occluded_by=[]),
             obj("toy_hammer#1", 0.1, 0.11, 0.02, occluded_by=["car_key#1"]))
    out = pick({"scan": s})
    assert (out["obstacle"]["id"], out["reason"]) == ("car_key#1", "occluded_by")


def test_clear_target_needs_nothing():
    out = pick({"scan": scan(obj("eraser#1", 0.1, 0.1, occluded_by=[]), obj("lip_balm#1", 0.15, 0.2, 0.02))})
    assert (out["obstacle"], out["reason"]) == (None, "target_clear")


def test_target_not_found_takes_free_candidate_with_largest_area():
    s = scan(None, obj("cover_plate#1", 0.1, 0.1, 0.02, occluded_by=[], visible_area_m2=0.008),
             obj("lip_balm#1", 0.15, 0.2, 0.025, occluded_by=[], visible_area_m2=0.0014),
             obj("toy_hammer#1", 0.1, 0.1, 0.03, occluded_by=["cover_plate#1"], visible_area_m2=0.002))
    out = pick({"scan": s})
    assert (out["obstacle"]["id"], out["reason"]) == ("cover_plate#1", "largest_visible")


def test_target_not_found_without_fields_takes_highest():
    out = pick({"scan": scan(None, obj("lip_balm#1", 0.15, 0.2, 0.025), obj("cover_plate#1", 0.1, 0.1, 0.004))})
    assert (out["obstacle"]["id"], out["reason"]) == ("lip_balm#1", "highest")


def test_unknown_occlusion_uses_overlap_and_height():
    """occluded_by 모름(null) → A 대안: 목표와 겹치고 더 높은 것. 떨어진 높은 물체는 고르지 않음."""
    target = obj("eraser#1", 0.10, 0.10, 0.012, occluded_by=None)
    s = scan(target, obj("lip_balm#1", 0.18, 0.25, 0.03), obj("cover_plate#1", 0.11, 0.10, 0.016))
    out = pick({"scan": s})
    assert (out["obstacle"]["id"], out["reason"]) == ("cover_plate#1", "overlap_higher")
    far = scan(target, obj("lip_balm#1", 0.18, 0.25, 0.03))
    assert pick({"scan": far})["obstacle"] is None


def test_box_model_target_with_valid_yaw_is_clear():
    """가림 필드가 없는 박스 모델 + yaw_valid true → 가림 의심 없음 (지금 P1 흐름 그대로)."""
    out = pick({"scan": scan(obj("eraser#1", 0.1, 0.1), obj("cover_plate#1", 0.11, 0.1, 0.02))})
    assert out["obstacle"] is None


def test_box_model_target_with_invalid_yaw_is_suspected():
    """A 보충(#120): yaw_valid=false 는 "가림 의심" → 겹치고 높은 것부터."""
    target = obj("eraser#1", 0.1, 0.1)
    target["pose"]["yaw_valid"] = False
    out = pick({"scan": scan(target, obj("cover_plate#1", 0.11, 0.1, 0.02))})
    assert out["obstacle"]["id"] == "cover_plate#1"


MOVED_HAMMER = {"class": "toy_hammer", "origin": obj("toy_hammer#1", 0.1, 0.11)["pose"],
                "placed": {"frame": "drawer_top", "position": [0.03, 0.25, 0.0], "yaw": 0.0}}


def test_already_moved_object_is_not_chosen_again():
    """#109: 옮긴 물체(놓은 자리 근처에서 다시 보임)는 같은 Unpacking 에서 다시 치우지 않음."""
    s = scan(None, obj("toy_hammer#2", 0.035, 0.255, 0.03, occluded_by=[], visible_area_m2=0.004),
             obj("cover_plate#1", 0.1, 0.1, 0.01, occluded_by=[], visible_area_m2=0.002))
    out = pick({"scan": s, "moved": [MOVED_HAMMER], "tol_m": TOL})
    assert out["obstacle"]["id"] == "cover_plate#1" and out["excluded"] == ["toy_hammer#2"]


def test_ambiguous_moved_object_is_held_back():
    """같은 class 가 2개(첫 시연 조건 위반) → 어느 쪽이 옮긴 것인지 확정 못 함 → 둘 다 고르지 않음."""
    s = scan(None, obj("toy_hammer#1", 0.1, 0.11, 0.03), obj("toy_hammer#2", 0.035, 0.255, 0.03),
             obj("cover_plate#1", 0.1, 0.1, 0.01))
    out = pick({"scan": s, "moved": [MOVED_HAMMER], "tol_m": TOL})
    assert out["obstacle"]["id"] == "cover_plate#1"
    assert out["held_back"] == ["toy_hammer#1", "toy_hammer#2"] and out["excluded"] == []


def test_occluder_already_moved_but_still_reported_stops():
    """목표를 덮은 물체가 후보에서 빠졌는데(옮김·모호) 아직 덮였다고 나옴 → 짐작으로 진행하지 않음."""
    s = scan(obj("eraser#1", 0.1, 0.1, occluded_by=["toy_hammer#1"]),
             obj("toy_hammer#1", 0.035, 0.255, 0.03, occluded_by=[]))
    out = pick({"scan": s, "moved": [MOVED_HAMMER], "tol_m": TOL})
    assert (out["obstacle"], out["reason"]) == (None, "occluder_unavailable")


def test_prefer_only_reorders_within_rule_candidates():
    """사용자 답(prefer)은 같은 규칙의 후보 안에서만 순서를 바꿈 (A 제안: 안전 판단은 못 넘김)."""
    s = scan(None, obj("cover_plate#1", 0.1, 0.1, 0.02, occluded_by=[], visible_area_m2=0.008),
             obj("lip_balm#1", 0.15, 0.2, 0.025, occluded_by=[], visible_area_m2=0.0014),
             obj("toy_hammer#1", 0.1, 0.1, 0.03, occluded_by=["cover_plate#1"]))
    assert pick({"scan": s, "prefer": "lip_balm"})["obstacle"]["id"] == "lip_balm#1"
    assert pick({"scan": s, "prefer": "toy_hammer"})["obstacle"]["id"] == "cover_plate#1"   # 덮인 것은 안 됨


@pytest.mark.parametrize("seen, status, distance", [
    ([obj("toy_hammer#3", 0.04, 0.26)], "found", 0.0141),
    ([obj("toy_hammer#3", 0.10, 0.11)], "ambiguous", 0.1565),          # 놓은 자리에서 멀리 — 이동 확정 안 함
    ([], "missing", None),
    ([obj("toy_hammer#3", 0.04, 0.26), obj("toy_hammer#4", 0.1, 0.1)], "ambiguous", None),
])
def test_find_moved(seen, status, distance):
    result = find_moved({"scan": scan(None, *seen), "record": MOVED_HAMMER, "tol_m": TOL}, WORLD)
    assert result.success and result.output["status"] == status and result.output["distance_m"] == distance
    assert (result.output["object"] is not None) == (status == "found")


def test_find_moved_target_counts_too():
    """목표로 잡힌 물체도 대조 대상 (target 은 candidates 에서 빠져 있음)."""
    s = scan(obj("toy_hammer#9", 0.031, 0.251))
    assert find_moved({"scan": s, "record": MOVED_HAMMER, "tol_m": TOL}, WORLD).output["status"] == "found"


@pytest.mark.parametrize("params", [{"scan": scan(), "record": MOVED_HAMMER},                  # tol_m 없음
                                   {"scan": scan(), "record": MOVED_HAMMER, "tol_m": -1},
                                   {"scan": None, "record": MOVED_HAMMER, "tol_m": TOL},
                                   {"scan": scan(), "record": {}, "tol_m": TOL}])
def test_find_moved_bad_params(params):
    assert find_moved(params, WORLD).error_code == "BAD_PARAMS"


def test_both_are_local_actions():
    assert route("select_obstacle").kind == LOCAL and route("find_moved").kind == LOCAL


# ---- 계약안 예시 태스크를 mock 으로 끝까지 (contracts/examples/task_unpack_select.json) ----

def test_example_task_unpacks_delivers_and_restores_in_reverse():
    """E #109 위 서랍 배치 모양: 목표(지우개)를 망치가, 망치를 차키가 덮음 → 차키 → 망치 순서로 고정 자리에 치움
    (망치는 aside_1 이 막혀 aside_2) → 지우개 전달 → finally 에서 거꾸로(망치 → 차키) 재식별해 원래 자리로.
    차키 원래 자리가 막히면(PLACE_BLOCKED) B 결정대로 고정 자리에 둔 채 끝냄. 로봇 동작은 FakeBackend."""
    import json
    from pathlib import Path
    from ready2go_runner.core.interpreter import ActionResult, Runner
    from ready2go_runner.core.ontology_query import local_action
    from test_tasks import ONTOLOGY, SCHEMA

    root = Path(__file__).resolve().parents[4]
    task = json.loads((root / "contracts/examples/task_unpack_select.json").read_text(encoding="utf-8"))
    eraser = obj("eraser#1", 0.10, 0.10, 0.012)
    key, hammer = obj("car_key#1", 0.10, 0.12, 0.03), obj("toy_hammer#1", 0.10, 0.11, 0.02)
    key_aside, hammer_aside = obj("car_key#2", 0.031, 0.032, 0.01), obj("toy_hammer#2", 0.032, 0.258, 0.02)
    scans = [
        scan({**eraser, "occluded_by": ["toy_hammer#1"]}, {**key, "occluded_by": []},
             {**hammer, "occluded_by": ["car_key#1"]}),
        scan({**eraser, "occluded_by": ["toy_hammer#1"]}, {**hammer, "occluded_by": []},
             {**key_aside, "occluded_by": []}),
        scan({**eraser, "occluded_by": []}, {**hammer_aside, "occluded_by": []}, {**key_aside, "occluded_by": []}),
        scan(None, hammer_aside, key_aside),                    # finally: 망치 되돌리기 전
        scan(None, obj("toy_hammer#3", 0.10, 0.11, 0.02), key_aside),   # 차키 되돌리기 전
    ]
    slots = {"aside_1": [0.03, 0.03, 0.0], "aside_2": [0.03, 0.26, 0.0]}
    place_results = [None, ActionResult(False, {"blocked_by": "car_key#2"}, "PLACE_BLOCKED"), None, None, None,
                     ActionResult(False, {"blocked_by": "toy_hammer#3"}, "PLACE_BLOCKED"), None]
    calls = []

    def execute(action, params, timeout_sec=None):
        calls.append((action, params))
        if action in ("select_obstacle", "find_moved"):
            return local_action(action, params, {}, ONTOLOGY["world"])
        if action == "inspect_region":
            return ActionResult(True, scans.pop(0))
        if action == "place_object":
            result = place_results.pop(0)
            if result is not None:
                return result
            where = {"frame": params["location"], "position": slots[params["slot"]], "yaw": 0.0} if "slot" in params \
                else params.get("pose") or {"frame": "handover_zone", "position": [0.02, 0.04, 0.0]}
            return ActionResult(True, {"slot": params.get("slot"), "placed_pose": where})
        return ActionResult(True, {})

    result = Runner(execute, schema=SCHEMA, ontology=ONTOLOGY).run(task)
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    picked = [p["target"]["id"] for a, p in calls if a == "pick_object"]
    assert picked == ["car_key#1", "toy_hammer#1", "eraser#1", "toy_hammer#2", "car_key#2"]
    placed = [p.get("slot") or ("origin" if "pose" in p else p["location"]) for a, p in calls if a == "place_object"]
    assert placed == ["aside_1", "aside_1", "aside_2", "handover_zone", "origin", "origin", "aside_1"]
    restore = [p["pose"]["position"][:2] for a, p in calls if a == "place_object" and "pose" in p]
    assert restore == [[0.10, 0.11], [0.10, 0.12]]                      # 망치 → 차키 (LIFO), 원래 자리
    assert result.blackboard["restore_stack"] == []
