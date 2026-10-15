"""Runner 저장소를 수정하거나 인덱스를 생성하지 않는 실행 단건 조회."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re


def checked_run_id(value):
    """ID를 파일 경로나 Mongo 연산자로 해석하지 않도록 제한한다."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_:.\-]{1,160}", value) or value in (".", ".."):
        raise ValueError("invalid run id")
    return value


class JsonlExecutionReader:
    """설정된 디렉터리의 해당 run 파일만 읽으며 디렉터리 검색은 하지 않는다."""

    def __init__(self, directory):
        self.directory = Path(directory).resolve()

    def read_run(self, run_id):
        """마지막 runs 문서와 기록된 steps를 반환한다. 손상된 줄은 성공으로 숨기지 않는다."""
        filename = checked_run_id(run_id).replace(":", "-") + ".jsonl"
        path = (self.directory / filename).resolve()
        if path.parent != self.directory:
            raise ValueError("record path escaped")
        run, steps = None, []
        if not path.exists():
            return {"run": None, "steps": []}
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                entry = json.loads(line)
                doc = entry.get("doc")
                if not isinstance(doc, dict) or doc.get("run_id") != run_id:
                    raise ValueError("record identity mismatch")
                if entry.get("collection") == "runs":
                    run = doc
                elif entry.get("collection") == "steps":
                    steps.append(doc)
        return {"run": run, "steps": steps}

    def close(self):
        """파일은 각 조회의 context manager에서 닫는다."""


class MongoExecutionReader:
    """Mongo runs/steps에 find만 수행한다. 운영 계정도 읽기 전용 권한을 사용한다."""

    def __init__(self, uri, database, timeout_ms):
        from pymongo import MongoClient
        self.client = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms,
                                  connectTimeoutMS=timeout_ms, socketTimeoutMS=timeout_ms)
        self.db = self.client[database]

    def read_run(self, run_id):
        """정확한 run_id로만 조회하며 child도 상위 기록의 명시적 참조로만 조회한다."""
        checked_run_id(run_id)
        return {"run": self.db.runs.find_one({"run_id": run_id}, {"_id": 0}),
                "steps": list(self.db.steps.find({"run_id": run_id}, {"_id": 0}))}

    def close(self):
        """웹 프로세스 종료 시 연결 풀을 정리한다."""
        self.client.close()


def reader_from_env():
    """명시적으로 설정한 저장소 하나만 사용한다. 서로 다른 DB/폴백 기록을 합치지 않는다."""
    directory = os.environ.get("WEB_RUN_JSONL_DIR")
    uri = os.environ.get("WEB_RUN_MONGO_URI")
    if directory and uri:
        raise ValueError("choose one execution store")
    if directory:
        return JsonlExecutionReader(directory)
    if uri:
        # 접속 대상/제한 시간은 운영자가 명시한다. Runner 설정이나 인증정보를 추정하지 않는다.
        database = os.environ["WEB_RUN_MONGO_DB"]
        timeout = int(os.environ["WEB_RUN_MONGO_TIMEOUT_MS"])
        if not database.strip() or timeout <= 0:
            raise ValueError("invalid execution store configuration")
        return MongoExecutionReader(uri, database, timeout)
    return None
