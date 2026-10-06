"""DSR 드라이버 서비스 클라이언트 (스킬 서버용). MultiThreadedExecutor 안의 액션 콜백에서 불러도 되도록
call_async + 완료 대기(다른 스레드가 응답을 처리)로 호출한다. 모든 호출에 타임아웃, 실패하면 None.
서비스 이름·요청 필드는 jog_gui(PR #69, 실물 확인)와 같다.
"""
import time

from rclpy.callback_groups import ReentrantCallbackGroup

from dsr_msgs2.srv import (GetCurrentPosj, GetCurrentPosx, GetCurrentTcp, GetCurrentTool, GetRobotMode, GetRobotState,
                           GetToolForce, MoveJoint, MoveLine, MoveStop, SetRobotMode)

SPEC = {"posj": (GetCurrentPosj, "aux_control/get_current_posj"),
        "posx": (GetCurrentPosx, "aux_control/get_current_posx"),
        "force": (GetToolForce, "aux_control/get_tool_force"),
        "movel": (MoveLine, "motion/move_line"),
        "state": (GetRobotState, "system/get_robot_state"),
        "mode": (GetRobotMode, "system/get_robot_mode"),
        "setmode": (SetRobotMode, "system/set_robot_mode"),
        "movej": (MoveJoint, "motion/move_joint"),
        "stop": (MoveStop, "motion/move_stop"),
        "tcp": (GetCurrentTcp, "tcp/get_current_tcp"),
        "tool": (GetCurrentTool, "tool/get_current_tool")}
AUTO = 1
REF_BASE = 0
QUICK_STOP = 2          # jog_gui 와 같은 stop_mode


class Dsr:
    def __init__(self, node, srv_prefix="/dsr01/dsr_controller2"):
        self.node = node
        group = ReentrantCallbackGroup()
        self.T = {k: v[0] for k, v in SPEC.items()}
        self.cli = {k: node.create_client(t, f"{srv_prefix}/{name}", callback_group=group)
                    for k, (t, name) in SPEC.items()}

    def ready(self, timeout=3.0):
        return all(c.wait_for_service(timeout_sec=timeout) for c in self.cli.values())

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

    def movel_async(self, posx, vel, acc, rot_vel=30.0, rot_acc=60.0):
        """비동기(sync_type=1) 직선 이동, base 기준 절대 posx. vel·acc mm/s, rot_vel·rot_acc deg/s.
        반환은 movej_async 와 같다 (True·False·None)."""
        r = self.call("movel", pos=[float(v) for v in posx], vel=[float(vel), float(rot_vel)],
                      acc=[float(acc), float(rot_acc)],
                      time=0.0, radius=0.0, ref=REF_BASE, mode=0, blend_type=0, sync_type=1)
        return None if r is None else bool(r.success)

    def stop(self):
        """정지 명령이 받아들여졌는지 반환 (응답 없음·실패면 False)."""
        r = self.call("stop", stop_mode=QUICK_STOP)
        return bool(r and r.success)
