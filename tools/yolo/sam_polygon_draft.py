#!/usr/bin/env python3
"""상자 라벨 → SAM2 윤곽(폴리곤) 초안 (담당 A, P2 인스턴스 분할 준비, #109).

- 입력: data/labeled/<세션>/images/NNNN.png + labels/NNNN.txt (YOLO 상자, 사람이 확인한 라벨)
- 각 상자를 SAM2 에 상자 프롬프트로 넣어 마스크를 얻고 → 상자(+여유) 밖은 잘라내고 → 가장 큰 덩어리의 외곽선을 폴리곤으로 줄인다.
- 출력(Roboflow 업로드용): <out>/<세션>/sNN_NNNN.png(원본 복사) + sNN_NNNN.txt(YOLO 분할 형식: 클래스 x1 y1 x2 y2 ... 0~1) + data.yaml,
  <out>/_reports/<세션>.csv(물체별 — 업로드 폴더 밖: Roboflow 가 CSV 를 주석 형식으로 읽어 업로드 오류)(물체별 마스크/상자 면적비·덩어리 수·의심 표시), <out>/_preview/<세션>/sNN_NNNN.jpg(왼쪽 상자, 오른쪽 윤곽)
- 의심(flag): 면적비가 너무 작거나 크다, 덩어리가 여러 개, 폴리곤이 안 만들어짐(→ 상자 사각형으로 대신 씀). 사람이 Roboflow 에서 확인한다.
- 초안일 뿐이다. 겹친 물체는 SAM 이 위 물체까지 같이 칠할 수 있으니 반드시 사람이 고친다.

실행(vision 이미지 안, 저장소 루트): python3 tools/yolo/sam_polygon_draft.py --sam <sam2.1_b.pt> [세션 ...] [--show] [--wait 0]
  --show: 처리 과정을 창으로 보여 준다(녹화용). --wait 0 이면 키를 누를 때마다 다음 장(q 종료), 숫자(ms)면 자동 진행.
"""
import argparse
import csv
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PALETTE = [(255, 99, 71), (60, 179, 113), (65, 105, 225), (238, 130, 238), (255, 215, 0), (0, 206, 209),
           (255, 140, 0), (154, 205, 50), (147, 112, 219), (240, 128, 128), (32, 178, 170)]   # BGR 아님(아래에서 뒤집음)


def read_boxes(txt: Path, w: int, h: int):
    out = []
    for line in txt.read_text().split("\n"):
        p = line.split()
        if len(p) != 5:
            continue
        c, x, y, bw, bh = int(p[0]), *map(float, p[1:])
        out.append((c, [(x - bw / 2) * w, (y - bh / 2) * h, (x + bw / 2) * w, (y + bh / 2) * h]))
    return out


def mask_to_polygon(mask: np.ndarray, box, margin: int, eps_px: float, min_part: float = 0.05):
    """상자(+margin) 밖을 지우고, 보이는 조각(가장 큰 조각의 min_part 이상)을 모두 외곽선 → 꼭짓점 줄인 폴리곤으로.
    조각이 여럿이면(다른 물체에 가려 둘로 나뉜 경우) Ultralytics 방식으로 가까운 점끼리 가는 선으로 이어 폴리곤 하나로 만든다.
    반환 (폴리곤 Nx2 | None, 마스크/상자 면적비, 조각 수)."""
    h, w = mask.shape
    x1, y1 = max(int(box[0]) - margin, 0), max(int(box[1]) - margin, 0)
    x2, y2 = min(int(np.ceil(box[2])) + margin, w), min(int(np.ceil(box[3])) + margin, h)
    m = np.zeros_like(mask, dtype=np.uint8)
    m[y1:y2, x1:x2] = mask[y1:y2, x1:x2].astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return None, 0.0, 0
    areas = stats[1:, cv2.CC_STAT_AREA]
    parts = [1 + i for i in np.argsort(-areas) if areas[i] >= min_part * areas.max()]
    polys, kept = [], 0
    for i in parts:
        comp = (lab == i).astype(np.uint8)
        cs, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        p = cv2.approxPolyDP(max(cs, key=cv2.contourArea), eps_px, True).reshape(-1, 2)
        if len(p) >= 3:
            polys.append(p)
            kept += int(comp.sum())
    if not polys:
        return None, 0.0, 0
    if len(polys) == 1:
        poly = polys[0]
    else:
        from ultralytics.data.converter import merge_multi_segment
        poly = np.concatenate(merge_multi_segment([p.reshape(-1).tolist() for p in polys]), axis=0)
    box_area = max((box[2] - box[0]) * (box[3] - box[1]), 1.0)
    return poly, kept / box_area, len(polys)


def resolve_overlaps(masks, boxes, margin: int):
    """같은 픽셀을 여러 마스크가 칠하면 마스크가 작은 물체에 준다.
    SAM 은 상자 안에 위에 얹힌 물체(차키·지우개·판)까지 아래 물체 마스크에 같이 칠하는 경우가 많다. 이때 아래 물체 마스크 =
    자기 + 위 물체라 위 물체 마스크보다 크므로, 작은 쪽 우선이면 위 물체 영역이 빠진다. X자 교차처럼 서로 일부만 겹치면
    교차 부분이 작은 물체에 가므로 틀릴 수 있다 → 빠진 비율을 돌려줘 의심 표시에 쓴다. 반환 (정리된 마스크들, 물체별 빠진 비율)."""
    if len(masks) == 0:
        return [], []
    h, w = masks[0].shape
    clipped = []
    for m, (_, b) in zip(masks, boxes):
        x1, y1 = max(int(b[0]) - margin, 0), max(int(b[1]) - margin, 0)
        x2, y2 = min(int(np.ceil(b[2])) + margin, w), min(int(np.ceil(b[3])) + margin, h)
        c = np.zeros((h, w), bool)
        c[y1:y2, x1:x2] = m[y1:y2, x1:x2]
        clipped.append(c)
    taken = np.zeros((h, w), bool)
    out, lost = [None] * len(clipped), [0.0] * len(clipped)
    for j in sorted(range(len(clipped)), key=lambda k: clipped[k].sum()):
        area = clipped[j].sum()
        out[j] = clipped[j] & ~taken
        lost[j] = float(1 - out[j].sum() / area) if area else 0.0
        taken |= out[j]
    return out, lost


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sessions", nargs="*", help="세션 이름 (생략 = data/labeled 의 전부)")
    ap.add_argument("--sam", required=True, help="SAM2 가중치 (예: sam2.1_b.pt)")
    ap.add_argument("--labeled", default=str(ROOT / "data/labeled"))
    ap.add_argument("--out", default=str(ROOT / "data/roboflow_upload_seg"))
    ap.add_argument("--classes", default=str(ROOT / "config/yolo_classes.txt"))
    ap.add_argument("--margin", type=int, default=4, help="상자 밖 허용 px (SAM 이 상자를 약간 넘는 것 허용)")
    ap.add_argument("--eps", type=float, default=1.5, help="폴리곤 단순화 허용 px (approxPolyDP)")
    ap.add_argument("--ratio-min", type=float, default=0.15, help="마스크/상자 면적비가 이보다 작으면 의심")
    ap.add_argument("--ratio-max", type=float, default=1.02, help="이보다 크면 의심(상자를 넘쳐 칠함)")
    ap.add_argument("--limit", type=int, default=0, help="세션당 앞 N장만 (시험용)")
    ap.add_argument("--show", action="store_true", help="처리 과정을 창으로 보기")
    ap.add_argument("--wait", type=int, default=300, help="--show 때 장당 대기 ms, 0 = 키 입력 대기")
    ap.add_argument("--no-resolve", action="store_true", help="겹친 픽셀 정리를 끈다(비교용)")
    ap.add_argument("--force", action="store_true", help="출력 세션 폴더가 있으면 지우고 다시 만든다")
    a = ap.parse_args()

    names = [l.strip() for l in Path(a.classes).read_text().splitlines() if l.strip()]
    labeled, out = Path(a.labeled), Path(a.out)
    sessions = a.sessions or sorted(p.name for p in labeled.iterdir() if (p / "labels").is_dir())
    for s in sessions:
        if (out / s).exists() and not a.force:
            sys.exit(f"이미 있음: {out / s} (다시 만들려면 --force)")

    from ultralytics import SAM
    sam = SAM(a.sam)
    win = "SAM2 polygon draft (left: box label / right: SAM2 polygon)  q=quit"
    total = flagged = 0
    for s in sessions:
        sd, prefix = out / s, s[:3]
        if sd.exists():
            shutil.rmtree(sd)
        sd.mkdir(parents=True)
        pv = out / "_preview" / s
        pv.mkdir(parents=True, exist_ok=True)
        (sd / "data.yaml").write_text("path: .\ntrain: images\nval: images\nnc: %d\nnames:\n" % len(names)
                                      + "".join(f"  {i}: {n}\n" for i, n in enumerate(names)))
        imgs = sorted((labeled / s / "images").glob("*.png"))
        if a.limit:
            imgs = imgs[:a.limit]
        rows = []
        for k, ip in enumerate(imgs):
            im = cv2.imread(str(ip))
            h, w = im.shape[:2]
            boxes = read_boxes(labeled / s / "labels" / (ip.stem + ".txt"), w, h)
            stem = f"{prefix}_{ip.stem}"
            shutil.copy(ip, sd / f"{stem}.png")
            lines, left, right = [], im.copy(), im.copy()
            if boxes:
                res = sam(im, bboxes=[b for _, b in boxes], verbose=False)[0]
                masks = res.masks.data.cpu().numpy() > 0.5 if res.masks is not None else []
            else:
                masks = []
            masks, lost = resolve_overlaps(masks, boxes[:len(masks)], a.margin) if len(masks) and not a.no_resolve else (masks, [])
            overlay = right.copy()
            for j, (c, b) in enumerate(boxes):
                col = PALETTE[c % len(PALETTE)][::-1]
                cv2.rectangle(left, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), col, 2)
                cv2.putText(left, names[c], (int(b[0]), max(14, int(b[1]) - 5)), 0, 0.5, col, 1, cv2.LINE_AA)
                poly, ratio, n_comp = (mask_to_polygon(masks[j], b, a.margin, a.eps) if j < len(masks) else (None, 0.0, 0))
                why = []
                if poly is None:
                    why.append("no_polygon")
                    poly = np.array([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]])
                if ratio < a.ratio_min or ratio > a.ratio_max:
                    why.append(f"ratio{ratio:.2f}")
                if j < len(lost) and lost[j] > 0.05:
                    why.append(f"overlap{lost[j]:.2f}")
                if n_comp > 1:
                    why.append(f"parts{n_comp}")
                pts = np.clip(poly.astype(np.float64), 0, [w - 1, h - 1])
                lines.append(f"{c} " + " ".join(f"{x / w:.6f} {y / h:.6f}" for x, y in pts))
                cv2.fillPoly(overlay, [pts.astype(np.int32)], col)
                cv2.polylines(right, [pts.astype(np.int32)], True, col, 2, cv2.LINE_AA)
                if why:
                    cv2.rectangle(right, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 0, 255), 1)
                    cv2.putText(right, "CHECK " + ",".join(why), (int(b[0]), int(b[3]) + 14), 0, 0.45, (0, 0, 255), 1, cv2.LINE_AA)
                rows.append([stem, j, names[c], f"{ratio:.3f}", n_comp, len(pts), " ".join(why)])
                flagged += bool(why)
            right = cv2.addWeighted(overlay, 0.35, right, 0.65, 0)
            (sd / f"{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
            view = np.hstack([left, right])
            cv2.putText(view, f"{s}  {k + 1}/{len(imgs)}  objects {len(boxes)}", (10, 28), 0, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.imwrite(str(pv / f"{stem}.jpg"), cv2.resize(view, (view.shape[1] // 2, view.shape[0] // 2)), [cv2.IMWRITE_JPEG_QUALITY, 85])
            total += len(boxes)
            print(f"{s} {k + 1}/{len(imgs)} {stem}: 물체 {len(boxes)}" + "".join(f" | {r[2]} {r[3]}{(' ' + r[6]) if r[6] else ''}" for r in rows[-len(boxes):] if boxes), flush=True)
            if a.show:
                cv2.imshow(win, cv2.resize(view, (view.shape[1] * 3 // 4, view.shape[0] * 3 // 4)))
                if (cv2.waitKey(a.wait) & 0xFF) == ord("q"):
                    a.show = False
                    cv2.destroyAllWindows()
                    print("창 닫음 (q). 처리는 계속합니다.")
        (out / "_reports").mkdir(exist_ok=True)
        with open(out / "_reports" / f"{s}.csv", "w", newline="") as f:
            csv.writer(f).writerows([["image", "obj", "class", "mask_box_ratio", "parts", "points", "flag"]] + rows)
    if a.show:
        cv2.destroyAllWindows()
    print(f"끝: 세션 {len(sessions)}, 물체 {total}, 확인 필요 {flagged} → {out}")


if __name__ == "__main__":
    main()
