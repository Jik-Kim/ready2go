import json
import uuid

import pytest

from ready2go_runner.core.log_records import run_document, step_document
from ready2go_runner.core.logstore import FallbackLogStore, JsonlLogStore, LogStore, MemoryLogStore, MongoLogStore

# LogStore 약속을 지켜야 하는 저장소들. 단계마다 여기에 추가한다 (JSONL·MongoDB·폴백).
STORES = {
    "memory": lambda tmp_path: MemoryLogStore(),
    "jsonl": lambda tmp_path: JsonlLogStore(tmp_path / "logs"),
    "mongo": None,                        # 실제 DB 필요 → mongo_store() 에서 만들고 없으면 건너뜀
    "fallback": lambda tmp_path: FallbackLogStore(MemoryLogStore(), JsonlLogStore(tmp_path / "logs")),
}


def mongo_store(request):
    """실제 MongoDB 에 테스트 전용 DB 를 만들고, 끝나면 지운다. pymongo·DB 가 없으면(호스트·CI) 건너뜀."""
    pytest.importorskip("pymongo")
    store = MongoLogStore(db_name=f"cobot2_test_{uuid.uuid4().hex[:8]}", timeout_ms=500)
    try:
        store.ping()
    except Exception:
        pytest.skip("MongoDB 에 연결할 수 없음 (ros2-core 컨테이너에서 실행: docs 참고)")
    request.addfinalizer(lambda: store.client.drop_database(store.db.name))
    return store


@pytest.fixture(params=list(STORES))
def store(request, tmp_path):
    if request.param == "mongo":
        return mongo_store(request)
    return STORES[request.param](tmp_path)


def sample_run(run_id="r1"):
    start = run_document(run_id, "find_visible", {"target": "watch", "stt_text": "시계 찾아줘"},
                         "2026-10-03T05:40:12.345Z")
    steps = [step_document(run_id, 0, {"id": "s1", "action": "drawer_control", "status": "SUCCESS"}),
             step_document(run_id, 1, {"id": "s2", "action": "pick_object", "status": "FAILURE",
                                       "error_code": "GRASP_FAILED"}),
             step_document(run_id, 2, {"id": "f1", "action": "move_to_named_pose", "status": "SUCCESS"})]
    end = run_document(run_id, "find_visible", {"target": "watch", "stt_text": "시계 찾아줘"},
                       "2026-10-03T05:40:12.345Z", ended_at="2026-10-03T05:41:00.000Z",
                       total_duration_sec=47.7, overall_status="FAILED", error_code="GRASP_FAILED",
                       failed_step="s2")
    return start, steps, end


def test_store_follows_logstore_protocol(store):
    assert isinstance(store, LogStore)


def test_full_run_roundtrip(store):
    start, steps, end = sample_run()
    store.start_run(start)
    for s in steps:
        store.write_step(s)
    store.end_run(end)

    saved = store.read_run("r1")
    assert saved["run"] == end                                            # 시작 기록이 끝 기록으로 완성됨
    assert [s["id"] for s in saved["steps"]] == ["s1", "s2", "f1"]
    assert saved["steps"][1]["error"] == {"code": "GRASP_FAILED"}


def test_run_in_progress_is_readable(store):
    # 실행 도중(끝나기 전)에도 지금까지의 기록을 읽을 수 있음 — 중간에 멈춰도 기록이 남음
    start, steps, _ = sample_run()
    store.start_run(start)
    store.write_step(steps[0])
    saved = store.read_run("r1")
    assert saved["run"] == start and "overall_status" not in saved["run"]
    assert [s["id"] for s in saved["steps"]] == ["s1"]


def test_steps_are_read_in_seq_order(store):
    start, steps, end = sample_run()
    store.start_run(start)
    for s in reversed(steps):                                             # 순서가 섞여 들어와도
        store.write_step(s)
    assert [s["seq"] for s in store.read_run("r1")["steps"]] == [0, 1, 2]


def test_runs_are_separated(store):
    for run_id in ("r1", "r2"):
        start, steps, end = sample_run(run_id)
        store.start_run(start)
        store.write_step(steps[0])
        store.end_run(end)
    assert len(store.read_run("r1")["steps"]) == 1
    assert store.read_run("r2")["run"]["run_id"] == "r2"


def test_unknown_run(store):
    assert store.read_run("nope") == {"run": None, "steps": []}


def test_store_does_not_change_callers_record(store):
    start, steps, _ = sample_run()
    original = dict(steps[0])
    store.start_run(start)
    store.write_step(steps[0])
    assert steps[0] == original                                           # MongoDB 의 _id 같은 것이 붙지 않음
    saved = store.read_run("r1")["steps"][0]
    saved["status"] = "CHANGED"                                           # 읽은 값을 고쳐도 저장본은 그대로
    assert store.read_run("r1")["steps"][0]["status"] == "SUCCESS"


# ---- JSONL 전용 ----

def test_jsonl_file_layout(tmp_path):
    store = JsonlLogStore(tmp_path / "logs")                                # 폴더가 없어도 만든다
    start, steps, end = sample_run("2026-10-03T05:40:12Z_a1b2c3")
    store.start_run(start)
    store.write_step(steps[0])
    store.end_run(end)

    files = list((tmp_path / "logs").iterdir())
    assert [f.name for f in files] == ["2026-10-03T05-40-12Z_a1b2c3.jsonl"]   # ':' → '-'
    lines = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    assert [line["collection"] for line in lines] == ["runs", "steps", "runs"]
    assert lines[1]["doc"] == steps[0]                                    # doc 은 MongoDB 레코드와 같은 모양
    assert "시계 찾아줘" in files[0].read_text(encoding="utf-8")           # 한글이 그대로 보임


def test_jsonl_skips_truncated_last_line(tmp_path):
    store = JsonlLogStore(tmp_path)
    start, steps, _ = sample_run()
    store.start_run(start)
    store.write_step(steps[0])
    with open(tmp_path / "r1.jsonl", "a", encoding="utf-8") as f:
        f.write('{"collection": "steps", "doc": {"run_id": "r1", "se')      # 쓰다 만 줄 (전원 차단)
    saved = store.read_run("r1")
    assert saved["run"] == start and [s["id"] for s in saved["steps"]] == ["s1"]


def test_jsonl_append_after_truncated_line(tmp_path):
    # 쓰다 만 줄 뒤에 이어서 기록해도 새 기록은 살아 있어야 함
    store = JsonlLogStore(tmp_path)
    start, steps, end = sample_run()
    store.start_run(start)
    with open(tmp_path / "r1.jsonl", "a", encoding="utf-8") as f:
        f.write('{"collection": "steps", "doc": {"run_id": "r1", "se')
    store.write_step(steps[1])
    store.end_run(end)
    saved = store.read_run("r1")
    assert [s["id"] for s in saved["steps"]] == ["s2"] and saved["run"] == end


# ---- MongoDB 전용 ----

def test_mongo_unreachable_fails_fast():
    # DB 가 없을 때 30초(기본값)가 아니라 짧게 실패해야 폴백이 로봇을 멈추지 않음
    pytest.importorskip("pymongo")
    import time
    store = MongoLogStore(uri="mongodb://127.0.0.1:1", timeout_ms=300)   # 아무도 안 듣는 포트
    start, _, _ = sample_run()
    t0 = time.monotonic()
    with pytest.raises(Exception):
        store.start_run(start)
    assert time.monotonic() - t0 < 3


# ---- 폴백 (DB 장애) ----

class FlakyStore(MemoryLogStore):
    """주 저장소 흉내. down=True 면 모든 쓰기가 실패하고, 호출 횟수를 센다."""

    def __init__(self, fail_after: int | None = None):
        super().__init__()
        self.down, self.calls, self.fail_after = False, 0, fail_after

    def _check(self):
        self.calls += 1
        if self.down or (self.fail_after is not None and self.calls > self.fail_after):
            raise ConnectionError("DB 연결 끊김")

    def start_run(self, d): self._check(); super().start_run(d)
    def write_step(self, d): self._check(); super().write_step(d)
    def end_run(self, d): self._check(); super().end_run(d)


def run_through(store, run_id="r1"):
    start, steps, end = sample_run(run_id)
    store.start_run(start)
    for s in steps:
        store.write_step(s)
    store.end_run(end)
    return start, steps, end


def test_fallback_uses_primary_when_healthy(tmp_path):
    primary, jsonl = FlakyStore(), JsonlLogStore(tmp_path)
    store = FallbackLogStore(primary, jsonl)
    _, _, end = run_through(store)
    assert primary.read_run("r1")["run"] == end and not store.degraded
    assert jsonl.read_run("r1") == {"run": None, "steps": []}            # 파일에는 안 씀


def test_fallback_when_db_down_from_start(tmp_path):
    primary, jsonl = FlakyStore(), JsonlLogStore(tmp_path)
    primary.down = True
    store = FallbackLogStore(primary, jsonl)
    _, steps, end = run_through(store)
    assert store.degraded and "ConnectionError" in store.last_error
    assert jsonl.read_run("r1") == {"run": end, "steps": steps}          # 같은 형식으로 전부 파일에
    assert primary.calls == 1                                            # 실패 후 같은 실행에서 DB 재시도 안 함


def test_fallback_from_start_writes_start_record_once(tmp_path):
    # PR #64 리뷰(P3): 처음부터 DB 가 꺼져 있으면 시작 기록이 JSONL 에 두 번 쓰였음
    primary, jsonl = FlakyStore(), JsonlLogStore(tmp_path)
    primary.down = True
    run_through(FallbackLogStore(primary, jsonl))
    lines = [json.loads(line) for line in (tmp_path / "r1.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [line["collection"] for line in lines].count("runs") == 2     # 시작 1 + 끝 1


def test_fallback_mid_run_keeps_whole_run_in_jsonl(tmp_path):
    primary, jsonl = FlakyStore(fail_after=2), JsonlLogStore(tmp_path)  # 시작·s1 까지 성공, s2 부터 실패
    store = FallbackLogStore(primary, jsonl)
    _, steps, end = run_through(store)
    assert jsonl.read_run("r1") == {"run": end, "steps": steps}          # 앞 기록도 다시 써서 한 파일에 전체
    assert store.read_run("r1") == {"run": end, "steps": steps}


def test_next_run_retries_primary(tmp_path):
    primary, jsonl = FlakyStore(), JsonlLogStore(tmp_path)
    store = FallbackLogStore(primary, jsonl)
    primary.down = True
    run_through(store, "r1")
    primary.down = False                                                 # DB 복구
    _, _, end2 = run_through(store, "r2")
    assert not store.degraded and store.last_error is None
    assert primary.read_run("r2")["run"] == end2
    assert jsonl.read_run("r2")["run"] is None


def test_fallback_failure_is_raised(tmp_path):
    class Broken(MemoryLogStore):
        def start_run(self, d): raise OSError("디스크 가득 참")

    primary = FlakyStore()
    primary.down = True
    store = FallbackLogStore(primary, Broken())
    with pytest.raises(OSError):                                          # 실행을 멈출지는 Runner 가 정함 (6단계)
        store.start_run(sample_run()[0])


def test_fallback_with_unreachable_mongo_is_fast(tmp_path):
    # 실제 MongoLogStore 가 DB 에 못 붙을 때: 실행 1건이 몇 초 안에 끝나고 전부 JSONL 에 남음
    pytest.importorskip("pymongo")
    import time
    store = FallbackLogStore(MongoLogStore(uri="mongodb://127.0.0.1:1", timeout_ms=300), JsonlLogStore(tmp_path))
    t0 = time.monotonic()
    _, steps, end = run_through(store)
    assert time.monotonic() - t0 < 3                                     # 스텝마다 기다리지 않음
    assert store.degraded
    assert JsonlLogStore(tmp_path).read_run("r1") == {"run": end, "steps": steps}
