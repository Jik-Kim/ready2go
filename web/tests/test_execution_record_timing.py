"""D 조회 경계 확인: 실제 C 코어/JSONL 기록기와 모의 동작을 사용하며 ROS·실물 시험은 아니다."""
import json
from pathlib import Path

import pytest

from ready2go_runner.core.interpreter import ActionResult, Runner
from ready2go_runner.core.logstore import JsonlLogStore
from ready2go_web.adapters.execution_reader import JsonlExecutionReader


@pytest.mark.parametrize("fail_second", [False, True])
def test_record_visibility_before_during_and_after_run(tmp_path, fail_second):
    """실행 중 조회에는 시작 입력과 끝난 단계만 보이고 종료 필드는 반환 후 보인다."""
    root = Path(__file__).resolve().parents[2]
    # 계약 원본의 예시 근거를 그대로 입력한다. 실제 분류 실행 또는 실물 근거라고 주장하지 않는다.
    sample = json.loads((root / "contracts/examples/intent_find_class.json").read_text())
    semantic = {**sample["semantic"], "items": sample["targets"]}
    assert semantic["evidence"]
    reader, writer = JsonlExecutionReader(tmp_path), JsonlLogStore(tmp_path)
    run_id = "timing_probe.1"
    assert reader.read_run(run_id) == {"run": None, "steps": []}
    snapshots = []

    def execute(action, params, timeout):
        # 동작 콜백 안에서 디스크를 다시 읽어 현재 단계가 아직 저장되지 않았음을 확인한다.
        snapshots.append(reader.read_run(run_id))
        return ActionResult(not (fail_second and params["text"] == "second"),
                            error_code="PROBE_FAILURE" if fail_second and params["text"] == "second" else None)

    task = {"task_id": "timing_probe", "sequence": [
        {"id": "s1", "action": "speak", "params": {"text": "first"}},
        {"id": "s2", "action": "speak", "params": {"text": "second"}},
    ]}
    result = Runner(execute, log_store=writer).run(
        task, inputs={"semantic": semantic}, meta={"parent_run_id": "timing_probe"}, run_id=run_id)
    assert len(snapshots) == 2
    for snapshot in snapshots:
        assert snapshot["run"]["parent_run_id"] == "timing_probe"
        assert snapshot["run"]["inputs"]["semantic"] == semantic
        assert "ended_at" not in snapshot["run"] and "overall_status" not in snapshot["run"]
    assert snapshots[0]["steps"] == []
    assert [(s["id"], s["status"]) for s in snapshots[1]["steps"]] == [("s1", "SUCCESS")]
    final = reader.read_run(run_id)
    assert final["run"]["ended_at"]
    assert final["run"]["overall_status"] == result.overall_status == ("FAILED" if fail_second else "COMPLETED")
    assert [(s["id"], s["status"]) for s in final["steps"]] == [
        ("s1", "SUCCESS"), ("s2", "FAILURE" if fail_second else "SUCCESS")]
    assert not result.log_errors
