"""Inventory and verdict tests for the release_candidate tool."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import ModuleType

import pytest

from tests._release_candidate_tool_helpers import load_tool
from tests._release_candidate_tool_helpers import seal_kwargs
from tests._release_qualification_test_support import failure_with_class
from tests._release_qualification_test_support import qualification_bundle
from tests._release_qualification_test_support import qualification_inventory
from tests._release_qualification_test_support import qualification_result


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return load_tool()


def test_n1_inventory_is_single_versioned_classification(tool: ModuleType) -> None:
    raw, inventory = qualification_inventory(tool)
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
    _, inventory = qualification_inventory(tool)
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
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    bundle = qualification_bundle(
        tool, manifest, advisory_failures={"visual-test", "perf-floors"}
    )
    report = qualification_result(tool, manifest, bundle)
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
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    bundle = qualification_bundle(tool, manifest, scenarios=[{"test-3.12": scenario}])
    if scenario == "missing-evidence":
        record = next(
            item
            for item in bundle["attempts"][0]["jobs"]
            if item["workflow_job_id"] == "test"
            and item["matrix"] == {"python-version": "3.12"}
        )
        record.pop("evidence")
    report = qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    assert failure_class in {failure["failure_class"] for failure in report["failures"]}
    assert report["rerun_eligible"] is (failure_class == "tests")
    if scenario == "tests":
        failure = failure_with_class(report, "tests")
        assert failure["first_failing_node_ids"] == [
            "tests/test_qualification.py::test_breaks"
        ]


def test_missing_matrix_entry_and_duplicate_job_mapping_are_red(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    missing = qualification_bundle(tool, manifest, missing_jobs={"test-3.14"})
    report = qualification_result(tool, manifest, missing)
    assert any(
        failure["job"] == "test (3.14)" and failure["failure_class"] == "missing"
        for failure in report["failures"]
    )
    duplicate = qualification_bundle(tool, manifest)
    record = copy.deepcopy(duplicate["attempts"][0]["jobs"][1])
    record["job_id"] += 100
    duplicate["attempts"][0]["jobs"].append(record)
    report = qualification_result(tool, manifest, duplicate)
    assert any(
        "ambiguous duplicate job mapping" in diagnostic
        for failure in report["failures"]
        for diagnostic in failure["diagnostics"]
    )


def test_failed_reporting_step_cannot_accept_a_partial_pytest_report(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    bundle = qualification_bundle(tool, manifest)
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
    result = qualification_result(tool, manifest, bundle)
    failure = failure_with_class(result, "harness")
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
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    bundle = qualification_bundle(tool, manifest)
    bundle[field] = value
    report = qualification_result(tool, manifest, bundle)
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
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    bundle = qualification_bundle(tool, manifest)
    test_record = next(
        item
        for item in bundle["attempts"][0]["jobs"]
        if item["workflow_job_id"] == "test"
        and item["matrix"] == {"python-version": "3.12"}
    )
    test_record["evidence"]["binding"][field] = value
    report = qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    failure = failure_with_class(report, "harness")
    assert field in " ".join(failure["diagnostics"])


def test_lint_binding_diagnostics_keep_missing_names(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    bundle = qualification_bundle(tool, manifest, scenarios=[{"lint": "bindings"}])
    report = qualification_result(tool, manifest, bundle)
    failure = next(item for item in report["failures"] if item["job"] == "lint")
    assert failure["failure_class"] == "harness"
    assert "required_binding" in " ".join(failure["diagnostics"])
    assert report["rerun_eligible"] is False
