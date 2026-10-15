#!/usr/bin/env python3
"""PC2 음성(호스트 install_host)과 Runner(도커, 지금 checkout) 의 C 코드 버전 맞춤 확인 — #384 E·C 합의 10/15.

E 음성은 C Runner 코드(`ready2go_runner.core.item_group` 안내 factory 등)를 호스트 빌드(install_host)에서 import 하고,
도커 Runner 는 기동 때 지금 checkout 을 빌드한다. 둘이 다른 시점이면 목록 안내가 E 에서 조용히 거절될 수 있음(#384 리뷰 ②,
구조화 안내 계약은 후속). 그래서 음성 노드를 띄우기 전에 확인:

1. 호스트에 설치된 Python 패키지 파일이 지금 저장소 소스와 같은가 (install_host 를 다시 빌드했나)
2. 떠 있는 Runner 의 기준점(pc2_up.sh 가 남긴 ready.txt 의 SHA)이 지금 checkout HEAD 와 같은가 (pc2_up 뒤에 git pull 안 했나)

한계: Python 패키지 파일만 비교(설치된 share 데이터 — TTL·태스크 — 는 안 봄), 커밋 안 한 수정을 pc2_up 뒤에 바꾼 경우는 2 가 못 잡음.

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


def latest_ready(log_dir: Path) -> Path | None:
    found = sorted(log_dir.glob("*/ready.txt"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ready", type=Path, help="pc2_up.sh 가 남긴 ready.txt (기본: 로그 폴더에서 가장 최근)")
    ap.add_argument("--log-dir", type=Path,                      # pc2_up.sh 와 같은 곳 (PC2_LOG_DIR)
                    default=Path(os.environ.get("PC2_LOG_DIR") or Path.home() / "ready2go_pc2_logs"))
    args = ap.parse_args(argv)
    bad, unknown, fixes = [], [], []

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
            bad.append(f"Runner 기준점 {sha} ≠ 지금 checkout {head} — pc2_up.sh 뒤에 코드가 바뀜 ({ready})")
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
    print(f"✅ 음성(install_host)·Runner 같은 C 코드 — 기준점 {head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
