"""피벗 방식 손끝 오프셋 측정 (대화형). 로봇을 움직이지 않고 플랜지 posx만 읽는다.

절차: 그리퍼를 닫고, 작업대에 고정한 뾰족한 점에 손끝(노란 캡 끝 가운데)을 댄 채
직접교시로 손목 자세만 바꿔 가며 자세마다 Enter. 4개 이상(권장 6개, 서로 30° 이상 다르게).

실행 (ROS·DSR 드라이버 source 후):
    cd ros2_ws/src/ready2go_skills
    python3 -m ready2go_skills.nodes.tcp_pivot                 # 기록 + 계산
    python3 -m ready2go_skills.nodes.tcp_pivot --solve-only    # 저장된 파일로 계산만
"""
import argparse
import json
from pathlib import Path

import numpy as np

from ready2go_skills.core.tcp_pivot import MIN_POSES, MIN_SPREAD_DEG, solve_pivot

SERVICE = "/dsr01/dsr_controller2/aux_control/get_current_tool_flange_posx"
TCP_Z_MM = 228.0   # 프로젝트 TCP GripperDA_v1 (결정 #28, 비교 출력용)


def read_flange_posx(node, client) -> list[float]:
    import rclpy
    from dsr_msgs2.srv import GetCurrentToolFlangePosx
    req = GetCurrentToolFlangePosx.Request()
    req.ref = 0   # DR_BASE
    fut = client.call_async(req)
    rclpy.spin_until_future_complete(node, fut, timeout_sec=3.0)
    res = fut.result()
    if res is None or not res.success:
        raise RuntimeError("get_current_tool_flange_posx 실패")
    return [float(v) for v in res.pos]


def report(posx_list) -> None:
    res = solve_pivot(posx_list)
    t = res.tip_in_flange_mm
    print("\n=== 피벗 결과 [실측·계산] ===")
    print(f"자세 {len(posx_list)}개, 자세 간 최대 회전 차이 {res.max_spread_deg:.1f}°")
    print(f"손끝 (플랜지 기준, mm): x={t[0]:.2f} y={t[1]:.2f} z={t[2]:.2f}")
    print(f"돌출량 Δ = z − {TCP_Z_MM:.0f} = {t[2] - TCP_Z_MM:.2f} mm")
    print(f"자세별 잔차 (mm): {np.round(res.residuals_mm, 2).tolist()}  최대 {res.residuals_mm.max():.2f}")
    if res.max_spread_deg < MIN_SPREAD_DEG:
        print(f"⚠ 자세 차이가 {MIN_SPREAD_DEG:.0f}° 미만 → z 결과가 부정확할 수 있음. 손목을 더 크게 기울여 추가 기록")
    if res.residuals_mm.max() > 2.0:
        print("⚠ 잔차가 2 mm 초과인 자세가 있음 → 손끝이 고정점에서 벗어났을 가능성. 해당 자세를 다시 기록")


def main() -> int:
    ap = argparse.ArgumentParser(description="피벗 방식 손끝 오프셋 측정")
    ap.add_argument("--file", default=str(Path.home() / "tcp_pivot_posx.json"), help="기록 파일")
    ap.add_argument("--solve-only", action="store_true")
    args = ap.parse_args()
    path = Path(args.file)
    posx_list = json.loads(path.read_text()) if path.exists() else []

    if not args.solve_only:
        import rclpy
        from dsr_msgs2.srv import GetCurrentToolFlangePosx
        rclpy.init()
        node = rclpy.create_node("tcp_pivot")
        client = node.create_client(GetCurrentToolFlangePosx, SERVICE)
        if not client.wait_for_service(timeout_sec=5.0):
            raise RuntimeError(f"서비스 없음: {SERVICE} (DSR 드라이버 실행 확인)")
        print(f"기존 기록 {len(posx_list)}개 ({path}). Enter=기록, u=마지막 취소, n=새로 시작, s=계산, q=종료")
        try:
            while True:
                cmd = input(f"[{len(posx_list)}] > ").strip().lower()
                if cmd == "q":
                    break
                if cmd == "n":
                    posx_list = []
                elif cmd == "u" and posx_list:
                    posx_list.pop()
                elif cmd == "s":
                    if len(posx_list) >= MIN_POSES:
                        report(posx_list)
                    else:
                        print(f"{MIN_POSES}개 이상 필요")
                    continue
                elif cmd == "":
                    p = read_flange_posx(node, client)
                    posx_list.append(p)
                    print("  기록:", [round(v, 2) for v in p[:6]])
                path.write_text(json.dumps(posx_list))
        finally:
            node.destroy_node()
            rclpy.try_shutdown()

    if len(posx_list) >= MIN_POSES:
        report(posx_list)
    else:
        print(f"기록 {len(posx_list)}개 — 계산하려면 {MIN_POSES}개 이상 필요")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
