"""[10/15 PC2 차키 사고] carry.spline movesx 점의 손목 각도 숫자 점프 → 제어기 경로 가정별 J5.

probe_before/after.json (probe_dump.py 로 스킬 노드가 보낸 점을 모은 것) 을 읽어
  ① 이웃 점 사이 각도 숫자(A·C) 차이 최대
  ② 제어기가 6개 숫자를 각각 스플라인으로 잇는다고 가정 → IK(sim/motion_check/m0609_kin) J5 최대
  ③ 쿼터니언 4개 숫자를 부호 정리 없이 잇는다고 가정 → J5 최대
를 출력. 저장소 루트에서: python3 practice/B/sim/spline_wrist/analyze.py   [추정 — 제어기 내부 모델은 모름]
"""
import json, math, sys
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation as Rot
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "sim" / "motion_check"))
import m0609_kin as K
HERE = Path(__file__).resolve().parent

def spline6(P, n=400):
    P = np.array(P, float); m = len(P)
    d = np.maximum(np.linalg.norm(np.diff(P[:, :3], axis=0), axis=1), 1e-6)
    t = np.concatenate([[0], np.cumsum(d)])
    out = []
    for dim in range(6):
        y = P[:, dim]; h = np.diff(t); A = np.zeros((m, m)); b = np.zeros(m); A[0, 0] = A[-1, -1] = 1
        for i in range(1, m - 1):
            A[i, i - 1] = h[i - 1]; A[i, i] = 2 * (h[i - 1] + h[i]); A[i, i + 1] = h[i]
            b[i] = 3 * ((y[i + 1] - y[i]) / h[i] - (y[i] - y[i - 1]) / h[i - 1])
        c = np.linalg.solve(A, b); bb = np.diff(y) / h - h * (2 * c[:-1] + c[1:]) / 3; dd = (c[1:] - c[:-1]) / (3 * h)
        ts = np.linspace(0, t[-1], n); i = np.clip(np.searchsorted(t, ts) - 1, 0, m - 2); dt = ts - t[i]
        out.append(y[i] + bb[i] * dt + c[i] * dt ** 2 + dd[i] * dt ** 3)
    return np.stack(out, 1)

def run(path, q0):
    q = np.array(q0, float); j5max, worst_tilt, fails = q[4], 0.0, 0
    for p in path:
        T = K.posx_to_T(list(p))
        tilt = math.degrees(math.acos(max(-1, min(1, -T[2, 2]))))
        worst_tilt = max(worst_tilt, tilt)
        q, ok = K.ik(T, q)
        fails += (not ok); j5max = max(j5max, abs(q[4]))
    return j5max, worst_tilt, fails

def main_euler():
  for tag in ("before", "after"):
      R = json.load(open(HERE / f"probe_{tag}.json"))
      print(f"\n=== {'고치기 전' if tag == 'before' else '고친 뒤'} (제어기가 6개 숫자를 각각 스플라인으로 잇는다고 가정) ===")
      for r in R:
          if not r["via"] or r["slot"] != 2 or r["nvia"] != 8: continue
          start = r["start"]
          A = [v[3] for v in [start] + r["via"]]; C = [v[5] for v in [start] + r["via"]]
          jump = max(max(abs(A[i + 1] - A[i]), abs(C[i + 1] - C[i])) for i in range(len(A) - 1))
          path = spline6([start] + r["via"])
          q0 = [-30.116, 11.578, 64.539, -0.069, 103.885, -29.994 + r["dturn"]]
          q0, _ = K.ik(K.posx_to_T(list(start)), q0)
          j5, tilt, fails = run(path, q0)
          print(f"direct={r['direct']!s:5} 손목회전 {r['dturn']:6.0f}°: 점간 각도숫자 최대 {jump:5.0f}° | 그리퍼 수직에서 최대 기울기 {tilt:5.1f}° | J5 최대 {j5:5.1f}° {'← 한계 133° 넘음' if j5 > 133 else ''}{' IK실패 ' + str(fails) if fails else ''}")


def quat(p):  # ZYZ deg → quaternion (x,y,z,w), 부호 그대로 (반구 맞추지 않음)
    return Rot.from_euler("ZYZ", p[3:6], degrees=True).as_quat()

def path_q(P, align):
    Q = [quat(p) for p in P]
    if align:
        for i in range(1, len(Q)):
            if np.dot(Q[i], Q[i - 1]) < 0: Q[i] = -Q[i]
    X = [list(p[:3]) + list(q) for p, q in zip(P, Q)]
    # 7개 숫자 스플라인 (위치 3 + 쿼터니언 4)
    P7 = np.array(X, float); m = len(P7)
    d = np.maximum(np.linalg.norm(np.diff(P7[:, :3], axis=0), axis=1), 1e-6); t = np.concatenate([[0], np.cumsum(d)])
    out = []
    for dim in range(7):
        y = P7[:, dim]; h = np.diff(t); A = np.zeros((m, m)); b = np.zeros(m); A[0, 0] = A[-1, -1] = 1
        for i in range(1, m - 1):
            A[i, i - 1] = h[i - 1]; A[i, i] = 2 * (h[i - 1] + h[i]); A[i, i + 1] = h[i]
            b[i] = 3 * ((y[i + 1] - y[i]) / h[i] - (y[i] - y[i - 1]) / h[i - 1])
        c = np.linalg.solve(A, b); bb = np.diff(y) / h - h * (2 * c[:-1] + c[1:]) / 3; dd = (c[1:] - c[:-1]) / (3 * h)
        ts = np.linspace(0, t[-1], 400); i = np.clip(np.searchsorted(t, ts) - 1, 0, m - 2); dt = ts - t[i]
        out.append(y[i] + bb[i] * dt + c[i] * dt ** 2 + dd[i] * dt ** 3)
    out = np.stack(out, 1)
    return out

def run_q(path, q0):
    q = np.array(q0, float); j5max = abs(q[4]); tiltmax = 0.0; fails = 0
    for r in path:
        qq = r[3:7]; nrm = np.linalg.norm(qq)
        T = np.eye(4); T[:3, :3] = Rot.from_quat(qq / max(nrm, 1e-9)).as_matrix(); T[:3, 3] = np.array(r[:3]) / 1000.0
        tilt = math.degrees(math.acos(max(-1, min(1, -T[2, 2])))); tiltmax = max(tiltmax, tilt)
        q, ok = K.ik(T, q); fails += (not ok); j5max = max(j5max, abs(q[4]))
    return j5max, tiltmax, fails

def main_quat():
    for tag in ("before", "after"):
        R = json.load(open(HERE / f"probe_{tag}.json"))
        print(f"\n=== {'고치기 전' if tag == 'before' else '고친 뒤'} (제어기가 자세를 쿼터니언 4개 숫자로 잇는다고 가정, 부호 정리 안 함) ===")
        for r in R:
            if not r["via"] or r["slot"] != 2 or r["nvia"] != 8 or not r["direct"]:
                continue
            P = [r["start"]] + r["via"]
            q0, _ = K.ik(K.posx_to_T(list(r["start"])), [-30.116, 11.578, 64.539, -0.069, 103.885, -29.994 + r["dturn"]])
            j5, tilt, fails = run_q(path_q(P, False), q0)
            print(f"손목회전 {r['dturn']:6.0f}°: 그리퍼 기울기 최대 {tilt:5.1f}° | J5 최대 {j5:5.1f}°{'  ← 한계 133° 넘음' if j5 > 133 else ''}{'  IK실패 ' + str(fails) if fails else ''}")


if __name__ == "__main__":
    main_euler()
    main_quat()
