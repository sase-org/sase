"""Tests for :func:`ensure_git_info_exclude_entry`."""

from __future__ import annotations

from pathlib import Path

from sase.workspace_provider.git_exclude import ensure_git_info_exclude_entry


def _make_regular_repo(root: Path) -> Path:
    """Create a minimal ``.git`` directory layout and return ``info/exclude``."""
    info = root / ".git" / "info"
    info.mkdir(parents=True)
    exclude = info / "exclude"
    exclude.write_text("# git ls-files --others --exclude-from=...\n", encoding="utf-8")
    return exclude


def test_writes_pattern_when_missing(tmp_path: Path) -> None:
    exclude = _make_regular_repo(tmp_path)

    ensure_git_info_exclude_entry(str(tmp_path), ".sase/")

    body = exclude.read_text(encoding="utf-8")
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    assert ".sase/" in lines


def test_idempotent(tmp_path: Path) -> None:
    exclude = _make_regular_repo(tmp_path)

    ensure_git_info_exclude_entry(str(tmp_path), ".sase/")
    ensure_git_info_exclude_entry(str(tmp_path), ".sase/")
    ensure_git_info_exclude_entry(str(tmp_path), ".sase/")

    body = exclude.read_text(encoding="utf-8")
    count = sum(1 for line in body.splitlines() if line.strip() == ".sase/")
    assert count == 1


def test_creates_exclude_when_info_missing(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()

    ensure_git_info_exclude_entry(str(tmp_path), ".sase/")

    exclude = tmp_path / ".git" / "info" / "exclude"
    assert exclude.is_file()
    assert ".sase/" in exclude.read_text(encoding="utf-8").splitlines()


def test_handles_worktree_gitdir_file(tmp_path: Path) -> None:
    """A ``.git`` *file* with ``gitdir:`` (worktree layout) is followed."""
    real_git = tmp_path / "real_gitdir"
    (real_git / "info").mkdir(parents=True)
    (real_git / "info" / "exclude").write_text("", encoding="utf-8")

    workspace = tmp_path / "worktree"
    workspace.mkdir()
    (workspace / ".git").write_text(f"gitdir: {real_git}\n", encoding="utf-8")

    ensure_git_info_exclude_entry(str(workspace), ".sase/")

    body = (real_git / "info" / "exclude").read_text(encoding="utf-8")
    assert ".sase/" in [line.strip() for line in body.splitlines()]


def test_noop_when_no_git(tmp_path: Path) -> None:
    ensure_git_info_exclude_entry(str(tmp_path), ".sase/")

    assert not (tmp_path / ".git").exists()


def test_appends_newline_when_missing(tmp_path: Path) -> None:
    """If exclude file lacks trailing newline, helper inserts one before pattern."""
    info = tmp_path / ".git" / "info"
    info.mkdir(parents=True)
    exclude = info / "exclude"
    exclude.write_text("existing-entry", encoding="utf-8")

    ensure_git_info_exclude_entry(str(tmp_path), ".sase/")

    body = exclude.read_text(encoding="utf-8")
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    assert lines == ["existing-entry", ".sase/"]
