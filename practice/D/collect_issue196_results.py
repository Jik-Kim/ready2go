#!/usr/bin/env python3
"""Collect one Issue #196 trial from Runner evidence into the versioned JSONL.

The collector fills reproducible metadata and required check rows. It never
invents a passing observation: checks missing from the optional measurement
file are recorded as ``unverifiable`` and the automatic result becomes
``inconclusive``. By default it only prints a validated preview; ``--append``
is required to change the result JSONL.

Examples:
  python3 practice/D/collect_issue196_results.py \
    --suite recovery --case-id S10 --environment mock \
    --runner-record /logs/run.json --checks /logs/s10-checks.json

  python3 practice/D/collect_issue196_results.py \
    --suite part --case-id C-03 --environment real \
    --runner-record /logs/2026-10-12T10-00-00Z_ab12cd.jsonl \
    --source 'https://artifacts.example/run-ab12cd.jsonl?sha256=<runner-sha256>' \
    --append

The optional check file is emitted by the integration test, not filled by a
person during the run. A passing check must include its actual evidence; a
missing evidence field is downgraded to ``unverifiable``. Its minimal shape is::

  {"machine_checks": {"check_id": {
    "status": "pass", "observed": true, "expected": true,
    "evidence": ["artifact:source.json?sha256=<sha256>#path"]}}}
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import validate_issue196_artifacts as validator


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_RESULTS = HERE / "issue196_results.v0.5-draft.jsonl"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class CollectionError(ValueError):
    """Raised when source evidence cannot produce a trustworthy trial."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _trial_started_at(run: dict[str, Any]) -> str:
    value = run.get("started_at")
    if not isinstance(value, str) or not value.strip():
        raise CollectionError("runner record must contain the actual trial started_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CollectionError("runner started_at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise CollectionError("runner started_at must include a timezone")
    return value


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CollectionError(f"cannot read {label} {path}: {exc}") from exc
    return _load_json_object_bytes(raw, path, label)


def _load_json_object_bytes(raw: bytes, path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CollectionError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CollectionError(f"{label} must be a JSON object: {path}")
    return value


def load_runner_record(path: Path, raw: bytes | None = None) -> dict[str, Any]:
    """Load exported {run, steps}, flat execution_log JSON, or Runner fallback JSONL."""
    path = path.resolve()
    if raw is None:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CollectionError(f"cannot read runner record {path}: {exc}") from exc
    if path.suffix != ".jsonl":
        value = _load_json_object_bytes(raw, path, "runner record")
        if isinstance(value.get("run"), dict) and isinstance(value.get("steps"), list):
            return value
        if isinstance(value.get("run_id"), str):
            steps = value.get("steps", value.get("logs", []))
            if not isinstance(steps, list):
                raise CollectionError("flat runner record steps/logs must be a list")
            run = {key: item for key, item in value.items() if key not in {"steps", "logs"}}
            return {"run": run, "steps": steps}
        raise CollectionError("runner record must contain {run, steps} or run_id")

    run: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CollectionError(f"cannot read runner record {path}: {exc}") from exc
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise CollectionError(f"runner JSONL line {line_number}: {exc}") from exc
        if not isinstance(entry, dict) or not isinstance(entry.get("doc"), dict):
            raise CollectionError(f"runner JSONL line {line_number} has invalid record")
        if entry.get("collection") == "runs":
            run = entry["doc"]
        elif entry.get("collection") == "steps":
            steps.append(entry["doc"])
    if run is None:
        raise CollectionError("runner JSONL has no runs record")
    return {"run": run, "steps": sorted(steps, key=lambda item: item.get("seq", 0))}


def _load_result_context(result_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    result_path = result_path.resolve()
    first_line = result_path.read_text(encoding="utf-8").splitlines()[0]
    result_set = json.loads(first_line)
    evaluation_path = result_path.parent / result_set["evaluation_path"]
    evaluation = _load_json_object(evaluation_path, "evaluation")
    voice_path = evaluation_path.parent / evaluation["voice_evaluation"]["path"]
    voice = _load_json_object(voice_path, "voice evaluation")
    return result_set, evaluation, voice


def _code_sha(override: str | None, run: dict[str, Any]) -> str:
    basis = run.get("basis") if isinstance(run.get("basis"), dict) else {}
    recorded = run.get("code_sha", basis.get("code_sha"))
    for label, value in (("--code-sha", override), ("runner code_sha", recorded)):
        if value is not None and (
            not isinstance(value, str) or not SHA_PATTERN.fullmatch(value)
        ):
            raise CollectionError(f"{label} must be 40 lowercase hexadecimal characters")
    if override is not None and recorded is not None and override != recorded:
        raise CollectionError("--code-sha does not match runner code_sha")
    if override is not None:
        return override
    if recorded is not None:
        return recorded
    raise CollectionError(
        "test-run code SHA is missing; record run.code_sha or pass --code-sha"
    )


def _normalise_checks(value: Any) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if isinstance(value, list):
        rows = value
    elif isinstance(value, dict):
        rows = []
        for check_id, detail in value.items():
            if not isinstance(detail, dict):
                raise CollectionError(f"check {check_id} must be an object")
            rows.append({"check_id": check_id, **detail})
    else:
        raise CollectionError("machine_checks must be a list or object")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("check_id"), str)
            or not row["check_id"].strip()
        ):
            raise CollectionError("every machine check must have a non-empty string check_id")
        check_id = row["check_id"]
        if check_id in result:
            raise CollectionError(f"duplicate machine check: {check_id}")
        result[check_id] = row
    return result


def _source_ref(path: Path, raw: bytes) -> str:
    resolved = path.resolve()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        relative = resolved.relative_to(REPO_ROOT)
    except ValueError:
        return f"artifact:{resolved.name}?sha256={digest}"
    return f"repo:{relative.as_posix()}?sha256={digest}"


def _object_field(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CollectionError(f"{label} must be an object")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise CollectionError(f"{label} must be a list of non-empty strings")
    return value


def _merge_without_conflicts(
    primary: dict[str, Any], supplemental: dict[str, Any], label: str
) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in supplemental.items():
        if key in merged and merged[key] is not None and merged[key] != value:
            raise CollectionError(
                f"{label}.{key} conflicts with the Runner record"
            )
        merged[key] = value
    return merged


def _empty_check_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False


def _machine_checks(
    required: list[str] | None,
    supplied: dict[str, dict[str, Any]],
    runner_record: dict[str, Any],
    environment: str,
    runner_ref: str,
    checks_ref: str | None,
) -> list[dict[str, Any]]:
    if required is not None:
        unexpected = sorted(set(supplied) - set(required))
        if unexpected:
            raise CollectionError(f"unexpected checks for case: {unexpected}")
        check_ids = required
    else:
        check_ids = sorted(supplied)

    rows: list[dict[str, Any]] = []
    for check_id in check_ids:
        source = supplied.get(check_id)
        if source is None:
            source = _derive_machine_check(
                check_id, runner_record, environment, runner_ref
            )
        if source is None:
            rows.append(
                {
                    "check_id": check_id,
                    "status": "unverifiable",
                    "observed": "unavailable",
                    "expected": "required",
                    "evidence": [f"{runner_ref}#missing:{check_id}"],
                }
            )
            continue
        observed = source.get("observed", "unavailable")
        expected = source.get("expected", "required")
        status = source.get("status")
        if status is None:
            status = "pass" if observed == expected else "fail"
        if status == "pass" and (
            "observed" not in source
            or "expected" not in source
            or _empty_check_value(observed)
            or _empty_check_value(expected)
            or observed == "unavailable"
            or expected == "required"
        ):
            status = "unverifiable"
        evidence = source.get("evidence")
        if evidence is None:
            origin = checks_ref or runner_ref
            evidence = [f"{origin}#missing-evidence:{check_id}"]
            if status == "pass":
                status = "unverifiable"
        else:
            evidence = _string_list(evidence, f"machine check {check_id} evidence")
            if status == "pass" and not evidence:
                status = "unverifiable"
        rows.append(
            {
                "check_id": check_id,
                "status": status,
                "observed": observed,
                "expected": expected,
                "evidence": evidence,
            }
        )
    return rows


def _derive_machine_check(
    check_id: str,
    runner_record: dict[str, Any],
    environment: str,
    runner_ref: str,
) -> dict[str, Any] | None:
    """Return only checks directly demonstrated by an exported Runner field."""
    run = runner_record["run"]
    evidence_root = runner_ref
    if check_id == "backend_environment_recorded":
        recorded = run.get("backend", run.get("environment"))
        if isinstance(recorded, str) and recorded.strip():
            return {
                "status": "pass" if recorded == environment else "fail",
                "observed": recorded,
                "expected": environment,
                "evidence": [f"{evidence_root}#run/backend"],
            }
    return None


def _automatic_result(checks: list[dict[str, Any]], pass_supported: bool) -> str:
    if any(check["status"] == "fail" for check in checks):
        return "fail"
    if not checks:
        return "not_evaluated"
    if not pass_supported or any(check["status"] != "pass" for check in checks):
        return "inconclusive"
    return "pass"


def build_records(
    *,
    result_path: Path,
    runner_path: Path,
    checks_path: Path | None,
    suite: str,
    case_id: str,
    environment: str,
    code_sha: str | None = None,
    basis_id: str | None = None,
    trial_id: str | None = None,
    human_approvals: list[str] | None = None,
    extra_sources: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result_set, evaluation, voice = _load_result_context(result_path)
    allowed_environments = evaluation["basis_policy"]["environment_values"]
    if environment not in allowed_environments:
        raise CollectionError(f"environment must be one of {allowed_environments}")

    runner_path = runner_path.resolve()
    try:
        runner_raw = runner_path.read_bytes()
    except OSError as exc:
        raise CollectionError(f"cannot read runner record {runner_path}: {exc}") from exc
    runner_record = load_runner_record(runner_path, runner_raw)
    runner_ref = _source_ref(runner_path, runner_raw)
    run = runner_record["run"]
    runner_environment = run.get("backend", run.get("environment"))
    if runner_environment is not None and runner_environment != environment:
        raise CollectionError(
            f"runner environment {runner_environment!r} does not match {environment!r}"
        )

    required_machine, required_human, pass_supported = validator._case_requirements(
        evaluation, voice, suite, case_id
    )
    checks_ref: str | None = None
    if checks_path:
        checks_path = checks_path.resolve()
        try:
            checks_raw = checks_path.read_bytes()
        except OSError as exc:
            raise CollectionError(f"cannot read check results {checks_path}: {exc}") from exc
        measurement = _load_json_object_bytes(checks_raw, checks_path, "check results")
        checks_ref = _source_ref(checks_path, checks_raw)
    else:
        measurement = {}
    supplied = _normalise_checks(measurement.get("machine_checks"))
    checks = _machine_checks(
        required_machine,
        supplied,
        runner_record,
        environment,
        runner_ref,
        checks_ref,
    )
    automatic_result = _automatic_result(checks, pass_supported)

    now = _utc_now()
    token = uuid.uuid4().hex[:10]
    resolved_sha = _code_sha(code_sha, run)
    resolved_basis_id = basis_id or f"basis-{environment}-{resolved_sha[:7]}-{token}"
    run_id = run.get("run_id")
    resolved_trial_id = trial_id or f"trial-{case_id.lower()}-{token}"
    halts = run.get("halts") if isinstance(run.get("halts"), list) else []
    active_halt = halts[-1] if halts and isinstance(halts[-1], dict) else {}

    source_refs = [runner_ref]
    if checks_ref:
        source_refs.append(checks_ref)
    source_refs.extend(_string_list(extra_sources, "sources"))
    basis = {
        "record_type": "basis",
        "schema_version": result_set["schema_version"],
        "basis_id": resolved_basis_id,
        "captured_at": now,
        "environment": environment,
        "code_sha": resolved_sha,
        "sources": source_refs,
        "human_approvals": human_approvals or [],
    }
    correlation = {"run_id": run_id} if run_id else {}
    for key in ("event_id", "question_id", "boot_id"):
        value = active_halt.get(key, run.get(key))
        if value is not None:
            correlation[key if key != "event_id" else "halt_event_id"] = value
    input_reference = {
        "task_id": run.get("task_id"),
        "inputs": run.get("inputs", {}),
    }
    input_reference = _merge_without_conflicts(
        input_reference,
        _object_field(measurement.get("input_reference"), "input_reference"),
        "input_reference",
    )
    correlation = _merge_without_conflicts(
        correlation,
        _object_field(measurement.get("correlation"), "correlation"),
        "correlation",
    )
    if suite == "recovery":
        halt_event_id = correlation.get("halt_event_id")
        if not isinstance(halt_event_id, str) or not halt_event_id.strip():
            raise CollectionError("recovery trial requires a non-empty halt_event_id")
    trial_evidence = source_refs + _string_list(measurement.get("evidence"), "evidence")
    trial = {
        "record_type": "trial",
        "schema_version": result_set["schema_version"],
        "trial_id": resolved_trial_id,
        "result_set_id": result_set["result_set_id"],
        "evaluation_version": result_set["evaluation_version"],
        "evaluation_sha256": result_set["evaluation_sha256"],
        "suite": suite,
        "suite_version": result_set["suite_versions"][suite],
        "case_id": case_id,
        "basis_id": resolved_basis_id,
        "environment": environment,
        "started_at": _trial_started_at(run),
        "correlation": correlation,
        "input_reference": input_reference,
        "machine_checks": checks,
        "automatic_result": automatic_result,
        "required_human_checks": required_human or [],
        "evidence": list(dict.fromkeys(trial_evidence)),
    }
    correlation_error = validator._correlation_requirement_error(trial)
    if automatic_result == "pass" and correlation_error is not None:
        requirement = validator.RECOVERY_CORRELATION_REQUIREMENTS.get(case_id)
        if requirement is not None:
            for check in checks:
                if check["check_id"] == requirement["check_id"]:
                    check["status"] = "unverifiable"
                    check["observed"] = "unavailable"
                    check["expected"] = correlation_error
                    break
        trial["automatic_result"] = _automatic_result(checks, pass_supported)
    return basis, trial


def validate_candidate(result_path: Path, records: tuple[dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    result_path = result_path.resolve()
    result_set, evaluation, _ = _load_result_context(result_path)
    evaluation_path = result_path.parent / result_set["evaluation_path"]
    voice_path = evaluation_path.parent / evaluation["voice_evaluation"]["path"]
    with tempfile.TemporaryDirectory(prefix="issue196-collector-") as raw_directory:
        directory = Path(raw_directory)
        candidate = directory / result_path.name
        shutil.copy2(result_path, candidate)
        shutil.copy2(evaluation_path, directory / evaluation_path.name)
        shutil.copy2(voice_path, directory / voice_path.name)
        with candidate.open("a", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return validator.validate_pair(candidate)


def append_records(result_path: Path, records: tuple[dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    result_path = result_path.resolve()
    sources = records[0].get("sources", [])
    durable_sources = [
        source
        for source in sources
        if source.startswith(("repo:", "https://", "http://"))
    ]
    for artifact in (source for source in sources if source.startswith("artifact:")):
        match = re.search(r"[?&#]sha256=([0-9a-f]{64})(?:[&#]|$)", artifact)
        digest = match.group(1) if match else None
        if digest is None or not any(
            re.search(rf"[?&#]sha256={digest}(?:[&#]|$)", source)
            for source in durable_sources
        ):
            raise CollectionError(
                f"external artifact {artifact} requires a durable --source with the same sha256"
            )
    payload = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        for record in records
    ).encode("utf-8")
    with result_path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0, 2)
        original_size = stream.tell()
        validate_candidate(result_path, records)
        try:
            stream.write(payload)
            stream.flush()
            stream.seek(0, 2)
            if stream.tell() != original_size + len(payload):
                raise CollectionError("incomplete result JSONL append")
            os.fsync(stream.fileno())
            return validator.validate_pair(result_path)
        except Exception:
            stream.seek(original_size)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--runner-record", type=Path, required=True)
    parser.add_argument("--checks", type=Path, help="optional machine-check result JSON")
    parser.add_argument(
        "--suite",
        required=True,
        choices=("part", "recovery", "voice", "voice_issue194_regression"),
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--environment", required=True, choices=("mock", "sim", "real"))
    parser.add_argument("--code-sha")
    parser.add_argument("--basis-id")
    parser.add_argument("--trial-id")
    parser.add_argument("--human-approval", action="append", default=[])
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="durable repository reference or URL for externally stored evidence",
    )
    parser.add_argument("--append", action="store_true", help="append after candidate validation")
    args = parser.parse_args(argv)
    try:
        records = build_records(
            result_path=args.results,
            runner_path=args.runner_record,
            checks_path=args.checks,
            suite=args.suite,
            case_id=args.case_id,
            environment=args.environment,
            code_sha=args.code_sha,
            basis_id=args.basis_id,
            trial_id=args.trial_id,
            human_approvals=args.human_approval,
            extra_sources=args.source,
        )
        summary = append_records(args.results, records) if args.append else validate_candidate(
            args.results, records
        )
    except (CollectionError, validator.ArtifactValidationError, OSError, KeyError) as exc:
        print(f"collection failed: {exc}", file=sys.stderr)
        return 1
    if not args.append:
        for record in records:
            print(json.dumps(record, ensure_ascii=False, indent=2))
    mode = "appended" if args.append else "validated preview"
    print(
        f"{mode}: {records[1]['trial_id']} result={records[1]['automatic_result']} "
        f"trials={summary['trial_count']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
