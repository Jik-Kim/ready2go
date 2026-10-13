"""DSR 드라이버 서비스 클라이언트 (스킬 서버용). MultiThreadedExecutor 안의 액션 콜백에서 불러도 되도록
call_async + 완료 대기(다른 스레드가 응답을 처리)로 호출한다. 모든 호출에 타임아웃, 실패하면 None.
서비스 이름·요청 필드는 jog_gui(PR #69, 실물 확인)와 같다.
"""
import time

from rclpy.callback_groups import ReentrantCallbackGroup

from dsr_msgs2.srv import (GetCurrentPosj, GetCurrentPosx, GetCurrentTcp, GetCurrentTool, GetRobotMode, GetRobotState,
                           GetToolForce, MoveBlending, MoveJoint, MoveLine, MoveSplineJoint, MoveStop, ReleaseComplianceCtrl,
                           ReleaseForce, SetDesiredForce, SetRobotMode, TaskComplianceCtrl)

SPEC = {"posj": (GetCurrentPosj, "aux_control/get_current_posj"),
        "posx": (GetCurrentPosx, "aux_control/get_current_posx"),
        "force": (GetToolForce, "aux_control/get_tool_force"),
        "movel": (MoveLine, "motion/move_line"),
        "movesj": (MoveSplineJoint, "motion/move_spline_joint"),
        "moveb": (MoveBlending, "motion/move_blending"),
        "state": (GetRobotState, "system/get_robot_state"),
        "mode": (GetRobotMode, "system/get_robot_mode"),
        "setmode": (SetRobotMode, "system/set_robot_mode"),
        "movej": (MoveJoint, "motion/move_joint"),
        "stop": (MoveStop, "motion/move_stop"),
        "tcp": (GetCurrentTcp, "tcp/get_current_tcp"),
        "tool": (GetCurrentTool, "tool/get_current_tool"),
        # 힘 제어 [PC2 `ros2 interface show dsr_msgs2/srv/…` 10/13 확인] — 넛지 drag.force_mode
        "compliance": (TaskComplianceCtrl, "force/task_compliance_ctrl"),
        "desired_force": (SetDesiredForce, "force/set_desired_force"),
        "release_force": (ReleaseForce, "force/release_force"),
        "release_compliance": (ReleaseComplianceCtrl, "force/release_compliance_ctrl")}
AUTO = 1
REF_BASE = 0
QUICK_STOP = 2          # jog_gui 와 같은 stop_mode
FORCE_KEYS = ("compliance", "desired_force", "release_force", "release_compliance")
FC_MOD_REL = 1          # set_desired_force: 부른 순간 힘을 0 으로 보고 상대값으로 (힘 0점이 흐름 [실측 B 10/06])


class Dsr:
    def __init__(self, node, srv_prefix="/dsr01/dsr_controller2"):
        self.node = node
        group = ReentrantCallbackGroup()
        self.T = {k: v[0] for k, v in SPEC.items()}
        self.cli = {k: node.create_client(t, f"{srv_prefix}/{name}", callback_group=group)
                    for k, (t, name) in SPEC.items()}

    def ready(self, timeout=3.0):
        """기본 서비스가 다 떴는지 — 힘 제어(drag.force_mode 에서만 씀)는 빼고 봄 (힘 제어가 없는 시뮬·트윈에서도 준비로)."""
        return all(c.wait_for_service(timeout_sec=timeout) for k, c in self.cli.items() if k not in FORCE_KEYS)

    def call(self, key, timeout=2.0, **kw):
        fut = self.cli[key].call_async(self.T[key].Request(**kw))
        t0 = time.monotonic()
        while not fut.done() and time.monotonic() - t0 < timeout:
            time.sleep(0.005)
        return fut.result() if fut.done() else None

    def state(self):
        r = self.call("state", timeout=0.5)
        return r.robot_state if r else None

    def posj(self):
        r = self.call("posj")
        return list(r.pos) if r else None

    def posx(self):
        """base 기준 TCP posx [x, y, z, Rz, Ry, Rz'] (mm, deg). 실패하면 None."""
        r = self.call("posx", ref=REF_BASE)
        return list(r.task_pos_info[0].data[:6]) if r and r.task_pos_info else None

    def tool_force(self):
        """base 기준 툴 외력 [fx, fy, fz, mx, my, mz]. 영점이 시간에 따라 흐르므로 쓰기 직전에 기준값을 잡고 변화량만 쓴다
        [실측 B 10/06]. 실패하면 None."""
        r = self.call("force", timeout=0.5, ref=REF_BASE)
        return list(r.tool_force) if r else None

    def force_on(self, fz_n, stiffness, ramp_s=0.2):
        """base 기준 z 만 힘 제어로 아래로 fz_n(N) 누름 — 컴플라이언스(강성 stiffness[6]) 켠 뒤 목표 힘. 둘 다 성공해야 True.
        누르는 동안 x·y 이동 명령은 그대로 따라가고 z 는 제어기가 힘으로 맞춤."""
        r = self.call("compliance", stx=[float(v) for v in stiffness], ref=REF_BASE, time=0.0)
        if not (r and r.success):
            return False
        r = self.call("desired_force", fd=[0.0, 0.0, -float(fz_n), 0.0, 0.0, 0.0], dir=[0, 0, 1, 0, 0, 0], ref=REF_BASE,
                      time=float(ramp_s), mod=FC_MOD_REL)
        return bool(r and r.success)

    def force_off(self, ramp_s=0.2):
        """힘 제어 → 컴플라이언스 순서로 해제. 둘 다 성공해야 True (실패면 부르는 쪽이 멈추고 사람 확인)."""
        a = self.call("release_force", time=float(ramp_s))
        b = self.call("release_compliance")
        return bool(a and a.success) and bool(b and b.success)

    def tool_names(self):
        tcp, tool = self.call("tcp"), self.call("tool")
        return (tcp.info if tcp else None, tool.info if tool else None)

    def auto(self, wait_s=2.0):
        """자동 모드로 바꾸고 실제로 바뀔 때까지 기다린다 (jog_gui 와 같은 절차)."""
        r = self.call("mode")
        if r and r.robot_mode == AUTO:
            return True
        self.call("setmode", robot_mode=AUTO)
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait_s:
            time.sleep(0.1)
            r = self.call("mode")
            if r and r.robot_mode == AUTO and self.state() in (1, 2):
                time.sleep(0.2)
                return True
        return False

    def movej_async(self, joints, vel, acc):
        """비동기(sync_type=1) 관절 이동. True = 수락, False = 명시적 거부, None = 응답 없음(수락 여부 모름).
        끝은 wait_motion 이, 응답 없음·거부 처리는 skill_flow.after_command 가 본다."""
        r = self.call("movej", pos=[float(v) for v in joints], vel=float(vel), acc=float(acc),
                      time=0.0, radius=0.0, mode=0, blend_type=0, sync_type=1)
        return None if r is None else bool(r.success)

    def movesj_async(self, points, vel, acc):
        """비동기 관절 스플라인 (경유점 posj 목록을 한 번에 부드럽게). vel·acc 형식(스칼라·배열)은 드라이버 필드를 보고 채움.
        반환은 movej_async 와 같다."""
        from std_msgs.msg import Float64MultiArray
        req = self.T["movesj"].Request()
        ft = req.get_fields_and_field_types()
        req.pos = [Float64MultiArray(data=[float(v) for v in p]) for p in points]
        req.pos_cnt = len(points)
        for name, val in (("vel", float(vel)), ("acc", float(acc))):
            t = ft.get(name, "")
            if t.startswith("double["):
                setattr(req, name, [val] * int(t[7:-1]))
            elif t.startswith("sequence<double"):
                setattr(req, name, [val] * 6)
            elif t:
                setattr(req, name, val)
        for name in ("time", "mode"):
            if name in ft:
                setattr(req, name, type(getattr(req, name))(0))
        req.sync_type = 1
        fut = self.cli["movesj"].call_async(req)
        t0 = time.monotonic()
        while not fut.done() and time.monotonic() - t0 < 2.0:
            time.sleep(0.005)
        r = fut.result() if fut.done() else None
        return None if r is None else bool(r.success)

    def movel_async(self, posx, vel, acc, rot_vel=30.0, rot_acc=60.0, radius=0.0):
        """비동기(sync_type=1) 직선 이동, base 기준 절대 posx. vel·acc mm/s, rot_vel·rot_acc deg/s.
        radius > 0 = 다음 이동과 이 반지름 안에서 이어짐 (blend_type 0, 다음 명령은 끝 radius 안에 들어온 뒤 보냄 — skill_server).
        반환은 movej_async 와 같다 (True·False·None)."""
        r = self.call("movel", pos=[float(v) for v in posx], vel=[float(vel), float(rot_vel)],
                      acc=[float(acc), float(rot_acc)],
                      time=0.0, radius=float(radius), ref=REF_BASE, mode=0, blend_type=0, sync_type=1)
        return None if r is None else bool(r.success)

    def moveb_async(self, points, radii, vel, acc, rot_vel=30.0, rot_acc=60.0):
        """비동기 직선 블렌딩 (posx 경유점 여러 개를 직선으로 잇고 모서리를 반지름 mm 로 둥글게, 마지막 점에서만 정지).
        구간 = [목표 posx 6, 원호 보조점 6(직선이면 0), 종류(직선 0), 반지름] [두산 MoveBlending, practice/B 10/06 표].
        드라이버 필드가 예상(segment·pos_cnt)과 다르면 명령을 보내지 않고 False. 반환은 movej_async 와 같다."""
        from std_msgs.msg import Float64MultiArray
        req = self.T["moveb"].Request()
        ft = req.get_fields_and_field_types()
        if "segment" not in ft or "pos_cnt" not in ft:
            self.node.get_logger().error(f"MoveBlending 필드가 예상과 다름 — 보내지 않음: {ft}")
            return False
        req.segment = [Float64MultiArray(data=[float(v) for v in p] + [0.0] * 6 + [0.0, float(r)])
                       for p, r in zip(points, radii)]
        req.pos_cnt = len(points)
        for name, val in (("vel", [float(vel), float(rot_vel)]), ("acc", [float(acc), float(rot_acc)])):
            if name in ft:
                setattr(req, name, val if "[" in ft[name] or "sequence" in ft[name] else val[0])
        for name in ("time", "ref", "mode"):
            if name in ft:
                setattr(req, name, type(getattr(req, name))(0))      # ref 0 = base, mode 0 = 절대
        req.sync_type = 1
        fut = self.cli["moveb"].call_async(req)
        t0 = time.monotonic()
        while not fut.done() and time.monotonic() - t0 < 2.0:
            time.sleep(0.005)
        r = fut.result() if fut.done() else None
        return None if r is None else bool(r.success)

    def stop(self):
        """정지 명령이 받아들여졌는지 반환 (응답 없음·실패면 False)."""
        r = self.call("stop", stop_mode=QUICK_STOP)
        return bool(r and r.success)
