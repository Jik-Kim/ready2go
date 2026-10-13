#!/usr/bin/env python3
"""B `unpack`(= Runner find_with_unpack 순서)을 로봇 없이 돌려 로봇 궤적과 물체 움직임을 기록한다 (담당 A, 트윈 사전 검증).

  python3 sim/motion_check/trace_unpack.py --dump <실물 덤프 .npz> [<다음 인식 덤프> ...] --target toy_wrench --out /tmp/unpack.json
  재생: ISAAC_SIM_CMD=$HOME/isaac-sim-5.1.0/python.sh bash sim/run_isaac.sh sim/scripts/play_motion_trace.py --trace /tmp/unpack.json

- B 스크립트 `ready2go_skills/scripts/b_sk.py` 의 `unpack()` 을 그대로 부른다(고르기·치우기·복구 판단 = Runner core.unpack).
  스킬은 B 스킬 서버 실제 코드(trace_skill_flow.py 와 같은 기구학 가짜 로봇). ROS·DSR·RG2 는 가짜.
- 인식: --dump 를 여러 개 주면 n 번째 인식에 n 번째 덤프를 이 저장소 비전 코드로 다시 계산해 쓴다(실물 회차의 인식 순서 그대로 —
  같은 회차의 덤프를 순서대로 주면 실물과 같은 인식으로 로봇 동작만 본다). 덤프가 모자라면 그 뒤는 가상 인식: 장면 기록에서 만든다
  (집으면 빠지고, 놓으면 놓은 자리에 온톨로지 높이로 생김, 다른 물체 위에 놓으면 그 위 높이 + occluded_by).
  가상 인식 한계: 가려졌던 물체는 덮은 것을 치워도 처음 (치우친) 위치·각도 그대로 — 실물은 다시 찍으면 바로잡힘. 결과 scans 에 출처 표시.
- 집기는 항상 성공한다고 본다(그리퍼 폭 = 기대 폭). 미끄러짐·무너짐·접촉은 흉내 내지 않는다.
- 결과: trace_skill_flow 형식(segments·grip_events) + `scene_events`(구간 번호마다 물체 상태·쥔 물체) + `log`(b_sk 출력).
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import importlib
import io
import json
import math
import sys
import types
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import trace_skill_flow as tsf  # noqa: E402


def replay_dump(npz: Path, target: str):
    """덤프의 검출(박스·마스크)·뎁스로 이 저장소 비전 코드를 다시 돌린 결과(result_json dict)."""
    import yaml
    sys.path.insert(0, str(ROOT / "ros2_ws/src/ready2go_vision"))
    from ready2go_vision.core.dump_masks import restore_masks
    from ready2go_vision.core.geometry import Intrinsics
    from ready2go_vision.core.inspect_real import inspect_scene
    z = np.load(npz, allow_pickle=False)
    m = json.loads(str(z["meta"]))
    dets = restore_masks([dict(d) for d in m["detections"]], z["masks"] if "masks" in z else None, z["color"].shape[1])
    params = yaml.safe_load((ROOT / "config/vision_params.yaml").read_text(encoding="utf-8"))
    items = json.loads((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))["world"]["items"]
    ok, err, js = inspect_scene(dets, z["depth_m"].astype(float), Intrinsics(*m["K"]), z["T_drawer_cam"], params, items,
                                m["request"]["region"], target, m.get("interior_m"), region_height_m=m.get("region_height_m"))
    if not ok:
        sys.exit(f"덤프 다시 계산 실패: {err}")
    return json.loads(js), m["request"]["region"]


class Scene:
    """가상 인식: 물체 목록(inspect_region 결과 항목)을 들고, 집기·놓기 결과로 갱신한다."""

    def __init__(self, first: dict, drawer: str, items: dict):
        self.objs = {o["id"]: copy.deepcopy(o) for o in ([first["target"]] if first.get("target") else []) + list(first.get("candidates") or [])}
        self.drawer, self.items, self.held, self.away = drawer, items, None, []
        self.events = []

    def snapshot(self, seg_i: int, why: str):
        self.events.append({"before_segment": seg_i, "why": why, "held": self.held and self.held["id"],
                            "objects": copy.deepcopy(list(self.objs.values())), "away": list(self.away)})

    def reset(self, res: dict):
        """실물 덤프 인식으로 장면을 바꿈(쥔 물체는 그대로)."""
        self.objs = {o["id"]: copy.deepcopy(o) for o in ([res["target"]] if res.get("target") else []) + list(res.get("candidates") or [])}

    def scan(self, search: str) -> dict:
        objs = [copy.deepcopy(o) for o in self.objs.values()]
        t = next((o for o in objs if o["class"] == search), None)
        return {"target_found": t is not None, "target": t, "candidates": [o for o in objs if o is not t], "visible_count": len(objs)}

    def pick(self, oid: str):
        o = self.objs.pop(oid)
        for x in self.objs.values():
            if x.get("occluded_by"):
                x["occluded_by"] = [i for i in x["occluded_by"] if i != oid]
        self.held = o

    def place(self, pose: dict | None):
        """pose = 놓은 자리(서랍 좌표, placed_pose). None = 서랍 밖(트레이)."""
        o, self.held = self.held, None
        if pose is None:
            self.away.append(o["id"])
            return
        x, y = pose["position"][:2]
        size = self.items[o["class"]]["size_m"]
        under = [u for u in self.objs.values() if _inside(x, y, u, self.items)]
        base = max((u["top_z"] for u in under), default=0.0)
        o["pose"] = {"frame": self.drawer, "position": [round(x, 4), round(y, 4), 0.0], "yaw": round(float(pose.get("yaw") or 0.0), 4), "yaw_valid": True}
        o["top_z"] = round(base + size[2], 4)
        o["occluded_by"] = []
        for u in under:
            if u["top_z"] < o["top_z"]:
                u["occluded_by"] = sorted(set((u.get("occluded_by") or []) + [o["id"]]))
        self.objs[o["id"]] = o


def _inside(x, y, u, items) -> bool:
    """(x, y) 가 물체 u 의 외접 사각형(yaw 회전) 안인가."""
    L, W = items[u["class"]]["size_m"][:2]
    px, py = u["pose"]["position"][:2]
    c, s = math.cos(u["pose"]["yaw"]), math.sin(u["pose"]["yaw"])
    dx, dy = x - px, y - py
    return abs(dx * c + dy * s) <= L / 2 and abs(-dx * s + dy * c) <= W / 2


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", required=True, nargs="+", help="인식에 차례로 쓸 실물 덤프 .npz (첫 번째는 필수, 모자라면 가상 인식)")
    ap.add_argument("--target", required=True, help="꺼낼 물체 클래스 (예: toy_wrench, eraser)")
    ap.add_argument("--out", default="unpack_trace.json")
    a = ap.parse_args()
    first, drawer = replay_dump(Path(a.dump[0]), a.target)
    items = json.loads((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))["world"]["items"]
    scene = Scene(first, drawer, items)

    robot = tsf.KinRobot(tsf.HOME_J)
    ss, sf, srv, Gripper = tsf.load_server(ROOT, robot)
    real_check = ss.gc.check_grasp

    def check_grasp(**kw):                                       # 집기는 항상 성공(폭 = 기대 폭) — 미끄러짐·접촉은 흉내 내지 않음
        Gripper.width = kw["expected_width_m"] * 1000.0          # 들어 올린 뒤 폭 확인(미끄러짐)도 같은 폭
        return real_check(**dict(kw, width_m=kw["expected_width_m"], grasp_detected=True))
    ss.gc.check_grasp = check_grasp

    sys.path.insert(0, str(ROOT / "ros2_ws/src/ready2go_skills/scripts"))
    tsf.stub_ros()
    for name, attrs in (("rclpy.signals", {"SignalHandlerOptions": object}), ("rclpy.action", {"ActionClient": object})):
        sys.modules.setdefault(name, types.ModuleType(name))
        for k, v in attrs.items():
            setattr(sys.modules[name], k, v)
    sys.modules["ready2go_interfaces.action"].Skill = types.SimpleNamespace(Feedback=lambda stage: stage, Goal=dict)
    b = importlib.import_module("b_sk")
    tmp = Path(a.out).resolve().parent / (Path(a.out).stem + "_tmp")
    tmp.mkdir(exist_ok=True)
    b.TMP, b.AFTER, b.TRAY_FILE, b.HELD_FILE = str(tmp), str(tmp / "after.json"), str(tmp / "tray.json"), str(tmp / "held.json")
    b.DRAWER, b.TARGET = drawer, a.target
    goal = types.SimpleNamespace(is_cancel_requested=False, publish_feedback=lambda f: None)
    results = []

    def run(node, cmd, goal_=None, retried=False):
        action, params = goal_ or b.goal_for(cmd)
        robot.step = cmd
        n0 = len(robot.segments)
        out, data = sf.run_guarded(lambda: getattr(srv, f"_do_{action}")(goal, json.loads(json.dumps(params))),
                                   stop=robot.stop, get_state=srv.state)
        for s in robot.segments[n0:]:
            s["step"] = cmd
        b.last["code"], b.last["out"] = out.error_code, data
        results.append(dict(step=cmd, action=action, success=out.success, error=out.error_code, reason=getattr(out, "reason", ""),
                            segments=len(robot.segments) - n0, first_segment=n0,
                            target=((params.get("target") or {}).get("id")), slot=params.get("slot"), location=params.get("location")))
        print(f"[{cmd}] {action} success={out.success} {out.error_code or ''} {getattr(out, 'reason', '') or ''} (이동 {len(robot.segments) - n0}개)")
        if out.success and action == "pick_object":
            scene.pick(params["target"]["id"])
            scene.snapshot(len(robot.segments), f"집음 {params['target']['id']}")
        elif out.success and action == "place_object":
            pose = (data or {}).get("placed_pose") if params.get("location") != "handover_zone" else None
            scene.place(pose)
            scene.snapshot(len(robot.segments), f"놓음 {params.get('location')} {params.get('slot') or ''}")
        return out.success

    scans = []

    def inspect_all(node, search):
        if not b.timed("view", lambda: run(node, "view")):
            sys.exit(f"탑뷰로 못 감 {b.last['code']}")
        k = len(scans)
        if k < len(a.dump):
            res, _ = replay_dump(Path(a.dump[k]), search) if k else (first, None)
            if k:
                scene.reset(res)
                scene.snapshot(len(robot.segments), f"인식 {k + 1}: 실물 덤프 {Path(a.dump[k]).name}")
            scans.append({"n": k + 1, "source": Path(a.dump[k]).name, "segment": len(robot.segments)})
        else:
            res = scene.scan(search)
            scans.append({"n": k + 1, "source": "가상", "segment": len(robot.segments)})
        print(f"  (인식 {k + 1}: {scans[-1]['source']})")
        b.print_seen(res)
        return res

    b.run, b.inspect_all = run, inspect_all
    scene.snapshot(0, "첫 장면 (덤프 다시 계산)")
    log = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(log):
            ok = b.unpack(None)
    except SystemExit as e:
        ok, code = False, e.code
    text = log.getvalue()
    print(text)
    if code:
        print(f"*** b_sk unpack 중단: {code}")
    tsf.save_trace(robot, ROOT, a.out, results, first.get("target") or {}, None)
    d = json.loads(Path(a.out).read_text())
    d.update(scene_events=scene.events, scans=scans, log=text, stopped=str(code) if code else "", unpack_ok=bool(ok), dump=[str(x) for x in a.dump], target_class=a.target)
    Path(a.out).write_text(json.dumps(d, ensure_ascii=False))
    print(f"\nunpack {'성공' if ok else '실패/중단'} — 장면 기록 {len(scene.events)}개 → {a.out}")


if __name__ == "__main__":
    main()
