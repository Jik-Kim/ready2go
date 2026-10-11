"""trace_skill_flow 의 단계 이름·설정 기록 (#192 E 리뷰 P2). Isaac·ROS 없이."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_skill_flow as tsf  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def test_blend_records_its_own_stage():
    """_blend(…, stage="lift") 로 보낸 moveb 구간은 앞 단계(to_drawer_top_view)가 아니라 lift 로 기록."""
    robot = tsf.KinRobot(tsf.HOME_J)
    robot.stage = "to_drawer_top_view"

    class Srv:
        def _blend(self, goal, points, radii, vel, stage):
            robot.moveb_async(points, radii, vel, vel)
    tsf.wrap_blend(Srv, robot)
    p = robot.posx()
    Srv()._blend(None, [[p[0], p[1], p[2] + 20.0] + p[3:]], [0.0], 100.0, "lift")
    assert [s["kind"] for s in robot.segments] == ["moveb"] and robot.segments[-1]["stage"] == "lift"


def test_trace_records_config_used(tmp_path):
    cfg = tsf.places_record(REPO / "config", False)
    assert cfg["assumed"] is False and len(cfg["places_sha256"]) == 64
    assert set(cfg["places"]) == set(tsf.PLACE_KEYS) and cfg["places"]["drawer_bottom"]["tf"]["translation_m"]
    robot = tsf.KinRobot(tsf.HOME_J)
    out = tmp_path / "t.json"
    tsf.save_trace(robot, REPO, out, [], {"pose": {}}, None, dict(cfg, assumed=True))
    assert json.loads(out.read_text())["config"]["assumed"] is True
