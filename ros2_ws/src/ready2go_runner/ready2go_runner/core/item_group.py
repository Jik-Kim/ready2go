"""목록·분류 요청 실행 (P3 1차, ROS 비의존) — #302 E 확정 10/15 (사용자 승인), 정본 UC-P3·FR-ONT-03.

E 가 목록·분류("출근 준비물", "귀중품")를 활성 물품 키로 풀어 준 결과(`ready2go_knowledge.core.semantic_query`
`query_list`/`query_class` 의 `{items, source, evidence}`)를 받아:
1. 물품마다 **Runner 현재 상태**로 기존 `query_ontology {item}` 위치 조회 — 위치를 모르거나 서랍이 아니면 빼고 시작 안내에
   이유, 전부 빠지면 로봇 동작 없이 거절(`UNKNOWN_ITEM`). 초기 배치로 위치를 보충하지 않음. 클래스 계층은 E 몫(C 는 다시 계산 안 함).
2. 서랍 순서(world.places 의 Drawer 순)로 묶고, **물품마다 기존 `find_with_unpack` 을 차례로 실행** — 같은 서랍도 물품마다
   열고 닫음(서랍당 한 번 열기는 후속), 한 번에 서랍 하나·물품 하나 전달.
3. 다음 물품으로 넘어가는 조건(허용 목록): 그 물품 실행이 정리까지 끝났고(COMPLETED·FAILED) 원인이 움직이기 전 실패
   (`CONTINUE_CODES`, 또는 코드 없음 — #359 전 main 은 못 꺼내도 COMPLETED)이며 빈손·그 서랍 닫힘. 그 밖(정지·충돌·동작 불확실·
   쥔 상태 모름·놓침·복구 실패 등)은 **묶음 전체 중단**(기존 규칙). 복구 실패는 결과 코드만 보지 않고 태스크 표식
   (`task_error = RESTORE_INCOMPLETE`·`restore_failed`)도 봄 — Runner 는 처음 원인(예 `NO_FREE_SPACE`)을 결과에 남기므로 (#371 E P2).
4. 결과: 요청한 물품을 전부 전달 `COMPLETED` / 일부 `FAILED`+`PARTIAL_DELIVERY` / 하나도 못 함 `FAILED`+첫 원인 /
   정지 `ABORTED`. **새 상태 값·`outcome` 필드 없음**(E 확정). 물품별 결과는 `GroupResult.items` 에 보존.
   전달 여부 = Runner 상태 `located_in(물품) == handover_zone`(place 스킬 effect) — 실행 결과 상태만 보지 않음.
5. 안내: 시작("차키, 립밤 가져올게요. 에어팟 케이스는 위치 기록이 없어서 빼고 가져올게요") / 끝 요약(실제 전달 수·못 가져온 물품).
   묶음 안 정지는 재개하지 않음 — "목록 작업은 이어서 할 수 없어요"(반복 안 재개 확장은 별도 후속). 묶음을 도는 동안만
   Runner 재개 보존(`resumable`)을 꺼서 물품 실행이 `SUSPENDED` 로 남지 않게 함 — 정지 잠금은 그대로, 끝나면 원래 설정 (#371 E P2).

공개 인텐트(`find_list`/`find_class` + `semantic`, #302 계약안)는 노드가 이 함수로 실행 — 요청 하나 = 상위 run_id R 하나
(#377 과 같은 상태 칸 규칙): 물품 실행은 `R.1`, `R.2` …(`parent_run_id: R`). 수락 안내(`accept_text`)가 있으면 첫 동작 전에
그 문장 1회 — 안내가 실패하면 로봇 동작 0번(계약07 규칙), 위치 기록이 없어 뺀 물품은 그다음에 이유를 따로 안내.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .interpreter import Runner, RunResult
from .ontology_query import BAD_QUERY, UNKNOWN_ITEM, query
from .variables import attach_particle

PARTIAL_DELIVERY = "PARTIAL_DELIVERY"       # 요청한 물품 중 일부만 전달 (overall_status FAILED, E 확정 10/15)
HANDOVER = "handover_zone"
# 이 코드로 끝난 물품은 정리(되돌리기·닫기·홈)까지 끝난 '움직이기 전 실패' — 빈손·서랍 닫힘이면 다음 물품으로
CONTINUE_CODES = {"TARGET_NOT_FOUND", "OCCLUSION_UNKNOWN", "UNPACK_INCOMPLETE", "NO_FREE_SPACE"}
SOURCE_KINDS = {"list", "class"}

DELIVERED, NOT_DELIVERED, EXCLUDED, NOT_RUN = "DELIVERED", "NOT_DELIVERED", "EXCLUDED", "NOT_RUN"
REASON_KO = {                               # 끝 요약에서 못 가져온 이유 ("립밤은 못 찾았어요")
    "TARGET_NOT_FOUND": "못 찾았어요",
    "OCCLUSION_UNKNOWN": "위에 뭐가 있는지 확인하지 못했어요",
    "NO_FREE_SPACE": "위에 있는 물건을 옮기지 못했어요",
    UNKNOWN_ITEM: "위치 기록이 없어요",
    "NOT_IN_DRAWER": "서랍에 있지 않아요",
}
REASON_DEFAULT = "꺼내지 못했어요"


@dataclass
class ItemOutcome:
    item: str
    name_ko: str
    drawer: str | None = None
    status: str = NOT_RUN                   # DELIVERED / NOT_DELIVERED / EXCLUDED / NOT_RUN(앞에서 멈춰 실행 안 함)
    overall_status: str | None = None       # 그 물품 find_with_unpack 실행 결과
    error_code: str | None = None
    run_id: str | None = None
    restore_incomplete: bool = False        # 그 물품 실행에서 옮긴 물건을 다 되돌리지 못함 (결과 코드와 따로)
    failure: dict | None = None             # 그 물품 실행의 last.failure 원천 (#376) — FAILED 물품의 처음 원인


@dataclass
class GroupResult:
    overall_status: str                     # COMPLETED / FAILED / ABORTED — 기존 값만
    error_code: str | None
    items: list[ItemOutcome] = field(default_factory=list)
    source: dict | None = None
    start_text: str | None = None
    summary_text: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def delivered(self) -> list[str]:
        return [o.item for o in self.items if o.status == DELIVERED]


def check_semantic(semantic, world: dict) -> list[str]:
    """E 조회 결과 형식 확인 (실행 전, 로봇 동작 없음). 문제가 있으면 이유 목록."""
    if not isinstance(semantic, dict):
        return ["E 조회 결과가 객체가 아님"]
    items, source = semantic.get("items"), semantic.get("source")
    problems = []
    if not isinstance(items, list) or not items:
        problems.append("items 가 비어 있지 않은 목록이어야 함")
    else:
        if any(not isinstance(i, str) or not i for i in items):
            problems.append("items 는 물품 키 문자열")
        elif len(set(items)) != len(items):
            problems.append("items 에 같은 물품이 두 번 이상")
        unknown = [i for i in items if isinstance(i, str) and i not in world.get("items", {})]
        if unknown:
            problems.append(f"활성 물품이 아님: {unknown}")
    if not isinstance(source, dict) or source.get("kind") not in SOURCE_KINDS:
        problems.append(f"source.kind 는 {sorted(SOURCE_KINDS)} 중 하나")
    return problems


def plan_group(semantic: dict, state: dict, world: dict) -> tuple[list[ItemOutcome], list[ItemOutcome]]:
    """(실행할 물품 — 서랍 순서, 뺀 물품). 위치는 Runner 현재 상태의 query_ontology {item} 만."""
    drawers = [p for p, info in world.get("places", {}).items() if isinstance(info, dict) and info.get("class") == "Drawer"]
    names = {k: v.get("name_ko", k) for k, v in world.get("items", {}).items()}
    runnable, excluded = [], []
    for item in semantic["items"]:
        found = query({"item": item}, state, world)
        if not found.success:
            excluded.append(ItemOutcome(item, names.get(item, item), status=EXCLUDED, error_code=UNKNOWN_ITEM))
            continue
        drawer = found.output["drawer_id"]
        if drawer not in drawers:           # 이미 트레이에 있음·쥐고 있음 등 — 서랍에서 꺼낼 물품이 아님
            excluded.append(ItemOutcome(item, names.get(item, item), drawer, EXCLUDED, error_code="NOT_IN_DRAWER"))
            continue
        runnable.append(ItemOutcome(item, names.get(item, item), drawer))
    runnable.sort(key=lambda o: drawers.index(o.drawer))   # 안정 정렬 — 같은 서랍 안은 E 가 준 순서
    return runnable, excluded


def start_text(runnable: list[ItemOutcome], excluded: list[ItemOutcome], accepted: bool = False) -> str:
    """시작 안내. accepted = E 수락 문장을 이미 말함 → 뺀 물품 이유만 (없으면 빈 문자열)."""
    text = "" if accepted else ", ".join(o.name_ko for o in runnable) + " 가져올게요."
    if excluded:
        why = {o.error_code for o in excluded}
        reason = "위치 기록이 없어서" if why == {UNKNOWN_ITEM} else "서랍에서 꺼낼 물건이 아니라서" if why == {"NOT_IN_DRAWER"} \
            else "위치를 확인하지 못해서"
        text += f" {attach_particle(', '.join(o.name_ko for o in excluded), '은')} {reason} 빼고 가져올게요."
    return text.strip()


def summary_text(result: GroupResult, stopped: str | None) -> str:
    total, got = len(result.items), len(result.delivered)
    if result.overall_status == "COMPLETED":
        return f"{total}개 모두 가져왔어요." if total > 1 else f"{attach_particle(result.items[0].name_ko, '을')} 가져왔어요."
    head = f"{total}개 중 {got}개 가져왔어요." if got else "하나도 가져오지 못했어요."
    misses = [o for o in result.items if o.status in (NOT_DELIVERED, EXCLUDED)]
    parts = [f"{attach_particle(o.name_ko, '은')} {REASON_KO.get(o.error_code, REASON_DEFAULT)}" for o in misses]
    left = [o.name_ko for o in result.items if o.status == NOT_RUN]
    if left:
        parts.append(f"{attach_particle(', '.join(left), '은')} 작업하지 않았어요")
    tail = ""
    if any(o.restore_incomplete for o in result.items):
        tail = " 옮긴 물건 일부를 원래 자리로 못 돌려놔서 목록 작업을 멈췄어요. 사람이 확인해 주세요."
    elif stopped == "halted":
        tail = " 목록 작업은 멈춰서 이어서 할 수 없어요. 다시 요청해 주세요."
    elif stopped == "failed":
        tail = " 문제가 생겨 목록 작업을 멈췄어요."
    return " ".join([head, *[p + "." for p in parts]]) + tail


def _delivered(runner: Runner, item: str) -> bool:
    return (runner.state.get("located_in") or {}).get(item) == HANDOVER


def _restore_incomplete(result: RunResult) -> bool:
    """태스크가 남긴 복구 실패 표식 — 처음 원인이 허용 코드여도 정리(복구)가 실패했을 수 있음 (Runner 는 처음 원인을 우선 보존)."""
    board = result.blackboard or {}
    mark = board.get("task_error")
    return (isinstance(mark, dict) and mark.get("code") == "RESTORE_INCOMPLETE") or bool(board.get("restore_failed"))


def _safe_to_continue(runner: Runner, result: RunResult, drawer: str) -> bool:
    if result.overall_status not in ("COMPLETED", "FAILED"):
        return False
    if result.overall_status == "FAILED" and result.error_code not in CONTINUE_CODES:
        return False
    state = runner.state
    return (state.get("gripper") or {}).get("robot") == "empty" and (state.get("open") or {}).get(drawer) is False


def run_group(runner: Runner, task: dict, semantic: dict, world: dict,
              speak: Callable[[str], object] | None = None, run_id: str | None = None, meta: dict | None = None,
              accept_text: str | None = None) -> GroupResult:
    """E 조회 결과로 물품마다 task(find_with_unpack)를 차례로 실행. speak(text) → 실패 코드(문자열) 또는 None(성공):
    시작·끝 안내(노드가 /voice/speak 연결). run_id: 상위 R — 물품 실행은 R.1, R.2 …, meta: 물품 실행 기록 헤더(parent_run_id 붙임).
    accept_text: E 수락 문장 — 첫 동작 전 1회, 실패하면 로봇 동작 0번으로 FAILED(그 코드)."""
    problems = check_semantic(semantic, world)
    if problems:
        return GroupResult("FAILED", BAD_QUERY, source=(semantic or {}).get("source") if isinstance(semantic, dict) else None,
                           problems=problems)
    runnable, excluded = plan_group(semantic, runner.state, world)
    result = GroupResult("FAILED", None, [*runnable, *excluded], semantic["source"])
    if not runnable:                        # 전부 위치 미상·서랍 밖 — 로봇 동작 없이 거절
        result.error_code = UNKNOWN_ITEM if any(o.error_code == UNKNOWN_ITEM for o in excluded) else "NOT_IN_DRAWER"
        result.problems = ["실행할 물품이 없음 (위치 기록 없음·서랍 밖)"]
        result.summary_text = summary_text(result, None)
        return result

    def say(text: str):
        """실패 코드 또는 None. 안내 예외는 실패 코드로 (실행을 깨뜨리지 않음)."""
        if speak is None or not text:
            return None
        try:
            code = speak(text)
        except Exception:  # noqa: BLE001
            return "BACKEND_ERROR"
        return code if isinstance(code, str) and code else None

    if accept_text:                         # 계약07: 수락 문장 1회 — 실패하면 로봇 동작 0번
        failed = say(accept_text)
        if runner.halted:                   # 안내 중 정지 — 실패 코드(CANCELED 등)보다 정지가 먼저 (#381 E 리뷰)
            result.overall_status, result.error_code = "ABORTED", runner.halt_code or "HALTED"
            result.problems = ["수락 안내 중 정지 — 로봇 동작 없음"]
            return result
        if failed:
            result.error_code, result.problems = failed, ["수락 안내 실패 — 로봇 동작 없음"]
            return result
    result.start_text = start_text(runnable, excluded, accepted=bool(accept_text))
    say(result.start_text)
    stopped = None
    resumable = runner.resumable            # 묶음 안 정지는 보존·재개 없음 — 물품 실행이 SUSPENDED 로 남지 않게 (#371 E P2)
    runner.resumable = False
    try:
        for outcome in runnable:
            if runner.halted:               # 물품 사이 정지 — 다음 물품을 시작하지 않음
                result.overall_status, result.error_code, stopped = "ABORTED", runner.halt_code or "HALTED", "halted"
                break
            child = {"run_id": f"{run_id}.{runnable.index(outcome) + 1}" if run_id else None,
                     "meta": {**(meta or {}), **({"parent_run_id": run_id} if run_id else {})} or None}
            run = runner.run(task, {"target": outcome.item}, **child)
            outcome.overall_status, outcome.error_code, outcome.run_id = run.overall_status, run.error_code, run.run_id
            outcome.failure = run.failure
            outcome.status = DELIVERED if _delivered(runner, outcome.item) else NOT_DELIVERED
            outcome.restore_incomplete = _restore_incomplete(run)
            if run.overall_status in ("ABORTED", "SUSPENDED"):   # 정지·비상정지 (SUSPENDED 는 보존을 꺼서 안 옴 — 방어)
                result.overall_status, result.error_code, stopped = "ABORTED", run.error_code, "halted"
                break
            if outcome.restore_incomplete:  # 허용 코드여도 정리(복구)가 실패했으면 다음 물품 안 함
                result.overall_status, result.error_code, stopped = "FAILED", "RESTORE_INCOMPLETE", "failed"
                break
            if not _safe_to_continue(runner, run, outcome.drawer):
                result.overall_status, result.error_code, stopped = "FAILED", run.error_code or "GROUP_STOPPED", "failed"
                break
    finally:
        runner.resumable = resumable
    if stopped is None:
        got = len(result.delivered)
        if got == len(result.items):
            result.overall_status, result.error_code = "COMPLETED", None
        elif got:
            result.error_code = PARTIAL_DELIVERY
        else:
            first = next(o for o in result.items if o.status in (NOT_DELIVERED, EXCLUDED))
            result.error_code = first.error_code or "UNPACK_INCOMPLETE"
    result.summary_text = summary_text(result, stopped)
    say(result.summary_text)
    return result
