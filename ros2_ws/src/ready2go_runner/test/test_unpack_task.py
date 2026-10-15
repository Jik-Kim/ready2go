"""tasks/find_with_unpack.json (P2 Unpacking) 을 겹친 장면 mock(core/mock_scene.py)으로 끝까지 실행.
치우기 순서·고정 자리(막히면 다른 자리)·전달·역순 재식별 복구·닫기·홈, 그리고 실패·중단 경로를 확인한다.
mock 이 B·A 실물 동작(얹힌 물체 집기·지지면)과 다를 수 있으므로 흐름 시험이다 (FR-ACT-04 실물 검증 아님)."""
import json
from pathlib import Path

import pytest

from ready2go_runner.core import run_report
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
        """실제 놓기만 (check_only 판단은 빼고 — 움직이지 않음, #242)."""
        return [_where(p) for a, p in self.calls if a == "place_object" and not p.get("check_only")]

    def checked(self):
        """놓기 판단만(check_only, B #241) 보낸 자리."""
        return [_where(p) for a, p in self.calls if a == "place_object" and p.get("check_only")]


def _where(p):
    return p.get("slot") or ("origin" if "pose" in p else p["location"])


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
    """A #109 위 칸 시나리오(사용자 결정 10/08): 렌치 ← 캐러멜 상자 ← 차키. 집기 전에 놓을 자리부터 판단(#242).
    놓을 자리는 서랍 안 빈 자리(free)만 (B 10/13 #265 — aside 고정 자리 안 씀, PC2 10/14 S1 aside 헛판단):
    차키(free) → 상자(free) → 렌치 전달 → 거꾸로 상자 원래 자리 → 차키 원래 자리는 상자와 붙어 판단에서 거부, 꺼낸 자리(free)
    판단은 통과 → 차키는 집지 않고 그대로 둠(집었다 같은 자리에 다시 놓는 헛동작 없음, PC2 10/12 32초) → 닫기 → 홈."""
    runner, robot, result = run("occluded_top", "toy_wrench")
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.picked() == ["car_key", "caramel_box", "toy_wrench", "caramel_box"]
    assert robot.placed() == ["free", "free", "handover_zone", "origin"]
    assert robot.checked() == ["free", "free", "origin", "origin", "origin", "origin"]   # 3번째 = 목표 집기 전 판단(s8.q1), 마지막 = 차키 지금 자리 판단(fr.5.0b)   # aside 헛판단 없음
    pick_view = [s for s in result.steps if s.get("parent") == "s8.t1" and s["action"] == "move_to_named_pose"]
    assert [bool(s.get("same_pose")) for s in pick_view] == [True]             # 방금 s7.6~7 탑뷰라 보내지 않음 (#245), 바로 집기라 두 번째 탑뷰 없음 (E 10/13 pick)
    scene = robot.skills.scene
    assert scene.delivered == ["toy_wrench"] and scene.held is None
    assert scene.objects["caramel_box"]["xy"][1] == 0.14                      # 상자는 원래 자리로
    assert scene.objects["car_key"]["xy"] == [0.033, 0.03]                    # 차키는 꺼낸 빈 자리(free) 그대로
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})
    assert "서랍을 닫았어요" in robot.spoken
    state = runner.state
    assert state["located_in"]["toy_wrench"] == "handover_zone" and state["open"]["drawer_top"] is False
    assert result.blackboard["restore_stack"] == [] and result.blackboard["holding"] is False


def test_restore_uses_original_pose_not_where_it_was_placed():
    """되돌리기 목적지는 치우기 전 관측 자리(origin) — 놓은 자리·다시 본 자리로 덮어쓰지 않음 (E #120 14:08 2번)."""
    _, robot, _ = run("occluded_top", "toy_wrench")
    restore = [(p["pose"]["position"][:2], bool(p.get("check_only"))) for a, p in robot.calls
               if a == "place_object" and "pose" in p]
    assert restore == [([0.12, 0.13], True),                       # 목표(렌치) 집기 전 판단 — 지금 자리 그대로 (s8.q1, 공간 만들기 필요?)
                       ([0.12, 0.14], True), ([0.12, 0.14], False), ([0.12, 0.17], True),   # 차키 원래 자리는 판단에서 막힘
                       ([0.033, 0.03], True)]                     # → 차키 지금 자리(다시 찍은 위치) 판단 (fr.5.0b)


def test_plate_over_eraser_moves_only_the_plate():
    """A #109 아래 칸 시나리오: 판이 지우개·립밤을 반쯤 덮음 → 판만 치우고 립밤은 건드리지 않음."""
    _, robot, result = run("plate_over_eraser", "eraser")
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.picked() == ["cover_plate", "eraser", "cover_plate"]
    assert robot.placed() == ["free", "handover_zone", "origin"]
    assert robot.checked() == ["free", "origin", "origin"]                      # 목표 집기 전 판단(s8.q1) + 판 원래 자리


def test_clear_target_needs_no_unpacking():
    """맨 위 물체(차키)를 찾으면 치울 것 없이 바로 전달, 복구할 것도 없음."""
    _, robot, result = run("occluded_top", "car_key")
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.picked() == ["car_key"] and robot.placed() == ["handover_zone"]


def test_estop_while_holding_obstacle_sends_nothing_more():
    """장애물을 쥐고 놓다가 비상정지 → ABORTED: 복구 반복·닫기·홈 없음 (restore_stack·holding 은 사람 확인용)."""
    _, robot, result = run("occluded_top", "toy_wrench", {"place_object": ["ESTOP", 1]})
    assert (result.overall_status, result.error_code) == ("ABORTED", "ESTOP")
    assert result.failed_step == "s7.3r"                                      # 실패 지정은 실제 놓기에 (판단은 안 셈)
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
    """B #191: 서랍 안 놓기 scan 에 쥔 물체 id 가 없으면 BAD_PARAMS — 치우기·되돌리기 모두 집을 때 쓴 scan 을 넘김.
    집기 전 판단(check_only)은 집을 물체(object)가 그 scan 에 있어야 함(B #241). 치울 물체 집기도 scan 을 같이 넘김."""
    _, robot, result = run("occluded_top", "toy_wrench")
    assert result.overall_status == "COMPLETED", steps(result)
    held = None
    for action, p in robot.calls:
        if action == "pick_object":
            held = p["target"]["id"]
        elif action == "place_object" and p["location"] != "handover_zone":
            scan, who = p["scan"], p["object"]["id"] if p.get("check_only") else held
            assert who in {o["id"] for o in [scan.get("target")] + scan["candidates"] if o}, (who, p)
    obstacle_picks = [s["params"] for s in result.steps if s["id"] in ("s7.1", "fr.5.1")]   # 치우기·되돌리기 집기
    assert len(obstacle_picks) == 3                                            # 집기 전 이웃 확인용 scan (#242 5·B 댓글)
    assert all(p["target"]["id"] in {o["id"] for o in p["scan"]["candidates"]} for p in obstacle_picks)


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
    목표는 꺼내지 않고, 옮긴 2개를 거꾸로 되돌린 뒤 닫기·홈. 차키가 원래 자리로 못 가서(꺼낸 자리에 그대로) 치우기 전
    차키 위였던 립밤도 원래 자리 복구 보류(받침 없이 놓지 않음 — E 10/14 occluded_by 안)."""
    robot = SceneRobot("occluded_top")
    robot.skills.scene.objects["lip_balm"] = {"xy": [0.12, 0.195], "yaw": 0.0, "top_z": 0.0728, "height": 0.02,
                                              "area": 0.0014, "on": ["car_key"]}
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(TASK, {"target": "toy_wrench"})
    assert (result.overall_status, result.error_code) == ("FAILED", "LOOP_LIMIT"), steps(result)
    assert robot.picked() == ["lip_balm", "car_key"]   # 치운 2개 → 거꾸로: 차키 원래 자리는 상자와 붙어 판단에서 막힘
    assert [c["class"] for c in result.blackboard["left_aside"]] == ["car_key", "lip_balm"]   # → 안 집고 그대로, 립밤 보류
    assert result.blackboard["restored"] == []
    assert "toy_wrench" not in robot.skills.scene.delivered
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})


class BlockedRestoreScene(MockScene):
    """전달 뒤(되돌리기 때)는 판단(check_only)은 통과하는데 실제로 놓으려 하면 서랍 안 어디든 막힘 — 판단과 놓기 사이에
    자리가 막힌 경우(물체가 굴러옴 등). 원래 자리·꺼낸 고정 자리 둘 다 막힘."""

    def place(self, params):
        if self.delivered and params.get("location") != "handover_zone" and not params.get("check_only"):
            return False, "PLACE_BLOCKED", {"slot": None, "placed_pose": None, "blocked_by": "toy_car#1"}
        return super().place(params)


def test_restore_blocked_twice_stops_holding_without_home():
    """B·C 합의 #168 3행: 원래 자리도, 꺼낸 고정 자리도 막힘 → 쥔 채 정지, 남은 복구 안 함, 안내, 홈 안 감."""
    robot = SceneRobot("occluded_top")
    robot.skills.scene = BlockedRestoreScene("occluded_top")
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(TASK, {"target": "toy_wrench"})
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "RESTORE_INCOMPLETE", "fr"), \
        steps(result)                                                        # 전달은 됐지만 복구 미완료 = 실패 (정본 137)
    assert robot.picked() == ["car_key", "caramel_box", "toy_wrench", "caramel_box"]   # 차키는 되돌리기 안 함
    assert robot.placed()[-2:] == ["origin", "free"]                          # 상자: 원래 자리 → 꺼낸 자리(free), 둘 다 막힘
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
    close = actions.index(("drawer_control", None, "close"))
    assert actions[close - 1][0] == "inspect_region"                          # 확인 촬영(fv.2) 바로 뒤 닫기
    assert next(s for s in result.steps if s["id"] == "fv.1").get("same_pose")   # 이미 탑뷰 (복구 판단만 — 안 움직임)
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


# ---- 가림 모름 다시 찍기 (A #214 권고): occlusion_unknown 이면 같은 자세에서 한 번만 다시 찍고 다시 고름 ----

class BlurryScene(MockScene):
    """정한 회차의 촬영은 분할 마스크가 번져 모든 물체 관계가 null(모름) — 고를 후보가 없어 occlusion_unknown."""

    def __init__(self, name, blurry_calls):
        super().__init__(name)
        self.calls, self.blurry_calls = 0, set(blurry_calls)

    def inspect(self, region, search_target):
        self.calls += 1
        result = super().inspect(region, search_target)
        if self.calls in self.blurry_calls:
            for obj in [result["target"]] + result["candidates"]:
                if obj:
                    obj["occluded_by"] = None
        return result


def run_blurry(blurry_calls):
    robot = SceneRobot("occluded_top")
    robot.skills.scene = BlurryScene("occluded_top", blurry_calls)
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    return robot, runner.run(TASK, {"target": "toy_wrench"})


def test_first_photo_unknown_reshoots_once_and_continues():
    robot, result = run_blurry({1})
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.picked() == ["car_key", "caramel_box", "toy_wrench", "caramel_box"]   # 평소와 같은 순서
    reshoot = [s for s in result.steps if s["id"] == "s6r.1"]
    assert len(reshoot) == 1 and reshoot[0]["status"] == "SUCCESS"
    first_pick = next(i for i, (a, _) in enumerate(robot.calls) if a == "pick_object")
    assert [a for a, _ in robot.calls[:first_pick]].count("inspect_region") == 2   # 촬영 → 다시 찍기 → 집기


def test_unknown_twice_does_not_pick_target_or_loop():
    """두 번째도 모르면 지금처럼 목표를 집지 않음 — 다시 찍기는 한 번뿐, 로봇 동작 없이 안내·닫기·홈."""
    robot, result = run_blurry({1, 2})
    assert robot.picked() == [] and "toy_wrench" not in robot.skills.scene.delivered
    assert [s["id"] for s in result.steps].count("s6r.1") == 1
    assert "장난감 스패너를 꺼내지 못했어요" in robot.spoken
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "OCCLUSION_UNKNOWN", "s8")


def test_unknown_after_moving_one_reshoots_inside_loop():
    """차키를 치운 뒤 다시 찍은 사진(2번째 촬영)이 모름 → 루프 안에서 한 번 더 찍고 상자를 고름."""
    robot, result = run_blurry({2})
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.picked()[:3] == ["car_key", "caramel_box", "toy_wrench"]
    assert [s["id"] for s in result.steps].count("s7.9.1") == 1


def test_clear_photo_needs_no_reshoot():
    _, robot, result = run("occluded_top", "toy_wrench")
    assert not any(s["id"].startswith(("s6r.", "s7.9.")) for s in result.steps)


# ---- 10/12 2차 핵심 점검 "음성 명령으로" Unpacking: 코드 수정 없이 RUNNER_INTENT_TASKS 로 find_item → find_with_unpack ----

def _voice_router(intent_tasks):
    from ready2go_runner.core import intent_router as ir
    tasks = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "tasks").glob("*.json"))]
    overrides = {name: json.loads((ROOT / path.lstrip("/")).read_text(encoding="utf-8"))
                 for name, path in ir.parse_overrides(intent_tasks).items()}      # 컨테이너 /tasks = 저장소 tasks/
    schema = json.loads((ROOT / "contracts/intent.schema.json").read_text(encoding="utf-8"))
    return ir.IntentRouter(schema, ir.tasks_by_intent(tasks, overrides), ONTOLOGY["world"]["items"], 0.6)


VOICE_WRENCH = json.dumps({"intent": "find_item", "targets": ["toy_wrench"], "confidence": 0.93,
                           "source": {"stt_text": "장난감 스패너 찾아줘"}}, ensure_ascii=False)


def test_voice_find_item_starts_unpacking_with_intent_tasks_setting():
    """RUNNER_INTENT_TASKS=find_item=/tasks/find_with_unpack.json → 음성 "스패너 찾아줘" 가 Unpacking 으로 실행되고
    (가려진 렌치: 치우기 → 전달 → 역순 복구), 실행 기록 inputs 에 음성 입력이 남음."""
    decision = _voice_router("find_item=/tasks/find_with_unpack.json").decide(VOICE_WRENCH, running=False, locked=False)
    assert (decision.kind, decision.task["task_id"]) == ("run", "find_with_unpack")
    robot = SceneRobot("occluded_top")
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY, log_store=MemoryLogStore())
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(decision.task, decision.inputs)
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.picked() == ["car_key", "caramel_box", "toy_wrench", "caramel_box"]
    run = runner.log_store.read_run(result.run_id)["run"]
    assert (run["inputs"]["source"], run["inputs"]["stt_text"]) == ("voice", "장난감 스패너 찾아줘")
    assert run["inputs"]["reid_tol_m"] == TASK["inputs"]["reid_tol_m"]        # 태스크 기본값은 그대로


def test_without_setting_voice_find_item_stays_plain_find_item():
    """설정이 없으면 지금처럼 find_item(치우기 없음, P1 시연 trigger.targets = 지우개만) — 점검 때만 켜는 설정.
    스패너는 움직이기 전에 보류(UNSUPPORTED_ITEM), 지우개는 find_item."""
    router = _voice_router("")
    assert router.decide(VOICE_WRENCH, running=False, locked=False).reason == "UNSUPPORTED_ITEM"
    eraser = VOICE_WRENCH.replace("toy_wrench", "eraser")
    assert router.decide(eraser, running=False, locked=False).task["task_id"] == "find_item"


# ---- 원래 자리 대신 빈 자리 안내 (10/12 2차 점검 "실패해도 원래대로" 대비): 놓기는 바닥에만이라 목표 위였던 자리로 못 돌아감 ----

class TargetPickFailsScene(MockScene):
    """치우기까지는 되고 목표 집기만 실패 — 목표가 그대로 있어 위에 있던 장애물의 원래 자리가 막힘."""

    def pick(self, params):
        if ((params.get("target") or {}).get("class")) == "toy_wrench":
            return False, "GRASP_FAILED", None
        return super().pick(params)


def test_success_tells_which_item_went_to_a_spare_slot():
    """성공: 상자는 원래 자리, 차키는 원래 자리가 상자와 붙어 막혀 꺼낸 빈 자리 → 차키만 안내·기록, 닫기 전에."""
    runner, robot, result = run("occluded_top", "toy_wrench")
    assert result.overall_status == "COMPLETED", steps(result)
    assert result.blackboard["left_aside"] == [{"class": "car_key", "slot": "free"}]
    assert robot.spoken[-2:] == ["차키는 원래 자리 대신 옆 빈 자리에 뒀어요", "서랍을 닫았어요"]
    from ready2go_runner.core import run_report
    header = run_report.header(runner.log_store.read_run(result.run_id))
    assert any(line.startswith("  원래 자리 대신 빈 자리: car_key(free) — 원위치 복구 아님") for line in header)  # #239 E


def test_target_pick_failure_restores_to_spare_slots_and_says_so():
    """목표 집기 실패: 장애물 둘 다 원래 자리(목표 위)가 막혀 빈 자리로 → 둘 다 안내, 서랍 닫기·홈은 그대로, 실패로 끝남."""
    robot = SceneRobot("occluded_top")
    robot.skills.scene = TargetPickFailsScene("occluded_top")
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(TASK, {"target": "toy_wrench"})
    assert (result.overall_status, result.error_code) == ("FAILED", "GRASP_FAILED")
    assert [a["class"] for a in result.blackboard["left_aside"]] == ["caramel_box", "car_key"]
    assert robot.spoken[-3:] == ["캐러멜 상자는 원래 자리 대신 옆 빈 자리에 뒀어요",
                                 "차키는 원래 자리 대신 옆 빈 자리에 뒀어요", "서랍을 닫았어요"]
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"}) and result.blackboard["holding"] is False


def test_all_back_at_origin_says_nothing_extra():
    _, robot, result = run("plate_over_eraser", "eraser")
    assert result.blackboard["left_aside"] == [] and not any("빈 자리에 뒀어요" in t for t in robot.spoken)


def test_estop_skips_aside_announcement_block():
    _, robot, result = run("occluded_top", "toy_wrench", {"place_object": ["ESTOP", 1]})
    assert result.overall_status == "ABORTED" and not any("빈 자리에 뒀어요" in t for t in robot.spoken)


# ---- 복구 미완료 = 실패 (정본 requirements 137, C 리뷰 10/12): 남은 물체도 계속 시도, 닫기·홈 뒤 안내 + FAILED ----

NOT_BACK = "옮긴 물건 일부를 원래 자리로 못 돌려놨어요. 사람이 확인해 주세요"


class RestorePickRefusedScene(MockScene):
    """전달 뒤 상자는 집기가 움직이기 전 거부(옆 물체가 손가락 자리에 걸림) — B 처럼 집기 전 놓기 판단도 같은 코드로 거부."""

    def pick_refusal(self, target):
        if self.delivered and target.get("class") == "caramel_box":
            return "NEIGHBOR_TOO_CLOSE"
        return super().pick_refusal(target)


class VanishedAfterDeliveryScene(MockScene):
    """전달 뒤 다시 찍으면 상자가 안 보임(사람이 치움·미검출) — 놓기 검사에는 그대로 있음."""

    def inspect(self, region, search_target):
        out = super().inspect(region, search_target)
        if self.delivered:
            out["candidates"] = [c for c in out["candidates"] if c["class"] != "caramel_box"]
        return out


def _run_with(scene, target="toy_wrench"):
    robot = SceneRobot(scene.name)
    robot.skills.scene = scene
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY, log_store=MemoryLogStore())
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    return runner, robot, runner.run(TASK, {"target": target})


@pytest.mark.parametrize("scene_cls", [RestorePickRefusedScene, VanishedAfterDeliveryScene])
def test_one_restore_fails_holds_item_that_was_on_it_then_failed(scene_cls):
    """상자 되돌리기 실패(집기 거부 / 다시 못 찾음) → 치우기 전 상자 위였던 차키는 원래 자리 복구 보류(꺼낸 자리에 그대로
    + 안내 — 받침 없이 원래 높이에 놓지 않음, E 10/14 occluded_by 안), 닫기·홈 → 안내 → RESTORE_INCOMPLETE."""
    runner, robot, result = _run_with(scene_cls("occluded_top"))
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "RESTORE_INCOMPLETE", "fr"), \
        steps(result)
    assert robot.skills.scene.delivered == ["toy_wrench"]                     # 전달은 됨
    assert robot.picked()[3:] == []                                           # 상자는 판단에서 거부 → 집지 않음 (#242)
    assert robot.skills.scene.objects["car_key"]["xy"] == [0.033, 0.03]       # 차키는 꺼낸 빈 자리(free) 그대로
    assert [r["class"] for r in result.blackboard["restore_failed"]] == ["caramel_box"]
    assert result.blackboard["left_aside"] == [{"class": "car_key", "slot": "free"}]
    assert not [s for s in result.steps if s["id"] == "fr.5.0a" and s["params"]["object"]["class"] == "car_key"]
    assert result.blackboard["holding"] is False
    assert NOT_BACK in robot.spoken
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})   # 닫기·홈은 그대로
    assert any(a == "drawer_control" and p.get("state") == "close" for a, p in robot.calls)
    text = run_report.to_text(runner.log_store.read_run(result.run_id))
    assert "RESTORE_INCOMPLETE" in text and "❌ 실패" in text


def test_all_restored_or_left_aside_is_not_restore_failure():
    """다 되돌렸거나 빈 자리 + 안내(E 판정 대기)는 실패로 보지 않음 — 안내도 없음."""
    _, robot, result = run("occluded_top", "toy_wrench")
    assert result.overall_status == "COMPLETED" and result.blackboard["restore_failed"] == []
    assert NOT_BACK not in robot.spoken


# ---- 계약07 수락 문장 (#249 E 리뷰 P2): find_item → find_with_unpack 설정에서도 첫 안내 1회, 실패면 로봇 동작 0번 ----

class SpeakFailsRobot(SceneRobot):
    """안내(speak)가 TTS 실패로 끝나는 로봇."""

    def call_action(self, name, params_json, timeout_sec):
        if name == SPEAK_ACTION:
            self.spoken.append(json.loads(params_json).get("text", ""))
            return Reply(False, "TTS_FAILED")
        return super().call_action(name, params_json, timeout_sec)


def _run_robot(robot, inputs):
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    return runner.run(TASK, inputs)


def test_accept_text_is_the_single_first_announcement_in_unpacking():
    robot = SceneRobot("plate_over_eraser")
    result = _run_robot(robot, {"target": "eraser", "accept_text": "지우개를 찾아올게요."})
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.spoken[0] == "지우개를 찾아올게요." and "지우개를 찾아 올게요" not in robot.spoken   # 기존 문장과 중복 없음


def test_unpacking_first_announcement_failure_sends_no_robot_motion():
    robot = SpeakFailsRobot("plate_over_eraser")
    result = _run_robot(robot, {"target": "eraser", "accept_text": "지우개를 찾아올게요."})
    assert (result.overall_status, result.failed_step) == ("FAILED", "s2.1")
    assert robot.calls == []                                                 # 서랍 열기·촬영·홈 모두 없음
# ---- #242 놓을 자리 먼저 판단한 뒤 집기 (PC2 10/12 run 7d18c6: aside 두 곳 거부 → 판을 쥔 채 정지) ----

def test_mock_check_only_judges_without_moving_and_free_avoids_target():
    """mock 도 B #241 과 같게: check_only 는 장면을 바꾸지 않고(안 쥐었으면 object 로 판단) 예정 자리는 planned_pose,
    slot "free" 는 다른 물체·목표 둘레를 피한 빈 자리, 빈 데가 없으면 움직이기 전 NO_FREE_SPACE."""
    import copy
    import math
    scene = MockScene("plate_over_eraser")
    scan = scene.inspect("drawer_top", "eraser")
    plate = next(c for c in scan["candidates"] if c["class"] == "cover_plate")
    before = copy.deepcopy(scene.objects)
    check = {"location": "drawer_top", "scan": scan, "object": plate, "check_only": True}
    ok, code, out = scene.place({**check, "slot": "aside_1"})
    assert (ok, code, out["check_only"], out["placed_pose"]) == (True, "", True, None)
    assert out["planned_pose"]["position"][:2] == [0.045, 0.045]
    ok, _, out = scene.place({**check, "slot": "free"})
    assert ok and out["slot"] == "free" and math.dist(out["planned_pose"]["position"][:2], [0.12, 0.12]) >= 0.1
    assert scene.objects == before and scene.held is None                    # 판단만 — 아무것도 안 움직임
    for i in range(30):                                                      # 서랍을 꽉 채움
        scene.objects[f"box{i}"] = {"xy": [0.03 + 0.04 * (i % 5), 0.03 + 0.04 * (i // 5)], "on": []}
    assert scene.place({**check, "slot": "free"})[:2] == (False, "NO_FREE_SPACE")


class AsidesTakenScene(MockScene):
    """aside 두 곳에 다른 물체가 있음 — PC2 10/12 15:11 처럼 고정 자리 둘 다 거부되는 장면(실물 원인은 가려진 지우개
    footprint 과대 추정, B #241 에서 고침). 서랍 안 다른 빈 자리는 있음."""

    def __init__(self, name):
        super().__init__(name)
        self.objects["toy_car"] = {"xy": [0.045, 0.045], "yaw": 0.0, "top_z": 0.03, "height": 0.03, "area": 0.002, "on": []}
        self.objects["masking_tape"] = {"xy": [0.045, 0.25], "yaw": 0.0, "top_z": 0.02, "height": 0.02, "area": 0.002,
                                        "on": []}


def test_free_only_judges_free_spot_then_restores():
    """#242 수락 기준 1 + B 10/13 #265(aside 안 씀): 집기 전에 free 만 판단 → 통과 → 집어서 free 에 놓음 → 전달 → 원래 자리로.
    aside 가 막혀 있어도(AsidesTakenScene) 판단하지 않음 — PC2 10/14 S1 처럼 aside 두 번 헛판단하지 않게."""
    runner, robot, result = _run_with(AsidesTakenScene("plate_over_eraser"), "eraser")
    assert result.overall_status == "COMPLETED", steps(result)
    first_pick = next(i for i, (a, _) in enumerate(robot.calls) if a == "pick_object")
    assert [p["slot"] for a, p in robot.calls[:first_pick] if a == "place_object"] == ["free"]
    assert robot.picked() == ["cover_plate", "eraser", "cover_plate"]
    assert robot.placed() == ["free", "handover_zone", "origin"]               # 판단한 자리에 바로 놓음
    assert result.blackboard["left_aside"] == [] and robot.skills.scene.objects["cover_plate"]["xy"][1] == 0.13
    record = runner.log_store.read_run(result.run_id)
    assert "판단만(움직이지 않음) → 놓을 수 있음: free" in run_report.to_text(record)


class NoRoomScene(MockScene):
    """서랍 안 어디에도 놓을 데가 없음 — 빈 자리 없음 (#242 수락 기준 2, aside 는 태스크가 안 씀)."""

    def place(self, params):
        if params.get("location") == "handover_zone":
            return super().place(params)
        code = "NO_FREE_SPACE" if params.get("slot") == "free" else "PLACE_BLOCKED"
        return False, code, {"slot": None, "placed_pose": None, "check_only": bool(params.get("check_only"))}


def test_no_room_anywhere_does_not_pick_and_never_stops_holding():
    """놓을 데가 전혀 없으면 집지 않고 끝 — 쥔 채 멈추지 않고 '꺼내지 못했어요' → 닫기 → 홈.
    실행 결과는 FAILED · NO_FREE_SPACE (E #196 10/14 — 예전엔 COMPLETED 로 찍혀 목표 미전달을 성공으로 보였음)."""
    _, robot, result = _run_with(NoRoomScene("plate_over_eraser"), "eraser")
    assert robot.picked() == [] and robot.placed() == []
    assert robot.checked() == ["free"]                                          # 빈 자리 판단 하나 (aside 안 씀)
    assert result.blackboard["sel"]["reason"] == "no_room" and result.blackboard["holding"] is False
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "NO_FREE_SPACE", "s7.0c")
    assert "위에 있는 물건을 옮기지 못해서 지우개를 꺼내지 못했어요" in robot.spoken
    assert result.blackboard["run_failure"] is None                              # 태스크가 정한 실패 — 원인 안내는 s8.n1 이 이미 함
    assert any(a == "drawer_control" and p.get("state") == "close" for a, p in robot.calls)
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})
    assert not any(s.get("fallback_stopped") for s in result.steps)             # 판단 거부는 움직이기 전 → 다음 대안


def test_restore_origin_blocked_leaves_item_without_picking():
    """#242 4번: 되돌리기 전에 원래 자리를 판단 — 막히면 집지 않고 꺼낸 자리에 그대로(left_aside + 안내)."""
    _, robot, result = run("occluded_top", "toy_wrench")
    judged = [(s["status"], s.get("error_code")) for s in result.steps if s["id"] == "fr.5.0a"]
    assert judged == [("SUCCESS", None), ("FAILURE", "PLACE_BLOCKED")]       # 상자 통과, 차키 거부
    restore_picks = [s["params"]["target"]["class"] for s in result.steps if s["id"] == "fr.5.1"]
    assert restore_picks == ["caramel_box"]
    assert robot.skills.scene.objects["car_key"]["xy"] == [0.033, 0.03]       # 꺼낸 빈 자리(free)에 놓은 그대로
    assert result.blackboard["left_aside"] == [{"class": "car_key", "slot": "free"}]


def test_restore_judged_unpickable_is_failure_not_left_aside():
    """원래 자리 판단도 꺼낸 자리 판단도 거부(집기부터 거부) → 집지 않고 복구 실패 — '빈 자리에 뒀어요'(A안 통과)로
    세지 않음. 예전 되돌리기 집기 거부와 같은 분류, 쥔 채 멈추지 않음."""
    _, robot, result = _run_with(RestorePickRefusedScene("occluded_top"))
    judged = [(s["id"], s.get("error_code")) for s in result.steps
              if s["id"] in ("fr.5.0a", "fr.5.0b") and s["status"] == "FAILURE"]
    assert judged == [("fr.5.0a", "NEIGHBOR_TOO_CLOSE"), ("fr.5.0b", "NEIGHBOR_TOO_CLOSE")]
    assert [c["class"] for c in result.blackboard["left_aside"]] == ["car_key"]   # 상자 위였던 차키는 보류 (빈 자리 + 안내)
    assert [c["class"] for c in result.blackboard["restore_failed"]] == ["caramel_box"]


# ---- 2번 받침 복구 보류 (E 10/14 occluded_by 안): 치우기 전 촬영의 occluded_by 로 "이 물체가 덮고 있던 물체" class 를
#      복구 기록(under)에 남기고, 그 물체가 원래 자리로 안 돌아왔으면 원래 자리 복구 보류. id 는 같은 촬영 안에서만 비교 ----

def _under(result):
    return {s["params"]["value"]["class"]: s["params"]["value"]["under"] for s in result.steps if s["id"] == "s7.5"}


def _judged_origin(result):
    return [s["params"]["object"]["class"] for s in result.steps if s["id"] == "fr.5.0a"]


def test_records_what_each_obstacle_covered_from_its_own_scan():
    """차키(첫 촬영에서 상자 위) → under [상자], 상자(차키 치운 뒤 촬영, 목표 렌치만 덮음 — 목표는 복구 대상 아님) → [].
    그 촬영에 보인 물체(목표 빼고)는 seen 에 — 안 보인 물체와의 관계는 모름으로 보기 위함 (E #339 P1)."""
    _, _, result = run("occluded_top", "toy_wrench")
    assert _under(result) == {"car_key": ["caramel_box"], "caramel_box": []}
    seen = {s["params"]["value"]["class"]: s["params"]["value"]["seen"] for s in result.steps if s["id"] == "s7.5"}
    assert seen == {"car_key": ["car_key", "caramel_box"], "caramel_box": ["caramel_box", "car_key"]}


def test_support_restored_then_upper_item_restored_normally():
    """상자가 원래 자리로 돌아오면 차키는 보류 없이 평소대로 원래 자리부터 판단."""
    _, _, result = run("occluded_top", "toy_wrench")
    assert result.overall_status == "COMPLETED"
    assert _judged_origin(result) == ["caramel_box", "car_key"]
    assert [s["status"] for s in result.steps if s["id"] == "fr.hh1"] == []


class SideBySideScene(MockScene):
    """상자와 차키가 서로 겹치지 않고 각각 렌치 한쪽 끝만 덮음. 나중에 치운 차키가 먼저 복구되는데 집기 거부 →
    상자는 차키와 관계없으므로 보류 없이 계속."""

    def __init__(self):
        super().__init__("occluded_top")
        self.objects["caramel_box"].update(xy=[0.12, 0.09], yaw=0.0)
        self.objects["car_key"].update(xy=[0.12, 0.17], top_z=0.0343, on=["toy_wrench"])

    def pick_refusal(self, target):
        if self.delivered and target.get("class") == "car_key":
            return "NEIGHBOR_TOO_CLOSE"
        return super().pick_refusal(target)


def test_unrelated_item_keeps_restoring_after_another_fails():
    """관계없는 물체는 앞 복구가 실패해도 평소대로 원래 자리부터 판단 (보수안처럼 남은 물체를 다 멈추지 않음)."""
    _, _, result = _run_with(SideBySideScene())
    assert _under(result) == {"car_key": [], "caramel_box": []}               # 서로 덮지 않음 (목표만 덮음)
    assert _judged_origin(result) == ["car_key", "caramel_box"]               # 차키 실패 뒤에도 상자 원래 자리 판단
    assert [r["class"] for r in result.blackboard["restore_failed"]] == ["car_key"]
    assert [r["class"] for r in result.blackboard["restored"]] == ["caramel_box"]
    assert [s for s in result.steps if s["id"] == "fr.hh1"] == []


class UnknownRelationScene(RestorePickRefusedScene):
    """분할 모델이 위에 뭐가 있는 물체의 관계를 모름(occluded_by null) — 맨 위만 []. 모름을 []로 바꾸지 않음."""

    def inspect(self, region, search_target):
        out = super().inspect(region, search_target)
        for o in [out["target"]] + out["candidates"]:
            if o and o["occluded_by"]:
                o["occluded_by"] = None
        return out


class UnknownRelationOkScene(UnknownRelationScene):
    def pick_refusal(self, target):
        return MockScene.pick_refusal(self, target)


class BoxModelScene(RestorePickRefusedScene):
    """박스 모델: 결과 전체에 가림 필드 없음 → 관계 모름."""

    def inspect(self, region, search_target):
        out = super().inspect(region, search_target)
        for o in [out["target"]] + out["candidates"]:
            if o:
                o.pop("occluded_by")
        return out


@pytest.mark.parametrize("scene_cls", [UnknownRelationScene, BoxModelScene])
def test_unknown_relation_holds_conservatively_when_support_fails(scene_cls):
    """관계 모름(null·필드 없음)인 물체는 '덮였을 수 있음'으로 under 에 넣음 → 그 물체가 복구 실패면 위 물체 보류."""
    _, robot, result = _run_with(scene_cls("occluded_top"))
    assert "caramel_box" in _under(result)["car_key"]
    assert [r["class"] for r in result.blackboard["restore_failed"]] == ["caramel_box"]
    assert "car_key" not in _judged_origin(result)
    assert [c["class"] for c in result.blackboard["left_aside"]] == ["car_key"]


def test_unknown_relation_but_support_restored_is_normal():
    _, _, result = _run_with(UnknownRelationOkScene("occluded_top"))
    assert result.blackboard["restore_failed"] == []
    assert _judged_origin(result) == ["caramel_box", "car_key"]


class FirstScanMissesCaramelScene(RestorePickRefusedScene):
    """첫 촬영(차키가 아직 원래 자리)에서 상자가 아예 검출 안 됨 — 렌치는 차키에 덮인 것으로만 보임. 차키를 치운 뒤
    촬영부터 상자가 보임. 전달 뒤 상자 되돌리기는 집기 거부."""

    def inspect(self, region, search_target):
        out = super().inspect(region, search_target)
        if self.objects["car_key"]["xy"] == [0.12, 0.17]:
            out["candidates"] = [c for c in out["candidates"] if c["class"] != "caramel_box"]
            out["target"]["occluded_by"] = ["car_key#1"]
            out["visible_count"] -= 1
        return out


def test_support_unseen_in_first_scan_still_holds_upper_item():
    """[E #339 P1] 차키를 고른 촬영에 상자가 없었으면 under 에 상자가 안 남음 → '관계 없음'이 아니라 모름(seen 에 없음)으로
    보고, 상자 복구가 실패하면 차키도 보류 — 차키 집기·원래 자리 놓기 0회."""
    _, robot, result = _run_with(FirstScanMissesCaramelScene("occluded_top"))
    assert _under(result) == {"car_key": [], "caramel_box": []}
    assert [r["class"] for r in result.blackboard["restore_failed"]] == ["caramel_box"]
    deliver = next(i for i, (a, p) in enumerate(robot.calls) if a == "place_object" and p.get("location") == "handover_zone")
    after = robot.calls[deliver + 1:]
    assert [p for a, p in after if a == "pick_object"] == []                          # 되돌리기 집기 0회
    assert [p for a, p in after if a == "place_object" and not p.get("check_only")] == []   # 실제 놓기 0회
    assert "car_key" not in _judged_origin(result)
    assert [c["class"] for c in result.blackboard["left_aside"]] == ["car_key"]


def test_missing_under_record_holds_conservatively():
    """기록에 under 를 못 남겼으면(찍은 결과 모양 이상 등) '*' — 앞 복구가 하나라도 원래 자리에 못 갔으면 보류."""
    task = json.loads(json.dumps(TASK))

    def strip(steps):
        for s in steps:
            if s.get("id") == "s7.u1":
                s["in"] = "$scan.no_such_list"
            for k in ("then", "else", "body"):
                strip(s.get(k, []))
            for o in s.get("options", []):
                strip(o)
    strip(task["sequence"])
    robot = SceneRobot("occluded_top")
    robot.skills.scene = RestorePickRefusedScene("occluded_top")
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY, log_store=MemoryLogStore())
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(task, {"target": "toy_wrench"})
    assert _under(result) == {"car_key": ["*"], "caramel_box": ["*"]}
    assert [c["class"] for c in result.blackboard["left_aside"]] == ["car_key"]


class NoOtherFreeSpotScene(MockScene):
    """전달 뒤에는 서랍 안에 '다른' 빈 자리가 없음(slot free → NO_FREE_SPACE) — B #337 뒤 다시 집을 자리만 고르면 생길 수 있음."""

    def place(self, params):
        if self.delivered and params.get("slot") == "free":
            return False, "NO_FREE_SPACE", {"slot": None, "placed_pose": None, "check_only": bool(params.get("check_only"))}
        return super().place(params)


def test_restore_keeps_item_where_it_is_without_searching_other_free_spot():
    """[C #260 2번, B 답 10/14] 원래 자리가 막히면 fr.5.0b 는 '지금 자리에 그대로 둬도 되나'(pose = 다시 찍은 위치 + object
    → 집을 수 있고 그 자리에 둘 수 있음)를 봄 — 다른 빈 자리를 찾지 않으므로 빈 자리가 없어도 복구 실패가 아니라 left_aside."""
    _, robot, result = _run_with(NoOtherFreeSpotScene("occluded_top"))
    b = [s for s in result.steps if s["id"] == "fr.5.0b"]
    assert [(s["status"], "pose" in s["params"], "slot" in s["params"]) for s in b] == [("SUCCESS", True, False)]
    assert b[0]["params"]["pose"]["position"][:2] == [0.033, 0.03]           # 차키를 다시 찍은 지금 자리
    assert result.overall_status == "COMPLETED" and result.blackboard["restore_failed"] == []
    assert result.blackboard["left_aside"] == [{"class": "car_key", "slot": "free"}]
    assert robot.skills.scene.objects["car_key"]["xy"] == [0.033, 0.03]      # 집지 않고 그대로


# ---- 실패 원인 안내 (E #196 10/14): 일반 실패면 정리(복구·닫기·홈) 전에 원인 한 문장, 정지·성공이면 안 함 ----

def _order(result, *ids):
    seq = [s["id"] for s in result.steps]
    return [seq.index(i) for i in ids]


def test_camera_timeout_cause_spoken_before_close():
    _, robot, result = run("occluded_top", "toy_wrench", {"inspect_region": ["CAMERA_TIMEOUT", 2]})
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "CAMERA_TIMEOUT", "s4")
    assert result.blackboard["run_failure"] == {"code": "CAMERA_TIMEOUT", "step": "s4", "action": "inspect_region",
                                                "text": "카메라 영상이 제때 오지 않아서 멈췄어요"}
    fx, close = _order(result, "fx.1", "f2")
    assert fx < close                                                             # 닫기 전에
    assert robot.spoken.index("카메라 영상이 제때 오지 않아서 멈췄어요") < robot.spoken.index("서랍을 닫았어요")


def test_place_failure_while_holding_says_cause_and_still_skips_home():
    _, robot, result = run("occluded_top", "toy_wrench", {"place_object": ["NOT_REACHED", 1]})
    assert (result.overall_status, result.error_code) == ("FAILED", "NOT_REACHED")
    assert result.blackboard["run_failure"]["text"] == "물건 놓기에 실패해서 멈췄어요"
    assert "물건 놓기에 실패해서 멈췄어요" in robot.spoken
    assert ("move_to_named_pose", {"pose_name": "home"}) not in robot.calls     # 쥔 채 정리 조건은 그대로


class CauseSpeakFails(SceneRobot):
    def call_action(self, name, params_json, timeout_sec):
        text = json.loads(params_json).get("text", "") if name == SPEAK_ACTION else ""
        if "멈췄어요" in text:
            self.spoken.append(text)
            return Reply(False, "TTS_FAILED")
        return super().call_action(name, params_json, timeout_sec)


def test_cause_speak_failure_keeps_original_error_and_cleanup():
    robot = CauseSpeakFails("occluded_top", {"inspect_region": ["CAMERA_TIMEOUT", 2]})
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY, log_store=MemoryLogStore())
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(TASK, {"target": "toy_wrench"})
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "CAMERA_TIMEOUT", "s4")
    assert [s["status"] for s in result.steps if s["id"] == "fx.1"] == ["FAILURE"]
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})      # 닫기·홈 그대로


def test_estop_and_success_do_not_speak_cause():
    _, robot, result = run("occluded_top", "toy_wrench", {"place_object": ["ESTOP", 1]})
    assert result.overall_status == "ABORTED" and result.blackboard["run_failure"] is None
    assert not [s for s in result.steps if s["id"] == "fx.1"]
    _, robot, result = run("occluded_top", "toy_wrench")
    assert result.overall_status == "COMPLETED" and result.blackboard["run_failure"] is None
    assert not [s for s in result.steps if s["id"] == "fx.1"]


# ---- 복구 원복 넛지 (B 요청 10/14): 지금 자리 판단이 WALL_TOO_CLOSE 면 끌기 → 다시 찍기·찾기 → 다시 판단 (최대 2번) ----

class WallAfterDeliveryScene(MockScene):
    """전달 뒤 상자가 벽에 붙어 집기가 WALL_TOO_CLOSE (놓기만 되는 자리에 둔 경우, #345). 끌 때마다 y 로 step_m 옮김 —
    pushes_needed 번 끌어야 집힘. nudge_code 면 끌기 실패(움직이기 전)."""

    def __init__(self, pushes_needed=1, step_m=0.012, nudge_code=None):
        super().__init__("occluded_top")
        self.pushes_needed, self.step_m, self.nudge_code, self.pushes = pushes_needed, step_m, nudge_code, 0

    def pick_refusal(self, target):
        if self.delivered and target.get("class") == "caramel_box" and self.pushes < self.pushes_needed:
            return "WALL_TOO_CLOSE"
        return super().pick_refusal(target)

    def nudge(self, params):
        if self.nudge_code:
            return False, self.nudge_code, {"pushed": False, "push_vector_m": [0.0, 0.0], "target_after": None}
        target = json.loads(json.dumps(params["target"]))
        cls = target["class"]
        self.objects[cls]["xy"] = [self.objects[cls]["xy"][0], round(self.objects[cls]["xy"][1] + self.step_m, 4)]
        self.pushes += 1
        target["pose"]["position"] = [self.objects[cls]["xy"][0], self.objects[cls]["xy"][1], 0.0]
        return True, "", {"pushed": True, "push_vector_m": [0.0, self.step_m], "target_after": target}


def _nudges(robot):
    return [p["target"]["class"] for a, p in robot.calls if a == "nudge_object"]


def test_restore_nudges_wall_item_then_restores_to_origin():
    _, robot, result = _run_with(WallAfterDeliveryScene())
    assert result.overall_status == "COMPLETED", steps(result)
    assert _nudges(robot) == ["caramel_box"]
    assert [s["status"] for s in result.steps if s["id"] == "fr.5.w6"] == ["SUCCESS"]
    assert robot.picked()[3:] == ["caramel_box"]                                   # 끈 뒤 상자 집어 원래 자리로 (차키는 평소대로 판단)
    assert robot.skills.scene.objects["caramel_box"]["xy"][1] == 0.14
    assert "caramel_box" in [r["class"] for r in result.blackboard["restored"]]


def test_restore_nudge_failure_is_restore_failure_without_pick():
    _, robot, result = _run_with(WallAfterDeliveryScene(nudge_code="NO_PUSH_ACCESS"))
    assert (result.overall_status, result.error_code) == ("FAILED", "RESTORE_INCOMPLETE")
    assert _nudges(robot) == ["caramel_box"]
    assert "caramel_box" not in robot.picked()[3:]
    assert [r["class"] for r in result.blackboard["restore_failed"]] == ["caramel_box"]
    assert [c["class"] for c in result.blackboard["left_aside"]] == ["car_key"]   # 받침 실패 → 위 물체 보류 (#339)
    assert result.blackboard["holding"] is False and robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})


def test_restore_nudges_at_most_twice_and_refinds_after_each_push():
    """끌 때마다 15 mm — 두 번이면 처음 놓은 자리에서 30 mm(reid_tol 20 mm 밖)지만 끈 뒤 예상 위치로 기록을 바꿔 매번 다시 찾음."""
    _, robot, result = _run_with(WallAfterDeliveryScene(pushes_needed=3, step_m=0.015))
    assert _nudges(robot) == ["caramel_box", "caramel_box"]
    assert [(s.get("result") or s.get("output"))["status"] for s in result.steps if s["id"] == "fr.5.w6"] == ["found", "found"]
    assert [r["class"] for r in result.blackboard["restore_failed"]] == ["caramel_box"]
    assert "caramel_box" not in robot.picked()[3:]


def test_other_restore_refusals_do_not_nudge():
    _, robot, result = _run_with(RestorePickRefusedScene("occluded_top"))   # NEIGHBOR_TOO_CLOSE
    assert _nudges(robot) == []
    assert not [s for s in result.steps if s["id"] == "fr.5.w2"]


# ---- 목표 공간 만들기 (B 요청 10/14, #260 7절): 목표 집기 NEIGHBOR_TOO_CLOSE → make_room 한 동작 → 다시 찍기 (최대 4) ----

class NeighborScene(MockScene):
    """맨 위 차키(목표)가 옆 물체에 막혀 집기 NEIGHBOR_TOO_CLOSE. make_room 을 sweeps 번 하면 집힘.
    moves=False 면 목표가 안 움직임(remove_first 를 받으면 움직임 — stuck_after_remove 면 그래도 안 움직임)."""

    def __init__(self, sweeps=1, moves=True, stuck_after_remove=False, code=None):
        super().__init__("occluded_top")
        self.objects["car_key"].update(on=[])                                     # 셋 다 바닥에 따로 (16:19 처럼)
        self.objects["caramel_box"].update(xy=[0.12, 0.10], on=[])
        self.objects["toy_wrench"].update(xy=[0.05, 0.25])
        self.sweeps, self.moves, self.stuck_after_remove, self.code = sweeps, moves, stuck_after_remove, code
        self.done, self.remove_flags = 0, []

    def pick_refusal(self, target):
        if target.get("class") == "car_key" and self.done < self.sweeps:
            return "NEIGHBOR_TOO_CLOSE"
        return super().pick_refusal(target)

    def nudge(self, params):
        if not params.get("make_room"):
            return super().nudge(params)
        self.remove_flags.append(bool(params.get("remove_first")))
        if self.code:
            return False, self.code, {"pushed": False, "push_vector_m": [0.0, 0.0], "target_after": None}
        move = self.moves or (params.get("remove_first") and not self.stuck_after_remove)
        pushed_after = []
        if move:                                  # 목표를 밀고 캐러멜도 같이 밀림 (B 계약: pushed_ids·pushed_after)
            for cls in ("car_key", "caramel_box"):
                self.objects[cls]["xy"] = [self.objects[cls]["xy"][0], round(self.objects[cls]["xy"][1] - 0.01, 4)]
            self.done += 1
            x, y = self.objects["caramel_box"]["xy"]
            pushed_after = [{"id": "caramel_box#1", "frame": "drawer_top", "position": [x, y, 0.0],
                             "yaw": self.objects["caramel_box"]["yaw"]}]
        return True, "", {"pushed": bool(move), "push_vector_m": [0.0, -0.01 if move else 0.0], "target_after": None,
                          "make_room": {"action": "sweep", "reason": "목표 밀기", "moved_id": "car_key#1" if move else None,
                                        "pushed_ids": ["caramel_box#1"] if move else [], "pushed_after": pushed_after,
                                        "ready_to_pick": self.done >= self.sweeps}}


def _room_records(result):
    return [s["params"]["value"]["class"] for s in result.steps if s["id"] in ("s8.m9c", "s8.m10e")]


def test_target_neighbor_makes_room_once_then_picks():
    """sweep 1번 → 집기. 같이 밀린 캐러멜은 이동 전 자리로 복구 목록에 들어가 정리 때 다시 찾아 되돌림 (E #352 P1 2)."""
    _, robot, result = _run_with(NeighborScene(), "car_key")
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.skills.scene.remove_flags == [False]
    assert robot.picked()[0] == "car_key" and robot.skills.scene.delivered == ["car_key"]
    assert [m["action"] for m in result.blackboard["room_made"]] == ["sweep"]
    assert _room_records(result) == ["caramel_box"]                             # 목표(moved_id = 차키)는 복구 대상 아님
    assert [s["status"] for s in result.steps if s["id"] == "fr.4"] == ["SUCCESS"]   # 밀린 자리에서 다시 찾음
    assert result.blackboard["restore_failed"] == []


def test_target_neighbor_repeats_until_ready_to_pick():
    _, robot, result = _run_with(NeighborScene(sweeps=2), "car_key")
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.skills.scene.remove_flags == [False, False]                    # 목표가 움직였으니 remove_first 안 씀


def test_target_not_moving_switches_to_remove_first():
    _, robot, result = _run_with(NeighborScene(moves=False), "car_key")
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.skills.scene.remove_flags == [False, False, True]              # 같은 sweep·같은 이유 두 번, 목표 그대로 → remove_first


def test_still_stuck_after_remove_first_stops_and_pick_refuses():
    _, robot, result = _run_with(NeighborScene(moves=False, stuck_after_remove=True), "car_key")
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "NEIGHBOR_TOO_CLOSE", "s8.t1.e3.o1.1"), steps(result)
    assert robot.skills.scene.remove_flags == [False, False, True]              # remove_first 뒤에도 그대로 → 네 번째는 안 부름
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})


def test_make_room_at_most_four_times():
    _, robot, result = _run_with(NeighborScene(sweeps=9), "car_key")
    assert (result.overall_status, result.error_code) == ("FAILED", "LOOP_LIMIT")
    assert len(robot.skills.scene.remove_flags) == 4
    assert "car_key" not in robot.picked() and robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})
    assert _room_records(result) == ["caramel_box"] * 4                         # 밀린 캐러멜은 실패해도 복구 목록으로 되돌림 시도


def test_make_room_refusal_fails_with_its_code_and_cleans_up():
    _, robot, result = _run_with(NeighborScene(code="NO_PUSH_ACCESS"), "car_key")
    assert (result.overall_status, result.error_code) == ("FAILED", "NO_PUSH_ACCESS")
    assert any(a == "drawer_control" and p.get("state") == "close" for a, p in robot.calls)
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})


def test_other_target_pick_failures_do_not_make_room():
    _, robot, result = run("occluded_top", "car_key", {"pick_object": ["GRASP_FAILED", 2]})
    assert result.overall_status == "FAILED"
    assert not [p for a, p in robot.calls if a == "nudge_object" and p.get("make_room")]


class RemoveNeighborsScene(MockScene):
    """[E #352 P1 1 재현] 목표(차키)는 그대로인데 make_room 이 막는 이웃을 하나씩 빈 자리로 옮김(remove, 이유가 매번 다름) — 셋 다 옮기면 집힘."""

    def __init__(self):
        super().__init__("occluded_top")
        self.objects["car_key"].update(on=[])
        self.objects["caramel_box"].update(xy=[0.12, 0.10], on=[])
        self.objects["toy_wrench"].update(xy=[0.06, 0.17])
        self.objects["lip_balm"] = {"xy": [0.17, 0.17], "yaw": 0.0, "top_z": 0.02, "height": 0.02, "area": 0.0014, "on": []}
        self.queue = [("caramel_box", [0.04, 0.05]), ("toy_wrench", [0.04, 0.25]), ("lip_balm", [0.17, 0.25])]
        self.remove_flags = []

    def pick_refusal(self, target):
        if target.get("class") == "car_key" and self.queue:
            return "NEIGHBOR_TOO_CLOSE"
        return super().pick_refusal(target)

    def nudge(self, params):
        if not params.get("make_room"):
            return super().nudge(params)
        self.remove_flags.append(bool(params.get("remove_first")))
        cls, xy = self.queue.pop(0)
        self.objects[cls]["xy"] = xy
        after = {"frame": "drawer_top", "position": [xy[0], xy[1], 0.0], "yaw": 0.0}
        return True, "", {"pushed": False, "push_vector_m": [0.0, 0.0], "target_after": None,
                          "make_room": {"action": "remove", "reason": f"막는 {cls}#1 → 빈 자리", "moved_id": f"{cls}#1",
                                        "moved_after": after, "pushed_ids": [], "pushed_after": [],
                                        "ready_to_pick": not self.queue}}


def test_removing_different_neighbors_is_progress_not_stuck():
    """목표가 그대로여도 remove(목표를 안 움직이는 동작)·이유가 매번 다르면 정체가 아님 → remove_first·멈춤 없이 셋 다 치우고 집기.
    옮긴 이웃 셋은 이동 전 자리로 복구 목록에 들어가 역순으로 되돌림 (E #352 P1 1·2)."""
    _, robot, result = _run_with(RemoveNeighborsScene(), "car_key")
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.skills.scene.remove_flags == [False, False, False]
    assert robot.skills.scene.delivered == ["car_key"]
    assert _room_records(result) == ["caramel_box", "toy_wrench", "lip_balm"]
    assert result.blackboard["restore_failed"] == []
    back = {c: robot.skills.scene.objects[c]["xy"] for c in ("caramel_box", "toy_wrench", "lip_balm")}
    assert (back["caramel_box"][1], back["toy_wrench"][1], back["lip_balm"][1]) == (0.10, 0.17, 0.17)   # 원래 자리 (x 는 mock 놓기 오차)


def test_neighbor_moved_by_make_room_that_cannot_be_restored_is_restore_incomplete():
    """옮긴 이웃을 되돌리지 못하면(다시 집기 거부) 전체 결과는 RESTORE_INCOMPLETE — 목표 전달만으로 COMPLETED 아님 (정본 FR-ACT-04)."""
    class Stuck(RemoveNeighborsScene):
        def pick_refusal(self, target):
            if self.delivered and target.get("class") == "lip_balm":
                return "WALL_TOO_CLOSE"
            return super().pick_refusal(target)
    _, robot, result = _run_with(Stuck(), "car_key")
    assert robot.skills.scene.delivered == ["car_key"]
    assert (result.overall_status, result.error_code) == ("FAILED", "RESTORE_INCOMPLETE")
    assert "lip_balm" in [r["class"] for r in result.blackboard["restore_failed"]]



# ---- 목표를 못 꺼내면 FAILED (PC2 10/14 20:11·20:14 — 판 치운 뒤 지우개 가림 모름인데 COMPLETED 로 찍힘) ----

class TargetUnknownAfterMoveScene(MockScene):
    """판을 치운 뒤 찍은 사진(2·3번째)에서 목표만 occluded_by null — A 기준 넓이 문제로 다 보이는 지우개를 '덜 보임'으로 본 경우."""

    def __init__(self):
        super().__init__("plate_over_eraser")
        self.calls = 0

    def inspect(self, region, search_target):
        self.calls += 1
        result = super().inspect(region, search_target)
        if self.calls in (2, 3) and result["target"]:
            result["target"]["occluded_by"] = None
        return result


def test_target_unknown_after_moving_cover_is_failed_occlusion_unknown():
    """판 치우기·다시 찍기까지는 그대로, 목표는 집지 않음 → 판 정리·닫기·홈 → FAILED · OCCLUSION_UNKNOWN (step s8)."""
    _, robot, result = _run_with(TargetUnknownAfterMoveScene(), "eraser")
    assert robot.picked()[0] == "cover_plate" and "eraser" not in robot.picked()   # 판은 치우고, 지우개는 안 집음
    assert robot.skills.scene.delivered == []
    assert [s["id"] for s in result.steps].count("s7.9.1") == 1                 # 다시 찍기는 한 번
    assert result.blackboard["sel"]["reason"] == "occlusion_unknown"
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "OCCLUSION_UNKNOWN", "s8")
    assert [r["class"] for r in result.blackboard["left_aside"]] == ["cover_plate"]   # 판 정리는 그대로 (mock 은 판 원래 자리 위 놓기 불가 → 옆 빈 자리)
    assert "지우개를 꺼내지 못했어요" in robot.spoken
    assert result.blackboard["run_failure"] is None                              # 태스크가 정한 실패 — 원인 안내는 s8.1 이 함
    assert any(a == "drawer_control" and p.get("state") == "close" for a, p in robot.calls)
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})


class TargetNeverSeenScene(MockScene):
    """목표가 한 번도 검출되지 않음 — 다른 물체를 치워 봐도 못 찾음."""

    def inspect(self, region, search_target):
        result = super().inspect(region, search_target)
        if result["target"]:
            result.update(target_found=False, target=None)
        return result


def test_target_never_found_is_failed_target_not_found():
    _, robot, result = _run_with(TargetNeverSeenScene("plate_over_eraser"), "eraser")
    assert robot.skills.scene.delivered == []
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "TARGET_NOT_FOUND", "s8")
    assert "지우개를 꺼내지 못했어요" in robot.spoken
    assert robot.calls[-1] == ("move_to_named_pose", {"pose_name": "home"})
