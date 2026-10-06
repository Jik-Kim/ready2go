"""tools/yolo/_outdir.py 회귀 테스트: 자동 라벨을 다시 돌려도 이전 결과가 학습 데이터에 남지 않는다. 표준 라이브러리만 사용(CI 호환)."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("outdir", Path(__file__).resolve().parents[4] / "tools/yolo/_outdir.py")
outdir = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(outdir)


def fill(out):
    for s in ("images", "labels", "preview"):
        (out / s).mkdir(parents=True)
    (out / "images/0003.png").write_bytes(b"x")
    (out / "labels/0003.txt").write_text("0 0.5 0.5 0.1 0.1\n")
    (out / "preview/0003.png").write_bytes(b"x")


def test_empty_or_new_output_is_fine(tmp_path):
    assert outdir.prepare_output(tmp_path / "out/s01", tmp_path / "raw/s01", force=False) == {}
    assert (tmp_path / "out/s01/labels").is_dir()


def test_existing_output_aborts_without_force(tmp_path):
    out = tmp_path / "out/s01"
    fill(out)
    with pytest.raises(FileExistsError, match="--force"):
        outdir.prepare_output(out, tmp_path / "raw/s01", force=False)
    assert (out / "labels/0003.txt").exists()            # 중단했으니 아무것도 지워지지 않는다


def test_force_removes_previous_results(tmp_path):
    out = tmp_path / "out/s01"
    fill(out)
    removed = outdir.prepare_output(out, tmp_path / "raw/s01", force=True)
    assert removed == {"images": 1, "labels": 1, "preview": 1}
    assert not (out / "labels/0003.txt").exists() and not (out / "images/0003.png").exists()
    assert (out / "labels").is_dir()                    # 폴더는 다시 만들어 둔다


def test_raw_is_never_touched_and_overlap_is_rejected(tmp_path):
    raw = tmp_path / "raw/s01"
    (raw / "images").mkdir(parents=True)
    (raw / "images/0000.png").write_bytes(b"orig")
    with pytest.raises(ValueError):
        outdir.prepare_output(raw, raw, force=True)               # 출력이 원본과 같으면 거부
    with pytest.raises(ValueError):
        outdir.prepare_output(raw / "images", raw, force=True)    # 원본 안쪽이어도 거부
    assert (raw / "images/0000.png").read_bytes() == b"orig"
