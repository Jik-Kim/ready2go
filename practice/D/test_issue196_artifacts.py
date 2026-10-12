from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
S10_MACHINE_CHECKS = [
    "explicit_recovery_request_linked",
    "actual_stop_confirmed",
    "safe_force_confirmed",
    "fresh_sensor_and_communication_confirmed",
    "controller_ready_and_recoverable",
    "b_recovery_result_passed",
    "c_unlock_after_b_result",
    "automatic_resume_count_zero",
]
S10_HUMAN_CHECKS = ["H-STOP-01", "H-AREA-01", "H-HW-01"]
SPEC = importlib.util.spec_from_file_location(
    "validate_issue196_artifacts", HERE / "validate_issue196_artifacts.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_pair(tmp_path: Path, version: str = "0.5-draft") -> tuple[Path, dict, dict]:
    source_evaluation = json.loads(
        (HERE / "issue196_evaluation.v0.5-draft.json").read_text(encoding="utf-8")
    )
    evaluation = copy.deepcopy(source_evaluation)
    evaluation_name = f"issue196_evaluation.v{version}.json"
    result_name = f"issue196_results.v{version}.jsonl"
    evaluation["evaluation_version"] = version
    evaluation["artifact_roles"]["evaluation_definition"] = evaluation_name
    evaluation["artifact_roles"]["execution_results"] = result_name
    evaluation["result_jsonl"]["path"] = result_name
    evaluation["basis_policy"]["record_location"] = f"{result_name} record_type=basis"
    evaluation["boundaries"] = [
        value.replace("issue196_results.v0.5-draft.jsonl", result_name)
        for value in evaluation["boundaries"]
    ]
    shutil.copy2(HERE / "issue20_voice_evaluation.json", tmp_path)
    evaluation_path = tmp_path / evaluation_name
    _write_json(evaluation_path, evaluation)
    result_set = {
        "record_type": "result_set",
        "schema_version": evaluation["schema_version"],
        "result_set_id": f"issue196-{version}",
        "evaluation_path": evaluation_name,
        "evaluation_version": version,
        "evaluation_sha256": _sha(evaluation_path),
        "suite_versions": VALIDATOR._suite_versions(evaluation),
    }
    result_path = tmp_path / result_name
    result_path.write_text(json.dumps(result_set) + "\n", encoding="utf-8")
    return result_path, evaluation, result_set


def _append_trial(result_path: Path, result_set: dict, **updates: object) -> None:
    basis_updates = updates.pop("basis_updates", {})
    include_basis = updates.pop("include_basis", True)
    basis = {
        "record_type": "basis",
        "schema_version": "1.1",
        "basis_id": "basis-1",
        "captured_at": "2026-10-12T00:00:00Z",
        "environment": "mock",
        "code_sha": "0" * 40,
        "sources": [],
        "human_approvals": [],
    }
    basis.update(basis_updates)
    trial = {
        "record_type": "trial",
        "schema_version": "1.1",
        "trial_id": "trial-1",
        "result_set_id": result_set["result_set_id"],
        "evaluation_version": result_set["evaluation_version"],
        "evaluation_sha256": result_set["evaluation_sha256"],
        "suite": "recovery",
        "suite_version": result_set["suite_versions"]["recovery"],
        "case_id": "S10",
        "basis_id": "basis-1",
        "environment": "mock",
        "started_at": "2026-10-12T00:00:01Z",
        "correlation": {},
        "input_reference": {},
        "machine_checks": [
            {
                "check_id": check_id,
                "status": "pass",
                "observed": True,
                "expected": True,
                "evidence": [f"evidence-{check_id}"],
            }
            for check_id in S10_MACHINE_CHECKS
        ],
        "automatic_result": "pass",
        "required_human_checks": S10_HUMAN_CHECKS,
        "evidence": ["mock-evidence"],
    }
    trial.update(updates)
    with result_path.open("a", encoding="utf-8") as stream:
        if include_basis:
            stream.write(json.dumps(basis) + "\n")
        stream.write(json.dumps(trial) + "\n")


def test_current_versioned_pair_passes() -> None:
    summary = VALIDATOR.validate_pair(HERE / "issue196_results.v0.5-draft.jsonl")
    assert summary["evaluation_version"] == "0.5-draft"
    assert summary["trial_count"] == 0


def test_matching_trial_passes(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(result_path, result_set)
    assert VALIDATOR.validate_pair(result_path)["trial_count"] == 1


def test_mixed_evaluation_version_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(result_path, result_set, evaluation_version="0.6-draft")
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="evaluation_version"):
        VALIDATOR.validate_pair(result_path)


def test_wrong_suite_version_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(
        result_path,
        result_set,
        suite="recovery",
        suite_version=result_set["suite_versions"]["part"],
    )
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="suite_version"):
        VALIDATOR.validate_pair(result_path)


def test_s10_missing_machine_check_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    checks = [
        {
            "check_id": check_id,
            "status": "pass",
            "observed": True,
            "expected": True,
            "evidence": ["evidence"],
        }
        for check_id in S10_MACHINE_CHECKS[:-1]
    ]
    _append_trial(result_path, result_set, machine_checks=checks)
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="machine check set mismatch"):
        VALIDATOR.validate_pair(result_path)


@pytest.mark.parametrize("status", ["fail", "unverifiable"])
def test_s10_nonpassing_machine_check_fails(tmp_path: Path, status: str) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    checks = [
        {
            "check_id": check_id,
            "status": status if check_id == S10_MACHINE_CHECKS[0] else "pass",
            "observed": True,
            "expected": True,
            "evidence": ["evidence"],
        }
        for check_id in S10_MACHINE_CHECKS
    ]
    _append_trial(result_path, result_set, machine_checks=checks)
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="status=pass"):
        VALIDATOR.validate_pair(result_path)


def test_s10_missing_human_check_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(
        result_path,
        result_set,
        required_human_checks=S10_HUMAN_CHECKS[:-1],
    )
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="human check set mismatch"):
        VALIDATOR.validate_pair(result_path)


def test_s10_missing_observed_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    checks = [
        {
            "check_id": check_id,
            "status": "pass",
            "expected": True,
            "evidence": ["evidence"],
        }
        if check_id == S10_MACHINE_CHECKS[0]
        else {
            "check_id": check_id,
            "status": "pass",
            "observed": True,
            "expected": True,
            "evidence": ["evidence"],
        }
        for check_id in S10_MACHINE_CHECKS
    ]
    _append_trial(result_path, result_set, machine_checks=checks)
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="missing required fields"):
        VALIDATOR.validate_pair(result_path)


def test_s10_empty_evidence_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    checks = [
        {
            "check_id": check_id,
            "status": "pass",
            "observed": True,
            "expected": True,
            "evidence": [] if check_id == S10_MACHINE_CHECKS[0] else ["evidence"],
        }
        for check_id in S10_MACHINE_CHECKS
    ]
    _append_trial(result_path, result_set, machine_checks=checks)
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="empty evidence"):
        VALIDATOR.validate_pair(result_path)


@pytest.mark.parametrize("field", ["observed", "expected"])
def test_s10_blank_observed_or_expected_fails(tmp_path: Path, field: str) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    checks = copy.deepcopy(
        [
            {
                "check_id": check_id,
                "status": "pass",
                "observed": True,
                "expected": True,
                "evidence": ["evidence"],
            }
            for check_id in S10_MACHINE_CHECKS
        ]
    )
    checks[0][field] = ""
    _append_trial(result_path, result_set, machine_checks=checks)
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="non-empty observed"):
        VALIDATOR.validate_pair(result_path)


def test_s10_blank_machine_evidence_item_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    checks = [
        {
            "check_id": check_id,
            "status": "pass",
            "observed": True,
            "expected": True,
            "evidence": [""] if check_id == S10_MACHINE_CHECKS[0] else ["evidence"],
        }
        for check_id in S10_MACHINE_CHECKS
    ]
    _append_trial(result_path, result_set, machine_checks=checks)
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="non-empty strings"):
        VALIDATOR.validate_pair(result_path)


def test_s10_non_list_machine_evidence_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    checks = [
        {
            "check_id": check_id,
            "status": "pass",
            "observed": True,
            "expected": True,
            "evidence": "not-a-list"
            if check_id == S10_MACHINE_CHECKS[0]
            else ["evidence"],
        }
        for check_id in S10_MACHINE_CHECKS
    ]
    _append_trial(result_path, result_set, machine_checks=checks)
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="evidence must be a list"):
        VALIDATOR.validate_pair(result_path)


def test_pass_trial_blank_evidence_item_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(result_path, result_set, evidence=[""])
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="non-empty strings"):
        VALIDATOR.validate_pair(result_path)


def test_unknown_case_id_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(result_path, result_set, case_id="S999")
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="unknown or duplicate"):
        VALIDATOR.validate_pair(result_path)


def test_part_case_machine_mapping_is_enforced(tmp_path: Path) -> None:
    result_path, evaluation, result_set = _make_pair(tmp_path)
    case_id = "A-01"
    required = evaluation["suites"]["part"]["machine_check_requirements"][case_id]
    human = next(
        case["required_human_checks"]
        for case in evaluation["suites"]["part"]["cases"]
        if case["case_id"] == case_id
    )
    checks = [
        {
            "check_id": check_id,
            "status": "pass",
            "observed": True,
            "expected": True,
            "evidence": ["evidence"],
        }
        for check_id in required[:-1]
    ]
    _append_trial(
        result_path,
        result_set,
        suite="part",
        suite_version=result_set["suite_versions"]["part"],
        case_id=case_id,
        machine_checks=checks,
        required_human_checks=human,
    )
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="machine check set mismatch"):
        VALIDATOR.validate_pair(result_path)


def _voice_check(status: str = "pass") -> dict[str, object]:
    return {
        "check_id": "intent_match",
        "status": status,
        "observed": "find_item" if status == "pass" else "cancel",
        "expected": "find_item",
        "evidence": ["observed-intent-log"],
    }


def test_voice_failed_check_cannot_be_recorded_as_pass(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(
        result_path,
        result_set,
        suite="voice",
        suite_version=result_set["suite_versions"]["voice"],
        case_id="TC-001",
        machine_checks=[_voice_check("fail")],
        required_human_checks=[],
    )
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="status=pass"):
        VALIDATOR.validate_pair(result_path)


def test_voice_empty_checks_cannot_be_recorded_as_pass(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(
        result_path,
        result_set,
        suite="voice",
        suite_version=result_set["suite_versions"]["voice"],
        case_id="TC-001",
        machine_checks=[],
        required_human_checks=[],
    )
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="non-empty machine_checks"):
        VALIDATOR.validate_pair(result_path)


def test_voice_empty_trial_evidence_cannot_be_recorded_as_pass(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(
        result_path,
        result_set,
        suite="voice",
        suite_version=result_set["suite_versions"]["voice"],
        case_id="TC-001",
        machine_checks=[_voice_check()],
        required_human_checks=[],
        evidence=[],
    )
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="empty evidence"):
        VALIDATOR.validate_pair(result_path)


def test_voice_pass_is_held_until_explicit_grader_is_connected(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(
        result_path,
        result_set,
        suite="voice",
        suite_version=result_set["suite_versions"]["voice"],
        case_id="TC-001",
        machine_checks=[_voice_check()],
        required_human_checks=[],
    )
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="automatic pass is unsupported"):
        VALIDATOR.validate_pair(result_path)


def test_voice_nonpassing_result_is_allowed_without_check_mapping(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(
        result_path,
        result_set,
        suite="voice",
        suite_version=result_set["suite_versions"]["voice"],
        case_id="TC-001",
        machine_checks=[_voice_check("fail")],
        automatic_result="fail",
        required_human_checks=[],
    )
    assert VALIDATOR.validate_pair(result_path)["trial_count"] == 1


def test_issue194_voice_pass_is_held_until_explicit_grader_is_connected(
    tmp_path: Path,
) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(
        result_path,
        result_set,
        suite="voice_issue194_regression",
        suite_version=result_set["suite_versions"]["voice_issue194_regression"],
        case_id="UX194-001",
        machine_checks=[_voice_check()],
        required_human_checks=[],
    )
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="automatic pass is unsupported"):
        VALIDATOR.validate_pair(result_path)


def test_trial_with_missing_basis_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(result_path, result_set, include_basis=False)
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="missing basis_id"):
        VALIDATOR.validate_pair(result_path)


def test_duplicate_basis_id_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(result_path, result_set)
    duplicate = {
        "record_type": "basis",
        "schema_version": "1.1",
        "basis_id": "basis-1",
        "captured_at": "2026-10-12T00:00:02Z",
        "environment": "mock",
        "code_sha": "1" * 40,
        "sources": [],
        "human_approvals": [],
    }
    with result_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(duplicate) + "\n")
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="duplicate basis_id"):
        VALIDATOR.validate_pair(result_path)


def test_blank_basis_id_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(result_path, result_set, basis_updates={"basis_id": ""})
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="invalid basis_id"):
        VALIDATOR.validate_pair(result_path)


def test_unreferenced_basis_fails(tmp_path: Path) -> None:
    result_path, _, _ = _make_pair(tmp_path)
    basis = {
        "record_type": "basis",
        "schema_version": "1.1",
        "basis_id": "orphan-basis",
        "captured_at": "2026-10-12T00:00:00Z",
        "environment": "mock",
        "code_sha": "0" * 40,
        "sources": [],
        "human_approvals": [],
    }
    with result_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(basis) + "\n")
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="unreferenced basis_id"):
        VALIDATOR.validate_pair(result_path)


def test_invalid_basis_environment_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(result_path, result_set, basis_updates={"environment": "laboratory"})
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="invalid environment"):
        VALIDATOR.validate_pair(result_path)


def test_invalid_basis_code_sha_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(result_path, result_set, basis_updates={"code_sha": "short-sha"})
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="invalid code_sha"):
        VALIDATOR.validate_pair(result_path)


def test_trial_environment_must_match_basis(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    _append_trial(result_path, result_set, environment="real")
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="does not match basis"):
        VALIDATOR.validate_pair(result_path)


def test_changed_definition_with_stale_hash_fails(tmp_path: Path) -> None:
    result_path, evaluation, _ = _make_pair(tmp_path)
    evaluation["status"] = "changed-without-version-bump"
    _write_json(tmp_path / "issue196_evaluation.v0.5-draft.json", evaluation)
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="evaluation_sha256"):
        VALIDATOR.validate_pair(result_path)


def test_changed_voice_definition_with_stale_hash_fails(tmp_path: Path) -> None:
    result_path, _, _ = _make_pair(tmp_path)
    voice_path = tmp_path / "issue20_voice_evaluation.json"
    voice_path.write_bytes(voice_path.read_bytes() + b"\n")
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="voice evaluation sha256"):
        VALIDATOR.validate_pair(result_path)


def test_new_version_uses_independent_pair(tmp_path: Path) -> None:
    old_result, _, _ = _make_pair(tmp_path, "0.5-draft")
    new_result, _, _ = _make_pair(tmp_path, "0.6-draft")
    assert VALIDATOR.validate_pair(old_result)["evaluation_version"] == "0.5-draft"
    assert VALIDATOR.validate_pair(new_result)["evaluation_version"] == "0.6-draft"


def test_second_result_set_fails(tmp_path: Path) -> None:
    result_path, _, result_set = _make_pair(tmp_path)
    with result_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(result_set) + "\n")
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="exactly one result_set"):
        VALIDATOR.validate_pair(result_path)


def test_unsupported_record_type_fails(tmp_path: Path) -> None:
    result_path, _, _ = _make_pair(tmp_path)
    with result_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"record_type": "summary"}) + "\n")
    with pytest.raises(VALIDATOR.ArtifactValidationError, match="unsupported record_type"):
        VALIDATOR.validate_pair(result_path)
