"""Typed QUALIFY_RED identity, history, and diagnostic tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest

from tests._release_candidate_tool_helpers import load_tool as _load_tool
from tests._release_candidate_tool_helpers import seal_kwargs as _seal_kwargs
from tests._release_qualification_test_support import (
    _qualification_bundle,
    _qualification_inventory,
)


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


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
