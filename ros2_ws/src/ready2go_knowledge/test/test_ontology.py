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
    results = onto_lib.check(onto["state"], onto["skills"]["pick"]["pre"], {"item": "watch", "from": "drawer_top"})
    failed = [r for r in results if not r["pass"]]
    assert [(r["predicate"], r["subject"]) for r in failed] == [("open", "drawer_top")]
