"""실행 기록 → 사람이 읽는 요약 (ROS·DB 비의존) — #23 C "MongoDB/JSONL 조회".

LogStore.read_run() 결과({"run", "steps"})를 한국어 줄 목록·Markdown 표로 바꾼다. 기록은 읽기만 한다.
- 시각은 KST, 길이는 mm, 오류 코드에는 짧은 한국어 설명 (docs/runner.md 7.1 에러 표)
- 행 = 최상위 스텝(parent 없음). if 는 줄로 내지 않고(안쪽 스텝이 따로 기록됨),
  스킬이 펼친 원자 동작(parent 있음)은 그 스킬 밑에 들여 쓴다.
"""
from __future__ import annotations

import json

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

ACTION_KO = {
    "query_ontology": "온톨로지 조회", "update_ontology": "상태 갱신", "inspect_region": "물체 조회",
    "move_to_named_pose": "자세 이동", "nudge_object": "끌기", "pick_object": "집기",
    "place_object": "놓기", "speak": "안내 음성", "set_var": "변수",
    "while": "반복", "for_each": "목록 반복", "push": "기록 쌓기", "pop": "기록 꺼내기", "fallback": "대안",
}
SKILL_KO = {
    "open_drawer": "서랍 열기", "close_drawer": "서랍 닫기", "pick": "집기", "pick_demo": "끌어서 집기",
    "place": "놓기", "inspect": "물체 조회",
}
ERROR_KO = {
    "BACKEND_ERROR": "백엔드 호출 실패 — 서버 없음·goal 거절(동작 안 함) 또는 통신 끊김",
    "PRE_UNMET": "사전 조건 불충족 (로봇 동작 안 보냄)",
    "TIMEOUT": "제한 시간 초과", "ESTOP": "비상정지", "HALTED": "Runner 중단 (취소·/runner/estop)",
    "STOP_UNCONFIRMED": "정지 확인 없음 → 잠금", "STATE_UNKNOWN": "로봇 상태 조회 실패 → 잠금",
    "MOVE_UNCONFIRMED": "이동 명령 수락 여부 모름 → 잠금", "LOCKED": "스킬 서버 잠김",
    "ACTION_FAILED": "백엔드가 코드 없이 실패", "INTERNAL_ERROR": "Runner 내부 오류",
    "VAR_UNDEFINED": "없는 변수 참조", "VAR_NULL": "변수 값이 null",
    "LOOP_LIMIT": "반복 최대 횟수 초과", "STACK_EMPTY": "꺼낼 기록이 없음", "NOT_A_LIST": "목록이 아님",
    "FALLBACK_FAILED": "대안이 없음",
    "TOOL_NOT_SET": "펜던트 툴·TCP 설정이 다름", "DRAWER_NOT_AT_TRAVEL": "서랍 인출 거리가 기준과 다름",
    "YAW_INVALID": "물체 방향(yaw)을 믿을 수 없음", "NOT_ON_FLOOR": "물체가 바닥에 있지 않음",
    "WALL_TOO_CLOSE": "벽에 너무 붙어 집을 수 없음", "NO_PUSH_ACCESS": "끌어도 잡을 수 없는 자리",
    "PUSH_BLOCKED": "끌다가 힘 초과", "NO_OBJECT_CONTACT": "끌기: 물체 접촉 없음",
    "GRASP_FAILED": "파지 실패", "UNKNOWN_SKILL": "알 수 없는 스킬",
    "TASK_INVALID": "태스크 검사 실패 — 실행 전 거절 (로봇 동작 없음)",
}
RUN_KO = {"COMPLETED": "✅ 성공", "FAILED": "❌ 실패", "ABORTED": "🛑 중단", "SUSPENDED": "⏸ 재개 대기"}


def kst(iso: str | None) -> str:
    """'2026-10-06T11:07:13.090Z' → '10/06 20:07:13' (KST)."""
    if not iso:
        return "-"
    when = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(KST)
    return when.strftime("%m/%d %H:%M:%S")


def _mm(metres) -> str:
    return f"{float(metres) * 1000:.1f} mm"


def _seconds(value) -> str:
    return "-" if value is None else f"{float(value):.1f} s"


def mark(step: dict) -> str:
    status = step.get("status")
    if status == "SUCCESS":
        return "✅"
    if status == "SKIPPED" or (status == "FAILURE" and step.get("on_failure") == "skip"):
        return "⏭"
    return "❌" if status == "FAILURE" else (status or "?")


def label(step: dict) -> str:
    if step.get("action") == "skill":
        return SKILL_KO.get(step.get("skill"), step.get("skill") or "스킬")
    if step.get("action") == "drawer_control":
        return {"open": "서랍 열기", "close": "서랍 닫기"}.get((step.get("params") or {}).get("state"), "서랍")
    return ACTION_KO.get(step.get("action"), step.get("action") or "?")


def _state_diff(diff: dict) -> str:
    """{'open.drawer_top': [False, True]} → 'drawer_top 닫힘 → 열림' (온톨로지 상태 변화)."""
    parts = []
    for key, (before, after) in diff.items():
        predicate, _, subject = key.partition(".")
        if predicate == "open":
            word = {True: "열림", False: "닫힘"}
            parts.append(f"{subject} {word.get(before, before)} → {word.get(after, after)}")
        elif predicate == "gripper":
            parts.append(f"그리퍼 {before} → {after}")
        elif predicate == "located_in":
            parts.append(f"{subject} 위치 {before} → {after}")
        else:
            parts.append(f"{key} {before} → {after}")
    return ", ".join(parts)


def detail(step: dict) -> str:
    """스텝 하나의 핵심 값 한 줄. 실패면 오류 설명을 붙인다."""
    action, params, result = step.get("action"), step.get("params") or {}, step.get("result") or {}
    text = ""
    if action == "skill":
        text = _state_diff(step.get("state_diff") or {})
        failed = [c for c in step.get("pre_check") or [] if not c.get("pass")]
        if failed:
            text = ", ".join(f"{c['subject']}.{c['predicate']} = {c.get('actual')} (필요 {c.get('value')})"
                             for c in failed)
    elif action == "query_ontology":
        if "item" in params:
            text = f"{params['item']} → {result.get('drawer_id', '?')}"
        elif "state" in params:
            text = f"{result.get('path', params['state'])} = {result.get('value')}"
    elif action == "move_to_named_pose":
        text = params.get("pose_name", "")
    elif action == "drawer_control" and result:
        if params.get("state") == "open":
            text = f"{_mm(result.get('drawer_displacement', 0))} 열림"
        else:
            text = "닫힘 확인" if result.get("close_confirmed") else "닫힘 미확인"
    elif action == "inspect_region" and result:
        target = result.get("target")
        if result.get("target_found") and target:
            position = (target.get("pose") or {}).get("position") or []
            name = target.get("class") or target.get("id")
            text = (f"{name} 찾음 ({float(position[0]) * 1000:.0f}, {float(position[1]) * 1000:.0f}) mm"
                    if len(position) >= 2 else f"{name} 찾음")        # 위치가 빠진 기록도 보고서는 멈추지 않음
        else:
            text = f"못 찾음 (보인 물체 {result.get('visible_count', 0)}개)"
    elif action == "nudge_object" and result:
        if result.get("pushed"):
            dx, dy = (result.get("push_vector_m") or [0, 0])[:2]
            text = f"{(float(dx) ** 2 + float(dy) ** 2) ** 0.5 * 1000:.1f} mm 끌기"
            after = (result.get("target_after") or {}).get("pose", {}).get("position")
            if after:
                text += f" → 예상 위치 ({float(after[0]) * 1000:.0f}, {float(after[1]) * 1000:.0f}) mm"
        else:
            text = "끌 필요 없음"
    elif action == "pick_object" and result:
        if "grasp_ok" in result:                       # 값이 없으면 판단을 적지 않음 (없음 ≠ 못 잡음)
            text = "잡음" if result["grasp_ok"] else "못 잡음"
    elif action == "place_object" and result:
        position = (result.get("placed_pose") or {}).get("position")
        text = str(result.get("slot") or "") or (               # 고정 자리 이름, 없으면 B 가 명령한 자리 (#166)
            f"놓은 자리 ({float(position[0]) * 1000:.0f}, {float(position[1]) * 1000:.0f}) mm" if position else "")
    elif action == "speak":
        text = f"\"{params.get('text', '')}\""
    elif action in ("while", "for_each") and step.get("iterations") is not None:
        text = f"{step['iterations']}회"
    elif action == "fallback" and step.get("option"):
        text = f"{step['option']}번 대안"
        if step.get("fallback_stopped"):           # 앞 대안이 팔을 움직였거나 결과 불확실 → 다음 대안 안 보냄
            text += f" · 다음 대안 안 보냄({step['fallback_stopped']})"
    elif action == "push" and result:
        text = f"{result.get('stack')} {result.get('size')}개"
    elif action == "pop" and "result" in step:
        text = json.dumps(step.get("result"), ensure_ascii=False)[:60]
    elif action == "set_var":
        text = f"{params.get('name')} = {params.get('value')}"
    code = (step.get("error") or {}).get("code")
    if code and action == "skill" and not text:
        text = code                            # 설명은 아래 원자 동작 줄에 (같은 설명 두 번 안 씀)
    elif code:
        text = f"{code}: {ERROR_KO.get(code, '')}".rstrip(": ") + (f" — {text}" if text else "")
    return text


@dataclass
class Row:
    step: dict
    children: list[Row] = field(default_factory=list)


def rows(steps: list[dict]) -> list[Row]:
    """최상위 스텝(if 제외) + 그 밑의 원자 동작. seq 순서.
    하위 동작은 seq 가 바로 앞인 같은 ID 의 스킬 기록에 붙인다(스킬 기록이 하위 동작보다 먼저 시작). 반복 안에서는
    같은 스텝 ID 가 회차마다 기록되므로, ID·회차로 묶으면 중첩 반복에서 다른 바깥 회차와 섞인다(#159 E 리뷰)."""
    result: list[Row] = []
    latest: dict[str, Row] = {}
    for step in sorted(steps, key=lambda s: s.get("seq", 0)):
        if step.get("parent"):
            owner = latest.get(step["parent"])
            if owner is not None:
                owner.children.append(Row(step))
        elif step.get("action") != "if":
            latest[step.get("id")] = row = Row(step)
            result.append(row)
    return result


def step_ref(step: dict) -> str:
    """'s2.1' / 반복 안이면 's2.1 · 2회차'."""
    return f"{step.get('id')} · {step['iteration']}회차" if step.get("iteration") else str(step.get("id"))


def header(record: dict) -> list[str]:
    run, steps = record.get("run") or {}, record.get("steps") or []
    status = run.get("overall_status")
    first = (f"실행 {run.get('run_id', '?')} · {run.get('task_id', '?')} · {RUN_KO.get(status, status or '진행 중?')}"
             f" · {_seconds(run.get('total_duration_sec'))} · 스텝 기록 {len(steps)}개")
    second = f"  시작 {kst(run.get('started_at'))} KST"
    inputs = run.get("inputs") or {}
    if inputs:
        second += " · 입력 " + ", ".join(f"{k}={v}" for k, v in inputs.items() if k != "intent_confidence")
    if run.get("backend"):
        second += f" · backend={run['backend']}"
    lines = [first, second]
    code = (run.get("error") or {}).get("code")
    if code:
        where = f"실패 스텝 {run['failed_step']}" if run.get("failed_step") else "실행 전 거절"
        lines.append(f"  {where} · {code}: {ERROR_KO.get(code, '')}".rstrip(": "))
    for halt in run.get("halts") or []:          # #152 정지 사건 → 재개·버림
        then = (f"재개 {kst(halt['resumed_at'])}" if halt.get("resumed_at")
                else f"버림 {kst(halt['discarded_at'])}" if halt.get("discarded_at") else "재개 대기")
        lines.append(f"  정지 {kst(halt.get('at'))} · {halt.get('code')} · {halt.get('step') or '마지막 뒤'} → {then}")
    for problem in run.get("problems") or []:    # 실행하지 않은 이유 (TASK_INVALID 검사 결과, 중단 잠김) — #105 D 리뷰
        lines.append(f"  이유: {problem}")
    return lines


def to_text(record: dict) -> str:
    lines = header(record) + [""]
    for n, row in enumerate(rows(record.get("steps") or []), 1):
        s = row.step
        lines.append(f"{n:>3} {mark(s)} {label(s)} · {_seconds(s.get('duration_sec'))}"
                     + (f" · {detail(s)}" if detail(s) else "") + f"   [{step_ref(s)}]")
        for child in row.children:
            c = child.step
            lines.append(f"      └ {mark(c)} {label(c)} · {_seconds(c.get('duration_sec'))}"
                         + (f" · {detail(c)}" if detail(c) else "") + f"   [{step_ref(c)}]")
    return "\n".join(lines)


def to_markdown(record: dict) -> str:
    """GitHub 댓글에 그대로 붙이는 표 (#22·#23 결과 보고)."""
    head = header(record)
    lines = ["**" + head[0] + "**", ""] + [f"- {line.strip()}" for line in head[1:]] + [""]
    lines += ["| # | 단계 | 결과 | 시간 | 내용 | 스텝 |", "| ---: | :--- | :---: | ---: | :--- | :--- |"]
    for n, row in enumerate(rows(record.get("steps") or []), 1):
        for depth, item in [(0, row)] + [(1, c) for c in row.children]:
            s = item.step
            name = ("└ " if depth else "") + label(s)
            lines.append(f"| {n if not depth else ''} | {name} | {mark(s)} | {_seconds(s.get('duration_sec'))} "
                         f"| {detail(s).replace('|', '/')} | `{step_ref(s)}` |")
    return "\n".join(lines)
