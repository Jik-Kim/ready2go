#!/usr/bin/env python3
"""YOLO 학습·평가 (담당 A, #14). build_dataset.py 가 만든 data/yolo/dataset.yaml 로 학습하고 검증 세션 mAP50 을 기록한다.

실행(yolo-detection 컨테이너 안, /yolo_train 에 사전학습 가중치가 있음):
  python3 tools/yolo/train.py --base /yolo_train/Fruits/yolov8n.pt --epochs 100 --name v1
결과: runs/<name>/ (ultralytics 산출물) + runs/<name>/metrics.json (mAP50, 기준 0.9, 통과 여부)
가중치는 runs/<name>/weights/best.pt → 확정되면 models/ 로 복사(Git LFS, .gitignore 의 models/*.pt 예외 처리 필요).
기준: mAP50 0.9 이상, 학습에 쓰지 않은 촬영 세션 검증셋 (결정 #22 제안값 [팀 확정 필요]).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="사전학습 가중치 (예: yolov8n.pt)")
    ap.add_argument("--data", default=str(ROOT / "data/yolo/dataset.yaml"))
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--name", default="v1")
    ap.add_argument("--threshold", type=float, default=0.9, help="통과 기준 mAP50")
    ap.add_argument("--device", default="0")
    args = ap.parse_args()

    if not Path(args.data).exists():
        print(f"{args.data} 가 없습니다. 먼저 tools/yolo/build_dataset.py 를 실행하세요.", file=sys.stderr)
        return 1
    from ultralytics import YOLO

    model = YOLO(args.base)
    model.train(data=args.data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, device=args.device,
                project=str(ROOT / "runs"), name=args.name, exist_ok=True, seed=0, plots=True)
    best = ROOT / "runs" / args.name / "weights/best.pt"
    metrics = YOLO(str(best)).val(data=args.data, split="val", device=args.device, project=str(ROOT / "runs"),
                                  name=f"{args.name}_val", exist_ok=True)
    m50 = float(metrics.box.map50)
    per_class = {n: float(v) for n, v in zip(metrics.names.values(), metrics.box.ap50)}
    result = {"name": args.name, "base": args.base, "epochs": args.epochs, "imgsz": args.imgsz,
              "map50": m50, "map50_per_class": per_class, "threshold": args.threshold, "passed": m50 >= args.threshold,
              "weights": str(best)}
    (ROOT / "runs" / args.name / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
