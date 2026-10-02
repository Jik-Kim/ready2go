from ready2go_runner.core.logstore import JsonlLogStore


def test_jsonl_roundtrip(tmp_path):
    store = JsonlLogStore(tmp_path)
    store.write_step("run1", {"id": "s1", "status": "SUCCESS"})
    store.write_step("run1", {"id": "s2", "status": "FAILURE", "error": {"code": "GRASP_FAILED"}})
    steps = store.read_run("run1")
    assert [s["status"] for s in steps] == ["SUCCESS", "FAILURE"]
