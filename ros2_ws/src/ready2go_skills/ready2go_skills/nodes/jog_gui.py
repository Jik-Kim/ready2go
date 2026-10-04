"""실물 로봇 조그 창 (교시·측정용 도구, 태스크 실행 경로 아님). 강의 rokey_cobot2 jog 화면을 바탕으로 안전 수정.

강의 jog와 다른 점
- +/- 는 입력칸 숫자가 아니라 로봇의 '지금' 위치를 새로 읽어 한 칸만 움직인다
  → 직접교시·다른 도구로 옮긴 뒤 눌러도 옛 위치로 돌아가지 않는다 (강의 jog의 충돌 위험).
- +/- 를 꾹 누르면(0.35초 이상) DSR 연속 조그로 누르는 동안 움직이고, 떼면 멈춘다.
  멈춤: 손 떼기 / 버튼 밖으로 나가기 / 창 포커스 잃기 / 한 번에 최대 HOLD_MAX_S초.
- 입력칸·맨 아래 실시간 좌표(copy)는 0.3초마다 갱신. 직접 고친 칸만 노란색으로 남고 movej/movel 목표가 된다.
- 움직이는 중 누른 버튼은 무시, 움직이기 전에 자동 모드로 바꾸고 바뀔 때까지 기다린다. 거부되면 상태·모드를 표시.
- 시작·'툴 확인' 때 펜던트 툴 설정(TCP, 툴 무게)이 config와 같은지 확인하고, 다르면 이동 버튼을 막는다
  (10/04 툴 설정이 풀려 좌표가 플랜지 기준으로 읽힌 사고, #6).
- 축 정렬 x / y / z / r (core/pose_math.py): TCP 위치 고정, 20° 이하 조각, 돌기 전 확인창, 정렬 후 직접교시(선택).
- grip(힘 칸) / release(최대) / 폭만큼 열기(폭 칸), 직접교시 ON/OFF, gohome(확인창).
- 창 닫기(X)·Ctrl+C: 움직이는 중이면 정지 명령을 보내고 깔끔하게 종료.

실행 (PC2 호스트, DSR 드라이버 실행 중, cobot2_ws 등 dsr_msgs2를 source 한 터미널):
    ros2 run ready2go_skills jog_gui                 # colcon 빌드 후
    cd ros2_ws/src/ready2go_skills && python3 -m ready2go_skills.nodes.jog_gui   # 빌드 없이
옵션: --config-dir <저장소>/config (기본: 저장소 config 자동 탐색), --rg2-ip (기본: 환경변수 RG2_HOST)
필요: python3-tk, python3-yaml
"""
import argparse
import os
import signal
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox

import rclpy
import yaml
from dsr_msgs2.srv import (GetCurrentPosj, GetCurrentPosx, GetCurrentTcp, GetCurrentTool, GetRobotMode,
                           GetRobotState, Jog, MoveJoint, MoveLine, MoveStop, SetRobotMode)

from ready2go_skills.adapters.rg2 import Rg2
from ready2go_skills.core.pose_math import align_target, rot, rotation_angle, step_target, waypoints, wrap

SRV = "/dsr01/dsr_controller2"
HOLD_DELAY_MS = 350          # 이보다 오래 누르면 '꾹 누르기'
HOLD_MAX_S = 5.0             # 꾹 누르기 한 번에 최대 시간
REFRESH_TIMEOUT_S = 0.5      # 화면 갱신용 조회 타임아웃 (드라이버가 느려도 정지 처리가 밀리지 않게, #69 PM 검토)
STEP_CONFIRM_DEG = 10.0      # 한 칸 이동이 이보다 크면 확인창 (관절·회전)
STEP_CONFIRM_MM = 20.0       # 한 칸 이동이 이보다 크면 확인창 (직선)
HOME_VEL = 40.0              # gohome 관절 속도 deg/s
ALIGN_VEL, ALIGN_STEP_DEG = 20.0, 20.0
JOINT_VEL, JOINT_ACC, LINE_VEL, LINE_ACC = 20, 20, 30, 60    # 슬라이더 기본값 (강의 jog 60은 빠름)
STATE = {0: "초기화", 1: "대기", 2: "이동 중", 3: "서보 꺼짐", 4: "직접교시", 5: "안전 정지",
         6: "비상정지", 7: "홈", 8: "복구 모드", 9: "안전 정지2", 10: "서보 꺼짐2", 15: "준비 안 됨"}
ALIGN_NAMES = {"x": "x 정렬 (수평·바깥)", "y": "y 정렬 (수평·-y)", "z": "z 정렬 (수직 아래)", "r": "r 정렬 (90° 칸)"}


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
                "tcp": (GetCurrentTcp, "tcp/get_current_tcp"),
                "tool": (GetCurrentTool, "tool/get_current_tool")}
        self.T = {k: v[0] for k, v in spec.items()}
        self.cli = {k: self.node.create_client(t, f"{srv}/{name}") for k, (t, name) in spec.items()}

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

    def movel(self, pose, vel, acc):
        r = self.call("movel", pos=[float(v) for v in pose], vel=[float(vel), float(vel) / 2],
                      acc=[float(acc), float(acc) / 2], ref=0, mode=0, sync_type=1)
        return bool(r and r.success)

    def movej(self, joints, vel, acc):
        r = self.call("movej", pos=[float(v) for v in joints], vel=float(vel), acc=float(acc),
                      time=0.0, radius=0.0, mode=0, blend_type=0, sync_type=1)
        return bool(r and r.success)

    def jog(self, axis, speed):
        r = self.call("jog", jog_axis=axis, move_reference=0, speed=float(speed))
        return bool(r and r.success)

    def stop(self):
        self.call("stop", stop_mode=2)

    def tool_names(self):
        tcp, tool = self.call("tcp"), self.call("tool")
        return (tcp.info if tcp else "?", tool.info if tool else "?")


class Gripper:
    """RG2 명령을 스레드로 보내 창이 멈추지 않게 한다. 결과는 text에 남겨 창 갱신 때 표시."""

    def __init__(self, ip):
        self.ip, self.text = ip, ("" if ip else "RG2 IP 없음 (--rg2-ip 또는 RG2_HOST)")

    def move(self, width, force):
        if not self.ip:
            return

        def run():
            try:
                st = Rg2(self.ip).move(width, force)
                self.text = f"그리퍼 폭 {st.width_mm:.1f} mm (명령 {width:g} mm, {force:g} N)"
            except Exception as e:  # noqa: BLE001 — 창이 죽지 않게 표시만
                self.text = f"RG2 실패: {e}"
            print(self.text)
        threading.Thread(target=run, daemon=True).start()


class App:
    def __init__(self, robot, gripper, settings):
        self.r, self.g, self.cfg = robot, gripper, settings
        self.root = tk.Tk()
        self.root.title("Pos 설정 (jog_gui)")
        self.ok = False
        self.hold = None             # (jog_axis, 시작 시각) 꾹 누르는 중
        self.pending = None          # 꾹 누르기 판정 대기 after id
        self.click = None
        self.quit_req = False        # Ctrl+C 요청 (신호 처리기에서 표시만 하고 watchdog에서 종료)
        self.seq = []                # 정렬 조각 목록 (하나씩 보냄)
        self.move_buttons = []

        self.joint = self.entries(["J1", "J2", "J3", "J4", "J5", "J6", "Speed", "Acc"], 0, JOINT_VEL, JOINT_ACC, 50)
        self.axes = self.entries(["X", "Y", "Z", "Rx", "Ry", "Rz", "Speed", "Acc"], 5, LINE_VEL, LINE_ACC, 100)

        gf = tk.Frame(self.root)
        gf.grid(row=0, column=0, columnspan=9, pady=8)
        self.grip_force = tk.Entry(gf, width=5)
        self.grip_force.insert(0, "20")
        self.grip_width = tk.Entry(gf, width=5)
        self.grip_width.insert(0, "35")
        tk.Button(gf, text="grip", width=8, height=2,
                  command=lambda: self.g.move(0.0, self.num(self.grip_force, 20.0, 40.0))).pack(side=tk.LEFT, padx=2)
        tk.Button(gf, text="release(최대)", height=2, command=lambda: self.g.move(100.0, 20.0)).pack(side=tk.LEFT, padx=2)
        tk.Label(gf, text="grip 힘(N)").pack(side=tk.LEFT, padx=(16, 0))
        self.grip_force.pack(side=tk.LEFT)
        tk.Button(gf, text="폭만큼 열기",
                  command=lambda: self.g.move(self.num(self.grip_width, 35.0, 100.0), 20.0)).pack(side=tk.LEFT, padx=(16, 2))
        tk.Label(gf, text="폭(mm)").pack(side=tk.LEFT)
        self.grip_width.pack(side=tk.LEFT)

        self.mb(tk.Button(self.root, text="movej", command=self.move_by_joint)).grid(row=9, column=1, pady=10)
        tk.Button(self.root, text="copy", command=lambda: self.copy(self.joint, "posj")).grid(row=9, column=2, pady=10)
        self.mb(tk.Button(self.root, text="movel", command=self.move_by_line)).grid(row=9, column=6, pady=10)
        tk.Button(self.root, text="copy", command=lambda: self.copy(self.axes, "posx")).grid(row=9, column=7, pady=10)
        self.inc_j = self.label_entry("Joint Increment", 1)
        self.inc_x = self.label_entry("Linear Increment", 6)

        af = tk.Frame(self.root)
        af.grid(row=11, column=0, columnspan=9, pady=8)
        for mode, text in ALIGN_NAMES.items():
            self.mb(tk.Button(af, text=text, command=lambda m=mode: self.align(m))).pack(side=tk.LEFT, padx=4)
        self.snap = tk.BooleanVar(value=False)
        self.teach_after = tk.BooleanVar(value=True)
        tk.Checkbutton(af, text="직각도 맞춤", variable=self.snap).pack(side=tk.LEFT, padx=4)
        tk.Checkbutton(af, text="정렬 후 직접교시", variable=self.teach_after).pack(side=tk.LEFT, padx=4)

        for i in range(6):
            for column, sign, group in ((2, 1, "j"), (3, -1, "j"), (7, 1, "x"), (8, -1, "x")):
                b = self.mb(tk.Button(self.root, text="+" if sign > 0 else "-"))
                b.grid(row=i + 1, column=column, padx=2, pady=5)
                b.bind("<ButtonPress-1>", lambda e, g=group, i=i, s=sign: self.press(g, i, s))
                b.bind("<ButtonRelease-1>", lambda e: self.release())
                b.bind("<Leave>", lambda e: self.end_hold())

        tk.Label(self.root, text="꾹 누르기 속도(%)\n(4% ≈ 10 mm/s)").grid(row=12, column=0)
        self.hold_speed = tk.Scale(self.root, from_=2, to=10, orient=tk.HORIZONTAL, length=150)
        self.hold_speed.set(4)
        self.hold_speed.grid(row=12, column=1, columnspan=3)
        bf = tk.Frame(self.root)
        bf.grid(row=12, column=4, columnspan=5, pady=6)
        tk.Button(bf, text="정지", bg="#d33", fg="white", width=8, height=2, command=self.stop_all).pack(side=tk.LEFT, padx=4)
        tk.Button(bf, text="직접교시 ON", height=2, command=self.teach_on).pack(side=tk.LEFT, padx=2)
        tk.Button(bf, text="직접교시 OFF", height=2, command=self.teach_off).pack(side=tk.LEFT, padx=2)
        home = self.mb(tk.Button(bf, text="gohome", height=2, command=self.go_home))
        home.pack(side=tk.LEFT, padx=6)
        tk.Button(bf, text="툴 확인", height=2, command=self.check_tool).pack(side=tk.LEFT, padx=2)
        self.banner = tk.Label(self.root, text="", font=("", 10, "bold"))
        self.banner.grid(row=13, column=0, columnspan=9, sticky="we")
        self.status = tk.Label(self.root, text="")
        self.status.grid(row=14, column=0, columnspan=9)

        self.live = {}               # 실시간 좌표 한 줄 (읽기 전용)
        for k, (label, name) in enumerate((("current_posx:", "posx"), ("joint_state:", "posj"))):
            tk.Label(self.root, text=label).grid(row=15 + k, column=0, sticky="e")
            var = tk.StringVar()
            tk.Entry(self.root, textvariable=var, width=70, state="readonly").grid(row=15 + k, column=1, columnspan=7, sticky="we")
            tk.Button(self.root, text="copy", command=lambda v=var: self.copy_text(v.get())).grid(row=15 + k, column=8)
            self.live[name] = var
        self.root.bind("<FocusOut>", lambda e: self.end_hold() if e.widget is self.root else None)   # 창이 포커스를 잃으면 멈춤
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self.on_error

        self.check_tool()
        if not self.cfg["home"]:
            home.config(state="disabled")
        self.refresh()
        self.watchdog()

    # --- 화면 구성 (강의 jog와 같은 배치) ---
    def entries(self, labels, column, vel, acc, max_val):
        out = []
        for i, text in enumerate(labels):
            tk.Label(self.root, text=text).grid(row=i + 1, column=column, padx=10, pady=5)
            if i <= 5:
                e = tk.Entry(self.root, width=10)
                e.dirty = False
                e.bind("<Key>", lambda ev, e=e: self.mark(e))
                e.grid(row=i + 1, column=column + 1, padx=10, pady=5)
            else:
                e = tk.Scale(self.root, from_=5, to=max_val, orient=tk.HORIZONTAL, length=200)
                e.set(vel if i == 6 else acc)
                e.grid(row=i + 1, column=column + 1, padx=10, pady=5, columnspan=3)
            out.append(e)
        return out

    def label_entry(self, text, column):
        tk.Label(self.root, text=text).grid(row=10, column=column - 1, padx=10, pady=5)
        e = tk.Entry(self.root, width=10)
        e.insert(0, "1")
        e.grid(row=10, column=column)
        return e

    @staticmethod
    def num(entry, default, upper):
        try:
            return max(0.0, min(upper, float(entry.get())))
        except ValueError:
            return default

    def mb(self, b):
        self.move_buttons.append(b)
        return b

    def mark(self, e):
        e.dirty = True
        e.config(bg="#ffd")

    def clear_marks(self):
        for e in self.joint[:6] + self.axes[:6]:
            e.dirty = False
            e.config(bg="white")

    def copy(self, entries, name):
        self.copy_text(f"{name}([" + ", ".join(e.get() for e in entries[:6]) + "])")

    def copy_text(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        print(f"copy to clipboard: {text}")

    # --- 상태 ---
    def check_tool(self):
        tcp, tool = self.r.tool_names()
        self.ok = (tcp, tool) == (self.cfg["tcp"], self.cfg["tool"])
        if self.ok:
            self.banner.config(text=f"툴 설정 정상: TCP {tcp}, 툴 {tool}", bg="#cfc", fg="black")
        else:
            self.banner.config(text=f"⚠ 펜던트 툴 설정 확인! TCP '{tcp}'(기대 {self.cfg['tcp']}), "
                                    f"툴 '{tool}'(기대 {self.cfg['tool']}) — 이동 막힘", bg="#d33", fg="white")
        for b in self.move_buttons:
            b.config(state="normal" if self.ok else "disabled")

    def refresh(self):
        if self.hold:                        # 꾹 누르는 동안은 조회하지 않음 — 손을 떼면 바로 정지되게
            self.status.config(text=f"상태: 꾹 누르는 중   {self.g.text}")
            self.root.after(300, self.refresh)
            return
        t = REFRESH_TIMEOUT_S
        for name, values, entries in (("posj", self.r.posj(t), self.joint), ("posx", self.r.posx(t), self.axes)):
            if values:
                self.live[name].set(f"{name}([" + ", ".join(f"{v:.3f}" for v in values) + "])")
                for e, v in zip(entries[:6], values):
                    if not e.dirty:          # 사용자가 고친 칸(노란색)은 덮어쓰지 않음
                        e.delete(0, tk.END)
                        e.insert(0, f"{v:.3f}")
        s = self.r.state(t)
        mode = "정렬 중" if self.seq else STATE.get(s, s)
        self.status.config(text=f"상태: {mode}   ({time.strftime('%H:%M:%S')} 갱신)   {self.g.text}")
        self.root.after(300, self.refresh)

    def can_move(self):
        self.check_tool()                    # 이동 직전마다 다시 확인 — 쓰는 도중 펜던트 설정이 바뀌어도 잡음 (#69 PM 검토)
        if not self.ok:
            return False
        if self.r.state() == 2:
            self.status.config(text="움직이는 중이라 무시함")
            return False
        if not self.r.auto():
            self.status.config(text=f"자동 모드로 못 바꿈 — 상태: {STATE.get(self.r.state(), '?')}, 모드: {self.r.mode_name()}")
            return False
        return True

    def report(self, ok, what):
        """이동 명령 결과를 상태줄에 표시 (거부되면 원인을 찾을 수 있게 상태·모드도)."""
        if ok:
            self.status.config(text=f"{what} 시작")
        else:
            self.status.config(text=f"{what} 거부됨 — 상태: {STATE.get(self.r.state(), '?')}, 모드: {self.r.mode_name()}")

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
            self.status.config(text=f"꾹 누르기 {HOLD_MAX_S:.0f}초 제한으로 멈춤 — 다시 누르세요")
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
            self.status.config(text="Increment 칸에 숫자를 넣으세요")
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

    # --- 축 정렬 ---
    def align(self, mode):
        if not self.can_move():
            return
        p = self.r.posx()
        if p is None:
            return
        target = align_target(p, mode, self.snap.get())
        self.seq = waypoints(p, target, ALIGN_STEP_DEG)
        if not self.seq:
            self.status.config(text="이미 정렬되어 있음")
            self.after_align()
            return
        turn = rotation_angle(rot(*p[3:]), rot(*target[3:]))
        dmax = max(abs(wrap(target[i] - p[i])) for i in range(3, 6))
        msg = (f"{ALIGN_NAMES[mode]}{' + 직각' if self.snap.get() and mode != 'r' else ''}\n\n"
               f"현재  {[round(v, 2) for v in p[3:]]}\n목표  {[round(v, 2) for v in target[3:]]}\n\n"
               f"회전 {turn:.1f}° → {len(self.seq)}조각(조각당 {ALIGN_STEP_DEG:g}° 이하), {ALIGN_VEL:g}°/s\n"
               f"Rx·Ry·Rz 최대 변화 {dmax:.1f}°\n위치는 그대로, 방향만 돌립니다.")
        if dmax > 90.0:
            msg += "\n\n주의: 각도 값이 90° 넘게 바뀝니다. 그리퍼가 크게 돌 수 있으니 주변을 확인하세요."
        print(msg.replace("\n\n", "\n"))
        if not messagebox.askokcancel("축 정렬 확인", msg, parent=self.root):
            self.seq = []
            self.status.config(text="정렬 취소")
            return
        self.next_piece()

    def next_piece(self):
        """정렬 조각을 하나 보내고, 끝나면(이동 중 아님) 다음 조각. 정지 버튼을 누르면 목록을 비운다."""
        if not self.seq:
            return
        if not self.r.movel(self.seq.pop(0), ALIGN_VEL, ALIGN_VEL * 2):
            self.seq = []
            self.report(False, "정렬")
            return
        self.wait_piece(time.monotonic(), False)

    def wait_piece(self, t0, seen):
        st = self.r.state()
        seen = seen or st == 2
        if (seen or time.monotonic() - t0 > 1.0) and st != 2:
            if self.seq:
                self.next_piece()
            else:
                self.after_align()
            return
        self.root.after(80, lambda: self.wait_piece(t0, seen))

    def after_align(self):
        self.clear_marks()
        if self.teach_after.get():
            self.r.teach()
            self.status.config(text="정렬 끝 → 직접교시 ON")

    # --- 모드·홈·정지 ---
    def teach_on(self):
        self.r.teach()
        self.status.config(text="직접교시 ON")

    def teach_off(self):
        self.r.teach_off()
        self.status.config(text="직접교시 OFF (자동 모드)")

    def go_home(self):
        home = self.cfg["home"]
        if not messagebox.askokcancel("gohome", f"홈 {home} 으로 관절 이동합니다 ({HOME_VEL:g}°/s).\n"
                                      "서랍 안이나 물건 옆이면 먼저 빼고 누르세요.", parent=self.root):
            return
        if self.can_move():
            self.report(self.r.movej(home, HOME_VEL, HOME_VEL), "gohome")
            self.clear_marks()

    def stop_all(self):
        self.seq = []                        # 정렬 중이면 남은 조각 취소
        self.end_hold()
        self.r.stop()

    def close(self):
        """창 닫기·Ctrl+C: 움직이는 중이면 멈추고 종료."""
        if self.hold or self.seq or self.r.state() == 2:
            self.stop_all()
        self.root.destroy()

    def on_error(self, exc, val, tb):
        if issubclass(exc, KeyboardInterrupt):
            self.close()
            return
        traceback.print_exception(exc, val, tb)
        self.status.config(text=f"오류: {val} (터미널 참고)")


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
