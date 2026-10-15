"""#302 E 계획 필드와 현재 C 소비 경계. 장치/ROS 운영은 실행하지 않습니다."""
import copy
import json
from pathlib import Path

import pytest
from ready2go_knowledge.core import ontology
from test_ontology import _split_copy

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / 'knowledge/robot_ontology.jsonld'


def test_split_and_legacy_plan_field_preserve_real_sensing_effect(tmp_path):
    onto = ontology.load(SOURCE)
    before = copy.deepcopy(onto['state'])
    skill = onto['skills']['handover_with_unpack']
    assert skill['kind'] == 'composite' and skill['effect'] == 'sensing'
    assert skill['task'] == 'tasks/find_with_unpack.json'
    assert skill['params'] == {'target':'Item', 'from':'Drawer'}
    assert skill['plan_effect'] == [{'subject':'$target', 'predicate':'located_in', 'value':'handover_zone'}]
    path = tmp_path/'legacy.jsonld';path.write_text(json.dumps(onto))
    assert ontology.load(path) == onto
    assert onto['state'] == before and before['located_in']['eraser'] == 'drawer_bottom'
    # 이전 형식에는 계획 필드가 필수가 아닙니다.
    del onto['skills']['handover_with_unpack']['plan_effect']
    path.write_text(json.dumps(onto));assert ontology.load(path) == onto


@pytest.mark.parametrize('target,drawer', [('toy_wrench','drawer_top'), ('eraser','drawer_bottom')])
@pytest.mark.parametrize('bad', [None, 'gripper_unknown', 'location_unknown', 'open_unknown', 'location_missing', 'open_missing', 'held', 'wrong_drawer', 'opened'])
def test_composite_pre_uses_bound_drawer_and_rejects_unknown(target,drawer,bad):
    onto = ontology.load(SOURCE);state = copy.deepcopy(onto['state'])
    binding = {'target':target, 'from':drawer}
    if bad == 'gripper_unknown': state['gripper']['robot'] = None
    elif bad == 'location_unknown': state['located_in'][target] = None
    elif bad == 'open_unknown': state['open'][drawer] = None
    elif bad == 'location_missing': state['located_in'].pop(target)
    elif bad == 'open_missing': state['open'].pop(drawer)
    elif bad == 'held': state['gripper']['robot'] = target
    elif bad == 'wrong_drawer': binding['from'] = 'drawer_bottom' if drawer == 'drawer_top' else 'drawer_top'
    elif bad == 'opened': state['open'][drawer] = True
    results = ontology.check(state, onto['skills']['handover_with_unpack']['pre'], binding)
    assert all(r['pass'] for r in results) == (bad is None)


@pytest.mark.parametrize('change', [
    {'plan_effect':[]}, {'plan_effect':'sensing'}, {'plan_effect':None},
    {'plan_effect':[{}]},
    {'plan_effect':[{'subject':'$target','predicate':'unknown','value':'handover_zone'}]},
    {'plan_effect':[{'subject':'absent_item','predicate':'located_in','value':'handover_zone'}]},
    {'plan_effect':[{'subject':'$missing','predicate':'located_in','value':'handover_zone'}]},
    {'plan_effect':[{'subject':'$target','predicate':'located_in','value':'absent_place'}]},
    {'plan_effect':[{'subject':'$target','predicate':'located_in','value':'$missing'}]},
    {'plan_effect':[{'subject':'$target','predicate':'located_in','value':'handover_zone','op':'=='}]},
    {'params':{'target':'MissingClass','from':'Drawer'}},
    {'params':{'target':'Drawer','from':'Drawer'}},
    {'params':{'target':'Item','from':'Item'}},
    {'params':{'target':'Item'}}, {'params':[]},
    {'kind':'primitive'}, {'effect':[]}, {'task':''},
    {'pre':[{'subject':'$missing','predicate':'open','op':'==','value':False}]},
    {'pre':[{'subject':'$from','predicate':'open','op':'==','value':None}]},
    {'pre':[{'subject':'$from','predicate':'open','op':[],'value':False}]},
])
def test_loader_rejects_malformed_planning_field_and_references(tmp_path,change):
    onto = ontology.load(SOURCE)
    onto['skills']['handover_with_unpack'].update(change)
    path = tmp_path/'invalid.jsonld';path.write_text(json.dumps(onto))
    with pytest.raises(ValueError, match='plan_effect'):
        ontology.load(path)


def test_manifest_loader_rejects_bad_plan_reference(tmp_path):
    source = _split_copy(tmp_path)
    path = source.parent/'skills/handover_with_unpack.jsonld'
    doc = json.loads(path.read_text());doc['skills']['handover_with_unpack']['plan_effect'][0]['value']='unregistered'
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='plan_effect'):ontology.load(source)


def test_actual_c_public_plan_consumer_or_explicitly_pending():
    import inspect
    from ready2go_runner.core.planner import plan, UNPLANNABLE, PLANNED
    from ready2go_runner.core.interpreter import Runner, ActionResult
    onto = ontology.load(SOURCE);before = copy.deepcopy(onto['state'])
    # C 실제 공개 소비 함수. C 새 구현 이전에는 composite만으로 계획할 수 없습니다.
    composite_only = copy.deepcopy(onto)
    composite_only['skills'] = {'handover_with_unpack':onto['skills']['handover_with_unpack']}
    goal = [{'subject':'eraser','predicate':'located_in','value':'handover_zone'}]
    opt_in = {'composites':True} if 'composites' in inspect.signature(plan).parameters else {}
    result = plan(before, composite_only, goal, **opt_in)
    if result.status == UNPLANNABLE:
        calls=[]
        runner = Runner(lambda *args: calls.append(args) or ActionResult(True), ontology=onto)
        execution = runner.run({'task_id':'e_composite_boundary', 'sequence':[
            {'id':'c1','skill':'handover_with_unpack',
             'params':{'target':'eraser','from':'drawer_bottom'}}]})
        assert execution.error_code == 'TASK_INVALID' and calls == []
        assert any('composite' in problem for problem in execution.problems)
        assert runner.state == before
        pytest.skip('현재 C 공개 planner는 primitive-only: 새 composite 소비/구간 실행 연결 대기')
    assert result.status == PLANNED
    assert result.steps[0].skill == 'handover_with_unpack'
    assert result.steps[0].params == {'target':'eraser', 'from':'drawer_bottom'}
    assert onto['state'] == before  # 계획 예상 효과를 실제 상태에 쓰지 않습니다.
