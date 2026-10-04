#!/usr/bin/env python3
"""단독 배치 세션 자동 라벨링 (담당 A, #14). 한 장에 물품 한 개인 세션(s01_single)용.

클래스는 촬영 때 기록한 class_ranges.txt(번호 구간 ↔ 물품)에서 가져오고, 박스는 정렬 뎁스에서 구한다:
  서랍 바닥 안쪽 영역의 뎁스에 바닥 평면을 맞추고 → 바닥보다 floor_margin_mm 이상 높은 픽셀의 가장 큰 연결 덩어리 → 외접 박스.
결과는 YOLO txt(클래스 id = config/yolo_classes.txt 줄 번호)로 data/labeled/<세션>/ 에 쓰고, 눈으로 확인할 미리보기 이미지도 만든다.

색 배경 차이로 보강: --background-session(빈 서랍 사진들의 중앙값)과 색 차이가 큰 픽셀도 덩어리에 합친다. 검은 물체·링 모양처럼 뎁스가 빠지는 곳을 메운다.

주의: 서랍 바닥 영역(ROI)은 기준 시점(drawer_top_view)에서의 화면 위치이다. 시점 변화 세션에는 쓰지 않는다.
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
# 기준 시점 1280x720 화면에서 서랍 바닥 안쪽 [x0, y0, x1, y1] 픽셀 (바닥-벽 경계선 안쪽, 눈으로 잰 값)
FLOOR_ROI = (268, 108, 1008, 614)


def load_classes(path: Path) -> list[str]:
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_ranges(path: Path) -> list[tuple[int, int, str]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\d+)-(\d+)\s+([a-z_]+)", line.strip())
        if m:
            out.append((int(m[1]), int(m[2]), m[3]))
    return out


def fit_floor(depth: np.ndarray, roi, margin_mm: float):
    """ROI 안 유효 뎁스에 평면을 맞춘다(물체로 보이는 높은 픽셀은 반복해서 뺀다). 반환: 각 픽셀의 바닥 거리(mm) 배열(ROI 크기)."""
    x0, y0, x1, y1 = roi
    reg = depth[y0:y1, x0:x1]
    valid = reg > 0
    yy, xx = np.mgrid[0:reg.shape[0], 0:reg.shape[1]]
    keep = valid.copy()
    p = None
    for _ in range(4):
        ys, xs = np.nonzero(keep)
        sel = slice(None, None, 11)
        A = np.stack([xs[sel], ys[sel], np.ones_like(xs[sel])], 1).astype(float)
        z = reg[ys[sel], xs[sel]]
        p = np.linalg.lstsq(A, z, rcond=None)[0]
        floor = p[0] * xx + p[1] * yy + p[2]
        keep = valid & (reg > floor - margin_mm)       # 바닥보다 margin 이상 가까운(높은) 픽셀은 다음 맞춤에서 제외
    return floor, reg, valid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", help="data/raw 아래 세션 이름 (예: s01_single_v0)")
    ap.add_argument("--raw", default=str(ROOT / "data/raw"))
    ap.add_argument("--out", default=str(ROOT / "data/labeled"))
    ap.add_argument("--classes", default=str(ROOT / "config/yolo_classes.txt"))
    ap.add_argument("--margin-mm", type=float, default=4.0, help="바닥보다 이만큼 높아야 물체 (config 화 예정 [팀 확정 필요])")
    ap.add_argument("--pad-px", type=int, default=3, help="박스를 사방으로 넓힘(뎁스-컬러 가장자리 오차)")
    ap.add_argument("--background-session", default="s05_empty_v0", help="빈 서랍 세션(같은 시점·조명). 없으면 뎁스만 사용")
    ap.add_argument("--color-diff", type=float, default=28.0, help="배경과의 색 차이(Lab 거리) 문턱 [팀 확정 필요]")
    ap.add_argument("--exclude", nargs="*", default=[], help="라벨링에서 뺄 이미지 번호 (예: 0017)")
    args = ap.parse_args()

    raw, out = Path(args.raw) / args.session, Path(args.out) / args.session
    classes = load_classes(Path(args.classes))
    ranges = load_ranges(raw / "class_ranges.txt")
    if not ranges:
        sys.exit(f"{raw}/class_ranges.txt 가 없거나 비어 있습니다")
    cls_of = {}
    for a, b, name in ranges:
        if name not in classes:
            sys.exit(f"class_ranges.txt 의 {name} 가 config/yolo_classes.txt 에 없습니다")
        for i in range(a, b + 1):
            cls_of[i] = name

    bg_lab = None
    bg_dir = Path(args.raw) / args.background_session / "images"
    if bg_dir.exists() and any(bg_dir.glob("*.png")):
        bgs = [cv2.imread(str(f)) for f in sorted(bg_dir.glob("*.png"))]
        bg_lab = cv2.cvtColor(np.median(np.stack(bgs), axis=0).astype(np.uint8), cv2.COLOR_BGR2LAB).astype(float)
    else:
        print(f"[auto_label] 배경 세션 {bg_dir} 없음 → 뎁스만 사용")
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(exist_ok=True)
    (out / "preview").mkdir(exist_ok=True)
    review, n_ok = [], 0
    for img_path in sorted((raw / "images").glob("*.png")):
        stem, i = img_path.stem, int(img_path.stem)
        if stem in args.exclude or i not in cls_of:
            review.append((stem, "제외(클래스 구간 없음 또는 --exclude)"))
            continue
        color = cv2.imread(str(img_path))
        depth = cv2.imread(str(raw / "depth" / img_path.name), cv2.IMREAD_UNCHANGED).astype(float)
        h, w = depth.shape
        floor, reg, valid = fit_floor(depth, FLOOR_ROI, args.margin_mm)
        obj = valid & (floor - reg > args.margin_mm)
        obj = cv2.morphologyEx(obj.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        if bg_lab is not None:                                   # 색 차이 보강: 뎁스 덩어리 근처(팽창 영역)의 색 변화만 합친다
            x0r, y0r, x1r, y1r = FLOOR_ROI
            lab_img = cv2.cvtColor(color, cv2.COLOR_BGR2LAB).astype(float)[y0r:y1r, x0r:x1r]
            diff = np.linalg.norm(lab_img - bg_lab[y0r:y1r, x0r:x1r], axis=2) > args.color_diff
            diff = cv2.morphologyEx(diff.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            near = cv2.dilate(obj, np.ones((41, 41), np.uint8)) > 0   # 뎁스 덩어리에서 약 2 cm 이내의 색 변화만
            obj = cv2.morphologyEx(((obj > 0) | ((diff > 0) & near)).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(obj)
        if n <= 1:
            review.append((stem, "물체 덩어리 없음"))
            continue
        areas = st[1:, cv2.CC_STAT_AREA]
        k = 1 + int(np.argmax(areas))
        x, y, bw, bh, area = st[k]
        x0, y0 = FLOOR_ROI[0], FLOOR_ROI[1]
        bx0, by0 = max(x + x0 - args.pad_px, 0), max(y + y0 - args.pad_px, 0)
        bx1, by1 = min(x + x0 + bw + args.pad_px, w), min(y + y0 + bh + args.pad_px, h)
        notes = []
        others = [a for j, a in enumerate(areas, start=1) if j != k and a > 0.15 * area]
        if others:
            notes.append(f"다른 큰 덩어리 {len(others)}개")
        if x + x0 <= FLOOR_ROI[0] or y + y0 <= FLOOR_ROI[1] or x + x0 + bw >= FLOOR_ROI[2] or y + y0 + bh >= FLOOR_ROI[3]:
            notes.append("ROI 가장자리에 닿음(벽 인접?)")
        if area < 1500:
            notes.append(f"덩어리 작음 {area}px")
        name = cls_of[i]
        (out / "labels" / f"{stem}.txt").write_text(
            f"{classes.index(name)} {(bx0 + bx1) / 2 / w:.6f} {(by0 + by1) / 2 / h:.6f} {(bx1 - bx0) / w:.6f} {(by1 - by0) / h:.6f}\n", encoding="utf-8")
        shutil.copy2(img_path, out / "images" / img_path.name)
        vis = color.copy()
        cv2.rectangle(vis, (int(bx0), int(by0)), (int(bx1), int(by1)), (0, 255, 0), 2)
        cv2.putText(vis, f"{stem} {name}", (int(bx0), max(int(by0) - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imwrite(str(out / "preview" / img_path.name), vis)
        n_ok += 1
        if notes:
            review.append((stem, "; ".join(notes)))
    print(f"[auto_label] {n_ok}장 라벨 작성 → {out}")
    for stem, why in review:
        print(f"  확인 필요 {stem}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
