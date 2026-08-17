"""Tests for bead state cleanliness probes in sase.bead.sync."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.bead._sync_git import BeadWorkLaunchCommitError
from sase.bead.sync import _is_in_tree_beads_dir, bead_state_is_clean

from .sync_test_helpers import init_git_repo


def test_split_beads_sidecar_is_not_an_in_tree_store(tmp_path: Path) -> None:
    assert not _is_in_tree_beads_dir(tmp_path / "sase" / "repos" / "beads")


def test_sync_status_clean_when_no_jsonl(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    assert bead_state_is_clean(beads_dir) is True


def test_sync_status_clean_when_committed(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text("")
    subprocess.run(["git", "add", str(jsonl)], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add jsonl"], cwd=tmp_path, capture_output=True
    )
    assert bead_state_is_clean(beads_dir) is True


def test_sync_status_dirty_when_modified(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text("")
    subprocess.run(["git", "add", str(jsonl)], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add jsonl"], cwd=tmp_path, capture_output=True
    )
    jsonl.write_text('{"id":"test"}\n')
    assert bead_state_is_clean(beads_dir) is False


def test_sync_status_dirty_when_event_stream_untracked(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text("")
    subprocess.run(["git", "add", "sdd/beads"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add bead state"],
        cwd=tmp_path,
        capture_output=True,
    )

    stream = beads_dir / "events/streams/test.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"test"}\n')

    assert bead_state_is_clean(beads_dir) is False


def test_sync_status_dirty_when_probe_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)

    def fail_probe(_beads_dir: Path, _repo_root: Path) -> list[str]:
        raise BeadWorkLaunchCommitError("git ls-files failed")

    monkeypatch.setattr("sase.bead._sync_git._list_bead_state_changes", fail_probe)

    assert bead_state_is_clean(beads_dir) is False


def test_sync_status_dirty_when_staged_only(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    subprocess.run(
        ["git", "add", str(jsonl)], cwd=tmp_path, capture_output=True, check=True
    )

    # Staged but not committed — both layers must agree this is dirty.
    assert bead_state_is_clean(beads_dir) is False
    changed = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "sdd/beads/issues.jsonl" in changed
