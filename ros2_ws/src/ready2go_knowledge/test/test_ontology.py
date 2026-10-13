"""ready2go_knowledge.core.ontology 단위 테스트 (ROS 불필요)."""
import os
from pathlib import Path

from ready2go_knowledge.core import ontology as onto_lib

ROOT = Path(__file__).resolve().parents[4]
ONTO = Path(os.environ.get("R2G_ONTOLOGY", ROOT / "knowledge" / "robot_ontology.jsonld"))


def _onto():
    return onto_lib.load(ONTO)


def test_list_references_are_defined():
    assert onto_lib.list_reference_errors(_onto()) == []


def test_open_drawer_pre_and_effect():
    onto = _onto()
    skill = onto["skills"]["open_drawer"]
    binding = {"drawer_id": "drawer_top"}
    results = onto_lib.check(onto["state"], skill["pre"], binding)
    assert all(r["pass"] for r in results)
    new, diff = onto_lib.apply(onto["state"], skill["effect"], binding)
    assert new["open"]["drawer_top"] is True
    assert diff == {"open.drawer_top": [False, True]}


def test_pick_blocked_when_drawer_closed():
    onto = _onto()
    results = onto_lib.check(onto["state"], onto["skills"]["pick"]["pre"], {"item": "eraser", "from": "drawer_top"})
    failed = [r for r in results if not r["pass"]]
    assert [(r["predicate"], r["subject"]) for r in failed] == [("open", "drawer_top")]


def _split_copy(tmp_path):
    """진입점의 ../config 참조까지 포함해 독립 구성 복사."""
    import shutil
    shutil.copytree(ONTO.parent, tmp_path / "knowledge")
    (tmp_path / "config").mkdir()
    shutil.copyfile(ROOT / "config/places.yaml", tmp_path / "config/places.yaml")
    shutil.copyfile(ROOT / "config/item_grasp.yaml", tmp_path / "config/item_grasp.yaml")
    return tmp_path / "knowledge/robot_ontology.jsonld"


def test_manifest_load_preserves_shape_and_rename():
    import json
    manifest = json.loads(ONTO.read_text())
    assert set(manifest) == {"@context", "sources"}
    onto = _onto()
    assert set(onto) == {"@context", "classes", "world", "state", "skills"}
    assert "fetch_with_unpack" not in onto["skills"]
    assert onto["skills"]["handover_with_unpack"]["task"] == "tasks/find_with_unpack.json"


def test_places_yaml_is_only_source_and_reload_reads_changes(tmp_path):
    import json
    import yaml
    manifest = _split_copy(tmp_path)
    raw = json.loads((manifest.parent / "world.jsonld").read_text())
    assert set(raw["world"]["places"]["drawer_top"]) == {"class", "name_ko"}
    settings = tmp_path / "config/places.yaml"
    data = yaml.safe_load(settings.read_text())
    data["drawer_top"]["max_travel_m"] = 0.13
    settings.write_text(yaml.safe_dump(data))
    place = onto_lib.load(manifest)["world"]["places"]["drawer_top"]
    assert place["max_travel_m"] == 0.13
    assert place["return_slot"] == data["drawer_top"]["return_slot"]
    assert place["tf"] == data["drawer_top"]["tf"]


def test_explicit_null_place_tf_is_preserved(tmp_path):
    import yaml
    manifest = _split_copy(tmp_path)
    settings = tmp_path / "config/places.yaml"
    data = yaml.safe_load(settings.read_text())
    data["drawer_top"]["tf"]["translation_m"] = None
    data["drawer_top"]["tf"]["quaternion_xyzw"] = None
    settings.write_text(yaml.safe_dump(data))
    place = onto_lib.load(manifest)["world"]["places"]["drawer_top"]
    assert place["tf"] == data["drawer_top"]["tf"]


def test_missing_place_settings_fails(tmp_path):
    import pytest
    import yaml
    manifest = _split_copy(tmp_path)
    settings = tmp_path / "config/places.yaml"
    data = yaml.safe_load(settings.read_text())
    del data["drawer_top"]
    settings.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="장소 설정이 없습니다: drawer_top"):
        onto_lib.load(manifest)


def test_duplicate_skill_reference_fails(tmp_path):
    import json
    import pytest
    manifest = _split_copy(tmp_path)
    data = json.loads(manifest.read_text())
    data["sources"]["skills"].append(data["sources"]["skills"][0])
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="중복 스킬 식별자"):
        onto_lib.load(manifest)


def test_world_yaml_duplicate_value_fails(tmp_path):
    import json
    import pytest
    manifest = _split_copy(tmp_path)
    world = manifest.parent / "world.jsonld"
    data = json.loads(world.read_text())
    data["world"]["places"]["drawer_top"]["max_travel_m"] = 0.25
    world.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="중복 설정"):
        onto_lib.load(manifest)


def test_unknown_item_class_fails(tmp_path):
    import json
    import pytest
    manifest = _split_copy(tmp_path)
    world = manifest.parent / "world.jsonld"
    data = json.loads(world.read_text())
    data["world"]["items"]["eraser"]["class"] = "missing_class"
    world.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="정의되지 않은 종류"):
        onto_lib.load(manifest)


def test_duplicate_yaml_and_json_keys_fail(tmp_path):
    import pytest
    manifest = _split_copy(tmp_path)
    settings = tmp_path / "config/places.yaml"
    original = settings.read_text()
    settings.write_text(original + "\ndrawer_top: {}\n")
    with pytest.raises(ValueError, match="중복 YAML 키: drawer_top"):
        onto_lib.load(manifest)
    settings.write_text(original)
    (manifest.parent / "classes.jsonld").write_text('{"classes": {}, "classes": {}}')
    with pytest.raises(ValueError, match="중복 JSON 키: classes"):
        onto_lib.load(manifest)


def test_missing_source_file_fails(tmp_path):
    import pytest
    manifest = _split_copy(tmp_path)
    (manifest.parent / "classes.jsonld").unlink()
    with pytest.raises(FileNotFoundError):
        onto_lib.load(manifest)


def test_relative_paths_ignore_cwd_and_state_is_fresh(tmp_path, monkeypatch):
    manifest = _split_copy(tmp_path)
    monkeypatch.chdir(tmp_path / "config")
    first = onto_lib.load(manifest)
    first["state"]["open"]["drawer_top"] = True
    assert onto_lib.load(manifest)["state"]["open"]["drawer_top"] is False


def test_legacy_single_file_can_still_load(tmp_path):
    import json
    path = tmp_path / "legacy.jsonld"
    data = {"world": {"items": {"eraser": {}}}, "state": {}}
    path.write_text(json.dumps(data))
    assert onto_lib.load(path) == data


def test_all_registered_items_are_request_targets_but_grasp_is_pending():
    import pytest
    onto = _onto()
    assert len(onto["world"]["items"]) == 10
    assert {"eraser", "cover_plate", "car_key"} <= onto["world"]["items"].keys()
    for name, item in onto["world"]["items"].items():
        assert "request_target" in item["roles"]
        assert item["size_m"][0] >= item["size_m"][1], name
        assert item["grip_force"] is None
        with pytest.raises(ValueError, match="파지 설정 미확정"):
            onto_lib.require_grasp_settings(onto, name)
    assert onto["world"]["items"]["cover_plate"]["size_m"][2] == 0.0405
    assert onto["world"]["items"]["eraser"]["size_m"] == [0.0525, 0.022, 0.0115]


def test_verified_grasp_configuration_must_include_force(tmp_path):
    import pytest
    import yaml
    manifest = _split_copy(tmp_path)
    path = tmp_path / "config/item_grasp.yaml"
    grasp = yaml.safe_load(path.read_text())
    grasp["eraser"]["grasp_verified"] = True
    path.write_text(yaml.safe_dump(grasp))
    with pytest.raises(ValueError, match="파지 힘이 없습니다"):
        onto_lib.load(manifest)
    grasp["eraser"]["grip_force"] = 5.0  # 테스트 전용 합성값, 실제 설정에 기록하지 않음
    path.write_text(yaml.safe_dump(grasp))
    assert onto_lib.require_grasp_settings(onto_lib.load(manifest), "eraser") == {"grip_force": 5.0}


def test_measured_grasp_widths_are_optional_and_bounded_by_size(tmp_path):
    """[B 실측 10/11] item_grasp.yaml 의 grasp_width_m·grasp_width_long_m(선택): 물품에 실리고, 0 이하·외접 변 초과·다른 키는 거부."""
    import pytest
    import yaml
    onto = _onto()
    car = onto["world"]["items"]["toy_car"]
    assert car["grasp_width_m"] == 0.0309 and car["grasp_width_long_m"] == 0.048
    assert "grasp_width_m" not in onto["world"]["items"]["eraser"]
    manifest = _split_copy(tmp_path)
    path = tmp_path / "config/item_grasp.yaml"
    original = path.read_text()
    for bad in ({"grasp_width_m": 0.0}, {"grasp_width_m": 0.03}, {"grasp_width_long_m": 0.06}, {"grasp_width_m": True}, {"width": 0.01}):
        grasp = yaml.safe_load(original)
        grasp["eraser"].update(bad)        # 지우개 size_m [0.0525, 0.022, 0.0115]
        path.write_text(yaml.safe_dump(grasp))
        with pytest.raises(ValueError):
            onto_lib.load(manifest)


def test_item_configuration_and_geometry_reference_errors(tmp_path):
    import json
    import pytest
    import yaml
    manifest = _split_copy(tmp_path)
    path = tmp_path / "config/item_grasp.yaml"
    original = path.read_text()
    grasp = yaml.safe_load(original)
    del grasp["eraser"]
    path.write_text(yaml.safe_dump(grasp))
    with pytest.raises(ValueError, match="식별자"):
        onto_lib.load(manifest)
    path.write_text(original)
    world = manifest.parent / "world.jsonld"
    data = json.loads(world.read_text())
    data["world"]["items"]["eraser"]["size_m"] = [0.022, 0, 0.0115]
    world.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="size_m"):
        onto_lib.load(manifest)


def test_p2_scene_selection_preserves_registry_and_default_state():
    expected = {
        "p2_s1": {"toy_wrench": "drawer_top", "caramel_box": "drawer_top", "car_key": "drawer_top"},
        "p2_s2": {"cover_plate": "drawer_bottom", "eraser": "drawer_bottom", "lip_balm": "drawer_bottom"},
        "p2_s3": {"cover_plate": "drawer_bottom", "lip_balm": "drawer_bottom"},
    }
    default = _onto()
    active = set(default["world"]["items"])
    assert len(active) == 10 and "carrot_pen" not in active
    assert default["state"]["located_in"] == dict.fromkeys(active, "drawer_top")
    assert "staging_tray" not in default["state"]["open"]
    assert "staging_tray" in default["world"]["places"]  # 잔존 소비자 호환 정의
    shared = {k: v for k, v in default["state"].items() if k != "located_in"}
    union = set()
    for scene, locations in expected.items():
        selected = onto_lib.load(ONTO, snapshot=f"snapshots/{scene}.json")
        assert set(selected["world"]["items"]) == active
        assert selected["state"]["located_in"] == locations
        assert {k: v for k, v in selected["state"].items() if k != "located_in"} == shared
        assert onto_lib.list_reference_errors(selected) == []
        union.update(locations)
    assert active - union == {"airpods_case", "masking_tape", "toy_car", "toy_hammer"}
    s3 = onto_lib.load(ONTO, snapshot="snapshots/p2_s3.json")
    assert "eraser" in s3["world"]["items"]
    assert onto_lib.get(s3["state"], "located_in", "eraser") is None
    s3["state"]["open"]["drawer_bottom"] = True
    assert onto_lib.load(ONTO, snapshot=ONTO.parent / "snapshots/p2_s3.json")["state"]["open"]["drawer_bottom"] is False
    assert _onto()["state"] == default["state"]


def test_selected_snapshot_validates_references(tmp_path):
    import json
    import pytest
    manifest = _split_copy(tmp_path)
    selected = manifest.parent / "snapshots/p2_s3.json"
    data = json.loads(selected.read_text())
    for item, place in [("carrot_pen", "drawer_bottom"), ("eraser", "missing_drawer")]:
        data["state"]["located_in"] = {item: place}
        selected.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="초기 위치의 물품/장소 참조가 없습니다"):
            onto_lib.load(manifest, snapshot="snapshots/p2_s3.json")


def test_selected_snapshot_rejects_duplicate_keys(tmp_path):
    import pytest
    manifest = _split_copy(tmp_path)
    selected = manifest.parent / "snapshots/p2_s3.json"
    selected.write_text('{"state":{"located_in":{"eraser":"drawer_top","eraser":"drawer_bottom"}}}')
    with pytest.raises(ValueError, match="중복 JSON 키"):
        onto_lib.load(manifest, snapshot=selected)


def test_snapshot_selection_errors_are_explicit(tmp_path):
    import json
    import pytest
    with pytest.raises(FileNotFoundError):
        onto_lib.load(ONTO, snapshot="snapshots/missing.json")
    with pytest.raises(ValueError, match="snapshot은 파일 경로"):
        onto_lib.load(ONTO, snapshot=5)
    legacy = tmp_path / "legacy.jsonld"
    data = {"world": {"items": {"eraser": {}}}, "state": {}}
    legacy.write_text(json.dumps(data))
    assert onto_lib.load(legacy) == data
    with pytest.raises(ValueError, match="sources manifest"):
        onto_lib.load(legacy, snapshot="snapshots/p2_s3.json")
