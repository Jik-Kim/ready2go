"""실행 기록 보고서 (core/run_report.py, nodes/run_report.py) — 10/06 PC2 실물 기록(#22) 그대로로 시험.

test/fixtures/pc2_run_20261006_*.json: PC2 cobot2 runs·steps 에서 _id 만 빼고 옮김
(6fc193 의 f3·f3.1 시간은 원본 조회에 없어 비움).
"""
import copy
import json
from pathlib import Path

from ready2go_runner.core import run_report as rr
from ready2go_runner.core.logstore import JsonlLogStore
from ready2go_runner.nodes import run_report as cli

DATA = Path(__file__).resolve().parent / "fixtures"
OK = json.loads((DATA / "pc2_run_20261006_f45c86.json").read_text(encoding="utf-8"))
FAIL = json.loads((DATA / "pc2_run_20261006_6fc193.json").read_text(encoding="utf-8"))


def test_success_run_reads_like_the_22_result():
    text = rr.to_text(OK)
    assert "✅ 성공 · 127.2 s · 스텝 기록 16개" in text
    assert "시작 10/06 20:07:13 KST" in text                              # UTC 11:07 → KST 20:07
    for expected in ["226.1 mm 열림", "eraser 찾음 (177, 290) mm", "41.8 mm 끌기 → 예상 위치 (177, 248) mm",
                     "잡음", "handover_zone_1", "닫힘 확인", "drawer_top 닫힘 → 열림", "그리퍼 empty → eraser"]:
        assert expected in text, expected


def test_rows_hide_if_and_nest_skill_expansions():
    rows = rr.rows(OK["steps"])
    assert [r.step["id"] for r in rows] == ["s1", "s2", "s3", "s4.1", "s4.2", "f1", "f2", "f3.1"]
    assert {r.step["id"]: [c.step["id"] for c in r.children] for r in rows if r.children} == {
        "s2": ["s2.e1", "s2.e2"], "s4.1": ["s4.1.e1", "s4.1.e2"], "s4.2": ["s4.2.e1"], "f2": ["f2.e1"]}


def test_failed_run_explains_cause_and_skip():
    text = rr.to_text(FAIL)
    assert "❌ 실패 · 4.0 s" in text and "실패 스텝 s2.e1 · BACKEND_ERROR" in text
    assert "⏭ 서랍 닫기" in text and "drawer_top.open = False (필요 True)" in text   # finally 닫기는 조건 불충족으로 건너뜀
    skill_line = next(line for line in text.splitlines() if line.strip().startswith("2 "))
    assert skill_line.count("백엔드 호출 실패") == 0                               # 설명은 원자 동작 줄에만


def test_markdown_table_has_one_line_per_row_and_child():
    md = rr.to_markdown(OK)
    table = [line for line in md.splitlines() if line.startswith("| ") and "---" not in line]
    assert len(table) == 1 + 8 + 6                                          # 머리 + 최상위 8 + 원자 동작 6
    assert all(line.count("|") == 7 for line in table)                     # 내용 안의 '|' 가 표를 깨지 않음


def test_report_is_read_only_and_tolerates_unknown_or_unfinished():
    before = copy.deepcopy(OK)
    rr.to_text(OK), rr.to_markdown(OK)
    assert OK == before
    odd = {"run": {"run_id": "x", "task_id": "t", "started_at": "2026-10-07T00:00:00Z"},
           "steps": [{"seq": 0, "id": "a", "action": "future_action", "status": "FAILURE",
                      "error": {"code": "NEW_CODE"}}]}
    text = rr.to_text(odd)
    assert "진행 중?" in text and "future_action" in text and "NEW_CODE" in text


def test_rejected_run_shows_why_it_did_not_start():
    """#105 D 리뷰 P2: 실행 전 거절(TASK_INVALID)은 스텝이 없으니 runs.problems 를 그대로 보여 준다."""
    rejected = {"run": {"run_id": "2026-10-07T03:00:00Z_abc123", "task_id": "p1_demo_eraser",
                        "started_at": "2026-10-07T03:00:00Z", "total_duration_sec": 0.0, "overall_status": "FAILED",
                        "error": {"code": "TASK_INVALID"},
                        "problems": ["sequence[0]: 알 수 없는 action 'opne_drawer'", "finally[1]: params 누락"]},
                "steps": []}
    text = rr.to_text(rejected)
    assert "실행 전 거절 · TASK_INVALID: 태스크 검사 실패" in text and "실패 스텝 ?" not in text
    assert "이유: sequence[0]: 알 수 없는 action 'opne_drawer'" in text and "이유: finally[1]: params 누락" in text
    md = rr.to_markdown(rejected)
    assert "- 이유: finally[1]: params 누락" in md


def test_kst():
    assert rr.kst("2026-10-06T15:30:00.5Z") == "10/07 00:30:00"
    assert rr.kst(None) == "-"


def _jsonl_dir(tmp_path):
    store = JsonlLogStore(tmp_path)
    for record in (FAIL, OK):                  # 시간 순으로 저장
        store.start_run(record["run"])
        for step in record["steps"]:
            store.write_step(step)
        store.end_run(record["run"])
    return tmp_path


def test_cli_reads_jsonl_latest_and_by_suffix(tmp_path, capsys):
    folder = _jsonl_dir(tmp_path)
    assert cli.jsonl_run_ids(folder) == [FAIL["run"]["run_id"], OK["run"]["run_id"]]
    assert cli.main(["--jsonl", str(folder)]) == 0
    assert "f45c86 · p1_demo_eraser · ✅ 성공" in capsys.readouterr().out
    assert cli.main(["--jsonl", str(folder), "--run", "6fc193", "--markdown"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("**실행 2026-10-06T11:02:28Z_6fc193") and "| # | 단계 |" in out
    assert cli.main(["--jsonl", str(folder), "-n", "2", "--ros-args"]) == 0
    out = capsys.readouterr().out
    assert out.index("6fc193") < out.index("f45c86")                      # 오래된 것부터


def test_cli_missing_run_is_an_error(tmp_path, capsys):
    assert cli.main(["--jsonl", str(_jsonl_dir(tmp_path)), "--run", "nope"]) == 1
    assert "기록 없음" in capsys.readouterr().err


# ---- 기록 누락 점검 (run_report --check, FR-LOG-02·AC-LOG-01) ----

def test_check_real_pc2_records_are_complete():
    """10/06 PC2 실물 기록(#22) 2건 — 성공·실패 모두 빠짐없음."""
    assert rr.check(OK) == [] and rr.check(FAIL) == []
    assert rr.check_line(OK).startswith("✅ 2026-10-06T11:07:13Z_f45c86")


def broken(record, change):
    record = copy.deepcopy(record)
    change(record)
    return rr.check(record)


def test_check_finds_each_kind_of_gap():
    assert broken(OK, lambda r: r["steps"].pop(3)) == ["스텝 기록 빠짐: seq [3]"]
    assert broken(OK, lambda r: r["steps"].append(copy.deepcopy(r["steps"][0]))) == ["스텝 기록 중복: seq [0]"]
    assert broken(OK, lambda r: r["run"].pop("overall_status")) == ["끝 기록 없음 — 아직 실행 중이거나 end_run 저장 누락"]
    assert broken(OK, lambda r: r["run"].pop("ended_at")) == ["끝 기록에 종료 시각·전체 시간 없음"]
    assert broken(OK, lambda r: r["steps"][2].pop("status"))[0].startswith("결과 없는 스텝")
    assert broken(FAIL, lambda r: r["run"].pop("error")) == ["FAILED 인데 오류 코드 없음"]
    assert broken(OK, lambda r: r["steps"][1].update(run_id="other")) == ["다른 실행의 스텝 기록이 섞임: ['other']"]
    child = next(i for i, s in enumerate(OK["steps"]) if s.get("parent"))
    parent = OK["steps"][child]["parent"]
    assert any(p.startswith("부모 스텝 기록 없음") for p in
               broken(OK, lambda r: r["steps"].__setitem__(slice(None), [s for s in r["steps"] if s["id"] != parent])))
    assert rr.check({"run": None, "steps": []}) == ["실행 헤더(runs) 없음 — start_run 저장 누락"]


def test_check_runner_records_including_rejected_and_resumed():
    """Runner 가 만든 기록: 정상·실행 전 거절(스텝 0개)·재개 대기 뒤 이어서 끝난 실행 모두 빠짐없음."""
    from ready2go_runner.core.interpreter import ActionResult, Runner
    from ready2go_runner.core.logstore import MemoryLogStore
    from test_interpreter import FakeBackend

    task = {"task_id": "t", "sequence": [{"id": "s1", "action": "move_to_named_pose", "params": {"pose_name": "home"}},
                                         {"id": "s2", "action": "speak", "params": {"text": "끝"}}]}
    store = MemoryLogStore()
    ok = Runner(FakeBackend(), log_store=store).run(task)
    from test_tasks import SCHEMA
    rejected = Runner(FakeBackend(), schema=SCHEMA, log_store=store).run(
        {"task_id": "bad", "sequence": [{"id": "x", "action": "fly"}]})
    assert (rejected.overall_status, rejected.error_code) == ("FAILED", "TASK_INVALID") and not rejected.steps
    resumable = Runner(FakeBackend({"move_to_named_pose": [ActionResult(False, error_code="ESTOP"), ActionResult(True)]}),
                       log_store=store, resumable=True)
    first = resumable.run(task)
    assert rr.check(store.read_run(first.run_id)) == []                      # SUSPENDED 도 그 시점까지 빠짐없음
    resumable.resume()
    resumable.resume_run(resumable.halt_event_id)
    for result in (ok, rejected, first):
        assert rr.check(store.read_run(result.run_id)) == [], result.run_id


def test_cli_check_exit_code(tmp_path, capsys):
    folder = _jsonl_dir(tmp_path)
    assert cli.main(["--jsonl", str(folder), "-n", "2", "--check"]) == 0
    out = capsys.readouterr().out
    assert out.count("✅") == 2 and "2건 중 누락 0건" in out
    store = JsonlLogStore(folder)                                            # 끝 기록 없는 실행을 하나 더
    store.start_run({"run_id": "2026-10-07T00:00:00Z_zzzzzz", "task_id": "t", "inputs": {}, "started_at": "x"})
    assert cli.main(["--jsonl", str(folder), "-n", "3", "--check"]) == 1
    out = capsys.readouterr().out
    assert "❌ 2026-10-07T00:00:00Z_zzzzzz" in out and "끝 기록 없음" in out and "3건 중 누락 1건" in out


def test_report_survives_non_numeric_values():
    """#167 PM 권장: 결과 값이 숫자가 아니어도(좌표·시간 문자열·None) 보고서가 멈추지 않고 그 칸만 표시."""
    record = {"run": {"run_id": "r", "task_id": "t", "overall_status": "FAILED", "total_duration_sec": "?",
                      "error": {"code": "LIFT_FAILED"}, "failed_step": "s2"},
              "steps": [
                  {"run_id": "r", "seq": 0, "id": "s1", "action": "inspect_region", "status": "SUCCESS",
                   "duration_sec": "abc", "result": {"target_found": True,
                                                     "target": {"class": "eraser", "pose": {"position": ["x", None]}}}},
                  {"run_id": "r", "seq": 1, "id": "s2", "action": "place_object", "status": "FAILURE",
                   "error": {"code": "LIFT_FAILED"}, "result": {"slot": None, "placed_pose": {"position": [None, "y"]}}},
                  {"run_id": "r", "seq": 2, "id": "s3", "action": "nudge_object", "status": "SUCCESS",
                   "result": {"pushed": True, "push_vector_m": ["a", "b"]}}]}
    text = rr.to_text(record)
    assert "결과 값을 읽을 수 없음" in text and "LIFT_FAILED" in text and "abc s" in text
    assert rr.to_markdown(record).count("결과 값을 읽을 수 없음") == 3


def test_failed_place_inside_skill_keeps_placed_pose_in_child_record():
    """#167 PM 권장 1: P2 실제 경로(place 스킬 → place_object 전개)에서도 그리퍼를 연 뒤 실패의 placed_pose 가
    하위 동작 기록(DB result)에 남고 블랙보드에는 없음."""
    from ready2go_runner.core.interpreter import ActionResult, Runner
    from ready2go_runner.core.logstore import MemoryLogStore
    from test_interpreter import FakeBackend

    placed = {"slot": None, "placed_pose": {"frame": "drawer_top", "position": [0.06, 0.22, 0.0], "yaw": 0.0}}
    onto = {"skills": {"place": {"kind": "primitive", "params": {"item": "Item", "to": "Place"}, "pre": [],
                                 "effect": [{"subject": "$item", "predicate": "located_in", "value": "$to"}],
                                 "expand": [{"action": "place_object", "params": {"location": "$to"}}]}},
            "state": {"located_in": {"eraser": "gripper"}}}
    store = MemoryLogStore()
    task = {"task_id": "t", "sequence": [{"id": "s1", "skill": "place", "params": {"item": "eraser", "to": "drawer_top"},
                                          "output": "placed"}]}
    runner = Runner(FakeBackend({"place_object": ActionResult(False, placed, "LIFT_FAILED")}), ontology=onto,
                    log_store=store)
    result = runner.run(task)
    assert (result.overall_status, result.error_code) == ("FAILED", "LIFT_FAILED")
    saved = store.read_run(result.run_id)["steps"]
    child = next(s for s in saved if s.get("parent") == "s1")
    assert child["result"] == placed and child["error"]["code"] == "LIFT_FAILED"
    assert "placed" not in result.blackboard and runner.state["located_in"]["eraser"] == "gripper"   # effect 없음
    assert "놓은 자리 (60, 220) mm" in rr.to_text(store.read_run(result.run_id))


def _restore_step(origin_yaw, now, status="found", distance=0.004, occluded_by=None):
    origin = {"frame": "drawer_top", "position": [0.12, 0.14, 0.0], "yaw": origin_yaw, "yaw_valid": True}
    return {"run_id": "r", "seq": 0, "id": "fv.3.1", "action": "find_moved", "status": "SUCCESS",
            "params": {"record": {"class": "caramel_box", "origin": origin, "placed": origin}, "tol_m": 0.1},
            "result": {"status": status, "distance_m": distance,
                       "object": None if now is None else {"class": "caramel_box", "pose": now,
                                                           **({} if occluded_by is None else {"occluded_by": occluded_by})}}}


def test_restore_error_shows_position_and_direction_not_a_verdict():
    """AC-ACT-03: 위치·방향 오차를 함께. 비전 yaw 는 반 바퀴 주기라 1.55 와 −1.55 는 2.4° 차이."""
    now = {"frame": "drawer_top", "position": [0.124, 0.14, 0.0], "yaw": -1.55, "yaw_valid": True}
    check = rr.restore_check(_restore_step(1.55, now))
    assert check["position_m"] == 0.004 and abs(check["yaw_rad"] - 0.0416) < 1e-3
    assert rr.detail(_restore_step(1.55, now)) == "복구 확인 caramel_box: 위치 오차 4.0 mm · 방향 오차 2.4°"
    record = {"run": {"run_id": "r", "task_id": "find_with_unpack"}, "steps": [_restore_step(1.55, now)]}
    assert "  복구 오차 (판정 아님): caramel_box 위치 오차 4.0 mm · 방향 오차 2.4°" in rr.header(record)


def test_restore_error_unknown_direction_missing_and_far():
    blurry = {"frame": "drawer_top", "position": [0.12, 0.14, 0.0], "yaw": 0.0, "yaw_valid": False}
    assert rr.detail(_restore_step(0.3, blurry)).endswith("위치 오차 4.0 mm · 방향 모름")
    assert rr.detail(_restore_step(0.3, None, "missing", None)) == "복구 확인 caramel_box: 못 찾음(missing)"
    assert rr.detail(_restore_step(0.3, None, "ambiguous", 0.15)).endswith("위치 오차 150.0 mm · 방향 모름 (ambiguous)")


def test_reid_find_moved_is_not_a_restore_check():
    step = {"id": "fr.4", "action": "find_moved", "params": {"record": {"class": "car_key", "origin": {"position": [0, 0]},
            "placed": {"position": [0.05, 0.04]}}}, "result": {"status": "found", "distance_m": 0.002}}
    assert rr.restore_check(step) is None and rr.detail(step) == "found (놓은 자리에서 2.0 mm)"


def test_region_photo_without_search_target_is_not_shown_as_not_found():
    """되돌리기·복구 확인처럼 찾는 물체 없이 서랍 전체를 찍은 결과는 '못 찾음'이 아니라 보인 물체 수 (10/11 노드 mock 에서 발견)."""
    photo = {"action": "inspect_region", "params": {"region": "drawer_top"},
             "result": {"target_found": False, "target": None, "candidates": [], "visible_count": 2}}
    assert rr.detail(photo) == "보인 물체 2개"
    missing = {**photo, "params": {"region": "drawer_top", "search_target": "eraser"}}
    assert rr.detail(missing) == "못 찾음 (보인 물체 2개)"


def test_region_not_visible_has_korean_explanation():
    """#220 비전 관측 오류 — '못 찾음'과 다른 관측 오류임을 보고서에서 바로 알 수 있게."""
    step = {"action": "inspect_region", "params": {"region": "drawer_top", "search_target": "eraser"},
            "error": {"code": "REGION_NOT_VISIBLE"}}
    assert rr.detail(step).startswith("REGION_NOT_VISIBLE: 촬영 지역 바닥이 충분히 안 보임")


def test_pick_failure_shows_hand_state():
    """#223 B hand: 실패 뒤 손 상태를 함께 — released 는 빈손 확정이 아님."""
    step = {"action": "pick_object", "params": {}, "result": {"grasp_ok": False, "hand": "released"}}
    assert rr.detail(step) == "못 잡음 (다시 벌림 — 빈손 확정 아님)"
    assert rr.detail({**step, "result": {"grasp_ok": False, "hand": "unknown"}}) == "못 잡음 (쥐었는지 모름)"
    assert rr.detail({**step, "result": {"grasp_ok": True, "hand": "holding"}}) == "잡음"
    assert rr.detail({**step, "result": {"grasp_ok": False}}) == "못 잡음"            # hand 없는 예전 기록


def test_restore_check_flags_object_covered_at_final_scan():
    """A Isaac 10/13: 복구 뒤 위에 다시 올린 물체(차키)가 가리면 마지막 촬영은 보이는 조각 가운데라 18.3 mm·−89.7° 로
    나옴(실제 0.3 mm) → 위치 오차로 쓰지 않고 가려짐으로 표시. 다 보이면(occluded_by []) 지금처럼 오차."""
    now = {"frame": "drawer_top", "position": [0.138, 0.14, 0.0], "yaw": -1.565, "yaw_valid": False}
    step = _restore_step(0.0, now, distance=0.0183, occluded_by=["car_key#1"])
    assert rr.detail(step) == "복구 확인 caramel_box: 가려짐(위에 car_key#1) — 보이는 조각 기준 18.3 mm, 위치 오차로 쓰지 않음"
    record = {"run": {"run_id": "r", "task_id": "find_with_unpack"}, "steps": [step]}
    assert "위치 오차로 쓰지 않음" in "\n".join(rr.header(record))
    clear = _restore_step(1.55, {"frame": "drawer_top", "position": [0.124, 0.14, 0.0], "yaw": -1.55, "yaw_valid": True},
                          occluded_by=[])
    assert rr.detail(clear) == "복구 확인 caramel_box: 위치 오차 4.0 mm · 방향 오차 2.4°"
