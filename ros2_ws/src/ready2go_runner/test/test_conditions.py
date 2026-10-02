import pytest

from ready2go_runner.core.conditions import BadCondition, evaluate
from ready2go_runner.core.variables import VarUndefined

BB = {
    "scan": {"target_found": False, "visible_count": 2, "candidates": [{"id": "unknown#3"}]},
    "restore_stack": [],
    "loc": {"drawer_id": "drawer_top"},
}


@pytest.mark.parametrize("op, a, b, expected", [
    ("==", "$scan.target_found", False, True), ("!=", "$loc.drawer_id", "drawer_bottom", True),
    ("<", "$scan.visible_count", 3, True), (">", "$scan.visible_count", 3, False),
    ("<=", "$scan.visible_count", 2, True), (">=", "$scan.visible_count", 3, False),
])
def test_compare(op, a, b, expected):
    assert evaluate({"op": op, "args": [a, b]}, BB) is expected


def test_logic_nested_like_find_with_unpack():
    # tasks/find_with_unpack.json s7: 목표를 못 찾았고 보이는 물체가 남아 있으면 계속
    cond = {"op": "and", "args": [
        {"op": "==", "args": ["$scan.target_found", False]},
        {"op": ">", "args": ["$scan.visible_count", 0]}]}
    assert evaluate(cond, BB) is True
    assert evaluate({"op": "not", "args": [cond]}, BB) is False
    assert evaluate({"op": "or", "args": [{"op": "==", "args": [1, 2]}, True]}, BB) is True


def test_empty_and_not_empty():
    assert evaluate({"op": "empty", "args": ["$restore_stack"]}, BB) is True
    assert evaluate({"op": "not_empty", "args": ["$scan.candidates"]}, BB) is True
    assert evaluate({"op": "empty", "args": [None]}, BB) is True


def test_short_circuit_skips_undefined_variable():
    # 앞에서 결과가 정해지면 뒤의 없는 변수($picked)는 평가하지 않음
    assert evaluate({"op": "and", "args": [False, {"op": "==", "args": ["$picked.id", 1]}]}, BB) is False
    assert evaluate({"op": "or", "args": [True, {"op": "==", "args": ["$picked.id", 1]}]}, BB) is True
    with pytest.raises(VarUndefined):
        evaluate({"op": "and", "args": [True, {"op": "==", "args": ["$picked.id", 1]}]}, BB)


@pytest.mark.parametrize("cond", [
    {"op": "==", "args": [1]},                                   # 비교인데 1개
    {"op": "and", "args": [True]},                               # and 인데 1개
    {"op": "not", "args": [True, False]},                        # not 인데 2개
    {"op": "<", "args": ["$loc.drawer_id", 3]},                  # 문자열 < 숫자
    {"op": "empty", "args": ["$scan.visible_count"]},            # 숫자는 empty 불가
    {"op": "xor", "args": [True, False]},                        # 없는 연산자
    {"args": [True]},                                            # op 없음
])
def test_bad_condition_raises(cond):
    with pytest.raises(BadCondition) as e:
        evaluate(cond, BB)
    assert e.value.code == "BAD_CONDITION"
