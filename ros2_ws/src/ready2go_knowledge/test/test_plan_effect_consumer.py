"""실제 C opt-in API + E 원본. C mock 장치만 재사용하며 제안 형식 복사본은 쓰지 않음."""
import copy
from pathlib import Path
import pytest
from ready2go_knowledge.core import ontology

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize('actual_delivery', [True, False])
def test_e_source_through_c_plan_exec_replans_only_after_actual_effect(actual_delivery):
    api = pytest.importorskip('ready2go_runner.core.plan_exec', reason='C #373 구간 실행 소비 API 연결 대기')
    from ready2go_runner.core import planner
    from ready2go_runner.core.mock_scene import MockScene
    from test_plan_exec import setup, load_task, LIMITS
    onto = ontology.load(ROOT/'knowledge/robot_ontology.jsonld')
    before = copy.deepcopy(onto)
    goals = [dict(subject='eraser',predicate='located_in',value='handover_zone'),
             dict(subject='drawer_top',predicate='open',value=True)]
    selected = planner.plan(onto['state'],onto,goals,limits=LIMITS,composites=True)
    assert [s.skill for s in selected.steps] == ['handover_with_unpack','open_drawer']
    assert selected.steps[0].params == {'target':'eraser','from':'drawer_bottom'}
    runner, robot = setup(onto,scene=MockScene('plate_over_eraser'))
    loaded=[]
    def tasks(path):
        loaded.append(path)
        assert path == onto['skills']['handover_with_unpack']['task'] == 'tasks/find_with_unpack.json'
        assert runner.state['located_in']['eraser'] == 'drawer_bottom'  # 예상 효과를 실제 상태에 미리 적용하지 않음
        if not actual_delivery:
            return {'task_id':'e_actual_no_effect','sequence':[
                {'id':'n1','action':'set_var','params':{'name':'checked','value':True}}]}
        return load_task(path)  # C 공개 head의 실제 find_with_unpack 원본
    out = api.run_plan(runner,onto,goals,tasks,limits=LIMITS)
    assert loaded == ['tasks/find_with_unpack.json'] and onto == before
    if not actual_delivery:
        assert (out.overall_status,out.error_code) == ('FAILED',api.PLAN_EFFECT_UNMET)
        assert len(out.segments) == 1 and runner.state['located_in']['eraser'] == 'drawer_bottom'
        assert robot.drawer_moves() == []
        return
    assert (out.overall_status,out.error_code) == ('COMPLETED',None)
    assert [s.kind for s in out.segments] == ['composite','primitive']
    assert [p['target']['class'] for a,p in robot.calls if a=='pick_object'] == ['cover_plate','eraser','cover_plate']
    assert runner.state['located_in']['eraser'] == 'handover_zone'
    assert (runner.state['open']['drawer_top'],runner.state['open']['drawer_bottom']) == (True,False)
    assert robot.drawer_moves() == [('drawer_bottom','open'),('drawer_bottom','close'),('drawer_top','open')]
