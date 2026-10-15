import json
from pathlib import Path
import pytest
from ready2go_knowledge.core import refusal_reasons as reasons


def test_catalog_preserves_b_ids_strategy_and_evidence():
    catalog = reasons.load()
    assert len(catalog) == 9
    assert catalog['cluster_front_wall']['status'] == 'verified_real'
    assert catalog['cylinder_handle_wall']['status'] == 'sim_only'
    for key, case in catalog.items():
        assert case['strategy'] == 'impossible'
        assert isinstance(case['evidence'], dict)
        assert reasons.text(key, 'impossible') == case['text_ko']
        if key != 'no_free_space':
            assert '수 있어요' in case['text_ko']


@pytest.mark.parametrize('case_id,strategy', [(None, 'impossible'), ('unknown', 'impossible'),
    ('standing', None), ('standing', 'direct'), ('standing', 'reobserve'), ([], 'impossible')])
def test_unknown_or_non_refusal_has_no_layout_explanation(case_id, strategy):
    assert reasons.text(case_id, strategy) is None


def test_installed_share_lookup(monkeypatch, tmp_path):
    import sys
    from types import ModuleType
    doc = reasons._document()
    share = tmp_path / 'share'
    (share / 'knowledge').mkdir(parents=True)
    (share / 'knowledge/refusal_reasons.json').write_text(json.dumps(doc))
    packages = ModuleType('ament_index_python.packages')
    packages.get_package_share_directory = lambda name: str(share)
    monkeypatch.setitem(sys.modules, 'ament_index_python.packages', packages)
    monkeypatch.setattr(reasons, '__file__', str(tmp_path / 'a/b/c/d/e/refusal_reasons.py'))
    assert len(reasons.load()) == 9
    assert reasons.unknown_text() in reasons.texts()


def test_duplicate_catalog_rejected(tmp_path):
    doc = reasons._document()
    doc['cases'].append(doc['cases'][0])
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        reasons.load(path)


@pytest.mark.parametrize('case_id', ['no_free_space', 'beyond_reach', 'cluster_front_wall',
    'cylinder_handle_wall', 'handle_wall_wide', 'chain_blocker_plate_pinned'])
def test_actual_b_impossible_return_ids_have_explanations(case_id):
    assert reasons.text(case_id, 'impossible')


def test_beyond_reach_keeps_source_strategy_and_rejects_nudge():
    case = reasons.load()['beyond_reach']
    assert case['source_strategy'] == 'nudge'
    assert case['source_then'] == 'impossible'
    assert reasons.text('beyond_reach', 'nudge') is None
    assert reasons.text('unknown', 'impossible') is None
