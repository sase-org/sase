"""Rerun, history, and CLI tests for the release_candidate tool."""

from __future__ import annotations

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


def test_duplicate_or_unreadable_evidence_file_fails_closed(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    bundle = qualification_bundle(tool, manifest)
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
    report = qualification_result(tool, manifest, loaded)
    failure = failure_with_class(report, "harness")
    assert "duplicate JSON key" in " ".join(failure["diagnostics"])


def test_unreadable_and_stale_inputs_are_red_with_diagnostics(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    raw, _ = qualification_inventory(tool)
    unreadable = tool._qualification.evaluate_qualification(
        manifest, b"{invalid", None, job_bundle_error="job history could not be read"
    )
    assert unreadable["verdict"] == "red"
    assert unreadable["failures"][0]["failure_class"] == "harness"
    stale = qualification_bundle(tool, manifest)
    stale["generation"] += 1
    report = tool._qualification.evaluate_qualification(manifest, raw, stale)
    assert report["verdict"] == "red"
    assert "generation mismatch" in " ".join(report["failures"][0]["diagnostics"])


def test_first_test_only_red_is_rerun_eligible_and_retry_preserves_history(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    first_bundle = qualification_bundle(
        tool, manifest, scenarios=[{"test-3.12": "tests"}]
    )
    first = qualification_result(tool, manifest, first_bundle)
    assert first["verdict"] == "red"
    assert first["rerun_eligible"] is True
    assert first["rerun_reason"] == "first attempt failed only in collected tests"

    retry_bundle = qualification_bundle(
        tool,
        manifest,
        scenarios=[{"test-3.12": "tests"}, {"test-3.12": "pass"}],
    )
    retry = qualification_result(tool, manifest, retry_bundle)
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

    raw, _ = qualification_inventory(tool)
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
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    bundle = qualification_bundle(
        tool,
        manifest,
        scenarios=[{"test-3.12": "tests"}, {"test-3.12": "tests"}],
    )
    report = qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    assert report["rerun_eligible"] is False
    assert "second qualification attempt" in report["rerun_reason"]


def test_attempt_two_cannot_hide_first_attempt_harness_failure(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    bundle = qualification_bundle(
        tool,
        manifest,
        scenarios=[{"test-3.12": "collection"}, {"test-3.12": "pass"}],
    )
    report = qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    assert any(failure["failure_class"] == "harness" for failure in report["failures"])
    assert report["rerun_eligible"] is False


def test_changed_carried_forward_success_is_ambiguous_and_red(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    bundle = qualification_bundle(
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
    report = qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    assert any(
        "same unchanged successful execution" in diagnostic
        for failure in report["failures"]
        for diagnostic in failure["diagnostics"]
    )


def test_successful_job_cannot_be_rerun_on_a_failed_only_attempt(
    tool: ModuleType,
) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    bundle = qualification_bundle(
        tool,
        manifest,
        scenarios=[{"test-3.12": "tests"}, {"test-3.12": "pass", "lint": "pass"}],
    )
    report = qualification_result(tool, manifest, bundle)
    assert report["verdict"] == "red"
    assert any(
        "only failed-job reruns" in diagnostic
        for failure in report["failures"]
        for diagnostic in failure["diagnostics"]
    )


def test_old_pass_never_wins_over_a_newer_red(tool: ModuleType) -> None:
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    raw, _ = qualification_inventory(tool)
    first_bundle = qualification_bundle(tool, manifest)
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
    second_bundle = qualification_bundle(
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
    old = tool.seal_manifest(**seal_kwargs(generation=1))  # type: ignore[arg-type]
    new = tool.seal_manifest(**seal_kwargs(generation=2))  # type: ignore[arg-type]
    raw, _ = qualification_inventory(tool)
    stale_bundle = qualification_bundle(tool, old)
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
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
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
    manifest = tool.seal_manifest(**seal_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    inventory_path = tmp_path / "inventory.json"
    raw, _ = qualification_inventory(tool)
    inventory_path.write_bytes(raw)
    evidence_dir = tmp_path / "evidence"
    bundle = qualification_bundle(tool, manifest, scenarios=[{"test-3.12": "tests"}])
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
