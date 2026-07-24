"""Tests for the git VCS provider — commit and branch operations.

Covers: commit, amend, rename_branch, rebase, archive, prune, stash_and_clean.
"""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from sase.git_lock_retry import ENV_GIT_LOCK_RETRY_DELAYS
from sase.vcs_provider.plugins.bare_git import BareGitPlugin

# === Tests for commit ===


# === Tests for amend ===


# === Tests for rename_branch ===


# === Tests for rebase ===


# === Tests for archive ===


def _git_cmds(mock_run: MagicMock) -> list[list[str]]:
    """Return the git argv list of every subprocess.run call, in order."""
    return [call[0][0] for call in mock_run.call_args_list]


def test_git_revision_id_resolves_head_to_full_commit(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.test"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "tracked.txt").write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "seed", "-q"], cwd=tmp_path, check=True)

    revision = BareGitPlugin().vcs_revision_id("HEAD", str(tmp_path))

    assert len(revision) == 40
    assert (
        revision
        == subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )


def test_git_runner_removes_persistent_index_lock_after_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("content\n", encoding="utf-8")
    lock_path = tmp_path / ".git" / "index.lock"
    lock_path.touch()
    monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, "0.001")

    success, error = BareGitPlugin().vcs_add_remove(str(tmp_path))

    assert success is True
    assert error is None
    assert not lock_path.exists()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert staged.stdout.splitlines() == ["tracked.txt"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_archive_success(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_archive on success (not on the target branch)."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="abc123\n", stderr=""),  # rev-parse commit
        MagicMock(returncode=1, stdout="", stderr=""),  # archive tag absent
        MagicMock(returncode=0, stdout="", stderr=""),  # git tag
        MagicMock(returncode=0, stdout="master\n", stderr=""),  # current branch
        MagicMock(returncode=0, stdout="", stderr=""),  # git branch -D
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_archive("old-feature", "/workspace")

    assert success is True
    assert error is None
    cmds = _git_cmds(mock_run)
    assert ["git", "tag", "archive/old-feature", "abc123"] in cmds
    assert ["git", "branch", "-D", "old-feature"] in cmds
    # No checkout needed: the worktree was on master, not the target branch.
    assert not any(cmd[:2] == ["git", "checkout"] for cmd in cmds)


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_archive_normalizes_origin_prefix(mock_run: MagicMock) -> None:
    """vcs_archive tags and deletes the local branch for origin/<branch>."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="abc123\n", stderr=""),  # rev-parse commit
        MagicMock(returncode=1, stdout="", stderr=""),  # archive tag absent
        MagicMock(returncode=0, stdout="", stderr=""),  # git tag
        MagicMock(returncode=0, stdout="master\n", stderr=""),  # current branch
        MagicMock(returncode=0, stdout="", stderr=""),  # git branch -D
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_archive("origin/old-feature", "/workspace")

    assert success is True
    assert error is None
    cmds = _git_cmds(mock_run)
    assert ["git", "tag", "archive/old-feature", "abc123"] in cmds
    assert ["git", "branch", "-D", "old-feature"] in cmds


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_archive_existing_matching_tag_is_idempotent(mock_run: MagicMock) -> None:
    """An archive tag at the same commit is accepted; the branch is deleted."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="abc123\n", stderr=""),  # rev-parse commit
        MagicMock(returncode=0, stdout="abc123\n", stderr=""),  # tag exists, matches
        MagicMock(returncode=0, stdout="master\n", stderr=""),  # current branch
        MagicMock(returncode=0, stdout="", stderr=""),  # git branch -D
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_archive("old-feature", "/workspace")

    assert success is True
    assert error is None
    cmds = _git_cmds(mock_run)
    # The tag already exists, so we must not try to recreate it.
    assert not any(cmd[:2] == ["git", "tag"] for cmd in cmds)
    assert ["git", "branch", "-D", "old-feature"] in cmds


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_archive_existing_conflicting_tag_fails(mock_run: MagicMock) -> None:
    """A conflicting archive tag fails before the branch is deleted."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="abc123\n", stderr=""),  # rev-parse commit
        MagicMock(returncode=0, stdout="def456\n", stderr=""),  # tag exists, differs
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_archive("old-feature", "/workspace")

    assert success is False
    assert error is not None
    assert "archive/old-feature" in error
    # Must not delete the branch when the archive tag conflicts.
    cmds = _git_cmds(mock_run)
    assert not any(cmd[:3] == ["git", "branch", "-D"] for cmd in cmds)


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_archive_current_branch_checks_out_default(mock_run: MagicMock) -> None:
    """When on the target branch, checkout the default branch before delete."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="abc123\n", stderr=""),  # rev-parse commit
        MagicMock(returncode=1, stdout="", stderr=""),  # archive tag absent
        MagicMock(returncode=0, stdout="", stderr=""),  # git tag
        MagicMock(returncode=0, stdout="old-feature\n", stderr=""),  # ON target branch
        MagicMock(  # _get_default_branch via origin/HEAD
            returncode=0, stdout="refs/remotes/origin/master\n", stderr=""
        ),
        MagicMock(returncode=0, stdout="", stderr=""),  # git checkout master
        MagicMock(returncode=0, stdout="", stderr=""),  # git branch -D
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_archive("old-feature", "/workspace")

    assert success is True
    assert error is None
    cmds = _git_cmds(mock_run)
    checkout_idx = cmds.index(["git", "checkout", "master"])
    delete_idx = cmds.index(["git", "branch", "-D", "old-feature"])
    # The checkout off the target branch must precede the delete.
    assert checkout_idx < delete_idx


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_archive_checkout_failure_returns_error(mock_run: MagicMock) -> None:
    """A failed checkout off the target branch surfaces a clear failure."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="abc123\n", stderr=""),  # rev-parse commit
        MagicMock(returncode=1, stdout="", stderr=""),  # archive tag absent
        MagicMock(returncode=0, stdout="", stderr=""),  # git tag
        MagicMock(returncode=0, stdout="old-feature\n", stderr=""),  # ON target branch
        MagicMock(  # _get_default_branch via origin/HEAD
            returncode=0, stdout="refs/remotes/origin/master\n", stderr=""
        ),
        MagicMock(returncode=1, stdout="", stderr="checkout failed"),  # git checkout
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_archive("old-feature", "/workspace")

    assert success is False
    assert error is not None
    assert "git checkout failed" in error
    # The branch must not be deleted if we could not move off it.
    cmds = _git_cmds(mock_run)
    assert not any(cmd[:3] == ["git", "branch", "-D"] for cmd in cmds)


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_archive_branch_delete_fails(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_archive when branch delete fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="abc123\n", stderr=""),  # rev-parse commit
        MagicMock(returncode=1, stdout="", stderr=""),  # archive tag absent
        MagicMock(returncode=0, stdout="", stderr=""),  # tag succeeds
        MagicMock(returncode=0, stdout="master\n", stderr=""),  # current branch
        MagicMock(returncode=1, stdout="", stderr="branch not found"),  # delete fails
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_archive("old-feature", "/workspace")

    assert success is False
    assert error is not None
    assert "git branch -D failed" in error


# === Tests for prune ===


# === Tests for stash_and_clean ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_stash_and_clean_status_fails(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_stash_and_clean when status check fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="status error")

    plugin = BareGitPlugin()
    success, error = plugin.vcs_stash_and_clean("backup-msg", "/workspace", timeout=300)

    assert success is False
    assert error is not None
    assert "git status failed" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_stash_and_clean_no_changes(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_stash_and_clean with clean workspace."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = BareGitPlugin()
    success, error = plugin.vcs_stash_and_clean("backup-msg", "/workspace", timeout=300)

    assert success is True
    assert error is None
    assert mock_run.call_count == 1  # only status check, no stash


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_stash_and_clean_stash_fails(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_stash_and_clean when stash push fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout=" M file.txt\n", stderr=""),  # status
        MagicMock(returncode=1, stdout="", stderr="stash error"),  # stash
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_stash_and_clean("backup-msg", "/workspace", timeout=300)

    assert success is False
    assert error is not None
    assert "git stash push failed" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_stash_and_clean_success(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_stash_and_clean succeeds with dirty workspace."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout=" M file.txt\n", stderr=""),  # status
        MagicMock(returncode=0, stdout="", stderr=""),  # stash
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_stash_and_clean("backup-msg", "/workspace", timeout=300)

    assert success is True
    assert error is None
    assert mock_run.call_args_list[1][0][0] == [
        "git",
        "stash",
        "push",
        "--include-untracked",
        "-m",
        "backup-msg",
    ]


# === Tests for resolve_revision ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_resolve_revision_valid_ref(mock_run: MagicMock) -> None:
    """Test vcs_resolve_revision returns name as-is when it's a valid git ref."""
    mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n", stderr="")

    plugin = BareGitPlugin()
    result = plugin.vcs_resolve_revision("sase_dull_basin__1", "sase", "/workspace")

    assert result == "sase_dull_basin__1"
    assert mock_run.call_args[0][0] == [
        "git",
        "rev-parse",
        "--verify",
        "--quiet",
        "sase_dull_basin__1",
    ]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_resolve_revision_falls_back_to_branch(mock_run: MagicMock) -> None:
    """Test vcs_resolve_revision derives branch name when ref is invalid.

    After branch naming reform, the fallback is the suffix-stripped
    ChangeSpec name (identity for git), not the old hyphenated form.
    """
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")

    plugin = BareGitPlugin()
    result = plugin.vcs_resolve_revision("sase_dull_basin__1", "sase", "/workspace")

    assert result == "sase_dull_basin"


# === Tests for show_revision ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_show_revision_success(mock_run: MagicMock) -> None:
    """Test vcs_show_revision returns patch content on success."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="diff --git a/f b/f\n+hello\n", stderr=""
    )

    plugin = BareGitPlugin()
    success, output = plugin.vcs_show_revision("abc123", "/workspace")

    assert success is True
    assert output == "diff --git a/f b/f\n+hello\n"
    assert mock_run.call_args[0][0] == [
        "git",
        "show",
        "--format=",
        "--patch",
        "abc123",
    ]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_show_revision_failure(mock_run: MagicMock) -> None:
    """Test vcs_show_revision returns error on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="bad revision")

    plugin = BareGitPlugin()
    success, error = plugin.vcs_show_revision("bad-ref", "/workspace")

    assert success is False
    assert error is not None
    assert "git show failed" in error
