"""Failed-only retry qualification transport integration tests.

Split from ``tests.test_qualification_transport_integration``; the original
module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest

from tests._qualification_transport_integration_helpers import (
    RUN_ID,
    collect_tool_fixture,  # noqa: F401 (registers the collect_tool fixture)
    fake_gh_fixture,  # noqa: F401 (registers the fake_gh fixture)
    job_row,
    manifest_kwargs,
    produce_evidence,
    qualify,
    release_tool_fixture,  # noqa: F401 (registers the release_tool fixture)
    run_collect,
    seed_artifacts,
    seed_jobs,
    seed_zip,
    session_report,
    write_tool_fixture,  # noqa: F401 (registers the write_tool fixture)
)

__all__ = [
    "test_failed_only_retry_stays_green",
]


def test_failed_only_retry_stays_green(
    collect_tool: ModuleType,
    release_tool: ModuleType,
    write_tool: ModuleType,
    fake_gh: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = release_tool.seal_manifest(**manifest_kwargs())  # type: ignore[arg-type]
    manifest_path = tmp_path / "candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    first_rows = [
        job_row("lint", 201),
        job_row("test (3.12)", 202, conclusion="failure"),
        job_row("test (3.13)", 203),
        job_row("test (3.14)", 204),
    ]
    first_sessions = {
        "test (3.12)": session_report(tmp_path, "red-312", failed=1),
        "test (3.13)": session_report(tmp_path, "green-313"),
        "test (3.14)": session_report(tmp_path, "green-314"),
    }
    produce_evidence(
        write_tool,
        monkeypatch,
        tmp_path,
        rows=first_rows,
        attempt=1,
        candidate_id=manifest["candidate_id"],
        generation=manifest["generation"],
        session_reports=first_sessions,
    )
    retry_rows = [job_row("test (3.12)", 302, run_attempt=2)]
    retry_sessions = {"test (3.12)": session_report(tmp_path, "retry-312")}
    produce_evidence(
        write_tool,
        monkeypatch,
        tmp_path,
        rows=retry_rows,
        attempt=2,
        candidate_id=manifest["candidate_id"],
        generation=manifest["generation"],
        session_reports=retry_sessions,
    )
    seed_jobs(fake_gh, 1, first_rows)
    seed_jobs(fake_gh, 2, retry_rows)
    names = [
        "qualify-evidence-lint-attempt-1",
        "qualify-evidence-test-3.12-attempt-1",
        "qualify-evidence-test-3.13-attempt-1",
        "qualify-evidence-test-3.14-attempt-1",
        "qualify-evidence-test-3.12-attempt-2",
    ]
    seed_artifacts(fake_gh, names)
    for index, name in enumerate(names):
        check = name.removeprefix("qualify-evidence-").rsplit("-attempt-", 1)
        payload = (
            tmp_path
            / "evidence"
            / f"attempt-{check[1]}"
            / f"qualify-evidence-{check[0]}.json"
        ).read_bytes()
        seed_zip(fake_gh, 1000 + index, f"qualify-evidence-{check[0]}.json", payload)
    jobs_path = run_collect(collect_tool, tmp_path, manifest_path, attempts=2)
    asset = (
        f"candidate-gen{manifest['generation']}-qualification-run{RUN_ID}-attempt2.json"
    )
    code, _, observation = qualify(
        release_tool, tmp_path, manifest_path, jobs_path, attempt=2, asset=asset
    )
    assert code == 0
    result = observation["extra"]["qualification"]["result"]
    assert result["verdict"] == "pass"
    assert result["current_attempt"] == 2
    assert result["attempt_results"][0]["verdict"] == "red"
    assert result["attempt_results"][1]["verdict"] == "pass"
