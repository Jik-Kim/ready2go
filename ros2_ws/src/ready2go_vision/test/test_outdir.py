"""tools/yolo/_outdir.py 회귀 테스트: 자동 라벨을 다시 돌려도 이전 결과가 남지 않고, 중간에 끊겨도 불완전한 세션이 남지 않는다. 표준 라이브러리만 사용(CI 호환)."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("outdir", Path(__file__).resolve().parents[4] / "tools/yolo/_outdir.py")
outdir = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(outdir)


def fill(out, stem="0003"):
    for s in ("images", "labels", "preview"):
        (out / s).mkdir(parents=True, exist_ok=True)
    (out / f"images/{stem}.png").write_bytes(b"x")
    (out / f"labels/{stem}.txt").write_text("0 0.5 0.5 0.1 0.1\n")
    (out / f"preview/{stem}.png").write_bytes(b"x")


def test_new_output_gets_empty_work_dir(tmp_path):
    out = tmp_path / "labeled/s01"
    work, found = outdir.prepare_output(out, tmp_path / "raw/s01", force=False)
    assert found == {} and (work / "labels").is_dir() and not out.exists()
    assert tmp_path / "labeled" not in work.parents          # 작업 폴더는 data/labeled 밖 (데이터셋에 섞이지 않음)


def test_existing_output_aborts_without_force(tmp_path):
    out = tmp_path / "labeled/s01"
    fill(out)
    with pytest.raises(FileExistsError, match="--force"):
        outdir.prepare_output(out, tmp_path / "raw/s01", force=False)
    assert (out / "labels/0003.txt").exists()


def test_force_keeps_old_until_commit_then_replaces(tmp_path):
    out = tmp_path / "labeled/s01"
    fill(out)
    work, found = outdir.prepare_output(out, tmp_path / "raw/s01", force=True)
    assert found == {"images": 1, "labels": 1, "preview": 1}
    assert (out / "labels/0003.txt").exists()                # 끝나기 전에는 기존 출력이 그대로
    fill(work, "0004")
    outdir.commit_output(work, out)
    assert not (out / "labels/0003.txt").exists() and (out / "labels/0004.txt").exists()
    assert not work.exists()


def test_interrupted_run_leaves_old_output_untouched(tmp_path):
    out = tmp_path / "labeled/s01"
    fill(out)
    work, _ = outdir.prepare_output(out, tmp_path / "raw/s01", force=True)
    fill(work, "0000")                                       # 일부만 만들고 오류로 끊김 (commit 안 함)
    assert (out / "labels/0003.txt").exists() and not (out / "labels/0000.txt").exists()
    work2, _ = outdir.prepare_output(out, tmp_path / "raw/s01", force=True)   # 다음 실행은 작업 폴더를 새로 시작
    assert not list((work2 / "labels").iterdir())


def test_raw_is_never_touched_and_overlap_is_rejected(tmp_path):
    raw = tmp_path / "raw/s01"
    (raw / "images").mkdir(parents=True)
    (raw / "images/0000.png").write_bytes(b"orig")
    with pytest.raises(ValueError):
        outdir.prepare_output(raw, raw, force=True)
    with pytest.raises(ValueError):
        outdir.prepare_output(raw / "images", raw, force=True)
    assert (raw / "images/0000.png").read_bytes() == b"orig"
