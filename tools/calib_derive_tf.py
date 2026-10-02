#!/usr/bin/env python3
"""핸드-아이 결과(TCP 기준)에서 bringup용 static TF `link_6 → wrist_cam_link` 를 다시 계산한다.

    T_link6→cam_link = T_link6→TCP × T_gripper2camera × (T_cam_link→color_optical)⁻¹

입력(모두 config/calibration/):
  - T_gripper2camera.npy        핸드-아이 결과. TCP 프레임 기준, 평행이동 mm
  - calibration_meta.yaml       tcp.offset_from_pendant (mm, deg, 두산 A·B·C = ZYZ 오일러각)
                                driver_tf_used (wrist_cam_link → wrist_cam_color_optical_frame, m)
출력: derived_tf (parent link_6, child wrist_cam_link) — 기본은 meta의 현재 derived_tf와 비교한다.

사용:
  python3 tools/calib_derive_tf.py            # 계산 + derived_tf와 비교 (불일치 시 종료 코드 1)
  python3 tools/calib_derive_tf.py --print    # 계산 결과만 출력
카메라를 바꾸거나 TCP 오프셋이 바뀌면 meta의 해당 블록을 갱신한 뒤 다시 실행하고, 출력으로 derived_tf를 교체한다.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import yaml
from scipy.spatial.transform import Rotation as R

ROOT = Path(__file__).resolve().parents[1]
CALIB = ROOT / "config" / "calibration"


def pose_matrix(translation_m, rotation: R) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = rotation.as_matrix()
    T[:3, 3] = translation_m
    return T


def tcp_offset_matrix(offset: dict) -> np.ndarray:
    """펜던트 TCP 오프셋(mm, deg) → T_link6→TCP (m). 회전은 두산 posx와 같은 ZYZ 오일러각."""
    t = np.array([offset["x"], offset["y"], offset["z"]], dtype=float) / 1000.0
    rot = R.from_euler("ZYZ", [offset["rx"], offset["ry"], offset["rz"]], degrees=True)
    return pose_matrix(t, rot)


def driver_matrix(drv: dict) -> np.ndarray:
    q = drv["quaternion_xyzw"]
    return pose_matrix(drv["translation_m"], R.from_quat(q))


def derive(T_gripper2camera_mm: np.ndarray, tcp_offset: dict, driver_tf: dict) -> np.ndarray:
    N = T_gripper2camera_mm.copy()
    N[:3, 3] /= 1000.0  # mm → m
    T_link6_optical = tcp_offset_matrix(tcp_offset) @ N
    return T_link6_optical @ np.linalg.inv(driver_matrix(driver_tf))


def rotation_diff_deg(qa, qb) -> float:
    """두 쿼터니언 사이 각도(도). 부호(q 와 -q)가 달라도 같은 회전으로 본다."""
    return float(np.degrees((R.from_quat(qa).inv() * R.from_quat(qb)).magnitude()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meta", type=Path, default=CALIB / "calibration_meta.yaml")
    ap.add_argument("--npy", type=Path, default=CALIB / "T_gripper2camera.npy")
    ap.add_argument("--tol-m", type=float, default=1e-5, help="평행이동 허용 오차 (m), 기본 1e-5")
    ap.add_argument("--tol-deg", type=float, default=0.01, help="회전 허용 오차 (도), 기본 0.01")
    ap.add_argument("--print", dest="print_only", action="store_true", help="비교 없이 계산 결과만 출력")
    args = ap.parse_args()

    meta = yaml.safe_load(args.meta.read_text(encoding="utf-8"))
    T = derive(np.load(args.npy), meta["tcp"]["offset_from_pendant"], meta["driver_tf_used"])
    t = [float(f"{v:.5f}") for v in T[:3, 3]]
    q = R.from_matrix(T[:3, :3]).as_quat()
    q = [float(f"{v:.5f}") for v in (q if q[3] >= 0 else -q)]

    print("derived_tf:")
    print("  parent: link_6")
    print("  child: wrist_cam_link")
    print(f"  translation_m: {t}")
    print(f"  quaternion_xyzw: {q}")

    if args.print_only:
        return 0

    saved = meta["derived_tf"]
    dt = float(np.abs(np.array(t) - np.array(saved["translation_m"])).max())
    dr = rotation_diff_deg(q, saved["quaternion_xyzw"])
    ok = dt <= args.tol_m and dr <= args.tol_deg
    print(f"\n저장된 derived_tf와 비교: 평행이동 최대 차이 {dt:.2e} m (허용 {args.tol_m:g}), "
          f"회전 차이 {dr:.4f}° (허용 {args.tol_deg:g}) → {'일치' if ok else '불일치'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
