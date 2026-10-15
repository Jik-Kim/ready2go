"""P3 목록 요청 1차 (#302 E 확정 10/15) — 실제 E TTL 조회 결과 + C 물품별 위치 조회 + 물품마다 find_with_unpack (mock 백엔드).

확인: 위치 미상 제외·전부 미상 거절 / 일부 전달 PARTIAL_DELIVERY / 서랍 전환(한 번에 하나) / 못 찾음 뒤 계속 /
움직인 뒤 실패·정지면 묶음 중단. 실물·음성 연결·공개 인텐트는 아직 (계약 PR 뒤).
"""
import json
from pathlib import Path

import pytest

from ready2go_knowledge.core.semantic_query import load_ttl
from ready2go_runner.core import item_group as ig
from ready2go_runner.core.backend import SPEAK_ACTION, Reply, RosBackend
from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.logstore import MemoryLogStore
from ready2go_runner.core.mock_skills import MockSkills

from start_states import P2_SINGLE, with_state  # noqa: E402
from test_tasks import ONTOLOGY, SCHEMA  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
TASK = json.loads((ROOT / "tasks/find_with_unpack.json").read_text(encoding="utf-8"))
WORLD = ONTOLOGY["world"]


def catalog():
    retired = (ROOT / "config/yolo_retired_classes.txt").read_text().splitlines()
    return load_ttl(ROOT / "knowledge/examples/p3_semantics.ttl", active_items=WORLD["items"], retired_items=retired)


class Robot:
    """mock 스킬(장면 없음 — 물품 하나 상자 모델)로 답하는 call_action·call_service. 보낸 동작·안내를 기록."""

    def __init__(self, failures=None, not_visible=()):
        self.skills = MockSkills(failures or {}, set(not_visible))
        self.calls: list[tuple[str, dict]] = []
        self.spoken: list[str] = []
        self.hook = None                    # (action, params) → ActionResult | None — 시험이 끼어들기
        self.speak_hook = None

    def call_action(self, name, params_json, timeout_sec):
        params = json.loads(params_json)
        if name == SPEAK_ACTION:
            self.spoken.append(params.get("text", ""))
            if self.speak_hook is not None:     # (text) → 실패 코드 | None — 시험이 안내 실패·도중 정지를 끼움
                code = self.speak_hook(params.get("text", ""))
                if code:
                    return Reply(False, code, "")
            return Reply(True)
        action = name.rsplit("/", 1)[-1]
        self.calls.append((action, params))
        if self.hook is not None:
            forced = self.hook(action, params)
            if forced is not None:
                return Reply(forced.success, forced.error_code, "")
        reply = self.skills.respond(action, params)
        return Reply(reply.success, reply.error_code, "" if reply.output is None else json.dumps(reply.output))

    def call_service(self, name, region, search_target, timeout_sec):
        self.calls.append(("inspect_region", {"region": region, "search_target": search_target}))
        reply = self.skills.inspect(region, search_target)
        return Reply(reply.success, reply.error_code, "" if reply.output is None else json.dumps(reply.output))

    def drawer_moves(self):
        return [(p["drawer_id"], p["state"]) for a, p in self.calls if a == "drawer_control"]


def setup(located=P2_SINGLE, **robot_kw):
    robot = Robot(**robot_kw)
    runner = Runner(None, schema=SCHEMA, ontology=with_state(ONTOLOGY, located), log_store=MemoryLogStore())
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, WORLD)
    said: list[str] = []
    return runner, robot, said


def statuses(result):
    return [(o.item, o.status) for o in result.items]


def test_commute_list_from_real_e_query_skips_unknown_and_is_partial():
    """'출근 준비물' = 에어팟 케이스(위치 기록 없음)·차키(위 칸)·립밤(아래 칸) — 에어팟은 빼고 안내, 위 칸 → 아래 칸 순서로
    물품마다 열고 닫음(한 번에 서랍 하나). 3개 중 2개 → FAILED + PARTIAL_DELIVERY, E 출처(sha256) 그대로 보존."""
    semantic = catalog().query_list("출근 준비물")
    assert semantic["items"] == ["airpods_case", "car_key", "lip_balm"]
    runner, robot, said = setup()
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=said.append)
    assert statuses(result) == [("car_key", ig.DELIVERED), ("lip_balm", ig.DELIVERED), ("airpods_case", ig.EXCLUDED)]
    assert (result.overall_status, result.error_code) == ("FAILED", ig.PARTIAL_DELIVERY)
    assert robot.drawer_moves() == [("drawer_top", "open"), ("drawer_top", "close"),
                                    ("drawer_bottom", "open"), ("drawer_bottom", "close")]
    assert said == ["차키, 립밤 가져올게요. 에어팟 케이스는 위치 기록이 없어서 빼고 가져올게요.",
                    "3개 중 2개 가져왔어요. 에어팟 케이스는 위치 기록이 없어요."]
    assert result.source == semantic["source"] and result.source["sha256"]
    assert all(o.run_id for o in result.items if o.status == ig.DELIVERED)          # 물품마다 따로 실행 기록
    state = runner.state
    assert state["located_in"]["car_key"] == state["located_in"]["lip_balm"] == "handover_zone"


def test_class_query_single_item_completes():
    """'귀중품' → 차키 하나(Key → Valuables) — 전부 전달이면 COMPLETED, 요약 '차키를 가져왔어요'."""
    semantic = catalog().query_class("귀중품")
    runner, _, said = setup()
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=said.append)
    assert (result.overall_status, result.error_code, result.delivered) == ("COMPLETED", None, ["car_key"])
    assert said[-1] == "차키를 가져왔어요."


def test_all_known_list_completes_with_count():
    semantic = catalog().query_list("출근 준비물")
    runner, _, said = setup({**P2_SINGLE, "airpods_case": "drawer_top"})
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=said.append)
    assert result.overall_status == "COMPLETED" and len(result.delivered) == 3
    assert [o.item for o in result.items] == ["airpods_case", "car_key", "lip_balm"]  # 위 칸 둘 → 아래 칸
    assert said[-1] == "3개 모두 가져왔어요."


def test_not_found_item_does_not_stop_the_rest():
    """차키를 못 찾아도(움직이기 전 실패, 정리까지 끝나고 빈손·닫힘) 다음 물품 립밤은 진행 → 일부 전달."""
    semantic = catalog().query_list("출근 준비물")
    runner, robot, said = setup(not_visible={"car_key"})
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=said.append)
    assert statuses(result)[:2] == [("car_key", ig.NOT_DELIVERED), ("lip_balm", ig.DELIVERED)]
    assert (result.overall_status, result.error_code) == ("FAILED", ig.PARTIAL_DELIVERY)
    assert ("drawer_bottom", "open") in robot.drawer_moves()
    assert said[-1].startswith("3개 중 1개 가져왔어요. 차키는 ")


def test_motion_failure_stops_the_group():
    """집기 실패(움직인 뒤 실패, 허용 목록 밖)면 묶음 전체 중단 — 립밤은 실행 안 함, 아래 서랍도 안 엶."""
    semantic = catalog().query_list("출근 준비물")
    runner, robot, said = setup(failures={"pick_object": ["GRASP_FAILED", None]})
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=said.append)
    assert result.overall_status == "FAILED" and result.error_code not in (None, ig.PARTIAL_DELIVERY)
    assert statuses(result)[:2] == [("car_key", ig.NOT_DELIVERED), ("lip_balm", ig.NOT_RUN)]
    assert ("drawer_bottom", "open") not in robot.drawer_moves()
    assert said[-1] == ("하나도 가져오지 못했어요. 차키는 꺼내지 못했어요. 에어팟 케이스는 위치 기록이 없어요. "
                        "립밤은 작업하지 않았어요. 문제가 생겨 목록 작업을 멈췄어요.")


def test_halt_inside_an_item_aborts_the_group():
    """차키 집는 중 '멈춰' → 그 물품 ABORTED → 묶음 ABORTED, 립밤 실행 안 함, 묶음 안 재개 없음 안내."""
    semantic = catalog().query_list("출근 준비물")
    runner, robot, said = setup()

    def stop_at_pick(action, params):
        if action == "pick_object":
            runner.halt(source="voice")
            return ActionResult(False, error_code="CANCELED")
        return None
    robot.hook = stop_at_pick
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=said.append)
    assert (result.overall_status, result.error_code) == ("ABORTED", "HALTED")
    assert statuses(result)[:2] == [("car_key", ig.NOT_DELIVERED), ("lip_balm", ig.NOT_RUN)]
    assert "이어서 할 수 없어요" in said[-1]


def test_halt_between_items_does_not_start_the_next(monkeypatch):
    semantic = catalog().query_list("출근 준비물")
    runner, robot, said = setup()
    real_run = runner.run

    def run_then_halt(task, inputs=None, **kw):
        result = real_run(task, inputs, **kw)
        runner.halt(source="voice")          # 첫 물품이 끝난 뒤 실행 사이 정지
        return result
    monkeypatch.setattr(runner, "run", run_then_halt)
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=said.append)
    assert (result.overall_status, result.error_code) == ("ABORTED", "HALTED")
    assert statuses(result)[:2] == [("car_key", ig.DELIVERED), ("lip_balm", ig.NOT_RUN)]
    assert said[-1] == ("3개 중 1개 가져왔어요. 에어팟 케이스는 위치 기록이 없어요. 립밤은 작업하지 않았어요. "
                        "목록 작업은 멈춰서 이어서 할 수 없어요. 다시 요청해 주세요.")


def test_all_unknown_is_rejected_without_motion():
    semantic = catalog().query_list("출근 준비물")
    runner, robot, said = setup({"toy_wrench": "drawer_top"})       # 세 물품 다 위치 기록 없음
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=said.append)
    assert (result.overall_status, result.error_code) == ("FAILED", "UNKNOWN_ITEM")
    assert robot.calls == [] and said == []                          # 로봇 동작·안내 없음 (거절은 E 가 안내)


@pytest.mark.parametrize("semantic", [
    {"items": [], "source": {"kind": "list"}},
    {"items": ["car_key", "car_key"], "source": {"kind": "list"}},
    {"items": ["wallet"], "source": {"kind": "class"}},
    {"items": ["car_key"], "source": {"kind": "location"}},
    "car_key",
])
def test_bad_e_result_is_rejected_before_anything(semantic):
    runner, robot, said = setup()
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=said.append)
    assert (result.overall_status, result.error_code) == ("FAILED", "BAD_QUERY") and result.problems
    assert robot.calls == [] and said == []


def test_item_already_on_tray_is_excluded_not_rerun():
    semantic = catalog().query_list("출근 준비물")
    runner, robot, said = setup({**P2_SINGLE, "car_key": "handover_zone"})
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=said.append)
    assert ("car_key", ig.EXCLUDED) in statuses(result)
    assert robot.drawer_moves() == [("drawer_bottom", "open"), ("drawer_bottom", "close")]


def test_resumable_runner_halt_inside_group_leaves_nothing_suspended():
    """[#371 E P2] 운영 재개 모드(resumable=True)에서 첫 탑뷰 이동 중 '멈춰' — 묶음은 ABORTED·재개 없음이고
    물품 실행도 SUSPENDED 로 남지 않음(묶음 밖에서 그 물품만 재개되지 않게). 정지 잠금은 유지, 원래 설정은 되돌림."""
    semantic = catalog().query_list("출근 준비물")
    runner, robot, said = setup()
    runner.resumable = True

    def stop_at_top_view(action, params):
        if action == "move_to_named_pose" and params.get("pose_name") == "drawer_top_view":
            runner.halt(source="voice")
            return ActionResult(False, error_code="CANCELED")
        return None
    robot.hook = stop_at_top_view
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=said.append)
    assert (result.overall_status, result.error_code) == ("ABORTED", "HALTED")
    assert runner.suspended is None and runner.halted is True                     # 보존 없음 · 잠금 유지
    assert runner.resumable is True                                                # 원래 설정으로
    assert statuses(result)[:2] == [("car_key", ig.NOT_DELIVERED), ("lip_balm", ig.NOT_RUN)]
    assert ("drawer_bottom", "open") not in robot.drawer_moves()
    assert "이어서 할 수 없어요" in said[-1]


# 처음 원인은 허용 코드(NO_FREE_SPACE)인데 정리(복구)도 실패한 실행 — 실제 Runner 가 처음 원인을 결과에 남기는지 재현하는 작은 태스크
NO_ROOM_THEN_RESTORE_FAIL = {
    "task_id": "no_room_then_restore_fail",
    "inputs": {"target": None},
    "sequence": [{"id": "a1", "action": "place_object", "params": {"location": "drawer_top", "slot": "free"}}],
    "finally": [
        {"id": "z1", "action": "set_var", "params": {"name": "restore_failed", "value": [{"class": "cover_plate"}]}},
        {"id": "z2", "action": "set_var", "params": {"name": "task_error", "value": {"code": "RESTORE_INCOMPLETE", "step": "fr"}}},
    ],
}


def test_allowed_failure_with_restore_failure_stops_the_group():
    """[#371 E P2] 결과 코드는 NO_FREE_SPACE(허용)여도 태스크 복구 실패 표식(task_error RESTORE_INCOMPLETE·restore_failed)이
    있으면 다음 물품을 하지 않음 — 빈손·서랍 닫힘이어도. 묶음 원인 RESTORE_INCOMPLETE, 안내에 사람 확인."""
    semantic = catalog().query_list("출근 준비물")
    runner, robot, said = setup(failures={"place_object": ["NO_FREE_SPACE", None]})
    result = ig.run_group(runner, NO_ROOM_THEN_RESTORE_FAIL, semantic, WORLD, speak=said.append)
    first = result.items[0]
    assert (first.item, first.overall_status, first.error_code, first.restore_incomplete) == \
        ("car_key", "FAILED", "NO_FREE_SPACE", True)                                # Runner 는 처음 원인을 남김
    assert (result.overall_status, result.error_code) == ("FAILED", "RESTORE_INCOMPLETE")
    assert statuses(result)[1] == ("lip_balm", ig.NOT_RUN)
    assert said[-1].endswith("옮긴 물건 일부를 원래 자리로 못 돌려놔서 목록 작업을 멈췄어요. 사람이 확인해 주세요.")



def test_accept_speech_failure_means_no_motion():
    """수락 문장(accept_text)이 실패하면 로봇 동작 0번으로 FAILED(그 코드) — 계약07."""
    semantic = catalog().query_list("출근 준비물")
    runner, robot, said = setup()
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=lambda text: "BACKEND_ERROR", accept_text="출근 준비물을 가져올게요.")
    assert (result.overall_status, result.error_code) == ("FAILED", "BACKEND_ERROR") and robot.calls == []


@pytest.mark.parametrize("returned", ["CANCELED", None])
def test_stop_during_accept_speech_is_aborted_not_failed(returned):
    """[#381 E 리뷰] 수락 안내 도중 '멈춰' — 안내가 CANCELED 로 끝나든 성공으로 끝나든 ABORTED·HALTED(정지 우선), 로봇 동작 0번."""
    semantic = catalog().query_list("출근 준비물")
    runner, robot, _ = setup()

    def speak(text):
        runner.halt(source="voice")
        return returned
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=speak, accept_text="출근 준비물을 가져올게요.")
    assert (result.overall_status, result.error_code) == ("ABORTED", "HALTED") and robot.calls == []



FULL = {**P2_SINGLE, "airpods_case": "drawer_top"}        # E 사용자 확정 10/15: 에어팟 케이스 = 위 칸 (initial_state 와 같은 배치)


def test_item_start_text_order_words():
    """물품별 순서 안내 (#302 E 요청 10/15) — 첫 '먼저', 그 뒤 '다음으로', 1개뿐이면 순서말 없음, 조사는 받침 따라."""
    assert ig.item_start_text("차키", 0, 3) == "먼저 차키를 가져올게요"
    assert ig.item_start_text("립밤", 2, 3) == "다음으로 립밤을 가져올게요"
    assert ig.item_start_text("차키", 0, 1) == "차키를 가져올게요"


def test_each_item_announces_its_order_instead_of_generic_line():
    """물품 실행의 첫 안내(s2.1)가 순서 안내 — 일반 안내 '…찾아 올게요'(s2.2)는 안 나감. 뺀 물품(에어팟)은 순번에 안 셈."""
    semantic = catalog().query_list("출근 준비물")
    runner, robot, _ = setup()                                                    # 에어팟 위치 없음 → 뺌
    ig.run_group(runner, TASK, semantic, WORLD, speak=lambda text: None)
    assert [t for t in robot.spoken if "가져올게요" in t or "찾아 올게요" in t] == \
        ["먼저 차키를 가져올게요", "다음으로 립밤을 가져올게요"]
    runner, robot, _ = setup(FULL)
    ig.run_group(runner, TASK, semantic, WORLD, speak=lambda text: None)
    assert [t for t in robot.spoken if "가져올게요" in t or "찾아 올게요" in t] == \
        ["먼저 에어팟 케이스를 가져올게요", "다음으로 차키를 가져올게요", "다음으로 립밤을 가져올게요"]


def test_single_item_list_has_no_order_word():
    semantic = catalog().query_class("귀중품")
    runner, robot, _ = setup()
    ig.run_group(runner, TASK, semantic, WORLD, speak=lambda text: None)
    assert "차키를 가져올게요" in robot.spoken and not any("먼저" in t or "찾아 올게요" in t for t in robot.spoken)


def test_item_speech_failure_stops_group_with_no_motion_for_that_item():
    """둘째 물품 안내 실패 → 그 물품 동작 0번(서랍도 안 엶), 허용 코드가 아니라 묶음 중단 — 셋째는 실행 안 함."""
    semantic = catalog().query_list("출근 준비물")
    runner, robot, _ = setup(FULL)
    robot.speak_hook = lambda text: "BACKEND_ERROR" if text == "다음으로 차키를 가져올게요" else None
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=lambda text: None)
    assert statuses(result) == [("airpods_case", ig.DELIVERED), ("car_key", ig.NOT_DELIVERED), ("lip_balm", ig.NOT_RUN)]
    assert result.overall_status == "FAILED" and result.error_code not in (None, ig.PARTIAL_DELIVERY, *ig.CONTINUE_CODES)
    assert robot.drawer_moves() == [("drawer_top", "open"), ("drawer_top", "close")]   # 첫 물품 것만
    assert runner.state["located_in"]["car_key"] == "drawer_top"


def test_stop_during_item_speech_aborts_group():
    """둘째 물품 안내 도중 '멈춰' → 그 물품 동작 0번, 묶음 ABORTED·HALTED(이어서 안 함)."""
    semantic = catalog().query_list("출근 준비물")
    runner, robot, _ = setup(FULL)

    def stop_on_second(text):
        if text == "다음으로 차키를 가져올게요":
            runner.halt(source="voice")
            return "CANCELED"
        return None
    robot.speak_hook = stop_on_second
    result = ig.run_group(runner, TASK, semantic, WORLD, speak=lambda text: None)
    assert (result.overall_status, result.error_code) == ("ABORTED", "HALTED")
    assert statuses(result)[1:] == [("car_key", ig.NOT_DELIVERED), ("lip_balm", ig.NOT_RUN)]
    assert robot.drawer_moves() == [("drawer_top", "open"), ("drawer_top", "close")]
