#!/usr/bin/env python3
"""전체 흐름(unpack) 시간 어림 + 줄이는 방법 비교 [사용자 10/13 "전체 플로우 시간 줄일 방법 시뮬"].

입력: A `sim/motion_check/trace_unpack.py` 결과 JSON (B b_sk unpack·스킬 서버 실제 코드를 기구학 가짜 로봇으로 돌린 명령 목록).
명령마다 속도·가속 사다리꼴로 시간을 계산하고(직선 = 거리, 회전 = 각도, 관절 = 가장 많이 도는 관절), 고정 시간(그리퍼·비전·명령 시작 지연)을 더함.
**고정 시간은 [추정]** — PC2 실행 기록(run_report / execution_log duration_sec)으로 맞춰야 함. 비교(줄어든 비율)는 고정 시간에 덜 민감.

    python3 practice/B/sim/flow_time_sim.py s2_trace.json s1_trace.json
"""
import json
import math
import sys
from collections import defaultdict

SERVER_JOINT = (80.0, 60.0)      # Bserver 관절 속도·가속 (트레이스 도구는 20 으로 둠 → 실물 값으로 바꿔 계산) [실측 설정 10/11]
GRIP_S = 1.0                     # 그리퍼 열기·닫기 한 번 [추정]
SCAN_S = 1.0                     # inspect_region 한 번 (예시 로그 0.8 s) [추정]
CMD_S = 0.15                     # 명령마다 출발·도착 확인 지연 [추정]
CARRY_PAUSE_S = 0.5              # carry.pause_s (집고 경유점 1 에서 멈춤)


def trap(d, v, a):
    """거리 d 를 최고 속도 v·가속 a 사다리꼴(정지→정지)로 가는 시간."""
    if d <= 0 or v <= 0:
        return 0.0
    a = max(a, 1e-6)
    return d / v + v / a if d >= v * v / a else 2.0 * math.sqrt(d / a)


def wrist_alt(q, j6_only_if_match=True):
    """같은 손 위치·같은 집기로 손목을 덜 돌리는 관절값 [제안, 실물 간섭 확인 전]:
    - 탑뷰 J6 −202° → +158° (같은 자세, 360° 차이)
    - 서랍 안 경유점(drag_down) J6 −30° → +150° (2손가락 그리퍼는 축으로 180° 돌려도 같은 집기 — 집는 방향은 180° 단위로 가까운 쪽)
    - 손잡이 쪽 자세(J5 < −60°, 손목 뒤집힌 해) → J4 −180°, J5 부호 반대 (플랜지가 축으로 180° 돈 같은 손 위치, 그리퍼 대칭)
    반환: (바뀐 q, J6 를 규칙으로 바꿨는지)."""
    q = list(q)
    if q[4] < -60.0:
        q[3], q[4] = q[3] - 180.0, -q[4]
    hit = False
    if abs(q[5] + 202.0) < 2.0:
        q[5], hit = 158.0, True
    elif abs(q[5] + 30.0) < 2.0 and q[4] > 60.0:
        q[5], hit = 150.0, True
    elif abs(q[5]) < 0.5 and abs(q[2] - 90.0) < 0.5:
        hit = True                                          # 홈 (J6 0 그대로)
    return q, hit


def seg_time(s, sc):
    k = s["kind"]
    if k == "movej" and sc.get("wrist"):
        q0, h0 = wrist_alt(s["joints"][0])
        q1, h1 = wrist_alt(s["joints"][-1])
        trav = [abs(q1[i] - q0[i]) for i in range(5)] + [abs(q1[5] - q0[5]) if (h0 and h1) else s["joint_travel_deg"][5]]
        s = dict(s, joint_travel_deg=trav)
    if k == "movej":
        v, a = s["vel"], s["acc"]
        if (v, a) == (20.0, 20.0):
            v, a = sc.get("server_joint", SERVER_JOINT)
        else:
            v *= sc.get("joint_scale", 1.0)
            a *= sc.get("joint_scale", 1.0)
        return trap(max(s["joint_travel_deg"]), v, a)
    v = s["vel"]
    slow = v <= 20.0                                       # 마지막 살포시 내려가기·놓기·닫기 끝 (grasp_mm_s·push_slow_mm_s)
    if not slow:
        v = sc.get("vel_map", {}).get(v, v)
    a = v * (sc.get("slow_acc_ratio", 1.0) if slow else sc.get("acc_ratio", 1.0))
    if slow and sc.get("slow_acc"):
        a = sc["slow_acc"]
    t_lin = trap(s.get("dist_mm", 0.0), v, a)
    if k == "moveb" and sc.get("blend_save"):
        t_lin *= 1.0 - sc["blend_save"]
    rv = s.get("rot_vel", 60.0) * sc.get("rot_scale", 1.0)
    return max(t_lin, trap(s.get("rot_deg", 0.0), rv, s.get("rot_acc", 60.0) * sc.get("rot_scale", 1.0)))


def flow_time(tr, sc):
    by_step, by_kind = defaultdict(float), defaultdict(float)
    for s in tr["segments"]:
        t = seg_time(s, sc) + CMD_S
        by_step[s.get("step", "?")] += t
        key = "느린 마지막(≤20 mm/s)" if s["kind"] != "movej" and s["vel"] <= 20 else s["kind"]
        by_kind[key] += t
    log = tr["log"] if isinstance(tr["log"], list) else tr["log"].splitlines()
    n_scan = sum(1 for line in log if "(인식" in line)
    n_carry = sum(1 for line in log if line.startswith("[place]"))
    fixed = len(tr["grip_events"]) * GRIP_S * sc.get("grip_scale", 1.0) + n_scan * SCAN_S + \
        n_carry * CARRY_PAUSE_S * sc.get("pause_scale", 1.0)
    by_kind["그리퍼·비전·멈춤(추정)"] += fixed
    return sum(by_step.values()) + fixed, by_step, by_kind


SCENARIOS = [
    ("지금", {}),
    ("① 느린 마지막 가속만 올림 (속도 15·10 그대로, 가속 100 mm/s²)", {"slow_acc": 100.0}),
    ("② 직선 가속 비율 1.0 → 1.5 (속도 그대로)", {"acc_ratio": 1.5}),
    ("③ 속도 한 단계 (빈 공간 300→400, 직선 200→250, 서랍 안 150→200, 관절 ×1.2)",
     {"vel_map": {300.0: 400.0, 200.0: 250.0, 150.0: 200.0}, "joint_scale": 1.2, "server_joint": (96.0, 72.0)}),
    ("④ 회전 속도 60 → 90 °/s", {"rot_scale": 1.5}),
    ("⑤ 들고 나오기 멈춤 0.5 s 빼기 + movesx (moveb 구간 −5%)", {"pause_scale": 0.0, "blend_save": 0.05}),
    ("⑥ 손목 덜 돌리기 (탑뷰 J6 +158°, 경유점 J6 +150°, 손잡이 자세 손목 뒤집기) — 실물 간섭 확인 전", {"wrist": True}),
    ("①+②+④+⑤ (속도는 그대로)", {"slow_acc": 100.0, "acc_ratio": 1.5, "rot_scale": 1.5, "pause_scale": 0.0, "blend_save": 0.05}),
    ("①+②+④+⑤+⑥ (속도는 그대로)", {"slow_acc": 100.0, "acc_ratio": 1.5, "rot_scale": 1.5, "pause_scale": 0.0,
                                   "blend_save": 0.05, "wrist": True}),
    ("전부 (①~⑥)", {"wrist": True, "slow_acc": 100.0, "acc_ratio": 1.5, "rot_scale": 1.5, "pause_scale": 0.0, "blend_save": 0.05,
                  "vel_map": {300.0: 400.0, 200.0: 250.0, 150.0: 200.0}, "joint_scale": 1.2, "server_joint": (96.0, 72.0)}),
]


def main():
    for path in sys.argv[1:]:
        tr = json.load(open(path, encoding="utf-8"))
        base, by_step, by_kind = flow_time(tr, {})
        print(f"\n== {path.split('/')[-1]} — 목표 {tr.get('target_class')}, 명령 {len(tr['segments'])}개, 그리퍼 {len(tr['grip_events'])}번")
        print(f"  지금 어림 {base:.1f} s (로봇 동작 + 그리퍼·비전 추정. 음성 안내·Runner 처리 시간 제외)")
        print("  동작 종류별: " + " · ".join(f"{k} {v:.1f}s" for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])))
        print("  단계별(상위 8): " + " · ".join(f"{k} {v:.1f}s" for k, v in sorted(by_step.items(), key=lambda kv: -kv[1])[:8]))
        for name, sc in SCENARIOS:
            t, _, _ = flow_time(tr, sc)
            print(f"  {t:6.1f} s  ({t - base:+5.1f} s, {100 * (t - base) / base:+4.0f}%)  {name}")


if __name__ == "__main__":
    main()
