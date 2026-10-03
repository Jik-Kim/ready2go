"""실행 로그 저장 — docs/runner.md 7.4.

Phase 1: JSONL 파일(LogStore 인터페이스). Phase 2: MongoDB 구현(MongoLogStore)을 같은 인터페이스로 추가하고,
DB 연결 실패 시 JSONL로 자동 폴백.

LogStore 약속: start_run(run_doc) → write_step(step_doc) × N → end_run(run_doc), read_run(run_id).
레코드 모양은 log_records.py 가 만든다. 저장 실패는 예외로 알리고, 폴백 여부는 호출하는 쪽이 정한다.
"""
from __future__ import annotations

import copy
import json
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
