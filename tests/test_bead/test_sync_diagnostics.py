"""Tests for bead_sync_diagnostics in sase.bead.sync."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.bead.sync import bead_sync_diagnostics

from .sync_test_helpers import init_git_repo


def _redirect_sync_logs(monkeypatch: pytest.MonkeyPatch, log_dir: Path) -> None:
    log_dir.mkdir()

    def fake_ensure_sase_directory(name: str) -> Path:
        assert name == "bead_push_logs"
        return log_dir

    monkeypatch.setattr(
        "sase.core.paths.ensure_sase_directory",
        fake_ensure_sase_directory,
    )


def _write_sync_log(
    log_dir: Path,
    name: str,
    repo_root: Path,
    *,
    event: str,
    mtime: float,
    error: str | None = None,
) -> Path:
    records = [
        {
            "ts": mtime,
            "event": "started",
            "repo_root": str(repo_root.resolve()),
            "beads_dir": str((repo_root / "beads").resolve(strict=False)),
        }
    ]
    if event == "failed":
        records.append(
            {
                "ts": mtime + 0.1,
                "event": "failed",
                "error": error or "injected failure",
                "integrated": False,
            }
        )
    else:
        records.append(
            {
                "ts": mtime + 0.1,
                "event": event,
                "pushed": event == "completed",
                "integrated": event == "completed",
            }
        )
    path = log_dir / name
    path.write_text(
        "".join(f"{json.dumps(record, sort_keys=True)}\n" for record in records),
        encoding="utf-8",
    )
    os.utime(path, (mtime, mtime))
    return path


def test_bead_sync_diagnostics_reports_recurring_managed_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    log_dir = tmp_path / "logs"
    _redirect_sync_logs(monkeypatch, log_dir)

    incident_error = (
        "Could not apply 17e1c56a... chore(beads): claim sase-9w.6; "
        "semantic bead conflict resolution failed: validation: cannot merge "
        "non-append-only bead event stream sase-9w: theirs rewrote base event 21"
    )
    _write_sync_log(
        log_dir,
        "sync-20260727T120000Z-1.log",
        tmp_path,
        event="failed",
        error=incident_error,
        mtime=1,
    )
    latest = _write_sync_log(
        log_dir,
        "sync-20260727T120001Z-2.log",
        tmp_path,
        event="failed",
        error=incident_error,
        mtime=2,
    )

    messages = bead_sync_diagnostics(beads_dir)

    warning = next(
        message for message in messages if "bead managed sync has" in message
    )
    assert "2 consecutive failed integration(s)" in warning
    assert "dominant error class: unresolved rebase (2/2)" in warning
    assert str(latest) in warning


def test_bead_sync_diagnostics_stays_quiet_after_healthy_same_clone_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    beads_dir = repo / "beads"
    beads_dir.mkdir()
    other_repo = tmp_path / "other"
    other_repo.mkdir()
    init_git_repo(other_repo)
    log_dir = tmp_path / "logs"
    _redirect_sync_logs(monkeypatch, log_dir)

    _write_sync_log(
        log_dir,
        "sync-20260727T120000Z-1.log",
        repo,
        event="failed",
        mtime=1,
        error="git rebase failed: Could not apply abc123",
    )
    _write_sync_log(
        log_dir,
        "sync-20260727T120001Z-2.log",
        repo,
        event="completed",
        mtime=2,
    )
    _write_sync_log(
        log_dir,
        "sync-20260727T120002Z-3.log",
        other_repo,
        event="failed",
        mtime=3,
        error="git rebase failed: Could not apply def456",
    )

    assert bead_sync_diagnostics(beads_dir) == []
