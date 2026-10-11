"""tasks/find_with_unpack.json (P2 Unpacking) 을 겹친 장면 mock(core/mock_scene.py)으로 끝까지 실행.
치우기 순서·고정 자리(막히면 다른 자리)·전달·역순 재식별 복구·닫기·홈, 그리고 실패·중단 경로를 확인한다.
mock 이 B·A 실물 동작(얹힌 물체 집기·지지면)과 다를 수 있으므로 흐름 시험이다 (FR-ACT-04 실물 검증 아님)."""
import json
from pathlib import Path

import pytest

from ready2go_runner.core.backend import SPEAK_ACTION, Reply, RosBackend
from ready2go_runner.core.interpreter import Runner
from ready2go_runner.core.logstore import MemoryLogStore
from ready2go_runner.core.mock_scene import MockScene
from ready2go_runner.core.mock_skills import MockSkills

from test_tasks import ONTOLOGY, SCHEMA  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
TASK = json.loads((ROOT / "tasks/find_with_unpack.json").read_text(encoding="utf-8"))


class SceneRobot:
    """ROS 대신 MockSkills(장면)로 답하는 call_action·call_service. 보낸 동작·파라미터를 기록."""

    def __init__(self, scene, failures=None):
        self.skills = MockSkills(failures or {}, scene=MockScene(scene))
        self.calls: list[tuple[str, dict]] = []
        self.spoken: list[str] = []

    def call_action(self, name, params_json, timeout_sec):
        params = json.loads(params_json)
        if name == SPEAK_ACTION:
            self.spoken.append(params.get("text", ""))
            return Reply(True)
        action = name.rsplit("/", 1)[-1]
        self.calls.append((action, params))
        reply = self.skills.respond(action, params)
        return Reply(reply.success, reply.error_code, "" if reply.output is None else json.dumps(reply.output))

    def call_service(self, name, region, search_target, timeout_sec):
        self.calls.append(("inspect_region", {"region": region, "search_target": search_target}))
        reply = self.skills.inspect(region, search_target)
        return Reply(reply.success, reply.error_code, "" if reply.output is None else json.dumps(reply.output))

    def picked(self):
        return [p["target"]["class"] for a, p in self.calls if a == "pick_object"]

    def placed(self):
        return [p.get("slot") or ("origin" if "pose" in p else p["location"]) for a, p in self.calls if a == "place_object"]


def run(scene, target, failures=None):
    robot = SceneRobot(scene, failures)
    store = MemoryLogStore()
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY, log_store=store)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(TASK, {"target": target})
    return runner, robot, result


def steps(result):
    return [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]


def test_unpacks_two_delivers_and_restores_in_reverse():
    """A #109 위 칸 시나리오(사용자 결정 10/08): 렌치 ← 캐러멜 상자 ← 차키. 차키(aside_1) → 상자(aside_1 막힘 →
    aside_2) → 렌치 전달 → 거꾸로 상자 원래 자리 → 차키 원래 자리는 상자와 붙어 막힘 → 차키를 꺼낸 그 고정 자리
    (aside_1)에 다시 둠, 빈손이라 계속(B·C 합의 #168) → 닫기 → 홈."""
    runner, robot, result = run("occluded_top", "toy_wrench")
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.picked() == ["car_key", "caramel_box", "toy_wrench", "caramel_box", "car_key"]
    assert robot.placed() == ["aside_1", "aside_1", "aside_2", "handover_zone", "origin", "origin", "aside_1"]
    scene = robot.skills.scene
    assert scene.delivered == ["toy_wrench"] and scene.held is None
    assert scene.objects["caramel_box"]["xy"][1] == 0.14                      # 상자는 원래 자리로
    assert scene.objects["car_key"]["xy"][1] == 0.045                         # 차키는 꺼낸 고정 자리(aside_1)
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})
    assert "서랍을 닫았어요" in robot.spoken
    state = runner.state
    assert state["located_in"]["toy_wrench"] == "handover_zone" and state["open"]["drawer_top"] is False
    assert result.blackboard["restore_stack"] == [] and result.blackboard["holding"] is False


def test_restore_uses_original_pose_not_where_it_was_placed():
    """되돌리기 목적지는 치우기 전 관측 자리(origin) — 놓은 자리·다시 본 자리로 덮어쓰지 않음 (E #120 14:08 2번)."""
    _, robot, _ = run("occluded_top", "toy_wrench")
    restore = [p["pose"]["position"][:2] for a, p in robot.calls if a == "place_object" and "pose" in p]
    assert restore == [[0.12, 0.14], [0.12, 0.17]]


def test_plate_over_eraser_moves_only_the_plate():
    """A #109 아래 칸 시나리오: 판이 지우개·립밤을 반쯤 덮음 → 판만 치우고 립밤은 건드리지 않음."""
    _, robot, result = run("plate_over_eraser", "eraser")
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.picked() == ["cover_plate", "eraser", "cover_plate"]
    assert robot.placed() == ["aside_1", "handover_zone", "origin"]


def test_clear_target_needs_no_unpacking():
    """맨 위 물체(차키)를 찾으면 치울 것 없이 바로 전달, 복구할 것도 없음."""
    _, robot, result = run("occluded_top", "car_key")
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.picked() == ["car_key"] and robot.placed() == ["handover_zone"]


def test_estop_while_holding_obstacle_sends_nothing_more():
    """장애물을 쥐고 놓다가 비상정지 → ABORTED: 복구 반복·닫기·홈 없음 (restore_stack·holding 은 사람 확인용)."""
    _, robot, result = run("occluded_top", "toy_wrench", {"place_object": ["ESTOP", 1]})
    assert (result.overall_status, result.error_code) == ("ABORTED", "ESTOP")
    last = max(i for i, (a, _) in enumerate(robot.calls) if a == "place_object")
    assert [a for a, _ in robot.calls[last + 1:]] == []                       # 그 뒤 로봇 동작 없음
    assert result.blackboard["holding"] is True


def test_place_failure_after_motion_keeps_holding_and_skips_home():
    """장애물 놓기가 움직인 뒤 실패(NOT_REACHED) → 다른 자리 안 감 → 쥔 채로 실패: 복구·홈 안 함, 닫기는 B 가 거부."""
    _, robot, result = run("occluded_top", "toy_wrench", {"place_object": ["NOT_REACHED", 1]})
    assert (result.overall_status, result.error_code) == ("FAILED", "NOT_REACHED")
    assert result.blackboard["holding"] is True
    assert ("move_to_named_pose", {"pose_name": "home"}) not in robot.calls
    assert robot.picked() == ["car_key"]                                     # 되돌리기 집기도 없음


@pytest.mark.parametrize("code", ["OBJECT_DROPPED", "SENSOR_INVALID"])
def test_drop_while_moving_obstacle_halts_and_locks(code):
    """#78 HALT_MOTION: 장애물을 놓다가 놓침·센서 이상 → 즉시 ABORTED·잠금. 복구 반복·닫기·홈 없음, 다음 요청도 거절.
    안내는 쥠 여부를 단정하지 않음(놓쳤으면 빈손, 센서 이상이면 모름)."""
    runner, robot, result = run("occluded_top", "toy_wrench", {"place_object": [code, 1]})
    assert (result.overall_status, result.error_code, runner.halted) == ("ABORTED", code, True)
    assert [a for a, _ in robot.calls][-1] == "place_object"                  # 그 뒤 로봇 동작 없음
    assert robot.spoken[-1] == "물건을 옮기다 멈췄어요. 사람이 확인해 주세요"
    again = runner.run(TASK, {"target": "toy_wrench"})
    assert again.overall_status == "ABORTED" and [a for a, _ in robot.calls][-1] == "place_object"


def test_every_drawer_place_sends_scan_with_held_object():
    """B #191: 서랍 안 놓기 scan 에 쥔 물체 id 가 없으면 BAD_PARAMS — 치우기·되돌리기 모두 집을 때 쓴 scan 을 넘김."""
    _, robot, result = run("occluded_top", "toy_wrench")
    assert result.overall_status == "COMPLETED", steps(result)
    held = None
    for action, p in robot.calls:
        if action == "pick_object":
            held = p["target"]["id"]
        elif action == "place_object" and p["location"] != "handover_zone":
            scan = p["scan"]
            assert held in {o["id"] for o in [scan.get("target")] + scan["candidates"] if o}, (held, p)


def test_mock_place_rejects_scan_without_held_object():
    """mock 도 B 와 같게: 쥔 물체가 scan 에 없으면 움직이기 전 BAD_PARAMS (쥔 상태 그대로)."""
    scene = MockScene("occluded_top")
    other = scene.inspect("drawer_top", "toy_wrench")
    assert scene.pick({"target": {"id": "car_key#1", "class": "car_key"}})[0]
    without = {**other, "candidates": [c for c in other["candidates"] if c["id"] != "car_key#1"]}
    assert scene.place({"location": "drawer_top", "slot": "aside_1", "scan": without})[:2] == (False, "BAD_PARAMS")
    assert scene.held == "car_key"
    assert scene.place({"location": "drawer_top", "slot": "aside_1", "scan": other})[:2] == (True, "")


def test_three_obstacles_hit_loop_limit_and_still_restore():
    """고정 자리가 2곳이라 치우기는 최대 2개(while max_iter 2). 3개째가 남으면 LOOP_LIMIT 로 실패 →
    목표는 꺼내지 않고, 옮긴 2개를 거꾸로 되돌린 뒤 닫기·홈."""
    robot = SceneRobot("occluded_top")
    robot.skills.scene.objects["lip_balm"] = {"xy": [0.12, 0.195], "yaw": 0.0, "top_z": 0.0728, "height": 0.02,
                                              "area": 0.0014, "on": ["car_key"]}
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(TASK, {"target": "toy_wrench"})
    assert (result.overall_status, result.error_code) == ("FAILED", "LOOP_LIMIT"), steps(result)
    assert robot.picked() == ["lip_balm", "car_key", "car_key", "lip_balm"]   # 치운 2개 → 거꾸로 되돌리기
    assert "toy_wrench" not in robot.skills.scene.delivered
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})


class BlockedRestoreScene(MockScene):
    """전달 뒤(되돌리기 때)는 서랍 안 어디에 놓아도 막힘 — 원래 자리·꺼낸 고정 자리 둘 다 막힌 경우."""

    def place(self, params):
        if self.delivered and params.get("location") != "handover_zone":
            return False, "PLACE_BLOCKED", {"slot": None, "placed_pose": None, "blocked_by": "toy_car#1"}
        return super().place(params)


def test_restore_blocked_twice_stops_holding_without_home():
    """B·C 합의 #168 3행: 원래 자리도, 꺼낸 고정 자리도 막힘 → 쥔 채 정지, 남은 복구 안 함, 안내, 홈 안 감."""
    robot = SceneRobot("occluded_top")
    robot.skills.scene = BlockedRestoreScene("occluded_top")
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(TASK, {"target": "toy_wrench"})
    assert result.overall_status == "COMPLETED", steps(result)                 # 전달은 됨, 복구는 skip
    assert robot.picked() == ["car_key", "caramel_box", "toy_wrench", "caramel_box"]   # 차키는 되돌리기 안 함
    assert robot.placed()[-2:] == ["origin", "aside_2"]                       # 상자: 원래 자리 → 꺼낸 자리, 둘 다 막힘
    assert result.blackboard["holding"] is True
    assert "물건을 옮기다 멈췄어요. 사람이 확인해 주세요" in robot.spoken
    assert ("move_to_named_pose", {"pose_name": "home"}) not in robot.calls
    closes = [p for a, p in robot.calls if a == "drawer_control" and p.get("state") == "close"]
    assert closes == []                                                      # D 체크시트 S-17: 쥔 채면 닫기 요청도 안 함


# ---- AC-ACT-03 복구 오차 기록: 원래 자리로 되돌린 물체만, 닫기 전에 다시 찍어 원래 자리와 지금 자리를 남김 ----

def _checks(result):
    return [s for s in result.steps if s["id"] == "fv.3.1"]


def test_restore_check_records_origin_and_now_only_for_items_back_at_origin():
    """상자는 원래 자리로 → 다시 찍어 기록(mock 놓기 오차 3 mm). 차키는 원래 자리가 막혀 꺼낸 고정 자리로 → 원위치
    복구가 아니라 확인하지 않음. 확인 촬영은 서랍 닫기 전, 판정(합격/불합격)은 하지 않음."""
    runner, robot, result = run("occluded_top", "toy_wrench")
    assert result.overall_status == "COMPLETED", steps(result)
    assert [r["class"] for r in result.blackboard["restored"]] == ["caramel_box"]
    (check,) = _checks(result)
    assert check["params"]["record"]["origin"]["position"][:2] == [0.12, 0.14]
    assert check["output"]["status"] == "found" and check["output"]["distance_m"] == 0.003
    actions = [(a, p.get("pose_name"), p.get("state")) for a, p in robot.calls]
    view = max(i for i, c in enumerate(actions) if c[:2] == ("move_to_named_pose", "drawer_top_view"))
    assert actions[view + 1][0] == "inspect_region" and actions[view + 2] == ("drawer_control", None, "close")
    record = runner.log_store.read_run(result.run_id)
    from ready2go_runner.core import run_report
    assert "복구 오차 (판정 아님): caramel_box 위치 오차 3.0 mm · 방향 오차 0.0°" in run_report.to_text(record)


def test_plate_restored_to_origin_is_checked():
    _, _, result = run("plate_over_eraser", "eraser")
    assert [(c["params"]["record"]["class"], c["output"]["status"]) for c in _checks(result)] == [("cover_plate", "found")]


def test_no_restore_no_extra_view_or_photo():
    """치운 것이 없으면(목표가 맨 위) 확인 촬영도 없음 — find_item 과 같은 끝."""
    _, robot, result = run("occluded_top", "car_key")
    assert result.overall_status == "COMPLETED" and _checks(result) == []
    delivered = max(i for i, (a, p) in enumerate(robot.calls) if a == "place_object")
    assert [a for a, _ in robot.calls[delivered + 1:]] == ["drawer_control", "move_to_named_pose"]   # 닫기 → 홈


def test_no_restore_check_while_holding_or_after_estop():
    """쥔 채 멈춤(되돌리기 두 번 막힘)·비상정지 뒤에는 확인하러 움직이지 않음."""
    robot = SceneRobot("occluded_top")
    robot.skills.scene = BlockedRestoreScene("occluded_top")
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(TASK, {"target": "toy_wrench"})
    assert result.blackboard["holding"] is True and _checks(result) == []
    last_place = max(i for i, (a, _) in enumerate(robot.calls) if a == "place_object")
    assert robot.calls[last_place + 1:] == []
    _, _, aborted = run("occluded_top", "toy_wrench", {"place_object": ["ESTOP", 1]})
    assert aborted.overall_status == "ABORTED" and _checks(aborted) == []
