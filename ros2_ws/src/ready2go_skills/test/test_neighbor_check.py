"""core/neighbor_check.py — 집기·끌기 전 옆 물체 확인 [사용자 10/09 서랍 안 랜덤 배치]."""
import math

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


def test_objects_under_the_target_are_ignored():
    """[P2 시뮬레이션 10/10] 가림막(98.5 × 74.2, 높이 40.5) 밑의 지우개·립밤은 손가락 자리 이웃이 아님 — 손가락은 판 둘레로 내려감.
    판 밖으로 삐져나오거나 판보다 높으면 그대로 막음."""
    SIZES["cover_plate"] = [0.0985, 0.0742, 0.0405]
    plate = _obj("cover_plate#1", "cover_plate", 0.110, 0.200, 0.0405)
    under = _obj("eraser#1", "eraser", 0.095, 0.185, 0.0115)
    common = dict(target=plate, size_m=SIZES["cover_plate"], open_mm=87.2, size_of=SIZES.get, default_size_m=[0.06, 0.06, 0.06],
                  finger_mm=13.0, margin_mm=5.0, support_m=0.0, below_tol_m=0.003)
    assert nc.pick_blocker(objects=[plate, under], **common) is None
    out = _obj("eraser#1", "eraser", 0.110, 0.250, 0.0115)                  # 판 옆으로 삐져나옴
    assert nc.pick_blocker(objects=[plate, out], **common) == "eraser#1"


def test_finger_band_only_for_long_object():
    """[P2 시뮬레이션 10/10] 몽키(170 mm) 끝 옆 차키는 손가락(가운데)에 안 닿음 — finger_half_width_mm 를 주면 손가락 띠만 봄."""
    SIZES["toy_wrench"], SIZES["car_key"] = [0.17, 0.061, 0.0185], [0.0695, 0.039, 0.0158]
    wrench = _obj("toy_wrench#1", "toy_wrench", 0.105, 0.150, 0.0185)
    key = _obj("car_key#1", "car_key", 0.035, 0.085, 0.0158, yaw=1.5708)
    common = dict(target=wrench, size_m=SIZES["toy_wrench"], open_mm=74.0, objects=[wrench, key], size_of=SIZES.get,
                  default_size_m=[0.06, 0.06, 0.06], finger_mm=13.0, margin_mm=5.0, support_m=0.0, below_tol_m=0.003)
    assert nc.pick_blocker(**common) == "car_key#1"                          # 예전: 물체 길이 전체
    assert nc.pick_blocker(finger_half_width_mm=15.8, **common) is None


def test_passes_under_uses_leg_gap_by_direction_and_narrow_part():
    """판 밑(occluded_by 판) 물체가 다리 안쪽 [긴 변 방향 65, 짧은 변 방향 35] 사이로 지나가는 폭인지 [사용자 10/13]."""
    plate = {"id": "cover_plate#1", "pose": {"position": [0.1, 0.2, 0.0], "yaw": 0.0, "yaw_valid": True}}
    def o(yaw, valid=True, top=0.019, occ=("cover_plate#1",)):
        return {"id": "w", "class": "toy_wrench", "top_z": top, "occluded_by": list(occ),
                "pose": {"position": [0.1, 0.2, 0.0], "yaw": yaw, "yaw_valid": valid}}
    W = [0.170, 0.061, 0.0185]
    gap = [65.0, 35.0]
    assert nc._passes_under(o(math.pi / 2), plate, W, 0.021, 0.005, gap)            # 판 짧은 변 쪽으로 가로지름: 61 ≤ 65
    assert not nc._passes_under(o(0.0), plate, W, 0.021, 0.005, gap)                # 판 긴 변과 나란: 61 > 35
    assert nc._passes_under(o(0.0), plate, W, 0.021, 0.005, gap, width_of=lambda c: 0.0259)   # 손잡이 25.9 ≤ 35
    assert nc._passes_under(o(0.0, valid=False), plate, W, 0.021, 0.005, gap)       # 방향 모름: 큰 쪽(65)
    assert not nc._passes_under(o(math.pi / 2, occ=()), plate, W, 0.021, 0.005, gap)   # 관계 없음
    assert not nc._passes_under(o(math.pi / 2, top=0.03), plate, W, 0.021, 0.005, gap)  # 21·18.5 + 5 넘음 (판 위 등)
    assert not nc._passes_under(o(math.pi / 2), plate, W, 0.021, 0.005, None)      # 간격 설정 없으면 예전 그대로
