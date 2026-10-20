"""Bundle collection tests for collect_qualification_jobs.

Split from ``tests.test_collect_qualification_jobs``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest

from tests._collect_qualification_jobs_helpers import (
    INVENTORY,
    blocking_artifact_names,
    check_names_for_attempt,
    collect_tool_fixture,  # noqa: F401 (registers the tool fixture)
    qualification_entries,
    qualification_job_row,
    qualification_manifest,
    release_tool_fixture,  # noqa: F401 (registers the release_tool fixture)
    run_collect,
    write_artifact_pages,
    write_job_pages,
    write_pass_evidence,
)

__all__ = [
    "test_duplicate_scoped_rows_are_preserved_for_refusal",
    "test_rerun_carry_forward_evaluates_green",
    "test_scope_is_exact_caller_prefix",
    "test_success_single_attempt_evaluates_green",
]


def test_success_single_attempt_evaluates_green(
    tool: ModuleType, release_tool: ModuleType, tmp_path: Path
) -> None:
    manifest = qualification_manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    entries = qualification_entries()
    job_ids = {str(entry["id"]): 2000 + index for index, entry in enumerate(entries)}
    rows = [
        qualification_job_row(str(entry["job"]["name"]), job_ids[str(entry["id"])])
        for entry in entries
    ]
    jobs_path = tmp_path / "jobs-attempt-1.json"
    write_job_pages(jobs_path, rows, paginated=False)
    artifacts_path = tmp_path / "artifacts-attempt-1.json"
    write_artifact_pages(artifacts_path, blocking_artifact_names(1))
    write_pass_evidence(
        release_tool, manifest, tmp_path, attempt=1, run_id=700, job_ids=job_ids
    )
    bundle_path = run_collect(
        tool,
        tmp_path,
        manifest_path=manifest_path,
        jobs={1: [jobs_path]},
        artifacts={1: [artifacts_path]},
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["schema_version"] == 1
    assert bundle["repository"] == manifest["repository"]
    assert bundle["candidate_id"] == manifest["candidate_id"]
    assert bundle["generation"] == manifest["generation"]
    assert bundle["sha"] == manifest["sha"]
    assert bundle["expected_core_version"] == manifest["core_version"]
    assert bundle["workflow_run_id"] == 700
    assert bundle["current_attempt"] == 1
    assert check_names_for_attempt(bundle, 1) == {
        "lint",
        "test (3.12)",
        "test (3.13)",
        "test (3.14)",
        "visual-test",
        "perf-floors",
        "tutorial-tests",
        "ace-page-group-isolation",
    }
    loaded = release_tool._qualification.load_job_bundle_file(bundle_path, tmp_path)
    assert "evidence" in loaded["attempts"][0]["jobs"][0]
    report = release_tool._qualification.evaluate_qualification(
        manifest,
        INVENTORY.read_bytes(),
        loaded,
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    assert report["verdict"] == "pass", report["failures"]


def test_scope_is_exact_caller_prefix(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = qualification_manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    decoys = [
        dict(qualification_job_row("lint", 9001), name="lint"),
        dict(qualification_job_row("lint", 9002), name="other-ci / lint"),
        dict(qualification_job_row("lint", 9003), name="qualify-ci-extra / lint"),
        dict(qualification_job_row("lint", 9004), name="qualify-ci"),
        dict(qualification_job_row("lint", 9005), name="qualify-ci / lint / nested"),
    ]
    scoped = qualification_job_row("lint", 9100)
    jobs_path = tmp_path / "jobs.json"
    write_job_pages(jobs_path, decoys + [scoped], paginated=True)
    out = tmp_path / "bundle.json"
    status = tool.main(
        [
            "--inventory",
            str(INVENTORY),
            "--manifest",
            str(manifest_path),
            "--run-id",
            "700",
            "--evidence-root",
            str(tmp_path),
            "--attempt-jobs",
            f"1={jobs_path}",
            "--out",
            str(out),
        ]
    )
    assert status == 0
    captured = capsys.readouterr()
    # "qualify-ci / lint / nested" is caller-scoped but matches no inventory
    # check, so it is scoped yet unemitted: never suffix-matched to lint.
    assert "2 scoped row(s)" in captured.out
    assert "4 ignored row(s)" in captured.out
    bundle = json.loads(out.read_text(encoding="utf-8"))
    attempt_jobs = bundle["attempts"][0]["jobs"]
    assert [row["job_id"] for row in attempt_jobs] == [9100]
    assert attempt_jobs[0]["job_name"] == "lint"
    assert attempt_jobs[0]["matrix"] == {}


def test_rerun_carry_forward_evaluates_green(
    tool: ModuleType, release_tool: ModuleType, tmp_path: Path
) -> None:
    manifest = qualification_manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    entries = qualification_entries()
    first_ids = {str(entry["id"]): 3000 + index for index, entry in enumerate(entries)}
    first_rows = []
    for entry in entries:
        check_id = str(entry["id"])
        conclusion = "failure" if check_id == "test-3.12" else "success"
        row = qualification_job_row(
            str(entry["job"]["name"]), first_ids[check_id], conclusion=conclusion
        )
        if check_id == "test-3.12":
            row["steps"] = [
                {"name": "setup", "status": "completed", "conclusion": "success"},
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
            ]
        first_rows.append(row)
    jobs_1 = tmp_path / "jobs-attempt-1.json"
    write_job_pages(jobs_1, first_rows, paginated=False)
    artifacts_1 = tmp_path / "artifacts-attempt-1.json"
    write_artifact_pages(artifacts_1, blocking_artifact_names(1))
    write_pass_evidence(
        release_tool,
        manifest,
        tmp_path,
        attempt=1,
        run_id=700,
        job_ids=first_ids,
        scenario={"test-3.12": "tests"},
    )
    rerun_id = 4000
    jobs_2 = tmp_path / "jobs-attempt-2.json"
    write_job_pages(
        jobs_2,
        [qualification_job_row("test (3.12)", rerun_id, run_attempt=2)],
        paginated=True,
    )
    artifacts_2 = tmp_path / "artifacts-attempt-2.json"
    write_artifact_pages(artifacts_2, ["qualify-evidence-test-3.12-attempt-2"])
    write_pass_evidence(
        release_tool,
        manifest,
        tmp_path,
        attempt=2,
        run_id=700,
        job_ids={"test-3.12": rerun_id, "lint": 0, "test-3.13": 0, "test-3.14": 0},
        scenario={"test-3.12": "pass"},
    )
    bundle_path = run_collect(
        tool,
        tmp_path,
        manifest_path=manifest_path,
        jobs={1: [jobs_1], 2: [jobs_2]},
        artifacts={1: [artifacts_1], 2: [artifacts_2]},
        run_id=700,
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["current_attempt"] == 2
    first = {row["job_name"]: row for row in bundle["attempts"][0]["jobs"]}
    second = {row["job_name"]: row for row in bundle["attempts"][1]["jobs"]}
    assert second["lint"] == first["lint"]
    assert second["lint"]["evidence_file"] == "attempt-1/qualify-evidence-lint.json"
    assert second["test (3.12)"]["job_id"] == rerun_id
    assert second["test (3.12)"]["execution_attempt"] == 2
    assert second["test (3.12)"]["evidence_file"] == (
        "attempt-2/qualify-evidence-test-3.12.json"
    )
    loaded = release_tool._qualification.load_job_bundle_file(bundle_path, tmp_path)
    report = release_tool._qualification.evaluate_qualification(
        manifest,
        INVENTORY.read_bytes(),
        loaded,
        expected_workflow_run_id=700,
        expected_attempt=2,
    )
    assert report["verdict"] == "pass", report["failures"]


def test_duplicate_scoped_rows_are_preserved_for_refusal(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest = qualification_manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    jobs_path = tmp_path / "jobs.json"
    write_job_pages(
        jobs_path,
        [qualification_job_row("lint", 7001), qualification_job_row("lint", 7002)],
        paginated=False,
    )
    bundle_path = run_collect(
        tool, tmp_path, manifest_path=manifest_path, jobs={1: [jobs_path]}
    )
    jobs = json.loads(bundle_path.read_text(encoding="utf-8"))["attempts"][0]["jobs"]
    assert sorted(row["job_id"] for row in jobs) == [7001, 7002]
