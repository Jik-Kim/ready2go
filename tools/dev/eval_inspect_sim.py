#!/usr/bin/env python3
"""sim/scripts/render_eraser_test.py 가 만든 시뮬 데이터를 inspect_region 코어에 넣어 정답과 비교한다 (담당 A, 트윈 사전 검증).

  python3 tools/dev/eval_inspect_sim.py <render 출력 폴더> [--yolo models/yolo11n_ready2go_v1.pt]
박스는 기본으로 정답 직육면체를 이미지에 투영한 사각형(oracle 박스)을 쓴다 — 검출이 아니라 좌표 변환·뎁스 덩어리·yaw 계산만 시험한다.
--yolo 를 주면 학습한 YOLO 가 시뮬 컬러에서 지우개를 찾는지도 센다(합성 이미지라 실물처럼 잘 찾지 못할 수 있음).
뎁스는 노이즈·결손 없는 이상적 센서라, 실물 오차의 하한이다. 위치 오차 기준 AC-VIS-01: 1.5 cm.
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
from ready2go_vision.core.geometry import Intrinsics, drawer_from_camera  # noqa: E402
from ready2go_vision.core.inspect_real import inspect_scene  # noqa: E402


def project_box(T_drawer_cam, K, cx, cy, yaw, size):
    pts = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for z in (0.0, size[2]):
                lx, ly = sx * size[0] / 2, sy * size[1] / 2
                pts.append([cx + lx * math.cos(yaw) - ly * math.sin(yaw), cy + lx * math.sin(yaw) + ly * math.cos(yaw), z, 1.0])
    pc = (np.linalg.inv(T_drawer_cam) @ np.array(pts).T)[:3]
    u, v = K.fx * pc[0] / pc[2] + K.cx, K.fy * pc[1] / pc[2] + K.cy
    return (float(u.min()), float(v.min()), float(u.max()), float(v.max()))


def line_diff(a, b):
    """두 yaw(직선) 사이 각도 차이 (rad, 0~pi/2)."""
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--yolo", default="")
    a = ap.parse_args()
    folder = Path(a.folder)
    tr = json.loads((folder / "truth.json").read_text(encoding="utf-8"))
    K = Intrinsics(**tr["K"])
    T_drawer_cam = drawer_from_camera(np.array(tr["T_base_drawer"]), np.array(tr["T_base_cam"]))
    params = yaml.safe_load((ROOT / "config/vision_params.yaml").read_text(encoding="utf-8"))
    world = json.loads((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))
    items = world.get("world", world)["items"]
    size = tr["size_m"]
    det = None
    if a.yolo:
        from ready2go_vision.core.detector import YoloDetector
        det = YoloDetector(a.yolo, params["detector"]["conf_min"], 0)
    pos_err, yaw_err, z_err, fails, yolo_hit, rows = [], [], [], [], 0, []
    for s in tr["samples"]:
        i = s["i"]
        depth = np.load(folder / f"{i:04d}_depth.npy").astype(float)
        depth[~np.isfinite(depth)] = 0.0
        box = project_box(T_drawer_cam, K, s["position"][0], s["position"][1], s["yaw"], size)
        ok, err, js = inspect_scene([{"class": "eraser", "conf": 1.0, "box": box}], depth, K, T_drawer_cam, params, items, "drawer_top", "eraser", tr["interior_m"])
        if not ok or not json.loads(js)["target_found"]:
            fails.append((i, err or "미발견"))
            continue
        t = json.loads(js)["target"]
        dx, dy = t["pose"]["position"][0] - s["position"][0], t["pose"]["position"][1] - s["position"][1]
        pos_err.append(math.hypot(dx, dy)); z_err.append(t["top_z"] - s["top_z"])
        yaw_err.append(line_diff(t["pose"]["yaw"], s["yaw"]) if t["pose"]["yaw_valid"] else float("nan"))
        rows.append((i, round(math.hypot(dx, dy) * 1000, 1), round(math.degrees(yaw_err[-1]), 1) if not math.isnan(yaw_err[-1]) else None, round(z_err[-1] * 1000, 1), t["pose"]["yaw_valid"]))
        if det is not None:
            import cv2
            if any(d["class"] == "eraser" for d in det.detect(cv2.imread(str(folder / f"{i:04d}_color.png")))):
                yolo_hit += 1
    n = len(tr["samples"])
    pe, ye, ze = np.array(pos_err) * 1000, np.degrees(np.array(yaw_err)), np.array(z_err) * 1000
    print(f"샘플 {n}장, 계산 실패 {len(fails)}장 {fails[:5]}")
    if len(pe):
        print(f"위치 오차 mm: 평균 {pe.mean():.1f}, 중앙값 {np.median(pe):.1f}, 최대 {pe.max():.1f} (기준 15 mm = AC-VIS-01 1.5 cm)")
        yv = ye[~np.isnan(ye)]
        print(f"yaw 오차 도: 평균 {yv.mean():.1f}, 최대 {yv.max():.1f} (유효 {len(yv)}/{len(ye)}장)")
        print(f"top_z 오차 mm: 평균 {ze.mean():+.1f}, 최대 절대 {np.abs(ze).max():.1f}")
        worst = sorted(rows, key=lambda r: -r[1])[:3]
        print("위치 오차 큰 샘플(번호, mm, yaw 오차 도, top_z 오차 mm, yaw_valid):", worst)
    if det is not None:
        print(f"YOLO가 시뮬 컬러에서 지우개를 찾은 장수: {yolo_hit}/{n}")
    return 0 if len(pe) == n and pe.max() < 15 else 1


if __name__ == "__main__":
    sys.exit(main())
