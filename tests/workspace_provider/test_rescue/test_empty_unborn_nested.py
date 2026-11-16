"""Empty unborn nested clones must not quarantine a workspace slot."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.workspace_provider._snapshot_capture_source import (
    snapshot_git_repo,
    snapshot_source_fingerprint,
)
from sase.workspace_provider._snapshot_nested import preserve_nested_repositories
from sase.workspace_provider._snapshot_model import PreservationError


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _empty_clone(remote: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(dest, "config", "user.email", "test@test.com")
    _git(dest, "config", "user.name", "Test")
    return dest


@pytest.fixture
def empty_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "empty.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    return remote


def test_empty_unborn_clone_snapshot_returns_none(
    tmp_path: Path, empty_remote: Path
) -> None:
    parent = tmp_path / "parent"
    nested = _empty_clone(
        empty_remote, parent / "sase" / "repos" / "external" / "gh" / "o" / "r"
    )
    assert (
        snapshot_git_repo(
            nested,
            workspace_dir=parent,
            workspace_num=7,
            label="test",
            reason="test",
        )
        is None
    )
    assert snapshot_source_fingerprint(nested)["head"] == "unborn"


def test_empty_unborn_clone_preservation_succeeds(
    tmp_path: Path, empty_remote: Path
) -> None:
    parent = tmp_path / "parent"
    _empty_clone(
        empty_remote, parent / "sase" / "repos" / "external" / "gh" / "o" / "r"
    )
    result = preserve_nested_repositories(
        parent,
        workspace_dir=parent,
        workspace_num=7,
        reason="test",
    )
    assert result.locations == ()


def test_unborn_clone_with_untracked_file_still_raises(
    tmp_path: Path, empty_remote: Path
) -> None:
    parent = tmp_path / "parent"
    nested = _empty_clone(
        empty_remote, parent / "sase" / "repos" / "external" / "gh" / "o" / "r"
    )
    (nested / "new.txt").write_text("work\n", encoding="utf-8")
    with pytest.raises(PreservationError, match="unborn HEAD"):
        snapshot_git_repo(
            nested,
            workspace_dir=parent,
            workspace_num=7,
            label="test",
            reason="test",
        )


def test_unborn_clone_with_staged_file_still_raises(
    tmp_path: Path, empty_remote: Path
) -> None:
    parent = tmp_path / "parent"
    nested = _empty_clone(
        empty_remote, parent / "sase" / "repos" / "external" / "gh" / "o" / "r"
    )
    (nested / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(nested, "add", "--", "staged.txt")
    with pytest.raises(PreservationError, match="unborn HEAD"):
        snapshot_git_repo(
            nested,
            workspace_dir=parent,
            workspace_num=7,
            label="test",
            reason="test",
        )


def test_unborn_head_with_other_branch_commits_still_raises(
    tmp_path: Path, empty_remote: Path
) -> None:
    parent = tmp_path / "parent"
    nested = _empty_clone(
        empty_remote, parent / "sase" / "repos" / "external" / "gh" / "o" / "r"
    )
    (nested / "a.txt").write_text("a\n", encoding="utf-8")
    _git(nested, "add", "-A")
    _git(nested, "commit", "-q", "-m", "first")
    _git(nested, "checkout", "--orphan", "orphan")
    # Orphan checkout: HEAD unborn, but refs/heads/main still holds a commit.
    with pytest.raises(PreservationError, match="unborn HEAD"):
        snapshot_git_repo(
            nested,
            workspace_dir=parent,
            workspace_num=7,
            label="test",
            reason="test",
        )
