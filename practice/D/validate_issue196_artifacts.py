#!/usr/bin/env python3
"""Validate version-pinned Issue #196 evaluation/result artifact pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


class ArtifactValidationError(ValueError):
    """Raised when an evaluation/result pair is not reproducible."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_fields(record: dict[str, Any], fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise ArtifactValidationError(f"{label} missing required fields: {missing}")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            raise ArtifactValidationError(f"{path.name}:{line_number} is blank")
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ArtifactValidationError(f"{path.name}:{line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise ArtifactValidationError(f"{path.name}:{line_number} must be an object")
        records.append(record)
    if not records:
        raise ArtifactValidationError(f"{path.name} is empty")
    return records


def _suite_versions(evaluation: dict[str, Any]) -> dict[str, str]:
    return {
        "part": evaluation["suites"]["part"]["suite_version"],
        "recovery": evaluation["suites"]["recovery"]["suite_version"],
        "voice": evaluation["voice_evaluation"]["evaluation_set_version"],
        "voice_issue194_regression": evaluation["voice_evaluation"][
            "issue_194_regression_version"
        ],
    }


def _find_case(cases: list[dict[str, Any]], key: str, value: str, suite: str) -> dict[str, Any]:
    matches = [case for case in cases if case.get(key) == value]
    if len(matches) != 1:
        raise ArtifactValidationError(f"unknown or duplicate {suite} case_id: {value}")
    return matches[0]


def _case_requirements(
    evaluation: dict[str, Any],
    voice_evaluation: dict[str, Any],
    suite: str,
    case_id: str,
) -> tuple[list[str] | None, list[str] | None]:
    if suite == "part":
        case = _find_case(evaluation["suites"]["part"]["cases"], "case_id", case_id, suite)
        machine = evaluation["suites"]["part"]["machine_check_requirements"].get(case_id)
        if not isinstance(machine, list) or not machine:
            raise ArtifactValidationError(f"part case {case_id} has no machine check mapping")
        return machine, case["required_human_checks"]
    if suite == "recovery":
        case = _find_case(
            evaluation["suites"]["recovery"]["cases"], "case_id", case_id, suite
        )
        return case["required_machine_checks"], case["required_human_checks"]
    if suite == "voice":
        _find_case(voice_evaluation["test_cases"], "case_id", case_id, suite)
        return None, None
    if suite == "voice_issue194_regression":
        _find_case(
            voice_evaluation["issue_194_regression"]["scenarios"],
            "scenario_id",
            case_id,
            suite,
        )
        return None, None
    raise ArtifactValidationError(f"unknown suite: {suite}")


def _validate_machine_checks(
    trial: dict[str, Any], required_machine: list[str] | None
) -> None:
    checks = trial["machine_checks"]
    if not isinstance(checks, list):
        raise ArtifactValidationError(f"trial {trial['trial_id']} machine_checks must be a list")
    allowed_statuses = {"not_evaluated", "pass", "fail", "unverifiable", "not_applicable"}
    by_id: dict[str, dict[str, Any]] = {}
    for position, check in enumerate(checks, 1):
        if not isinstance(check, dict):
            raise ArtifactValidationError(
                f"trial {trial['trial_id']} machine check {position} must be an object"
            )
        _require_fields(
            check,
            ["check_id", "status", "observed", "expected", "evidence"],
            f"trial {trial['trial_id']} machine check {position}",
        )
        check_id = check["check_id"]
        if not isinstance(check_id, str) or not check_id:
            raise ArtifactValidationError(f"trial {trial['trial_id']} has invalid check_id")
        if check_id in by_id:
            raise ArtifactValidationError(
                f"trial {trial['trial_id']} has duplicate machine check: {check_id}"
            )
        if check["status"] not in allowed_statuses:
            raise ArtifactValidationError(
                f"trial {trial['trial_id']} machine check {check_id} has invalid status"
            )
        if not check["evidence"]:
            raise ArtifactValidationError(
                f"trial {trial['trial_id']} machine check {check_id} has empty evidence"
            )
        by_id[check_id] = check

    if required_machine is None:
        return
    actual_ids = set(by_id)
    required_ids = set(required_machine)
    if actual_ids != required_ids:
        missing = sorted(required_ids - actual_ids)
        unexpected = sorted(actual_ids - required_ids)
        raise ArtifactValidationError(
            f"trial {trial['trial_id']} machine check set mismatch: "
            f"missing={missing}, unexpected={unexpected}"
        )
    if trial["automatic_result"] != "pass":
        return
    for check_id in required_machine:
        check = by_id[check_id]
        if check["status"] != "pass":
            raise ArtifactValidationError(
                f"trial {trial['trial_id']} pass requires {check_id} status=pass"
            )
        if check["observed"] is None or check["expected"] is None:
            raise ArtifactValidationError(
                f"trial {trial['trial_id']} pass requires observed and expected for {check_id}"
            )


def _validate_human_checks(trial: dict[str, Any], required_human: list[str] | None) -> None:
    actual = trial["required_human_checks"]
    if not isinstance(actual, list) or any(not isinstance(value, str) or not value for value in actual):
        raise ArtifactValidationError(
            f"trial {trial['trial_id']} required_human_checks must be non-empty strings"
        )
    if len(actual) != len(set(actual)):
        raise ArtifactValidationError(
            f"trial {trial['trial_id']} has duplicate required human checks"
        )
    if required_human is not None and set(actual) != set(required_human):
        missing = sorted(set(required_human) - set(actual))
        unexpected = sorted(set(actual) - set(required_human))
        raise ArtifactValidationError(
            f"trial {trial['trial_id']} human check set mismatch: "
            f"missing={missing}, unexpected={unexpected}"
        )


def validate_pair(result_path: Path) -> dict[str, Any]:
    result_path = result_path.resolve()
    records = _load_jsonl(result_path)
    result_set = records[0]
    if result_set.get("record_type") != "result_set":
        raise ArtifactValidationError("the first record must be result_set")
    if sum(record.get("record_type") == "result_set" for record in records) != 1:
        raise ArtifactValidationError("the result file must contain exactly one result_set")

    evaluation_name = result_set.get("evaluation_path")
    if not isinstance(evaluation_name, str) or Path(evaluation_name).name != evaluation_name:
        raise ArtifactValidationError("evaluation_path must be a sibling file name")
    evaluation_path = result_path.parent / evaluation_name
    if not evaluation_path.is_file():
        raise ArtifactValidationError(f"evaluation file does not exist: {evaluation_name}")
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))

    version = evaluation.get("evaluation_version")
    expected_evaluation_name = f"issue196_evaluation.v{version}.json"
    expected_result_name = f"issue196_results.v{version}.jsonl"
    if evaluation_path.name != expected_evaluation_name:
        raise ArtifactValidationError(
            f"evaluation filename/version mismatch: expected {expected_evaluation_name}"
        )
    if result_path.name != expected_result_name:
        raise ArtifactValidationError(
            f"result filename/version mismatch: expected {expected_result_name}"
        )

    roles = evaluation["artifact_roles"]
    if roles.get("evaluation_definition") != evaluation_path.name:
        raise ArtifactValidationError("artifact_roles.evaluation_definition mismatch")
    if roles.get("execution_results") != result_path.name:
        raise ArtifactValidationError("artifact_roles.execution_results mismatch")
    if evaluation["result_jsonl"].get("path") != result_path.name:
        raise ArtifactValidationError("result_jsonl.path mismatch")

    actual_evaluation_sha = sha256_file(evaluation_path)
    result_set_required = evaluation["result_jsonl"]["record_types"]["result_set"][
        "required"
    ]
    _require_fields(result_set, result_set_required, "result_set")
    if result_set["schema_version"] != evaluation["schema_version"]:
        raise ArtifactValidationError("result_set schema_version mismatch")
    if result_set["evaluation_version"] != version:
        raise ArtifactValidationError("result_set evaluation_version mismatch")
    if result_set["result_set_id"] != f"issue196-{version}":
        raise ArtifactValidationError("result_set result_set_id/version mismatch")
    if result_set["evaluation_sha256"] != actual_evaluation_sha:
        raise ArtifactValidationError("result_set evaluation_sha256 mismatch")
    expected_suites = _suite_versions(evaluation)
    if result_set["suite_versions"] != expected_suites:
        raise ArtifactValidationError("result_set suite_versions mismatch")
    if "status" in result_set or "trial_count" in result_set:
        raise ArtifactValidationError("result_set must not contain mutable summaries")

    voice = evaluation["voice_evaluation"]
    voice_path = evaluation_path.parent / voice["path"]
    if not voice_path.is_file():
        raise ArtifactValidationError(f"referenced voice evaluation missing: {voice['path']}")
    if voice.get("sha256") != sha256_file(voice_path):
        raise ArtifactValidationError("referenced voice evaluation sha256 mismatch")
    voice_evaluation = json.loads(voice_path.read_text(encoding="utf-8"))

    definitions = evaluation["result_jsonl"]["record_types"]
    allowed_types = set(definitions)
    trial_ids: set[str] = set()
    for index, record in enumerate(records[1:], 2):
        record_type = record.get("record_type")
        if record_type not in allowed_types - {"result_set"}:
            raise ArtifactValidationError(
                f"record {index} has unsupported record_type: {record_type!r}"
            )
        _require_fields(record, definitions[record_type]["required"], f"record {index}")
        if record.get("schema_version") != result_set["schema_version"]:
            raise ArtifactValidationError(f"record {index} schema_version mismatch")
        if record_type != "trial":
            continue
        if record["trial_id"] in trial_ids:
            raise ArtifactValidationError(f"duplicate trial_id: {record['trial_id']}")
        trial_ids.add(record["trial_id"])
        if record["result_set_id"] != result_set["result_set_id"]:
            raise ArtifactValidationError(f"trial {record['trial_id']} result_set_id mismatch")
        if record["evaluation_version"] != result_set["evaluation_version"]:
            raise ArtifactValidationError(
                f"trial {record['trial_id']} evaluation_version mismatch"
            )
        if record["evaluation_sha256"] != result_set["evaluation_sha256"]:
            raise ArtifactValidationError(
                f"trial {record['trial_id']} evaluation_sha256 mismatch"
            )
        suite = record["suite"]
        if suite not in result_set["suite_versions"]:
            raise ArtifactValidationError(f"trial {record['trial_id']} unknown suite: {suite}")
        if record["suite_version"] != result_set["suite_versions"][suite]:
            raise ArtifactValidationError(
                f"trial {record['trial_id']} suite_version mismatch"
            )
        if record["automatic_result"] not in evaluation["result_jsonl"][
            "automatic_result_values"
        ]:
            raise ArtifactValidationError(
                f"trial {record['trial_id']} has invalid automatic_result"
            )
        required_machine, required_human = _case_requirements(
            evaluation, voice_evaluation, suite, record["case_id"]
        )
        _validate_machine_checks(record, required_machine)
        _validate_human_checks(record, required_human)

    return {
        "evaluation": evaluation_path.name,
        "results": result_path.name,
        "evaluation_version": version,
        "evaluation_sha256": actual_evaluation_sha,
        "trial_count": len(trial_ids),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="*", type=Path)
    args = parser.parse_args()
    paths = args.results or sorted(Path(__file__).parent.glob("issue196_results.v*.jsonl"))
    if not paths:
        raise ArtifactValidationError("no versioned Issue #196 result files found")
    for path in paths:
        summary = validate_pair(path)
        print(
            "OK "
            f"{summary['evaluation_version']} "
            f"sha256={summary['evaluation_sha256']} "
            f"trials={summary['trial_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
