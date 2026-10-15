#!/usr/bin/env python3
"""PC2 음성(호스트 install_host)과 Runner(도커, 지금 checkout) 의 C 코드 버전 맞춤 확인 — #384 E·C 합의 10/15.

E 음성은 C Runner 코드(`ready2go_runner.core.item_group` 안내 factory 등)를 호스트 빌드(install_host)에서 import 하고,
도커 Runner 는 기동 때 지금 checkout 을 빌드한다. 둘이 다른 시점이면 목록 안내가 E 에서 조용히 거절될 수 있음(#384 리뷰 ②,
구조화 안내 계약은 후속). 그래서 음성 노드를 띄우기 전에 확인:

1. 호스트에 설치된 Python 패키지 파일이 지금 저장소 소스와 같은가 (install_host 를 다시 빌드했나)
2. 떠 있는 Runner 의 기준점(pc2_up.sh 가 남긴 ready.txt 의 SHA)이 지금 checkout HEAD 와 같은가 (pc2_up 뒤에 git pull 안 했나) —
   커밋이 달라도 실행 파일(RUNTIME_PATHS, 그 안 Markdown 제외)이 그대로면(문서만 바뀜) 통과

한계: 1 은 Python 패키지 파일만 비교(설치된 share 데이터 — TTL·태스크 — 는 안 봄). 2 는 기동 때 기록(ready.txt)과 커밋 비교라
지금 살아 있는 Runner 프로세스·로드된 모듈을 직접 보지 않고, 커밋 안 한 수정을 pc2_up 뒤에 바꾼 경우는 못 잡음.

  python3 tools/dev/pc2_version_check.py [--ready <ready.txt>]     # install_host 를 source 한 셸에서
종료 코드 0 = 맞음, 1 = 다름(이유 출력), 2 = 확인 못 함.
"""
from __future__ import annotations

import argparse
import filecmp
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("ready2go_runner", "ready2go_knowledge", "ready2go_voice")   # 음성이 import 하는 팀 Python 패키지
RUNTIME_PATHS = ("ros2_ws/src", "tasks", "knowledge", "config", "contracts", "docker", "compose.yaml")  # Runner 기동·실행에 쓰는 것
NOT_RUNTIME = (":(exclude,glob)**/*.md",)   # 그 안이라도 실행에 안 쓰는 것 — 패키지 README 등 문서


def installed_dir(package: str) -> Path | None:
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))


def compare(src: Path, installed: Path) -> list[str]:
    """소스와 설치본의 .py 차이 — 바뀐 파일·설치 안 된 파일·소스에 없는 설치 파일 (상대 경로)."""
    if installed.resolve() == src.resolve():
        return []                                   # --symlink-install 이거나 소스를 직접 import — 항상 같음
    def files(base: Path) -> set[str]:
        return {str(p.relative_to(base)) for p in base.rglob("*.py") if "__pycache__" not in p.parts}
    a, b = files(src), files(installed)
    diff = [f"바뀜 {f}" for f in sorted(a & b) if not filecmp.cmp(src / f, installed / f, shallow=False)]
    diff += [f"설치 안 됨 {f}" for f in sorted(a - b)]
    diff += [f"소스에 없음 {f}" for f in sorted(b - a)]
    return diff


def runtime_changed(root: Path, sha: str) -> int:
    """sha → HEAD 사이 실행 파일 변화: 0 = 없음, 1 = 있음, 그 밖 = 비교 불가(기준점 커밋 없음 등).
    Markdown 은 뺌 — 설치·빌드·실행 입력으로 쓰는 .md 가 없음(setup.py data_files·CMake·Docker 확인, #385 E 재리뷰).
    그 밖 확장자(.py·package.xml·setup.py·YAML·TTL·JSON 태스크 등)는 모두 실행 파일로 봄 — 확장자 허용 목록이 아니라 제외 목록."""
    return subprocess.run(["git", "-C", str(root), "diff", "--quiet", sha, "HEAD", "--", *RUNTIME_PATHS, *NOT_RUNTIME],
                          capture_output=True).returncode


def latest_ready(log_dir: Path) -> Path | None:
    found = sorted(log_dir.glob("*/ready.txt"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ready", type=Path, help="pc2_up.sh 가 남긴 ready.txt (기본: 로그 폴더에서 가장 최근)")
    ap.add_argument("--log-dir", type=Path,                      # pc2_up.sh 와 같은 곳 (PC2_LOG_DIR)
                    default=Path(os.environ.get("PC2_LOG_DIR") or Path.home() / "ready2go_pc2_logs"))
    args = ap.parse_args(argv)
    bad, unknown, fixes, notes = [], [], [], []

    for package in PACKAGES:
        src = ROOT / "ros2_ws/src" / package / package
        installed = installed_dir(package)
        if installed is None:
            unknown.append(f"{package}: 설치본을 찾지 못함 (install_host 를 source 했나)")
            continue
        diff = compare(src, installed)
        if diff:
            more = f" 외 {len(diff) - 5}개" if len(diff) > 5 else ""
            bad.append(f"{package}: 호스트 설치본이 저장소와 다름 — {', '.join(diff[:5])}{more}")
            fix = ("음성 호스트 다시 빌드: (cd ros2_ws && colcon build --build-base build_host --install-base install_host "
                   "--packages-up-to ready2go_voice)")
            if fix not in fixes:
                fixes.append(fix)

    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip() or "unknown"
    ready = args.ready or latest_ready(args.log_dir)
    if ready is None or not ready.is_file():
        unknown.append(f"Runner 기준점(ready.txt) 없음 — pc2_up.sh 를 먼저 ({args.log_dir})")
    else:
        fields = ready.read_text(encoding="utf-8").split()
        state, sha = (fields + ["", ""])[:2]
        if state != "OK":
            unknown.append(f"Runner 준비가 OK 가 아님 ({ready}: {state or '빈 파일'})")
        elif sha != head:
            # 커밋이 달라도 실행에 쓰는 파일이 그대로면(문서만 바뀜) 다시 띄우지 않아도 됨 (#385 E 리뷰)
            changed = runtime_changed(ROOT, sha)
            if changed == 0:
                notes.append(f"Runner 기준점 {sha} → 지금 {head}: 실행 파일({', '.join(RUNTIME_PATHS)}, .md 제외) 변화 없음 (문서·도구만 바뀜) — 다시 띄우지 않아도 됨")
            else:                           # 1 = 실행 파일 바뀜, 그 밖 = 기준점 커밋을 못 찾음(비교 불가 → 다름으로)
                why = "실행 파일이 바뀜" if changed == 1 else "기준점 커밋을 이 저장소에서 못 찾아 비교 불가"
                bad.append(f"Runner 기준점 {sha} ≠ 지금 checkout {head} — pc2_up.sh 뒤에 {why} ({ready})")
                fixes.append("Runner 다시 띄우기: bash tools/dev/pc2_down.sh → bash tools/dev/pc2_up.sh (같은 모드)")

    for line in bad:
        print(f"❌ {line}")
    for line in unknown:
        print(f"⚠️  {line}")
    if bad:
        for fix in fixes:
            print(f"   맞추기: {fix}")
        return 1
    if unknown:
        return 2
    for line in notes:
        print(f"   {line}")
    print(f"✅ 음성(install_host)·Runner 같은 C 코드 — 지금 {head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
