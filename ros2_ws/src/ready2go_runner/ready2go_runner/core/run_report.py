"""실행 기록 → 사람이 읽는 요약 (ROS·DB 비의존) — #23 C "MongoDB/JSONL 조회".

LogStore.read_run() 결과({"run", "steps"})를 한국어 줄 목록·Markdown 표로 바꾼다. 기록은 읽기만 한다.
- 시각은 KST, 길이는 mm, 오류 코드에는 짧은 한국어 설명 (docs/runner.md 7.1 에러 표)
- 행 = 최상위 스텝(parent 없음). if 는 줄로 내지 않고(안쪽 스텝이 따로 기록됨),
  스킬이 펼친 원자 동작(parent 있음)은 그 스킬 밑에 들여 쓴다.
"""
from __future__ import annotations

import json
import math

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

ACTION_KO = {
    "query_ontology": "온톨로지 조회", "update_ontology": "상태 갱신", "inspect_region": "물체 조회",
    "move_to_named_pose": "자세 이동", "nudge_object": "끌기", "pick_object": "집기",
    "place_object": "놓기", "speak": "안내 음성", "set_var": "변수",
    "while": "반복", "for_each": "목록 반복", "push": "기록 쌓기", "pop": "기록 꺼내기", "fallback": "대안",
    "select_obstacle": "치울 물체 고르기", "find_moved": "옮긴 물체 찾기",
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
    "RESTORE_INCOMPLETE": "옮긴 물체를 원래 자리로 다 돌려놓지 못함 (되돌리기 실패·다시 못 찾음·쥔 채 멈춤) — 전달은 됐을 수 있음",
    "REGION_NOT_VISIBLE": "촬영 지역 바닥이 충분히 안 보임 (가림·뎁스 결손·다른 곳을 찍음) — 미검출 아님, 관측 오류",
    "TASK_INVALID": "태스크 검사 실패 — 실행 전 거절 (로봇 동작 없음)",
}
HAND_KO = {"holding": "쥠", "empty": "빈손 확인", "released": "다시 벌림 — 빈손 확정 아님", "unknown": "쥐었는지 모름"}
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
    try:
        return "-" if value is None else f"{float(value):.1f} s"
    except (TypeError, ValueError):                 # 기록 값이 숫자가 아니어도 보고서는 멈추지 않음 (#167 PM 권장)
        return f"{value} s"


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
    """스텝 하나의 핵심 값 한 줄. 실패면 오류 설명을 붙인다. 결과 값 모양이 예상과 달라도(숫자가 아닌 좌표 등)
    보고서 전체가 멈추지 않게 그 칸만 '값을 읽을 수 없음'으로 둔다 (#167 PM 권장 — 보고서는 사람이 원인을 볼 도구)."""
    try:
        text = _detail_text(step)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        text = "결과 값을 읽을 수 없음"
    action = step.get("action")
    code = (step.get("error") or {}).get("code") if isinstance(step.get("error"), dict) else None
    if code and action == "skill" and not text:
        text = code                            # 설명은 아래 원자 동작 줄에 (같은 설명 두 번 안 씀)
    elif code:
        text = f"{code}: {ERROR_KO.get(code, '')}".rstrip(": ") + (f" — {text}" if text else "")
    return text


def _detail_text(step: dict) -> str:
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
        text = params.get("pose_name", "") + (" · 이미 그 자세라 보내지 않음" if step.get("same_pose") else "")   # #245
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
        elif not params.get("search_target"):           # 찾는 물체 없이 서랍 전체 촬영(되돌리기·복구 확인) — 실패 아님
            text = f"보인 물체 {result.get('visible_count', 0)}개"
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
            hand = HAND_KO.get(result.get("hand"))     # #223 B: 실패 뒤 손 상태 (released ≠ 빈손)
            if hand and not result["grasp_ok"]:
                text += f" ({hand})"
    elif action == "place_object" and (result or params.get("check_only")):
        check = bool(params.get("check_only") or result.get("check_only"))   # #241 판단만 — 놓은 것처럼 보이지 않게
        position = (result.get("planned_pose" if check else "placed_pose") or {}).get("position")
        where = str(result.get("slot") or "") or (               # 고정 자리 이름, 없으면 B 가 명령한(놓을) 자리 (#166)
            f"({float(position[0]) * 1000:.0f}, {float(position[1]) * 1000:.0f}) mm" if position else "")
        if check:
            text = "판단만(움직이지 않음)" + (f" → 놓을 수 있음: {where}" if where else "")
        else:
            text = where if result.get("slot") or not where else f"놓은 자리 {where}"
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
    elif action == "find_moved" and result:
        check = restore_check(step)
        if check:
            text = f"복구 확인 {check['class']}: {_restore_text(check)}"
        else:
            distance = result.get("distance_m")
            text = str(result.get("status", "")) + (f" (놓은 자리에서 {_mm(distance)})" if distance is not None else "")
    return text


def _yaw_error(a, b) -> float:
    """두 yaw 의 차이 rad. 비전 yaw 는 (−π/2, π/2] 반 바퀴 주기(contracts/README inspect_region pose)라 π 로 접는다."""
    d = abs(float(a) - float(b)) % math.pi
    return min(d, math.pi - d)


def restore_check(step: dict) -> dict | None:
    """원위치 복구 확인 기록(find_with_unpack fv.3.1 — find_moved 의 record.placed = origin)이면 원래 자리와 지금 자리의
    위치·방향 오차 (AC-ACT-03 "위치와 방향 오차를 함께 기록"). 판정은 하지 않음 — 기준값은 정본·시험표에서."""
    record = (step.get("params") or {}).get("record") or {}
    origin = record.get("origin")
    if step.get("action") != "find_moved" or not isinstance(origin, dict) or record.get("placed") != origin:
        return None
    result = step.get("result") or {}
    check = {"class": record.get("class"), "status": result.get("status"),
             "position_m": result.get("distance_m"), "yaw_rad": None}
    seen = result.get("object") or {}
    now = seen.get("pose") or {}
    if origin.get("yaw_valid") and now.get("yaw_valid"):
        check["yaw_rad"] = _yaw_error(origin.get("yaw"), now.get("yaw"))
    above = seen.get("occluded_by")
    if isinstance(above, list) and above:       # 마지막 촬영에서 위에 다른 물체(되돌린 차키 등)가 올라가 가려짐 → 보이는 조각
        check["occluded_by"] = above            # 가운데라 실제 자리와 다름 (A Isaac 10/13: 캐러멜 실제 0.3 mm 가 18.3 mm 로)
    return check


def _restore_text(check: dict) -> str:
    if check["position_m"] is None:
        return f"못 찾음({check['status']})"
    if check.get("occluded_by"):                # 가려진 조각 기준 값 — 위치 오차로 쓰지 않음 (AC-ACT-03 근거 아님)
        return (f"가려짐(위에 {', '.join(check['occluded_by'])}) — 보이는 조각 기준 {_mm(check['position_m'])}, "
                f"위치 오차로 쓰지 않음")
    yaw = "방향 모름" if check["yaw_rad"] is None else f"방향 오차 {math.degrees(check['yaw_rad']):.1f}°"
    return f"위치 오차 {_mm(check['position_m'])} · {yaw}" + ("" if check["status"] == "found" else f" ({check['status']})")


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


STEP_STATUSES = {"SUCCESS", "FAILURE", "SKIPPED"}


def check(record: dict) -> list[str]:
    """실행 기록이 빠짐없이 저장됐는지 — FR-LOG-02 "DB 기록과 실행 결과의 누락 여부 확인", AC-LOG-01 증거용.
    빈 목록 = 완전. 기록만 보고 판단하며(읽기 전용) 로봇 동작·실행 결과의 옳고 그름은 판단하지 않는다."""
    run, steps = record.get("run"), record.get("steps") or []
    if not run:
        return ["실행 헤더(runs) 없음 — start_run 저장 누락"]
    problems = []
    run_id, status = run.get("run_id"), run.get("overall_status")
    if status is None:
        problems.append("끝 기록 없음 — 아직 실행 중이거나 end_run 저장 누락")
    elif run.get("total_duration_sec") is None or not run.get("ended_at"):
        problems.append("끝 기록에 종료 시각·전체 시간 없음")
    if status in ("FAILED", "ABORTED", "SUSPENDED") and not (run.get("error") or {}).get("code"):
        problems.append(f"{status} 인데 오류 코드 없음")
    other = sorted({s.get("run_id") for s in steps} - {run_id})
    if other:
        problems.append(f"다른 실행의 스텝 기록이 섞임: {other}")
    seqs = [s.get("seq") for s in steps]
    if any(not isinstance(q, int) for q in seqs):
        problems.append("seq 없는 스텝 기록 있음")
    numbers = [q for q in seqs if isinstance(q, int)]
    if numbers:
        missing = sorted(set(range(max(numbers) + 1)) - set(numbers))
        if missing:
            problems.append(f"스텝 기록 빠짐: seq {missing}")
        dup = sorted({q for q in numbers if numbers.count(q) > 1})
        if dup:
            problems.append(f"스텝 기록 중복: seq {dup}")
    ids = {s.get("id") for s in steps}
    for s in steps:
        if s.get("status") not in STEP_STATUSES:
            problems.append(f"결과 없는 스텝 [{s.get('id')}] (seq {s.get('seq')})")
        if s.get("status") == "FAILURE" and not (s.get("error") or {}).get("code"):
            problems.append(f"실패인데 오류 코드 없는 스텝 [{s.get('id')}]")
        if s.get("parent") and s["parent"] not in ids:
            problems.append(f"부모 스텝 기록 없음 [{s.get('id')}] → {s['parent']}")
    failed = run.get("failed_step")
    if failed and steps and failed not in ids:
        problems.append(f"실패 스텝 {failed} 의 기록 없음")
    return problems


def check_line(record: dict) -> str:
    """`run_report --check` 한 줄: ✅ 완전 / ❌ 누락 목록."""
    run = record.get("run") or {}
    head = f"{run.get('run_id', '?')} · {run.get('task_id', '?')} · {run.get('overall_status') or '끝 기록 없음'}"
    problems = check(record)
    if not problems:
        return f"✅ {head} · 스텝 기록 {len(record.get('steps') or [])}개 빠짐없음"
    return "\n".join([f"❌ {head}"] + [f"   - {p}" for p in problems])


HALT_SOURCE_KO = {"service": "/runner/estop", "voice": "음성 멈춰", "backend": "스킬 서버", "runner": "Runner"}


def _gap(start: str | None, end: str | None) -> float | None:
    """두 ISO 시각 사이 초 (정지 요청 → 응답). 모르면 None."""
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(0.0, (b - a).total_seconds())
    except (AttributeError, TypeError, ValueError):
        return None


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
    for halt in run.get("halts") or []:          # 정지 기록 (#187 요청→응답 시각, #152 재개·버림)
        if halt.get("resumed_at"):
            then = f"재개 {kst(halt['resumed_at'])}"
        elif halt.get("discarded_at"):
            then = f"버림 {kst(halt['discarded_at'])}"
        else:
            then = "재개 대기" if status == "SUSPENDED" else "중단"
        source = HALT_SOURCE_KO.get(halt.get("source"), halt.get("source") or "")
        reply = ""
        if halt.get("step_code"):
            gap = _gap(halt.get("requested_at") or halt.get("at"), halt.get("stopped_at"))
            reply = f" · 응답 {halt['step_code']}" + (f" +{gap:.1f} s" if gap is not None else "")
        lines.append(f"  정지 {kst(halt.get('requested_at') or halt.get('at'))} · {halt.get('code')}"
                     + (f" · {source}" if source else "") + f" · {halt.get('step') or '마지막 뒤'}{reply} → {then}")
    aside = [(st.get("params") or {}).get("value") or {} for st in steps
             if st.get("action") == "push" and (st.get("params") or {}).get("stack") == "left_aside"
             and st.get("status") == "SUCCESS"]
    if aside:                                    # find_with_unpack: 원래 자리가 막혀 꺼냈던 빈 자리에 둔 물체 (사람이 찾을 수 있게)
        lines.append("  원래 자리 대신 빈 자리: " + ", ".join(f"{a.get('class', '?')}({a.get('slot', '?')})" for a in aside)
                     + " — 원위치 복구 아님 (A안은 2차 점검의 제한적 통과, AC-ACT-03 완료 아님 — #239 E 리뷰)")
    checks = [c for c in (restore_check(st) for st in steps) if c]
    if checks:                                   # AC-ACT-03 근거 — 판정 아님, 기준은 정본·시험표
        lines.append("  복구 오차 (판정 아님): " + "; ".join(f"{c['class']} {_restore_text(c)}" for c in checks))
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
