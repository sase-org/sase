"""Green-path qualification transport integration tests.

Split from ``tests.test_qualification_transport_integration``; the original
module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest

from tests._qualification_transport_integration_helpers import (
    REPO,
    RUN_ID,
    fake_gh_fixture,  # noqa: F401 (registers the fake_gh fixture)
    job_row,
    manifest_kwargs,
    produce_evidence,
    release_tool_fixture,  # noqa: F401 (registers the release_tool fixture)
    run_workflow_qualify,
    seed_artifacts,
    seed_jobs,
    seed_zip,
    session_report,
    write_tool_fixture,  # noqa: F401 (registers the write_tool fixture)
)

__all__ = [
    "test_green_run_with_failed_advisory_passes",
    "test_probe_with_failed_setup_names_missing_bindings",
]


def _seed_green_attempt(
    state: Path,
    tmp_path: Path,
    attempt: int,
    rows: list[dict[str, object]],
    checks: tuple[str, ...] = ("lint", "test-3.12", "test-3.13", "test-3.14"),
) -> None:
    names = [f"qualify-evidence-{check}-attempt-{attempt}" for check in checks]
    seed_artifacts(state, names)
    for index, name in enumerate(names):
        leaf = f"qualify-evidence-{checks[index]}.json"
        payload = (tmp_path / "evidence" / f"attempt-{attempt}" / leaf).read_bytes()
        seed_zip(state, 1000 + index, leaf, payload)
    seed_jobs(state, attempt, rows)


def test_green_run_with_failed_advisory_passes(
    release_tool: ModuleType,
    write_tool: ModuleType,
    fake_gh: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = release_tool.seal_manifest(**manifest_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        job_row("lint", 101),
        job_row("test (3.12)", 102),
        job_row("test (3.13)", 103),
        job_row("test (3.14)", 104),
        job_row("visual-test", 105, conclusion="failure"),
    ]
    sessions = {
        name: session_report(tmp_path, f"green-{name}")
        for name in ("test (3.12)", "test (3.13)", "test (3.14)")
    }
    produce_evidence(
        write_tool,
        monkeypatch,
        tmp_path,
        rows=rows,
        attempt=1,
        candidate_id=manifest["candidate_id"],
        generation=manifest["generation"],
        session_reports=sessions,
    )
    _seed_green_attempt(fake_gh, tmp_path, 1, rows)
    outputs, out, observation = run_workflow_qualify(tmp_path, manifest_path)
    calls = (fake_gh / "calls.log").read_text(encoding="utf-8")
    assert (
        f"api repos/{REPO}/actions/runs/{RUN_ID}/attempts/1/jobs "
        "--paginate --slurp" in calls
    )
    assert (
        f"api repos/{REPO}/actions/runs/{RUN_ID}/artifacts --paginate --slurp" in calls
    )
    assert "/attempts/1/artifacts" not in calls
    assert calls.count(f"api repos/{REPO}/actions/artifacts/") == 4
    asset = (
        f"candidate-gen{manifest['generation']}-qualification-run{RUN_ID}-attempt1.json"
    )
    assert outputs["status"] == "0"
    assert observation["asset"] == asset
    assert observation["verdict"] == "pass"
    result = observation["extra"]["qualification"]["result"]
    assert result["verdict"] == "pass"
    assert result["workflow_run_id"] == RUN_ID
    assert result["current_attempt"] == 1
    assert result["rerun_eligible"] is False
    advisory = next(
        item for item in result["advisories"] if item["job_name"] == "visual-test"
    )
    assert "did not pass" in advisory["diagnostic"]
    assert out.is_file()


def test_probe_with_failed_setup_names_missing_bindings(
    release_tool: ModuleType,
    write_tool: ModuleType,
    fake_gh: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = release_tool.seal_manifest(**manifest_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rows = [
        job_row("lint", 401, conclusion="failure"),
        job_row("test (3.12)", 402),
        job_row("test (3.13)", 403),
        job_row("test (3.14)", 404),
    ]
    sessions = {
        name: session_report(tmp_path, f"probe-{name}")
        for name in ("test (3.12)", "test (3.13)", "test (3.14)")
    }
    stderr = (
        "sase_core_rs 0.17.0 is missing 2 of 10 required binding(s):\n"
        "  federation_worker_main\n"
        "  feature_flag_state_get\n"
        "remedy: published core is missing required bindings\n"
    )
    produce_evidence(
        write_tool,
        monkeypatch,
        tmp_path,
        rows=rows,
        attempt=1,
        candidate_id=manifest["candidate_id"],
        generation=manifest["generation"],
        session_reports=sessions,
        bindings_stderr=stderr,
        lint_steps=("failure", "skipped"),
        installed_core_version="0.17.0",
    )
    _seed_green_attempt(fake_gh, tmp_path, 1, rows)
    outputs, _, observation = run_workflow_qualify(
        tmp_path, manifest_path, tested_core_version="0.17.0"
    )
    asset = (
        f"candidate-gen{manifest['generation']}-qualification-run{RUN_ID}-attempt1.json"
    )
    assert outputs["status"] == str(release_tool.EXIT_REFUSED)
    assert observation["asset"] == asset
    result = observation["extra"]["qualification"]["result"]
    assert result["verdict"] == "red"
    assert result["rerun_eligible"] is False
    failure = next(item for item in result["failures"] if item["job"] == "lint")
    assert failure["failure_class"] == "harness"
    diagnostics = " ".join(failure["diagnostics"])
    assert "federation_worker_main" in diagnostics
    assert "feature_flag_state_get" in diagnostics
    assert "QUALIFY_RED" in observation["reason"]
