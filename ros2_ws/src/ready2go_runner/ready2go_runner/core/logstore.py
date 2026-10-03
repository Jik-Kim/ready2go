"""실행 로그 저장 — docs/runner.md 7.4.

P1부터 MongoDB 실행 이력(FR-LOG-01, NFR-DB-01): MongoLogStore 가 cobot2 DB 의 runs·steps 에 저장하고,
DB 연결 실패 시 같은 형식의 레코드를 JsonlLogStore 로 남긴다 (로봇 동작은 멈추지 않음).

LogStore 약속: start_run(run_doc) → write_step(step_doc) × N → end_run(run_doc), read_run(run_id).
레코드 모양은 log_records.py 가 만든다. 저장 실패는 예외로 알리고, 폴백 여부는 호출하는 쪽이 정한다.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Protocol, runtime_checkable


def _ends_with_newline(path: Path) -> bool:
    with open(path, "rb") as f:
        f.seek(-1, 2)
        return f.read(1) == b"\n"


@runtime_checkable
class LogStore(Protocol):
    def start_run(self, run_doc: dict) -> None: ...

    def write_step(self, step_doc: dict) -> None: ...

    def end_run(self, run_doc: dict) -> None: ...

    def read_run(self, run_id: str) -> dict:
        """{"run": runs 레코드 또는 None, "steps": seq 순서의 steps 레코드 목록}"""
        ...


class MemoryLogStore:
    """메모리 저장소. LogStore 약속의 기준 구현이자 Runner 테스트용."""

    def __init__(self):
        self.runs: dict[str, dict] = {}
        self.steps: list[dict] = []

    def start_run(self, run_doc: dict) -> None:
        self.runs[run_doc["run_id"]] = copy.deepcopy(run_doc)

    def write_step(self, step_doc: dict) -> None:
        self.steps.append(copy.deepcopy(step_doc))

    def end_run(self, run_doc: dict) -> None:
        self.runs[run_doc["run_id"]] = copy.deepcopy(run_doc)

    def read_run(self, run_id: str) -> dict:
        steps = sorted((s for s in self.steps if s["run_id"] == run_id), key=lambda s: s["seq"])
        return {"run": copy.deepcopy(self.runs.get(run_id)), "steps": copy.deepcopy(steps)}


class JsonlLogStore:
    """JSONL 파일 저장소 (DB 장애 시 폴백). 실행 1건 = 파일 1개, 한 줄 = {"collection", "doc"}.
    doc 은 MongoDB 에 넣는 레코드와 같다. 덧붙이기만 하므로 실행 끝 기록은 마지막 runs 줄이 최신."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        return self.directory / f"{run_id.replace(':', '-')}.jsonl"   # ':' 는 일부 도구·OS 에서 문제

    def _append(self, collection: str, doc: dict) -> None:
        line = json.dumps({"collection": collection, "doc": doc}, ensure_ascii=False)
        path = self._path(doc["run_id"])
        with open(path, "ab") as f:
            if f.tell() > 0 and not _ends_with_newline(path):   # 쓰다 만 줄 뒤에 붙지 않도록 줄을 바꾼다
                f.write(b"\n")
            f.write((line + "\n").encode("utf-8"))

    def start_run(self, run_doc: dict) -> None:
        self._append("runs", run_doc)

    def write_step(self, step_doc: dict) -> None:
        self._append("steps", step_doc)

    def end_run(self, run_doc: dict) -> None:
        self._append("runs", run_doc)

    def read_run(self, run_id: str) -> dict:
        run, steps = None, []
        path = self._path(run_id)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:            # 쓰다 만 줄(전원 차단 등)은 건너뛰고 앞 기록은 살림
                    continue
                if entry.get("collection") == "runs":
                    run = entry["doc"]
                elif entry.get("collection") == "steps":
                    steps.append(entry["doc"])
        return {"run": run, "steps": sorted(steps, key=lambda s: s["seq"])}


DEFAULT_MONGO_URI = "mongodb://localhost:27017"   # compose 의 db 는 network_mode: host
DEFAULT_DB_NAME = "cobot2"                        # docs/interfaces.md
MONGO_TIMEOUT_MS = 1000   # 연결·응답 제한. 기본 30초면 DB 장애 때 로봇이 그만큼 멈춤 [추정, 실측 후 조정]


class MongoLogStore:
    """MongoDB 저장소 (cobot2.runs·steps). runs 는 run_id 로 덮어써 시작 기록을 끝 기록으로 완성한다.
    읽을 때 MongoDB 의 _id 는 빼서 JSONL 과 같은 모양으로 돌려준다."""

    def __init__(self, uri: str | None = None, db_name: str = DEFAULT_DB_NAME,
                 timeout_ms: int = MONGO_TIMEOUT_MS):
        from pymongo import MongoClient   # pymongo 는 ros2-core 이미지에만 있음 (호스트·CI 는 없이도 import 가능)

        self.client = MongoClient(uri or os.environ.get("MONGO_URI", DEFAULT_MONGO_URI),
                                  serverSelectionTimeoutMS=timeout_ms, connectTimeoutMS=timeout_ms,
                                  socketTimeoutMS=timeout_ms)
        self.db = self.client[db_name]
        self._indexed = False

    def _ensure_indexes(self) -> None:
        if not self._indexed:
            self.db.runs.create_index("run_id", unique=True)
            self.db.steps.create_index([("run_id", 1), ("seq", 1)])
            self._indexed = True

    def ping(self) -> None:
        """연결 확인. 실패하면 pymongo 예외 (폴백 판단용)."""
        self.client.admin.command("ping")

    def start_run(self, run_doc: dict) -> None:
        self._ensure_indexes()
        self.db.runs.replace_one({"run_id": run_doc["run_id"]}, copy.deepcopy(run_doc), upsert=True)

    def write_step(self, step_doc: dict) -> None:
        self._ensure_indexes()
        self.db.steps.insert_one(copy.deepcopy(step_doc))     # insert_one 이 넘긴 dict 에 _id 를 붙이므로 복사본

    def end_run(self, run_doc: dict) -> None:
        self.start_run(run_doc)

    def read_run(self, run_id: str) -> dict:
        run = self.db.runs.find_one({"run_id": run_id}, {"_id": 0})
        steps = list(self.db.steps.find({"run_id": run_id}, {"_id": 0}).sort("seq", 1))
        return {"run": run, "steps": steps}


class FallbackLogStore:
    """주 저장소(MongoDB)가 실패하면 예비 저장소(JSONL)로 같은 레코드를 남긴다 (FR-LOG-01, NFR-DB-01).

    - 실행 도중 주 저장소가 실패하면 그때까지 쓴 시작 기록·스텝을 예비 저장소에 다시 써서
      한 실행의 기록이 둘로 갈라지지 않게 한다.
    - 한 번 실패한 실행은 끝날 때까지 예비 저장소만 쓴다 (스텝마다 연결 제한만큼 멈추지 않게).
    - 다음 실행이 시작될 때 주 저장소를 다시 시도한다.
    - 예비 저장소까지 실패하면 예외를 올린다 (Runner 가 실행을 멈추지 않도록 감쌈).
    """

    def __init__(self, primary: LogStore, fallback: LogStore):
        self.primary, self.fallback = primary, fallback
        self.degraded = False                  # 지금 실행을 예비 저장소에 쓰는 중인지 (/runner/status 표시용)
        self.last_error: str | None = None
        self._run_start: dict | None = None    # 실행 도중 전환 시 예비 저장소에 다시 쓸 기록
        self._run_steps: list[dict] = []

    def _switch(self, error: Exception) -> None:
        self.degraded = True
        self.last_error = f"{type(error).__name__}: {error}"
        if self._run_start is not None:
            self.fallback.start_run(self._run_start)
        for step in self._run_steps:
            self.fallback.write_step(step)

    def _write(self, method: str, doc: dict) -> None:
        if not self.degraded:
            try:
                getattr(self.primary, method)(doc)
                return
            except Exception as e:             # DB 연결 끊김·시간 초과 등
                self._switch(e)
        getattr(self.fallback, method)(doc)

    def start_run(self, run_doc: dict) -> None:
        self.degraded, self.last_error = False, None   # 새 실행은 주 저장소부터 다시 시도
        self._run_start, self._run_steps = copy.deepcopy(run_doc), []
        self._write("start_run", run_doc)

    def write_step(self, step_doc: dict) -> None:
        self._write("write_step", step_doc)
        if not self.degraded:
            self._run_steps.append(copy.deepcopy(step_doc))

    def end_run(self, run_doc: dict) -> None:
        self._write("end_run", run_doc)
        self._run_start, self._run_steps = None, []

    def read_run(self, run_id: str) -> dict:
        saved = self.fallback.read_run(run_id)          # 폴백된 실행은 예비 저장소에 전체가 있음
        if saved["run"] is not None:
            return saved
        try:
            return self.primary.read_run(run_id)
        except Exception:
            return saved
