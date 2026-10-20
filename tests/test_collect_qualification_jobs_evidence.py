"""Evidence typing tests for collect_qualification_jobs.

Split from ``tests.test_collect_qualification_jobs``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

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
    "test_advisory_jobs_need_no_evidence",
    "test_concatenated_streaming_pages_decode_without_slurp",
    "test_expired_and_unreadable_payloads_stay_typed",
    "test_live_artifact_supersedes_an_expired_tombstone",
    "test_missing_upload_is_typed_missing",
]


def test_missing_upload_is_typed_missing(
    tool: ModuleType, release_tool: ModuleType, tmp_path: Path
) -> None:
    manifest = qualification_manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    entries = qualification_entries()
    job_ids = {str(entry["id"]): 5000 + index for index, entry in enumerate(entries)}
    rows = [
        qualification_job_row(str(entry["job"]["name"]), job_ids[str(entry["id"])])
        for entry in entries
    ]
    jobs_path = tmp_path / "jobs.json"
    write_job_pages(jobs_path, rows, paginated=False)
    artifacts_path = tmp_path / "artifacts.json"
    write_artifact_pages(
        artifacts_path,
        [name for name in blocking_artifact_names(1) if "test-3.14" not in name],
    )
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
    records = {row["job_name"]: row for row in bundle["attempts"][0]["jobs"]}
    assert records["test (3.14)"]["evidence_error_class"] == "missing"
    assert "evidence_file" not in records["test (3.14)"]
    loaded = release_tool._qualification.load_job_bundle_file(bundle_path, tmp_path)
    report = release_tool._qualification.evaluate_qualification(
        manifest,
        INVENTORY.read_bytes(),
        loaded,
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    assert report["verdict"] == "red"
    failure = next(item for item in report["failures"] if item["job"] == "test (3.14)")
    assert failure["failure_class"] == "missing"


def test_expired_and_unreadable_payloads_stay_typed(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest = qualification_manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        qualification_job_row("lint", 6001),
        qualification_job_row("test (3.12)", 6002),
        qualification_job_row("test (3.13)", 6003),
        qualification_job_row("test (3.14)", 6004),
    ]
    jobs_path = tmp_path / "jobs.json"
    write_job_pages(jobs_path, rows, paginated=False)
    artifacts_path = tmp_path / "artifacts.json"
    write_artifact_pages(
        artifacts_path,
        blocking_artifact_names(1),
        expired={"qualify-evidence-lint-attempt-1"},
    )
    evidence_dir = tmp_path / "attempt-1"
    evidence_dir.mkdir()
    (evidence_dir / "qualify-evidence-test-3.12.json").write_text(
        "not json", encoding="utf-8"
    )
    bundle_path = run_collect(
        tool,
        tmp_path,
        manifest_path=manifest_path,
        jobs={1: [jobs_path]},
        artifacts={1: [artifacts_path]},
    )
    records = {
        row["job_name"]: row
        for row in json.loads(bundle_path.read_text(encoding="utf-8"))["attempts"][0][
            "jobs"
        ]
    }
    assert records["lint"]["evidence_error_class"] == "missing"
    assert "expired" in records["lint"]["evidence_error"]
    assert records["test (3.12)"]["evidence_error_class"] == "harness"
    assert records["test (3.13)"]["evidence_error_class"] == "missing"
    assert records["test (3.14)"]["evidence_error_class"] == "missing"


def test_advisory_jobs_need_no_evidence(
    tool: ModuleType, release_tool: ModuleType, tmp_path: Path
) -> None:
    manifest = qualification_manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    blocking = [
        entry for entry in qualification_entries() if entry["disposition"] == "blocking"
    ]
    job_ids = {str(entry["id"]): 8000 + index for index, entry in enumerate(blocking)}
    rows = [
        qualification_job_row(str(entry["job"]["name"]), job_ids[str(entry["id"])])
        for entry in blocking
    ]
    jobs_path = tmp_path / "jobs.json"
    write_job_pages(jobs_path, rows, paginated=False)
    artifacts_path = tmp_path / "artifacts.json"
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
    assert check_names_for_attempt(bundle, 1) == {
        "lint",
        "test (3.12)",
        "test (3.13)",
        "test (3.14)",
    }
    loaded = release_tool._qualification.load_job_bundle_file(bundle_path, tmp_path)
    report = release_tool._qualification.evaluate_qualification(
        manifest,
        INVENTORY.read_bytes(),
        loaded,
        expected_workflow_run_id=700,
        expected_attempt=1,
    )
    assert report["verdict"] == "pass", report["failures"]
    assert len(report["advisories"]) == 4
    assert all(item["status"] == "missing" for item in report["advisories"])


def test_concatenated_streaming_pages_decode_without_slurp(
    tool: ModuleType, tmp_path: Path
) -> None:
    manifest = qualification_manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    entries = qualification_entries()
    job_ids = {str(entry["id"]): 9100 + index for index, entry in enumerate(entries)}
    rows = [
        qualification_job_row(str(entry["job"]["name"]), job_ids[str(entry["id"])])
        for entry in entries
    ]
    first, second = rows[:3], rows[3:]
    stream = tmp_path / "jobs-stream.json"
    stream.write_text(
        json.dumps({"total_count": len(rows), "jobs": first})
        + "\n"
        + json.dumps({"total_count": len(rows), "jobs": second}),
        encoding="utf-8",
    )
    artifacts_path = tmp_path / "artifacts.json"
    write_artifact_pages(artifacts_path, blocking_artifact_names(1))
    bundle_path = run_collect(
        tool,
        tmp_path,
        manifest_path=manifest_path,
        jobs={1: [stream]},
        artifacts={1: [artifacts_path]},
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert len(bundle["attempts"][0]["jobs"]) == len(entries)


def test_live_artifact_supersedes_an_expired_tombstone(
    tool: ModuleType, release_tool: ModuleType, tmp_path: Path
) -> None:
    manifest = qualification_manifest()
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    jobs_path = tmp_path / "jobs.json"
    write_job_pages(jobs_path, [qualification_job_row("lint", 9301)], paginated=False)
    artifacts_path = tmp_path / "artifacts.json"
    artifacts_path.write_text(
        json.dumps(
            {
                "total_count": 2,
                "artifacts": [
                    {
                        "id": 1,
                        "name": "qualify-evidence-lint-attempt-1",
                        "expired": True,
                    },
                    {
                        "id": 2,
                        "name": "qualify-evidence-lint-attempt-1",
                        "expired": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    write_pass_evidence(
        release_tool,
        manifest,
        tmp_path,
        attempt=1,
        run_id=700,
        job_ids={"lint": 9301, "test-3.12": 0, "test-3.13": 0, "test-3.14": 0},
    )
    bundle_path = run_collect(
        tool,
        tmp_path,
        manifest_path=manifest_path,
        jobs={1: [jobs_path]},
        artifacts={1: [artifacts_path]},
    )
    records = {
        row["job_name"]: row
        for row in json.loads(bundle_path.read_text(encoding="utf-8"))["attempts"][0][
            "jobs"
        ]
    }
    assert records["lint"]["evidence_file"] == "attempt-1/qualify-evidence-lint.json"
