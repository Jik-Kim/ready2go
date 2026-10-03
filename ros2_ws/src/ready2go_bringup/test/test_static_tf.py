from pathlib import Path

import pytest
import yaml

from ready2go_bringup.static_tf import StaticTfError, load_static_tfs, parse_tf

REPO_CONFIG = Path(__file__).resolve().parents[4] / "config"
CAMERA_TF = {"parent": "link_6", "child": "wrist_cam_link",
             "translation_m": [0.01875, 0.07650, 0.02641],
             "quaternion_xyzw": [-0.50615, -0.49852, -0.5008, 0.49446]}


def write_config(tmp_path, derived_tf=CAMERA_TF, places=None):
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration/calibration_meta.yaml").write_text(
        yaml.safe_dump({"derived_tf": derived_tf}), encoding="utf-8")
    if places is not None:
        (tmp_path / "places.yaml").write_text(yaml.safe_dump(places), encoding="utf-8")
    return tmp_path


def test_repo_config_publishes_wrist_camera():
    # 저장소의 실제 config: 손목 카메라 derived_tf(A) 는 발행, places.yaml 은 아직 tf 블록 전
    tfs, skipped = load_static_tfs(REPO_CONFIG)
    camera = [tf for tf in tfs if tf.child == "wrist_cam_link"]
    assert len(camera) == 1 and camera[0].parent == "link_6"           # 접두어 없음 (B 실측, 이슈 #3)
    assert any("places.yaml" in reason for reason in skipped)


def test_places_with_tf_block_are_published(tmp_path):
    places = {
        "drawer_top": {"max_travel_m": 0.17, "tf": {"parent": "base_link", "child": "drawer_top",
                                                    "translation_m": [0.5, 0.0, 0.1],
                                                    "quaternion_xyzw": [0, 0, 0, 1]}},
        "staging_tray": {"origin": None, "rpy": None, "slots": 3},     # 측정 전 (기존 형식)
    }
    tfs, skipped = load_static_tfs(write_config(tmp_path, places=places))
    assert [(tf.parent, tf.child) for tf in tfs] == [("link_6", "wrist_cam_link"), ("base_link", "drawer_top")]
    assert skipped == ["places.yaml:staging_tray: tf 블록 없음 (측정 전, 이슈 #6)"]


def test_places_with_null_tf_values_are_skipped(tmp_path):
    # main 의 places.yaml 형식 (PR #28): tf 블록은 있으나 측정 전이라 값이 null
    places = {"drawer_top": {"tf": {"parent": "base_link", "child": "drawer_top",
                                    "translation_m": None, "quaternion_xyzw": None}, "max_travel_m": 0.17}}
    tfs, skipped = load_static_tfs(write_config(tmp_path, places=places))
    assert [tf.child for tf in tfs] == ["wrist_cam_link"]                 # launch 는 멈추지 않음
    assert skipped == ["places.yaml:drawer_top: tf 값 null (측정 전, #6)"]


def test_partially_filled_tf_raises(tmp_path):
    places = {"drawer_top": {"tf": {"parent": "base_link", "child": "drawer_top",
                                    "translation_m": [0.5, 0.0, 0.1], "quaternion_xyzw": None}}}
    with pytest.raises(StaticTfError) as e:
        load_static_tfs(write_config(tmp_path, places=places))
    assert "quaternion_xyzw" in str(e.value)


def test_missing_files_are_skipped(tmp_path):
    tfs, skipped = load_static_tfs(tmp_path)
    assert tfs == []
    assert any("파일 없음" in reason for reason in skipped)


@pytest.mark.parametrize("change, expected", [
    ({"parent": ""}, "parent"),
    ({"translation_m": [0.1, 0.2]}, "translation_m"),
    ({"translation_m": None}, "translation_m"),                         # 측정값 null 이 섞인 블록
    ({"quaternion_xyzw": [0, 0, 0, 2]}, "단위 쿼터니언"),
    ({"quaternion_xyzw": [0, 0, True, 1]}, "quaternion_xyzw"),
])
def test_invalid_block_raises(change, expected):
    with pytest.raises(StaticTfError) as e:
        parse_tf({**CAMERA_TF, **change}, "test")
    assert expected in str(e.value)


def test_duplicate_child_raises(tmp_path):
    places = {"camera_again": {"tf": {**CAMERA_TF}}}                    # 같은 child 를 두 곳에서 발행
    with pytest.raises(StaticTfError) as e:
        load_static_tfs(write_config(tmp_path, places=places))
    assert "wrist_cam_link" in str(e.value)


@pytest.mark.parametrize("field, text", [
    ("translation_m", "[.nan, 0.0, 0.0]"),
    ("translation_m", "[.inf, 0.0, 0.0]"),
    ("translation_m", "[0.0, -.inf, 0.0]"),
    ("quaternion_xyzw", "[.nan, 0.0, 0.0, 1.0]"),        # 크기가 NaN 이면 단위 쿼터니언 검사도 못 잡음
])
def test_non_finite_values_raise(field, text):
    # PR #40 리뷰(D): tf2 BufferCore 는 NaN transform 을 TF_NAN_INPUT 으로 버려, bringup 은 정상처럼 떠도 TF 가 사라짐
    with pytest.raises(StaticTfError) as e:
        parse_tf({**CAMERA_TF, field: yaml.safe_load(text)}, "test")
    assert "NaN·무한대" in str(e.value)


def test_non_finite_in_calibration_file_stops_launch(tmp_path):
    (tmp_path / "calibration").mkdir()
    (tmp_path / "calibration/calibration_meta.yaml").write_text(
        "derived_tf: {parent: link_6, child: wrist_cam_link, translation_m: [.nan, 0.0, 0.0], "
        "quaternion_xyzw: [0.0, 0.0, 0.0, 1.0]}\n", encoding="utf-8")
    with pytest.raises(StaticTfError):
        load_static_tfs(tmp_path)
