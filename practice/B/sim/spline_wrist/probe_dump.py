"""스킬 노드가 carry.spline 에서 movesx 로 보내는 점 모으기 (실제 _do_place_object, 가짜 로봇).

direct 끔·켬 × spline_via 8·20 × 손목 회전 0/45/90/170° × 트레이 1·2칸 = 32 경우 (2칸 8 via 만 분석 = 20 줄 출력 중 일부).
돌리는 법 (conftest 때문에 테스트 폴더에서):
  cp practice/B/sim/spline_wrist/probe_dump.py ros2_ws/src/ready2go_skills/test/test_zz_probe.py
  SPLINE_PROBE_OUT=practice/B/sim/spline_wrist/probe_after.json python3 -m pytest ros2_ws/src -q -k test_probe
  rm ros2_ws/src/ready2go_skills/test/test_zz_probe.py
고치기 전 = #365 수정 전 커밋(75127fe 이전 spline 처리)에서, 고친 뒤 = 지금 코드에서 돌린 결과.
"""
import json, itertools, os, pathlib
from test_skill_server_node import *  # noqa: F401,F403  (fixtures)
from test_skill_server_node import _with_prm, LIP_HELD

OUT = pathlib.Path(os.environ.get("SPLINE_PROBE_OUT", "spline_probe.json"))


def test_probe(server, monkeypatch):
    res = []
    for direct, nvia, dturn, nslot in itertools.product((False, True), (8, 20), (0.0, 45.0, 90.0, 170.0), (1, 2)):
        _with_prm(server, monkeypatch, carry={"spline": True, "direct": direct, "spline_via": nvia})
        srv = server.srv
        route = srv.poses()["carry_line"]["drawer_top"]
        cap = {}

        def movesx(pts, vel, acc, rot_vel=30.0, rot_acc=60.0, const_vel=True):
            cap["via"] = [list(p) for p in pts]
            cap["start"] = list(srv.robot.p)
            srv.robot.p = list(pts[-1])
            return True
        srv.robot.movesx_async = movesx
        srv.tray = {}
        for k in range(nslot):
            srv.held = dict(LIP_HELD)
            server.Gripper.holding, server.Gripper.width = True, 19.5
            p = list(route[0]); p[5] += dturn
            srv.robot.p = p
            srv.robot.j = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
            cap.clear()
            out, data = server.run("place_object", {"location": "handover_zone"})
            server.Gripper.holding = False
        res.append({"direct": direct, "nvia": nvia, "dturn": dturn, "slot": nslot, "ok": out.success, "reason": out.reason,
                    "start": cap.get("start"), "via": cap.get("via"), "route": route})
    OUT.write_text(json.dumps(res))
