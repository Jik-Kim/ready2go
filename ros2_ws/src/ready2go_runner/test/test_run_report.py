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
