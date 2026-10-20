"""Refusal and fetch-evidence tests for collect_qualification_jobs.

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
    collect_tool_fixture,  # noqa: F401 (registers the tool fixture)
    qualification_job_row,
    qualification_manifest,
    write_job_pages,
)

__all__ = [
    "test_duplicate_artifact_identities_refuse",
    "test_fetch_evidence_fails_closed_on_api_errors",
    "test_fetch_evidence_refuses_conflicting_payload_bytes",
    "test_malformed_pages_refuse",
    "test_noncontiguous_attempts_refuse",
]


def patch_gh_transport(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch, handler: object
) -> None:
    monkeypatch.setattr(tool, "_run_gh", handler)


def test_noncontiguous_attempts_refuse(tool: ModuleType, tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(qualification_manifest()), encoding="utf-8")
    jobs_1 = tmp_path / "jobs-1.json"
    write_job_pages(jobs_1, [qualification_job_row("lint", 9001)], paginated=False)
    jobs_3 = tmp_path / "jobs-3.json"
    write_job_pages(
        jobs_3, [qualification_job_row("lint", 9002, run_attempt=3)], paginated=False
    )
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
            f"1={jobs_1}",
            "--attempt-jobs",
            f"3={jobs_3}",
            "--out",
            str(tmp_path / "bundle.json"),
        ]
    )
    assert status == 2


def test_malformed_pages_refuse(tool: ModuleType, tmp_path: Path) -> None:
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(qualification_manifest()), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"total_count": 0}), encoding="utf-8")
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
            f"1={bad}",
            "--out",
            str(tmp_path / "bundle.json"),
        ]
    )
    assert status == 2


def test_duplicate_artifact_identities_refuse(
    tool: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(qualification_manifest()), encoding="utf-8")
    jobs_path = tmp_path / "jobs.json"
    write_job_pages(jobs_path, [qualification_job_row("lint", 9201)], paginated=False)
    artifacts_path = tmp_path / "artifacts.json"
    artifacts_path.write_text(
        json.dumps(
            {
                "total_count": 2,
                "artifacts": [
                    {
                        "id": 1,
                        "name": "qualify-evidence-lint-attempt-1",
                        "expired": False,
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
            "--attempt-artifacts",
            f"1={artifacts_path}",
            "--out",
            str(tmp_path / "bundle.json"),
        ]
    )
    assert status == 2
    assert "duplicate artifact identity" in capsys.readouterr().err


def test_fetch_evidence_fails_closed_on_api_errors(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def refused(api_args: list[str]) -> tuple[int, bytes, str]:
        return 1, b"", "forbidden"

    patch_gh_transport(tool, monkeypatch, refused)
    status = tool.main(
        [
            "fetch-evidence",
            "--repo",
            "sase-org/sase",
            "--run-id",
            "700",
            "--attempts",
            "1",
            "--jobs-dir",
            str(tmp_path / "jobs-pages"),
            "--artifacts-file",
            str(tmp_path / "artifacts-pages" / "run.json"),
            "--evidence-root",
            str(tmp_path / "evidence"),
            "--zips-dir",
            str(tmp_path / "zips"),
        ]
    )
    assert status == tool.EXIT_ERROR


def test_fetch_evidence_refuses_conflicting_payload_bytes(
    tool: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import io
    import zipfile

    def first() -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("qualify-evidence-lint.json", json.dumps({"artifact": 1}))
        return buffer.getvalue()

    def second() -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("qualify-evidence-lint.json", json.dumps({"artifact": 2}))
        return buffer.getvalue()

    artifacts = {
        "total_count": 2,
        "artifacts": [
            {"id": 11, "name": "qualify-evidence-lint-attempt-1", "expired": False},
            {
                "id": 12,
                "name": "qualify-evidence-lint-attempt-1x-attempt-1",
                "expired": False,
            },
        ],
    }
    zips = {"11": first(), "12": second()}

    def handler(api_args: list[str]) -> tuple[int, bytes, str]:
        endpoint = api_args[0]
        if endpoint.endswith("/jobs"):
            return 0, json.dumps({"total_count": 0, "jobs": []}).encode(), ""
        if endpoint.endswith("/artifacts"):
            return 0, json.dumps([artifacts]).encode(), ""
        assert endpoint.startswith("repos/sase-org/sase/actions/artifacts/")
        artifact_id = endpoint.split("/")[-2]
        return 0, zips[artifact_id], ""

    patch_gh_transport(tool, monkeypatch, handler)
    status = tool.main(
        [
            "fetch-evidence",
            "--repo",
            "sase-org/sase",
            "--run-id",
            "700",
            "--attempts",
            "1",
            "--jobs-dir",
            str(tmp_path / "jobs-pages"),
            "--artifacts-file",
            str(tmp_path / "artifacts-pages" / "run.json"),
            "--evidence-root",
            str(tmp_path / "evidence"),
            "--zips-dir",
            str(tmp_path / "zips"),
        ]
    )
    assert status == tool.EXIT_ERROR
    assert (
        tmp_path / "evidence" / "attempt-1" / "qualify-evidence-lint.json"
    ).is_file()
