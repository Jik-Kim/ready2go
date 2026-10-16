"""표시명은 원본의 정확한 단계/expand ID에만 부여하며 실행 여부는 만들지 않는다."""
import json
from pathlib import Path

from ready2go_knowledge.core.ontology import load
from ready2go_web.core.step_labels import task_step_labels


def test_real_task_expanded_place_label():
    root = Path(__file__).resolve().parents[2]
    task = json.loads((root / "tasks/find_with_unpack.json").read_text())
    skills = load(root / "knowledge/robot_ontology.jsonld")["skills"]
    labels = task_step_labels(task, skills)
    assert labels["s8.t2.e1"] == "전달 트레이에 물품 놓기"
    assert "s8.t2.e999" not in labels


def test_nested_expand_and_check_only_are_not_delivery():
    # 모의 정의로 각 분기 ID 규칙과 미지원 동작의 보수적 처리를 확인한다.
    skills = {"test": {"name_ko": "시험", "expand": [
        {"action": "if", "then": [{"action": "fallback", "options": [[
            {"action": "place_object", "params": {"check_only": True}}]]}],
         "else": [{"action": "unknown"}]}]}}
    labels = task_step_labels({"sequence": [{"id": "s1", "skill": "test"}]}, skills)
    assert labels["s1.e1.t1.o1.1"] == "물품 배치 공간 확인"
    assert "s1.e1.f1" not in labels



def test_extra_labels_and_safe_home_require_declared_policy():
    """반복/선택과 선언된 실패 복귀만 이름을 만들며 임의 복귀 ID를 만들지 않는다."""
    labels = task_step_labels({"sequence": [
        {"id": "s6", "action": "select_obstacle"},
        {"id": "fa", "action": "for_each", "body": [
            {"id": "fa.1", "action": "speak", "on_failure": "safe_home"}]},
        {"id": "plain", "action": "speak"}], "finally": []}, {})
    assert labels["s6"] == "치울 물체 고르기"
    assert labels["fa"] == "반복 처리"
    assert labels["fa.1.safe_home"] == "기본 자세로 이동"
    assert "plain.safe_home" not in labels
