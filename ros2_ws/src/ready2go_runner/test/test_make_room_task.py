"""find_with_unpack make_room 진입·다시 찍기 (#392 2·3, B 제안 — PC2 10/15 출근 준비물 에어팟) — mock 백엔드 + 끼어들기.

2: 놓기 판단(s8.q1 check_only)이 WALL_TOO_CLOSE 여도 make_room 반복(s8.mw)으로 — 예전엔 NEIGHBOR_TOO_CLOSE 만, 벽이면 pick 의
   벽 넛지로 가서 '끄는 길에 몽키'로 끝남. make_room 은 끈 뒤 집기까지 보고 계획(wall_nudge·sweep·remove).
3: make_room 이 OCCLUSION_UNKNOWN(움직이기 전, '다시 찍기' 뜻)이면 반복 안에서 다시 찍음 — 예전엔 그 물품이 바로 끝남.
   다시 찍는 회차는 이전 결과(mr)로 복구 목록·이전 행동 기록을 쓰지 않음.
"""
import pytest

from ready2go_runner.core import item_group as ig
from ready2go_runner.core.interpreter import ActionResult

from start_states import P2_SINGLE  # noqa: E402
from test_item_group import TASK, WORLD, catalog, setup, statuses  # noqa: E402

FULL = {**P2_SINGLE, "airpods_case": "drawer_top"}


def _id(params, key):
    return ((params.get(key) or {}).get("id") or "")


def make_room_ok(action="wall_nudge"):
    return ActionResult(True, {"make_room": {"action": action, "ready_to_pick": True, "moved_id": None,
                                             "pushed_ids": [], "pushed_after": [], "reason": "벽에서 떼어 냄"}})


def run_airpods(hook):
    """출근 준비물(에어팟 위 칸) — 에어팟에만 끼어들기. (결과, 에어팟에 보낸 (동작, params) 목록)."""
    runner, robot, _ = setup(FULL)
    robot.hook = hook
    result = ig.run_group(runner, TASK, catalog().query_list("출근 준비물"), WORLD, speak=lambda text: None)
    sent = [(a, p) for a, p in robot.calls
            if any(_id(p, k).startswith("airpods") for k in ("target", "object"))]
    return result, sent


def test_wall_too_close_judgement_goes_to_make_room():
    """[#392 2] check_only WALL_TOO_CLOSE → make_room(nudge_object make_room) → 준비되면 집기·전달."""
    def hook(action, params):
        if action == "place_object" and params.get("check_only") and _id(params, "object").startswith("airpods"):
            return ActionResult(False, error_code="WALL_TOO_CLOSE")
        if action == "nudge_object" and params.get("make_room"):
            return make_room_ok()
        return None
    result, sent = run_airpods(hook)
    kinds = [a + (".make_room" if p.get("make_room") else "") for a, p in sent if a != "inspect_region"]
    assert "nudge_object.make_room" in kinds and kinds.index("nudge_object.make_room") < kinds.index("pick_object")
    assert statuses(result)[0] == ("airpods_case", ig.DELIVERED)


def test_occlusion_unknown_from_make_room_reshoots_inside_loop():
    """[#392 3] make_room 첫 회 OCCLUSION_UNKNOWN → 반복 안에서 다시 찍고 다시 make_room → 준비되면 집기. 다시 찍는 회차는 복구 목록에
    아무것도 넣지 않음(이전 결과 재사용 없음)."""
    calls = []

    def hook(action, params):
        if action == "place_object" and params.get("check_only") and _id(params, "object").startswith("airpods"):
            return ActionResult(False, error_code="NEIGHBOR_TOO_CLOSE")
        if action == "nudge_object" and params.get("make_room"):
            calls.append(1)
            return ActionResult(False, error_code="OCCLUSION_UNKNOWN") if len(calls) == 1 else make_room_ok()
        return None
    result, sent = run_airpods(hook)
    assert len(calls) == 2
    assert statuses(result)[0] == ("airpods_case", ig.DELIVERED)


def test_occlusion_unknown_every_time_ends_loop_without_picking_target():
    """[#392 3] 계속 OCCLUSION_UNKNOWN → 반복 한도(max_iter 4)까지만 다시 찍고 목표는 집지 않음."""
    calls = []

    def hook(action, params):
        if action == "place_object" and params.get("check_only") and _id(params, "object").startswith("airpods"):
            return ActionResult(False, error_code="NEIGHBOR_TOO_CLOSE")
        if action == "nudge_object" and params.get("make_room"):
            calls.append(1)
            return ActionResult(False, error_code="OCCLUSION_UNKNOWN")
        return None
    result, sent = run_airpods(hook)
    assert len(calls) == 4
    assert "pick_object" not in [a for a, _ in sent]
    assert statuses(result)[0][1] == ig.NOT_DELIVERED and result.items[0].error_code is not None


def test_rescan_after_stalled_moves_does_not_count_as_remove_stall():
    """[#394 E 리뷰] 목표 그대로인 wall_nudge(준비 안 됨) 2회 → 다음 부름 remove_first → 그 부름이 OCCLUSION_UNKNOWN(움직이기 전)이면
    다음 회차는 같은 행동 반복 판정을 건너뛰고 remove_first 를 다시 시도 — 예전엔 이전 mr_prev 로 다시 판정해 실행하지 않은
    remove_first 를 '하고도 그대로'로 보고 멈춤(make_room 3회 뒤 바로 집기)."""
    sent = []

    def hook(action, params):
        if action == "place_object" and params.get("check_only") and _id(params, "object").startswith("airpods"):
            return ActionResult(False, error_code="NEIGHBOR_TOO_CLOSE")
        if action == "nudge_object" and params.get("make_room"):
            sent.append(bool(params.get("remove_first")))
            if len(sent) <= 2:
                return ActionResult(True, {"make_room": {"action": "wall_nudge", "ready_to_pick": False, "moved_id": None,
                                                         "pushed_ids": [], "pushed_after": [], "reason": "벽에서 덜 떨어짐"}})
            if len(sent) == 3:
                return ActionResult(False, error_code="OCCLUSION_UNKNOWN")
            return make_room_ok("remove")
        return None
    result, _ = run_airpods(hook)
    assert sent == [False, False, True, True]
    assert statuses(result)[0] == ("airpods_case", ig.DELIVERED)
