"""Tests for the git VCS provider — sync/rebase workflow operations.

Covers: sync_workspace, is_sync_in_progress, get_conflicted_files,
continue_sync, abort_sync.
"""

import os
from unittest.mock import MagicMock, patch

from sase.vcs_provider.plugins.bare_git import BareGitPlugin

# === Tests for sync_workspace ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_sync_workspace_fetch_fails(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_sync_workspace when fetch fails."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="fatal: unable to access remote"
    )

    plugin = BareGitPlugin()
    success, error = plugin.vcs_sync_workspace("/workspace")

    assert success is False
    assert error is not None
    assert "git fetch origin failed" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_sync_workspace_default_branch_fallback(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_sync_workspace falls back to 'main' when symbolic-ref fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # fetch succeeds
        MagicMock(returncode=1, stdout="", stderr=""),  # symbolic-ref fails
        MagicMock(returncode=1, stdout="", stderr=""),  # show-ref master fails
        MagicMock(returncode=1, stdout="", stderr=""),  # show-ref main fails
        MagicMock(returncode=0, stdout="", stderr=""),  # rebase succeeds
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_sync_workspace("/workspace")

    assert success is True
    assert error is None
    # Should default to "main"
    assert mock_run.call_args_list[4][0][0] == ["git", "rebase", "origin/main"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_sync_workspace_detects_master_branch(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_sync_workspace detects 'master' as default branch."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # fetch succeeds
        MagicMock(
            returncode=0, stdout="refs/remotes/origin/master\n", stderr=""
        ),  # symbolic-ref returns master
        MagicMock(returncode=0, stdout="", stderr=""),  # rebase succeeds
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_sync_workspace("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args_list[2][0][0] == ["git", "rebase", "origin/master"]


# === Tests for is_sync_in_progress ===


@patch("os.path.isdir")
@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_is_sync_in_progress_rebase_apply(
    mock_run: MagicMock, mock_isdir: MagicMock
) -> None:
    """Test vcs_is_sync_in_progress detects rebase-apply directory."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="/workspace/.git\n", stderr=""
    )
    mock_isdir.side_effect = lambda p: "rebase-apply" in p

    plugin = BareGitPlugin()
    assert plugin.vcs_is_sync_in_progress("/workspace") is True


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_is_sync_in_progress_git_fails(mock_run: MagicMock) -> None:
    """Test vcs_is_sync_in_progress returns False when git rev-parse fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a git repo")

    plugin = BareGitPlugin()
    assert plugin.vcs_is_sync_in_progress("/workspace") is False


@patch("os.path.isdir")
@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_is_sync_in_progress_relative_git_dir(
    mock_run: MagicMock, mock_isdir: MagicMock
) -> None:
    """Test vcs_is_sync_in_progress handles relative .git path by joining with cwd."""
    mock_run.return_value = MagicMock(returncode=0, stdout=".git\n", stderr="")
    mock_isdir.side_effect = lambda p: (
        p == os.path.join("/workspace", ".git", "rebase-merge")
    )

    plugin = BareGitPlugin()
    assert plugin.vcs_is_sync_in_progress("/workspace") is True


# === Tests for get_conflicted_files ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_conflicted_files_no_conflicts(mock_run: MagicMock) -> None:
    """Test vcs_get_conflicted_files returns empty list when no conflicts."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = BareGitPlugin()
    assert plugin.vcs_get_conflicted_files("/workspace") == []


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_conflicted_files_command_fails(mock_run: MagicMock) -> None:
    """Test vcs_get_conflicted_files returns empty list on command failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

    plugin = BareGitPlugin()
    assert plugin.vcs_get_conflicted_files("/workspace") == []


# === Tests for continue_sync ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_continue_sync_more_conflicts(mock_run: MagicMock) -> None:
    """Test vcs_continue_sync failure when more conflicts are encountered."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="CONFLICT (content): Merge conflict in file.py"
    )

    plugin = BareGitPlugin()
    success, error = plugin.vcs_continue_sync("/workspace")

    assert success is False
    assert error is not None
    assert "git rebase --continue failed" in error


# === Tests for abort_sync ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_abort_sync_no_rebase(mock_run: MagicMock) -> None:
    """Test vcs_abort_sync failure when no rebase is in progress."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="fatal: No rebase in progress?",
    )

    plugin = BareGitPlugin()
    success, error = plugin.vcs_abort_sync("/workspace")

    assert success is False
    assert error is not None
    assert "git rebase --abort failed" in error
