"""Seal/verify/observe/evaluate tests for the release_candidate tool."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import ModuleType

import pytest

from tests._release_candidate_tool_helpers import dists as _dists
from tests._release_candidate_tool_helpers import load_tool as _load_tool
from tests._release_candidate_tool_helpers import seal_kwargs as _seal_kwargs
from tests._release_qualification_test_support import (
    _failure_with_class,
    _qualification_bundle,
    _qualification_inventory,
    _qualification_result,
)


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def test_candidate_id_stable_across_observations(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    before = manifest["candidate_id"]
    tool.append_observation(
        manifest,
        kind="qualification",
        run_id=1,
        attempt=1,
        verdict="pass",
        reason="",
    )
    assert tool.verify_manifest(manifest) == []
    assert manifest["candidate_id"] == before


def test_candidate_id_changes_with_generation(tool: ModuleType) -> None:
    first = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    second = tool.seal_manifest(**_seal_kwargs(generation=2))  # type: ignore[arg-type]
    assert first["candidate_id"] != second["candidate_id"]


def test_each_identity_mismatch_refuses(tool: ModuleType) -> None:
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**_seal_kwargs(repository=""))  # type: ignore[arg-type]
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**_seal_kwargs(version=""))  # type: ignore[arg-type]


def test_extra_or_missing_dist_refuses(tool: ModuleType) -> None:
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**_seal_kwargs(dists=_dists()[:1]))  # type: ignore[arg-type]
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(
            **_seal_kwargs(dists=_dists() + [_dists()[0]])  # type: ignore[arg-type]
        )
    wrong_name = _dists()
    wrong_name[0] = dict(wrong_name[0], filename="sase-9.9.9-py3-none-any.whl")
    with pytest.raises(tool.Refusal):
        tool.seal_manifest(**_seal_kwargs(dists=wrong_name))  # type: ignore[arg-type]


def test_incomplete_core_file_set_refuses_to_seal(tool: ModuleType) -> None:
    from tests._release_candidate_tool_helpers import core_files

    partial = [entry for entry in core_files() if entry["packagetype"] == "sdist"]
    with pytest.raises(tool.Refusal, match="incomplete core file set"):
        tool.seal_manifest(**_seal_kwargs(core_files=partial))  # type: ignore[arg-type]


def test_yanked_only_core_file_set_refuses_to_seal(tool: ModuleType) -> None:
    from tests._release_candidate_tool_helpers import core_files

    yanked = core_files(yanked=True)
    with pytest.raises(tool.Refusal, match="incomplete core file set"):
        tool.seal_manifest(**_seal_kwargs(core_files=yanked))  # type: ignore[arg-type]


def test_second_stash_generation_must_requalify(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    result = tool.evaluate_manifest(manifest, manifest["observations"])
    assert result["publishable"] is False
    assert any(
        clause["name"] == "qualification"
        and "required evidence missing" in clause["detail"]
        for clause in result["clauses"]
    )


def test_evaluate_reports_missing_evidence_red(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    result = tool.evaluate_manifest(manifest, [])
    assert result["publishable"] is False
    missing = [
        clause["name"]
        for clause in result["clauses"]
        if not clause["ok"] and "required evidence missing" in clause["detail"]
    ]
    assert missing == ["qualification", "exercise"]


def test_evaluate_veto_blocks(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    tool.append_observation(
        manifest,
        kind="qualification",
        run_id=1,
        attempt=1,
        verdict="pass",
        reason="green",
    )
    tool.append_observation(
        manifest,
        kind="exercise",
        run_id=2,
        attempt=1,
        verdict="pass",
        reason="green",
    )
    tool.append_observation(
        manifest,
        kind="veto",
        run_id=3,
        attempt=1,
        verdict="hold",
        reason="human hold",
    )
    result = tool.evaluate_manifest(manifest, manifest["observations"])
    assert result["publishable"] is False
    veto = next(
        clause
        for clause in result["clauses"]
        if clause["name"] == "no_confirmed_release_veto"
    )
    assert veto["ok"] is False


def test_observe_reappend_is_idempotent(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    first = tool.append_observation(
        manifest,
        kind="qualification",
        run_id=7,
        attempt=1,
        verdict="pass",
        reason="green",
    )
    second = tool.append_observation(
        manifest,
        kind="qualification",
        run_id=7,
        attempt=1,
        verdict="pass",
        reason="green",
    )
    assert first["asset"] == second["asset"]
    assert second["asset"].startswith("candidate-gen1-qualification-run7-attempt1")
    assert len(manifest["observations"]) == 1


def test_observe_refuses_to_replace_a_conflicting_asset(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    tool.append_observation(
        manifest,
        kind="qualification",
        run_id=7,
        attempt=1,
        verdict="pass",
        reason="green",
    )
    with pytest.raises(tool.Refusal, match="conflicting observation"):
        tool.append_observation(
            manifest,
            kind="qualification",
            run_id=7,
            attempt=1,
            verdict="red",
            reason="different payload",
        )


def test_unknown_observation_kind_refuses(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    with pytest.raises(tool.Refusal, match="unknown observation kind"):
        tool.append_observation(
            manifest,
            kind="smoke",
            run_id=1,
            attempt=1,
            verdict="pass",
        )


def test_unsupported_locator_fails_closed(tool: ModuleType, tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(tool.Refusal, match="unsupported asset locator"):
        tool.resolve_locator("s3://bucket/key", tmp_path / "out.bin")


def test_missing_file_locator_fails_closed(tool: ModuleType, tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(tool.Refusal, match="asset not found"):
        tool.resolve_locator("file:/does/not/exist.bin", tmp_path / "out.bin")


def test_parse_expected_suffixes_reads_single_source(tool: ModuleType) -> None:
    text = "jobs:\n  x:\n    env:\n      EXPECTED_DIST_SUFFIXES: ['.tar.gz', '-py3-none-any.whl']\n"
    assert tool.parse_expected_suffixes(text) == [".tar.gz", "-py3-none-any.whl"]
    with pytest.raises(tool.Refusal, match="EXPECTED_DIST_SUFFIXES not found"):
        tool.parse_expected_suffixes("no suffixes here\n")


def test_cross_check_lock_hashes_catches_mismatch(tool: ModuleType, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from tests._release_candidate_tool_helpers import core_files

    lock = tmp_path / "uv.lock"
    files = core_files()
    first = files[0]
    lock.write_text(
        '[[package]]\nname = "sase-core-rs"\nversion = "0.42.0"\n'
        f'[package.metadata]\n[package.sdist]\nurl = "{first["url"]}"\n'
        'hash = "sha256:deadbeef"\n',
        encoding="utf-8",
    )
    problems = tool.cross_check_lock_hashes(files, lock, "0.42.0")
    assert problems == [f"HASH_MISMATCH {first['filename']}"]


def test_n1_inventory_is_single_versioned_classification(tool: ModuleType) -> None:
    raw, inventory = _qualification_inventory(tool)
    checks = inventory["checks"]
    blocking = [entry["id"] for entry in checks if entry["disposition"] == "blocking"]
    assert blocking == [
        "lint",
        "test-3.12",
        "test-3.13",
        "test-3.14",
        "release-exercise",
    ]
    assert [entry["id"] for entry in checks if entry["disposition"] == "advisory"] == [
        "visual-test",
        "perf-floors",
        "tutorial-tests",
        "ace-page-group-isolation",
    ]
    exercise = next(entry for entry in checks if entry["evidence_kind"] == "exercise")
    assert len(exercise["required_legs"]) == 4
    assert inventory["admission_policy"]["id"] == "master-gate"
    assert tool._qualification.inventory_digest(
        raw
    ) != tool._qualification.inventory_digest(raw + b" ")


def test_qualification_evaluator_loads_its_focused_helpers(tool: ModuleType) -> None:
    evaluator = tool._qualification
    assert Path(evaluator.__file__).name == "_release_qualification.py"
    assert (
        Path(evaluator._evidence.__file__).name == "_release_qualification_evidence.py"
    )
    assert (
        Path(evaluator._inventory.__file__).name
        == "_release_qualification_inventory.py"
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value.update(schema_version=2),
            "unknown qualification inventory schema",
        ),
        (lambda value: value.update(checks=[]), "no release checks"),
        (
            lambda value: [
                entry.update(disposition="advisory", evidence_kind="job")
                for entry in value["checks"]
            ],
            "empty blocking release inventory",
        ),
        (
            lambda value: value["checks"][0].update(evidence_kind="job"),
            "unmapped required evidence",
        ),
        (
            lambda value: value["checks"].append(copy.deepcopy(value["checks"][0])),
            "duplicate inventory check id",
        ),
        (
            lambda value: value["checks"].append(
                {**copy.deepcopy(value["checks"][1]), "id": "test-copy"}
            ),
            "duplicate or conflicting workflow/job mapping",
        ),
    ],
)
def test_inventory_invalid_contracts_fail_closed(
    tool: ModuleType, mutate, message: str
) -> None:  # type: ignore[no-untyped-def]
    _, inventory = _qualification_inventory(tool)
    changed = copy.deepcopy(inventory)
    mutate(changed)
    with pytest.raises(tool._qualification.QualificationInputError, match=message):
        tool._qualification.load_inventory(json.dumps(changed).encode())


def test_inventory_duplicate_json_keys_fail_closed(tool: ModuleType) -> None:
    with pytest.raises(
        tool._qualification.QualificationInputError, match="duplicate JSON key"
    ):
        tool._qualification.load_inventory(
            b'{"schema_version":1,"schema_version":1,"admission_policy":{},"checks":[]}'
        )


def test_qualification_pass_archives_bound_evidence_and_advisories(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    bundle = _qualification_bundle(
        tool, manifest, advisory_failures={"visual-test", "perf-floors"}
    )
    report = _qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "pass"
    assert report["rerun_eligible"] is False
    assert {
        item["check_id"] for item in report["advisories"] if item["diagnostic"]
    } == {
        "visual-test",
        "perf-floors",
    }
    lint = report["attempt_results"][0]["jobs"][0]
    assert lint["evidence"]["kind"] == "command"
    assert "collected" not in lint["evidence"]
    assert all(
        item["evidence"]["binding"]["inventory_digest"] == report["inventory_digest"]
        for item in report["attempt_results"][0]["jobs"]
    )


@pytest.mark.parametrize(
    ("scenario", "failure_class"),
    [
        ("tests", "tests"),
        ("collection", "collection"),
        ("zero", "zero"),
        ("binding", "harness"),
        ("bad-counts", "harness"),
        ("missing-evidence", "missing"),
        ("skipped", "missing"),
        ("in-progress", "missing"),
    ],
)
def test_required_job_red_classes_are_typed(
    tool: ModuleType, scenario: str, failure_class: str
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    bundle = _qualification_bundle(tool, manifest, scenarios=[{"test-3.12": scenario}])
    if scenario == "missing-evidence":
        record = next(
            item
            for item in bundle["attempts"][0]["jobs"]
            if item["workflow_job_id"] == "test"
            and item["matrix"] == {"python-version": "3.12"}
        )
        record.pop("evidence")
    report = _qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    assert failure_class in {failure["failure_class"] for failure in report["failures"]}
    assert report["rerun_eligible"] is (failure_class == "tests")
    if scenario == "tests":
        failure = _failure_with_class(report, "tests")
        assert failure["first_failing_node_ids"] == [
            "tests/test_qualification.py::test_breaks"
        ]


def test_missing_matrix_entry_and_duplicate_job_mapping_are_red(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    missing = _qualification_bundle(tool, manifest, missing_jobs={"test-3.14"})
    report = _qualification_result(tool, manifest, missing)
    assert any(
        failure["job"] == "test (3.14)" and failure["failure_class"] == "missing"
        for failure in report["failures"]
    )
    duplicate = _qualification_bundle(tool, manifest)
    record = copy.deepcopy(duplicate["attempts"][0]["jobs"][1])
    record["job_id"] += 100
    duplicate["attempts"][0]["jobs"].append(record)
    report = _qualification_result(tool, manifest, duplicate)
    assert any(
        "ambiguous duplicate job mapping" in diagnostic
        for failure in report["failures"]
        for diagnostic in failure["diagnostics"]
    )


def test_failed_reporting_step_cannot_accept_a_partial_pytest_report(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    bundle = _qualification_bundle(tool, manifest)
    record = next(
        item
        for item in bundle["attempts"][0]["jobs"]
        if item["workflow_job_id"] == "test"
        and item["matrix"] == {"python-version": "3.12"}
    )
    report_step = next(
        step
        for step in record["steps"]
        if step["name"] == "Upload qualification evidence"
    )
    report_step["conclusion"] = "failure"
    record["conclusion"] = "failure"
    record["evidence"]["passed"] = 1
    record["evidence"]["failed"] = 1
    record["evidence"]["exit_status"] = 1
    record["evidence"]["first_failing_node_ids"] = ["tests/test.py::test_red"]
    result = _qualification_result(tool, manifest, bundle)
    failure = _failure_with_class(result, "harness")
    assert "Upload qualification evidence" in " ".join(failure["diagnostics"])
    assert result["rerun_eligible"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sha", "0" * 40),
        ("candidate_id", "candidate-other"),
        ("generation", 9),
        ("expected_core_version", "0.99.0"),
        ("inventory_digest", "0" * 64),
    ],
)
def test_job_bundle_identity_mismatches_are_red(
    tool: ModuleType, field: str, value: object
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    bundle = _qualification_bundle(tool, manifest)
    bundle[field] = value
    report = _qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    assert report["failures"][0]["failure_class"] == "harness"
    assert field in " ".join(report["failures"][0]["diagnostics"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_id", "candidate-stale"),
        ("generation", 2),
        ("checked_out_sha", "0" * 40),
        ("expected_core_version", "0.99.0"),
        ("installed_core_version", "0.99.0"),
        ("inventory_digest", "0" * 64),
        ("workflow_run_id", 999),
        ("job_name", "test (other)"),
        ("attempt", 2),
    ],
)
def test_evidence_binding_mismatches_are_red(
    tool: ModuleType, field: str, value: object
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    bundle = _qualification_bundle(tool, manifest)
    test_record = next(
        item
        for item in bundle["attempts"][0]["jobs"]
        if item["workflow_job_id"] == "test"
        and item["matrix"] == {"python-version": "3.12"}
    )
    test_record["evidence"]["binding"][field] = value
    report = _qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    failure = _failure_with_class(report, "harness")
    assert field in " ".join(failure["diagnostics"])


def test_lint_binding_diagnostics_keep_missing_names(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    bundle = _qualification_bundle(tool, manifest, scenarios=[{"lint": "bindings"}])
    report = _qualification_result(tool, manifest, bundle)
    failure = next(item for item in report["failures"] if item["job"] == "lint")
    assert failure["failure_class"] == "harness"
    assert "required_binding" in " ".join(failure["diagnostics"])
    assert report["rerun_eligible"] is False


def test_duplicate_or_unreadable_evidence_file_fails_closed(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    bundle = _qualification_bundle(tool, manifest)
    record = next(
        item
        for item in bundle["attempts"][0]["jobs"]
        if item["workflow_job_id"] == "test"
        and item["matrix"] == {"python-version": "3.12"}
    )
    record.pop("evidence")
    evidence_file = "attempt-1/qualify-evidence-test-3.12.json"
    record["evidence_file"] = evidence_file
    evidence_dir = tmp_path / "evidence"
    evidence_path = evidence_dir / evidence_file
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        '{"schema_version":1,"schema_version":1}', encoding="utf-8"
    )
    bundle_path = tmp_path / "jobs.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    loaded = tool._qualification.load_job_bundle_file(bundle_path, evidence_dir)
    report = _qualification_result(tool, manifest, loaded)
    failure = _failure_with_class(report, "harness")
    assert "duplicate JSON key" in " ".join(failure["diagnostics"])


def test_unreadable_and_stale_inputs_are_red_with_diagnostics(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    raw, _ = _qualification_inventory(tool)
    unreadable = tool._qualification.evaluate_qualification(
        manifest, b"{invalid", None, job_bundle_error="job history could not be read"
    )
    assert unreadable["verdict"] == "red"
    assert unreadable["failures"][0]["failure_class"] == "harness"
    stale = _qualification_bundle(tool, manifest)
    stale["generation"] += 1
    report = tool._qualification.evaluate_qualification(manifest, raw, stale)
    assert report["verdict"] == "red"
    assert "generation mismatch" in " ".join(report["failures"][0]["diagnostics"])


def test_fact_fetch_failure_keeps_identity_and_revalidates_typed_red(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    raw, _ = _qualification_inventory(tool)
    report = tool._qualification.evaluate_qualification(
        manifest,
        raw,
        None,
        job_bundle_error="qualification fact fetch failed; see the job log",
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    assert report["verdict"] == "red"
    assert report["workflow_run_id"] == 700
    assert report["current_attempt"] == 1
    assert report["rerun_eligible"] is False
    assert "QUALIFY_RED" in tool._qualification.qualify_failure_summary(report)
    payload = tool._qualification.make_observation_payload(
        manifest,
        raw,
        None,
        job_bundle_error="qualification fact fetch failed; see the job log",
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    manifest_path = tmp_path / "candidate.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    tool.append_observation(
        manifest,
        kind="qualification",
        run_id=700,
        attempt=1,
        verdict="red",
        reason=tool._qualification.qualify_failure_summary(report),
        extra={"qualification": payload},
    )
    latest, error = tool._latest_qualification_report(
        manifest, manifest["observations"]
    )
    assert error is None
    assert latest is not None
    assert latest["verdict"] == "red"
    assert latest["rerun_eligible"] is False
    evaluated = tool.evaluate_manifest(manifest, manifest["observations"])
    clause = next(
        item for item in evaluated["clauses"] if item["name"] == "qualification"
    )
    assert clause["ok"] is False
    assert "QUALIFY_RED" in clause["detail"]
    assert evaluated["rerun_eligible"] is False


def test_contradictory_history_still_refuses_despite_expected_identity(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    raw, _ = _qualification_inventory(tool)
    forged = _qualification_bundle(tool, manifest, run_id=999)
    report = tool._qualification.evaluate_qualification(
        manifest,
        raw,
        forged,
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    assert report["verdict"] == "red"
    assert report["workflow_run_id"] == 999
    payload = tool._qualification.make_observation_payload(
        manifest,
        raw,
        forged,
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    tool.append_observation(
        manifest,
        kind="qualification",
        run_id=700,
        attempt=1,
        verdict="red",
        reason=tool._qualification.qualify_failure_summary(report),
        extra={"qualification": payload},
    )
    latest, error = tool._latest_qualification_report(
        manifest, manifest["observations"]
    )
    assert latest is None
    assert error is not None
    assert "disagrees" in error


def test_command_evidence_keeps_scan_names_beside_binding_mismatch(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    raw, inventory = _qualification_inventory(tool)
    digest = tool._qualification.inventory_digest(raw)
    entry = next(item for item in inventory["checks"] if item["id"] == "lint")
    record = {
        "workflow_file": entry["workflow"],
        "workflow_job_id": entry["job"]["id"],
        "matrix": {},
        "job_id": 4242,
        "job_name": "lint",
        "workflow_run_id": 700,
        "execution_attempt": 1,
        "status": "completed",
        "conclusion": "failure",
        "url": "https://example.invalid/run/700/job/4242",
        "started_at": "2026-10-19T20:00:00Z",
        "completed_at": "2026-10-19T20:10:00Z",
        "steps": [
            {"name": "run", "status": "completed", "conclusion": "failure"},
            {
                "name": "Write qualification evidence",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "name": "Upload qualification evidence",
                "status": "completed",
                "conclusion": "success",
            },
        ],
    }
    record["evidence"] = {
        "schema_version": 1,
        "kind": "command",
        "binding": {
            "repository": manifest["repository"],
            "candidate_id": "candidate-stale",
            "generation": manifest["generation"],
            "checked_out_sha": manifest["sha"],
            "expected_core_version": manifest["core_version"],
            "installed_core_version": manifest["core_version"],
            "inventory_digest": digest,
            "workflow_run_id": 700,
            "job_id": 4242,
            "job_name": "lint",
            "attempt": 1,
        },
        "steps": [
            {
                "name": "Preflight core bindings",
                "status": "completed",
                "conclusion": "failure",
                "exit_status": 1,
            }
        ],
        "missing_bindings": ["vanished_binding"],
        "diagnostics": ["probe wheel predates the sealed pin"],
    }
    bundle = {
        "schema_version": 1,
        "repository": manifest["repository"],
        "candidate_id": manifest["candidate_id"],
        "generation": manifest["generation"],
        "sha": manifest["sha"],
        "expected_core_version": manifest["core_version"],
        "inventory_digest": digest,
        "workflow_run_id": 700,
        "current_attempt": 1,
        "attempts": [{"attempt": 1, "jobs": [record]}],
    }
    for check_id in ("test-3.12", "test-3.13", "test-3.14"):
        check = next(item for item in inventory["checks"] if item["id"] == check_id)
        bundle["attempts"][0]["jobs"].append(
            {
                "workflow_file": check["workflow"],
                "workflow_job_id": check["job"]["id"],
                "matrix": dict(check["job"]["matrix"]),
                "job_id": 5000 + len(bundle["attempts"][0]["jobs"]),
                "job_name": check["job"]["name"],
                "workflow_run_id": 700,
                "execution_attempt": 1,
                "status": "completed",
                "conclusion": "success",
                "url": "https://example.invalid/run/700",
                "started_at": "2026-10-19T20:00:00Z",
                "completed_at": "2026-10-19T20:10:00Z",
                "steps": [
                    {
                        "name": "Write qualification evidence",
                        "status": "completed",
                        "conclusion": "success",
                    },
                    {
                        "name": "Upload qualification evidence",
                        "status": "completed",
                        "conclusion": "success",
                    },
                ],
                "evidence_error": "evidence upload is missing",
                "evidence_error_class": "missing",
            }
        )
    report = tool._qualification.evaluate_qualification(
        manifest, raw, bundle, expected_workflow_run_id=700, expected_attempt=1
    )
    failure = next(item for item in report["failures"] if item["job"] == "lint")
    assert failure["failure_class"] == "harness"
    diagnostics = " ".join(failure["diagnostics"])
    assert "mismatch" in diagnostics
    assert "vanished_binding" in diagnostics
    assert "predates the sealed pin" in diagnostics


def test_first_test_only_red_is_rerun_eligible_and_retry_preserves_history(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    first_bundle = _qualification_bundle(
        tool, manifest, scenarios=[{"test-3.12": "tests"}]
    )
    first = _qualification_result(tool, manifest, first_bundle)
    assert first["verdict"] == "red"
    assert first["rerun_eligible"] is True
    assert first["rerun_reason"] == "first attempt failed only in collected tests"

    retry_bundle = _qualification_bundle(
        tool,
        manifest,
        scenarios=[{"test-3.12": "tests"}, {"test-3.12": "pass"}],
    )
    retry = _qualification_result(tool, manifest, retry_bundle)
    assert retry["verdict"] == "pass"
    assert retry["rerun_eligible"] is False
    attempt_two = retry["attempt_results"][1]
    assert all(
        job["carried_forward"]
        for job in attempt_two["jobs"]
        if job["check_id"] != "test-3.12"
    )
    rerun_job = next(
        job for job in attempt_two["jobs"] if job["check_id"] == "test-3.12"
    )
    assert rerun_job["attempt"] == 2
    assert rerun_job["evidence"]["binding"]["attempt"] == 2

    raw, _ = _qualification_inventory(tool)
    for bundle, attempt in ((first_bundle, 1), (retry_bundle, 2)):
        payload = tool._qualification.make_observation_payload(
            manifest,
            raw,
            bundle,
            expected_workflow_run_id=700,
            expected_attempt=attempt,
        )
        report = payload["result"]
        tool.append_observation(
            manifest,
            kind="qualification",
            run_id=700,
            attempt=attempt,
            verdict="pass" if report["verdict"] == "pass" else "red",
            reason="" if report["verdict"] == "pass" else "QUALIFY_RED",
            extra={"qualification": payload},
        )
    assert len(manifest["observations"]) == 2
    evaluated = tool.evaluate_manifest(manifest, manifest["observations"])
    qualification = next(
        item for item in evaluated["clauses"] if item["name"] == "qualification"
    )
    assert qualification["ok"] is True


def test_second_red_is_not_rerun_eligible(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    bundle = _qualification_bundle(
        tool,
        manifest,
        scenarios=[{"test-3.12": "tests"}, {"test-3.12": "tests"}],
    )
    report = _qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    assert report["rerun_eligible"] is False
    assert "second qualification attempt" in report["rerun_reason"]


def test_attempt_two_cannot_hide_first_attempt_harness_failure(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    bundle = _qualification_bundle(
        tool,
        manifest,
        scenarios=[{"test-3.12": "collection"}, {"test-3.12": "pass"}],
    )
    report = _qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    assert any(failure["failure_class"] == "harness" for failure in report["failures"])
    assert report["rerun_eligible"] is False


def test_changed_carried_forward_success_is_ambiguous_and_red(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    bundle = _qualification_bundle(
        tool,
        manifest,
        scenarios=[{"test-3.12": "tests"}, {"test-3.12": "pass"}],
    )
    carried = next(
        item
        for item in bundle["attempts"][1]["jobs"]
        if item["workflow_job_id"] == "lint"
    )
    carried["job_id"] += 1
    report = _qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    assert any(
        "same unchanged successful execution" in diagnostic
        for failure in report["failures"]
        for diagnostic in failure["diagnostics"]
    )


def test_successful_job_cannot_be_rerun_on_a_failed_only_attempt(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    bundle = _qualification_bundle(
        tool,
        manifest,
        scenarios=[{"test-3.12": "tests"}, {"test-3.12": "pass", "lint": "pass"}],
    )
    report = _qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    assert any(
        "only failed-job reruns" in diagnostic
        for failure in report["failures"]
        for diagnostic in failure["diagnostics"]
    )


def test_old_pass_never_wins_over_a_newer_red(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    raw, _ = _qualification_inventory(tool)
    first_bundle = _qualification_bundle(tool, manifest)
    first_payload = tool._qualification.make_observation_payload(
        manifest,
        raw,
        first_bundle,
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    tool.append_observation(
        manifest,
        kind="qualification",
        run_id=700,
        attempt=1,
        verdict="pass",
        extra={"qualification": first_payload},
    )
    second_bundle = _qualification_bundle(
        tool, manifest, scenarios=[{}, {"test-3.12": "tests"}]
    )
    second_payload = tool._qualification.make_observation_payload(
        manifest,
        raw,
        second_bundle,
        expected_workflow_run_id=700,
        expected_attempt=2,
    )
    tool.append_observation(
        manifest,
        kind="qualification",
        run_id=700,
        attempt=2,
        verdict="red",
        reason="QUALIFY_RED",
        extra={"qualification": second_payload},
    )
    result = tool.evaluate_manifest(manifest, manifest["observations"])
    clause = next(item for item in result["clauses"] if item["name"] == "qualification")
    assert clause["ok"] is False


def test_old_generation_evidence_cannot_qualify_new_candidate(tool: ModuleType) -> None:
    old = tool.seal_manifest(**_seal_kwargs(generation=1))  # type: ignore[arg-type]
    new = tool.seal_manifest(**_seal_kwargs(generation=2))  # type: ignore[arg-type]
    raw, _ = _qualification_inventory(tool)
    stale_bundle = _qualification_bundle(tool, old)
    payload = tool._qualification.make_observation_payload(
        new,
        raw,
        stale_bundle,
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    assert payload["result"]["verdict"] == "red"
    assert "candidate_id mismatch" in " ".join(
        payload["result"]["failures"][0]["diagnostics"]
    )
    old_observation = tool.append_observation(
        old,
        kind="qualification",
        run_id=700,
        attempt=1,
        verdict="pass",
        extra={
            "qualification": tool._qualification.make_observation_payload(
                old,
                raw,
                stale_bundle,
                expected_workflow_run_id=700,
                expected_attempt=1,
            )
        },
    )
    new["observations"].append(old_observation)
    result = tool.evaluate_manifest(new, new["observations"])
    clause = next(item for item in result["clauses"] if item["name"] == "qualification")
    assert clause["ok"] is False


def test_bare_pass_observation_is_not_qualification_evidence(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    tool.append_observation(
        manifest,
        kind="qualification",
        run_id=700,
        attempt=1,
        verdict="pass",
        reason="bare pass",
    )
    result = tool.evaluate_manifest(manifest, manifest["observations"])
    clause = next(item for item in result["clauses"] if item["name"] == "qualification")
    assert clause["ok"] is False
    assert "unverifiable" in clause["detail"]


def test_qualify_cli_persists_red_observation_before_refusal(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tool.seal_manifest(**_seal_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    inventory_path = tmp_path / "inventory.json"
    raw, _ = _qualification_inventory(tool)
    inventory_path.write_bytes(raw)
    evidence_dir = tmp_path / "evidence"
    bundle = _qualification_bundle(tool, manifest, scenarios=[{"test-3.12": "tests"}])
    for snapshot in bundle["attempts"]:
        for record in snapshot["jobs"]:
            evidence = record.pop("evidence", None)
            if evidence is None:
                continue
            evidence_file = (
                Path(f"attempt-{snapshot['attempt']}")
                / f"qualify-evidence-{record['workflow_job_id']}-{record['job_id']}.json"
            )
            destination = evidence_dir / evidence_file
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(evidence), encoding="utf-8")
            record["evidence_file"] = evidence_file.as_posix()
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps(bundle), encoding="utf-8")
    output_path = tmp_path / "observation.json"
    code = tool.main(
        [
            "qualify",
            "--manifest",
            str(manifest_path),
            "--inventory",
            str(inventory_path),
            "--jobs",
            str(jobs_path),
            "--evidence-dir",
            str(evidence_dir),
            "--run-id",
            "700",
            "--attempt",
            "1",
            "--out",
            str(output_path),
        ]
    )
    assert code == tool.EXIT_REFUSED
    capsys.readouterr()
    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(written["observations"]) == 1
    qualification = written["observations"][0]["extra"]["qualification"]
    assert qualification["inventory_sha256"] == tool._qualification.inventory_digest(
        raw
    )
    assert qualification["result"]["rerun_eligible"] is True
    assert output_path.is_file()
    evaluated = tool.evaluate_manifest(written, written["observations"])
    clause = next(
        item for item in evaluated["clauses"] if item["name"] == "qualification"
    )
    assert clause["ok"] is False
