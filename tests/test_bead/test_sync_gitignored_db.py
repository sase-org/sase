"""Tests for gitignored bead database files during sase.bead.sync writes."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.bead.sync import commit_epic_graph_checkpoint, git_sync

from .sync_test_helpers import init_git_repo


def _init_repo_with_beads_db_ignored(tmp_path: Path) -> None:
    """Init a git repo with ``sdd/beads/beads.db*`` listed in ``.gitignore``."""
    init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("sdd/beads/beads.db*\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add gitignore"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )


def test_git_sync_succeeds_when_gitignored_beads_db_present(tmp_path):
    _init_repo_with_beads_db_ignored(tmp_path)

    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"test"}\n')
    (beads_dir / "beads.db").write_bytes(b"SQLite")
    stream = beads_dir / "events/streams/sase-1.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"sase-1:000001"}\n')

    git_sync(beads_dir)

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "sdd/beads/issues.jsonl" in staged
    assert "sdd/beads/events/streams/sase-1.jsonl" in staged
    assert "sdd/beads/beads.db" not in staged


def test_commit_epic_graph_checkpoint_succeeds_when_gitignored_beads_db_present(
    tmp_path,
):
    _init_repo_with_beads_db_ignored(tmp_path)

    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"test"}\n')
    (beads_dir / "beads.db").write_bytes(b"SQLite")
    (beads_dir / "beads.db-wal").write_bytes(b"WAL")
    (beads_dir / "beads.db-shm").write_bytes(b"SHM")
    stream = beads_dir / "events/streams/sase-1.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"sase-1:000001"}\n')

    committed = commit_epic_graph_checkpoint(beads_dir, "sase-1")

    assert committed is True
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "sdd/beads/beads.db" not in files
    assert "sdd/beads/beads.db-wal" not in files
    assert "sdd/beads/beads.db-shm" not in files
    assert "sdd/beads/issues.jsonl" in files
    assert "sdd/beads/events/streams/sase-1.jsonl" in files


def test_commit_epic_graph_checkpoint_noops_when_only_ignored_db_changed(tmp_path):
    _init_repo_with_beads_db_ignored(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "beads.db").write_bytes(b"SQLite")

    committed = commit_epic_graph_checkpoint(beads_dir, "sase-1")

    assert committed is False
    log_count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert log_count == "2"  # init + .gitignore commit only
