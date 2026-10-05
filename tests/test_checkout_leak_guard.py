"""Tests for the checkout-leak guard and the SDD-init repo guard helper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests._checkout_leak_guard import (
    CheckoutSnapshot,
    classify_checkout_change,
    collect_range_commits,
    find_new_sdd_entries,
    git_head,
    is_test_identity_email,
    take_checkout_snapshot,
)
from tests._conftest_environment import (
    _REPO_ROOT,
    _is_repo_checkout_workspace,
)

_GIT_AVAILABLE = (
    subprocess.run(["git", "--version"], capture_output=True).returncode == 0
)


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    merged = dict(os.environ)
    if env:
        merged.update(env)
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=merged,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    (repo / "file.txt").write_text("data\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-m", "initial")


_FOREIGN_ENV = {
    "GIT_AUTHOR_NAME": "Foreign",
    "GIT_AUTHOR_EMAIL": "foreign@example.com",
    "GIT_COMMITTER_NAME": "Foreign",
    "GIT_COMMITTER_EMAIL": "foreign@example.com",
}


def test_repo_checkout_helper_refuses_suite_checkout() -> None:
    """The 5a guard classifies the suite checkout (and children) as in-scope."""
    assert _is_repo_checkout_workspace(_REPO_ROOT) is not None
    assert _is_repo_checkout_workspace(_REPO_ROOT / "src") is not None


def test_repo_checkout_helper_ignores_tmp(tmp_path: Path) -> None:
    """Workspaces outside the checkout never trip the 5a guard."""
    assert _is_repo_checkout_workspace(tmp_path) is None


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
def test_test_identity_commit_is_a_leak(tmp_path: Path) -> None:
    """A test-identity commit between snapshots is a leak."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    start = take_checkout_snapshot(repo)
    assert not start.disabled
    (repo / "second.txt").write_text("more\n", encoding="utf-8")
    _git(repo, "add", "second.txt")
    _git(repo, "commit", "-m", "test change")
    end = take_checkout_snapshot(repo)
    commits = collect_range_commits(repo, start.head)
    assert commits
    assert is_test_identity_email(commits[0].author_email)
    leak = classify_checkout_change(start, end, commits)
    assert leak is not None
    assert leak.test_commits


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
def test_foreign_identity_commit_is_not_a_leak(tmp_path: Path) -> None:
    """A foreign-identity commit is only a note, never a failure."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    start = take_checkout_snapshot(repo)
    (repo / "second.txt").write_text("more\n", encoding="utf-8")
    _git(repo, "add", "second.txt")
    _git(
        repo,
        "-c",
        "user.email=foreign@example.com",
        "-c",
        "user.name=Foreign",
        "commit",
        "-m",
        "foreign change",
        env=_FOREIGN_ENV,
    )
    end = take_checkout_snapshot(repo)
    commits = collect_range_commits(repo, start.head)
    assert commits
    assert not is_test_identity_email(commits[0].author_email)
    assert classify_checkout_change(start, end, commits) is None


@pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")
def test_new_untracked_sdd_readme_is_a_leak(tmp_path: Path) -> None:
    """A new untracked ``sdd/README.md`` status entry is a leak."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    start = take_checkout_snapshot(repo)
    assert start.sdd_entries == frozenset()
    sdd_readme = repo / "sdd" / "README.md"
    sdd_readme.parent.mkdir(parents=True, exist_ok=True)
    sdd_readme.write_text("guide\n", encoding="utf-8")
    end = take_checkout_snapshot(repo)
    assert end.sdd_entries
    new_entries = find_new_sdd_entries(start.sdd_entries, end.sdd_entries)
    assert new_entries
    leak = classify_checkout_change(start, end, [])
    assert leak is not None
    assert leak.new_sdd_entries == new_entries


def test_non_git_root_disables_the_guard(tmp_path: Path) -> None:
    """A root that is not a git checkout disables the guard silently."""
    plain = tmp_path / "plain"
    plain.mkdir()
    snapshot = take_checkout_snapshot(plain)
    assert snapshot.disabled is True
    assert (
        classify_checkout_change(snapshot, CheckoutSnapshot(disabled=True), []) is None
    )
    assert git_head(plain) is None
