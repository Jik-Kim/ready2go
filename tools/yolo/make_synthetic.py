#!/usr/bin/env python3
"""파이프라인 점검용 합성 데이터 (담당 A, #14). 실물 데이터가 아니므로 학습 결과를 모델로 쓰지 않는다.

배경 노이즈 위에 클래스별로 모양·색이 다른 도형을 놓고 YOLO 라벨을 만든다. 세션마다 배경 밝기를 달리해 세션 단위 분할이 의미 있게 한다.
  python3 tools/yolo/make_synthetic.py --out data/labeled --sessions 4 --per-session 20
"""
import argparse
import random
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys_path = str(ROOT / "tools/yolo")
import sys  # noqa: E402

sys.path.insert(0, sys_path)
from build_dataset import CLASSES_FILE, load_classes  # noqa: E402

COLORS = [(40, 40, 220), (50, 200, 50), (220, 80, 40), (30, 200, 220), (200, 50, 200)]   # BGR, 클래스 수만큼 순환


def draw(img, cls, cx, cy, w, h):
    x1, y1, x2, y2 = int(cx - w / 2), int(cy - h / 2), int(cx + w / 2), int(cy + h / 2)
    col = COLORS[cls % len(COLORS)]
    if cls % 3 == 0:
        cv2.rectangle(img, (x1, y1), (x2, y2), col, -1)
    elif cls % 3 == 1:
        cv2.ellipse(img, (int(cx), int(cy)), (int(w / 2), int(h / 2)), 0, 0, 360, col, -1)
    else:
        cv2.fillConvexPoly(img, np.array([[cx, y1], [x1, y2], [x2, y2]], np.int32), col)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "data/labeled"))
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--per-session", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--classes", default=str(CLASSES_FILE), help="고정 클래스 목록 (없으면 온톨로지 순서 — 합성 점검 전용)")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    names, warns = load_classes(Path(a.classes), allow_ontology_order=True)   # 데이터셋 구성(build_dataset)과 같은 번호 체계
    for w in warns:
        print(f"[synthetic] ! {w}")
    nc = len(names)
    W, H = 640, 480
    for s in range(1, a.sessions + 1):
        sess = Path(a.out) / f"syn{s:02d}"
        (sess / "images").mkdir(parents=True, exist_ok=True)
        (sess / "labels").mkdir(exist_ok=True)
        base = rng.randint(70, 170)
        for i in range(a.per_session):
            img = np.clip(np.random.default_rng(a.seed * 1000 + s * 100 + i).normal(base, 12, (H, W, 3)), 0, 255).astype(np.uint8)
            labels, boxes = [], []
            for cls in rng.sample(range(nc), rng.randint(1, nc)):
                for _ in range(20):   # 겹치지 않는 위치 찾기
                    w, h = rng.randint(60, 110), rng.randint(60, 110)
                    cx, cy = rng.randint(w, W - w), rng.randint(h, H - h)
                    if all(abs(cx - bx) > (w + bw) / 2 + 5 or abs(cy - by) > (h + bh) / 2 + 5 for bx, by, bw, bh in boxes):
                        boxes.append((cx, cy, w, h))
                        draw(img, cls, cx, cy, w, h)
                        labels.append(f"{cls} {cx / W:.6f} {cy / H:.6f} {w / W:.6f} {h / H:.6f}")
                        break
            cv2.imwrite(str(sess / "images" / f"{i:04d}.png"), img)
            (sess / "labels" / f"{i:04d}.txt").write_text("\n".join(labels) + "\n", encoding="utf-8")
        print(f"[synthetic] {sess} {a.per_session}장")


if __name__ == "__main__":
    main()
