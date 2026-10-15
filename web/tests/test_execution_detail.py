"""기존 종료 기록 조회의 식별자·저장 시점·전달 판정을 검증한다."""
from copy import deepcopy
import json

import pytest

from ready2go_web.adapters.execution_reader import JsonlExecutionReader, reader_from_env
from ready2go_web.core.execution_detail import read_detail
from ready2go_web.core.state_cache import StateCache
from ready2go_web.server import create_app


class Records:
    """외부 DB 없이 실제 runs/steps 형식을 주입하는 읽기 전용 시험 저장소."""
    def __init__(self):
        self.rows = {
            "r1": {"run": {"run_id": "r1", "task_id": "group_test", "ended_at": "2026-10-15T00:00:00Z",
                "overall_status": "FAILED", "inputs": {"semantic": {"items": ["b", "a"],
                    "evidence": {"a": {"class_paths": [["Key", "Valuables"]]}}}},
                "items": [{"item": "a", "run_id": "child", "status": "DELIVERED"},
                          {"item": "b", "run_id": None, "status": "NOT_RUN"},
                          {"item": "c", "run_id": None, "status": "EXCLUDED"}]}, "steps": []},
            "child": {"run": {"run_id": "child", "parent_run_id": "r1"}, "steps": [
                {"run_id": "child", "seq": 0, "id": "s1", "status": "SUCCESS", "result": {"verified": True}}]},
        }

    def read_run(self, run_id):
        """호출자가 저장소 원본을 변경할 수 없도록 복사본을 반환한다."""
        return deepcopy(self.rows.get(run_id, {"run": None, "steps": []}))


def test_recorded_order_evidence_and_delivery_are_not_inferred():
    """semantic 순서와 종료 items 순서가 달라도 C 종료 기록만 사용한다."""
    reader = Records()
    detail = read_detail(reader, "r1", "group_test", "FAILED")
    assert [row["id"] for row in detail["items"]] == ["a", "b", "c"]
    assert detail["delivery"] == {"completed": 1, "total": 2}
    assert detail["items"][0]["evidence"] == {"class_paths": [["Key", "Valuables"]]}
    assert detail["items"][1]["steps"] == []
    assert detail["location"] is None and detail["destination"] is None
    # 단계 성공이 있어도 전달 결과가 NOT_DELIVERED면 전달 완료로 올리지 않는다.
    reader.rows["r1"]["run"]["items"][0]["status"] = "NOT_DELIVERED"
    assert read_detail(reader, "r1", "group_test", "FAILED")["delivery"]["completed"] == 0


def test_start_record_does_not_claim_final_order():
    """시작 semantic만 있는 동안에는 완료 상세를 반환하지 않는다."""
    reader = Records()
    del reader.rows["r1"]["run"]["ended_at"]
    assert read_detail(reader, "r1", "group_test", "FAILED") is None


@pytest.mark.parametrize("fault", ["parent", "step_run", "duplicate_seq", "status"])
def test_malformed_or_other_run_records_fail_closed(fault):
    """다른 parent/단계 run, 중복 순서, 알 수 없는 결과는 전체 상세 오류다."""
    reader = Records()
    child = reader.rows["child"]
    if fault == "parent":
        child["run"]["parent_run_id"] = "other"
    elif fault == "step_run":
        child["steps"][0]["run_id"] = "other"
    elif fault == "duplicate_seq":
        child["steps"].append(deepcopy(child["steps"][0]))
    else:
        child["steps"][0]["status"] = "invented"
    with pytest.raises(ValueError):
        read_detail(reader, "r1", "group_test", "FAILED")


def cache_and_payload():
    """요청과 종료 결과의 run/task가 일치하는 현재 기동 캐시다."""
    cache = StateCache({"runner": None})
    payload = {"boot_id": "boot", "seq": 1,
               "last_intent": {"decision": "run", "run_id": "r1", "task_id": "group_test"},
               "last": {"run_id": "r1", "task_id": "group_test", "overall_status": "FAILED"}}
    cache.record_message("runner", payload)
    return cache, payload


def test_api_checks_before_and_after_storage_read():
    """읽기 중 재기동하면 정상 DB 응답이어도 409로 폐기한다."""
    cache, payload = cache_and_payload()
    reader = Records()
    client = create_app(state_cache=cache, execution_reader=reader).test_client()
    response = client.get("/api/execution-detail/r1?boot_id=boot&seq=1")
    assert response.status_code == 200
    assert response.json["identity"] == {"bootId": "boot", "runId": "r1"}
    assert response.headers["Cache-Control"] == "no-store"
    assert client.get("/api/execution-detail/r1?boot_id=old&seq=1").status_code == 409
    assert client.get("/api/execution-detail/other?boot_id=boot&seq=1").status_code == 409
    original = reader.read_run

    def reboot(run_id):
        """외부 읽기 대기 도중 Runner 기동 교체를 재현한다."""
        cache.record_message("runner", {**payload, "boot_id": "new"})
        return original(run_id)

    reader.read_run = reboot
    assert client.get("/api/execution-detail/r1?boot_id=boot&seq=1").status_code == 409


def test_jsonl_exact_run_only_and_invalid_lines(tmp_path):
    """단건 파일의 마지막 runs와 steps만 읽고 경로 탈출·손상·타 run을 거부한다."""
    reader = JsonlExecutionReader(tmp_path)
    path = tmp_path / "r1.jsonl"
    path.write_text(json.dumps({"collection": "runs", "doc": {"run_id": "r1"}}) + "\n")
    assert reader.read_run("r1")["run"] == {"run_id": "r1"}
    assert reader.read_run("missing")["run"] is None
    with pytest.raises(ValueError):
        reader.read_run("../secret")
    path.write_text('{"collection":')
    assert reader.read_run("r1")["run"] is None
    path.write_text('[]\n')
    with pytest.raises(ValueError):
        reader.read_run("r1")


def test_storage_is_opt_in(monkeypatch):
    """기존 상태 서버는 저장소 미설정 시에도 사용할 수 있다."""
    for key in ("WEB_RUN_JSONL_DIR", "WEB_RUN_MONGO_URI"):
        monkeypatch.delenv(key, raising=False)
    assert reader_from_env() is None
    assert create_app().test_client().get("/api/execution-detail/r1?boot_id=b&seq=1").status_code == 503


def test_mongo_adapter_only_reads_exact_run(monkeypatch):
    """Mongo 호출은 정확한 run 조건과 _id 제외 projection의 find뿐이다."""
    import sys
    from types import SimpleNamespace
    from ready2go_web.adapters.execution_reader import MongoExecutionReader
    calls = []

    class Cursor(list):
        def sort(self, key, direction):
            """Runner 공통 조회의 seq 정렬 호출을 지원한다."""
            return self

    class Collection:
        def find_one(self, query, projection):
            """runs 단건 조회 조건을 기록한다."""
            calls.append(("find_one", query, projection))
            return {"run_id": "r1"}

        def find(self, query, projection):
            """steps 조회 조건을 기록한다. 쓰기 메서드는 제공하지 않는다."""
            calls.append(("find", query, projection))
            return Cursor()

    class Client:
        def __init__(self, *args, **kwargs):
            """외부 네트워크 없이 Mongo client 표면만 제공한다."""

        def __getitem__(self, database):
            return SimpleNamespace(runs=Collection(), steps=Collection())

        def close(self):
            calls.append("closed")

    monkeypatch.setitem(sys.modules, "pymongo", SimpleNamespace(MongoClient=Client))
    reader = MongoExecutionReader("mongodb://example", "records", 1000)
    assert reader.read_run("r1")["run"] == {"run_id": "r1"}
    reader.close()
    assert calls == [("find_one", {"run_id": "r1"}, {"_id": 0}),
                     ("find", {"run_id": "r1"}, {"_id": 0}), "closed"]


def test_store_exception_is_not_exposed_to_browser():
    """DB 실패 시 이전 결과나 URI가 노출되지 않고 상세만 unavailable이 된다."""
    cache, _ = cache_and_payload()

    class FailedReader:
        def read_run(self, run_id):
            raise RuntimeError("secret database address")

    response = create_app(state_cache=cache, execution_reader=FailedReader()).test_client().get(
        "/api/execution-detail/r1?boot_id=boot&seq=1")
    assert response.status_code == 503
    assert "secret" not in response.text


@pytest.mark.parametrize("fault", ["bundle", "child_list", "child_string", "segment_list", "segment_child"])
def test_malformed_child_and_segment_are_422(fault):
    """완전한 JSON의 구조 오류를 저장소 연결 실패로 오인하지 않는다."""
    reader = Records()
    if fault == "bundle":
        reader.rows["child"] = []
    elif fault in ("child_list", "child_string"):
        reader.rows["child"]["run"] = [] if fault == "child_list" else "bad"
    else:
        reader.rows["r1"]["run"]["items"] = []
        reader.rows["r1"]["run"]["segments"] = [[]] if fault == "segment_list" else [{"run_id": "child"}]
        reader.rows["child"]["run"] = []
    cache, _ = cache_and_payload()
    response = create_app(state_cache=cache, execution_reader=reader).test_client().get(
        "/api/execution-detail/r1?boot_id=boot&seq=1")
    assert response.status_code == 422 and response.json["status"] == "invalid_record"


@pytest.mark.parametrize("seq", ["abc", "1.0", "-1", "", "9007199254740992"])
def test_bad_query_is_400(seq):
    """잘못된 요청은 기록을 읽기 전에 클라이언트 오류로 반환한다."""
    cache, _ = cache_and_payload()
    response = create_app(state_cache=cache, execution_reader=Records()).test_client().get(
        f"/api/execution-detail/r1?boot_id=boot&seq={seq}")
    assert response.status_code == 400 and response.json["status"] == "invalid_request"


def test_fallback_priority_and_split_children(tmp_path):
    """부모는 primary, child는 JSONL인 실행과 오래된 primary를 가리는 fallback을 확인한다."""
    from ready2go_runner.core.logstore import JsonlLogStore
    from ready2go_web.adapters.execution_reader import FallbackExecutionReader
    primary = Records()
    child = primary.rows.pop("child")
    writer = JsonlLogStore(tmp_path)
    writer.start_run(child["run"])
    for step in child["steps"]:
        writer.write_step(step)
    # C의 실제 writer가 만든 파일과 D reader의 파일명/기록 처리가 일치한다.
    reader = FallbackExecutionReader(primary, JsonlExecutionReader(tmp_path))
    assert read_detail(reader, "r1", "group_test", "FAILED")["items"][0]["steps"]
    parent = deepcopy(primary.rows["r1"]["run"])
    parent["items"][0]["status"] = "NOT_DELIVERED"
    writer.end_run(parent)
    assert read_detail(reader, "r1", "group_test", "FAILED")["delivery"]["completed"] == 0


def test_truncated_jsonl_between_valid_records(tmp_path):
    """잘린 줄 뒤 C writer가 덧쓴 정상 종료 기록을 D에서도 읽는다."""
    from ready2go_runner.core.logstore import JsonlLogStore
    writer = JsonlLogStore(tmp_path)
    run_id = "2026-10-15T00:00:00Z_test"
    writer.start_run({"run_id": run_id})
    with writer._path(run_id).open("a") as stream:
        stream.write('{"collection":')
    writer.end_run({"run_id": run_id, "overall_status": "COMPLETED"})
    reader = JsonlExecutionReader(tmp_path)
    assert reader.read_run(run_id) == writer.read_run(run_id)


def test_configuration_failure_logs_without_secret(monkeypatch, caplog):
    """미설정은 조용히 유지하고 예외는 종류/점검 안내만 남겨 URI를 노출하지 않는다."""
    import logging
    from ready2go_web.adapters import execution_reader as module
    # 다른 서버 시험의 전역 logging 설정과 무관하게 이 진단만 수집한다.
    logger = logging.Logger("reader-test")
    logger.addHandler(caplog.handler)
    monkeypatch.setattr(module, "reader_from_env", lambda: None)
    assert module.load_reader_for_startup(logger) is None
    assert not caplog.records

    def fail():
        raise ValueError("mongodb://user:secret@host")

    monkeypatch.setattr(module, "reader_from_env", fail)
    assert module.load_reader_for_startup(logger) is None
    assert "ValueError" in caplog.text and "WEB_RUN_" in caplog.text
    assert "secret" not in caplog.text and "mongodb://" not in caplog.text


def test_environment_enables_both_readers(monkeypatch, tmp_path):
    """두 설정을 함께 주면 선택 충돌 없이 run별 폴백 reader를 구성한다."""
    from ready2go_web.adapters import execution_reader as module
    primary = object()
    monkeypatch.setattr(module, "MongoExecutionReader", lambda *args: primary)
    monkeypatch.setenv("WEB_RUN_JSONL_DIR", str(tmp_path))
    monkeypatch.setenv("WEB_RUN_MONGO_URI", "mongodb://test")
    monkeypatch.setenv("WEB_RUN_MONGO_DB", "test")
    monkeypatch.setenv("WEB_RUN_MONGO_TIMEOUT_MS", "100")
    reader = module.reader_from_env()
    assert isinstance(reader, module.FallbackExecutionReader)
    assert reader.primary is primary
    assert reader.fallback.directory == tmp_path.resolve()
