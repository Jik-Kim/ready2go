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
        """Runner처럼 잘린 JSON 줄을 건너뛴다. 완전한 줄의 구조/식별자 오류는 거부한다."""
        # Runner의 파일명 규칙을 직접 재사용하되 디렉터리 생성/쓰기 초기화는 호출하지 않는다.
        from ready2go_runner.core.logstore import JsonlLogStore
        path = JsonlLogStore._path(self, checked_run_id(run_id)).resolve()
        if path.parent != self.directory:
            raise ValueError("record path escaped")
        run, steps = None, []
        if not path.exists():
            return {"run": None, "steps": []}
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    # Runner는 잘린 줄 뒤 개행하고 계속 쓰므로 이후 정상 종료 기록을 살린다.
                    continue
                if not isinstance(entry, dict):
                    raise ValueError("invalid JSONL entry")
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
        # 조회 shape/projection/seq 정렬은 C의 read_run을 공유한다. 쓰기/인덱스 메서드는 호출하지 않는다.
        from ready2go_runner.core.logstore import MongoLogStore
        return MongoLogStore.read_run(self, run_id)

    def close(self):
        """웹 프로세스 종료 시 연결 풀을 정리한다."""
        self.client.close()


class FallbackExecutionReader:
    """각 run마다 JSONL 우선, 없으면 Mongo 조회. 서로 다른 저장소의 단계는 합치지 않는다."""

    def __init__(self, primary, fallback):
        self.primary, self.fallback = primary, fallback

    def read_run(self, run_id):
        """Runner와 동일한 우선순위를 적용하되 DB 실패는 웹에서 503으로 진단한다."""
        saved = self.fallback.read_run(run_id)
        if saved["run"] is not None:
            return saved
        return self.primary.read_run(run_id)

    def close(self):
        """읽기 연결만 정리한다."""
        self.primary.close()
        self.fallback.close()


def reader_from_env():
    """두 저장소를 함께 설정하면 run별 JSONL 폴백 우선 조회를 활성화한다."""
    directory = os.environ.get("WEB_RUN_JSONL_DIR")
    uri = os.environ.get("WEB_RUN_MONGO_URI")
    fallback = JsonlExecutionReader(directory) if directory else None
    if uri:
        # 접속 대상/제한 시간은 운영자가 명시한다. 오류 메시지에 URI를 포함하지 않는다.
        database = os.environ["WEB_RUN_MONGO_DB"]
        timeout = int(os.environ["WEB_RUN_MONGO_TIMEOUT_MS"])
        if not database.strip() or timeout <= 0:
            raise ValueError("invalid execution store configuration")
        primary = MongoExecutionReader(uri, database, timeout)
        return FallbackExecutionReader(primary, fallback) if fallback else primary
    return fallback


def load_reader_for_startup(logger):
    """저장소 미설정은 정상 None, 오구성은 비밀값 없는 진단을 남기고 상태 서버를 유지한다."""
    try:
        return reader_from_env()
    except Exception as exc:
        # 외부 예외 메시지에는 URI/암호가 들어갈 수 있어 종류와 고정 점검 안내만 기록한다.
        logger.error("Execution reader configuration failed (%s); check WEB_RUN_* settings and Mongo dependencies",
                     type(exc).__name__)
        return None
