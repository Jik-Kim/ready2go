"""재개 불가 이유의 C 상태·실제 태스크 대조. 장치와 실행 정책은 변경하지 않는다."""
from copy import deepcopy

import pytest

from ready2go_voice.core.hotfix import prompts
from ready2go_voice.core.runner_speech import task_steps, unavailable_work_text
from ready2go_voice.core.tts_prefill import prefill_texts


def status(step='f2.e1', outcome='ABORTED'):
    return dict(phase='idle', halt=None, last=dict(run_id='run',task_id='find_with_unpack',
                                                overall_status=outcome,failed_step=step))


def test_expanded_finally_close_reason_and_prefill(cfg, ontology, tmp_path):
    texts = prompts(cfg)
    steps = task_steps(cfg)
    assert steps['find_with_unpack']['f2']['_in_finally']
    assert steps['find_with_unpack']['f2']['skill'] == 'close_drawer'
    assert not steps['find_with_unpack']['s8.t1']['_in_finally']
    recovered = unavailable_work_text(status(),steps,texts,recovered=True,run_id='run')
    assert recovered == texts['runtime_recover_finally_close']
    assert '서랍을 닫는 마무리 단계' in recovered
    assert unavailable_work_text(status(),steps,texts) == texts['runtime_resume_finally_close']
    assert unavailable_work_text(status('fr.5.1'),steps,texts) == texts['runtime_resume_finally']
    assert unavailable_work_text(status('s8.t2.e1'),steps,texts) == texts['runtime_resume_no_work']
    assert unavailable_work_text(status(),steps,texts,operation='recover') == texts['runtime_no_recover_work']
    cfg['tts_melotts_assets'] = str(tmp_path)
    assert cfg['tts_prefill_max_texts'] == 512
    selected = prefill_texts(cfg,ontology['world']['items'].values())
    for key in ('runtime_recover_finally_close','runtime_recover_finally','runtime_recover_no_work',
                'runtime_resume_finally_close','runtime_resume_finally','runtime_resume_no_work',
                'runtime_no_recover_work'):
        assert texts[key] in selected


@pytest.mark.parametrize('change', ['missing', 'running', 'halted', 'offered', 'suspended', 'other_run', 'missing_halt'])
def test_unknown_or_resumable_work_never_claimed_absent(cfg, change):
    doc = status()
    if change == 'missing': doc = None
    elif change == 'running': doc['phase'] = 'running'
    elif change == 'halted': doc['phase'] = 'halted'
    elif change == 'offered': doc['halt'] = dict(resume=dict(offered=True))
    elif change == 'suspended': doc['last']['overall_status'] = 'SUSPENDED'
    elif change == 'missing_halt': del doc['halt']
    else: doc['last']['run_id'] = 'other'
    assert unavailable_work_text(doc,task_steps(cfg),prompts(cfg),recovered=True,run_id='run') is None


def test_unknown_step_is_not_guessed_as_finally(cfg):
    texts = prompts(cfg)
    doc = status('not_in_task.e1')
    before = deepcopy(doc)
    assert unavailable_work_text(doc,task_steps(cfg),texts,recovered=True,run_id='run') == texts['runtime_recover_no_work']
    assert doc == before
