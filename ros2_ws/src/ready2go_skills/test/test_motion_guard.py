from pathlib import Path

import pytest
import yaml

from ready2go_skills.core import motion_guard as mg
from ready2go_skills.core import nudge_plan

ROOT = Path(__file__).resolve().parents[4]
PARAMS = yaml.safe_load((ROOT / "ros2_ws/src/ready2go_skills/params/skills.yaml").read_text(encoding="utf-8"))["motion_guard"]
TF_AT = yaml.safe_load((ROOT / "config/places.yaml").read_text(encoding="utf-8"))["drawer_top"]["tf_at_travel_m"]

ERASER_H = 0.0115     # #8 실측 높이 (온톨로지 size_m[2])
TARGET = {"id": "eraser#1", "class": "eraser",
          "pose": {"frame": "drawer_top", "position": [0.10, 0.15, 0.0], "yaw": 0.52, "yaw_valid": True},
          "top_z": 0.0115}


def _pose(**kw):
    return {**TARGET, "pose": {**TARGET["pose"], **kw}}


# ---- TOOL_NOT_SET (결정 #28: 맞음 / TCP 다름 / 툴 다름 / 서비스 실패)
def test_expected_tool_comes_from_calibration_meta():
    meta = yaml.safe_load((ROOT / "config/calibration/calibration_meta.yaml").read_text(encoding="utf-8"))
    assert mg.expected_tool(meta) == ("GripperDA_v1", "tool_weight")


@pytest.mark.parametrize("tcp,tool,ok", [
    ("GripperDA_v1", "tool_weight", True),
    ("", "tool_weight", False),               # TCP 풀림 (#6 3점 터치 사고)
    ("GripperDA_V1", "tool_weight", False),   # 대소문자 다름
    ("GripperDA_v1", "", False),              # 툴 풀림
    (None, "tool_weight", False),             # 서비스 실패
    ("GripperDA_v1", None, False),
])
def test_check_tool(tcp, tool, ok):
    err = mg.check_tool(tcp, tool, "GripperDA_v1", "tool_weight")
    assert (err is None) == ok
    if not ok:
        assert err.error_code == mg.TOOL_NOT_SET


# ---- DRAWER_NOT_AT_TRAVEL (정상 / 덜 열림 / 값 없음)
def test_travel_at_max_is_ok():
    assert mg.check_travel(TF_AT, TF_AT, PARAMS["travel_tolerance_m"]) is None


def test_travel_short_is_rejected():
    err = mg.check_travel(0.200, TF_AT, PARAMS["travel_tolerance_m"])    # 레일에 걸려 20 cm (#15 PM 예)
    assert err.error_code == mg.DRAWER_NOT_AT_TRAVEL


def test_travel_missing_is_rejected():
    assert mg.check_travel(None, TF_AT, PARAMS["travel_tolerance_m"]).error_code == mg.DRAWER_NOT_AT_TRAVEL


# ---- YAW_INVALID: pose 를 그대로 받아 기본값을 넣지 않음 (#66 PM 후속 3)
@pytest.mark.parametrize("pose_kw", [{"yaw_valid": False, "yaw": 0.0}, {"yaw_valid": 1}, {"yaw_valid": "true"}])
def test_untrusted_yaw_is_rejected(pose_kw):
    assert mg.check_yaw(_pose(**pose_kw)).error_code == mg.YAW_INVALID


def test_missing_yaw_valid_is_rejected():
    pose = {k: v for k, v in TARGET["pose"].items() if k != "yaw_valid"}
    assert mg.check_yaw({**TARGET, "pose": pose}).error_code == mg.YAW_INVALID
    assert mg.check_yaw({**TARGET, "pose": None}).error_code == mg.YAW_INVALID


def test_valid_yaw_including_zero_passes():
    assert mg.check_yaw(TARGET) is None
    assert mg.check_yaw(_pose(yaw=0.0)) is None


def test_yaw_code_is_shared_with_nudge():
    assert nudge_plan.YAW_INVALID == mg.YAW_INVALID == "YAW_INVALID"


# ---- NOT_ON_FLOOR
def test_object_on_floor_passes():
    assert mg.check_on_floor(TARGET, ERASER_H, PARAMS["on_floor_tolerance_m"]) is None


def test_object_on_another_object_is_rejected():
    stacked = {**TARGET, "top_z": ERASER_H + 0.0158}                       # 차키 위에 얹힌 지우개
    assert mg.check_on_floor(stacked, ERASER_H, PARAMS["on_floor_tolerance_m"]).error_code == mg.NOT_ON_FLOOR


@pytest.mark.parametrize("top_z", [None, "0.01", True])
def test_missing_or_bad_top_z_is_rejected(top_z):
    assert mg.check_on_floor({**TARGET, "top_z": top_z}, ERASER_H, 0.01).error_code == mg.NOT_ON_FLOOR


# ---- 묶음: 순서 (인출 거리 → yaw → 바닥 위)
def _pick(target=TARGET, displacement=TF_AT):
    return mg.precheck_pick(target=target, height_m=ERASER_H, displacement_m=displacement,
                            tf_at_travel_m=TF_AT, params=PARAMS)


def test_precheck_pick_ok():
    assert _pick() is None


def test_precheck_pick_order():
    bad_all = {**_pose(yaw_valid=False, yaw=0.0), "top_z": 0.05}
    assert _pick(bad_all, displacement=0.10).error_code == mg.DRAWER_NOT_AT_TRAVEL
    assert _pick(bad_all).error_code == mg.YAW_INVALID
    assert _pick({**TARGET, "top_z": 0.05}).error_code == mg.NOT_ON_FLOOR


def test_precheck_nudge_skips_floor_check():
    on_top = {**TARGET, "top_z": 0.05}                                     # 밀기 판단은 top_z 를 보지 않음
    assert mg.precheck_nudge(target=on_top, displacement_m=TF_AT, tf_at_travel_m=TF_AT, params=PARAMS) is None
    assert mg.precheck_nudge(target=_pose(yaw_valid=False, yaw=0.0), displacement_m=TF_AT,
                             tf_at_travel_m=TF_AT, params=PARAMS).error_code == mg.YAW_INVALID


# ---- 비유한 수치는 통과시키지 않음 (#70 D 리뷰: NaN 비교가 항상 False라 fail-open)
NAN, INF = float("nan"), float("inf")


@pytest.mark.parametrize("disp,ref,tol", [(NAN, TF_AT, 0.005), (INF, TF_AT, 0.005), (-INF, TF_AT, 0.005),
                                          (TF_AT, NAN, 0.005), (TF_AT, TF_AT, NAN), (TF_AT, TF_AT, INF),
                                          (True, TF_AT, 0.005), ("0.226", TF_AT, 0.005)])
def test_non_finite_travel_is_rejected(disp, ref, tol):
    assert mg.check_travel(disp, ref, tol).error_code == mg.DRAWER_NOT_AT_TRAVEL


@pytest.mark.parametrize("top_z,height,tol", [(NAN, ERASER_H, 0.01), (INF, ERASER_H, 0.01), (-INF, ERASER_H, 0.01),
                                              (0.0115, NAN, 0.01), (0.0115, ERASER_H, NAN), (0.0115, ERASER_H, INF),
                                              (-0.05, ERASER_H, 0.01)])          # 바닥 아래 top_z
def test_non_finite_or_below_floor_top_z_is_rejected(top_z, height, tol):
    assert mg.check_on_floor({**TARGET, "top_z": top_z}, height, tol).error_code == mg.NOT_ON_FLOOR


def test_precheck_pick_rejects_nan_everywhere():
    assert _pick(displacement=NAN).error_code == mg.DRAWER_NOT_AT_TRAVEL
    assert _pick({**TARGET, "top_z": NAN}).error_code == mg.NOT_ON_FLOOR


# ---- 쌓인 물체 집기 [사용자 10/09, P2 3개 겹침]
@pytest.mark.parametrize("top_z,ok", [
    (0.0115, True),                  # 바닥
    (0.0115 + 0.0435, True),         # 망치 25 + 캐러멜 18.5 위 지우개 — 윗면 55 mm
    (0.0611, True),                  # 상한과 같음
    (0.0612, False),                 # 테두리(71.1) − 10 mm 넘음
    (-0.02, False),                  # 바닥 아래 = 측정 오류
])
def test_stacked_pick_allowed_below_cap(top_z, ok):
    err = mg.precheck_pick(target={**TARGET, "top_z": top_z}, height_m=ERASER_H, displacement_m=TF_AT,
                           tf_at_travel_m=TF_AT, params=PARAMS, max_top_m=0.0611)
    assert (err is None) == ok
    if not ok:
        assert err.error_code == mg.NOT_ON_FLOOR


def test_stacked_refused_without_cap_like_p1():
    err = mg.precheck_pick(target={**TARGET, "top_z": 0.055}, height_m=ERASER_H, displacement_m=TF_AT,
                           tf_at_travel_m=TF_AT, params=PARAMS)
    assert err.error_code == mg.NOT_ON_FLOOR


@pytest.mark.parametrize("top_z,support", [(0.0115, 0.0), (0.0125, 0.0), (0.055, 0.0435)])
def test_support_height(top_z, support):
    assert mg.support_m({**TARGET, "top_z": top_z}, ERASER_H, 0.01) == pytest.approx(support)
