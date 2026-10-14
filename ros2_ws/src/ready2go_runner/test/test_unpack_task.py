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
    assert robot.checked() == ["free", "free", "origin", "origin", "free"]   # aside 헛판단 없음
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
    assert restore == [([0.12, 0.14], True), ([0.12, 0.14], False), ([0.12, 0.17], True)]   # 차키는 판단에서 막힘


def test_plate_over_eraser_moves_only_the_plate():
    """A #109 아래 칸 시나리오: 판이 지우개·립밤을 반쯤 덮음 → 판만 치우고 립밤은 건드리지 않음."""
    _, robot, result = run("plate_over_eraser", "eraser")
    assert result.overall_status == "COMPLETED", steps(result)
    assert robot.picked() == ["cover_plate", "eraser", "cover_plate"]
    assert robot.placed() == ["free", "handover_zone", "origin"]
    assert robot.checked() == ["free", "origin"]


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
    목표는 꺼내지 않고, 옮긴 2개를 거꾸로 되돌린 뒤 닫기·홈."""
    robot = SceneRobot("occluded_top")
    robot.skills.scene.objects["lip_balm"] = {"xy": [0.12, 0.195], "yaw": 0.0, "top_z": 0.0728, "height": 0.02,
                                              "area": 0.0014, "on": ["car_key"]}
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])
    result = runner.run(TASK, {"target": "toy_wrench"})
    assert (result.overall_status, result.error_code) == ("FAILED", "LOOP_LIMIT"), steps(result)
    assert robot.picked() == ["lip_balm", "car_key", "lip_balm"]   # 치운 2개 → 거꾸로: 차키 원래 자리는 상자와 붙어
    assert [c["class"] for c in result.blackboard["left_aside"]] == ["car_key"]   # 판단에서 막힘 → 안 집고 그대로
    assert [c["class"] for c in result.blackboard["restored"]] == ["lip_balm"]
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
def test_one_restore_fails_others_still_restored_then_failed(scene_cls):
    """상자 되돌리기 실패(집기 거부 / 다시 못 찾음) → 차키는 계속 원래 자리로, 닫기·홈 → 안내 → RESTORE_INCOMPLETE."""
    runner, robot, result = _run_with(scene_cls("occluded_top"))
    assert (result.overall_status, result.error_code, result.failed_step) == ("FAILED", "RESTORE_INCOMPLETE", "fr"), \
        steps(result)
    assert robot.skills.scene.delivered == ["toy_wrench"]                     # 전달은 됨
    assert robot.picked()[3:] == ["car_key"]                                  # 상자는 판단에서 거부 → 집지 않음 (#242)
    assert robot.skills.scene.objects["car_key"]["xy"][1] == 0.17              # 차키는 원래 자리로 (남은 복구 계속)
    assert [r["class"] for r in result.blackboard["restore_failed"]] == ["caramel_box"]
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
    """놓을 데가 전혀 없으면 집지 않고 끝 — 쥔 채 멈추지 않고 '꺼내지 못했어요' → 닫기 → 홈."""
    _, robot, result = _run_with(NoRoomScene("plate_over_eraser"), "eraser")
    assert robot.picked() == [] and robot.placed() == []
    assert robot.checked() == ["free"]                                          # 빈 자리 판단 하나 (aside 안 씀)
    assert result.blackboard["sel"]["reason"] == "no_room" and result.blackboard["holding"] is False
    assert "지우개를 꺼내지 못했어요" in robot.spoken
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
    judged = [(s["params"].get("slot") or "origin", s.get("error_code")) for s in result.steps
              if s["id"] in ("fr.5.0a", "fr.5.0b") and s["status"] == "FAILURE"]
    assert judged == [("origin", "NEIGHBOR_TOO_CLOSE"), ("free", "NEIGHBOR_TOO_CLOSE")]
    assert [c["class"] for c in result.blackboard["left_aside"]] == []
    assert [c["class"] for c in result.blackboard["restore_failed"]] == ["caramel_box"]
