#!/usr/bin/env python3
"""Roboflow 내보내기(YOLOv8 TXT)를 우리 규칙으로 되돌린다 (담당 A, #14).

- 클래스 번호: 내보낸 data.yaml 의 names 를 config/yolo_classes.txt 의 이름→번호로 다시 매긴다(순서가 달라도 이름으로 맞춘다).
- 세션 복원: 파일 이름 접두어(s01_, s02_, ...)로 data/raw 의 세션을 찾는다. 이미지는 Roboflow 가 다시 인코딩한 것이 아니라 원본 PNG 를 쓴다.
- 결과: data/labeled/<세션>/images/NNNN.png, labels/NNNN.txt (build_dataset.py 가 읽는 형식). 라벨이 없는 이미지는 빈 라벨(.txt, 0바이트).
- 검증: 라벨 파일은 있는데 원본 이미지가 없거나, 클래스 이름이 우리 목록에 없거나, 좌표가 0~1 밖이면 중단하고 알려 준다.

실행: python3 tools/yolo/import_roboflow.py <내보낸 폴더> [--out data/labeled] [--raw data/raw] [--dry-run]
Roboflow 내보내기 파일 이름 예: s01_0000_png.rf.<해시>.jpg / .txt
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME_RE = re.compile(r"^(s\d+)_(\d{4})_png\.rf\.[0-9a-zA-Z]+$")      # Roboflow 가 붙인 이름
PLAIN_RE = re.compile(r"^(s\d+)_(\d{4})$")                              # 해시가 없는 경우


def load_names(yaml_path: Path) -> list[str]:
    """data.yaml 의 names 를 순서대로 읽는다 (PyYAML 없이도 동작: 목록형·사전형 모두 지원)."""
    text = yaml_path.read_text(encoding="utf-8")
    try:
        import yaml
        d = yaml.safe_load(text)
        names = d["names"]
        return [names[k] for k in sorted(names)] if isinstance(names, dict) else list(names)
    except ImportError:
        names = {}
        m = re.search(r"names:\s*\[(.*?)\]", text, re.S)
        if m:
            return [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
        for line in text.splitlines():
            mm = re.match(r"^\s+(\d+):\s*(\S+)", line)
            if mm:
                names[int(mm[1])] = mm[2]
        return [names[k] for k in sorted(names)]


def find_session_dir(raw: Path, prefix: str) -> Path | None:
    cands = sorted(p for p in raw.iterdir() if p.is_dir() and p.name.startswith(prefix + "_") and (p / "images").exists())
    return cands[0] if cands else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export_dir", help="Roboflow 에서 내려받아 푼 폴더 (train/valid/test 하위 폴더와 data.yaml 이 있음)")
    ap.add_argument("--out", default=str(ROOT / "data/labeled"))
    ap.add_argument("--raw", default=str(ROOT / "data/raw"))
    ap.add_argument("--classes", default=str(ROOT / "config/yolo_classes.txt"))
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 요약만 출력")
    args = ap.parse_args()

    export, raw, out = Path(args.export_dir), Path(args.raw), Path(args.out)
    ours = [l.strip() for l in Path(args.classes).read_text(encoding="utf-8").splitlines() if l.strip()]
    ypath = next(iter(sorted(export.glob("data.yaml"))), None) or next(iter(sorted(export.rglob("data.yaml"))), None)
    if ypath is None:
        sys.exit("data.yaml 을 찾지 못했습니다")
    theirs = load_names(ypath)
    unknown = [n for n in theirs if n not in ours]
    if unknown:
        sys.exit(f"Roboflow 클래스 중 우리 목록에 없는 이름: {unknown} (Roboflow 에서 이름을 고치거나 yolo_classes.txt 와 맞추세요)")
    remap = {i: ours.index(n) for i, n in enumerate(theirs)}
    print(f"[import] 클래스 번호 재매핑: " + ", ".join(f"{i}:{theirs[i]}→{remap[i]}" for i in range(len(theirs)) if i != remap[i]) or "동일")

    sessions: dict[str, dict[str, list[str]]] = {}      # 세션 → {원본 stem: 라벨 줄들}
    seen_img: dict[str, set[str]] = {}
    errors, split_of = [], {}
    for split in ("train", "valid", "val", "test"):
        ldir, idir = export / split / "labels", export / split / "images"
        if not ldir.exists():
            continue
        for img in sorted(idir.glob("*")):
            m = NAME_RE.match(img.stem) or PLAIN_RE.match(img.stem)
            if m:
                sdir = find_session_dir(raw, m[1])
                if sdir:
                    seen_img.setdefault(sdir.name, set()).add(m[2])
                    split_of[(sdir.name, m[2])] = split
        for lab in sorted(ldir.glob("*.txt")):
            m = NAME_RE.match(lab.stem) or PLAIN_RE.match(lab.stem)
            if not m:
                errors.append(f"{lab.name}: 이름에서 세션·번호를 읽지 못함")
                continue
            sdir = find_session_dir(raw, m[1])
            if sdir is None:
                errors.append(f"{lab.name}: 세션 {m[1]} 의 원본 폴더가 data/raw 에 없음")
                continue
            lines = []
            for ln in lab.read_text(encoding="utf-8").splitlines():
                parts = ln.split()
                if not parts:
                    continue
                cid, *coords = parts
                if len(parts) != 5 or int(cid) not in remap or not all(0.0 <= float(c) <= 1.0 for c in coords):
                    errors.append(f"{lab.name}: 잘못된 라벨 줄 '{ln}'")
                    continue
                lines.append(" ".join([str(remap[int(cid)])] + coords))
            sessions.setdefault(sdir.name, {})[m[2]] = lines
    if errors:
        print("\n".join(errors[:30]))
        sys.exit(f"오류 {len(errors)}건 — 중단")

    total = 0
    for sname in sorted(set(sessions) | set(seen_img)):
        imgs = sorted((raw / sname / "images").glob("*.png"))
        n_lab = n_empty = 0
        for p in imgs:
            num = p.stem
            if num not in sessions.get(sname, {}) and num not in seen_img.get(sname, set()):
                continue                                   # Roboflow 에 올라가지 않은(또는 내보내지 않은) 장
            lines = sessions.get(sname, {}).get(num, [])
            if not args.dry_run:
                (out / sname / "images").mkdir(parents=True, exist_ok=True)
                (out / sname / "labels").mkdir(exist_ok=True)
                shutil.copy2(p, out / sname / "images" / p.name)
                (out / sname / "labels" / f"{num}.txt").write_text("".join(l + "\n" for l in lines), encoding="utf-8")
            n_lab += bool(lines)
            n_empty += not lines
            total += 1
        splits = sorted({v for (s, _), v in split_of.items() if s == sname})
        print(f"[import] {sname}: 장 {n_lab + n_empty} (박스 있음 {n_lab}, 빈 라벨 {n_empty}) 분할 {splits}")
    print(f"[import] 합계 {total}장 → {out}" + (" (dry-run, 쓰지 않음)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
