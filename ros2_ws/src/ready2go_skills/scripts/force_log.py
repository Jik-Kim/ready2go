#!/usr/bin/env python3
"""정지 중 툴 힘 기록 — 지속 외력 판정 기준(W1 external_force) 실측용 [C 10/13 2단계 요청]. **로봇·그리퍼 명령 없음** (읽기만).

    python3 scripts/force_log.py a_empty           # ① 빈손, 홈에서 멈춘 채 30 s
    python3 scripts/force_log.py b_holding         # ② 지우개 쥔 채
    python3 scripts/force_log.py c_push --sec 20   # ③ 사람이 그리퍼를 손으로 지그시 미는 동안

DSR `aux_control/get_tool_force`(ref 0 = base, 스킬 서버 tool_force 와 같음)를 --hz 로 읽어 CSV 저장 + 요약 출력.
요약: 축별 평균·표준편차, 처음 1 s 평균(영점) 대비 힘 크기(Fx·Fy·Fz) 변화의 최대·p99, 읽기 간격(신선도).
"""
import argparse
import csv
import math
import time
from pathlib import Path

import rclpy
from dsr_msgs2.srv import GetToolForce

SRV = "/dsr01/dsr_controller2/aux_control/get_tool_force"


def pct(xs, q):
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))] if s else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("--sec", type=float, default=30.0)
    ap.add_argument("--hz", type=float, default=20.0)
    ap.add_argument("--out", default=str(Path.home() / "ready2go_force_logs"))
    a = ap.parse_args()
    rclpy.init()
    node = rclpy.create_node("force_log")
    cli = node.create_client(GetToolForce, SRV)
    if not cli.wait_for_service(timeout_sec=5.0):
        raise SystemExit(f"{SRV} 없음 — roboton 켜졌는지, r2genv 했는지")
    rows, gaps, fails, last = [], [], 0, None
    t0 = time.monotonic()
    print(f"[{a.label}] {a.sec:.0f} s 기록 시작 ({a.hz:.0f} Hz) — 로봇은 움직이지 않음")
    while time.monotonic() - t0 < a.sec:
        tick = time.monotonic()
        f = cli.call_async(GetToolForce.Request(ref=0))
        rclpy.spin_until_future_complete(node, f, timeout_sec=1.0)
        now = time.monotonic()
        r = f.result() if f.done() else None
        if r is None or len(r.tool_force) < 6:
            fails += 1
        else:
            rows.append([round(now - t0, 3)] + [float(v) for v in r.tool_force[:6]])
            if last is not None:
                gaps.append(now - last)
            last = now
        time.sleep(max(0.0, 1.0 / a.hz - (time.monotonic() - tick)))
    node.destroy_node()
    rclpy.shutdown()
    if not rows:
        raise SystemExit("읽은 값 없음")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%m%d_%H%M%S')}_{a.label}.csv"
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t_s", "fx", "fy", "fz", "mx", "my", "mz"])
        w.writerows(rows)
    base = [r for r in rows if r[0] <= 1.0] or rows[:1]
    zero = [sum(r[i] for r in base) / len(base) for i in range(1, 4)]
    dev = [math.dist(r[1:4], zero) for r in rows]
    print(f"\n[{a.label}] 저장 {path}")
    print(f"  읽음 {len(rows)} · 실패 {fails} · 간격 평균 {1000 * sum(gaps) / max(1, len(gaps)):.0f} ms · 최대 {1000 * max(gaps or [0]):.0f} ms")
    for i, k in enumerate(("Fx", "Fy", "Fz"), start=1):
        v = [r[i] for r in rows]
        m = sum(v) / len(v)
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
        print(f"  {k}: 평균 {m:+7.2f} N · 표준편차 {sd:5.2f} · 최소 {min(v):+7.2f} · 최대 {max(v):+7.2f}")
    print(f"  처음 1 s 대비 |ΔF|: p50 {pct(dev, 0.5):.2f} · p99 {pct(dev, 0.99):.2f} · 최대 {max(dev):.2f} N")


if __name__ == "__main__":
    main()
