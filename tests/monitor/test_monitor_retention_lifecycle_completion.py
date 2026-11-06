"""Monitor retention lifecycle: completion and settlement entry points.

Covers prepared host completion, repeated settlement, stale claims, the proc
settlement entry point, repository-less commands, and unchanged foreign
baseline dirt.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.monitor._settlement_retention import release_monitor_claim
from sase.monitor.output import OutputCapture
from sase.monitor.settlement import settle_claim_and_followup
from sase.running_field import get_claimed_workspaces

from ._retention_fixtures import (
    init_retention_repo,
    make_retention_monitor,
    no_launch_followup,
    read_retention_meta,
    retention_record,
    write_monitor_baselines,
    write_retention_meta,
)


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)


def test_prepared_completion_success_releases_clean(tmp_path: Path) -> None:
    """A committed host completion releases a clean workspace normally."""
    from sase.monitor._host_completion_shared import HOST_COMPLETED_OUTCOME

    repo = init_retention_repo(tmp_path / "ws", dirty=False)
    artifacts_dir, project_file = make_retention_monitor(
        repo, outcome=HOST_COMPLETED_OUTCOME
    )
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    assert get_claimed_workspaces(project_file) == []


def test_prepared_completion_failure_retains_dirty(tmp_path: Path) -> None:
    """A failed completion with unresolved dirt retains the workspace."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo, outcome="not-launchable")
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_repeated_settlement_is_idempotent(tmp_path: Path) -> None:
    """Settling twice pins once and keeps the checkout intact."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)

    first = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="stopped",
        exit_code=None,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=no_launch_followup,
    )
    meta = read_retention_meta(artifacts_dir)
    second = settle_claim_and_followup(
        artifacts_dir,
        meta,
        monitor_state="stopped",
        exit_code=None,
        elapsed_seconds=0.0,
        capture=OutputCapture(),
        timeout_kind=None,
        project_name="proj",
        launch_followup=no_launch_followup,
    )

    assert first.error is None
    assert second.error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"


def test_stale_claim_is_noop(tmp_path: Path) -> None:
    """Settlement against a moved claim never pins or clears the occupant."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    meta = read_retention_meta(artifacts_dir)
    meta["pid"] = 999999999
    write_retention_meta(artifacts_dir, meta)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pid == os.getpid()
    assert claims[0].pinned is False


def test_proc_reconcile_path_retains_dirty(tmp_path: Path) -> None:
    """The proc settlement entry point converges on the same retention."""
    from sase.monitor.proc_adapter import settle_monitor_followup

    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo, next_action=None)
    meta = read_retention_meta(artifacts_dir)
    state: dict[str, object] = {
        "artifacts_dir": artifacts_dir,
        "proc_id": "abc123def456",
        "status": "success",
        "termination_reason": "success",
        "exit_code": 0,
        "monitor_state": "completed",
        "monitor_exit_code": 0,
        "monitor_elapsed_seconds": 0.0,
        "monitor_meta": dict(meta),
    }

    settle_monitor_followup(state)

    # Completed + clean would release; dirty retains through the same adapter.
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert (repo / "tracked.txt").read_text() == "session owned\n"
    _ = SimpleNamespace  # keep import used across protocol variants


def test_repo_less_command_releases(tmp_path: Path) -> None:
    """A positively known non-repository command still releases."""
    workspace = tmp_path / "plain"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("not a repo\n", encoding="utf-8")
    artifacts_dir, project_file = make_retention_monitor(workspace)
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    assert get_claimed_workspaces(project_file) == []
    assert retention_record(artifacts_dir) is None
    assert (workspace / "notes.txt").read_text(encoding="utf-8") == "not a repo\n"


def test_unchanged_foreign_baseline_dirt_releases(tmp_path: Path) -> None:
    """Dirt already present in the starter baseline still releases."""
    repo = init_retention_repo(tmp_path / "ws", dirty=True)
    artifacts_dir, project_file = make_retention_monitor(repo)
    write_monitor_baselines(
        artifacts_dir, [("primary", repo)], capture_fingerprints=True
    )
    meta = read_retention_meta(artifacts_dir)

    error = release_monitor_claim(
        meta, project_name="proj", artifacts_dir=artifacts_dir
    )

    assert error is None
    assert get_claimed_workspaces(project_file) == []
    assert retention_record(artifacts_dir) is None
    assert (repo / "tracked.txt").read_text() == "session owned\n"
