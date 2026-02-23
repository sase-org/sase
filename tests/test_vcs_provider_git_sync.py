"""Tests for the git VCS provider — sync/rebase workflow operations.

Covers: sync_workspace, is_sync_in_progress, get_conflicted_files,
continue_sync, abort_sync.
"""

import os
from unittest.mock import MagicMock, patch

from sase.vcs_provider.plugins.github import GitHubPlugin

# === Tests for sync_workspace ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_sync_workspace_success(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_sync_workspace on success."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # git fetch origin
        MagicMock(
            returncode=0, stdout="refs/remotes/origin/main\n", stderr=""
        ),  # symbolic-ref
        MagicMock(returncode=0, stdout="", stderr=""),  # git rebase
    ]

    plugin = GitHubPlugin()
    success, error = plugin.vcs_sync_workspace("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 3
    assert mock_run.call_args_list[0][0][0] == ["git", "fetch", "origin"]
    assert mock_run.call_args_list[2][0][0] == ["git", "rebase", "origin/main"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_sync_workspace_fetch_fails(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_sync_workspace when fetch fails."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="fatal: unable to access remote"
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_sync_workspace("/workspace")

    assert success is False
    assert error is not None
    assert "git fetch origin failed" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_sync_workspace_rebase_fails(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_sync_workspace when rebase fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # fetch succeeds
        MagicMock(
            returncode=0, stdout="refs/remotes/origin/main\n", stderr=""
        ),  # symbolic-ref
        MagicMock(returncode=1, stdout="", stderr="CONFLICT"),  # rebase fails
    ]

    plugin = GitHubPlugin()
    success, error = plugin.vcs_sync_workspace("/workspace")

    assert success is False
    assert error is not None
    assert "git rebase failed" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_sync_workspace_default_branch_fallback(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_sync_workspace falls back to 'main' when symbolic-ref fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # fetch succeeds
        MagicMock(returncode=1, stdout="", stderr=""),  # symbolic-ref fails
        MagicMock(returncode=0, stdout="", stderr=""),  # rebase succeeds
    ]

    plugin = GitHubPlugin()
    success, error = plugin.vcs_sync_workspace("/workspace")

    assert success is True
    assert error is None
    # Should default to "main"
    assert mock_run.call_args_list[2][0][0] == ["git", "rebase", "origin/main"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_sync_workspace_detects_master_branch(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_sync_workspace detects 'master' as default branch."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # fetch succeeds
        MagicMock(
            returncode=0, stdout="refs/remotes/origin/master\n", stderr=""
        ),  # symbolic-ref returns master
        MagicMock(returncode=0, stdout="", stderr=""),  # rebase succeeds
    ]

    plugin = GitHubPlugin()
    success, error = plugin.vcs_sync_workspace("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args_list[2][0][0] == ["git", "rebase", "origin/master"]


# === Tests for is_sync_in_progress ===


@patch("os.path.isdir")
@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_is_sync_in_progress_rebase_merge(
    mock_run: MagicMock, mock_isdir: MagicMock
) -> None:
    """Test vcs_is_sync_in_progress detects rebase-merge directory."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="/workspace/.git\n", stderr=""
    )
    mock_isdir.side_effect = lambda p: "rebase-merge" in p

    plugin = GitHubPlugin()
    assert plugin.vcs_is_sync_in_progress("/workspace") is True


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

    plugin = GitHubPlugin()
    assert plugin.vcs_is_sync_in_progress("/workspace") is True


@patch("os.path.isdir", return_value=False)
@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_is_sync_in_progress_no_rebase(
    mock_run: MagicMock, mock_isdir: MagicMock
) -> None:
    """Test vcs_is_sync_in_progress returns False when no rebase dirs exist."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="/workspace/.git\n", stderr=""
    )

    plugin = GitHubPlugin()
    assert plugin.vcs_is_sync_in_progress("/workspace") is False


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_is_sync_in_progress_git_fails(mock_run: MagicMock) -> None:
    """Test vcs_is_sync_in_progress returns False when git rev-parse fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a git repo")

    plugin = GitHubPlugin()
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

    plugin = GitHubPlugin()
    assert plugin.vcs_is_sync_in_progress("/workspace") is True


# === Tests for get_conflicted_files ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_conflicted_files_returns_list(mock_run: MagicMock) -> None:
    """Test vcs_get_conflicted_files returns file list from output."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="src/foo.py\nsrc/bar.py\n", stderr=""
    )

    plugin = GitHubPlugin()
    files = plugin.vcs_get_conflicted_files("/workspace")

    assert files == ["src/foo.py", "src/bar.py"]
    assert mock_run.call_args[0][0] == ["git", "diff", "--name-only", "--diff-filter=U"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_conflicted_files_no_conflicts(mock_run: MagicMock) -> None:
    """Test vcs_get_conflicted_files returns empty list when no conflicts."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
    assert plugin.vcs_get_conflicted_files("/workspace") == []


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_conflicted_files_command_fails(mock_run: MagicMock) -> None:
    """Test vcs_get_conflicted_files returns empty list on command failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

    plugin = GitHubPlugin()
    assert plugin.vcs_get_conflicted_files("/workspace") == []


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_conflicted_files_extra_whitespace(mock_run: MagicMock) -> None:
    """Test vcs_get_conflicted_files handles extra whitespace and blank lines."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="  src/foo.py  \n\n  src/bar.py  \n\n", stderr=""
    )

    plugin = GitHubPlugin()
    files = plugin.vcs_get_conflicted_files("/workspace")

    assert files == ["  src/foo.py  ", "  src/bar.py  "]


# === Tests for continue_sync ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_continue_sync_success(mock_run: MagicMock) -> None:
    """Test vcs_continue_sync on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_continue_sync("/workspace")

    assert success is True
    assert error is None
    cmd = mock_run.call_args[0][0]
    assert cmd == ["git", "-c", "core.editor=true", "rebase", "--continue"]
    assert mock_run.call_args[1]["timeout"] == 600


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_continue_sync_more_conflicts(mock_run: MagicMock) -> None:
    """Test vcs_continue_sync failure when more conflicts are encountered."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="CONFLICT (content): Merge conflict in file.py"
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_continue_sync("/workspace")

    assert success is False
    assert error is not None
    assert "git rebase --continue failed" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_continue_sync_no_rebase(mock_run: MagicMock) -> None:
    """Test vcs_continue_sync failure when no rebase is in progress."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="fatal: No rebase in progress?",
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_continue_sync("/workspace")

    assert success is False
    assert error is not None
    assert "No rebase in progress" in error


# === Tests for abort_sync ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_abort_sync_success(mock_run: MagicMock) -> None:
    """Test vcs_abort_sync on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_abort_sync("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "rebase", "--abort"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_abort_sync_no_rebase(mock_run: MagicMock) -> None:
    """Test vcs_abort_sync failure when no rebase is in progress."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="fatal: No rebase in progress?",
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_abort_sync("/workspace")

    assert success is False
    assert error is not None
    assert "git rebase --abort failed" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_abort_sync_permission_error(mock_run: MagicMock) -> None:
    """Test vcs_abort_sync failure on permission error."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="error: could not remove .git/rebase-merge: Permission denied",
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_abort_sync("/workspace")

    assert success is False
    assert error is not None
    assert "Permission denied" in error
