"""core/neighbor_check.py — 집기·끌기 전 옆 물체 확인 [사용자 10/09 서랍 안 랜덤 배치]."""
import pytest

from ready2go_skills.core import neighbor_check as nc

SIZES = {"eraser": [0.0525, 0.022, 0.0115], "caramel_box": [0.075, 0.049, 0.0185], "toy_hammer": [0.18, 0.075, 0.025]}
ERASER = {"id": "eraser#1", "class": "eraser", "top_z": 0.0115,
          "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.3, "yaw_valid": True}}


def _obj(id_, cls, x, y, top_z, yaw=0.0, yaw_valid=True):
    return {"id": id_, "class": cls, "top_z": top_z,
            "pose": {"frame": "drawer_top", "position": [x, y, 0.0], "yaw": yaw, "yaw_valid": yaw_valid}}


def _pick(objects, support=0.0, target=ERASER):
    return nc.pick_blocker(target=target, size_m=SIZES[target["class"]], open_mm=35.0, objects=objects,
                           size_of=SIZES.get, default_size_m=[0.10, 0.10], finger_mm=13.0, margin_mm=5.0,
                           support_m=support, below_tol_m=0.003)


@pytest.mark.parametrize("dy, blocked", [(0.06, True), (0.09, False)])
def test_pick_blocked_by_close_caramel_only(dy, blocked):
    cara = _obj("caramel_box#1", "caramel_box", 0.10, 0.15 + dy, 0.0185)
    assert _pick([ERASER, cara]) == ("caramel_box#1" if blocked else None)     # 자기 자신(같은 id)은 무시


def test_support_below_is_ignored_for_stacked_pick():
    """지우개가 캐러멜(윗면 43.5 mm) 위 — 받침인 캐러멜·망치는 손가락보다 아래."""
    top = {**ERASER, "top_z": 0.055}
    under = [_obj("caramel_box#1", "caramel_box", 0.10, 0.15, 0.0435), _obj("toy_hammer#1", "toy_hammer", 0.10, 0.15, 0.025)]
    assert _pick([top] + under, support=0.0435, target=top) is None


def test_unknown_top_z_or_class_blocks_conservatively():
    o = _obj("thing#1", "unknown", 0.10, 0.20, None)
    assert _pick([ERASER, o]) == "thing#1"


@pytest.mark.parametrize("ny, blocked", [(0.20, True), (0.10, False), (0.30, False)])
def test_drag_blocked_only_by_object_ahead_on_path(ny, blocked):
    """+y 로 40 mm 끌 때: 앞(y 0.20)은 막음, 뒤(y 0.10)는 멀어짐, 멀리(0.30)는 안 닿음."""
    t = {**ERASER, "pose": {**ERASER["pose"], "yaw": 0.0}}
    o = _obj("caramel_box#1", "caramel_box", 0.10, ny, 0.0185)
    who = nc.drag_blocker(target=t, size_m=SIZES["eraser"], shift_y_m=0.040, objects=[t, o], size_of=SIZES.get,
                          default_size_m=[0.10, 0.10], margin_mm=5.0, support_m=0.0, below_tol_m=0.003)
    assert who == ("caramel_box#1" if blocked else None)


def test_bad_input_refused():
    bad = {**ERASER, "pose": {**ERASER["pose"], "position": [float("nan"), 0.15, 0.0]}}
    with pytest.raises(ValueError):
        _pick([], target=bad)
