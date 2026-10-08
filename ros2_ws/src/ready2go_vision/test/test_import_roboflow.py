"""tools/yolo/import_roboflow.py 회귀 테스트: Roboflow 가 클래스 번호를 바꿔 내보내도 우리 번호로 되돌린다. 표준 라이브러리만 사용(CI 에 cv2 없어도 동작)."""
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[4] / "tools/yolo/import_roboflow.py"
OURS = ["airpods_case", "caramel_box", "car_key"]


def make_env(tmp_path, names, rows, extra_labels=None):
    classes = tmp_path / "yolo_classes.txt"
    classes.write_text("\n".join(OURS) + "\n", encoding="utf-8")
    raw = tmp_path / "raw/s01_single_v0/images"
    raw.mkdir(parents=True)
    exp = tmp_path / "export"
    (exp / "train/images").mkdir(parents=True)
    (exp / "train/labels").mkdir()
    (exp / "data.yaml").write_text("nc: %d\nnames: [%s]\n" % (len(names), ", ".join(names)), encoding="utf-8")
    for i, line in enumerate(rows):
        (raw / f"{i:04d}.png").write_bytes(b"png")
        stem = f"s01_{i:04d}_png.rf.abc{i}"
        (exp / "train/images" / f"{stem}.jpg").write_bytes(b"jpg")
        (exp / "train/labels" / f"{stem}.txt").write_text(line, encoding="utf-8")
    return classes, raw.parent.parent, exp


def run(tmp_path, classes, raw, exp, *extra):
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, str(TOOL), str(exp), "--out", str(out), "--raw", str(raw), "--classes", str(classes), *extra],
                       capture_output=True, text=True)
    return r, out


def test_class_numbers_are_remapped_by_name(tmp_path):
    names = ["airpods_case", "car_key", "caramel_box"]          # Roboflow 가나다순: car_key=1, caramel_box=2
    classes, raw, exp = make_env(tmp_path, names, ["1 0.5 0.5 0.1 0.2\n", "2 0.4 0.4 0.1 0.1\n", ""])
    r, out = run(tmp_path, classes, raw, exp)
    assert r.returncode == 0, r.stdout + r.stderr
    got = [(out / "s01_single_v0/labels" / f"{i:04d}.txt").read_text() for i in range(3)]
    assert got[0].startswith("2 ")          # car_key → 우리 번호 2
    assert got[1].startswith("1 ")          # caramel_box → 우리 번호 1
    assert got[2] == ""                     # 빈 라벨은 빈 파일로
    assert (out / "s01_single_v0/images/0000.png").read_bytes() == b"png"      # 원본 이미지를 사용


def test_unknown_class_name_stops(tmp_path):
    classes, raw, exp = make_env(tmp_path, ["airpods_case", "mystery"], ["1 0.5 0.5 0.1 0.2\n"])
    r, out = run(tmp_path, classes, raw, exp)
    assert r.returncode != 0 and "mystery" in (r.stdout + r.stderr)
    assert not out.exists()


def test_out_of_range_coordinate_stops(tmp_path):
    classes, raw, exp = make_env(tmp_path, OURS, ["0 1.5 0.5 0.1 0.2\n"])
    r, out = run(tmp_path, classes, raw, exp)
    assert r.returncode != 0 and not out.exists()


def test_dry_run_writes_nothing(tmp_path):
    classes, raw, exp = make_env(tmp_path, OURS, ["0 0.5 0.5 0.1 0.2\n"])
    r, out = run(tmp_path, classes, raw, exp, "--dry-run")
    assert r.returncode == 0 and not out.exists()


def test_seg_without_box_file_keeps_pieces_unmerged(tmp_path):
    """--seg: 상자 라벨 파일이 없는 장은 같은 클래스 조각을 합치지 않는다(지우개 2개가 하나로 합쳐지는 것 방지, PM 검토 #131)."""
    names = ["airpods_case", "car_key", "caramel_box"]
    poly = lambda x: "1 " + " ".join(f"{a:.2f} {b:.2f}" for a, b in [(x, 0.1), (x + 0.05, 0.1), (x + 0.05, 0.15), (x, 0.15)])  # noqa: E731
    classes, raw, exp = make_env(tmp_path, names, [poly(0.1) + "\n" + poly(0.6) + "\n"])
    r, out = run(tmp_path, classes, raw, exp, "--seg", "--boxes", str(tmp_path / "no_boxes"))
    assert r.returncode == 0, r.stdout + r.stderr
    lines = (out / "s01_single_v0/labels/0000.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all(l.split()[0] == "2" for l in lines)        # car_key → 우리 번호 2, 조각 2개 그대로
    assert "상자 라벨 파일 없음" in r.stdout
