"""실행 로그 저장 — docs/runner.md 7.4.

Phase 1: JSONL 파일(LogStore 인터페이스). Phase 2: MongoDB 구현(MongoLogStore)을 같은 인터페이스로 추가하고,
DB 연결 실패 시 JSONL로 자동 폴백.
"""
from __future__ import annotations

import json
from pathlib import Path


class JsonlLogStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def write_step(self, run_id: str, step: dict) -> None:
        with open(self.directory / f"{run_id}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(step, ensure_ascii=False) + "\n")

    def read_run(self, run_id: str) -> list[dict]:
        path = self.directory / f"{run_id}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
