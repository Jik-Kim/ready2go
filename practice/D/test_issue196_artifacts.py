from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
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
        "machine_checks": [],
        "automatic_result": "not_evaluated",
        "required_human_checks": [],
        "evidence": ["mock-evidence"],
    }
    trial.update(updates)
    with result_path.open("a", encoding="utf-8") as stream:
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
