"""Tests for the git VCS provider — core operations.

Covers: registry detection, private helpers, checkout, diff, diff_revision,
apply_patch, apply_patches, add_remove, clean_workspace.
"""

import os
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

from sase.vcs_provider import get_vcs_provider
from sase.vcs_provider._git import _GitProvider

# === Tests for registry detection ===


def test_get_vcs_provider_detects_git() -> None:
    """Test get_vcs_provider detects .git directory and returns _GitProvider."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, ".git"))
        provider = get_vcs_provider(tmpdir)
        assert isinstance(provider, _GitProvider)


# === Tests for private helpers ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_run_timeout(mock_run: MagicMock) -> None:
    """Test _GitProvider._run handles timeout."""
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=300)

    provider = _GitProvider()
    success, error = provider.checkout("main", "/workspace")

    assert success is False
    assert error is not None
    assert "timed out" in error


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_run_command_not_found(mock_run: MagicMock) -> None:
    """Test _GitProvider._run handles command not found."""
    mock_run.side_effect = FileNotFoundError()

    provider = _GitProvider()
    success, error = provider.checkout("main", "/workspace")

    assert success is False
    assert error is not None
    assert "not found" in error


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_run_generic_exception(mock_run: MagicMock) -> None:
    """Test _GitProvider._run handles generic exceptions."""
    mock_run.side_effect = OSError("permission denied")

    provider = _GitProvider()
    success, error = provider.checkout("main", "/workspace")

    assert success is False
    assert error is not None
    assert "Error running" in error


# === Tests for checkout ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_checkout_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.checkout on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.checkout("main", "/workspace")

    assert success is True
    assert error is None
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == ["git", "checkout", "main"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_checkout_failure(mock_run: MagicMock) -> None:
    """Test _GitProvider.checkout on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="error: pathspec 'bad' did not match"
    )

    provider = _GitProvider()
    success, error = provider.checkout("bad", "/workspace")

    assert success is False
    assert error is not None
    assert "git checkout failed" in error


# === Tests for diff ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_diff_with_changes(mock_run: MagicMock) -> None:
    """Test _GitProvider.diff returns diff text when changes exist."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="diff --git a/file.py b/file.py\n+new line",
        stderr="",
    )

    provider = _GitProvider()
    success, diff_text = provider.diff("/workspace")

    assert success is True
    assert diff_text is not None
    assert "new line" in diff_text
    assert mock_run.call_args[0][0] == ["git", "diff", "HEAD"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_diff_no_changes(mock_run: MagicMock) -> None:
    """Test _GitProvider.diff returns None when no changes."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, diff_text = provider.diff("/workspace")

    assert success is True
    assert diff_text is None


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_diff_fallback_empty_repo(mock_run: MagicMock) -> None:
    """Test _GitProvider.diff falls back to 'git diff' for empty repos."""
    # First call (git diff HEAD) fails, second (git diff) succeeds
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout="", stderr="fatal: bad revision 'HEAD'"),
        MagicMock(returncode=0, stdout="diff content", stderr=""),
    ]

    provider = _GitProvider()
    success, diff_text = provider.diff("/workspace")

    assert success is True
    assert diff_text == "diff content"
    assert mock_run.call_count == 2


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_diff_both_fail(mock_run: MagicMock) -> None:
    """Test _GitProvider.diff when both HEAD and plain diff fail."""
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout="", stderr="fatal: bad revision 'HEAD'"),
        MagicMock(returncode=1, stdout="", stderr="repository error"),
    ]

    provider = _GitProvider()
    success, error = provider.diff("/workspace")

    assert success is False
    assert error is not None
    assert "git diff failed" in error


# === Tests for diff_revision ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_diff_revision_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.diff_revision on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="diff output", stderr="")

    provider = _GitProvider()
    success, diff_text = provider.diff_revision("abc123", "/workspace")

    assert success is True
    assert diff_text == "diff output"
    assert mock_run.call_args[0][0] == ["git", "diff", "abc123~1", "abc123"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_diff_revision_root_commit_fallback(mock_run: MagicMock) -> None:
    """Test _GitProvider.diff_revision falls back for root commits."""
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout="", stderr="fatal: bad revision"),
        MagicMock(returncode=0, stdout="root diff", stderr=""),
    ]

    provider = _GitProvider()
    success, diff_text = provider.diff_revision("abc123", "/workspace")

    assert success is True
    assert diff_text == "root diff"
    second_call = mock_run.call_args_list[1]
    assert second_call[0][0] == ["git", "show", "--format=", "--patch", "abc123"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_diff_revision_both_fail(mock_run: MagicMock) -> None:
    """Test _GitProvider.diff_revision when both attempts fail."""
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout="", stderr="bad revision"),
        MagicMock(returncode=1, stdout="", stderr="unknown revision"),
    ]

    provider = _GitProvider()
    success, error = provider.diff_revision("bad_rev", "/workspace")

    assert success is False
    assert error is not None
    assert "git diff failed" in error


# === Tests for apply_patch ===


@patch("sase.vcs_provider._git.subprocess.run")
@patch("os.path.exists", return_value=True)
def test_git_apply_patch_success(mock_exists: MagicMock, mock_run: MagicMock) -> None:
    """Test _GitProvider.apply_patch on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.apply_patch("/tmp/fix.patch", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "apply", "/tmp/fix.patch"]


@patch("os.path.exists", return_value=False)
def test_git_apply_patch_file_not_found(mock_exists: MagicMock) -> None:
    """Test _GitProvider.apply_patch when file doesn't exist."""
    provider = _GitProvider()
    success, error = provider.apply_patch("/tmp/missing.patch", "/workspace")

    assert success is False
    assert error is not None
    assert "Diff file not found" in error


@patch("sase.vcs_provider._git.subprocess.run")
@patch("os.path.exists", return_value=True)
def test_git_apply_patch_failure(mock_exists: MagicMock, mock_run: MagicMock) -> None:
    """Test _GitProvider.apply_patch when git apply fails."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="patch does not apply"
    )

    provider = _GitProvider()
    success, error = provider.apply_patch("/tmp/bad.patch", "/workspace")

    assert success is False
    assert error is not None
    assert "patch does not apply" in error


# === Tests for apply_patches ===


def test_git_apply_patches_empty_list() -> None:
    """Test _GitProvider.apply_patches with empty list."""
    provider = _GitProvider()
    success, error = provider.apply_patches([], "/workspace")

    assert success is True
    assert error is None


@patch("sase.vcs_provider._git.subprocess.run")
@patch("os.path.exists", return_value=True)
def test_git_apply_patches_success(mock_exists: MagicMock, mock_run: MagicMock) -> None:
    """Test _GitProvider.apply_patches on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.apply_patches(
        ["/tmp/a.patch", "/tmp/b.patch"], "/workspace"
    )

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "apply", "/tmp/a.patch", "/tmp/b.patch"]


@patch("os.path.exists", side_effect=[True, False])
def test_git_apply_patches_missing_file(mock_exists: MagicMock) -> None:
    """Test _GitProvider.apply_patches when a file is missing."""
    provider = _GitProvider()
    success, error = provider.apply_patches(
        ["/tmp/a.patch", "/tmp/missing.patch"], "/workspace"
    )

    assert success is False
    assert error is not None
    assert "Diff file not found" in error


@patch("sase.vcs_provider._git.subprocess.run")
@patch("os.path.exists", return_value=True)
def test_git_apply_patches_failure(mock_exists: MagicMock, mock_run: MagicMock) -> None:
    """Test _GitProvider.apply_patches when git apply fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="conflict")

    provider = _GitProvider()
    success, error = provider.apply_patches(["/tmp/a.patch"], "/workspace")

    assert success is False
    assert error is not None
    assert "conflict" in error


# === Tests for add_remove ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_add_remove_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.add_remove on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.add_remove("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "add", "-A"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_add_remove_failure(mock_run: MagicMock) -> None:
    """Test _GitProvider.add_remove on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="fatal: not a git repo"
    )

    provider = _GitProvider()
    success, error = provider.add_remove("/workspace")

    assert success is False
    assert error is not None
    assert "git add -A failed" in error


# === Tests for clean_workspace ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_clean_workspace_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.clean_workspace on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.clean_workspace("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[0][0][0] == ["git", "reset", "--hard", "HEAD"]
    assert mock_run.call_args_list[1][0][0] == ["git", "clean", "-fd"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_clean_workspace_reset_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.clean_workspace when reset fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="reset error")

    provider = _GitProvider()
    success, error = provider.clean_workspace("/workspace")

    assert success is False
    assert error is not None
    assert "git reset --hard failed" in error


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_clean_workspace_clean_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.clean_workspace when clean step fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # reset succeeds
        MagicMock(returncode=1, stdout="", stderr="clean error"),  # clean fails
    ]

    provider = _GitProvider()
    success, error = provider.clean_workspace("/workspace")

    assert success is False
    assert error is not None
    assert "git clean -fd failed" in error


# === Tests for sync_workspace ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_sync_workspace_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.sync_workspace on success."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # git fetch origin
        MagicMock(
            returncode=0, stdout="refs/remotes/origin/main\n", stderr=""
        ),  # symbolic-ref
        MagicMock(returncode=0, stdout="", stderr=""),  # git rebase
    ]

    provider = _GitProvider()
    success, error = provider.sync_workspace("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 3
    assert mock_run.call_args_list[0][0][0] == ["git", "fetch", "origin"]
    assert mock_run.call_args_list[2][0][0] == ["git", "rebase", "origin/main"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_sync_workspace_fetch_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.sync_workspace when fetch fails."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="fatal: unable to access remote"
    )

    provider = _GitProvider()
    success, error = provider.sync_workspace("/workspace")

    assert success is False
    assert error is not None
    assert "git fetch origin failed" in error


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_sync_workspace_rebase_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.sync_workspace when rebase fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # fetch succeeds
        MagicMock(
            returncode=0, stdout="refs/remotes/origin/main\n", stderr=""
        ),  # symbolic-ref
        MagicMock(returncode=1, stdout="", stderr="CONFLICT"),  # rebase fails
    ]

    provider = _GitProvider()
    success, error = provider.sync_workspace("/workspace")

    assert success is False
    assert error is not None
    assert "git rebase failed" in error


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_sync_workspace_default_branch_fallback(mock_run: MagicMock) -> None:
    """Test _GitProvider.sync_workspace falls back to 'main' when symbolic-ref fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # fetch succeeds
        MagicMock(returncode=1, stdout="", stderr=""),  # symbolic-ref fails
        MagicMock(returncode=0, stdout="", stderr=""),  # rebase succeeds
    ]

    provider = _GitProvider()
    success, error = provider.sync_workspace("/workspace")

    assert success is True
    assert error is None
    # Should default to "main"
    assert mock_run.call_args_list[2][0][0] == ["git", "rebase", "origin/main"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_sync_workspace_detects_master_branch(mock_run: MagicMock) -> None:
    """Test _GitProvider.sync_workspace detects 'master' as default branch."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # fetch succeeds
        MagicMock(
            returncode=0, stdout="refs/remotes/origin/master\n", stderr=""
        ),  # symbolic-ref returns master
        MagicMock(returncode=0, stdout="", stderr=""),  # rebase succeeds
    ]

    provider = _GitProvider()
    success, error = provider.sync_workspace("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args_list[2][0][0] == ["git", "rebase", "origin/master"]


# === Tests for is_sync_in_progress ===


@patch("os.path.isdir")
@patch("sase.vcs_provider._git.subprocess.run")
def test_git_is_sync_in_progress_rebase_merge(
    mock_run: MagicMock, mock_isdir: MagicMock
) -> None:
    """Test is_sync_in_progress detects rebase-merge directory."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="/workspace/.git\n", stderr=""
    )
    mock_isdir.side_effect = lambda p: "rebase-merge" in p

    provider = _GitProvider()
    assert provider.is_sync_in_progress("/workspace") is True


@patch("os.path.isdir")
@patch("sase.vcs_provider._git.subprocess.run")
def test_git_is_sync_in_progress_rebase_apply(
    mock_run: MagicMock, mock_isdir: MagicMock
) -> None:
    """Test is_sync_in_progress detects rebase-apply directory."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="/workspace/.git\n", stderr=""
    )
    mock_isdir.side_effect = lambda p: "rebase-apply" in p

    provider = _GitProvider()
    assert provider.is_sync_in_progress("/workspace") is True


@patch("os.path.isdir", return_value=False)
@patch("sase.vcs_provider._git.subprocess.run")
def test_git_is_sync_in_progress_no_rebase(
    mock_run: MagicMock, mock_isdir: MagicMock
) -> None:
    """Test is_sync_in_progress returns False when no rebase dirs exist."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="/workspace/.git\n", stderr=""
    )

    provider = _GitProvider()
    assert provider.is_sync_in_progress("/workspace") is False


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_is_sync_in_progress_git_fails(mock_run: MagicMock) -> None:
    """Test is_sync_in_progress returns False when git rev-parse fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a git repo")

    provider = _GitProvider()
    assert provider.is_sync_in_progress("/workspace") is False


@patch("os.path.isdir")
@patch("sase.vcs_provider._git.subprocess.run")
def test_git_is_sync_in_progress_relative_git_dir(
    mock_run: MagicMock, mock_isdir: MagicMock
) -> None:
    """Test is_sync_in_progress handles relative .git path by joining with cwd."""
    mock_run.return_value = MagicMock(returncode=0, stdout=".git\n", stderr="")
    mock_isdir.side_effect = lambda p: (
        p == os.path.join("/workspace", ".git", "rebase-merge")
    )

    provider = _GitProvider()
    assert provider.is_sync_in_progress("/workspace") is True


# === Tests for get_conflicted_files ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_conflicted_files_returns_list(mock_run: MagicMock) -> None:
    """Test get_conflicted_files returns file list from output."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="src/foo.py\nsrc/bar.py\n", stderr=""
    )

    provider = _GitProvider()
    files = provider.get_conflicted_files("/workspace")

    assert files == ["src/foo.py", "src/bar.py"]
    assert mock_run.call_args[0][0] == ["git", "diff", "--name-only", "--diff-filter=U"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_conflicted_files_no_conflicts(mock_run: MagicMock) -> None:
    """Test get_conflicted_files returns empty list when no conflicts."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    assert provider.get_conflicted_files("/workspace") == []


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_conflicted_files_command_fails(mock_run: MagicMock) -> None:
    """Test get_conflicted_files returns empty list on command failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")

    provider = _GitProvider()
    assert provider.get_conflicted_files("/workspace") == []


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_conflicted_files_extra_whitespace(mock_run: MagicMock) -> None:
    """Test get_conflicted_files handles extra whitespace and blank lines."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="  src/foo.py  \n\n  src/bar.py  \n\n", stderr=""
    )

    provider = _GitProvider()
    files = provider.get_conflicted_files("/workspace")

    assert files == ["  src/foo.py  ", "  src/bar.py  "]


# === Tests for continue_sync ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_continue_sync_success(mock_run: MagicMock) -> None:
    """Test continue_sync on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.continue_sync("/workspace")

    assert success is True
    assert error is None
    cmd = mock_run.call_args[0][0]
    assert cmd == ["git", "-c", "core.editor=true", "rebase", "--continue"]
    assert mock_run.call_args[1]["timeout"] == 600


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_continue_sync_more_conflicts(mock_run: MagicMock) -> None:
    """Test continue_sync failure when more conflicts are encountered."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="CONFLICT (content): Merge conflict in file.py"
    )

    provider = _GitProvider()
    success, error = provider.continue_sync("/workspace")

    assert success is False
    assert error is not None
    assert "git rebase --continue failed" in error


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_continue_sync_no_rebase(mock_run: MagicMock) -> None:
    """Test continue_sync failure when no rebase is in progress."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="fatal: No rebase in progress?",
    )

    provider = _GitProvider()
    success, error = provider.continue_sync("/workspace")

    assert success is False
    assert error is not None
    assert "No rebase in progress" in error


# === Tests for abort_sync ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_abort_sync_success(mock_run: MagicMock) -> None:
    """Test abort_sync on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.abort_sync("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "rebase", "--abort"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_abort_sync_no_rebase(mock_run: MagicMock) -> None:
    """Test abort_sync failure when no rebase is in progress."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="fatal: No rebase in progress?",
    )

    provider = _GitProvider()
    success, error = provider.abort_sync("/workspace")

    assert success is False
    assert error is not None
    assert "git rebase --abort failed" in error


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_abort_sync_permission_error(mock_run: MagicMock) -> None:
    """Test abort_sync failure on permission error."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="error: could not remove .git/rebase-merge: Permission denied",
    )

    provider = _GitProvider()
    success, error = provider.abort_sync("/workspace")

    assert success is False
    assert error is not None
    assert "Permission denied" in error
