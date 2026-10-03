#!/usr/bin/env python3
"""YOLO 데이터셋 구성 (담당 A, #14). 라벨링된 촬영 세션을 **세션 단위로** train/val 로 나눈다.

입력 구조:  data/labeled/<세션>/images/*.png  +  data/labeled/<세션>/labels/*.txt  (YOLO 형식, 클래스 id = 아래 클래스 목록 순서)
클래스 목록: knowledge/robot_ontology.jsonld 의 world.items 키 순서 (물품 목록 #8 이 온톨로지에 반영되면 자동으로 따라감)
출력:        data/yolo/{train,val}/{images,labels}/<세션>__<파일>  (심볼릭 링크) + data/yolo/dataset.yaml

  python3 tools/yolo/build_dataset.py --val s03_overlap s05_light      # 검증 세션 지정 (권장)
  python3 tools/yolo/build_dataset.py --val-ratio 0.25                  # 세션 이름순 뒤쪽을 검증으로 (세션 ≥ 2개)
연속 프레임을 무작위로 나누면 train/val 이 거의 같은 장면이라 mAP50 이 과대평가된다 → 항상 세션 단위.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def class_names(ontology=ROOT / "knowledge/robot_ontology.jsonld") -> list[str]:
    return list(json.loads(Path(ontology).read_text(encoding="utf-8"))["world"]["items"].keys())


def split_sessions(sessions: list[str], val: list[str] | None, val_ratio: float) -> tuple[list[str], list[str]]:
    if val:
        unknown = [v for v in val if v not in sessions]
        if unknown:
            raise ValueError(f"없는 세션: {unknown}")
        valset = set(val)
    else:
        if len(sessions) < 2:
            raise ValueError("세션이 2개 미만이면 세션 단위 분할이 불가능합니다. 세션을 더 촬영하세요.")
        k = max(1, round(len(sessions) * val_ratio))
        valset = set(sorted(sessions)[-k:])
    train = [s for s in sorted(sessions) if s not in valset]
    if not train:
        raise ValueError("train 세션이 비었습니다.")
    return train, sorted(valset)


def check_labels(label_dir: Path, nc: int) -> tuple[int, int, list[str]]:
    """(라벨 파일 수, 빈 라벨 수, 오류 목록). 클래스 id 범위·좌표 범위를 확인."""
    errs, n, empty = [], 0, 0
    for f in sorted(label_dir.glob("*.txt")):
        n += 1
        lines = [l for l in f.read_text().splitlines() if l.strip()]
        empty += not lines
        for i, line in enumerate(lines, 1):
            p = line.split()
            try:
                cls, vals = int(p[0]), [float(x) for x in p[1:]]
            except ValueError:
                errs.append(f"{f.name}:{i} 숫자가 아님")
                continue
            if not 0 <= cls < nc:
                errs.append(f"{f.name}:{i} 클래스 id {cls} (0~{nc - 1} 범위 밖)")
            if len(vals) < 4 or any(not 0.0 <= v <= 1.0 for v in vals):
                errs.append(f"{f.name}:{i} 좌표가 0~1 범위 밖이거나 값 부족")
    return n, empty, errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labeled", default=str(ROOT / "data/labeled"))
    ap.add_argument("--out", default=str(ROOT / "data/yolo"))
    ap.add_argument("--val", nargs="*", help="검증용 세션 이름")
    ap.add_argument("--val-ratio", type=float, default=0.25)
    args = ap.parse_args()

    names = class_names()
    labeled = Path(args.labeled)
    sessions = sorted(p.name for p in labeled.iterdir() if (p / "images").is_dir()) if labeled.is_dir() else []
    if not sessions:
        print(f"라벨링된 세션이 없습니다: {labeled}/<세션>/images, labels", file=sys.stderr)
        return 1
    try:
        train, val = split_sessions(sessions, args.val, args.val_ratio)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    bad = False
    for s in sessions:
        n, empty, errs = check_labels(labeled / s / "labels", len(names))
        imgs = len(list((labeled / s / "images").glob("*.png")))
        print(f"[{'val ' if s in val else 'train'}] {s}: 이미지 {imgs}, 라벨 {n} (빈 라벨 {empty})")
        if n != imgs:
            print(f"  ! 이미지 수와 라벨 수가 다릅니다")
            bad = True
        for e in errs[:5]:
            print(f"  ! {e}")
        bad |= bool(errs)
    if bad:
        print("라벨 오류가 있어 중단합니다.", file=sys.stderr)
        return 1

    out = Path(args.out)
    shutil.rmtree(out, ignore_errors=True)
    for split, group in (("train", train), ("val", val)):
        (out / split / "images").mkdir(parents=True)
        (out / split / "labels").mkdir(parents=True)
        for s in group:
            for img in sorted((labeled / s / "images").glob("*.png")):
                (out / split / "images" / f"{s}__{img.name}").symlink_to(img.resolve())
                lab = labeled / s / "labels" / f"{img.stem}.txt"
                (out / split / "labels" / f"{s}__{img.stem}.txt").symlink_to(lab.resolve())
    (out / "dataset.yaml").write_text(
        f"path: {out.resolve()}\ntrain: train/images\nval: val/images\nnc: {len(names)}\nnames: {json.dumps(names)}\n",
        encoding="utf-8")
    print(f"클래스 {names}\ntrain 세션 {train}\nval 세션 {val}\n→ {out / 'dataset.yaml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
