"""Refusal-path qualification transport integration tests.

Split from ``tests.test_qualification_transport_integration``; the original
module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from tests._qualification_transport_integration_helpers import (
    INVENTORY,
    RELEASE_SCRIPT,
    REPO,
    RUN_ID,
    collect_tool_fixture,  # noqa: F401 (registers the collect_tool fixture)
    fake_gh_fixture,  # noqa: F401 (registers the fake_gh fixture)
    job_row,
    manifest_kwargs,
    release_tool_fixture,  # noqa: F401 (registers the release_tool fixture)
)

__all__ = [
    "test_api_failure_stays_typed_red_through_cli_and_steward",
    "test_wrong_caller_and_duplicate_scoped_rows_stay_red",
]


def test_api_failure_stays_typed_red_through_cli_and_steward(
    collect_tool: ModuleType,
    release_tool: ModuleType,
    fake_gh: Path,
    tmp_path: Path,
) -> None:
    manifest = release_tool.seal_manifest(**manifest_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    # No jobs seed: the fake transport has no pages, so every fetch fails
    # and the caller records the workflow's typed-red fallback, verbatim.
    code = collect_tool.main(
        [
            "fetch-evidence",
            "--repo",
            REPO,
            "--run-id",
            str(RUN_ID),
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
    assert code == collect_tool.EXIT_ERROR
    fallback = tmp_path / "jobs.json"
    fallback.write_text(
        "qualification fact fetch failed; see the job log\n", encoding="utf-8"
    )
    asset = (
        f"candidate-gen{manifest['generation']}-qualification-run{RUN_ID}-attempt1.json"
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "qualify",
            "--manifest",
            str(manifest_path),
            "--inventory",
            str(INVENTORY),
            "--jobs",
            str(fallback),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--run-id",
            str(RUN_ID),
            "--attempt",
            "1",
            "--out",
            str(tmp_path / asset),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == release_tool.EXIT_REFUSED
    observation = json.loads((tmp_path / asset).read_text(encoding="utf-8"))
    assert observation["asset"] == asset
    assert observation["verdict"] == "red"
    assert observation["reason"].startswith("QUALIFY_RED")
    result = observation["extra"]["qualification"]["result"]
    assert result["workflow_run_id"] == RUN_ID
    assert result["current_attempt"] == 1
    assert result["rerun_eligible"] is False
    assert result["input_error"] != ""
    assert "unreadable JSON" in result["input_error"]
    # The steward reads the same observation through the evaluate CLI.
    evaluated = subprocess.run(
        [
            sys.executable,
            str(RELEASE_SCRIPT),
            "evaluate",
            "--manifest",
            str(manifest_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert evaluated.returncode == release_tool.EXIT_REFUSED
    payload = json.loads(evaluated.stdout)
    clause = next(
        item for item in payload["clauses"] if item["name"] == "qualification"
    )
    assert clause["ok"] is False
    assert "QUALIFY_RED" in clause["detail"]
    assert payload["rerun_eligible"] is False


def test_wrong_caller_and_duplicate_scoped_rows_stay_red(
    collect_tool: ModuleType,
    release_tool: ModuleType,
    tmp_path: Path,
) -> None:
    manifest = release_tool.seal_manifest(**manifest_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        dict(job_row("lint", 501), name="other-ci / lint"),
        job_row("lint", 502),
        job_row("lint", 503),
    ]
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps({"total_count": 3, "jobs": rows}), encoding="utf-8")
    artifacts_path = tmp_path / "artifacts.json"
    artifacts_path.write_text(json.dumps({"total_count": 0, "artifacts": []}))
    code = collect_tool.main(
        [
            "--inventory",
            str(INVENTORY),
            "--manifest",
            str(manifest_path),
            "--run-id",
            str(RUN_ID),
            "--caller-job",
            "qualify-ci",
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
    assert code == 0
    bundle = json.loads((tmp_path / "bundle.json").read_text(encoding="utf-8"))
    assert sorted(row["job_id"] for row in bundle["attempts"][0]["jobs"]) == [502, 503]
    asset = "candidate-gen1-qualification-run700-attempt1.json"
    out = tmp_path / asset
    qualify_code = release_tool.main(
        [
            "qualify",
            "--manifest",
            str(manifest_path),
            "--inventory",
            str(INVENTORY),
            "--jobs",
            str(tmp_path / "bundle.json"),
            "--evidence-dir",
            str(tmp_path),
            "--run-id",
            str(RUN_ID),
            "--attempt",
            "1",
            "--out",
            str(out),
        ]
    )
    assert qualify_code == release_tool.EXIT_REFUSED
    result = json.loads(out.read_text(encoding="utf-8"))["extra"]["qualification"][
        "result"
    ]
    assert result["verdict"] == "red"
    failure = next(item for item in result["failures"] if item["job"] == "lint")
    assert failure["failure_class"] == "harness"
    assert "ambiguous" in " ".join(failure["diagnostics"])
