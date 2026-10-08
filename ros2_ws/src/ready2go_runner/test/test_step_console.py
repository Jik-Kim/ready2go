"""#98 스텝 진행 콘솔: 문구(run_report 와 같은 말), 시작·끝 순서, 콘솔 실패가 실행에 영향 없음."""
import json
from pathlib import Path

from ready2go_knowledge.core import ontology
from ready2go_runner.core import step_console as sc
from ready2go_runner.core.backend import RosBackend
from ready2go_runner.core.interpreter import Runner
from ready2go_runner.core.logstore import MemoryLogStore

from test_tasks import MockRobot  # noqa: E402  (find_item 실제 경로 mock)

ROOT = Path(__file__).resolve().parents[4]
ONTOLOGY = ontology.load(ROOT / "knowledge/robot_ontology.jsonld")
SCHEMA = json.loads((ROOT / "contracts/task.schema.json").read_text(encoding="utf-8"))
TASK = json.loads((ROOT / "tasks/find_item.json").read_text(encoding="utf-8"))
RUN = "2026-10-08T00:14:06Z_04b242"


def run_with_console(robot, on_step=None):
    lines, store = [], MemoryLogStore()
    runner = Runner(None, schema=SCHEMA, ontology=ONTOLOGY, log_store=store)
    runner.execute = RosBackend(robot.call_action, robot.call_service, lambda: runner.state, ONTOLOGY["world"])

    def console(event, record, info):
        if event == "start":
            line = sc.start_line(info["run_id"], record, info["finally"], info.get("params"))
            if line:
                lines.append(("start", line))
        else:
            lines.append(sc.end_line(info["run_id"], record, info["finally"]))
    runner.on_step = on_step or console
    result = runner.run(TASK)
    return result, lines, store.read_run(result.run_id)


# ---- 문구 ----

def test_start_line_has_run_step_names_and_kst_time():
    record = {"id": "s3.e2", "action": "drawer_control", "parent": "s3", "started_at": "2026-10-08T00:14:06.123Z"}
    line = sc.start_line(RUN, record, params={"drawer_id": "$drawer_id", "state": "open"})   # 시작 때는 아직 안 푼 params
    assert line == "[04b242]   └ ▶ s3.e2 서랍 열기 (drawer_control) 시작 · 09:14:06.123"
    assert "params" not in record                                                    # 원본 기록은 그대로
    assert sc.start_line(RUN, {"id": "s1", "action": "query_ontology"}) is None      # 즉시 끝남 → 끝 줄만


def test_end_lines_success_failure_skip_stop_and_finally():
    ok = {"id": "s5.1.e3", "action": "nudge_object", "parent": "s5.1", "status": "SUCCESS", "duration_sec": 21.37,
          "result": {"pushed": True, "push_vector_m": [0.0, -0.0401],
                     "target_after": {"pose": {"position": [0.025, 0.2519, 0.0]}}}}
    assert sc.end_line(RUN, ok) == (sc.INFO, "[04b242]   └ ✅ s5.1.e3 끌기 (nudge_object) · 21.4 s · "
                                             "40.1 mm 끌기 → 예상 위치 (25, 252) mm")
    level, line = sc.end_line(RUN, {"id": "s5.1.e6", "action": "pick_object", "parent": "s5.1",
                                    "status": "FAILURE", "error_code": "GRASP_FAILED", "duration_sec": 0.0})
    assert level == sc.ERROR and "❌ s5.1.e6 집기 (pick_object)" in line and "GRASP_FAILED" in line
    level, line = sc.end_line(RUN, {"id": "f2", "action": "skill", "skill": "close_drawer",
                                    "status": "SKIPPED", "skipped_reason": "ABORTED"}, in_finally=True)
    assert level == sc.WARN and line.startswith("[04b242] finally ⏭ f2 서랍 닫기 (close_drawer) · 건너뜀 (ABORTED)")
    level, line = sc.end_line(RUN, {"id": "f2", "action": "skill", "skill": "close_drawer", "status": "FAILURE",
                                    "on_failure": "skip", "error_code": "DRAWER_STUCK"}, in_finally=True)
    assert level == sc.WARN and "실패 → 건너뛰고 계속" in line
    level, line = sc.end_line(RUN, {"id": "s5.1.e3", "action": "nudge_object", "status": "FAILURE",
                                    "error_code": "ESTOP"})
    assert level == sc.ERROR and "🛑 s5.1.e3" in line                                  # 비상정지는 따로 표시
    level, line = sc.end_line(RUN, {"id": "f3", "action": "if", "status": "SUCCESS", "branch": "then"}, True)
    assert level == sc.INFO and "→ then" in line


# ---- Runner 연결 ----

def test_console_follows_run_order_and_matches_saved_steps():
    result, lines, saved = run_with_console(MockRobot())
    assert result.overall_status == "COMPLETED"
    ends = [line for level, line in lines if level != "start"]
    assert len(ends) == len(saved["steps"])                                          # 저장된 스텝마다 끝 줄 1개
    assert all(result.run_id[-6:] in line for _, line in lines)
    texts = "\n".join(line for _, line in lines)
    assert texts.index("▶ s3.e2 서랍 열기") < texts.index("✅ s3.e2 서랍 열기")           # 시작 → 끝
    assert "finally ✅ f2s.1 안내 음성 (speak)" in texts and "✅ s5.1.e5 물체 조회" in texts
    assert all(level == sc.INFO for level, _ in lines if level != "start")             # 성공 실행은 경고·오류 없음


def test_failure_run_shows_failed_step_then_finally():
    result, lines, _ = run_with_console(MockRobot(fail={"pick_object": ["GRASP_FAILED"]}))
    assert (result.overall_status, result.failed_step) == ("FAILED", "s5.1.e6")
    errors = [line for level, line in lines if level == sc.ERROR]
    assert any("❌ s5.1.e6 집기" in line for line in errors)
    assert not any("✅ s5.1 " in line for _, line in lines)                          # 실패를 성공으로 찍지 않음
    after = [line for _, line in lines][[line for _, line in lines].index(errors[0]):]
    assert any("finally ✅ f2 서랍 닫기" in line for line in after)


def test_estop_run_marks_stop_and_skipped_finally():
    result, lines, _ = run_with_console(MockRobot(fail={"nudge_object": ["ESTOP"]}))
    assert result.overall_status == "ABORTED"
    texts = "\n".join(line for _, line in lines)
    assert "🛑 s5.1.e3 끌기" in texts and "finally ⏭ f2 서랍 닫기 (close_drawer) · 건너뜀 (ABORTED)" in texts


def test_console_errors_never_change_run_or_records():
    def broken(event, record, info):
        raise RuntimeError("콘솔 고장")
    robot = MockRobot()
    result, _, saved = run_with_console(robot, on_step=broken)
    plain = Runner(None, schema=SCHEMA, ontology=ONTOLOGY)
    plain.execute = RosBackend(MockRobot().call_action, MockRobot().call_service, lambda: plain.state,
                               ONTOLOGY["world"])
    expected = plain.run(TASK)
    assert result.overall_status == expected.overall_status == "COMPLETED"
    assert [s["id"] for s in saved["steps"]] == [s["id"] for s in expected.steps]
