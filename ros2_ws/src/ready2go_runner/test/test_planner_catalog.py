"""AC-PLN-01 목표형 명령 시험표 (#150) — E 선정 5종(E-150-GOAL-CATALOG-20261010-01) + 별도 시험(이미 만족·계획 불가).
칸: 명령 · 시작 상태 · 목표 · 생성 계획과 단계별 근거 · mock 실행 뒤 최종 상태. 실물 결과는 10/12 실물 기록(이 파일 밖).
실물 범위 = Runner 노드 plan_limits 기본값 planner.DEFAULT_PLAN_LIMITS(위·아래 칸, 서랍은 한 번에 하나만) — test_real_limits_match_runner_default.
시작 상태 = 사용자 확정 P2 단일 배치(start_states.P2_SINGLE — 위 S1·아래 S2, #283)를 시험이 직접 정함(운영 initial_state 와 무관).
docs/planner.md 의 같은 표와 짝."""
import copy
import json
from pathlib import Path

import pytest

from ready2go_knowledge.core import ontology
from ready2go_runner.core import planner as pl

from test_planner import run_plan  # noqa: E402  (계획 → 태스크 → Runner(mock) 실행)
from test_tasks import MockRobot  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
from start_states import P2_SINGLE, with_state  # noqa: E402

ONTO = with_state(ontology.load(ROOT / "knowledge/robot_ontology.jsonld"), P2_SINGLE)
REAL_TEXT = ("open_drawer.drawer_id=drawer_top|drawer_bottom,open_drawer.one_open=true,"
             "close_drawer.drawer_id=drawer_top|drawer_bottom,pick.from=drawer_top|drawer_bottom,place.to=handover_zone")
REAL = pl.parse_limits(REAL_TEXT)
ONE_OPEN = {"open_drawer": {"one_open": {"true"}}}   # 값 제한 없이 "서랍 하나만" 규칙만 (mock 계획 비교용)


def state(open_top=False, **located):
    s = copy.deepcopy(ONTO["state"])
    s["open"]["drawer_top"] = open_top
    s["located_in"].update(located)
    return s


def g(subject, value, predicate="located_in"):
    return {"predicate": predicate, "subject": subject, "value": value}


OPEN, CLOSE = "open_drawer(drawer_top)", "close_drawer(drawer_top)"
OPEN_B, CLOSE_B = "open_drawer(drawer_bottom)", "close_drawer(drawer_bottom)"


def deliver_bottom(item):   # P2 단일 배치: 지우개·립밤은 아래 칸
    return [OPEN_B, f"pick({item}, drawer_bottom)", f"place({item}, handover_zone)", CLOSE_B]


# E 선정 5종 (번호·명령·목표 = E 결정 표). (번호, 명령, 시작 상태, 목표, 계획, 끝난 뒤 위 서랍 열림)
SELECTED = [
    (1, "지우개 트레이에 갖다 놔", state(), [g("eraser", "handover_zone")], deliver_bottom("eraser"), False),
    (2, "위 서랍 열어 둬", state(), [g("drawer_top", True, "open")], [OPEN], True),
    (3, "위 서랍 닫아", state(open_top=True), [g("drawer_top", False, "open")], [CLOSE], False),
    (4, "지우개 갖다 놓고 서랍은 열어 둬", state(), [g("eraser", "handover_zone"), g("drawer_top", True, "open")],
     deliver_bottom("eraser") + [OPEN], True),     # 아래 칸을 닫은 뒤 위 칸을 엶 — 두 칸을 같이 열고 집지 않음(one_open)
    (5, "립밤 트레이에 갖다 놔", state(), [g("lip_balm", "handover_zone")], deliver_bottom("lip_balm"), False),
]
IDS = [f"{c[0]}-{c[1]}" for c in SELECTED]


def test_selected_five_are_e_decision():
    assert [(c[0], c[1]) for c in SELECTED] == [
        (1, "지우개 트레이에 갖다 놔"), (2, "위 서랍 열어 둬"), (3, "위 서랍 닫아"),
        (4, "지우개 갖다 놓고 서랍은 열어 둬"), (5, "립밤 트레이에 갖다 놔")]


@pytest.mark.parametrize("no, name, initial, goals, steps, open_after", SELECTED, ids=IDS)
def test_selected_plans_on_real_range_with_reasons(no, name, initial, goals, steps, open_after):
    """실물 지원 범위에서 계획되고, 제한 없는 mock 계획과 같으며, 모든 스텝에 근거(어느 조건·목표 때문인지)가 있다."""
    real = pl.plan(initial, ONTO, goals, limits=REAL)
    assert real.status == pl.PLANNED, real.reason
    assert [s.label() for s in real.steps] == steps
    assert [s.label() for s in pl.plan(initial, ONTO, goals, limits=ONE_OPEN).steps] == steps   # 값 제한 없는 mock 과 같음
    assert all(s.reasons for s in real.steps), pl.describe(real)
    assert any("목표" in r for s in real.steps for r in s.reasons)          # 명시 목표가 근거에 나옴


@pytest.mark.parametrize("no, name, initial, goals, steps, open_after", SELECTED, ids=IDS)
def test_selected_runs_on_mock_and_final_state_meets_goals(no, name, initial, goals, steps, open_after):
    """계획 → 태스크 → Runner(mock) 실행 뒤 상태: 목표 모두 참, 위 서랍 열림/닫힘이 기대대로, 빈손."""
    runner, result = run_plan(MockRobot(), pl.plan(initial, ONTO, goals, limits=REAL), initial)
    assert result.overall_status == "COMPLETED", [(s["id"], s.get("status"), s.get("error_code")) for s in result.steps]
    assert all(runner.state[x["predicate"]][x["subject"]] == x["value"] for x in goals)
    assert runner.state["open"]["drawer_top"] is open_after
    assert runner.state["open"]["drawer_bottom"] is False                   # 아래 칸은 닫고 끝남
    assert runner.state["gripper"] == initial["gripper"]                    # 빈손으로 끝남


# 별도 시험 — 5종 실물 기록을 대체하지 않음 (E 결정: 이미 만족 = 0동작, 계획 불가 = 실행 0)
EXTRA = [   # (명령, 시작 상태, 목표, 실물 범위 결과, 이유에 나올 말)
    ("지우개 서랍에 둬 (이미 있음)", state(), [g("eraser", "drawer_bottom")], pl.SATISFIED, "이미 만족"),
    ("위 서랍 닫아 (이미 닫힘)", state(), [g("drawer_top", False, "open")], pl.SATISFIED, "이미 만족"),
    ("트레이의 지우개 서랍에 다시 넣어", state(eraser="handover_zone"), [g("eraser", "drawer_bottom")],
     pl.UNPLANNABLE, "지원 범위"),                                         # 트레이 집기·서랍 놓기 미지원
    ("립밤 위 서랍으로 옮겨", state(), [g("lip_balm", "drawer_top")], pl.UNPLANNABLE, "지원 범위"),   # 서랍 안 놓기 미지원
    ("전달 트레이 닫아", state(), [g("handover_zone", False, "open")], pl.UNPLANNABLE, "handover_zone"),
]


@pytest.mark.parametrize("name, initial, goals, status, words", EXTRA, ids=[c[0] for c in EXTRA])
def test_extra_satisfied_or_unplannable_runs_nothing(name, initial, goals, status, words):
    real = pl.plan(initial, ONTO, goals, limits=REAL)
    assert (real.status, real.steps) == (status, [])
    assert words in real.reason, real.reason
    with pytest.raises(ValueError):                                        # 태스크가 안 만들어짐 = 로봇 동작 0
        pl.to_task(real)


def test_real_limits_match_runner_default():
    """시험의 실물 범위가 Runner 가 실제로 쓰는 기본값과 같은지 (값을 따로 정하지 않음)."""
    assert pl.parse_limits(pl.DEFAULT_PLAN_LIMITS) == REAL
    src = (ROOT / "ros2_ws/src/ready2go_runner/ready2go_runner/nodes/runner_node.py").read_text(encoding="utf-8")
    assert "planner.DEFAULT_PLAN_LIMITS" in src                            # 노드가 이 값을 기본으로 씀


def test_catalog_table_in_planner_md_lists_same_commands():
    doc = ROOT / "docs/planner.md"
    if not doc.exists():                                   # ros2-core 컨테이너에는 docs/ 가 마운트되지 않음 (호스트·CI 에서 검사)
        pytest.skip("docs/planner.md 없음 (컨테이너)")
    text = doc.read_text(encoding="utf-8")
    for no, name, *_ in SELECTED:
        assert f"| {no} | {name} |" in text, name
    for name, *_ in EXTRA:
        assert name in text, name


if __name__ == "__main__":       # 표 만들 때 근거 보기: PYTHONPATH=..:../../ready2go_knowledge python3 test_planner_catalog.py
    for no, name, initial, goals, *_ in SELECTED:
        print(no, name, json.dumps(goals, ensure_ascii=False))
        print("\n".join("   " + line for line in pl.describe(pl.plan(initial, ONTO, goals, limits=REAL))))
    for name, initial, goals, *_ in EXTRA:
        print("-", name, "→", pl.describe(pl.plan(initial, ONTO, goals, limits=REAL))[0])
