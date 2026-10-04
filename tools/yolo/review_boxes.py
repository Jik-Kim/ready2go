#!/usr/bin/env python3
"""한 장에 박스 하나인 라벨(단독 배치 세션)을 한 장씩 보며 고치는 도구 (담당 A, #14). OpenCV 창을 쓴다.

실행: python3 tools/yolo/review_boxes.py <세션> --labeled <data/labeled> --out <data/labeled_fixed>
  원본 라벨은 건드리지 않고, 확인·수정한 라벨을 --out 에 따로 저장한다.

조작
  마우스 왼쪽 버튼 드래그 : 박스를 새로 그린다(이전 박스는 지워짐)
  Enter / Space          : 이 박스를 확정하고 다음 장으로
  r                      : 자동 박스로 되돌리기
  b                      : 이전 장으로
  s                      : 이 장 건너뛰기(라벨 저장 안 함, 학습에서 빠짐)
  q / Esc                : 종료(지금까지 확정한 것은 저장되어 있음)
이미 --out 에 있는 장은 확정된 것으로 보고 건너뛴다(--redo 로 처음부터).
"""
import argparse
import sys
from pathlib import Path

import cv2

WINDOW = "review_boxes"


def read_label(path: Path):
    """YOLO txt 한 줄 → (class_id, x0, y0, x1, y1) 픽셀. w, h 는 호출자가 곱한다(정규화 값 그대로 반환)."""
    c, xc, yc, bw, bh = path.read_text(encoding="utf-8").split()[:5]
    return int(c), float(xc) - float(bw) / 2, float(yc) - float(bh) / 2, float(xc) + float(bw) / 2, float(yc) + float(bh) / 2


def write_label(path: Path, cls: int, x0: float, y0: float, x1: float, y1: float) -> None:
    x0, x1 = sorted((min(max(x0, 0.0), 1.0), min(max(x1, 0.0), 1.0)))
    y0, y1 = sorted((min(max(y0, 0.0), 1.0), min(max(y1, 0.0), 1.0)))
    path.write_text(f"{cls} {(x0 + x1) / 2:.6f} {(y0 + y1) / 2:.6f} {x1 - x0:.6f} {y1 - y0:.6f}\n", encoding="utf-8")


class Editor:
    def __init__(self):
        self.box = None          # 화면 픽셀 (x0, y0, x1, y1)
        self.drag = None

    def on_mouse(self, event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drag = (x, y)
            self.box = (x, y, x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self.drag:
            self.box = (self.drag[0], self.drag[1], x, y)
        elif event == cv2.EVENT_LBUTTONUP and self.drag:
            self.box = (self.drag[0], self.drag[1], x, y)
            self.drag = None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session")
    ap.add_argument("--labeled", required=True, help="자동 라벨이 있는 폴더 (images/, labels/)")
    ap.add_argument("--out", required=True, help="확정한 라벨을 저장할 폴더")
    ap.add_argument("--classes", default=str(Path(__file__).resolve().parents[2] / "config/yolo_classes.txt"))
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--scale", type=float, default=1.0, help="화면 배율(화면이 작으면 0.8 등)")
    args = ap.parse_args()

    src, dst = Path(args.labeled) / args.session, Path(args.out) / args.session
    (dst / "labels").mkdir(parents=True, exist_ok=True)
    (dst / "images").mkdir(exist_ok=True)
    names = [l.strip() for l in Path(args.classes).read_text(encoding="utf-8").splitlines() if l.strip()]
    stems = sorted(p.stem for p in (src / "labels").glob("*.txt"))
    if not stems:
        sys.exit(f"{src}/labels 에 라벨이 없습니다")
    ed = Editor()
    cv2.namedWindow(WINDOW)
    cv2.setMouseCallback(WINDOW, ed.on_mouse)
    i = 0
    while 0 <= i < len(stems):
        stem = stems[i]
        done = dst / "labels" / f"{stem}.txt"
        if done.exists() and not args.redo:
            i += 1
            continue
        img = cv2.imread(str(src / "images" / f"{stem}.png"))
        h, w = img.shape[:2]
        cls, x0, y0, x1, y1 = read_label(src / "labels" / f"{stem}.txt")
        auto = (x0, y0, x1, y1)
        s = args.scale
        ed.box = (x0 * w * s, y0 * h * s, x1 * w * s, y1 * h * s)
        ed.drag = None
        base = cv2.resize(img, None, fx=s, fy=s) if s != 1.0 else img
        while True:
            view = base.copy()
            b = [int(v) for v in ed.box]
            cv2.rectangle(view, (b[0], b[1]), (b[2], b[3]), (0, 255, 0), 2)
            cv2.putText(view, f"{i + 1}/{len(stems)}  {stem}  {names[cls]}   [Enter 확정 | 드래그 새 박스 | r 되돌리기 | b 이전 | s 건너뜀 | q 종료]",
                        (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.imshow(WINDOW, view)
            k = cv2.waitKey(20) & 0xFF
            if k in (13, 32):                                   # Enter, Space
                bx0, by0, bx1, by1 = ed.box
                write_label(done, cls, bx0 / (w * s), by0 / (h * s), bx1 / (w * s), by1 / (h * s))
                cv2.imwrite(str(dst / "images" / f"{stem}.png"), img)
                i += 1
                break
            elif k == ord("r"):
                ed.box = (auto[0] * w * s, auto[1] * h * s, auto[2] * w * s, auto[3] * h * s)
            elif k == ord("b"):
                i = max(i - 1, 0)
                (dst / "labels" / f"{stems[i]}.txt").unlink(missing_ok=True)
                break
            elif k == ord("s"):
                i += 1
                break
            elif k in (ord("q"), 27):
                cv2.destroyAllWindows()
                print(f"[review] 종료: 확정 {len(list((dst / 'labels').glob('*.txt')))}장 → {dst}")
                return 0
    cv2.destroyAllWindows()
    print(f"[review] 끝: 확정 {len(list((dst / 'labels').glob('*.txt')))}장 → {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
