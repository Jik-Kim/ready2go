"""10/06 B 시연 흐름 — 사용자가 직접 정한 순서·좌표 그대로 (스킬 서버 없이 DSR·RG2 직접, PC2 호스트 roboton).

  bash b_flow.sh demo        단계마다 Enter 로 진행 (q = 멈춤)
  bash b_flow.sh demo go     멈추지 않고 끝까지 (실패하면 그 자리에서 멈춤)
  bash b_flow.sh demo 5      5단계부터 (단계마다 Enter)

시작: 홈, 위 서랍 닫힘, 지우개 실측 자리(세로, 오른쪽 아래 모서리), 그리퍼 비움, 비상정지 대기.
경유점·속도 외의 판단(경로 계산·우회)은 넣지 않는다. 실패하면 정지만 하고 복구 동작 없음.
"""
import os
import sys
import time
from pathlib import Path

import rclpy
import yaml
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import Float64MultiArray
from dsr_msgs2.srv import (GetCurrentPosj, GetCurrentPosx, GetCurrentTcp, GetCurrentTool, GetToolForce, MoveJoint,
                           MoveLine, MoveSplineJoint, MoveStop, SetRobotMode)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ready2go_skills.adapters.rg2 import Rg2  # noqa: E402

CFG = Path.home() / "ready2go" / "config"
SRV = "/dsr01/dsr_controller2/"
J5_MAX = 133.0                                   # 펜던트 안전 135° [사용자 10/06]

# ---- 좌표 (전부 10/06 실측·직접교시, base mm·deg) ----
HOME = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
READY = [22.08, 20.928, 111.886, 105.463, -106.194, -45.033]              # drawer_approach (손잡이 앞 108 mm)
HANDLE = [382.105, -289.757, 268.641, 89.981, -89.964, 179.892]          # 손잡이 잡기 (실측 −291.757 에서 +y 2 mm 덜)
PULL_MM = 226.0                                                          # 최대 인출 [실측 225.3~226.3]
TOP_VIEW = [-35.473, 36.888, 10.267, -0.191, 132.849, -35.490]           # drawer_top_view
CROSS_Z = 325.0                                                          # 홈에서 올리는 높이 (서랍 앞판 295.5 위)
DOWN = [-37.487, 16.482, 65.461, -0.078, 98.068, -37.366]                # 탑뷰 → 서랍 안 (TCP 385.3, −286.7, 229.9)
TARGET_Y = -287.28                                                       # 지우개 y (stub, 비전이 되면 그 값)
TILT = [0.241, 150.117, 0.224]                                           # 손으로 기울여 지우개에 올렸던 각도 (오른쪽 30°)
PRESS_START = [521.414, TARGET_Y, 226.011]                               # 지우개 끝 위 5 mm (손 시험 x 그대로, +5 mm 취소 10/06)
DRAG_MM = 41.7                                                           # −x 로 끌기
VERTICAL = [141.741, -179.994, 141.741]                                  # 수직 (손가락 x 방향)
GRASP = [480.82, -287.47, 209.23]                                        # 끈 뒤 지우개 (바닥 + 11.5)
SAFE_Z = 300.0                                                           # 서랍 안에서 올리는 높이 (테두리 268 위)
CARRY = [[-31.045, 9.364, 69.832, -0.060, 100.801, -30.918],             # 들고 나오기 1 (movej 로)
         [-23.219, -3.090, 74.870, -0.028, 108.214, -23.088],            # 2 ┐
         [-10.854, -8.664, 79.743, -0.012, 108.914, -10.720],            # 3 ├ movesj
         [39.090, 3.303, 103.813, -0.032, 72.897, 39.239]]               # 4 ┘ (TCP z 86.1, 각도 38.535 −179.986 38.534)
TRAY_ABOVE = [578.8, 205.6, 86.146, 38.535, -179.986, 38.534]            # 트레이 첫 칸 위 (y = 트레이 가운데)
TRAY_PLACE_Z = 16.9                                                      # 트레이 바닥 3.9 + 11.5 + 1.5
HANDLE_OPEN = [382.264, -66.470, 268.556]                                # 끝까지 연 손잡이 [실측]
PUSH_Z = 268.556 + 3.6                                                   # 30 mm 벌린 손끝(TCP 아래 3.6) = 손잡이 높이
CLOSED_Y = -291.757 - 2.0                                                # 닫힌 손잡이 y + 2 mm 더 밀기 [사용자]

RG2_IP = os.environ.get("RG2_HOST") or "192.168.1.1"


class Stop(Exception):
    pass


class Robot:
    def __init__(self):
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
        self.n = rclpy.create_node("b_demo")
        self.cli = {}

    def call(self, typ, name, timeout=5.0, req=None, **kw):
        if name not in self.cli:
            self.cli[name] = self.n.create_client(typ, SRV + name)
            if not self.cli[name].wait_for_service(timeout_sec=3.0):
                raise Stop(f"서비스 없음: {name} — roboton 확인")
        f = self.cli[name].call_async(req or typ.Request(**kw))
        rclpy.spin_until_future_complete(self.n, f, timeout_sec=timeout)
        return f.result()

    def stop(self):
        self.call(MoveStop, "motion/move_stop", stop_mode=2)

    def posx(self):
        r = self.call(GetCurrentPosx, "aux_control/get_current_posx", ref=0)
        if not (r and r.task_pos_info):
            raise Stop("좌표 조회 실패")
        return list(r.task_pos_info[0].data[:6])

    def posj(self):
        r = self.call(GetCurrentPosj, "aux_control/get_current_posj")
        if not r:
            raise Stop("관절 조회 실패")
        return list(r.pos)

    def fz(self):
        r = self.call(GetToolForce, "aux_control/get_tool_force", timeout=0.5, ref=0)
        if not r:
            raise Stop("힘 조회 실패")
        return list(r.tool_force)

    def check_tool(self):
        meta = yaml.safe_load((CFG / "calibration" / "calibration_meta.yaml").read_text(encoding="utf-8"))["tcp"]
        tcp = self.call(GetCurrentTcp, "tcp/get_current_tcp")
        tool = self.call(GetCurrentTool, "tool/get_current_tool")
        got = (tcp.info if tcp else None, tool.info if tool else None)
        want = (meta["name_on_pendant"], meta["tool_weight_on_pendant"]["name"])
        if got != want:
            raise Stop(f"펜던트 TCP·툴 {got} ≠ {want}")
        self.call(SetRobotMode, "system/set_robot_mode", robot_mode=1)
        time.sleep(0.5)

    def movej(self, j, vel=20.0):
        if abs(j[4]) > J5_MAX:
            raise Stop(f"J5 {j[4]}° > {J5_MAX}°")
        r = self.call(MoveJoint, "motion/move_joint", timeout=90.0, pos=[float(v) for v in j], vel=vel, acc=vel,
                      time=0.0, radius=0.0, mode=0, blend_type=0, sync_type=0)
        if not (r and r.success):
            raise Stop("movej 실패")

    def movel(self, x, vel=50.0, rot=15.0):
        r = self.call(MoveLine, "motion/move_line", timeout=90.0, pos=[float(v) for v in x], vel=[vel, rot],
                      acc=[vel, rot], time=0.0, radius=0.0, ref=0, mode=0, blend_type=0, sync_type=0)
        if not (r and r.success):
            raise Stop("movel 실패")

    def movel_watch(self, x, vel, watch, timeout_s):
        """비동기 직선 이동 + 주기 감시. watch(posx, dforce) 가 문자열을 돌려주면 정지하고 그 문자열 반환, 도착이면 None."""
        f0 = self.fz()
        self.call(MoveLine, "motion/move_line", pos=[float(v) for v in x], vel=[vel, 10.0], acc=[vel, 10.0],   # 가속 = 속도 (스킬 서버와 같게, 가속이 크면 힘 값이 튐)
                  time=0.0, radius=0.0, ref=0, mode=0, blend_type=0, sync_type=1)
        t0 = time.monotonic()
        try:
            while time.monotonic() - t0 < timeout_s:
                p, f = self.posx(), self.fz()
                hit = watch(p, [f[i] - f0[i] for i in range(3)])
                if hit:
                    self.stop()
                    time.sleep(0.4)
                    return hit
                if max(abs(p[i] - x[i]) for i in range(3)) < 0.5:
                    time.sleep(0.2)
                    return None
                time.sleep(0.02)
        except BaseException:                    # 감시 조회 실패·Ctrl+C 도 진행 중 이동부터 정지 (#83 D 재검토 P1)
            self.stop()
            raise
        self.stop()
        raise Stop("시간 초과 — 정지")

    def movesj(self, pts, vel=20.0):
        req = MoveSplineJoint.Request()
        ft = req.get_fields_and_field_types()
        req.pos = [Float64MultiArray(data=[float(v) for v in p]) for p in pts]
        req.pos_cnt = len(pts)
        for name in ("vel", "acc"):
            t = ft.get(name, "")
            if t.startswith("double["):
                setattr(req, name, [vel] * int(t[7:-1]))
            elif t.startswith("sequence<double"):
                setattr(req, name, [vel] * 6)
            elif t:
                setattr(req, name, vel)
        for name in ("time", "mode", "sync_type"):
            if name in ft:
                setattr(req, name, type(getattr(req, name))(0))
        r = self.call(MoveSplineJoint, "motion/move_spline_joint", timeout=120.0, req=req)
        if not (r and r.success):
            raise Stop("movesj 실패")


def grip(width, force):
    g = Rg2(RG2_IP)
    try:
        return g.move(width, force)
    finally:
        g.close()


def run(r):
    """(이름, 함수) 단계 목록."""
    st = {}

    def open_drawer():
        grip(30.0, 20.0)
        p = r.posx()
        r.movel(p[:2] + [max(p[2], SAFE_Z)] + p[3:])                      # 홈에서 위로
        r.movej(READY)
        hit = r.movel_watch(HANDLE, 25.0, lambda p, d: f"손잡이 앞 {abs(d[1]):.1f} N 접촉 @ y {p[1]:.1f}" if abs(d[1]) > 12.0 else None, 20)
        if hit:
            raise Stop(hit + " — 서랍이 끝까지 닫혔는지 확인")
        s = grip(0.0, 40.0)
        if s.width_mm <= 3.0:
            grip(30.0, 20.0)
            raise Stop(f"손잡이 못 잡음 (폭 {s.width_mm:.1f} mm)")
        start = r.posx()
        end = HANDLE[:1] + [HANDLE[1] + PULL_MM] + HANDLE[2:]
        hit = r.movel_watch(end, 40.0, lambda p, d: f"{abs(d[1]):.0f} N 걸림 (인출 {p[1] - start[1]:.0f} mm)"
                            if abs(d[1]) > 30.0 else None, 20)
        moved = r.posx()[1] - start[1]
        if hit and moved < PULL_MM - 10.0:
            raise Stop(hit)
        grip(30.0, 20.0)
        p = r.posx()
        r.movel([p[0], p[1] + 60.0] + p[2:])
        print(f"   열림 {moved:.1f} mm")

    def to_top_view():
        r.movej(HOME)
        p = r.posx()
        r.movel(p[:2] + [CROSS_Z] + p[3:])
        r.movej(TOP_VIEW)

    def down_and_tilt():
        grip(0.0, 20.0)                                                 # 누르기용으로 닫기 (탑뷰에서, 서랍 밖 높이)
        r.movej(DOWN)
        p = r.posx()
        r.movel([p[0], TARGET_Y, p[2]] + p[3:])                         # y 를 목표물 y 로
        r.movel([p[0], TARGET_Y, p[2]] + TILT)                          # 제자리 30°
        r.movel(PRESS_START + TILT, vel=30.0)                           # 지우개 끝 위 5 mm

    def press_and_drag():
        hit = r.movel_watch(PRESS_START[:2] + [PRESS_START[2] - 9.0] + TILT, 5.0,
                            lambda p, d: f"{d[2]:+.1f} N" if abs(d[2]) >= 2.0 else None, 10)
        if not hit:
            raise Stop("9 mm 내려가도 접촉 없음")
        p = r.posx()
        print(f"   접촉 {hit} @ z {p[2]:.2f}")
        hit = r.movel_watch([p[0] - DRAG_MM] + p[1:], 10.0,
                            lambda q, d: f"끄는 중 {sum(v * v for v in d) ** 0.5:.0f} N" if sum(v * v for v in d) > 15.0 ** 2 else None,
                            15)
        if hit:
            raise Stop(hit)
        p = r.posx()
        r.movel(p[:2] + [p[2] + 30.0] + p[3:])

    def pick():
        p = r.posx()
        r.movel(p[:2] + [SAFE_Z] + p[3:])
        r.movel(p[:2] + [SAFE_Z] + VERTICAL)                            # 제자리 수직
        r.movel(GRASP[:2] + [SAFE_Z] + VERTICAL)
        grip(35.0, 20.0)
        r.movel(GRASP + VERTICAL, vel=15.0)
        s = grip(0.0, 7.0)
        if not 19.0 <= s.width_mm <= 25.0:
            grip(35.0, 20.0)
            raise Stop(f"지우개 못 잡음 (폭 {s.width_mm:.1f} mm, 기대 22)")
        st["width"] = s.width_mm
        r.movel(GRASP[:2] + [SAFE_Z] + VERTICAL)

    def carry_out():
        r.movej(CARRY[0])
        r.movesj(CARRY[1:])

    def place():
        r.movel(TRAY_ABOVE)
        r.movel(TRAY_ABOVE[:2] + [TRAY_PLACE_Z] + TRAY_ABOVE[3:], vel=15.0)
        grip(st.get("width", 22.0) + 6.0, 20.0)
        r.movel(TRAY_ABOVE)

    def close_drawer():
        r.movej(HOME)
        h = r.posx()
        grip(30.0, 20.0)
        r.movel([HANDLE_OPEN[0], HANDLE_OPEN[1] + 30.0, PUSH_Z] + h[3:])
        y0 = HANDLE_OPEN[1]
        hit = r.movel_watch([HANDLE_OPEN[0], CLOSED_Y, PUSH_Z] + h[3:], 30.0,
                            lambda p, d: f"{abs(d[1]):.0f} N" if abs(d[1]) > 25.0 else None, 20)
        p = r.posx()
        left = p[1] - CLOSED_Y
        if hit and left > 15.0:
            raise Stop(f"닫힘 {left:.0f} mm 전에 {hit} — 걸림")
        print(f"   닫힘 위치까지 {left:.1f} mm 남음 (밀린 거리 {y0 - p[1]:.0f} mm)")
        r.movel([p[0], p[1] + 60.0] + p[2:])
        r.movej(HOME)

    return [("서랍 열기", open_drawer), ("탑뷰", to_top_view), ("내려와서 30° 기울이기 → 지우개 끝 위", down_and_tilt),
            ("누르고 끌기", press_and_drag), ("집기", pick), ("들고 나오기 (movej 1 → movesj 2·3·4)", carry_out),
            ("트레이에 얹기", place), ("서랍 닫기 → 홈", close_drawer)]


def main():
    args = sys.argv[1:]
    go = "go" in args
    first = next((int(a) for a in args if a.isdigit()), 1)
    r = Robot()
    try:
        r.check_tool()
        steps = run(r)
        for i, (name, fn) in enumerate(steps, 1):
            if i < first:
                continue
            if not go and input(f"\n[{i}/{len(steps)}] {name} — Enter 진행, q 멈춤: ").strip().lower() == "q":
                print("멈춤")
                return
            print(f"[{i}/{len(steps)}] {name}")
            fn()
        print("\n끝")
    except Stop as e:
        try:
            r.stop()                             # 어느 단계에서 멈추든 정지 명령 (움직이지 않던 중이면 영향 없음)
        except Exception:
            pass
        print(f"\n멈춤: {e}")
    except KeyboardInterrupt:
        r.stop()
        print("\nCtrl+C — 정지 명령 보냄")
    except Exception as e:                       # 예상 못 한 오류도 로봇 정지 후 이유 출력
        try:
            r.stop()
        except Exception:
            pass
        import traceback
        traceback.print_exc()
        print(f"\n멈춤(오류): {e!r}")


if __name__ == "__main__":
    main()
