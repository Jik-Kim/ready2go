"""무동작 안전 상태 조회(W1 /skills/check_state)·B 복구(W2 /skills/recover) 판단 [#152·#271 C 계약, 제안 10/13 B] — 모름은 null."""
import pytest
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
    for bad in (-0.005, 0.5, float("nan"), float("inf")):                            # 쥔 기록 없어도 폭 이상 = 모름 [E #297 P1]
        assert view(width_m=bad, grasp_detected=False)["state"] is None, bad


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
    bad = view(safety_error=True)                                                    # RG2 안전 오류 — 쥔 기록 없어도 막음 [E #297 P1]
    assert s.recover_blockers(state(gripper=bad)) == ["SENSOR_INVALID", "GRIPPER_UNKNOWN"]
    neg = view(width_m=-0.005, grasp_detected=False)
    assert state(gripper=neg)["sensors_ok"] is False and "GRIPPER_UNKNOWN" in s.recover_blockers(state(gripper=neg))


def test_unknown_hold_decision_same_as_restart_restore():
    """[E #297 재리뷰 P1] 쥐었는지 모름 기록(21 mm)은 같은 폭이면 복원, 빈손 닫힘이면 지움, 그 밖은 불확실(None)."""
    rec = {"id": "eraser#1", "class": "eraser", "width_m": 0.021}
    d = lambda w: s.unknown_hold_decision(width_m=w, record=rec, **G)                 # noqa: E731
    assert d(0.0212) == "restore"                                                    # 같은 폭
    assert d(0.0009) == "empty"                                                      # 빈손 닫힘
    assert d(0.100) is None and d(0.030) is None                                     # 활짝 열림·다른 물체 폭
    assert d(None) is None and d(-0.005) is None and d(float("nan")) is None


def _contract():
    import json
    from pathlib import Path
    repo = Path(__file__).resolve().parents[4]
    schema = json.loads((repo / "contracts/skills_safe_state.schema.json").read_text(encoding="utf-8"))
    ex = {n: json.loads((repo / f"contracts/examples/{n}.json").read_text(encoding="utf-8")) for n in ("skills_check_state", "skills_recover")}
    return schema, ex


def test_safe_state_examples_follow_schema_and_rules():
    """contracts/examples/skills_check_state.json·skills_recover.json — 스키마(#297 계약안) 통과 + 칸 사이 규칙(response_errors).
    정상·거절·조회/서버 오류 경우가 모두 있음 [E #297 재리뷰]."""
    jsonschema = pytest.importorskip("jsonschema")
    schema, ex = _contract()
    want = {"skills_check_state": ("check_state", "check_state_error"), "skills_recover": ("recover", "recover_error")}
    for name, doc in ex.items():
        seen = set()
        for c in doc["cases"]:
            ok_def = [d for d in want[name] if not list(jsonschema.Draft202012Validator(
                {"$ref": f"#/$defs/{d}", "$defs": schema["$defs"]}).iter_errors(c["message"]))]
            assert len(ok_def) == 1, (name, c["case"])
            jsonschema.validate(c["message"], schema)
            assert s.response_errors(doc["service"], c["success"], c["message"]) == [], (name, c["case"])
            seen.add((ok_def[0], c["success"]))
        assert {d for d, _ in seen} == set(want[name]) and {ok for _, ok in seen} == {True, False}, name
    assert any(c["message"].get("code") == "HOLD_UNCERTAIN" for c in ex["skills_recover"]["cases"])


def test_response_errors_catches_broken_rules():
    """규칙이 어긋난 응답은 잡음 — 예시를 고칠 때 규칙을 깨면 시험이 실패하게."""
    _, ex = _contract()
    rec = {c["case"]: c for c in ex["skills_recover"]["cases"]}
    ok = rec["recovered_restore"]["message"]
    assert s.response_errors("/skills/recover", False, ok)                                  # success ≠ recovered
    assert s.response_errors("/skills/recover", True, dict(ok, blockers=["BUSY"]))
    assert s.response_errors("/skills/recover", True, dict(ok, state=dict(ok["state"], b_locked=True)))
    bad = rec["refused_estop"]["message"]
    assert s.response_errors("/skills/recover", False, dict(bad, code="CONTROLLER_NOT_READY"))
    assert s.response_errors("/skills/recover", False, dict(bad, cleared=["locked"]))
    err = rec["server_error"]["message"]
    assert s.response_errors("/skills/recover", False, dict(err, state=ok["state"]))
    w1 = {c["case"]: c for c in ex["skills_check_state"]["cases"]}
    assert s.response_errors("/skills/check_state", True, w1["query_error"]["message"])
    assert s.response_errors("/skills/check_state", False, w1["estop"]["message"])
