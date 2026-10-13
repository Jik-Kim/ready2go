"""무동작 안전 상태 조회(W1 /skills/check_state)·B 복구(W2 /skills/recover) 판단 [#152·#271 C 계약, 제안 10/13 B] — 모름은 null."""
from ready2go_skills.core import safe_state as s

G = {"min_width_m": 0.002, "slip_tolerance_m": 0.0015}


def view(**kw):
    base = dict(width_m=0.0009, grasp_detected=True, safety_error=False, held=None, hold_unknown=None,
                min_width_m=G["min_width_m"], slip_tolerance_m=G["slip_tolerance_m"])
    base.update(kw)
    return s.gripper_view(**base)


def test_gripper_view_empty_holding_unknown():
    assert view()["state"] == "empty"                                                 # 빈손 닫힘 0.9 mm
    assert view(width_m=0.1, grasp_detected=False)["state"] == "empty"                # 활짝 열림
    held = {"id": "eraser#1", "class": "eraser", "width_m": 0.021}
    v = view(width_m=0.0212, held=held)
    assert v["state"] == "holding" and v["held_id"] == "eraser#1"
    assert view(width_m=0.0009, held=held)["state"] == "empty"                        # 기억과 다름 — 떨어짐
    assert view(width_m=0.03, held=None)["state"] == "holding"                        # 기억 없는데 쥠 — 무엇인지 모름
    assert view(width_m=0.03, held=None)["held_id"] is None
    assert view(width_m=None, grasp_detected=None)["state"] is None                   # 못 읽음 = 모름
    assert view(safety_error=True)["state"] is None
    assert view(hold_unknown={"id": "eraser#1", "width_m": 0.021})["state"] is None   # 재시작 때 폭 못 읽음


def state(**kw):
    base = dict(robot_state=1, motion_state=1, busy=False, tool_ok=True, gripper=view(), gripper_read=True,
                locked=None, disp={"drawer_top": 0.226}, stamp="t")
    base.update(kw)
    return s.build_state(**base)


def test_build_state_fields_and_unknowns():
    st = state()
    assert st["stopped"] is True and st["estop_active"] is False and st["controller_ready"] is True
    assert st["b_locked"] is False and st["gripper"]["state"] == "empty" and st["drawers"] == {"drawer_top": 0.226}
    assert st["external_force"] is None                                               # 판정 기준 미실측 — 모름
    assert state(robot_state=None)["stopped"] is None and state(robot_state=None)["estop_active"] is None
    assert state(robot_state=None)["comm_ok"] is False
    assert state(motion_state=2)["stopped"] is False and state(busy=True)["stopped"] is False
    assert state(robot_state=6)["estop_active"] is True and state(robot_state=6)["controller_ready"] is False
    assert state(locked="pick_object: MOVE_UNCONFIRMED")["b_locked"] is True
    assert state(tool_ok=None)["tcp_tool_ok"] is None


def test_recover_blockers():
    assert s.recover_blockers(state()) == []
    assert s.recover_blockers(state(robot_state=5)) == ["ESTOP_ACTIVE", "CONTROLLER_NOT_READY"]
    assert s.recover_blockers(state(robot_state=None))[0] == "STOPPED_UNKNOWN"
    assert s.recover_blockers(state(tool_ok=False)) == ["TOOL_MISMATCH"]
    assert s.recover_blockers(state(locked="x")) == []                               # 잠금은 복구가 푸는 것 — 막지 않음
