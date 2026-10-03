import pytest

from ready2go_runner.core.variables import (BadFilter, VarUndefined, attach_particle, get_path,
                                            interpolate, resolve)

BB = {
    "inputs": {"target": "watch"},
    "loc": {"name_ko": "시계", "drawer_id": "drawer_top"},
    "list": {"items_ko": ["차키", "지갑", "시계"], "name_ko": "출근 준비물"},
    "scan": {
        "target_found": True,
        "target": {"id": "watch#1", "top_z": 0.04},
        "candidates": [{"id": "unknown#3"}, {"id": "wallet#1"}],
        "visible_count": 3,
    },
}


def test_get_path_nested_and_index():
    assert get_path(BB, "inputs.target") == "watch"
    assert get_path(BB, "scan.target.id") == "watch#1"
    assert get_path(BB, "scan.candidates[1].id") == "wallet#1"


def test_resolve_keeps_original_type():
    assert resolve("$scan.target_found", BB) is True
    assert resolve("$scan.visible_count", BB) == 3
    assert resolve("$scan.target", BB) == {"id": "watch#1", "top_z": 0.04}


def test_resolve_params_recursively():
    params = {"object_id": "$scan.target.id", "approach_offset": [0, 0, 0.1],
              "value": {"origin": "$scan.target.top_z", "ids": ["$scan.candidates[0].id"]}}
    assert resolve(params, BB) == {"object_id": "watch#1", "approach_offset": [0, 0, 0.1],
                                   "value": {"origin": 0.04, "ids": ["unknown#3"]}}


def test_resolve_leaves_plain_values():
    assert resolve("home", BB) == "home"
    assert resolve(0.1, BB) == 0.1
    assert resolve(None, BB) is None


def test_interpolate_sentence():
    assert interpolate("{{loc.name_ko}} 찾기를 시작합니다", BB) == "시계 찾기를 시작합니다"
    assert interpolate("{{ loc.name_ko }}는 {{loc.drawer_id}}에, 후보 {{scan.visible_count}}개", BB) \
        == "시계는 drawer_top에, 후보 3개"
    assert interpolate("변수 없는 문장", BB) == "변수 없는 문장"


def test_resolve_interpolates_strings_in_params():
    params = {"text": "{{loc.name_ko}} 찾기를 시작합니다", "pose_name": "home"}
    assert resolve(params, BB) == {"text": "시계 찾기를 시작합니다", "pose_name": "home"}


def test_interpolate_undefined_raises():
    with pytest.raises(VarUndefined):
        interpolate("{{loc.name_en}} 찾기", BB)


@pytest.mark.parametrize("word, particle, expected", [
    ("시계", "을", "시계를"), ("지갑", "을", "지갑을"), ("지갑", "를", "지갑을"),
    ("시계", "이", "시계가"), ("지갑", "가", "지갑이"),
    ("시계", "은", "시계는"), ("지갑", "는", "지갑은"),
    ("시계", "과", "시계와"), ("지갑", "와", "지갑과"),
    ("서랍", "으로", "서랍으로"), ("트레이", "으로", "트레이로"), ("연필", "으로", "연필로"),
    ("연필", "을", "연필을"),                                  # ㄹ 받침이라도 "으로" 외에는 받침 있음 규칙
    ("RG2", "을", "RG2를"), ("TV", "이", "TV가"),               # 영문·숫자로 끝나면 받침 없음
])
def test_attach_particle(word, particle, expected):
    assert attach_particle(word, particle) == expected


def test_interpolate_with_particle_filter():
    assert interpolate("{{loc.name_ko|을}} 찾았습니다", BB) == "시계를 찾았습니다"
    assert interpolate("서랍장에서 {{ loc.name_ko | 을 }} 찾지 못했습니다", BB) == "서랍장에서 시계를 찾지 못했습니다"
    assert interpolate("{{list.name_ko}} {{list.items_ko|목록|을}} 찾겠습니다", BB) \
        == "출근 준비물 차키, 지갑, 시계를 찾겠습니다"
    assert interpolate("{{list.items_ko|목록}}", BB) == "차키, 지갑, 시계"


@pytest.mark.parametrize("text", ["{{loc.name_ko|에게}}", "{{loc.name_ko|목록}}"])
def test_bad_filter_raises(text):
    with pytest.raises(BadFilter) as e:
        interpolate(text, BB)
    assert e.value.code == "BAD_FILTER"


@pytest.mark.parametrize("path", ["$loc.name_en", "$scan.target.pose", "$scan.candidates[5].id",
                                  "$scan.visible_count.x", "$scan..id", "$"])
def test_undefined_variable_raises(path):
    with pytest.raises(VarUndefined) as e:
        resolve(path, BB)
    assert e.value.code == "VAR_UNDEFINED"
