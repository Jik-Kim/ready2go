"""스텝 진행 콘솔 한 줄 (ROS 비의존) — #98: 터미널만 보고 진행·실패 지점을 알 수 있게.

문구는 run_report(실행 기록 보고서)와 같은 함수(mark·label·detail)를 써서 콘솔과 보고서가 같은 말을 한다.
B 스킬 서버 로그와 시각·동작 이름으로 대조할 수 있게 시작 시각(KST, ms)과 원자 동작 이름을 같이 적는다.
콘솔 출력은 보기용이며 MongoDB/JSONL 실행 기록을 대신하지 않는다 (저장 성공은 run_id 로 조회해 확인).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .interpreter import HALT_CODES, HALTED
from .log_records import step_document
from .run_report import detail, label, mark

INFO, WARN, ERROR = "info", "warn", "error"
# 시작 줄을 찍지 않는 즉시 끝나는 동작 (줄 수를 줄임 — 끝 줄만)
INSTANT = {"query_ontology", "update_ontology", "set_var", "if", "push", "pop"}
STOP_CODES = HALT_CODES | {HALTED, "CANCELED"}
_KST = timezone(timedelta(hours=9))


def _clock(iso: str | None) -> str:
    """'2026-10-08T00:14:06.123Z' → '09:14:06.123' (KST). B 로그와 시각 대조용."""
    if not iso:
        return "--:--:--"
    try:
        stamp = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(_KST)
    except ValueError:
        return iso
    return stamp.strftime("%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}"


def _name(record: dict) -> str:
    """'서랍 열기 (drawer_control)' — 한국어 이름 + 원자 동작/스킬 이름(B 로그의 액션 이름과 같음)."""
    raw = record.get("skill") if record.get("action") == "skill" else record.get("action")
    ko = label(record)
    return f"{ko} ({raw})" if raw and raw != ko else ko


def _prefix(run_id: str, record: dict, in_finally: bool) -> str:
    tag = f"[{run_id[-6:]}]" if run_id else "[------]"
    where = "finally " if in_finally else ""
    indent = "  └ " if record.get("parent") else ""
    return f"{tag} {where}{indent}"


def start_line(run_id: str, record: dict, in_finally: bool = False, params: dict | None = None) -> str | None:
    """스텝 시작 줄. 즉시 끝나는 동작은 None (끝 줄만 찍음). params: 아직 풀지 않은 스텝 params (이름 표시용)."""
    if record.get("action") in INSTANT:
        return None
    if params and "params" not in record:
        record = {**record, "params": params}       # 원본 기록은 건드리지 않음
    return f"{_prefix(run_id, record, in_finally)}▶ {record['id']} {_name(record)} 시작 · {_clock(record.get('started_at'))}"


def end_line(run_id: str, record: dict, in_finally: bool = False) -> tuple[str, str]:
    """스텝 끝 줄과 로그 등급. 성공 info · 건너뜀/skip warn · 실패 error · 중단(비상정지·취소) error."""
    doc = step_document(run_id, 0, record)
    code = record.get("error_code")
    icon = "🛑" if code in STOP_CODES else mark(doc)
    parts = [f"{_prefix(run_id, record, in_finally)}{icon} {record['id']} {_name(record)}"]
    status = record.get("status")
    if status == "SKIPPED":
        parts.append(f"건너뜀 ({record.get('skipped_reason', '')})".replace(" ()", ""))
    elif status == "FAILURE" and record.get("on_failure") == "skip":
        parts.append("실패 → 건너뛰고 계속")
    if record.get("action") == "if" and record.get("branch"):
        parts.append(f"→ {record['branch']}")
    if record.get("duration_sec") is not None:
        parts.append(f"{record['duration_sec']:.1f} s")
    text = detail(doc)
    if text:
        parts.append(text)
    if record.get("retry_stopped"):
        parts.append(f"재시도 안 함({record['retry_stopped']})")
    if record.get("fallback_stopped"):
        parts.append(f"다음 대안 안 보냄({record['fallback_stopped']})")
    line = " · ".join([parts[0], *parts[1:]]) if len(parts) > 1 else parts[0]
    if icon == "✅":
        return INFO, line
    if icon == "⏭":
        return WARN, line
    return ERROR, line
