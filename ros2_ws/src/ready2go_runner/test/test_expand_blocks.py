"""스킬 expand 안 fallback·if 블록과 fallback.next_on (#121·#245 계약, E 대화 승인 10/13, 사용자 전달 — #263).
E 가 공통 pick 을 "탑뷰 → 찍기 → fallback(next_on WALL_TOO_CLOSE)[ 집기 | 넛지 → 탑뷰 → 찍기 → 집기 ]" 로 바꿨을 때
Runner 가 그대로 돌리는지 — 지금 knowledge/skills/pick.jsonld 는 그대로 두고 시험 안에서만 바꾼 온톨로지로 본다."""
import copy

from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.validation import check_task

from test_tasks import ONTOLOGY, SCHEMA, TASK, MockRobot, run, step  # noqa: E402

VIEW = {"action": "move_to_named_pose", "params": {"pose_name": "drawer_top_view", "drawer_id": "$from"}}
LOOK = {"action": "inspect_region", "params": {"region": "$from", "search_target": "$item"}, "output": "scan"}
PICK = {"action": "pick_object", "params": {"target": "$scan.target", "scan": "$scan", "approach_offset": [0, 0, 0.1]}}
NUDGE = {"action": "nudge_object", "params": {"target": "$scan.target", "drawer_id": "$from", "scan": "$scan"},
         "output": "nudge"}
PROPOSED_EXPAND = [VIEW, LOOK, {"action": "fallback", "next_on": ["WALL_TOO_CLOSE"],
                                "options": [[PICK], [NUDGE, VIEW, LOOK, PICK]]}]


def onto_with(expand):
    onto = copy.deepcopy(ONTOLOGY)
    onto["skills"]["pick"]["expand"] = expand
    return onto


ONTO = onto_with(PROPOSED_EXPAND)


def sent_in_pick(robot):
    """s4 촬영 뒤(= pick 스킬 안) 보낸 동작 이름."""
    names = [n.rsplit("/", 1)[-1] for n in robot.sent]
    first_pick_look = names.index("inspect_region", names.index("inspect_region") + 1)
    end = len(names) - names[::-1].index("pick_object") if "pick_object" in names else len(names)
    return names[first_pick_look:end]


def block(result):
    return next(s for s in result.steps if s["id"] == "s5.1.e3")


def test_proposed_pick_passes_validation_with_find_item():
    assert check_task(TASK, SCHEMA, ONTO["skills"]) == []


def test_pick_first_without_nudge_when_grasp_is_possible():
    """넛지가 필요 없으면 촬영 1번 → 바로 집기 (지금 pick 은 넛지 판단 뒤 탑뷰·촬영을 한 번 더 함)."""
    robot = MockRobot()
    _, result, _ = run(robot, onto=ONTO)
    assert result.overall_status == "COMPLETED", result.steps
    assert sent_in_pick(robot) == ["inspect_region", "pick_object"]
    assert (block(result)["status"], block(result)["option"]) == ("SUCCESS", 1)


def test_wall_too_close_goes_nudge_rescan_pick_with_new_scan():
    robot = MockRobot(fail={"pick_object": ["WALL_TOO_CLOSE"]}, seen_y=[0.2895, 0.2895, 0.2478])
    _, result, _ = run(robot, onto=ONTO)
    assert result.overall_status == "COMPLETED", result.steps
    assert sent_in_pick(robot) == ["inspect_region", "pick_object", "nudge_object", "move_to_named_pose",
                                   "inspect_region", "pick_object"]
    first, second = robot.params["pick_object"]
    assert first["target"]["pose"]["position"][1] == 0.2895
    assert second["target"]["pose"]["position"][1] == 0.2478     # 넛지 뒤 새로 찍은 값 (target_after 아님)
    assert second["scan"]["target"] == second["target"]          # 그 새 scan 전체를 같이 넘김
    assert (block(result)["option"], step(result, "s5.1.e3.o2.1")["action"]) == (2, "nudge_object")


def test_other_no_motion_refusal_does_not_nudge():
    """움직이기 전 거부라도 next_on 밖 코드(NEIGHBOR_TOO_CLOSE)면 넛지로 가지 않고 그 코드로 멈춤 (#260 E).
    이 시도에서 팔을 안 움직였으니(탑뷰 이동은 same_pose 로 안 보냄) 스텝 retry 1 대로 pick 을 한 번 더 — 그래도 같으면 그 코드 (#392 4)."""
    robot = MockRobot(fail={"pick_object": ["NEIGHBOR_TOO_CLOSE", "NEIGHBOR_TOO_CLOSE"]})
    _, result, _ = run(robot, onto=ONTO)
    assert "nudge_object" not in sent_in_pick(robot)
    assert sent_in_pick(robot).count("pick_object") == 2 and step(result, "s5.1")["attempts"] == 2
    assert (block(result)["status"], block(result)["fallback_stopped"]) == ("FAILURE", "NOT_IN_NEXT_ON")
    assert step(result, "s5.1")["error_code"] == "NEIGHBOR_TOO_CLOSE"


def test_nudge_failure_or_moved_failure_stops_without_next_pick():
    """넛지까지 움직이기 전 거부(NO_PUSH_ACCESS)면 이 시도에서 팔을 안 움직였으므로 retry 1 대로 pick 스킬을 한 번 더(#392 4) —
    그래도 같으면 FAILED. 집다 실패(GRASP_FAILED)는 움직였을 수 있어 지금처럼 다시 보내지 않음."""
    for fail, stopped, picks in (
            ({"pick_object": ["WALL_TOO_CLOSE"] * 2, "nudge_object": ["NO_PUSH_ACCESS"] * 2}, "NOT_IN_NEXT_ON", 2),
            ({"pick_object": ["GRASP_FAILED"]}, "MOTION_UNCERTAIN", 1)):   # 집다 실패 = 움직였을 수 있음
        robot = MockRobot(fail=fail)
        _, result, _ = run(robot, onto=ONTO)
        assert sent_in_pick(robot).count("pick_object") == picks, fail
        assert block(result)["fallback_stopped"] == stopped, fail
        assert result.overall_status == "FAILED"


def test_halt_inside_option_aborts_without_further_motion():
    class StopAtNudge(MockRobot):
        def call_action(self, name, params_json, timeout_sec):
            reply = super().call_action(name, params_json, timeout_sec)
            if name.endswith("nudge_object"):
                runner.halt(source="voice")
            return reply

    robot = StopAtNudge(fail={"pick_object": ["WALL_TOO_CLOSE"]})
    runner = Runner(None, schema=SCHEMA, ontology=ONTO)
    from ready2go_runner.core.backend import RosBackend
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTO["world"])
    result = runner.run(TASK)
    assert result.overall_status == "ABORTED"
    assert robot.motion_after("/skills/nudge_object") == []      # 넛지 뒤 탑뷰·집기·닫기·홈 없음


def test_expand_rules_are_checked_before_running():
    no_next_on = onto_with([VIEW, LOOK, {"action": "fallback", "options": [[PICK], [NUDGE, VIEW, LOOK, PICK]]}])
    stale_scan = onto_with([VIEW, LOOK, {"action": "fallback", "next_on": ["WALL_TOO_CLOSE"],
                                         "options": [[PICK], [NUDGE, PICK]]}])          # 넛지 뒤 다시 안 찍음
    loop = onto_with([VIEW, LOOK, {"action": "while", "cond": True, "max_iter": 2, "body": [PICK]}])
    for onto, expected in ((no_next_on, "next_on"), (stale_scan, "새로 찍은 관측"), (loop, "while 미지원")):
        problems = check_task(TASK, SCHEMA, onto["skills"])
        assert any(expected in p for p in problems), problems


def test_task_level_next_on_limits_next_option():
    def task(next_on):
        fb = {"id": "s1", "action": "fallback", "options": [
            [{"id": "s1.a", "action": "place_object", "params": {"location": "handover_zone"}}],
            [{"id": "s1.b", "action": "speak", "params": {"text": "다른 길"}}]]}
        if next_on is not None:
            fb["next_on"] = next_on
        return {"task_id": "t", "sequence": [fb]}

    def backend(action, params, timeout_sec):
        return ActionResult(False, error_code="WALL_TOO_CLOSE") if action == "place_object" else ActionResult(True)

    for next_on, status, stopped in ((None, "COMPLETED", None),                    # 기존: 움직이지 않은 실패면 다음
                                     (["PLACE_BLOCKED"], "FAILED", "NOT_IN_NEXT_ON"),
                                     (["WALL_TOO_CLOSE"], "COMPLETED", None)):
        result = Runner(backend, schema=SCHEMA).run(task(next_on))
        assert result.overall_status == status, next_on
        assert next(s for s in result.steps if s["id"] == "s1").get("fallback_stopped") == stopped


def _fb(*second):
    return [VIEW, LOOK, {"action": "fallback", "next_on": ["WALL_TOO_CLOSE"], "options": [[PICK], list(second)]}]


def test_after_nudge_only_fresh_observation_can_be_grasped():
    """#263 E 리뷰 P2: 글자 포함이 아니라 넛지 뒤 새로 찍은 관측의 target·scan 으로만 집는지 본다."""
    after = {"action": "pick_object", "params": {"target": "$nudge.target_after"}}
    fresh = {"action": "inspect_region", "params": {"region": "$from", "search_target": "$item"}, "output": "fresh"}
    bad = {
        "scan 생략 + target_after": _fb(NUDGE, VIEW, after),
        "새로 찍었지만 target 은 target_after": _fb(NUDGE, VIEW, fresh,
                                                {"action": "pick_object", "params": {"target": "$nudge.target_after",
                                                                                     "scan": "$fresh"}}),
        "새로 찍었지만 target 은 넛지 전 scan": _fb(NUDGE, VIEW, fresh,
                                              {"action": "pick_object", "params": {"target": "$scan.target",
                                                                                   "scan": "$fresh"}}),
        "target·scan 출처가 다름": _fb(NUDGE, VIEW, fresh, LOOK,
                                    {"action": "pick_object", "params": {"target": "$fresh.target", "scan": "$scan"}}),
        "넛지 전 target_after": [VIEW, LOOK, {"action": "pick_object", "params": {"target": "$scan.target_after"}}],
    }
    for name, expand in bad.items():
        assert check_task(TASK, SCHEMA, onto_with(expand)["skills"]), name
    good = {
        "다른 변수 이름으로 새로 찍음": _fb(NUDGE, VIEW, fresh,
                                       {"action": "pick_object", "params": {"target": "$fresh.target", "scan": "$fresh"}}),
        "scan 없이 새 관측 target": _fb(NUDGE, VIEW, LOOK, {"action": "pick_object", "params": {"target": "$scan.target"}}),
        "지금 flat pick (넛지 → 다시 찍기 → 집기)": ONTOLOGY["skills"]["pick"]["expand"],
    }
    for name, expand in good.items():
        assert check_task(TASK, SCHEMA, onto_with(expand)["skills"]) == [], name


def test_after_branch_only_observation_fresh_on_every_path_counts():
    """분기 뒤에는 모든 경로에서 넛지 뒤 새로 찍은 관측만 — 한 경로만 다시 찍었으면 블록 뒤 집기는 거절."""
    one_path = [VIEW, LOOK, {"action": "fallback", "next_on": ["WALL_TOO_CLOSE"],
                             "options": [[NUDGE], [NUDGE, VIEW, LOOK]]}, PICK]
    both = [VIEW, LOOK, {"action": "fallback", "next_on": ["WALL_TOO_CLOSE"],
                         "options": [[NUDGE, VIEW, LOOK], [NUDGE, VIEW, LOOK]]}, PICK]
    assert check_task(TASK, SCHEMA, onto_with(one_path)["skills"])
    assert check_task(TASK, SCHEMA, onto_with(both)["skills"]) == []


def test_overwritten_fresh_observation_loses_its_status():
    """#263 E 재리뷰 P2: 다시 찍은 관측 변수를 set_var·다른 output 이 덮어쓰면 '새 관측' 자격을 잃는다 —
    old 저장 → 넛지 → 다시 찍기(scan) → scan 을 old 로 되돌림 → 집기 는 실행 전 거절 (E 재현: 넛지 전 0.2895 로 집었음)."""
    save = {"action": "set_var", "params": {"name": "old", "value": "$scan"}}
    restore = {"action": "set_var", "params": {"name": "scan", "value": "$old"}}
    dynamic = {"action": "set_var", "params": {"name": "$which", "value": "$old"}}
    other_out = {"action": "move_to_named_pose", "params": {"pose_name": "drawer_top_view", "drawer_id": "$from"},
                 "output": "scan"}
    for name, second in (("set_var 로 되돌림", [save, NUDGE, VIEW, LOOK, restore, PICK]),
                         ("동적 이름 set_var", [save, NUDGE, VIEW, LOOK, dynamic, PICK]),
                         ("다른 동작 output 이 덮어씀", [NUDGE, VIEW, LOOK, other_out, PICK])):
        problems = check_task(TASK, SCHEMA, onto_with(_fb(*second))["skills"])
        assert any("새로 찍은 관측" in p for p in problems), (name, problems)
    ok = [save, NUDGE, VIEW, LOOK, {"action": "set_var", "params": {"name": "note", "value": "$old"}}, PICK]
    assert check_task(TASK, SCHEMA, onto_with(_fb(*ok))["skills"]) == []     # 다른 변수를 쓰면 그대로
    again = [save, NUDGE, VIEW, LOOK, restore, VIEW, LOOK, PICK]               # 되돌린 뒤 다시 찍으면 통과
    assert check_task(TASK, SCHEMA, onto_with(_fb(*again))["skills"]) == []
