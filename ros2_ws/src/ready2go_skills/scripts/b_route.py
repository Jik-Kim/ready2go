"""들고 나오기 경로만 시험 (스킬 서버 없이 DSR 서비스 직접, PC2 호스트 roboton). b_flow.sh route1 | route 가 부름.
  route1  경유점 1(서랍 안)으로 관절 이동 — 시작 자세 맞추기
  route   경유점 1~4 를 movesj 로 한 번에 → 4에서 트레이 첫 칸 위(y = 트레이 가운데, 4번 높이)로 직선
경유점: config/poses.yaml carry_out.drawer_top [직접교시 B 10/06]. 트레이 칸: config/places.yaml handover_zone.
움직이기 전 펜던트 TCP·툴 확인 (calibration_meta.yaml), 다르면 안 움직임."""
import sys
from pathlib import Path

import rclpy
import yaml
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import Float64MultiArray
from dsr_msgs2.srv import (GetCurrentPosj, GetCurrentPosx, GetCurrentTcp, GetCurrentTool, GetToolForce, MoveJoint,
                           MoveLine, MoveSplineJoint, MoveStop, SetRobotMode)

CFG = Path.home() / "ready2go" / "config"
SRV = "/dsr01/dsr_controller2/"
SPLINE_VEL, SPLINE_ACC = 20.0, 20.0     # deg/s, deg/s2
LINE_VEL, LINE_ACC = 50.0, 50.0         # mm/s
JOINT_VEL = 20.0


def to_base(tf, p):
    x, y, z, w = tf["quaternion_xyzw"]
    r = ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
         (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
         (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))
    t = tf["translation_m"]
    return [t[i] + sum(r[i][j] * p[j] for j in range(3)) for i in range(3)]


class Robot:
    def __init__(self):
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
        self.n = rclpy.create_node("b_route")

    def call(self, typ, name, timeout=5.0, **kw):
        c = self.n.create_client(typ, SRV + name)
        if not c.wait_for_service(timeout_sec=3.0):
            sys.exit(f"서비스 없음: {name} — roboton 확인")
        req = kw.pop("_req", None) or typ.Request(**kw)
        f = c.call_async(req)
        rclpy.spin_until_future_complete(self.n, f, timeout_sec=timeout)
        return f.result()

    def check_tool(self):
        meta = yaml.safe_load((CFG / "calibration" / "calibration_meta.yaml").read_text(encoding="utf-8"))["tcp"]
        tcp = self.call(GetCurrentTcp, "tcp/get_current_tcp")
        tool = self.call(GetCurrentTool, "tool/get_current_tool")
        got = (tcp.info if tcp else None, tool.info if tool else None)
        want = (meta["name_on_pendant"], meta["tool_weight_on_pendant"]["name"])
        if got != want:
            sys.exit(f"펜던트 TCP·툴 {got} ≠ {want} — 안 움직임")
        self.call(SetRobotMode, "system/set_robot_mode", robot_mode=1)

    def posj(self):
        r = self.call(GetCurrentPosj, "aux_control/get_current_posj")
        return list(r.pos) if r else None

    def posx(self):
        r = self.call(GetCurrentPosx, "aux_control/get_current_posx", ref=0)
        return list(r.task_pos_info[0].data[:6]) if r and r.task_pos_info else None

    def movej(self, j):
        r = self.call(MoveJoint, "motion/move_joint", timeout=60.0, pos=[float(v) for v in j], vel=JOINT_VEL,
                      acc=JOINT_VEL, time=0.0, radius=0.0, mode=0, blend_type=0, sync_type=0)
        return bool(r and r.success)

    def movel(self, x):
        r = self.call(MoveLine, "motion/move_line", timeout=60.0, pos=[float(v) for v in x], vel=[LINE_VEL, 20.0],
                      acc=[LINE_ACC, 20.0], time=0.0, radius=0.0, ref=0, mode=0, blend_type=0, sync_type=0)
        return bool(r and r.success)

    def force(self):
        r = self.call(GetToolForce, "aux_control/get_tool_force", timeout=0.5, ref=0)
        return list(r.tool_force) if r else None

    def press(self, max_down_mm, stop_n, speed):
        """지금 자세 그대로 z 로 최대 max_down_mm 내려가며 툴 힘 z 변화가 stop_n 이상이면 정지 (내려가기 직전 0점)."""
        import time
        base = self.force()
        p0 = self.posx()
        if base is None or p0 is None:
            return "힘·좌표 조회 실패"
        target = p0[:2] + [p0[2] - max_down_mm] + p0[3:]
        self.call(MoveLine, "motion/move_line", pos=[float(v) for v in target], vel=[speed, 10.0],
                  acc=[2 * speed, 20.0], time=0.0, radius=0.0, ref=0, mode=0, blend_type=0, sync_type=1)
        t0 = time.monotonic()
        while time.monotonic() - t0 < max_down_mm / speed + 5.0:
            f = self.force()
            if f is not None and abs(f[2] - base[2]) >= stop_n:
                self.call(MoveStop, "motion/move_stop", stop_mode=2)
                time.sleep(0.3)
                return f"접촉 {f[2] - base[2]:+.1f} N → 정지, posx {[round(v, 3) for v in self.posx()]}"
            p = self.posx()
            if p is not None and p[2] <= target[2] + 0.2:
                return f"{max_down_mm} mm 내려가도 {stop_n} N 안 됨 — posx {[round(v, 3) for v in p]}"
            time.sleep(0.02)
        self.call(MoveStop, "motion/move_stop", stop_mode=2)
        return "시간 초과 — 정지"

    def movesj(self, pts):
        req = MoveSplineJoint.Request()
        ft = req.get_fields_and_field_types()
        req.pos = [Float64MultiArray(data=[float(v) for v in p]) for p in pts]
        req.pos_cnt = len(pts)
        for name, val in (("vel", SPLINE_VEL), ("acc", SPLINE_ACC)):     # 드라이버마다 스칼라·배열 다름 → 필드 형식 보고 채움
            t = ft.get(name, "")
            if t.startswith("double["):
                setattr(req, name, [val] * int(t[7:-1]))
            elif t.startswith("sequence<double"):
                setattr(req, name, [val] * 6)
            elif t:
                setattr(req, name, val)
        for name in ("time", "mode", "sync_type", "opt"):
            if name in ft:
                setattr(req, name, type(getattr(req, name))(0))
        print(f"movesj 필드: {ft}")
        r = self.call(MoveSplineJoint, "motion/move_spline_joint", timeout=90.0, _req=req)
        return bool(r and r.success)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    pts = yaml.safe_load((CFG / "poses.yaml").read_text(encoding="utf-8"))["carry_out"]["drawer_top"]
    tray = yaml.safe_load((CFG / "places.yaml").read_text(encoding="utf-8"))["handover_zone"]
    lx, ly = tray["interior_m"][:2]
    slot1 = to_base(tray["tf"], (lx / (2 * tray["slots"]), ly / 2, 0.0))      # 첫 칸 가운데 (y = 트레이 가운데)
    r = Robot()
    r.check_tool()
    if cmd == "view":                                        # drawer_top_view 로 관절 이동 하나만 (경유 없음 — 10/06 홈 경유로 사고 날 뻔함)
        poses = yaml.safe_load((CFG / "poses.yaml").read_text(encoding="utf-8"))
        print("drawer_top_view 로 관절 이동 (경유 없음)")
        print("성공" if r.movej(poses["drawer_top_view"]["drawer_top"]) else "실패")
        return
    if cmd == "press":                                       # press — 지금 자세로 z 최대 9 mm 내려가며 2 N 닿으면 정지 (5 mm/s)
        print(r.press(9.0, 2.0, 5.0))
        return
    if cmd == "movej":                                       # movej J1..J6 — 툴 확인 후 관절 이동
        if len(sys.argv) != 8:
            sys.exit("사용: movej J1 J2 J3 J4 J5 J6")
        j = [float(v) for v in sys.argv[2:8]]
        if abs(j[4]) > 133.0:
            sys.exit(f"J5 {j[4]}° — 제한 133° 넘음, 안 움직임")
        print(f"관절 이동 → {j}")
        print("성공" if r.movej(j) else "실패")
        return
    if cmd == "mvl":                                         # mvl X Y Z A B C — 툴 확인 후 직선 이동 (호스트 mvl 대신)
        if len(sys.argv) != 8:
            sys.exit("사용: mvl X Y Z A B C")
        target = [float(v) for v in sys.argv[2:8]]
        print(f"직선 이동 → {target}")
        print("성공" if r.movel(target) else "실패")
        return
    if cmd == "route1":
        print("경유점 1(서랍 안)으로 관절 이동")
        print("성공" if r.movej(pts[0]) else "실패")
        return
    if cmd != "route":
        sys.exit("사용: view | route1 | route | mvl X Y Z A B C | movej J1..J6 | press")
    cur = r.posj()
    if cur is None or max(abs(a - b) for a, b in zip(cur, pts[0])) > 2.0:
        sys.exit(f"지금 관절 {cur} 이 경유점 1과 2° 넘게 다름 — 먼저 route1")
    print("movesj 경유점 2 → 3 → 4")
    if not r.movesj(pts[1:]):
        sys.exit("movesj 실패 — 펜던트·터미널 확인")
    p4 = r.posx()
    above = [slot1[0] * 1000.0, slot1[1] * 1000.0, p4[2]] + p4[3:]
    print(f"경유점 4 {[round(v, 1) for v in p4[:3]]} → 트레이 첫 칸 위 {[round(v, 1) for v in above[:3]]} 직선")
    print("성공" if r.movel(above) else "movel 실패")


if __name__ == "__main__":
    main()
