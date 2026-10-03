#!/usr/bin/env python3
"""YOLO 데이터셋 구성 (담당 A, #14). 라벨링된 촬영 세션을 **세션 단위로** train/val 로 나눈다.

입력 구조:  data/labeled/<세션>/images/*.png  +  data/labeled/<세션>/labels/*.txt  (YOLO 형식, 클래스 id = 아래 클래스 목록 순서)
클래스 목록: **config/yolo_classes.txt (한 줄에 클래스 하나, 줄 번호 = 클래스 id, 깃으로 추적)** 가 원본이다. 온톨로지(world.items) 순서를 그대로 쓰면
             물품이 추가·재정렬될 때 이미 만든 라벨의 번호가 어긋나므로, 라벨링을 시작하기 전에 `--init-classes`로 고정한다.
             yolo_classes.txt 의 모든 이름은 온톨로지 world.items 에 있어야 한다(tools/validate_contracts.py 가 검사). 물품을 추가하면 맨 뒤에 덧붙인다(앞의 번호를 바꾸지 말 것).
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


ONTOLOGY = ROOT / "knowledge/robot_ontology.jsonld"
CLASSES_FILE = ROOT / "config/yolo_classes.txt"


def ontology_items(ontology=ONTOLOGY) -> list[str]:
    """온톨로지 world.items 의 키 순서. 정의가 분리된 형식(진입 파일의 sources.world → world.jsonld)과
    단일 파일 형식(진입 파일 안의 world)을 모두 읽는다. 학습 도구가 PyYAML 에 의존하지 않도록
    ready2go_knowledge 의 load() 대신 world 파일만 직접 따라간다."""
    path = Path(ontology)
    data = json.loads(path.read_text(encoding="utf-8"))
    ref = data.get("sources", {}).get("world")
    if ref:
        path = (path.parent / ref).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
    try:
        return list(data["world"]["items"].keys())
    except KeyError:
        raise ValueError(f"{path}: world.items 를 찾지 못했습니다") from None


def class_names(ontology=ONTOLOGY) -> list[str]:
    """온톨로지 순서의 클래스 목록 (합성 데이터 점검용). 실제 학습은 load_classes 의 고정 목록을 쓴다."""
    return ontology_items(ontology)


def load_classes(classes_file: Path = CLASSES_FILE, ontology=ONTOLOGY) -> tuple[list[str], list[str]]:
    """(클래스 목록, 경고 목록). classes_file 이 있으면 그 순서를 쓰고 온톨로지에 없는 이름은 오류(ValueError)."""
    items = ontology_items(ontology)
    f = Path(classes_file)
    if not f.exists():
        return items, ["config/yolo_classes.txt 가 없어 온톨로지 순서를 씁니다. 물품이 바뀌면 기존 라벨 번호가 어긋납니다 → --init-classes 로 고정하세요"]
    names = [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(set(names)) != len(names):
        raise ValueError(f"{f}: 중복된 클래스 이름이 있습니다")
    unknown = [n for n in names if n not in items]
    if unknown:
        raise ValueError(f"{f}: 온톨로지 world.items 에 없는 클래스: {unknown}")
    new = [i for i in items if i not in names]
    return names, ([f"온톨로지에는 있지만 yolo_classes.txt 에 없는 물품(학습 대상 아님): {new}"] if new else [])


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


def pair_errors(session_dir: Path) -> tuple[list[str], list[str]]:
    """이미지와 라벨 파일명(stem)을 1:1로 비교. (라벨 없는 이미지, 이미지 없는 라벨)."""
    imgs = {p.stem for p in (session_dir / "images").glob("*.png")}
    labs = {p.stem for p in (session_dir / "labels").glob("*.txt")}
    return sorted(imgs - labs), sorted(labs - imgs)


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
    ap.add_argument("--classes", default=str(CLASSES_FILE), help="고정 클래스 목록 파일")
    ap.add_argument("--init-classes", action="store_true", help="온톨로지 순서로 클래스 파일을 만들어 번호를 고정하고 종료 (이미 있으면 거절)")
    args = ap.parse_args()

    labeled = Path(args.labeled)
    if args.init_classes:
        f = Path(args.classes)
        if f.exists():
            print(f"{f} 가 이미 있습니다. 번호가 바뀌지 않도록 덮어쓰지 않습니다.", file=sys.stderr)
            return 1
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(ontology_items()) + "\n", encoding="utf-8")
        print(f"{f} 생성: {ontology_items()}")
        return 0
    try:
        names, warns = load_classes(Path(args.classes))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    for w in warns:
        print(f"  ! {w}")
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
        missing, extra = pair_errors(labeled / s)
        for m in missing[:5]:
            print(f"  ! 라벨 없음: {m}.png")
        for x in extra[:5]:
            print(f"  ! 이미지 없는 라벨: {x}.txt")
        bad |= bool(missing or extra)
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
    (out / "classes.txt").write_text("\n".join(names) + "\n", encoding="utf-8")   # 학습 시점의 클래스 목록 기록
    print(f"클래스 {names}\ntrain 세션 {train}\nval 세션 {val}\n→ {out / 'dataset.yaml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
