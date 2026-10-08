"""jog_gui '좌표로 이동' 칸 해석 (parse_goto). tkinter 가 없으면(코어 CI) 건너뜀."""
import importlib
import sys
import types

import pytest

pytest.importorskip("tkinter")


@pytest.fixture
def jg(monkeypatch):
    for name in ("rclpy", "rclpy.signals", "dsr_msgs2", "pymodbus", "pymodbus.client"):
        try:
            importlib.import_module(name)
        except ImportError:
            monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    sys.modules["pymodbus.client"].ModbusTcpClient = getattr(sys.modules["pymodbus.client"], "ModbusTcpClient", object)
    try:
        importlib.import_module("dsr_msgs2.srv")
    except ImportError:
        srv = types.ModuleType("dsr_msgs2.srv")
        for n in ("GetCurrentPosj GetCurrentPosx GetCurrentTcp GetCurrentTool GetRobotMode GetRobotState GetToolForce "
                  "Jog MoveJoint MoveLine MoveStop SetRobotMode").split():
            setattr(srv, n, type(n, (), {}))
        monkeypatch.setitem(sys.modules, "dsr_msgs2.srv", srv)
    monkeypatch.delitem(sys.modules, "ready2go_skills.nodes.jog_gui", raising=False)
    return importlib.import_module("ready2go_skills.nodes.jog_gui")


def test_posx_and_posj_text(jg):
    assert jg.parse_goto("posx([375.551, -216.972, 253.753, 151.235, -179.998, 151.235])") == \
        ("posx", [375.551, -216.972, 253.753, 151.235, -179.998, 151.235])
    assert jg.parse_goto("copy to clipboard: posj([24.487, 6.879, 97.554, -0.044, 75.569, 24.636])")[0] == "posj"


def test_numbers_only_has_no_kind(jg):
    assert jg.parse_goto("[1, 2, 3, 4, 5, 6]") == (None, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert jg.parse_goto("1 2 3 4 5 -6.5e1")[1][-1] == -65.0


@pytest.mark.parametrize("text", ["", "posx([1, 2, 3])", "posj([1, 2, 3, 4, 5, 6, 7])", "abc"])
def test_not_six_numbers(jg, text):
    assert jg.parse_goto(text) == (None, None)
