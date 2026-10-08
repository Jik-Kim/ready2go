"""tasks/find_with_unpack.json (P2 Unpacking) 을 겹친 장면 mock(core/mock_scene.py)으로 끝까지 실행.
치우기 순서·고정 자리(막히면 다른 자리)·전달·역순 재식별 복구·닫기·홈, 그리고 실패·중단 경로를 확인한다.
mock 이 B·A 실물 동작(얹힌 물체 집기·지지면)과 다를 수 있으므로 흐름 시험이다 (FR-ACT-04 실물 검증 아님)."""
import json
from pathlib import Path

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
    assert "옮기던 물건을 쥔 채 멈췄어요. 사람이 확인해 주세요" in robot.spoken
    assert ("move_to_named_pose", {"pose_name": "home"}) not in robot.calls
