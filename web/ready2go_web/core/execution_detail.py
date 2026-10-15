"""기존 종료 기록을 화면용으로 정규화한다. 순서·분류·전달 여부를 재계산하지 않는다."""
from __future__ import annotations

from copy import deepcopy


RESULTS = {"COMPLETED", "FAILED", "ABORTED", "SUSPENDED"}
ITEM_RESULTS = {"DELIVERED", "NOT_DELIVERED", "EXCLUDED", "NOT_RUN"}
STEP_RESULTS = {"SUCCESS", "FAILURE", "SKIPPED"}


def linked_result(data):
    """현재 실행 run을 추측하지 않고 최근 요청에 확실히 연결된 종료 run만 허용한다."""
    if not isinstance(data, dict):
        return None
    intent, result = data.get("last_intent"), data.get("last")
    if not isinstance(intent, dict) or not isinstance(result, dict) or intent.get("decision") != "run":
        return None
    for key in ("run_id", "task_id"):
        if not isinstance(intent.get(key), str) or not intent[key].strip() or intent[key] != result.get(key):
            return None
    if result.get("overall_status") not in RESULTS:
        return None
    return result


def checked_bundle(reader, run_id):
    """외부 reader의 모든 상위/child 반환 구조를 같은 422 경계에서 검증한다."""
    bundle = reader.read_run(run_id)
    if not isinstance(bundle, dict) or not isinstance(bundle.get("steps"), list):
        raise ValueError("invalid record bundle")
    if bundle.get("run") is not None and not isinstance(bundle["run"], dict):
        raise ValueError("invalid run document")
    return bundle


def normalized_steps(bundle, run_id):
    """기록된 seq는 단계 시작 순서다. 누락 단계나 실행 중 단계를 만들어 넣지 않는다."""
    steps, seen = [], set()
    if not isinstance(bundle.get("steps"), list):
        raise ValueError("invalid steps")
    for row in bundle["steps"]:
        if not isinstance(row, dict):
            raise ValueError("invalid step")
        seq = row.get("seq")
        if row.get("run_id") != run_id or type(seq) is not int or seq < 0 or seq in seen:
            raise ValueError("invalid step identity/sequence")
        if not isinstance(row.get("id"), str) or row.get("status") not in STEP_RESULTS:
            raise ValueError("invalid step record")
        seen.add(seq)
        steps.append({key: deepcopy(row.get(key)) for key in
                      ("seq", "id", "status", "result", "error", "action", "started_at", "duration_sec")})
    return sorted(steps, key=lambda row: row["seq"])


def read_detail(reader, run_id, task_id, overall_status):
    """종료 기록의 물품 배열 순서를 보존한다. semantic.items는 실행 순서로 사용하지 않는다."""
    bundle = checked_bundle(reader, run_id)
    run = bundle.get("run")
    if run is None:
        return None
    if not isinstance(run, dict):
        raise ValueError("invalid run")
    if run.get("run_id") != run_id or run.get("task_id") != task_id:
        raise ValueError("run identity mismatch")
    # 토픽보다 저장이 늦거나 일부 기록만 남았으면 완료된 상세로 표시하지 않는다.
    if not run.get("ended_at") or run.get("overall_status") != overall_status:
        return None
    if not isinstance(run.get("ended_at"), str) or not isinstance(run.get("inputs"), dict):
        raise ValueError("invalid run metadata")
    if not isinstance(run.get("items", []), list) or not isinstance(run.get("segments", []), list):
        raise ValueError("invalid child references")
    semantic = run["inputs"].get("semantic")
    if semantic is not None and not isinstance(semantic, dict):
        raise ValueError("invalid semantic")
    items = []
    for outcome in run.get("items", []):
        if not isinstance(outcome, dict) or outcome.get("status") not in ITEM_RESULTS:
            raise ValueError("invalid item outcome")
        item_id, child_id = outcome.get("item"), outcome.get("run_id")
        if not isinstance(item_id, str) or not item_id or any(row["id"] == item_id for row in items):
            raise ValueError("invalid item identity")
        child_steps, available = [], False
        if child_id is not None:
            child = checked_bundle(reader, child_id)
            child_run = child.get("run")
            if child_run is not None:
                if child_run.get("run_id") != child_id or child_run.get("parent_run_id") != run_id:
                    raise ValueError("child parent mismatch")
                child_steps = normalized_steps(child, child_id)
                available = True
        evidence = (semantic or {}).get("evidence")
        items.append({"id": item_id, "runId": child_id, "status": outcome["status"],
                      "errorCode": outcome.get("error_code"), "steps": child_steps,
                      "recordedDrawer": outcome.get("drawer"),
                      "restoreIncomplete": outcome.get("restore_incomplete") is True,
                      "stepsAvailable": available,
                      "evidence": deepcopy(evidence.get(item_id)) if isinstance(evidence, dict) else None})
    # 묶음 계획 segments는 물품 순서와 다르므로 별도 기록으로 반환한다.
    segments = []
    for segment in run.get("segments", []):
        if not isinstance(segment, dict):
            raise ValueError("invalid segment")
        child_id = segment.get("run_id")
        if child_id is None:
            continue
        child = checked_bundle(reader, child_id)
        child_run = child.get("run")
        if child_run is not None and (child_run.get("parent_run_id") != run_id or child_run.get("run_id") != child_id):
            raise ValueError("segment parent mismatch")
        segments.append({"runId": child_id, "kind": segment.get("kind"),
                         "steps": normalized_steps(child, child_id) if child_run else []})
    return {"runId": run_id, "taskId": task_id, "overallStatus": overall_status,
            "kind": "finished_record", "endedAt": run["ended_at"], "items": items,
            "steps": normalized_steps(bundle, run_id), "segments": segments,
            "semantic": deepcopy(semantic), "location": None, "destination": None,
            "delivery": {"completed": sum(row["status"] == "DELIVERED" for row in items),
                         "total": sum(row["status"] != "EXCLUDED" for row in items)} if items else None}
