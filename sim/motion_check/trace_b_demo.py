#!/usr/bin/env python3
"""B 시연 스크립트(ready2go_skills/scripts/b_demo.py, 스킬 서버 없이 DSR·RG2 직접)의 실제 코드로 흐름을 돌려 궤적을 계산한다 (담당 A).

  python3 sim/motion_check/trace_b_demo.py --repo <B 저장소> --out trace_demo.json

- b_demo.py 를 그대로 불러(ROS·DSR·RG2 는 가짜) run() 의 단계를 차례로 실행한다. 로봇 객체만 기구학 가짜 로봇으로 바꾼다
  (movej·movel·movel_watch·movesj → trace_skill_flow.KinRobot 와 같은 계산).
- 힘 감시(movel_watch)는 접촉을 흉내 낸다: 누르기(pressed)만 지우개 윗면 예상 높이(PRESS_START z − 5 mm)에서 3 N, 그 밖은 0 N.
  감시 함수와 연속 확인(confirm)은 b_demo 의 것을 그대로 부른다.
- 결과 형식은 trace_skill_flow.py 와 같다(play_motion_trace.py 로 재생). 단계 이름: open·view·down·press·pick·carry·place·close.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m0609_kin as kin  # noqa: E402
from trace_skill_flow import HOME_J, KinRobot, save_trace, stub_ros  # noqa: E402

STEP_NAMES = ["open", "view", "down", "press", "pick", "carry", "place", "close"]
WATCH_STAGE = {"open": ["reach_handle", "pull"], "press": ["press", "drag"], "close": ["push"]}


class DemoRobot(KinRobot):
    """b_demo.Robot 와 같은 메서드 이름. 동기 이동은 바로 끝난 것으로 본다."""

    def __init__(self, q0, demo):
        super().__init__(q0)
        self.demo, self._watch_n = demo, 0

    def check_tool(self):
        return None

    def _finish(self):                                                   # b_demo 의 이동은 동기(끝날 때까지 기다림) → 경로 끝까지
        while self._path:
            self.p, self.j = self._path.pop(0)
        self._moving = 0

    def halt(self, *a, **k):
        return None

    def grip(self, width, force):                                        # 손잡이 8 mm·지우개 21 mm·빈 손 0.9 mm (실제 폭 흉내)
        d = self.demo
        w = float(width) if width > 0 else {d.GRIP_HANDLE_N: 8.0, d.GRIP_ERASER_N: 21.0}.get(force, 0.9)
        self.grip_events.append(dict(before_segment=len(self.segments), width_mm=w, step=self.step))
        return types.SimpleNamespace(width_mm=w)

    def movej(self, j, vel=20.0):
        self.stage = self.step
        if abs(j[4]) > self.demo.J5_MAX:
            raise self.demo.Stop(f"J5 {j[4]}° > {self.demo.J5_MAX}°")
        self.movej_async(j, vel, vel)

    def movel(self, x, vel=50.0, rot=15.0):
        self.stage = self.step
        self.movel_async(list(x), vel, vel, rot, rot)
        self._finish()

    def movesj(self, pts, vel=20.0):
        self.stage = self.step
        self.movesj_async(pts, vel, vel)

    def movel_watch(self, x, vel, watch, timeout_s, confirm=1):
        names = WATCH_STAGE.get(self.step, [])
        self.stage = names[self._watch_n] if self._watch_n < len(names) else f"watch{self._watch_n}"
        self._watch_n += 1
        x = list(x)
        p0 = np.array(self.p[:3])
        d = np.array(x[:3]) - p0
        n = max(2, int(np.linalg.norm(d) / 0.25))
        contact_z = self.demo.PRESS_START[2] - 5.0 if getattr(watch, "__name__", "") == "pressed" else None
        streak = 0
        for k in range(1, n + 1):
            p = list(p0 + d * k / n) + x[3:]
            f = [0.0, 0.0, 3.0 if contact_z is not None and p[2] <= contact_z else 0.0]
            hit = watch(p, f)
            streak = streak + 1 if hit else 0
            if hit and streak >= confirm:
                self.movel_async(p, vel, vel)                             # 멈춘 곳까지만
                self._finish()
                return hit
        self.movel_async(x, vel, vel)
        self._finish()
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="trace_demo.json")
    a = ap.parse_args()
    repo = Path(a.repo).resolve()
    stub_ros()
    for name in ("rclpy.signals", "std_msgs", "std_msgs.msg"):
        if name not in sys.modules:
            m = types.ModuleType(name)
            m.SignalHandlerOptions = types.SimpleNamespace(NO=None)
            m.Float64MultiArray = object
            sys.modules[name] = m
    sys.path.insert(0, str(repo / "ros2_ws/src/ready2go_skills"))
    spec = importlib.util.spec_from_file_location("b_demo", repo / "ros2_ws/src/ready2go_skills/scripts/b_demo.py")
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    robot = DemoRobot(HOME_J, demo)

    demo.grip = robot.grip                                               # 예전 b_demo 는 모듈 함수 grip, 지금은 r.grip
    demo.time.sleep = lambda s: None
    steps, results = demo.run(robot), []
    for (title, fn), step in zip(steps, STEP_NAMES):
        robot.step, robot._watch_n, robot.stage = step, 0, step
        n0 = len(robot.segments)
        try:
            fn()
            ok, err = True, ""
        except demo.Stop as e:
            ok, err = False, str(e)
        for s in robot.segments[n0:]:
            s["step"] = step
            if s["stage"] in (step, ""):
                s["stage"] = f"{step}:{s['kind']}"
        results.append(dict(step=step, title=title, success=ok, error=err, segments=len(robot.segments) - n0))
        print(f"{step:6s} {title:32s} {'성공' if ok else '실패 ' + err} (이동 {len(robot.segments) - n0}개)")
        if not ok:
            break
    ers = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
           "pose": {"frame": "drawer_top", "position": [0.1769, 0.2895, 0.0], "yaw": 0.0, "yaw_valid": True}}   # b_sk·#22 실측
    after = {**ers, "pose": {**ers["pose"], "position": [0.1769, round(0.2895 - demo.DRAG_MM / 1000.0, 4), 0.0]}}   # base −x = 서랍 −y
    save_trace(robot, repo, a.out, results, ers, after)


if __name__ == "__main__":
    main()
