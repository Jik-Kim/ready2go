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
  가상 인식은 높이로 보아 불가능한 얹힘 관계(덮은 것 윗면 < 두 물체 높이 합 − 6 mm)를 뺀다(경계 높이 헛관계는 다시 찍으면 대개 사라짐 [추정]).
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


LEGGED = {"cover_plate"}                                 # 다리로 서는 물체 — 밑에 다른 물체가 들어감 (B clear_plan LEG_CLASSES 와 같은 뜻)


class Scene:
    """가상 인식: 물체 목록(inspect_region 결과 항목)을 들고, 집기·놓기 결과로 갱신한다."""

    def __init__(self, first: dict, drawer: str, items: dict):
        self.objs = {o["id"]: copy.deepcopy(o) for o in ([first["target"]] if first.get("target") else []) + list(first.get("candidates") or [])}
        self.drawer, self.items, self.held, self.away = drawer, items, None, []
        self.placed = {}                                        # 이번 시뮬에서 놓은 자리 (실물 덤프와 갈렸는지 볼 때)
        self.events = []

    def snapshot(self, seg_i: int, why: str):
        self.events.append({"before_segment": seg_i, "why": why, "held": self.held and self.held["id"],
                            "objects": copy.deepcopy(list(self.objs.values())), "away": list(self.away)})

    def reset(self, res: dict):
        """실물 덤프 인식으로 장면을 바꿈(쥔 물체는 그대로)."""
        self.objs = {o["id"]: copy.deepcopy(o) for o in ([res["target"]] if res.get("target") else []) + list(res.get("candidates") or [])}

    def scan(self, search: str) -> dict:
        objs = [copy.deepcopy(o) for o in self.objs.values()]
        tops = {o["id"]: o["top_z"] for o in objs}
        for o in objs:                                          # 가상 인식: 높이로 보아 불가능한 얹힘(덮은 것 윗면 < 두 물체 온톨로지 높이 합 − 6 mm)은 뺌
            if o.get("occluded_by"):                            # — 실물 경계 높이 헛관계(10/13 030105 립밤)는 덮개를 치우고 다시 찍으면 대개 사라짐 [추정]
                h = self.items[o["class"]]["size_m"][2]
                cls = {x["id"]: x["class"] for x in objs}
                o["occluded_by"] = [c for c in o["occluded_by"] if c not in tops or cls[c] in LEGGED or
                                    tops[c] >= h + self.items[cls[c]]["size_m"][2] - 0.006]
        t = next((o for o in objs if o["class"] == search), None)
        return {"target_found": t is not None, "target": t, "candidates": [o for o in objs if o is not t], "visible_count": len(objs)}

    def pick(self, oid: str):
        o = self.objs.pop(oid)
        for x in self.objs.values():
            if x.get("occluded_by"):
                x["occluded_by"] = [i for i in x["occluded_by"] if i != oid]
        self.held = o

    def move(self, oid: str, pose: dict | None):
        """넛지·밀기로 옮겨진 물체 (스킬 서버의 예상 자리 — 실물은 다시 찍어 확인)."""
        if pose and oid in self.objs:
            o = self.objs[oid]
            o["pose"] = dict(o["pose"], position=[round(pose["position"][0], 4), round(pose["position"][1], 4), 0.0],
                             yaw=round(float(pose.get("yaw", o["pose"]["yaw"])), 4))

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
        self.placed[o["id"]] = (x, y)
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
    ap.add_argument("--mode", default="unpack", choices=("unpack", "clear"),
                    help="unpack = B unpack (Runner find_with_unpack 순서) / clear = B clear (nudge_object make_room 반복 → 집기 → 트레이)")
    ap.add_argument("--pre-remove", default="", help="시작 전에 이 id 들을 집어 서랍 빈 자리(free)에 둠 (쉼표). 예: cover_plate#1")
    a = ap.parse_args()
    first, drawer = replay_dump(Path(a.dump[0]), a.target)
    items = json.loads((ROOT / "knowledge/world.jsonld").read_text(encoding="utf-8"))["world"]["items"]
    scene = Scene(first, drawer, items)

    robot = tsf.KinRobot(tsf.HOME_J)
    ss, sf, srv, Gripper = tsf.load_server(ROOT, robot)
    _log = types.SimpleNamespace(info=lambda m: print(f"  [서버] {m}"), warn=lambda m: print(f"  [서버 경고] {m}"),
                                 warning=lambda m: print(f"  [서버 경고] {m}"), error=lambda m: print(f"  [서버 오류] {m}"))
    srv.get_logger = lambda: _log                                # 가짜 서버(object.__new__)엔 ROS 로거가 없음
    real_check = ss.gc.check_grasp

    def check_grasp(**kw):                                       # 집기는 항상 성공(폭 = 기대 폭) — 미끄러짐·접촉은 흉내 내지 않음
        Gripper.width = kw["expected_width_m"] * 1000.0          # 들어 올린 뒤 폭 확인(미끄러짐)도 같은 폭
        if robot.grip_events:                                    # 재생기가 닫는 폭 = 잡은 물체 폭 (가짜 그리퍼의 고정 닫힘 21·0.9 mm 가 아니라)
            robot.grip_events[-1]["width_mm"] = Gripper.width    # — 예전엔 손가락이 물체를 뚫고 닫혀 옆 물체까지 파고듦 [사용자 영상 10/13]
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
        b.last["make_room"] = (data or {}).get("make_room") if cmd == "clear" else None   # b_sk run 과 같게 (clear 가 ready_to_pick 을 봄)
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
        elif out.success and action == "nudge_object" and data:
            mr = data.get("make_room") or {}
            tid = (params.get("target") or {}).get("id")
            moved = []
            if mr.get("moved_id"):
                moved.append((mr["moved_id"], mr.get("placed_pose") or mr.get("moved_after")))
            moved += [(p_["id"], p_) for p_ in mr.get("pushed_after") or []]
            if data.get("target_after") and (not mr or mr.get("moved_id") == tid):
                moved.append((tid, data["target_after"].get("pose") if "pose" in data["target_after"] else data["target_after"]))
            for oid, pose in moved:
                scene.move(oid, pose)
            if moved:
                scene.snapshot(len(robot.segments), f"옮김 {[m[0] for m in moved]} ({mr.get('action') or 'nudge'})")
        return out.success

    scans = []
    diverged = []

    def use_dump(k, search):
        """k 번째 실물 덤프를 쓸 수 있으면 그 인식. 이번 시뮬에서 놓은 물체가 덤프와 20 mm 넘게 다르면(B 가 실물 회차와 다른 자리에 놓음)
        그 물체만 시뮬 자리로 바꿔 합침 — 손대지 않은 물체(예: 덮개를 치운 뒤 다 보이는 캐러멜)는 실물 인식 그대로 [가려진 자리 오차 방지]."""
        if k >= len(a.dump):
            return None
        res = replay_dump(Path(a.dump[k]), search)[0] if k else first
        objs_ = {o["id"]: o for o in ([res["target"]] if res.get("target") else []) + list(res.get("candidates") or [])}
        moved = set(scene.placed) | set(scene.away) | ({scene.held["id"]} if scene.held else set())
        off = []
        for oid in moved:
            o = objs_.get(oid)
            sim = scene.objs.get(oid)
            if sim is None:                                    # 트레이로 갔거나 쥔 것 — 덤프에 있으면 빼야 함
                if o is not None:
                    off.append(oid)
                continue
            if o is None or math.hypot(o["pose"]["position"][0] - sim["pose"]["position"][0], o["pose"]["position"][1] - sim["pose"]["position"][1]) > 0.02:
                off.append(oid)
        if not off:
            return res
        note = f"인식 {k + 1}: {off} 이(가) 실물 덤프와 다른 자리 — 그 물체만 시뮬 자리로 바꿔 합침"
        diverged.append(note)
        print(f"  ** {note}")
        keep = [copy.deepcopy(o) for oid, o in objs_.items() if oid not in moved]
        keep += [copy.deepcopy(scene.objs[oid]) for oid in moved if oid in scene.objs]
        t = next((o for o in keep if o["class"] == search), None)
        return {"target_found": t is not None, "target": t, "candidates": [o for o in keep if o is not t], "visible_count": len(keep)}

    def inspect_all(node, search):
        if not b.timed("view", lambda: run(node, "view")):
            sys.exit(f"탑뷰로 못 감 {b.last['code']}")
        k = len(scans)
        res = use_dump(k, search)
        if res is not None:
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

    def scan(node, for_pick=False):                              # B clear 의 인식 (탑뷰 이동은 clear 의 look 이 먼저 함)
        k = len(scans)
        res = use_dump(k, a.target)
        if res is not None:
            if k:
                scene.reset(res)
            scans.append({"n": k + 1, "source": Path(a.dump[k]).name, "segment": len(robot.segments)})
        else:
            res = scene.scan(a.target)
            scans.append({"n": k + 1, "source": "가상", "segment": len(robot.segments)})
        print(f"  (인식 {k + 1}: {scans[-1]['source']})")
        b.print_seen(res)
        with open(b.full_scan_file(drawer), "w") as f:
            json.dump(res, f)
        if res.get("target"):
            with open(b.scan_file(), "w") as f:
                json.dump(res["target"], f)
        return bool(res.get("target_found"))

    b.run, b.inspect_all, b.scan = run, inspect_all, scan
    scene.snapshot(0, "첫 장면 (덤프 다시 계산)")
    log = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(log):
            if a.mode == "clear" or a.pre_remove:
                for step in ("ready", "open"):
                    if not run(None, step):
                        sys.exit(f"{step} {b.last['code']}")
            for oid in [x for x in a.pre_remove.split(",") if x]:   # 시작 전 치우기: 집기 → 서랍 빈 자리 (B free 와 같은 slot "free")
                res0 = scene.scan(a.target)
                obj = next(o for o in [res0["target"]] + res0["candidates"] if o and o["id"] == oid)
                if not run(None, "pick", ("pick_object", {"target": obj, "approach_offset": [0, 0, 0.1], "scan": res0})) or \
                        not run(None, "free", ("place_object", {"location": drawer, "slot": "free", "scan": res0})):
                    sys.exit(f"시작 전 치우기 {oid} 실패 {b.last['code']}")
            if a.mode == "clear":
                scans.append({"n": 0, "source": "첫 장면(시작 전 치우기 반영)", "segment": len(robot.segments)}) if a.pre_remove else None
                b.clear(None)
                ok = True
            else:
                ok = b.unpack(None)
    except SystemExit as e:
        ok, code = False, e.code
    text = log.getvalue()
    print(text)
    if code:
        print(f"*** b_sk unpack 중단: {code}")
    tsf.save_trace(robot, ROOT, a.out, results, first.get("target") or {}, None)
    d = json.loads(Path(a.out).read_text())
    d.update(scene_events=scene.events, scans=scans, diverged=diverged, log=text, stopped=str(code) if code else "", unpack_ok=bool(ok), dump=[str(x) for x in a.dump], target_class=a.target)
    Path(a.out).write_text(json.dumps(d, ensure_ascii=False))
    print(f"\nunpack {'성공' if ok else '실패/중단'} — 장면 기록 {len(scene.events)}개 → {a.out}")


if __name__ == "__main__":
    main()
