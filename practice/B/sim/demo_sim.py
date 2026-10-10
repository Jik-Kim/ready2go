"""P2 시연 흐름을 B 스킬 서버 실제 코드 + 기구학 가짜 로봇(A sim/motion_check)으로 돌림. A 파일은 고치지 않고 가져다 씀."""
import sys, json, math, types, importlib
from pathlib import Path
import numpy as np
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "sim/motion_check"))
import trace_skill_flow as tsf
import m0609_kin as kin

class Robot(tsf.KinRobot):
    STEP_MM, STEP_DEG = 3.0, 1.5                         # IK 간격 (A 도구 0.5 mm·0.25° 보다 거칠게 — 빠르게, 특이점 판정은 충분)

    def movel_async(self, p, vel, acc, rot_vel=30.0, rot_acc=60.0, radius=0.0):
        if self._path:                                   # 이동 중에 새 명령(블렌딩): 남은 경로 끝으로 건너뜀
            self.p, self.j = self._path[-1]; self._path = []
        return self.moveb_async([p], [0.0], vel, acc, rot_vel, rot_acc, kind="movel")

    def movej_async(self, j, vel, acc):
        if self._path:
            self.p, self.j = self._path[-1]; self._path = []
        return super().movej_async(j, vel, acc)

    def moveb_async(self, pts, radii, vel, acc, rot_vel=30.0, rot_acc=60.0, kind="moveb"):
        if self._path:
            self.p, self.j = self._path[-1]; self._path = []
        path_all, traj_all, fail, p, q = [], [list(self.j)], 0, list(self.p), self.j
        dist_tot, ang_tot = 0.0, 0.0
        for pt in pts:
            dist = float(np.linalg.norm(np.array(pt[:3]) - np.array(p[:3])))
            _, ang = kin.interp_line(p, pt, 1)
            n = max(2, int(max(dist / self.STEP_MM, ang / self.STEP_DEG)))
            Ts, _ = kin.interp_line(p, pt, n)
            for T in Ts[1:]:
                q, ok = kin.ik(T, q)
                fail += 0 if ok else 1
                traj_all.append(list(map(float, q)))
                path_all.append(((T[:3, 3] * 1000.0).tolist() + list(pt[3:]), list(map(float, q))))
            dist_tot += dist; ang_tot += ang; p = list(pt)
        self._record(kind, self.p, list(pts[-1]), traj_all, dict(vel=vel, acc=acc, rot_vel=rot_vel, rot_acc=rot_acc,
                                                                   dist_mm=dist_tot, rot_deg=ang_tot, ik_fail=fail, n_pts=len(pts)))
        idx = np.linspace(0, len(path_all) - 1, min(len(path_all), 200)).round().astype(int)
        self._path = [path_all[i] for i in idx]
        self._path[-1] = (list(pts[-1]), path_all[-1][1])
        self._path_i, self._path_n = 0, len(self._path)
        self._moving = 1
        return True

def load(robot):
    tsf.stub_ros()
    sys.path.insert(0, str(REPO / "ros2_ws/src/ready2go_skills"))
    from ready2go_skills.core import skill_flow as sf, grasp_check as gc
    from ready2go_skills.core.rg2_protocol import Rg2Status
    ss = importlib.import_module("ready2go_skills.nodes.skill_server")
    real_wait = sf.wait_motion
    def fast_wait(**kw):
        kw.update(settle_s=0.0, sleep=lambda s: None)
        return real_wait(**kw)
    sf.wait_motion = fast_wait
    ss.time.sleep = lambda s: None
    class Gripper:
        width = 99.0
        def __init__(self, ip): pass
        def move(self, w, f):
            Gripper.width = {"open": 8.0}.get(robot.step, Gripper.width if w == 0 else float(w)) if w == 0 else float(w)
            if w == 0 and robot.step not in ("open", "pick"):
                Gripper.width = 0.9
            robot.grip_events.append(dict(before_segment=len(robot.segments), width_mm=Gripper.width, step=robot.step))
            return Rg2Status(Gripper.width, False, w == 0, False)
        def status(self): return Rg2Status(Gripper.width, False, True, False)
        def close(self): pass
    ss.Rg2 = Gripper
    real_check = gc.check_grasp
    def check_grasp(**kw):                       # 잡은 폭 = 기대 폭 (실물 폭은 실측으로)
        if kw.get("expected_width_m"):
            kw["width_m"] = kw["expected_width_m"]; Gripper.width = kw["width_m"] * 1000.0
        return real_check(**kw)
    ss.gc.check_grasp = check_grasp
    import yaml
    tsf.SEARCH_BELOW_MM[0] = (yaml.safe_load(Path(ss.PARAMS_FILE).read_text(encoding="utf-8")).get("drag") or {}).get("search_below_mm")
    srv = object.__new__(ss.SkillServer)
    srv.cfg_dir, srv.params_file, srv.rg2_ip = REPO / "config", ss.PARAMS_FILE, "x"
    srv.robot, srv.disp, srv.held, srv.tray = robot, {}, None, {}
    srv.state = sf.MotionState(robot.state, robot.posj)
    srv.move_timeout, srv.joint_vel, srv.joint_acc, srv.reach_tol = 30.0, 20.0, 20.0, 0.5
    real_line = ss.SkillServer._line
    def line(self, goal, posx, vel, stage, watch=None, **kw):
        robot.stage, robot.from_line = stage, True
        if stage != "drag":
            robot.contact = tsf.contact_for(stage, robot.p, posx)
        return real_line(self, goal, posx, vel, stage, watch, **kw)
    ss.SkillServer._line = line
    real_blend = ss.SkillServer._blend
    def blend(self, goal, points, radii, vel, stage):
        robot.stage, robot.contact = stage, None
        return real_blend(self, goal, points, radii, vel, stage)
    ss.SkillServer._blend = blend
    real_named = ss.SkillServer._named
    def named(self, goal, pose_name, drawer_id=None, **k):
        robot.stage, robot.contact, robot.from_line = f"to_{pose_name}", None, False
        return real_named(self, goal, pose_name, drawer_id, **k)
    ss.SkillServer._named = named
    real_movej = ss.SkillServer._movej
    def movej(self, goal, joints, stage, **k):
        robot.stage, robot.contact = stage, None
        return real_movej(self, goal, joints, stage, **k)
    ss.SkillServer._movej = movej
    return ss, sf, srv

def obj(oid, cls, x, y, yaw, top_z, drawer):
    return {"id": oid, "class": cls, "top_z": top_z, "pose": {"frame": drawer, "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": True}}

def run_scenario(name, drawer, steps):
    robot = Robot(tsf.HOME_J)
    ss, sf, srv = load(robot)
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)
    print(f"\n===== {name} ({drawer}) =====")
    ok_all = True
    ctx = {}
    for label, action, params in steps:
        if callable(params):
            params = params(ctx)
        robot.step = "open" if action == "drawer_control" and params.get("state") == "open" else ("pick" if action == "pick_object" else label)
        n0 = len(robot.segments)
        out, data = sf.run_guarded(lambda: getattr(srv, f"_do_{action}")(goal, json.loads(json.dumps(params))), stop=robot.stop, get_state=srv.state)
        ctx[label] = data
        ctx["_" + label.split()[0] + "_reason"] = out.reason or ""
        segs = robot.segments[n0:]
        ikf = sum(s.get("ik_fail", 0) for s in segs)
        bad = [s for s in segs if s["kind"] in ("movel", "moveb") and (s["min_abs_j3"] < 15 or s["min_abs_j5"] < 10)]
        jmax = max((max(abs(v) for v in s["joints"][-1]) for s in segs), default=0)
        print(f"  {label:26s} {'OK ' if out.success else 'FAIL'} {out.error_code or ''} {(out.reason or '')[:110]}")
        if ikf or bad:
            print(f"      ⚠ IK실패 {ikf}점, 특이점 근처 구간 {[(s['stage'], round(s['min_abs_j3'],1), round(s['min_abs_j5'],1)) for s in bad][:4]}")
        if not out.success:
            ok_all = False
            break
    return ok_all, robot, srv
