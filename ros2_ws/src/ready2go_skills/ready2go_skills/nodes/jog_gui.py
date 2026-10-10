"""실물 로봇 조그 창 R2G Jog (교시·측정용 도구, 태스크 실행 경로 아님). 강의 rokey_cobot2 jog 화면을 바탕으로 안전 수정.
화면 배치 10/08 새로 (사용자 시안 v22 확정, @9기_SDG): 위 상태줄(툴·툴 힘·꾹 누르기) → posx/posj → 관절 | 직선 이동 →
좌표로 이동 → 그리퍼 기울이기 | 정렬·회전 | 그리퍼(+직접교시) | 비상정지 해제·정지 → gohome·상태.

강의 jog와 다른 점
- +/- 는 입력칸 숫자가 아니라 로봇의 '지금' 위치를 새로 읽어 증분만큼만 움직인다
  → 직접교시·다른 도구로 옮긴 뒤 눌러도 옛 위치로 돌아가지 않는다 (강의 jog의 충돌 위험).
- +/- 를 꾹 누르면(0.35초 이상) DSR 연속 조그로 누르는 동안 움직이고, 떼면 멈춘다.
  멈춤: 손 떼기 / 버튼 밖으로 나가기 / 창 포커스 잃기 / 한 번에 최대 HOLD_MAX_S초.
- 입력칸·posx/posj 칸은 0.3초마다 갱신. 직접 고친 입력칸만 노란색으로 남고 '입력값으로 movej/movel' 목표가 된다.
- 좌표로 이동: posx([...]) → movel, posj([...]) → movej (숫자만이면 묻기). 이동 전 확인창, posj 는 J5 ≤ 133°·J3 ≥ 10°.
- 움직이는 중 누른 버튼은 무시, 움직이기 전에 자동 모드로 바꾸고 바뀔 때까지 기다린다. 거부되면 상태·모드를 표시.
- 시작·'다시 확인' 때 펜던트 툴 설정(TCP, 툴 무게)이 config와 같은지 확인하고, 다르면 이동 버튼을 막는다
  (10/04 툴 설정이 풀려 좌표가 플랜지 기준으로 읽힌 사고, #6).
- 정렬 x / y / z / 그리퍼 정렬 (core/pose_math.py): TCP 위치 고정, 한 번에 돌기(170° 넘으면 2번), 돌기 전 확인창, 끝나면 직접교시.
- 그리퍼 회전 ↺ − / ↻ + (기본 90°): 툴 z 둘레, TCP 위치 고정. + = 수직 아래 자세에서 위에서 볼 때 시계 방향.
- 그리퍼 기울이기 왼(−x)·오른(+x)·앞(+y)·뒤(−y)·수직: TCP 위치 고정, 수직 아래에서 각도 칸(기본 30°)만큼 손끝을 그쪽으로.
- 툴 힘(base, 관절 토크 추정): reset 누른 순간 기준의 변화량 표시 (화면 표시만, 로봇·스킬 서버에 영향 없음).
- 그리퍼: 닫기(힘 칸) / 최대 열기 / 폭만큼 열기(폭 칸). 지금 폭·잡힘을 2초마다 읽음.
- 정지 버튼·Esc 키(입력칸 밖이면 Space 도): 정지. 비상정지 해제: 소프트웨어 안전정지(충돌·한계)만, 확인창 뒤
  (물리 비상정지 버튼은 직접 풀어야 함). gohome(확인창).
- 창 닫기(X)·Ctrl+C: 움직이는 중이면 정지 명령을 보내고 깔끔하게 종료.

실행 (PC2 호스트, DSR 드라이버 실행 중, cobot2_ws 등 dsr_msgs2를 source 한 터미널):
    ros2 run ready2go_skills jog_gui                 # colcon 빌드 후
    cd ros2_ws/src/ready2go_skills && python3 -m ready2go_skills.nodes.jog_gui   # 빌드 없이
옵션: --config-dir <저장소>/config (기본: 저장소 config 자동 탐색), --rg2-ip (기본: 환경변수 RG2_HOST)
필요: python3-tk, python3-yaml
"""
import argparse
import math
import os
import re
import signal
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox

import rclpy
import yaml
from dsr_msgs2.srv import (GetCurrentPosj, GetCurrentPosx, GetCurrentTcp, GetCurrentTool, GetRobotMode,
                           GetRobotState, GetToolForce, Jog, MoveJoint, MoveLine, MoveStop, SetRobotMode)
try:                                 # 비상정지 해제용 — 없는 드라이버면 버튼만 막음
    from dsr_msgs2.srv import SetRobotControl, SetSafeStopResetType
except ImportError:
    SetRobotControl = SetSafeStopResetType = None

from ready2go_skills.adapters.rg2 import Rg2
from ready2go_skills.core.pose_math import (align_target, roll_target, rot, rotation_angle, step_target, tilt_target,
                                            waypoints, wrap)

SRV = "/dsr01/dsr_controller2"
HOLD_DELAY_MS = 350          # 이보다 오래 누르면 '꾹 누르기'
HOLD_MAX_S = 5.0             # 꾹 누르기 한 번에 최대 시간
REFRESH_TIMEOUT_S = 0.5      # 화면 갱신용 조회 타임아웃 (드라이버가 느려도 정지 처리가 밀리지 않게, #69 PM 검토)
STEP_CONFIRM_DEG = 10.0      # 한 칸 이동이 이보다 크면 확인창 (관절·회전)
STEP_CONFIRM_MM = 20.0       # 한 칸 이동이 이보다 크면 확인창 (직선)
HOME_VEL = 40.0              # gohome 관절 속도 deg/s
ALIGN_VEL, ALIGN_ACC = 30.0, 60.0   # 회전(축 정렬·기울이기·그리퍼 회전) 속도 deg/s·가속 (10/06 사용자 요청으로 실제 10 → 30°/s)
ALIGN_STEP_DEG = 170.0       # 이보다 큰 회전만 나눔 — 180° 근처는 도는 방향이 정해지지 않아서 (사용자 요청 10/06: 중간 멈춤 없앰)
PIECE_TIMEOUT_EXTRA_S = 5.0  # 회전 시간(각도 / ALIGN_VEL) + 이 안에 도착하지 않으면 정지
JOINT_VEL, JOINT_ACC, LINE_VEL, LINE_ACC = 20, 20, 30, 60    # 슬라이더 기본값 (강의 jog 60은 빠름)
STATE = {0: "초기화", 1: "대기", 2: "이동 중", 3: "서보 꺼짐", 4: "직접교시", 5: "안전 정지",
         6: "비상정지", 7: "홈", 8: "복구 모드", 9: "안전 정지2", 10: "서보 꺼짐2", 15: "준비 안 됨"}
ALIGN_NAMES = {"x": "x 정렬 (수평·바깥)", "y": "y 정렬 (수평·-y)", "z": "z 정렬 (수직 아래)", "r": "그리퍼 정렬 (가까운 90°)"}
TILT_DIRS = (("← 왼 (−x, 로봇 쪽)", (-1.0, 0.0)), ("오른 (+x) →", (1.0, 0.0)),
             ("앞 (+y, 내 반대쪽)", (0.0, 1.0)), ("뒤 (−y, 내 쪽)", (0.0, -1.0)))   # 서동권 자리(base −y)에서 본 방향
J5_MAX, J3_MIN = 133.0, 10.0        # 좌표로 이동(posj) 거부 — params/skills.yaml joint_limits_deg 와 같음 [사용자 10/06]
# 비상정지 해제 (system/set_robot_control) [PC2 `ros2 interface show dsr_msgs2/srv/SetRobotControl` 10/08 확인]:
#   2 CONTROL_RESET_SAFET_STOP = SAFE_STOP(5) → STANDBY, 3 CONTROL_RESET_SAFET_OFF = SAFE_OFF(3) → STANDBY.
#   SAFE_STOP2(9)·SAFE_OFF2(10) 는 복구 모드(4·5 → 빼내기 → 7)를 거쳐야 해서 펜던트로 (여기서 보내지 않음).
RECOVER = {5: 2, 3: 3}
RECOVER_BY_PENDANT = (9, 10)
# 안전정지 리셋(2) 전에 reset type 을 PROGRAM_STOP(0) 으로 — 1(PROGRAM_RESUME)이 남아 있으면 자동 모드에서 멈췄던
# 동작이 재개될 수 있음 (E #171 검수 P1, NFR-SAF-02). Doosan 예제도 리셋 직전 SAFE_STOP_RESET_TYPE_DEFAULT 설정.
SAFE_STOP_RESET_PROGRAM_STOP = 0
C = {"bg": "#e9e9e7", "panel": "#f7f7f5", "line": "#c9c9c4", "sub": "#5d6470", "blue": "#2f6fde", "red": "#d33a2c",
     "green": "#e7f4ec", "amber": "#fff4dc", "posx": "#e8f0fd", "posj": "#f3ece0", "dark": "#2b2b2b", "silver": "#d5d9de"}
TILT_DEFAULT, TILT_MAX = 30.0, 45.0
ROLL_DEFAULT, ROLL_MAX = 90.0, 180.0     # 그리퍼 회전(툴 z 둘레) 한 번에


def find_config_dir():
    env = os.environ.get("READY2GO_CONFIG_DIR")
    if env:
        return Path(env)
    for d in Path(__file__).resolve().parents:       # 소스·symlink 설치면 저장소 config를 찾음
        if (d / "config" / "poses.yaml").exists():
            return d / "config"
    return Path.home() / "ready2go" / "config"


def load_settings(config_dir):
    """펜던트 TCP·툴 이름은 calibration_meta.yaml, 홈 관절각은 poses.yaml에서 읽는다 (값은 한 곳에만)."""
    meta = yaml.safe_load((config_dir / "calibration" / "calibration_meta.yaml").read_text(encoding="utf-8"))
    poses = yaml.safe_load((config_dir / "poses.yaml").read_text(encoding="utf-8"))
    tcp = meta["tcp"]
    return {"tcp": tcp["name_on_pendant"], "tool": tcp["tool_weight_on_pendant"]["name"],
            "home": (poses.get("home") or {}).get("joints_deg")}


class Robot:
    """DSR 드라이버 서비스 클라이언트 (모든 호출에 타임아웃)."""

    def __init__(self, srv):
        try:                         # Ctrl+C는 창이 직접 받아 정지 후 종료 (서비스 대기 중 예외로 끊기지 않게)
            from rclpy.signals import SignalHandlerOptions
            rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
        except ImportError:
            rclpy.init()
        self.node = rclpy.create_node("jog_gui")
        spec = {"posx": (GetCurrentPosx, "aux_control/get_current_posx"),
                "posj": (GetCurrentPosj, "aux_control/get_current_posj"),
                "state": (GetRobotState, "system/get_robot_state"),
                "mode": (GetRobotMode, "system/get_robot_mode"),
                "setmode": (SetRobotMode, "system/set_robot_mode"),
                "movel": (MoveLine, "motion/move_line"),
                "movej": (MoveJoint, "motion/move_joint"),
                "jog": (Jog, "motion/jog"),
                "stop": (MoveStop, "motion/move_stop"),
                "force": (GetToolForce, "aux_control/get_tool_force"),
                "tcp": (GetCurrentTcp, "tcp/get_current_tcp"),
                "tool": (GetCurrentTool, "tool/get_current_tool")}
        self.T = {k: v[0] for k, v in spec.items()}
        self.cli = {k: self.node.create_client(t, f"{srv}/{name}") for k, (t, name) in spec.items()}
        self.ctrl = (self.node.create_client(SetRobotControl, f"{srv}/system/set_robot_control")   # ready() 에 넣지 않음
                     if SetRobotControl else None)
        self.reset_type = (self.node.create_client(SetSafeStopResetType, f"{srv}/system/set_safe_stop_reset_type")
                           if SetSafeStopResetType else None)

    def ready(self):
        return all(c.wait_for_service(timeout_sec=3.0) for c in self.cli.values())

    def call(self, key, timeout=2.0, **kw):
        f = self.cli[key].call_async(self.T[key].Request(**kw))
        rclpy.spin_until_future_complete(self.node, f, timeout_sec=timeout)
        return f.result() if f.done() else None

    def posx(self, timeout=2.0):
        r = self.call("posx", timeout, ref=0)
        return list(r.task_pos_info[0].data[:6]) if r else None

    def posj(self, timeout=2.0):
        r = self.call("posj", timeout)
        return list(r.pos) if r else None

    def state(self, timeout=2.0):
        r = self.call("state", timeout)
        return r.robot_state if r else None

    def tool_force(self, timeout=2.0):
        r = self.call("force", timeout, ref=0)
        return list(r.tool_force) if r else None

    def control(self, value):
        """set_robot_control (비상정지 해제). 서비스가 없거나 응답 없으면 False."""
        if not self.ctrl or not self.ctrl.wait_for_service(timeout_sec=1.0):
            return False
        f = self.ctrl.call_async(SetRobotControl.Request(robot_control=int(value)))
        rclpy.spin_until_future_complete(self.node, f, timeout_sec=2.0)
        return bool(f.done() and f.result() and f.result().success)

    def safe_stop_reset_type(self, value):
        """set_safe_stop_reset_type (안전정지 리셋 뒤 프로그램 재개 여부). 서비스가 없거나 응답 없으면 False."""
        if not self.reset_type or not self.reset_type.wait_for_service(timeout_sec=1.0):
            return False
        f = self.reset_type.call_async(SetSafeStopResetType.Request(reset_type=int(value)))
        rclpy.spin_until_future_complete(self.node, f, timeout_sec=2.0)
        return bool(f.done() and f.result() and f.result().success)

    def mode_name(self):
        r = self.call("mode")
        return {0: "수동(직접교시)", 1: "자동"}.get(r.robot_mode, r.robot_mode) if r else "?"

    def auto(self):
        """자동 모드로 바꾸고, 제어기가 실제로 바뀔 때까지(최대 2초) 기다린다."""
        r = self.call("mode")
        if r and r.robot_mode == 1:
            return True
        self.call("setmode", robot_mode=1)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 2.0:
            time.sleep(0.1)
            r = self.call("mode")
            if r and r.robot_mode == 1 and self.state() in (1, 2):
                time.sleep(0.2)
                return True
        return False

    def teach_off(self):
        self.call("setmode", robot_mode=1)

    def teach(self):
        """직접교시: 자동 → 0.5초 → 수동. 바로 수동만 보내면 LED가 깜빡이며 교시가 막히는 경우가 있음 [실측 10/03]."""
        self.call("setmode", robot_mode=1)
        time.sleep(0.5)
        self.call("setmode", robot_mode=0)

    def movel(self, pose, vel, acc, rot_vel=None, rot_acc=None):
        """vel·acc = 직선(mm/s), 회전은 rot_vel·rot_acc(deg/s), 없으면 직선의 절반 (강의 jog 그대로)."""
        rv = float(vel) / 2 if rot_vel is None else float(rot_vel)
        ra = float(acc) / 2 if rot_acc is None else float(rot_acc)
        r = self.call("movel", pos=[float(v) for v in pose], vel=[float(vel), rv],
                      acc=[float(acc), ra], ref=0, mode=0, sync_type=1)
        return bool(r and r.success)

    def movej(self, joints, vel, acc):
        r = self.call("movej", pos=[float(v) for v in joints], vel=float(vel), acc=float(acc),
                      time=0.0, radius=0.0, mode=0, blend_type=0, sync_type=1)
        return bool(r and r.success)

    def jog(self, axis, speed):
        r = self.call("jog", jog_axis=axis, move_reference=0, speed=float(speed))
        return bool(r and r.success)

    def stop(self):
        """move_stop 결과: True 성공 / False 제어기 거부 / None 응답 없음(서비스 못 찾음·2초 안에 응답 없음)."""
        r = self.call("stop", stop_mode=2)
        return None if r is None else bool(r.success)

    def tool_names(self):
        tcp, tool = self.call("tcp"), self.call("tool")
        return (tcp.info if tcp else "?", tool.info if tool else "?")


class Gripper:
    """RG2 명령을 스레드로 보내 창이 멈추지 않게 한다. 결과는 text에 남겨 창 갱신 때 표시."""

    def __init__(self, ip):
        self.ip, self.text = ip, ("" if ip else "RG2 IP 없음 (--rg2-ip 또는 RG2_HOST)")
        self.width, self.detected, self.busy = None, None, False

    def _run(self, fn):
        if not self.ip or self.busy:
            return
        self.busy = True

        def run():
            g = None
            try:
                g = Rg2(self.ip)
                fn(g)
            except Exception as e:  # noqa: BLE001 — 창이 죽지 않게 표시만
                self.text = f"RG2 실패: {e}"
                print(self.text)
            finally:
                if g is not None:
                    g.close()
                self.busy = False
        threading.Thread(target=run, daemon=True).start()

    def move(self, width, force):
        def fn(g):
            st = g.move(width, force)
            self.width, self.detected = st.width_mm, st.grip_detected
            self.text = f"그리퍼 폭 {st.width_mm:.1f} mm (명령 {width:g} mm, {force:g} N)"
            print(self.text)
        self._run(fn)

    def poll(self):
        def fn(g):
            st = g.status()
            self.width, self.detected = st.width_mm, st.grip_detected
        self._run(fn)


def force_text(d):
    """툴 힘 표시 — 값마다 자리 수 고정(±99.9 N 까지)이라 글자 수가 늘 같음."""
    return f"Fx {d[0]:+5.1f}  Fy {d[1]:+5.1f}  Fz {d[2]:+5.1f} N"


FORCE_W = len(force_text([0.0, 0.0, 0.0]))


def parse_goto(text):
    """'좌표로 이동' 칸 → (종류, 숫자 6개). 종류 = 'posx' / 'posj' / None(숫자만). 숫자가 6개가 아니면 (None, None)."""
    low = text.lower()
    kind = "posx" if "posx" in low else "posj" if "posj" in low else None
    nums = re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", text)
    vals = [float(v) for v in nums]
    if len(vals) != 6 or not all(math.isfinite(v) for v in vals):    # 1e999 → inf 는 거부 (E #171 검수 P2)
        return None, None
    return kind, vals


class App:
    def __init__(self, robot, gripper, settings):
        self.r, self.g, self.cfg = robot, gripper, settings
        self.root = tk.Tk()
        self.root.title("R2G Jog · @9기_SDG")
        self.root.configure(bg=C["bg"])
        self.ok = False
        self.hold = None             # (jog_axis, 시작 시각) 꾹 누르는 중
        self.pending = None          # 꾹 누르기 판정 대기 after id
        self.click = None
        self.quit_req = False        # Ctrl+C 요청 (신호 처리기에서 표시만 하고 watchdog에서 종료)
        self.seq = []                # 정렬 조각 목록 (하나씩 보냄)
        self.rotating = False        # 조각 도착 기다리는 중
        self.teach_when_done = False  # 정렬 = 끝나면 직접교시, 그리퍼 회전·기울이기 = 그대로
        self.move_buttons = []
        self.f0 = None               # 툴 힘 reset 기준
        self.force = None
        self.state_name = "?"

        self.header()
        body = tk.Frame(self.root, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=8, pady=(6, 4))
        self.top_panel(body)
        mid = tk.Frame(body, bg=C["bg"])
        mid.pack(fill="x", pady=6)
        self.joint = self.jog_panel(mid, "관절 이동 (deg)", ["J1", "J2", "J3", "J4", "J5", "J6"], "j", JOINT_VEL, JOINT_ACC,
                                    50, "°", "입력값으로 movej", self.move_by_joint, "posj",
                                    {2: f"≥{J3_MIN:g}", 4: f"≤{J5_MAX:g}"})
        self.axes = self.jog_panel(mid, "직선 이동 (mm · deg)", ["X", "Y", "Z", "Rx", "Ry", "Rz"], "x", LINE_VEL, LINE_ACC,
                                   100, "mm·°", "입력값으로 movel", self.move_by_line, "posx", {}, tag="기준 base_link")
        self.goto_panel(body)
        bottom = tk.Frame(body, bg=C["bg"])
        bottom.pack(fill="x")
        self.tilt_panel(bottom)
        self.align_panel(bottom)
        self.gripper_panel(bottom)
        self.stop_panel(bottom)
        foot = tk.Frame(body, bg=C["bg"])
        foot.pack(fill="x", pady=(6, 0))
        self.status = tk.Label(foot, text="", bg=C["bg"], fg=C["sub"], anchor="e")
        self.status.pack(side="right")

        self.root.bind("<FocusOut>", lambda e: self.end_hold() if e.widget is self.root else None)   # 창이 포커스를 잃으면 멈춤
        self.root.bind("<Escape>", lambda e: self.stop_all())
        self.root.bind("<space>", self.space_stop)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self.on_error

        self.check_tool()
        if not self.cfg["home"]:
            self.home_btn.config(state="disabled")
        self.refresh()
        self.poll_gripper()
        self.watchdog()

    # --- 화면 구성 ---
    def btn(self, parent, text, cmd=None, move=False, **kw):
        """버튼은 포커스를 받지 않음 — Space 가 마지막에 누른 이동 버튼을 다시 누르지 않게 (Space = 정지)."""
        kw.setdefault("bg", "white")
        b = tk.Button(parent, text=text, command=cmd, takefocus=0, relief="groove", bd=1, **kw)
        if move:
            self.move_buttons.append(b)
        return b

    def panel(self, parent, title=None, tag=None, **pack):
        f = tk.Frame(parent, bg=C["panel"], highlightbackground=C["line"], highlightthickness=1, padx=8, pady=6)
        f.pack(**pack)
        if title:
            h = tk.Frame(f, bg=C["panel"])
            h.pack(fill="x", pady=(0, 4))
            tk.Label(h, text=title, bg=C["panel"], fg=C["sub"], font=("", 9, "bold")).pack(side="left")
            if tag:
                tk.Label(h, text=tag, bg=C["posx"], fg=C["blue"], font=("", 8), padx=4).pack(side="left", padx=6)
        return f

    def header(self):
        h = tk.Frame(self.root, bg=C["dark"])
        h.pack(fill="x")
        tk.Label(h, text="R2G Jog", bg=C["dark"], fg="white", font=("", 10, "bold")).pack(side="left", padx=(10, 4), pady=4)
        tk.Label(h, text="· Pos 설정 (jog_gui)", bg=C["dark"], fg="#9aa").pack(side="left")
        tk.Label(h, text=" @9기_SDG ", bg="#3c4146", fg=C["silver"], font=("", 9, "bold"),
                 highlightbackground="#aab1b9", highlightthickness=1).pack(side="right", padx=10, pady=4)

    def top_panel(self, parent):
        f = self.panel(parent, fill="x")
        row = tk.Frame(f, bg=C["panel"])
        row.pack(fill="x")
        self.banner = tk.Label(row, text="", font=("", 9, "bold"), padx=8, pady=3)
        self.banner.pack(side="left")
        bf = tkfont.Font(font=self.banner["font"])        # 툴 정상 띠 폭 고정: 상태 글자가 바뀌어도 뒤 칸이 안 움직이게
        self.banner_w = math.ceil(max(bf.measure(f"✔ 툴 정상 · {n}") for n in (*STATE.values(), "정렬 중", "꾹 누르는 중"))
                                  / bf.measure("0"))
        self.btn(row, "다시 확인", self.check_tool, font=("", 8)).pack(side="left", padx=4)
        tk.Frame(row, bg=C["line"], width=1, height=18).pack(side="left", padx=6)
        tk.Label(row, text="툴 힘", bg=C["panel"], font=("", 9, "bold")).pack(side="left")
        self.force_lbl = tk.Label(row, text="—", bg=C["panel"], font=("TkFixedFont", 9), width=FORCE_W, anchor="w")
        self.force_lbl.pack(side="left", padx=4)          # 고정폭 글꼴·글자 수 고정: 값이 바뀌어도 reset 이 안 움직임
        self.btn(row, "reset", self.force_reset, font=("", 8)).pack(side="left")
        # 꾹 누르기 묶음은 오른쪽 끝에 고정 (툴 힘 글자 길이에 따라 왔다갔다 안 하게, 사용자 10/08)
        self.hold_lbl = tk.Label(row, text="4 %", bg=C["panel"], width=4)
        self.hold_lbl.pack(side="right")
        self.hold_speed = tk.Scale(row, from_=2, to=20, orient=tk.HORIZONTAL, length=110, showvalue=0, bg=C["panel"],
                                   highlightthickness=0, command=lambda v: self.hold_lbl.config(text=f"{int(float(v))} %"))
        self.hold_speed.set(4)
        self.hold_speed.pack(side="right", padx=(2, 0))
        tk.Label(row, text="꾹 누르기 속도", bg=C["panel"], font=("", 9, "bold")).pack(side="right")
        tk.Frame(row, bg=C["line"], width=1, height=18).pack(side="right", padx=6)
        self.cells = {}
        tbl = tk.Frame(f, bg=C["panel"])                  # posx·posj 한 표: 12칸 같은 폭, 위아래 줄 칸 맞춤
        tbl.pack(fill="x", pady=(5, 0))
        for col in range(1, 7):
            tbl.columnconfigure(col, weight=1, uniform="cell")
        for row, (name, labels, bg) in enumerate((("posx", ("X", "Y", "Z", "Rx", "Ry", "Rz"), C["posx"]),
                                                  ("posj", ("J1", "J2", "J3", "J4", "J5", "J6"), C["posj"]))):
            strip = tk.Frame(tbl, bg=bg, highlightbackground=C["line"], highlightthickness=1)   # 줄 바탕 (칸 뒤)
            strip.grid(row=row, column=0, columnspan=8, sticky="nsew", pady=2)
            tk.Label(tbl, text=name, bg=bg, font=("", 9, "bold"), width=5, anchor="w").grid(row=row, column=0, padx=(6, 2),
                                                                                         pady=5)
            vals = []
            for k, lab in enumerate(labels):
                c = tk.Frame(tbl, bg="white", highlightbackground="#d3d6da", highlightthickness=1)
                c.grid(row=row, column=k + 1, sticky="ew", padx=2, pady=5)
                tk.Label(c, text=lab, bg="white", fg="#8a8f98", font=("", 7), width=2, anchor="w").pack(side="left",
                                                                                                       padx=(3, 0))
                v = tk.Label(c, text="—", bg="white", font=("TkFixedFont", 9), anchor="e")
                v.pack(side="right", padx=3)
                vals.append(v)
            self.btn(tbl, "copy", lambda n=name: self.copy_live(n), font=("", 8)).grid(row=row, column=7, padx=(4, 4))
            self.cells[name] = vals
        self.btn(tbl, "둘 다\ncopy", self.copy_both, font=("", 8)).grid(row=0, column=8, rowspan=2, sticky="ns",
                                                                       padx=(2, 6), pady=2)   # posx·posj 한 번에 (사용자 10/09)
        self.live = {"posx": None, "posj": None}

    def jog_panel(self, parent, title, labels, group, vel, acc, vmax, unit, move_text, move_cmd, copy_name, hints, tag=None):
        f = self.panel(parent, title, tag, side="left", fill="both", expand=True, padx=(0, 6) if group == "j" else 0)
        body = tk.Frame(f, bg=C["panel"])
        body.pack(expand=True)                             # 칸 안에서 가운데 (왼쪽 쏠림 없앰)
        grid = tk.Frame(body, bg=C["panel"])
        grid.pack(side="left")
        tk.Label(grid, text="입력 (고쳐서 이동)", bg=C["panel"], fg=C["sub"], font=("", 7)).grid(row=0, column=1)
        tk.Label(grid, text="증분만큼 바로", bg=C["panel"], fg=C["sub"], font=("", 7)).grid(row=0, column=2, columnspan=2)
        out = []
        for i, text in enumerate(labels):
            tk.Label(grid, text=text, bg=C["panel"], font=("", 9, "bold"), width=3).grid(row=i + 1, column=0)
            e = tk.Entry(grid, width=8, justify="right", font=("TkFixedFont", 10))
            e.dirty = False
            e.bind("<Key>", lambda ev, e=e: self.mark(e))
            e.grid(row=i + 1, column=1, padx=3, pady=2)
            for col, sign in ((2, -1), (3, 1)):                     # − 왼쪽, + 오른쪽
                b = self.btn(grid, "−" if sign < 0 else "+", move=True, font=("", 10, "bold"), padx=8, pady=0)
                b.grid(row=i + 1, column=col, padx=2, pady=2)
                b.bind("<ButtonPress-1>", lambda ev, g=group, i=i, s=sign: self.press(g, i, s))
                b.bind("<ButtonRelease-1>", lambda ev: self.release())
                b.bind("<Leave>", lambda ev: self.end_hold())
            if i in hints:
                tk.Label(grid, text=hints[i], bg=C["panel"], fg=C["sub"], font=("", 7)).grid(row=i + 1, column=4, padx=2)
            out.append(e)
        tk.Frame(body, bg=C["line"], width=1).pack(side="left", fill="y", padx=14)   # 선 양옆 여백 (사용자 10/08)
        side = tk.Frame(body, bg=C["panel"])
        side.pack(side="left", fill="y")
        r0 = tk.Frame(side, bg=C["panel"])
        r0.pack(anchor="w")
        tk.Label(r0, text="증분", bg=C["panel"]).pack(side="left")
        inc = tk.Entry(r0, width=5, justify="right")
        inc.insert(0, "1")
        inc.pack(side="left", padx=3)
        tk.Label(r0, text=unit, bg=C["panel"]).pack(side="left")
        if group == "j":
            self.inc_j = inc
        else:
            self.inc_x = inc
        for text, val in (("속도", vel), ("가속", acc)):
            r = tk.Frame(side, bg=C["panel"])
            r.pack(anchor="w")
            tk.Label(r, text=text, bg=C["panel"]).pack(side="left")
            sc = tk.Scale(r, from_=5, to=vmax, orient=tk.HORIZONTAL, length=90, bg=C["panel"], highlightthickness=0,
                          font=("", 7))
            sc.set(val)
            sc.pack(side="left")
            out.append(sc)
        self.btn(side, move_text, move_cmd, move=True, bg=C["blue"], fg="white", activebackground="#2557b0",
                 font=("", 9, "bold")).pack(fill="x", pady=(4, 3))
        r = tk.Frame(side, bg=C["panel"])
        r.pack(anchor="w")
        self.btn(r, "지금 값", self.clear_marks, font=("", 8)).pack(side="left")
        self.btn(r, "copy", lambda: self.copy(out, copy_name), font=("", 8)).pack(side="left", padx=4)
        return out

    def goto_panel(self, parent):
        f = self.panel(parent, fill="x", pady=(0, 6))
        tk.Label(f, text="좌표로 이동", bg=C["panel"], fg=C["sub"], font=("", 9, "bold")).pack(side="left")
        self.goto_entry = tk.Entry(f, font=("TkFixedFont", 10))
        self.goto_entry.pack(side="left", fill="x", expand=True, padx=6)
        for key in ("<Control-a>", "<Control-A>"):      # Tk 기본은 줄 맨 앞으로 — 전체 선택으로 (사용자 10/08)
            self.goto_entry.bind(key, self.goto_select_all)
        self.goto_entry.bind("<<Paste>>", self.goto_paste)
        tk.Label(f, text="posx→movel · posj→movej", bg=C["panel"], fg=C["sub"], font=("", 8)).pack(side="left")
        self.btn(f, "이동", self.goto, move=True, bg=C["blue"], fg="white", activebackground="#2557b0",
                 font=("", 10, "bold"), width=6).pack(side="left", padx=(6, 0))

    def tilt_panel(self, parent):
        f = self.panel(parent, "그리퍼 기울이기 (TCP 고정)", side="left", fill="y", padx=(0, 6))
        r = tk.Frame(f, bg=C["panel"])
        r.pack(anchor="w", pady=(0, 4))
        tk.Label(r, text="각도", bg=C["panel"], fg=C["sub"]).pack(side="left")
        self.tilt_deg = tk.Entry(r, width=4, justify="right")
        self.tilt_deg.insert(0, f"{TILT_DEFAULT:g}")
        self.tilt_deg.pack(side="left", padx=3)
        tk.Label(r, text="°", bg=C["panel"]).pack(side="left")
        pad = tk.Frame(f, bg=C["panel"])
        pad.pack()
        names = {(-1.0, 0.0): ("← 왼\n(−x)", 1, 0), (1.0, 0.0): ("오른 →\n(+x)", 1, 2),
                 (0.0, 1.0): ("↑ 앞\n(+y)", 0, 1), (0.0, -1.0): ("↓ 뒤\n(−y)", 2, 1)}
        for text, d in TILT_DIRS:
            label, row, col = names[d]
            self.btn(pad, label, lambda t=text, d=d: self.tilt(d, t), move=True, width=5, font=("", 8)).grid(
                row=row, column=col, padx=2, pady=2)
        self.btn(pad, "수직", lambda: self.tilt((1.0, 0.0), "수직", 0.0), move=True, width=5, height=2, bg=C["green"],
                 font=("", 9, "bold")).grid(row=1, column=1, padx=2, pady=2)

    def align_panel(self, parent):
        f = self.panel(parent, "정렬 · 회전", side="left", fill="y", padx=(0, 6))
        g = tk.Frame(f, bg=C["panel"])
        g.pack()
        for k, (mode, text) in enumerate((("x", "x 정렬\n수평·바깥"), ("y", "y 정렬\n수평·−y"),
                                          ("z", "z 정렬\n수직 아래"), ("r", "그리퍼 정렬"))):
            self.btn(g, text, lambda m=mode: self.align(m), move=True, width=9, font=("", 8)).grid(
                row=k // 2, column=k % 2, padx=2, pady=2, sticky="nsew")
        r = tk.Frame(f, bg=C["panel"])
        r.pack(anchor="w", pady=(5, 0))
        tk.Label(r, text="회전", bg=C["panel"], fg=C["sub"]).pack(side="left")
        self.btn(r, "↺ −", lambda: self.roll(-1), move=True, font=("", 8)).pack(side="left", padx=3)
        self.roll_deg = tk.Entry(r, width=4, justify="right")
        self.roll_deg.insert(0, f"{ROLL_DEFAULT:g}")
        self.roll_deg.pack(side="left")
        tk.Label(r, text="°", bg=C["panel"]).pack(side="left")
        self.btn(r, "↻ +", lambda: self.roll(1), move=True, font=("", 8)).pack(side="left", padx=3)
        tk.Label(f, text="정렬 끝나면 직접교시 켜짐", bg=C["panel"], fg=C["sub"], font=("", 8)).pack(anchor="w", pady=(5, 0))

    def gripper_panel(self, parent):
        f = self.panel(parent, side="left", fill="y", padx=(0, 6))
        self.grip_lbl = tk.Label(f, text="그리퍼", bg=C["panel"], fg=C["sub"], font=("", 9, "bold"), anchor="w")
        self.grip_lbl.pack(fill="x", pady=(0, 4))
        r = tk.Frame(f, bg=C["panel"])
        r.pack(fill="x")
        self.btn(r, "닫기", lambda: self.g.move(0.0, self.num(self.grip_force, 20.0, 40.0)), bg=C["blue"], fg="white",
                 activebackground="#2557b0", font=("", 10, "bold"), width=13).pack(side="left")
        tk.Label(r, text="힘", bg=C["panel"]).pack(side="left", padx=(6, 2))
        self.grip_force = tk.Entry(r, width=4, justify="right")
        self.grip_force.insert(0, "20")
        self.grip_force.pack(side="left")
        tk.Label(r, text="N", bg=C["panel"]).pack(side="left", padx=2)
        r = tk.Frame(f, bg=C["panel"])
        r.pack(fill="x", pady=(5, 0))
        self.btn(r, "최대 열기", lambda: self.g.move(100.0, 20.0), font=("", 8), padx=4).pack(side="left")
        self.btn(r, "폭만큼 열기", lambda: self.g.move(self.num(self.grip_width, 35.0, 100.0), 20.0), font=("", 8),
                 padx=4).pack(side="left", padx=3)
        tk.Label(r, text="폭", bg=C["panel"]).pack(side="left", padx=(3, 2))
        self.grip_width = tk.Entry(r, width=4, justify="right")
        self.grip_width.insert(0, "35")
        self.grip_width.pack(side="left")
        tk.Label(r, text="mm", bg=C["panel"]).pack(side="left", padx=2)
        tk.Frame(f, bg=C["line"], height=1).pack(fill="x", pady=6)
        self.home_btn = self.btn(f, "⌂ gohome (확인 후)", self.go_home, move=True, bg=C["amber"], font=("", 9))
        self.home_btn.pack(side="bottom", fill="x", pady=(5, 0))
        r = tk.Frame(f, bg=C["panel"])
        r.pack(fill="both", expand=True)                  # 직접교시 두 버튼이 남는 세로 공간을 채움
        self.btn(r, "직접교시 ON", self.teach_on, bg=C["green"], font=("", 10, "bold")).pack(side="left", fill="both",
                                                                                          expand=True)
        self.btn(r, "직접교시 OFF", self.teach_off, font=("", 10, "bold")).pack(side="left", fill="both", expand=True,
                                                                            padx=(4, 0))

    def stop_panel(self, parent):
        f = self.panel(parent, side="left", fill="both", expand=True)
        rec = self.btn(f, "비상정지 해제\n확인 창 뒤·안전정지만", self.recover, bg=C["amber"], font=("", 8, "bold"))
        rec.pack(fill="x")
        if not self.r.ctrl:
            rec.config(state="disabled")
        tk.Button(f, text="정지\nEsc / Space", command=self.stop_all, takefocus=0, bg=C["red"], fg="white",
                  activebackground="#b02a1e", activeforeground="white", font=("", 14, "bold"), relief="raised",
                  bd=2).pack(fill="both", expand=True, pady=(6, 0))

    @staticmethod
    def num(entry, default, upper):
        try:
            return max(0.0, min(upper, float(entry.get())))
        except ValueError:
            return default

    def mark(self, e):
        e.dirty = True
        e.config(bg="#ffd")

    def clear_marks(self):
        for e in self.joint[:6] + self.axes[:6]:
            e.dirty = False
            e.config(bg="white")

    def copy(self, entries, name):
        self.copy_text(f"{name}([" + ", ".join(e.get() for e in entries[:6]) + "])")

    def copy_live(self, name):
        if self.live[name]:
            self.copy_text(f"{name}([" + ", ".join(f"{v:.3f}" for v in self.live[name]) + "])")

    def copy_both(self):
        """posx 줄, posj 줄 두 줄로 복사 (지금 로봇 값)."""
        if self.live["posx"] and self.live["posj"]:
            self.copy_text("\n".join(f"{n}([" + ", ".join(f"{v:.3f}" for v in self.live[n]) + "])" for n in ("posx", "posj")))
        else:
            self.say("좌표 조회 전이라 복사 안 함")

    def copy_text(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        print(f"copy to clipboard: {text}")

    def say(self, text):
        """상태줄(맨 아래, 다음 문구까지 유지) + 터미널 (10/07 거부 이유가 안 보였던 문제, 7e3a93d)."""
        self.status.config(text=f"{text}   ({time.strftime('%H:%M:%S')})")
        print(text, flush=True)

    def space_stop(self, event):
        if not isinstance(event.widget, tk.Entry):       # 입력칸에서 띄어쓰기는 정지 아님
            self.stop_all()

    # --- 상태 ---
    def check_tool(self):
        tcp, tool = self.r.tool_names()
        self.ok = (tcp, tool) == (self.cfg["tcp"], self.cfg["tool"])
        self.tool_text = (tcp, tool)
        self.show_banner()
        for b in self.move_buttons:
            b.config(state="normal" if self.ok else "disabled")

    def show_banner(self, extra=None):
        if self.ok:
            self.banner.config(text=f"✔ 툴 정상 · {extra or self.state_name}", bg="#d9f2df", fg="black",
                               width=self.banner_w)
        else:
            tcp, tool = self.tool_text
            self.banner.config(text=f"⚠ 펜던트 툴 확인! TCP '{tcp}'(기대 {self.cfg['tcp']}), 툴 '{tool}'(기대 "
                                    f"{self.cfg['tool']}) — 이동 막힘", bg=C["red"], fg="white", width=0)

    def refresh(self):
        if self.hold:                        # 꾹 누르는 동안은 조회하지 않음 — 손을 떼면 바로 정지되게
            self.show_banner("꾹 누르는 중")
            self.root.after(300, self.refresh)
            return
        t = REFRESH_TIMEOUT_S
        for name, values, entries in (("posj", self.r.posj(t), self.joint), ("posx", self.r.posx(t), self.axes)):
            if values:
                self.live[name] = values
                for c, v in zip(self.cells[name], values):
                    c.config(text=f"{v:.3f}")
                for e, v in zip(entries[:6], values):
                    if not e.dirty:          # 사용자가 고친 칸(노란색)은 덮어쓰지 않음
                        e.delete(0, tk.END)
                        e.insert(0, f"{v:.3f}")
        f = self.r.tool_force(t)
        if f:
            self.force = f
            d = [f[i] - (self.f0[i] if self.f0 else 0.0) for i in range(3)]
            text = force_text(d)
            self.force_lbl.config(text=text, width=max(FORCE_W, len(text)))   # 100 N 넘을 때만 늘어남
        s = self.r.state(t)
        self.state_name = "정렬 중" if self.seq or self.rotating else STATE.get(s, s)
        self.show_banner()
        if self.g.width is not None:
            grip = "예" if self.g.detected else "아니오"
            self.grip_lbl.config(text=f"그리퍼   지금 {self.g.width:.1f} mm · grip 신호 {grip}")
        elif self.g.text:
            self.grip_lbl.config(text=f"그리퍼   {self.g.text}")
        self.root.after(300, self.refresh)

    def poll_gripper(self):
        self.g.poll()
        self.root.after(2000, self.poll_gripper)

    def force_reset(self):
        self.f0 = list(self.force) if self.force else None
        self.say("툴 힘 기준 reset (화면 표시만)")

    def can_move(self):
        self.check_tool()                    # 이동 직전마다 다시 확인 — 쓰는 도중 펜던트 설정이 바뀌어도 잡음 (#69 PM 검토)
        if not self.ok:
            self.say("펜던트 TCP·툴 설정이 달라 이동 막힘 (위 빨간 띠)")
            return False
        if self.r.state() == 2:
            self.say("움직이는 중이라 무시함")
            return False
        if not self.r.auto():
            self.say(f"자동 모드로 못 바꿈 — 상태: {STATE.get(self.r.state(), '?')}, 모드: {self.r.mode_name()}")
            return False
        return True

    def report(self, ok, what):
        """이동 명령 결과를 상태줄에 표시 (거부되면 원인을 찾을 수 있게 상태·모드도)."""
        if ok:
            self.say(f"{what} 시작")
        else:
            self.say(f"{what} 거부됨 — 상태: {STATE.get(self.r.state(), '?')}, 모드: {self.r.mode_name()}")

    # --- 한 칸 / 꾹 누르기 ---
    def press(self, group, idx, sign):
        if not self.ok:
            return
        self.pending = self.root.after(HOLD_DELAY_MS, lambda: self.start_hold(group, idx, sign))
        self.click = (group, idx, sign)

    def release(self):
        if self.pending:                     # 짧게 누름 → 한 칸
            self.root.after_cancel(self.pending)
            self.pending = None
            self.step(*self.click)
        self.end_hold()

    def start_hold(self, group, idx, sign):
        self.pending = None
        if not self.can_move():
            return
        axis = idx if group == "j" else 6 + idx           # 0~5 관절, 6~11 X Y Z Rx Ry Rz (베이스)
        if self.r.jog(axis, sign * float(self.hold_speed.get())):
            self.hold = (axis, time.monotonic())

    def end_hold(self):
        if self.pending:
            self.root.after_cancel(self.pending)
            self.pending = None
        if self.hold:
            self.r.jog(self.hold[0], 0.0)
            self.r.stop()
            self.hold = None
            self.clear_marks()

    def watchdog(self):
        if self.quit_req:
            self.close()
            return
        if self.hold and time.monotonic() - self.hold[1] > HOLD_MAX_S:
            self.end_hold()
            self.say(f"꾹 누르기 {HOLD_MAX_S:.0f}초 제한으로 멈춤 — 다시 누르세요")
        self.root.after(100, self.watchdog)

    def big_step_ok(self, inc, limit, unit):
        """한 칸이 상한보다 크면 확인창 (입력 실수로 한 번에 크게 도는 것 방지)."""
        if abs(inc) <= limit:
            return True
        return messagebox.askokcancel("큰 이동 확인", f"한 칸 {inc:g}{unit} — 상한 {limit:g}{unit}보다 큽니다. 움직일까요?",
                                      parent=self.root)

    def step(self, group, idx, sign):
        try:
            inc = float((self.inc_j if group == "j" else self.inc_x).get())
        except ValueError:
            self.say("증분 칸에 숫자를 넣으세요")
            return
        limit, unit = (STEP_CONFIRM_MM, " mm") if group != "j" and idx < 3 else (STEP_CONFIRM_DEG, "°")
        if not self.big_step_ok(inc, limit, unit) or not self.can_move():
            return
        if group == "j":
            q = self.r.posj()                # 지금 관절값을 새로 읽음
            if q is None:
                return
            q[idx] += sign * inc
            self.report(self.r.movej(q, self.joint[6].get(), self.joint[7].get()), f"J{idx + 1} 이동")
        else:
            p = self.r.posx()                # 지금 위치를 새로 읽음
            if p is None:
                return
            ok = self.r.movel(step_target(p, idx, sign * inc), self.axes[6].get(), self.axes[7].get())
            self.report(ok, "XYZ"[idx] + " 이동" if idx < 3 else "R" + "xyz"[idx - 3] + " 회전")
        self.clear_marks()

    # --- 입력값으로 이동 (강의 jog의 movej / movel) ---
    def move_by_joint(self):
        if self.can_move():
            self.report(self.r.movej([float(e.get()) for e in self.joint[:6]], self.joint[6].get(), self.joint[7].get()), "movej")
            self.clear_marks()

    def move_by_line(self):
        if self.can_move():
            self.report(self.r.movel([float(e.get()) for e in self.axes[:6]], self.axes[6].get(), self.axes[7].get()), "movel")
            self.clear_marks()

    # --- 좌표로 이동 ---
    def goto_select_all(self, _event=None):
        self.goto_entry.select_range(0, "end")
        self.goto_entry.icursor("end")
        return "break"

    def goto_paste(self, _event=None):
        """붙여넣기: 선택된 글자를 바꿔 넣음 (리눅스 Tk 기본은 선택을 지우지 않고 뒤에 덧붙임)."""
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return "break"
        if self.goto_entry.selection_present():
            self.goto_entry.delete("sel.first", "sel.last")
        self.goto_entry.insert("insert", text)
        return "break"

    def goto(self):
        """posx([...]) → movel, posj([...]) → movej. 숫자 6개만이면 어느 쪽인지 묻는다. 이동 전 확인창."""
        text = self.goto_entry.get()
        kind, vals = parse_goto(text)
        if vals is None:
            self.say("좌표로 이동: 유한한 숫자 6개가 필요 (예: posx([x, y, z, rx, ry, rz]))")
            return
        if kind is None:
            ans = messagebox.askyesnocancel("좌표 종류", f"{vals}\n\n숫자만 있습니다. posx(직선 movel)면 '예', "
                                            "posj(관절 movej)면 '아니오'.", parent=self.root)
            if ans is None:
                return
            kind = "posx" if ans else "posj"
        if kind == "posj" and (abs(vals[4]) > J5_MAX or vals[2] < J3_MIN):
            self.say(f"좌표로 이동 거부: J5 {vals[4]:g}° / J3 {vals[2]:g}° — 제한(J5 ≤ {J5_MAX:g}°, J3 ≥ {J3_MIN:g}°) 밖")
            return
        sliders = self.axes if kind == "posx" else self.joint
        how = "직선 movel" if kind == "posx" else "관절 movej"
        if not messagebox.askokcancel("좌표로 이동", f"{kind}({vals})\n\n{how}, 속도 {sliders[6].get()} · 가속 "
                                      f"{sliders[7].get()}\n가는 길에 부딪힐 것이 없는지 확인하세요.", parent=self.root):
            return
        if not self.can_move():
            return
        if kind == "posx":
            self.report(self.r.movel(vals, sliders[6].get(), sliders[7].get()), "좌표로 movel")
        else:
            self.report(self.r.movej(vals, sliders[6].get(), sliders[7].get()), "좌표로 movej")
        self.clear_marks()

    # --- 정렬 ---
    def align(self, mode):
        if not self.can_move():
            return
        p = self.r.posx()
        if p is None:
            return
        target = align_target(p, mode, False)
        self.teach_when_done = True
        self.rotate_to(p, target, ALIGN_NAMES[mode], "정렬")

    def roll(self, sign):
        """그리퍼 축(툴 z) 둘레로 ±각도 칸(기본 90°) 회전, TCP 고정. + = 수직 아래 자세에서 위에서 볼 때 시계 방향."""
        if not self.can_move():
            return
        p = self.r.posx()
        if p is None:
            return
        deg = sign * self.num(self.roll_deg, ROLL_DEFAULT, ROLL_MAX)
        self.teach_when_done = False
        self.rotate_to(p, roll_target(p, deg), f"그리퍼 회전 {deg:+g}° (툴 z 둘레)", "그리퍼 회전",
                       "\n\n손가락이 서랍 벽·물체에 닿지 않는 높이인지 확인하세요.")

    def tilt(self, direction, name, deg=None):
        """수직 아래에서 direction 쪽으로 기울이기 (deg None = 각도 칸 값). 끌기(nudge_object) 자세 시험용."""
        if not self.can_move():
            return
        p = self.r.posx()
        if p is None:
            self.say("현재 좌표 조회 실패 — 기울이기 안 함")
            return
        deg = self.num(self.tilt_deg, TILT_DEFAULT, TILT_MAX) if deg is None else deg
        target = tilt_target(p, direction, deg)
        self.teach_when_done = False
        self.rotate_to(p, target, f"기울이기 {name} {deg:g}°" if deg else "수직 아래로", "기울이기",
                       "\n\n서랍·물체 안이면 손가락이 벽에 닿을 수 있으니 먼저 올리세요.")

    def rotate_to(self, p, target, title, what, warn=""):
        """TCP 고정 회전: 확인창 → 한 번에 (170° 넘으면 2번) (축 정렬·기울이기·그리퍼 회전 공통)."""
        self.seq = waypoints(p, target, ALIGN_STEP_DEG)
        if not self.seq:
            self.say("이미 그 자세임")
            self.after_align()
            return
        turn = rotation_angle(rot(*p[3:]), rot(*target[3:]))
        dmax = max(abs(wrap(target[i] - p[i])) for i in range(3, 6))
        msg = (f"{title}\n\n"
               f"현재  {[round(v, 2) for v in p[3:]]}\n목표  {[round(v, 2) for v in target[3:]]}\n\n"
               f"회전 {turn:.1f}°{f' ({len(self.seq)}번에 나눠)' if len(self.seq) > 1 else ''}, {ALIGN_VEL:g}°/s\n"
               f"Rx·Ry·Rz 최대 변화 {dmax:.1f}°\n위치는 그대로, 방향만 돌립니다.")
        if dmax > 90.0:
            msg += "\n\n주의: 각도 값이 90° 넘게 바뀝니다. 그리퍼가 크게 돌 수 있으니 주변을 확인하세요."
        msg += warn
        print(msg.replace("\n\n", "\n"))
        if not messagebox.askokcancel(f"{what} 확인", msg, parent=self.root):
            self.seq = []
            self.say(f"{what} 취소")
            return
        self.next_piece()

    def next_piece(self):
        """정렬 조각을 하나 보내고, 끝나면(이동 중 아님) 다음 조각. 정지 버튼을 누르면 목록을 비운다."""
        if not self.seq:
            return
        piece = self.seq.pop(0)
        self.rotating = True
        if not self.r.movel(piece, 30.0, 60.0, ALIGN_VEL, ALIGN_ACC):   # TCP 고정이라 직선 속도는 거의 안 씀
            self.seq, self.rotating = [], False
            self.report(False, "정렬")
            return
        cur = self.r.posx()
        turn = rotation_angle(rot(*cur[3:]), rot(*piece[3:])) if cur else 180.0
        self.wait_piece(time.monotonic(), piece, turn / ALIGN_VEL + PIECE_TIMEOUT_EXTRA_S)

    def wait_piece(self, t0, piece, limit_s):
        """조각 목표에 도착하고(1 mm·0.5°) 멈춘 뒤 다음 조각. 실물 드라이버는 이동 중에도 '이동 중' 상태가 늦거나
        안 뜰 때가 있어(10/06 스킬 서버) 상태값만 보지 않는다. limit_s 안에 못 오면 정지하고 남은 조각 취소."""
        if not self.rotating:                # 정지 버튼으로 취소됨
            return
        st, p = self.r.state(), self.r.posx()
        there = p is not None and (max(abs(p[i] - piece[i]) for i in range(3)) <= 1.0
                                   and rotation_angle(rot(*p[3:]), rot(*piece[3:])) <= 0.5)
        if there and st != 2:
            if self.seq:
                self.next_piece()
            else:
                self.rotating = False
                self.after_align()
            return
        if time.monotonic() - t0 > limit_s:
            self.stop_all()
            self.say(f"회전이 {limit_s:.0f}초 안에 도착하지 않아 정지")
            return
        self.root.after(80, lambda: self.wait_piece(t0, piece, limit_s))

    def after_align(self):
        self.clear_marks()
        if self.teach_when_done:
            self.r.teach()
            self.say("정렬 끝 → 직접교시 ON")
        else:
            self.say("회전 끝")

    # --- 모드·홈·정지 ---
    def teach_on(self):
        self.r.teach()
        self.say("직접교시 ON")

    def teach_off(self):
        self.r.teach_off()
        self.say("직접교시 OFF (자동 모드)")

    def go_home(self):
        home = self.cfg["home"]
        if not messagebox.askokcancel("gohome", f"홈 {home} 으로 관절 이동합니다 ({HOME_VEL:g}°/s).\n"
                                      "서랍 안이나 물건 옆이면 먼저 빼고 누르세요.", parent=self.root):
            return
        if self.can_move():
            self.report(self.r.movej(home, HOME_VEL, HOME_VEL), "gohome")
            self.clear_marks()

    def recover(self):
        """비상정지 해제: 소프트웨어 안전정지(충돌·한계)만 set_robot_control 로. 물리 비상정지는 사람이 버튼을 풀어야 함.
        안전정지 리셋 전엔 reset type 0(프로그램 정지)을 먼저 성공시키고, 리셋 뒤 움직이면 바로 정지 보냄.
        로봇은 움직이지 않는다 (해제 뒤 대기)."""
        st = self.r.state()
        name = STATE.get(st, st)
        if st == 6:
            messagebox.showinfo("비상정지 해제", "물리 비상정지 버튼이 눌린 상태입니다.\n버튼을 돌려 푼 뒤 다시 누르세요.",
                                parent=self.root)
            return
        if st in RECOVER_BY_PENDANT:
            messagebox.showinfo("비상정지 해제", f"지금 상태: {name}\n복구 모드를 거쳐야 하는 정지라 여기서 풀지 않습니다.\n"
                                "펜던트에서 복구(Recovery) 후 해제하세요.", parent=self.root)
            return
        code = RECOVER.get(st)
        if code is None:
            self.say(f"해제할 안전정지 없음 (상태: {name})")
            return
        what = "안전정지 리셋" if code == 2 else "서보 켜기"
        if not messagebox.askokcancel("비상정지 해제", f"지금 상태: {name}\n제어기에 {what} (set_robot_control {code}) 을 "
                                      "보냅니다.\n로봇은 움직이지 않습니다.\n\n멈춘 원인(충돌·한계)을 확인했나요?",
                                      parent=self.root):
            return
        if code == 2 and not self.r.safe_stop_reset_type(SAFE_STOP_RESET_PROGRAM_STOP):
            self.say("비상정지 해제 안 함: 리셋 뒤 프로그램 정지(reset type 0) 설정 실패 — 펜던트에서 해제하세요")
            return
        ok = self.r.control(code)
        time.sleep(0.5)
        after = self.r.state()
        if after == 2:                                  # 리셋 뒤 움직이면 안 됨 — 바로 정지
            self.r.stop()
            self.say("비상정지 해제 뒤 로봇이 움직여서 정지 보냄 — 펜던트에서 프로그램 상태 확인")
            return
        self.say(f"비상정지 해제 {'보냄' if ok else '실패'} — 상태: {STATE.get(after, '?')}")

    def stop_all(self):
        self.seq, self.rotating = [], False  # 정렬·기울이기 중이면 남은 조각 취소
        self.end_hold()
        ok = self.r.stop()
        result = {True: "제어기 수락", False: "제어기 거부", None: "응답 없음 — move_stop 서비스 확인"}[ok]
        self.say(f"정지 보냄 ({result}) — 상태: {STATE.get(self.r.state(REFRESH_TIMEOUT_S), '?')}")   # 결과가 안 보였던 문제 (사용자 10/08)

    def close(self):
        """창 닫기·Ctrl+C: 움직이는 중이면 멈추고 종료."""
        if self.hold or self.seq or self.rotating or self.r.state() == 2:
            self.stop_all()
        self.root.destroy()

    def on_error(self, exc, val, tb):
        if issubclass(exc, KeyboardInterrupt):
            self.close()
            return
        traceback.print_exception(exc, val, tb)
        self.say(f"오류: {val} (터미널 참고)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="실물 로봇 조그 창 (교시·측정용)")
    ap.add_argument("--config-dir", type=Path, default=None, help="저장소 config 폴더 (기본: 자동 탐색)")
    ap.add_argument("--rg2-ip", default=os.environ.get("RG2_HOST", ""), help="RG2 IP (기본: 환경변수 RG2_HOST)")
    ap.add_argument("--srv", default=SRV, help=f"DSR 드라이버 서비스 접두어 (기본 {SRV})")
    args, _ = ap.parse_known_args(argv)
    config_dir = args.config_dir or find_config_dir()
    try:
        settings = load_settings(config_dir)
    except (OSError, KeyError, TypeError) as e:
        raise SystemExit(f"config 읽기 실패 ({config_dir}): {e} — --config-dir <저장소>/config 로 지정")
    robot = Robot(args.srv)
    if not robot.ready():
        raise SystemExit(f"드라이버 서비스 없음: {args.srv} (DSR 드라이버 실행 중인지 확인)")
    app = App(robot, Gripper(args.rg2_ip), settings)
    signal.signal(signal.SIGINT, lambda *_: setattr(app, "quit_req", True))
    try:
        app.root.mainloop()
    finally:
        robot.node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
