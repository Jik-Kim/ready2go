#!/usr/bin/env python3
"""YOLO 데이터셋 구성 (담당 A, #14). 라벨링된 촬영 세션을 **세션 단위로** train/val 로 나눈다.

입력 구조:  data/labeled/<세션>/images/*.png  +  data/labeled/<세션>/labels/*.txt  (YOLO 형식, 클래스 id = 아래 클래스 목록 순서)
클래스 목록: **config/yolo_classes.txt (한 줄에 클래스 하나, 줄 번호 = 클래스 id, 깃으로 추적)** 가 원본이다. 온톨로지(world.items) 순서를 그대로 쓰면
             물품이 추가·재정렬될 때 이미 만든 라벨의 번호가 어긋나므로, 라벨링을 시작하기 전에 `--init-classes`로 고정한다.
             yolo_classes.txt 의 모든 이름은 온톨로지 world.items 또는 은퇴 목록 config/yolo_retired_classes.txt 에 있어야 한다(class_errors, tools/validate_contracts.py 도 같은 검사).
             물품을 추가하면 맨 뒤에 덧붙인다(앞의 번호를 바꾸지 말 것). 물품을 빼도 줄은 지우지 않고 은퇴 목록에 적는다(뒤 번호가 밀리지 않게, #23 당근 펜).
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
RETIRED_NAME = "yolo_retired_classes.txt"   # 클래스 파일과 같은 폴더. 시연에서 뺀 물품의 학습 클래스(번호는 그대로, 온톨로지에서는 빠져도 됨)


def ontology_items(ontology=None) -> list[str]:
    """온톨로지 world.items 의 키 순서. 정의가 분리된 형식(진입 파일의 sources.world → world.jsonld)과
    단일 파일 형식(진입 파일 안의 world)을 모두 읽는다. 학습 도구가 PyYAML 에 의존하지 않도록
    ready2go_knowledge 의 load() 대신 world 파일만 직접 따라간다."""
    path = Path(ONTOLOGY if ontology is None else ontology)   # 호출 시점에 해석(시험에서 ONTOLOGY 를 바꿀 수 있게)
    data = json.loads(path.read_text(encoding="utf-8"))
    ref = data.get("sources", {}).get("world")
    if ref:
        path = (path.parent / ref).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
    try:
        return list(data["world"]["items"].keys())
    except KeyError:
        raise ValueError(f"{path}: world.items 를 찾지 못했습니다") from None


def read_names(path: Path) -> list[str]:
    """한 줄에 이름 하나(빈 줄 무시). 파일이 없으면 빈 목록."""
    path = Path(path)
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []


def class_errors(names: list[str], items, retired: list[str]) -> list[str]:
    """고정 클래스 목록(names) 검사: 이름은 온톨로지 world.items 또는 은퇴 목록(retired)에 있어야 한다(오타·미등록 거부).
    은퇴 이름은 고정 목록에 실제로 있어야 하고 중복이 없어야 한다. 은퇴 이름이 아직 온톨로지에 있어도 된다(제거 전후 모두 통과).
    validate_contracts.py 와 같은 함수를 쓴다."""
    errs = []
    if len(set(names)) != len(names):
        errs.append("yolo_classes.txt: 중복된 클래스 이름")
    if len(set(retired)) != len(retired):
        errs.append("yolo_retired_classes.txt: 중복된 이름")
    errs += [f"yolo_retired_classes.txt: yolo_classes.txt 에 없는 이름 {n}" for n in dict.fromkeys(retired) if n not in names]
    errs += [f"yolo_classes.txt: 온톨로지 world.items 에도 은퇴 목록에도 없는 클래스 {n}" for n in names if n not in items and n not in retired]
    return errs


def load_classes(classes_file: Path | None = None, ontology=None, allow_ontology_order: bool = False,
                 retired_file: Path | None = None) -> tuple[list[str], list[str]]:
    """(클래스 목록, 경고 목록). classes_file 이 있으면 그 순서를 쓰고 온톨로지에 없는 이름은 오류(ValueError).
    파일이 없으면 오류(ValueError) — 온톨로지 순서가 바뀌면 이미 만든 라벨이 조용히 다른 클래스로 해석되기 때문.
    합성 점검처럼 명시적으로 허용한 경우(allow_ontology_order=True)에만 온톨로지 순서로 대체하고 경고를 돌려준다."""
    items = ontology_items(ontology)
    f = Path(CLASSES_FILE if classes_file is None else classes_file)
    if not f.exists():
        if not allow_ontology_order:
            raise ValueError(f"{f} 가 없습니다. 라벨 번호가 물품 목록 변경에 흔들리지 않도록 먼저 --init-classes 로 클래스 번호를 고정하세요 (합성 점검만 --allow-ontology-order 로 허용)")
        return items, [f"{f.name} 가 없어 온톨로지 순서를 씁니다 (점검 전용 — 실제 라벨링에는 쓰지 마세요)"]
    names = read_names(f)
    retired = read_names(f.with_name(RETIRED_NAME) if retired_file is None else retired_file)
    errs = class_errors(names, items, retired)
    if errs:
        raise ValueError(f"{f}: " + " / ".join(errs))
    new = [i for i in items if i not in names]
    warns = [f"온톨로지에는 있지만 yolo_classes.txt 에 없는 물품(학습 대상 아님): {new}"] if new else []
    gone = [n for n in names if n in retired and n not in items]
    return names, warns + ([f"은퇴 클래스(번호 유지, 온톨로지에 없음 — 노드는 검출을 버림): {gone}"] if gone else [])


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
    ap.add_argument("--allow-ontology-order", action="store_true", help="클래스 고정 파일이 없어도 온톨로지 순서를 허용 (합성 점검 전용)")
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
        names, warns = load_classes(Path(args.classes), allow_ontology_order=args.allow_ontology_order)
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
