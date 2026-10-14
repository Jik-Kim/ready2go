from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SPEC = importlib.util.spec_from_file_location(
    "collect_issue196_results", HERE / "collect_issue196_results.py"
)
assert SPEC and SPEC.loader
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)

S10_CHECKS = [
    "explicit_recovery_request_linked",
    "actual_stop_confirmed",
    "safe_force_confirmed",
    "fresh_sensor_and_communication_confirmed",
    "controller_ready_and_recoverable",
    "b_recovery_result_passed",
    "c_unlock_after_b_result",
    "automatic_resume_count_zero",
]
MISMATCH_CASES = {
    "S14": ("halt_event_id", "active_and_referenced_ids_separated"),
    "S23": ("boot_id", "previous_boot_question_invalidated"),
    "S29": ("question_id", "active_and_referenced_ids_separated"),
}
RUNNER_CURRENT_IDS = {
    "halt_event_id": "halt-1",
    "question_id": "question-1",
    "boot_id": "boot-current",
}


def _copy_pair(tmp_path: Path) -> Path:
    for name in (
        "issue196_evaluation.v0.5-draft.json",
        "issue196_results.v0.5-draft.jsonl",
        "issue20_voice_evaluation.json",
    ):
        shutil.copy2(HERE / name, tmp_path / name)
    return tmp_path / "issue196_results.v0.5-draft.jsonl"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _durable_source(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"https://evidence.example/{path.name}?sha256={digest}"


def _init_git_repo(path: Path) -> str:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Issue196 Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-qm", "test evidence"], check=True
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _runner(
    path: Path,
    environment: str = "mock",
    code_sha: str | None = None,
    stopped_at: str | None = None,
) -> Path:
    halt = {"event_id": "halt-1", "question_id": "question-1"}
    if stopped_at is not None:
        halt["stopped_at"] = stopped_at
    run = {
        "run_id": "run-1",
        "task_id": "find_item",
        "backend": environment,
        "started_at": "2026-10-12T00:00:00Z",
        "inputs": {"target": "eraser"},
        "overall_status": "COMPLETED",
        "halts": [halt],
    }
    if code_sha is not None:
        run["code_sha"] = code_sha
    _write_json(
        path,
        {
            "run": run,
            "steps": [],
        },
    )
    return path


def test_missing_required_checks_become_inconclusive(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    original = result_path.read_bytes()
    basis, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "runner.json"),
        checks_path=None,
        suite="recovery",
        case_id="S10",
        environment="mock",
        code_sha="1" * 40,
    )
    assert basis["code_sha"] == "1" * 40
    assert trial["automatic_result"] == "inconclusive"
    assert {check["check_id"] for check in trial["machine_checks"]} == set(S10_CHECKS)
    assert {check["status"] for check in trial["machine_checks"]} == {"unverifiable"}
    assert trial["correlation"] == {
        "run_id": "run-1",
        "halt_event_id": "halt-1",
        "question_id": "question-1",
    }
    COLLECTOR.validate_candidate(result_path, (basis, trial))
    assert result_path.read_bytes() == original


def test_complete_machine_results_append_as_pass(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    checks_path = tmp_path / "checks.json"
    runner_path = _runner(tmp_path / "runner.json")
    check_digest = "0" * 64
    _write_json(
        checks_path,
        {
            "machine_checks": {
                check_id: {
                    "status": "pass",
                    "observed": True,
                    "expected": True,
                    "evidence": [
                        f"https://evidence.example/S10?sha256={check_digest}#{check_id}"
                    ],
                }
                for check_id in S10_CHECKS
            }
        },
    )
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=checks_path,
        suite="recovery",
        case_id="S10",
        environment="mock",
        code_sha="2" * 40,
        extra_sources=[_durable_source(runner_path), _durable_source(checks_path)],
    )
    assert records[1]["automatic_result"] == "pass"
    summary = COLLECTOR.append_records(result_path, records)
    assert summary["trial_count"] == 1
    assert len(result_path.read_text(encoding="utf-8").splitlines()) == 3


def test_voice_pass_is_collected_as_inconclusive(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    checks_path = tmp_path / "checks.json"
    _write_json(
        checks_path,
        {
            "machine_checks": {
                "intent_match": {
                    "status": "pass",
                    "observed": "find_item",
                    "expected": "find_item",
                }
            }
        },
    )
    _, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "runner.json"),
        checks_path=checks_path,
        suite="voice",
        case_id="TC-001",
        environment="mock",
        code_sha="3" * 40,
    )
    assert trial["automatic_result"] == "inconclusive"


def test_runner_environment_mismatch_fails(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    with pytest.raises(COLLECTOR.CollectionError, match="does not match"):
        COLLECTOR.build_records(
            result_path=result_path,
            runner_path=_runner(tmp_path / "runner.json", "real"),
            checks_path=None,
            suite="recovery",
            case_id="S10",
            environment="mock",
            code_sha="4" * 40,
        )


def test_runner_fallback_jsonl_is_loaded(tmp_path: Path) -> None:
    path = tmp_path / "runner.jsonl"
    lines = [
        {"collection": "runs", "doc": {"run_id": "run-1", "started_at": "start"}},
        {"collection": "steps", "doc": {"run_id": "run-1", "seq": 1, "status": "SUCCESS"}},
        {
            "collection": "runs",
            "doc": {"run_id": "run-1", "started_at": "start", "overall_status": "COMPLETED"},
        },
    ]
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    record = COLLECTOR.load_runner_record(path)
    assert record["run"]["overall_status"] == "COMPLETED"
    assert record["steps"][0]["seq"] == 1


def test_runner_fallback_jsonl_preserves_records_around_truncated_line(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runner.jsonl"
    lines = [
        json.dumps(
            {
                "collection": "runs",
                "doc": {"run_id": "run-1", "started_at": "start"},
            }
        ),
        '{"collection":"steps","doc":',
        json.dumps(
            {
                "collection": "steps",
                "doc": {"run_id": "run-1", "seq": 1, "status": "SUCCESS"},
            }
        ),
        json.dumps(
            {
                "collection": "runs",
                "doc": {"run_id": "run-1", "overall_status": "COMPLETED"},
            }
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    record = COLLECTOR.load_runner_record(path)
    assert record["run"]["overall_status"] == "COMPLETED"
    assert record["steps"] == [
        {"run_id": "run-1", "seq": 1, "status": "SUCCESS"}
    ]


def test_invalid_measurement_evidence_fails(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    checks_path = tmp_path / "checks.json"
    _write_json(checks_path, {"machine_checks": {}, "evidence": "not-a-list"})
    with pytest.raises(COLLECTOR.CollectionError, match="list of non-empty strings"):
        COLLECTOR.build_records(
            result_path=result_path,
            runner_path=_runner(tmp_path / "runner.json"),
            checks_path=checks_path,
            suite="recovery",
            case_id="S10",
            environment="mock",
            code_sha="5" * 40,
        )


def test_code_sha_comes_from_test_run_and_is_required(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    basis, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "with-sha.json", code_sha="6" * 40),
        checks_path=None,
        suite="part",
        case_id="C-03",
        environment="mock",
    )
    assert basis["code_sha"] == "6" * 40
    assert trial["basis_id"] == basis["basis_id"]

    with pytest.raises(COLLECTOR.CollectionError, match="test-run code SHA is missing"):
        COLLECTOR.build_records(
            result_path=result_path,
            runner_path=_runner(tmp_path / "without-sha.json"),
            checks_path=None,
            suite="part",
            case_id="C-03",
            environment="mock",
        )


def test_direct_runner_fields_fill_only_provable_checks(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    _, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "runner.json"),
        checks_path=None,
        suite="part",
        case_id="C-03",
        environment="mock",
        code_sha="7" * 40,
    )
    checks = {row["check_id"]: row for row in trial["machine_checks"]}
    assert checks["active_run_id_linked"]["status"] == "unverifiable"
    assert checks["error_notice_linked"]["status"] == "unverifiable"
    assert trial["automatic_result"] == "inconclusive"

    _, recovery_trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(
            tmp_path / "stopped-runner.json",
            stopped_at="2026-10-12T00:00:01Z",
        ),
        checks_path=None,
        suite="recovery",
        case_id="S10",
        environment="mock",
        code_sha="7" * 40,
    )
    recovery_checks = {
        row["check_id"]: row for row in recovery_trial["machine_checks"]
    }
    assert recovery_checks["actual_stop_confirmed"]["status"] == "unverifiable"
    assert recovery_checks["safe_force_confirmed"]["status"] == "unverifiable"


def test_evidence_references_are_portable_and_content_addressed(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    runner_path = _runner(tmp_path / "runner.json")
    basis, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=None,
        suite="part",
        case_id="C-03",
        environment="mock",
        code_sha="8" * 40,
    )
    expected_prefix = "artifact:runner.json?sha256="
    assert basis["sources"][0].startswith(expected_prefix)
    assert str(tmp_path) not in basis["sources"][0]
    assert trial["evidence"][0] == basis["sources"][0]


def test_append_rolls_back_when_post_validation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_path = _copy_pair(tmp_path)
    original_bytes = result_path.read_bytes()
    runner_path = _runner(tmp_path / "runner.json")
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=None,
        suite="part",
        case_id="C-03",
        environment="mock",
        code_sha="9" * 40,
        extra_sources=[_durable_source(runner_path)],
    )
    original_validate = COLLECTOR.validator.validate_pair
    calls = 0

    def fail_second_validation(path: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise COLLECTOR.validator.ArtifactValidationError("post-append failure")
        return original_validate(path)

    monkeypatch.setattr(COLLECTOR.validator, "validate_pair", fail_second_validation)
    with pytest.raises(
        COLLECTOR.validator.ArtifactValidationError, match="post-append failure"
    ):
        COLLECTOR.append_records(result_path, records)
    assert result_path.read_bytes() == original_bytes


def test_pass_without_explicit_evidence_is_downgraded(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    checks_path = tmp_path / "checks.json"
    _write_json(
        checks_path,
        {
            "machine_checks": {
                check_id: {
                    "status": "pass",
                    "observed": True,
                    "expected": True,
                }
                for check_id in S10_CHECKS
            }
        },
    )
    _, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "runner.json"),
        checks_path=checks_path,
        suite="recovery",
        case_id="S10",
        environment="mock",
        code_sha="a" * 40,
    )
    assert trial["automatic_result"] == "inconclusive"
    assert {row["status"] for row in trial["machine_checks"]} == {
        "unverifiable"
    }


@pytest.mark.parametrize("explicit_status", ["fail", None])
def test_failure_without_explicit_evidence_is_downgraded(
    tmp_path: Path, explicit_status: str | None
) -> None:
    result_path = _copy_pair(tmp_path)
    check = {"observed": False, "expected": True}
    if explicit_status is not None:
        check["status"] = explicit_status
    checks_path = tmp_path / "checks.json"
    _write_json(
        checks_path,
        {"machine_checks": {check_id: dict(check) for check_id in S10_CHECKS}},
    )
    _, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "runner.json"),
        checks_path=checks_path,
        suite="recovery",
        case_id="S10",
        environment="mock",
        code_sha="a" * 40,
    )
    assert trial["automatic_result"] == "inconclusive"
    assert {row["status"] for row in trial["machine_checks"]} == {
        "unverifiable"
    }


def test_pass_without_observed_and_expected_is_downgraded(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    checks_path = tmp_path / "checks.json"
    _write_json(
        checks_path,
        {
            "machine_checks": {
                check_id: {
                    "status": "pass",
                    "evidence": [f"https://evidence.example/S10#{check_id}"],
                }
                for check_id in S10_CHECKS
            }
        },
    )
    _, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "runner.json"),
        checks_path=checks_path,
        suite="recovery",
        case_id="S10",
        environment="mock",
        code_sha="a" * 40,
    )
    assert trial["automatic_result"] == "inconclusive"
    assert {row["status"] for row in trial["machine_checks"]} == {
        "unverifiable"
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (("observed", ""), ("expected", []), ("evidence", [])),
)
def test_empty_pass_value_is_downgraded(
    tmp_path: Path, field: str, value: object
) -> None:
    result_path = _copy_pair(tmp_path)
    checks = {
        check_id: {
            "status": "pass",
            "observed": True,
            "expected": True,
            "evidence": [f"https://evidence.example/S10#{check_id}"],
        }
        for check_id in S10_CHECKS
    }
    checks[S10_CHECKS[0]][field] = value
    checks_path = tmp_path / "checks.json"
    _write_json(checks_path, {"machine_checks": checks})
    _, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "runner.json"),
        checks_path=checks_path,
        suite="recovery",
        case_id="S10",
        environment="mock",
        code_sha="f" * 40,
    )
    first = next(
        row for row in trial["machine_checks"] if row["check_id"] == S10_CHECKS[0]
    )
    assert first["status"] == "unverifiable"
    assert trial["automatic_result"] == "inconclusive"


def test_measurement_cannot_override_runner_identity(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    checks_path = tmp_path / "checks.json"
    _write_json(checks_path, {"correlation": {"run_id": "other-run"}})
    with pytest.raises(COLLECTOR.CollectionError, match="correlation.run_id conflicts"):
        COLLECTOR.build_records(
            result_path=result_path,
            runner_path=_runner(tmp_path / "runner.json"),
            checks_path=checks_path,
            suite="part",
            case_id="C-03",
            environment="mock",
            code_sha="b" * 40,
        )

    _write_json(checks_path, {"input_reference": {"task_id": "other-task"}})
    with pytest.raises(
        COLLECTOR.CollectionError, match="input_reference.task_id conflicts"
    ):
        COLLECTOR.build_records(
            result_path=result_path,
            runner_path=_runner(tmp_path / "runner.json"),
            checks_path=checks_path,
            suite="part",
            case_id="C-03",
            environment="mock",
            code_sha="b" * 40,
        )


def test_external_artifact_requires_durable_source_before_append(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    original = result_path.read_bytes()
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "runner.json"),
        checks_path=None,
        suite="part",
        case_id="C-03",
        environment="mock",
        code_sha="c" * 40,
    )
    with pytest.raises(COLLECTOR.CollectionError, match="same sha256"):
        COLLECTOR.append_records(result_path, records)
    assert result_path.read_bytes() == original


@pytest.mark.parametrize("source_state", ["untracked", "modified"])
def test_repository_worktree_evidence_requires_durable_source_before_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_state: str,
) -> None:
    result_path = _copy_pair(tmp_path)
    repository = tmp_path / "evidence-repo"
    repository.mkdir()
    tracked_runner = _runner(repository / "runner.json")
    code_sha = _init_git_repo(repository)
    if source_state == "untracked":
        runner_path = _runner(repository / "untracked-runner.json")
    else:
        runner_path = tracked_runner
        runner = json.loads(runner_path.read_text(encoding="utf-8"))
        runner["run"]["overall_status"] = "FAILED"
        _write_json(runner_path, runner)
    monkeypatch.setattr(COLLECTOR, "REPO_ROOT", repository)
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=None,
        suite="part",
        case_id="C-03",
        environment="mock",
        code_sha=code_sha,
    )
    assert records[0]["sources"][0].startswith("artifact:")
    with pytest.raises(COLLECTOR.CollectionError, match="requires a durable --source"):
        COLLECTOR.append_records(result_path, records)


def test_committed_repository_evidence_records_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_path = _copy_pair(tmp_path)
    repository = tmp_path / "evidence-repo"
    repository.mkdir()
    runner_path = _runner(repository / "runner.json")
    code_sha = _init_git_repo(repository)
    monkeypatch.setattr(COLLECTOR, "REPO_ROOT", repository)
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=None,
        suite="part",
        case_id="C-03",
        environment="mock",
        code_sha=code_sha,
    )
    source = records[0]["sources"][0]
    assert source.startswith("repo:runner.json?")
    assert f"rev={code_sha}" in source
    summary = COLLECTOR.append_records(result_path, records)
    assert summary["trial_count"] == 1


@pytest.mark.parametrize(
    "evidence",
    [
        "https://evidence.example/video.mp4",
        "https://evidence.example/video.mp4?sha256=not-a-digest",
    ],
)
def test_http_evidence_requires_valid_sha256(
    tmp_path: Path, evidence: str
) -> None:
    result_path = _copy_pair(tmp_path)
    runner_path = _runner(tmp_path / "runner.json")
    checks_path = tmp_path / "checks.json"
    _write_json(
        checks_path,
        _s10_pass_checks([evidence]),
    )
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=checks_path,
        suite="recovery",
        case_id="S10",
        environment="mock",
        code_sha="c" * 40,
        extra_sources=[_durable_source(runner_path), _durable_source(checks_path)],
    )
    with pytest.raises(COLLECTOR.CollectionError, match="sha256"):
        COLLECTOR.append_records(result_path, records)


def test_nonexistent_repository_evidence_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_path = _copy_pair(tmp_path)
    repository = tmp_path / "evidence-repo"
    repository.mkdir()
    runner_path = _runner(repository / "runner.json")
    code_sha = _init_git_repo(repository)
    monkeypatch.setattr(COLLECTOR, "REPO_ROOT", repository)
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=None,
        suite="part",
        case_id="C-03",
        environment="mock",
        code_sha=code_sha,
        extra_sources=[f"repo:missing.json?rev={code_sha}&sha256={'0' * 64}"],
    )
    with pytest.raises(COLLECTOR.CollectionError, match="does not exist"):
        COLLECTOR.append_records(result_path, records)


def test_repository_evidence_digest_must_match_git_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_path = _copy_pair(tmp_path)
    repository = tmp_path / "evidence-repo"
    repository.mkdir()
    runner_path = _runner(repository / "runner.json")
    code_sha = _init_git_repo(repository)
    monkeypatch.setattr(COLLECTOR, "REPO_ROOT", repository)
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=None,
        suite="part",
        case_id="C-03",
        environment="mock",
        code_sha=code_sha,
        extra_sources=[f"repo:runner.json?rev={code_sha}&sha256={'0' * 64}"],
    )
    with pytest.raises(COLLECTOR.CollectionError, match="sha256 mismatch"):
        COLLECTOR.append_records(result_path, records)


def test_repository_evidence_revision_must_match_basis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_path = _copy_pair(tmp_path)
    repository = tmp_path / "evidence-repo"
    repository.mkdir()
    runner_path = _runner(repository / "runner.json")
    code_sha = _init_git_repo(repository)
    monkeypatch.setattr(COLLECTOR, "REPO_ROOT", repository)
    digest = hashlib.sha256(runner_path.read_bytes()).hexdigest()
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=None,
        suite="part",
        case_id="C-03",
        environment="mock",
        code_sha=code_sha,
        extra_sources=[f"repo:runner.json?rev={'0' * 40}&sha256={digest}"],
    )
    with pytest.raises(COLLECTOR.CollectionError, match="basis code_sha"):
        COLLECTOR.append_records(result_path, records)


def test_each_external_artifact_requires_matching_durable_source(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    runner_path = _runner(tmp_path / "runner.json")
    checks_path = tmp_path / "checks.json"
    _write_json(checks_path, {})
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=checks_path,
        suite="part",
        case_id="C-03",
        environment="mock",
        code_sha="c" * 40,
        extra_sources=[_durable_source(runner_path)],
    )
    with pytest.raises(COLLECTOR.CollectionError, match="checks.json.*same sha256"):
        COLLECTOR.append_records(result_path, records)


def _s10_pass_checks(evidence: list[str]) -> dict[str, object]:
    return {
        "machine_checks": {
            check_id: {
                "status": "pass",
                "observed": True,
                "expected": True,
                "evidence": evidence,
            }
            for check_id in S10_CHECKS
        }
    }


def test_machine_check_artifact_requires_matching_durable_source(
    tmp_path: Path,
) -> None:
    result_path = _copy_pair(tmp_path)
    runner_path = _runner(tmp_path / "runner.json")
    video_digest = "1" * 64
    checks_path = tmp_path / "checks.json"
    _write_json(
        checks_path,
        _s10_pass_checks(
            [f"artifact:video.mp4?sha256={video_digest}#frame=120"]
        ),
    )
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=checks_path,
        suite="recovery",
        case_id="S10",
        environment="mock",
        code_sha="c" * 40,
        extra_sources=[_durable_source(runner_path), _durable_source(checks_path)],
    )
    with pytest.raises(COLLECTOR.CollectionError, match="video.mp4.*same sha256"):
        COLLECTOR.append_records(result_path, records)


def test_machine_check_artifact_with_matching_durable_source_appends(
    tmp_path: Path,
) -> None:
    result_path = _copy_pair(tmp_path)
    runner_path = _runner(tmp_path / "runner.json")
    video_digest = "2" * 64
    checks_path = tmp_path / "checks.json"
    _write_json(
        checks_path,
        _s10_pass_checks(
            [f"artifact:video.mp4?sha256={video_digest}#frame=120"]
        ),
    )
    records = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=checks_path,
        suite="recovery",
        case_id="S10",
        environment="mock",
        code_sha="c" * 40,
        extra_sources=[
            _durable_source(runner_path),
            _durable_source(checks_path),
            f"https://evidence.example/video.mp4?sha256={video_digest}",
        ],
    )
    summary = COLLECTOR.append_records(result_path, records)
    assert summary["trial_count"] == 1


def test_runner_parse_and_source_hash_use_same_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_path = _copy_pair(tmp_path)
    runner_path = _runner(tmp_path / "runner.json")
    original_raw = runner_path.read_bytes()
    original_code_sha = COLLECTOR._code_sha

    def mutate_after_parse(override: str | None, run: dict[str, object]) -> str:
        _write_json(
            runner_path,
            {
                "run": {
                    "run_id": "new-run",
                    "task_id": "other-task",
                    "backend": "mock",
                },
                "steps": [],
            },
        )
        return original_code_sha(override, run)

    monkeypatch.setattr(COLLECTOR, "_code_sha", mutate_after_parse)
    basis, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=runner_path,
        checks_path=None,
        suite="part",
        case_id="C-03",
        environment="mock",
        code_sha="d" * 40,
    )
    assert trial["correlation"]["run_id"] == "run-1"
    assert hashlib.sha256(original_raw).hexdigest() in basis["sources"][0]
    assert hashlib.sha256(runner_path.read_bytes()).hexdigest() not in basis["sources"][0]


def test_runner_started_at_is_required_and_must_be_zoned(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    runner_path = _runner(tmp_path / "runner.json")
    runner = json.loads(runner_path.read_text(encoding="utf-8"))
    del runner["run"]["started_at"]
    _write_json(runner_path, runner)
    with pytest.raises(COLLECTOR.CollectionError, match="actual trial started_at"):
        COLLECTOR.build_records(
            result_path=result_path,
            runner_path=runner_path,
            checks_path=None,
            suite="part",
            case_id="C-03",
            environment="mock",
            code_sha="e" * 40,
        )

    runner["run"]["started_at"] = "2026-10-12T00:00:00"
    _write_json(runner_path, runner)
    with pytest.raises(COLLECTOR.CollectionError, match="include a timezone"):
        COLLECTOR.build_records(
            result_path=result_path,
            runner_path=runner_path,
            checks_path=None,
            suite="part",
            case_id="C-03",
            environment="mock",
            code_sha="e" * 40,
        )


def test_recovery_trial_requires_halt_event_id(tmp_path: Path) -> None:
    result_path = _copy_pair(tmp_path)
    runner_path = _runner(tmp_path / "runner.json")
    runner = json.loads(runner_path.read_text(encoding="utf-8"))
    runner["run"]["halts"] = []
    _write_json(runner_path, runner)
    checks_path = tmp_path / "checks.json"
    _write_json(
        checks_path,
        {
            "machine_checks": {
                check_id: {
                    "status": "pass",
                    "observed": True,
                    "expected": True,
                    "evidence": [f"https://evidence.example/S10#{check_id}"],
                }
                for check_id in S10_CHECKS
            }
        },
    )
    with pytest.raises(COLLECTOR.CollectionError, match="requires a non-empty halt_event_id"):
        COLLECTOR.build_records(
            result_path=result_path,
            runner_path=runner_path,
            checks_path=checks_path,
            suite="recovery",
            case_id="S10",
            environment="mock",
            code_sha="f" * 40,
        )


@pytest.mark.parametrize(("case_id", "field", "relation_check"), [
    (case_id, field, relation_check)
    for case_id, (field, relation_check) in MISMATCH_CASES.items()
])
def test_mismatch_pass_without_referenced_id_becomes_inconclusive(
    tmp_path: Path, case_id: str, field: str, relation_check: str
) -> None:
    result_path = _copy_pair(tmp_path)
    evaluation = json.loads(
        (tmp_path / "issue196_evaluation.v0.5-draft.json").read_text(encoding="utf-8")
    )
    case = next(
        row
        for row in evaluation["suites"]["recovery"]["cases"]
        if row["case_id"] == case_id
    )
    checks_path = tmp_path / "checks.json"
    _write_json(
        checks_path,
        {
            "correlation": {field: RUNNER_CURRENT_IDS[field]},
            "machine_checks": {
                check_id: {
                    "status": "pass",
                    "observed": True,
                    "expected": True,
                    "evidence": [f"https://evidence.example/{case_id}#{check_id}"],
                }
                for check_id in case["required_machine_checks"]
            },
        },
    )
    _, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "runner.json"),
        checks_path=checks_path,
        suite="recovery",
        case_id=case_id,
        environment="mock",
        code_sha="f" * 40,
    )
    checks = {row["check_id"]: row for row in trial["machine_checks"]}
    assert trial["automatic_result"] == "inconclusive"
    assert checks[relation_check]["status"] == "unverifiable"


@pytest.mark.parametrize(("case_id", "field", "relation_check"), [
    (case_id, field, relation_check)
    for case_id, (field, relation_check) in MISMATCH_CASES.items()
])
def test_mismatch_failure_without_referenced_id_becomes_inconclusive(
    tmp_path: Path, case_id: str, field: str, relation_check: str
) -> None:
    result_path = _copy_pair(tmp_path)
    evaluation = json.loads(
        (tmp_path / "issue196_evaluation.v0.5-draft.json").read_text(encoding="utf-8")
    )
    case = next(
        row
        for row in evaluation["suites"]["recovery"]["cases"]
        if row["case_id"] == case_id
    )
    checks_path = tmp_path / "checks.json"
    first_check = case["required_machine_checks"][0]
    _write_json(
        checks_path,
        {
            "correlation": {field: RUNNER_CURRENT_IDS[field]},
            "machine_checks": {
                check_id: {
                    "status": "fail" if check_id == first_check else "pass",
                    "observed": False if check_id == first_check else True,
                    "expected": True,
                    "evidence": [f"https://evidence.example/{case_id}#{check_id}"],
                }
                for check_id in case["required_machine_checks"]
            },
        },
    )
    _, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "runner.json"),
        checks_path=checks_path,
        suite="recovery",
        case_id=case_id,
        environment="mock",
        code_sha="f" * 40,
    )
    checks = {row["check_id"]: row for row in trial["machine_checks"]}
    assert trial["automatic_result"] == "inconclusive"
    assert checks[relation_check]["status"] == "unverifiable"


@pytest.mark.parametrize(("case_id", "field", "relation_check"), [
    (case_id, field, relation_check)
    for case_id, (field, relation_check) in MISMATCH_CASES.items()
])
def test_mismatch_pass_with_distinct_ids_is_preserved(
    tmp_path: Path, case_id: str, field: str, relation_check: str
) -> None:
    result_path = _copy_pair(tmp_path)
    evaluation = json.loads(
        (tmp_path / "issue196_evaluation.v0.5-draft.json").read_text(encoding="utf-8")
    )
    case = next(
        row
        for row in evaluation["suites"]["recovery"]["cases"]
        if row["case_id"] == case_id
    )
    checks_path = tmp_path / "checks.json"
    _write_json(
        checks_path,
        {
            "correlation": {field: RUNNER_CURRENT_IDS[field]},
            "input_reference": {field: f"{field}-previous"},
            "machine_checks": {
                check_id: {
                    "status": "pass",
                    "observed": True,
                    "expected": True,
                    "evidence": [f"https://evidence.example/{case_id}#{check_id}"],
                }
                for check_id in case["required_machine_checks"]
            },
        },
    )
    _, trial = COLLECTOR.build_records(
        result_path=result_path,
        runner_path=_runner(tmp_path / "runner.json"),
        checks_path=checks_path,
        suite="recovery",
        case_id=case_id,
        environment="mock",
        code_sha="f" * 40,
    )
    assert trial["automatic_result"] == "pass"
