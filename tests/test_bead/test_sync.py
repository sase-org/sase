"""Tests for git_sync staging in sase.bead.sync."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.bead.sync import commit_epic_graph_checkpoint, git_sync
from sase.sdd._repository_transaction import SddRepositoryHealthError

from .sync_test_helpers import init_git_repo


def test_git_sync_stages_bead_state(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    stream = beads_dir / "events/streams/test.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"test"}\n')

    git_sync(beads_dir)

    # Verify the bead state was staged but not committed.
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert "issues.jsonl" in result.stdout
    assert "events/streams/test.jsonl" in result.stdout


def test_git_sync_noop_when_clean(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text("")
    subprocess.run(["git", "add", str(jsonl)], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True
    )

    # Sync again with no changes — nothing should be staged
    git_sync(beads_dir)
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""


@pytest.mark.parametrize("marker", ["rebase-merge", "MERGE_HEAD"])
def test_bead_git_writers_refuse_operations_before_staging(
    tmp_path: Path,
    marker: str,
) -> None:
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    state = beads_dir / "issues.jsonl"
    state.write_text('{"id":"test"}\n', encoding="utf-8")
    marker_path = tmp_path / ".git" / marker
    if "." in marker:
        marker_path.write_text("blocked\n", encoding="utf-8")
    else:
        marker_path.mkdir()
    before = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    with pytest.raises(SddRepositoryHealthError):
        git_sync(beads_dir)
    with pytest.raises(SddRepositoryHealthError):
        commit_epic_graph_checkpoint(beads_dir, "sase-1")

    assert state.read_text(encoding="utf-8") == '{"id":"test"}\n'
    assert (
        subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == before
    )
