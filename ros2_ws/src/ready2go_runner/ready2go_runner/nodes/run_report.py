"""실행 기록 보고서 명령 (ROS 없이 동작, 읽기 전용) — MongoDB 또는 JSONL 의 실행 기록을 한국어 요약으로.

  ros2 run ready2go_runner run_report                     # 가장 최근 실행 1건 (MONGO_URI, 기본 localhost)
  ros2 run ready2go_runner run_report -n 3                # 최근 3건
  ros2 run ready2go_runner run_report --run f45c86        # run_id 가 이 글자로 끝나는 실행
  ros2 run ready2go_runner run_report --markdown          # GitHub 댓글용 표
  ros2 run ready2go_runner run_report --uri mongodb://172.24.0.3:27017   # 다른 PC(PC2) DB
  ros2 run ready2go_runner run_report --jsonl /logs       # DB 장애 때 남은 JSONL 예비 기록
  ros2 run ready2go_runner run_report -n 20 --check       # 최근 20건 기록이 빠짐없는지 (FR-LOG-02·AC-LOG-01), 누락 있으면 종료 코드 1
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ..core.logstore import DEFAULT_DB_NAME, DEFAULT_MONGO_URI, JsonlLogStore
from ..core.run_report import check, check_line, to_markdown, to_text


def jsonl_run_ids(directory: Path) -> list[str]:
    """JSONL 파일 이름(run_id 의 ':' → '-')에서 run_id 를 되살린다. 이름이 시각으로 시작해 정렬 = 시간 순."""
    ids = []
    for path in sorted(directory.glob("*.jsonl")):
        stem = path.stem
        date, _, rest = stem.partition("T")
        ids.append(f"{date}T{rest[:8].replace('-', ':')}{rest[8:]}" if rest else stem)
    return ids


def pick(run_ids: list[str], run: str | None, last: int) -> list[str]:
    if run:
        return [r for r in run_ids if r.endswith(run) or r == run][-1:]
    return run_ids[-last:] if last > 0 else []


def load_mongo(uri: str, run: str | None, last: int) -> list[dict]:
    from pymongo import MongoClient   # ros2-core 이미지에 있음

    db = MongoClient(uri, serverSelectionTimeoutMS=3000)[DEFAULT_DB_NAME]
    ids = [r["run_id"] for r in db.runs.find({}, {"_id": 0, "run_id": 1}).sort("started_at", 1)]
    records = []
    for run_id in pick(ids, run, last):
        records.append({"run": db.runs.find_one({"run_id": run_id}, {"_id": 0}),
                        "steps": list(db.steps.find({"run_id": run_id}, {"_id": 0}).sort("seq", 1))})
    return records


def load_jsonl(directory: Path, run: str | None, last: int) -> list[dict]:
    store = JsonlLogStore(directory)
    return [store.read_run(run_id) for run_id in pick(jsonl_run_ids(directory), run, last)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="실행 기록을 사람이 읽는 요약으로 (읽기 전용)")
    ap.add_argument("--uri", default=os.environ.get("MONGO_URI", DEFAULT_MONGO_URI), help="MongoDB 주소")
    ap.add_argument("--jsonl", type=Path, help="MongoDB 대신 이 폴더의 JSONL 예비 기록을 읽음")
    ap.add_argument("--run", help="run_id (끝 글자만 써도 됨, 예: f45c86)")
    ap.add_argument("-n", "--last", type=int, default=1, help="최근 몇 건 (기본 1)")
    ap.add_argument("--markdown", action="store_true", help="GitHub 댓글용 Markdown 표")
    ap.add_argument("--check", action="store_true", help="요약 대신 기록 누락 점검 (헤더·끝 기록·seq 빠짐/중복·결과 없는 스텝)")
    args, _ = ap.parse_known_args(argv)        # ros2 run 이 붙이는 --ros-args 무시
    try:
        records = (load_jsonl(args.jsonl, args.run, args.last) if args.jsonl
                   else load_mongo(args.uri, args.run, args.last))
    except Exception as e:                     # 연결 실패 등: 원인만 알리고 끝냄
        reason = str(e).split(" (configured")[0].split(", Timeout")[0][:200]   # pymongo 메시지는 길어서 앞부분만
        print(f"기록을 읽지 못함 ({args.jsonl or args.uri}): {type(e).__name__}: {reason}", file=sys.stderr)
        return 1
    if not records:
        print("해당 실행 기록 없음", file=sys.stderr)
        return 1
    if args.check:
        print("\n".join(check_line(r) for r in records))
        bad = sum(1 for r in records if check(r))
        print(f"\n{len(records)}건 중 누락 {bad}건")
        return 1 if bad else 0
    render = to_markdown if args.markdown else to_text
    print("\n\n".join(render(r) for r in records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
