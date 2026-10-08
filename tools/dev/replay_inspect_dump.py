#!/usr/bin/env python3
"""inspect_region 노드가 dump_dir 에 저장한 .npz 를 로봇 없이 다시 계산한다 (담당 A, 실물 진단).

  python3 tools/dev/replay_inspect_dump.py <덤프 .npz 또는 폴더> [--truth X Y YAW] [--dz-mm D]
저장된 검출(YOLO 박스, 분할 모델이면 덤프 masks 마스크)·뎁스·K·TF 를 그대로 쓰고, 현재 config/vision_params.yaml 로 inspect_scene 과 바닥 진단을 다시 돌린다.
  --truth   손끝 터치 정답 (서랍 좌표 x y m, yaw rad — ready2go_skills/core/stub_measure.py 출력). 위치 오차를 함께 출력
  --dz-mm   서랍 원점을 z 로 이만큼 옮겨 다시 계산 (원점 보정 차이가 top_z·위치에 주는 영향 확인용, 예: -3.0)
  --weights 저장된 검출 대신 이 YOLO 가중치로 저장된 컬러 이미지를 다시 검출 (같은 실물 프레임에서 모델 비교, ultralytics 필요)
AC-VIS-01 위치 오차 기준 1.5 cm. 정답이 없는 덤프는 결과만 출력한다.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ros2_ws/src/ready2go_vision"))
from ready2go_vision.core.floor_probe import floor_probe  # noqa: E402
from ready2go_vision.core.geometry import Intrinsics, drawer_from_camera  # noqa: E402
from ready2go_vision.core.inspect_real import inspect_scene  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--truth", nargs=3, type=float, metavar=("X", "Y", "YAW"))
    ap.add_argument("--dz-mm", type=float, default=0.0)
    ap.add_argument("--weights", default="")
    a = ap.parse_args()
    p = Path(a.path)
    files = sorted(p.glob("inspect_*.npz")) if p.is_dir() else [p]
    params = yaml.safe_load((ROOT / "config/vision_params.yaml").read_text(encoding="utf-8"))
    world = json.loads((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))
    items = world.get("world", world)["items"]
    detector = None
    if a.weights:
        from ready2go_vision.core.detector import YoloDetector
        detector = YoloDetector(a.weights, params["detector"]["conf_min"], 0)
    for f in files:
        z = np.load(f, allow_pickle=False)
        meta = json.loads(str(z["meta"]))
        K = Intrinsics(*meta["K"])
        T_base_drawer = z["T_base_drawer"].copy()
        T_base_drawer[:3, 3] += T_base_drawer[:3, 2] * a.dz_mm / 1000.0       # 서랍 z 축 방향으로 원점 이동
        T = drawer_from_camera(T_base_drawer, z["T_base_cam"])
        depth = z["depth_m"].astype(float)
        dets = detector.detect(z["color"]) if detector else [{**d, "box": tuple(d["box"])} for d in meta["detections"]]
        if not detector and "masks" in z.files:                                # 분할 모델 덤프: 저장된 마스크 복원
            w = z["color"].shape[1]
            for d, mk in zip(dets, np.unpackbits(z["masks"], axis=-1)[..., :w].astype(bool)):
                d["mask"] = mk
        req = meta["request"]
        debug = []
        ok, err, js = inspect_scene(dets, depth, K, T, params, items, req["region"], req["search_target"], meta["interior_m"], debug)
        floor = floor_probe(depth, K, T, meta["interior_m"], [d["box"] for d in dets], params["floor_probe"])
        print(f"== {f.name} (저장 당시 success={meta['success']} {meta['error_code']}, 버전 {meta['versions'].get('code_sha') or '?'}, "
              f"검출 {'다시: ' + Path(a.weights).name if detector else '저장된 것'})")
        print(f"  재계산 success={ok} {err} {js}")
        for d in debug:
            print(f"  검출 {json.dumps(d, ensure_ascii=False)}")
        print(f"  바닥(카메라, 서랍 z) {json.dumps(floor)}  원점 이동 {a.dz_mm:+.1f} mm")
        if a.truth and ok and json.loads(js)["target_found"]:
            t = json.loads(js)["target"]["pose"]
            dx, dy = t["position"][0] - a.truth[0], t["position"][1] - a.truth[1]
            dyaw = abs(t["yaw"] - a.truth[2]) % math.pi
            print(f"  정답 대비: dx {dx * 1000:+.1f} mm, dy {dy * 1000:+.1f} mm, 거리 {math.hypot(dx, dy) * 1000:.1f} mm "
                  f"(기준 15 mm), yaw 차이 {math.degrees(min(dyaw, math.pi - dyaw)):.1f}° (yaw_valid={t['yaw_valid']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
