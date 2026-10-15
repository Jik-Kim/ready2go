"""PC2 버전 확인(tools/dev/pc2_version_check.py, C 인프라)의 Runner 기준점 비교 — #385 E 재리뷰 회귀.

기준점(ready.txt SHA) 뒤 바뀐 것이 Markdown 문서뿐이면 0(재기동 요구 안 함), 코드·설정·빌드 입력이 바뀌면 1, 기준점 커밋을
못 찾으면 비교 불가(0·1 아님 → 검사기는 다름으로 봄). 임시 git 저장소에서 직접 커밋을 만들어 확인.
"""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("pc2_version_check", ROOT / "tools/dev/pc2_version_check.py")
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git 없음")

BASE_FILES = {
    "ros2_ws/src/ready2go_voice/README.md": "voice\n",
    "ros2_ws/src/ready2go_voice/ready2go_voice/core/group_speech.py": "x = 1\n",
    "ros2_ws/src/ready2go_voice/package.xml": "<package/>\n",
    "ros2_ws/src/ready2go_voice/setup.py": "# setup\n",
    "ros2_ws/src/ready2go_voice/params/voice.yaml": "a: 1\n",
    "knowledge/semantics.ttl": "# ttl\n",
    "knowledge/README.md": "knowledge\n",
    "tasks/find_with_unpack.json": "{}\n",
    "docs/runner.md": "doc\n",
    "practice/E/CURRENT.md": "e\n",
}


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    for rel, text in BASE_FILES.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    return tmp_path, git(tmp_path, "rev-parse", "--short", "HEAD")


def change(repo, *paths):
    for rel in paths:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((p.read_text() if p.exists() else "") + "changed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "change")


@pytest.mark.parametrize("paths", [
    ("ros2_ws/src/ready2go_voice/README.md",),                                  # 패키지 README 만 (E 재현 경우)
    ("ros2_ws/src/ready2go_voice/README.md", "knowledge/README.md", "docs/runner.md", "practice/E/CURRENT.md"),
    ("tools/dev/pc2_voice.sh",),                                                 # 실행 경로 밖 도구
])
def test_docs_only_changes_do_not_need_runner_restart(repo, paths):
    root, base = repo
    change(root, *paths)
    assert vc.runtime_changed(root, base) == 0


@pytest.mark.parametrize("path", [
    "ros2_ws/src/ready2go_voice/ready2go_voice/core/group_speech.py",
    "ros2_ws/src/ready2go_voice/package.xml",
    "ros2_ws/src/ready2go_voice/setup.py",
    "ros2_ws/src/ready2go_voice/params/voice.yaml",
    "knowledge/semantics.ttl",
    "tasks/find_with_unpack.json",
    "compose.yaml",
])
def test_code_config_build_inputs_need_runner_restart(repo, path):
    """README 와 같이 바뀌어도 실행 입력이 하나라도 바뀌면 1."""
    root, base = repo
    change(root, "ros2_ws/src/ready2go_voice/README.md", path)
    assert vc.runtime_changed(root, base) == 1


def test_unknown_base_commit_is_not_treated_as_same(repo):
    root, _ = repo
    assert vc.runtime_changed(root, "abc1234") not in (0, 1)
