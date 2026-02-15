"""Tests for the git VCS provider."""

import os
import subprocess
import tempfile
from unittest.mock import MagicMock, mock_open, patch

import pytest

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


# === Tests for commit ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_commit_new_branch(mock_run: MagicMock) -> None:
    """Test _GitProvider.commit creates new branch when needed."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="main\n", stderr=""),  # rev-parse
        MagicMock(returncode=0, stdout="", stderr=""),  # checkout -b
        MagicMock(returncode=0, stdout="", stderr=""),  # commit
    ]

    provider = _GitProvider()
    success, error = provider.commit("feature", "/tmp/msg.txt", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args_list[1][0][0] == ["git", "checkout", "-b", "feature"]
    assert mock_run.call_args_list[2][0][0] == ["git", "commit", "-F", "/tmp/msg.txt"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_commit_same_branch(mock_run: MagicMock) -> None:
    """Test _GitProvider.commit skips branch creation when already on branch."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="feature\n", stderr=""),  # rev-parse
        MagicMock(returncode=0, stdout="", stderr=""),  # commit
    ]

    provider = _GitProvider()
    success, error = provider.commit("feature", "/tmp/msg.txt", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 2  # No checkout -b call


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_commit_branch_creation_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.commit when branch creation fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="main\n", stderr=""),  # rev-parse
        MagicMock(
            returncode=1, stdout="", stderr="branch already exists"
        ),  # checkout -b fails
    ]

    provider = _GitProvider()
    success, error = provider.commit("feature", "/tmp/msg.txt", "/workspace")

    assert success is False
    assert error is not None
    assert "git checkout -b failed" in error


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_commit_failure(mock_run: MagicMock) -> None:
    """Test _GitProvider.commit when commit itself fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="feature\n", stderr=""),  # rev-parse
        MagicMock(returncode=1, stdout="", stderr="nothing to commit"),  # commit fails
    ]

    provider = _GitProvider()
    success, error = provider.commit("feature", "/tmp/msg.txt", "/workspace")

    assert success is False
    assert error is not None
    assert "git commit failed" in error


# === Tests for amend ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_amend_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.amend on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.amend("fix typo", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "commit", "--amend", "-m", "fix typo"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_amend_no_upload_ignored(mock_run: MagicMock) -> None:
    """Test _GitProvider.amend silently ignores no_upload flag."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, _ = provider.amend("fix typo", "/workspace", no_upload=True)

    assert success is True
    # Same command regardless of no_upload
    assert mock_run.call_args[0][0] == ["git", "commit", "--amend", "-m", "fix typo"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_amend_failure(mock_run: MagicMock) -> None:
    """Test _GitProvider.amend on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="nothing to amend"
    )

    provider = _GitProvider()
    success, error = provider.amend("note", "/workspace")

    assert success is False
    assert error is not None
    assert "git commit --amend failed" in error


# === Tests for rename_branch ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_rename_branch_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.rename_branch on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.rename_branch("new_name", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "branch", "-m", "new_name"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_rename_branch_failure(mock_run: MagicMock) -> None:
    """Test _GitProvider.rename_branch on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="fatal: rename failed"
    )

    provider = _GitProvider()
    success, error = provider.rename_branch("bad", "/workspace")

    assert success is False
    assert error is not None
    assert "git branch -m failed" in error


# === Tests for rebase ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_rebase_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.rebase on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.rebase("feature", "main", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "rebase", "--onto", "main", "feature"]
    # Verify 600s timeout
    assert mock_run.call_args[1]["timeout"] == 600


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_rebase_failure(mock_run: MagicMock) -> None:
    """Test _GitProvider.rebase on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="merge conflict")

    provider = _GitProvider()
    success, error = provider.rebase("feature", "main", "/workspace")

    assert success is False
    assert error is not None
    assert "git rebase failed" in error


# === Tests for archive ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_archive_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.archive on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.archive("old-feature", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[0][0][0] == [
        "git",
        "tag",
        "archive/old-feature",
        "old-feature",
    ]
    assert mock_run.call_args_list[1][0][0] == ["git", "branch", "-D", "old-feature"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_archive_tag_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.archive when tagging fails."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="tag already exists"
    )

    provider = _GitProvider()
    success, error = provider.archive("old-feature", "/workspace")

    assert success is False
    assert error is not None
    assert "git tag failed" in error
    # Should not attempt branch delete
    mock_run.assert_called_once()


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_archive_branch_delete_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.archive when branch delete fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # tag succeeds
        MagicMock(returncode=1, stdout="", stderr="branch not found"),  # delete fails
    ]

    provider = _GitProvider()
    success, error = provider.archive("old-feature", "/workspace")

    assert success is False
    assert error is not None
    assert "git branch -D failed" in error


# === Tests for prune ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_prune_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.prune on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.prune("dead-branch", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "branch", "-D", "dead-branch"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_prune_failure(mock_run: MagicMock) -> None:
    """Test _GitProvider.prune on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="error: branch not found"
    )

    provider = _GitProvider()
    success, error = provider.prune("nonexistent", "/workspace")

    assert success is False
    assert error is not None
    assert "git branch -D failed" in error


# === Tests for stash_and_clean ===


@patch("builtins.open", mock_open())
@patch("sase.vcs_provider._git.subprocess.run")
def test_git_stash_and_clean_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.stash_and_clean on success."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="diff content", stderr=""),  # diff
        MagicMock(returncode=0, stdout="", stderr=""),  # reset
        MagicMock(returncode=0, stdout="", stderr=""),  # clean
    ]

    provider = _GitProvider()
    success, error = provider.stash_and_clean("/tmp/backup.diff", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 3


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_stash_and_clean_diff_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.stash_and_clean when diff fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="diff error")

    provider = _GitProvider()
    success, error = provider.stash_and_clean("/tmp/backup.diff", "/workspace")

    assert success is False
    assert error is not None
    assert "diff error" in error


@patch("builtins.open", side_effect=OSError("permission denied"))
@patch("sase.vcs_provider._git.subprocess.run")
def test_git_stash_and_clean_write_fails(
    mock_run: MagicMock, mock_open_fn: MagicMock
) -> None:
    """Test _GitProvider.stash_and_clean when file write fails."""
    mock_run.return_value = MagicMock(returncode=0, stdout="diff content", stderr="")

    provider = _GitProvider()
    success, error = provider.stash_and_clean("/tmp/backup.diff", "/workspace")

    assert success is False
    assert error is not None
    assert "Failed to write diff file" in error


@patch("builtins.open", mock_open())
@patch("sase.vcs_provider._git.subprocess.run")
def test_git_stash_and_clean_reset_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.stash_and_clean when reset step fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="diff content", stderr=""),  # diff
        MagicMock(returncode=1, stdout="", stderr="reset error"),  # reset
    ]

    provider = _GitProvider()
    success, error = provider.stash_and_clean("/tmp/backup.diff", "/workspace")

    assert success is False
    assert error is not None
    assert "git reset --hard failed" in error


@patch("builtins.open", mock_open())
@patch("sase.vcs_provider._git.subprocess.run")
def test_git_stash_and_clean_clean_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.stash_and_clean when clean step fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="diff content", stderr=""),  # diff
        MagicMock(returncode=0, stdout="", stderr=""),  # reset ok
        MagicMock(returncode=1, stdout="", stderr="clean error"),  # clean fails
    ]

    provider = _GitProvider()
    success, error = provider.stash_and_clean("/tmp/backup.diff", "/workspace")

    assert success is False
    assert error is not None
    assert "git clean -fd failed" in error


# === Tests for get_branch_name ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_branch_name_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_branch_name on success."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="feature-branch\n", stderr=""
    )

    provider = _GitProvider()
    success, name = provider.get_branch_name("/workspace")

    assert success is True
    assert name == "feature-branch"


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_branch_name_detached_head(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_branch_name returns None in detached HEAD."""
    mock_run.return_value = MagicMock(returncode=0, stdout="HEAD\n", stderr="")

    provider = _GitProvider()
    success, name = provider.get_branch_name("/workspace")

    assert success is True
    assert name is None


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_branch_name_failure(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_branch_name on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a git repo")

    provider = _GitProvider()
    success, error = provider.get_branch_name("/workspace")

    assert success is False
    assert error is not None
    assert "failed" in error


# === Tests for get_description ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_description_full(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_description returns full description."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="Full commit message\n\nBody text\n", stderr=""
    )

    provider = _GitProvider()
    success, desc = provider.get_description("abc123", "/workspace")

    assert success is True
    assert desc is not None
    assert "Full commit message" in desc
    assert mock_run.call_args[0][0] == ["git", "log", "--format=%B", "-n1", "abc123"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_description_short(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_description with short=True."""
    mock_run.return_value = MagicMock(returncode=0, stdout="Short subject\n", stderr="")

    provider = _GitProvider()
    success, desc = provider.get_description("abc123", "/workspace", short=True)

    assert success is True
    assert desc is not None
    assert "Short subject" in desc
    assert mock_run.call_args[0][0] == ["git", "log", "--format=%s", "-n1", "abc123"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_description_failure(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_description on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="unknown revision"
    )

    provider = _GitProvider()
    success, error = provider.get_description("bad_rev", "/workspace")

    assert success is False
    assert error is not None
    assert "unknown revision" in error


# === Tests for has_local_changes ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_has_local_changes_with_changes(mock_run: MagicMock) -> None:
    """Test _GitProvider.has_local_changes when changes exist."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout=" M file.py\n?? new.py\n", stderr=""
    )

    provider = _GitProvider()
    success, text = provider.has_local_changes("/workspace")

    assert success is True
    assert text is not None
    assert "file.py" in text


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_has_local_changes_clean(mock_run: MagicMock) -> None:
    """Test _GitProvider.has_local_changes when workspace is clean."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, text = provider.has_local_changes("/workspace")

    assert success is True
    assert text is None


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_has_local_changes_failure(mock_run: MagicMock) -> None:
    """Test _GitProvider.has_local_changes on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a repo")

    provider = _GitProvider()
    success, error = provider.has_local_changes("/workspace")

    assert success is False
    assert error is not None
    assert "not a repo" in error


# === Tests for get_workspace_name ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_workspace_name_from_remote(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_workspace_name extracts from remote URL."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="https://github.com/user/my-repo.git\n",
        stderr="",
    )

    provider = _GitProvider()
    success, name = provider.get_workspace_name("/workspace")

    assert success is True
    assert name == "my-repo"


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_workspace_name_no_git_suffix(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_workspace_name with URL without .git suffix."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="https://github.com/user/my-repo\n",
        stderr="",
    )

    provider = _GitProvider()
    success, name = provider.get_workspace_name("/workspace")

    assert success is True
    assert name == "my-repo"


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_workspace_name_fallback_to_root(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_workspace_name falls back to repo root."""
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout="", stderr=""),  # no remote
        MagicMock(
            returncode=0, stdout="/home/user/my-project\n", stderr=""
        ),  # toplevel
    ]

    provider = _GitProvider()
    success, name = provider.get_workspace_name("/workspace")

    assert success is True
    assert name == "my-project"


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_workspace_name_both_fail(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_workspace_name when everything fails."""
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout="", stderr=""),  # no remote
        MagicMock(returncode=1, stdout="", stderr=""),  # no toplevel
    ]

    provider = _GitProvider()
    success, error = provider.get_workspace_name("/workspace")

    assert success is False
    assert error is not None
    assert "Could not determine workspace name" in error


# === Tests for reword ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_reword_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.reword on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    provider = _GitProvider()
    success, error = provider.reword("new description", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == [
        "git",
        "commit",
        "--amend",
        "-m",
        "new description",
    ]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_reword_failure(mock_run: MagicMock) -> None:
    """Test _GitProvider.reword on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="nothing to amend"
    )

    provider = _GitProvider()
    success, error = provider.reword("desc", "/workspace")

    assert success is False
    assert error is not None
    assert "git commit --amend failed" in error


# === Tests for unimplemented methods ===


def test_git_unimplemented_methods() -> None:
    """Test that Google-internal methods raise NotImplementedError."""
    provider = _GitProvider()

    methods_to_test = [
        lambda: provider.find_reviewers("123", "/cwd"),
        lambda: provider.rewind(["/path"], "/cwd"),
    ]

    for method in methods_to_test:
        with pytest.raises(NotImplementedError):
            method()


# === Tests for get_change_url ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_change_url_with_pr(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_change_url when PR exists."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="https://github.com/user/repo/pull/42\n",
        stderr="",
    )

    provider = _GitProvider()
    success, url = provider.get_change_url("/workspace")

    assert success is True
    assert url == "https://github.com/user/repo/pull/42"


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_change_url_no_pr(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_change_url when no PR exists."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="no pull requests found"
    )

    provider = _GitProvider()
    success, url = provider.get_change_url("/workspace")

    assert success is True
    assert url is None


# === Tests for get_cl_number (PR number) ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_cl_number_with_pr(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_cl_number when PR exists."""
    mock_run.return_value = MagicMock(returncode=0, stdout="42\n", stderr="")

    provider = _GitProvider()
    success, number = provider.get_cl_number("/workspace")

    assert success is True
    assert number == "42"


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_get_cl_number_no_pr(mock_run: MagicMock) -> None:
    """Test _GitProvider.get_cl_number when no PR exists."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="no pull requests found"
    )

    provider = _GitProvider()
    success, number = provider.get_cl_number("/workspace")

    assert success is True
    assert number is None


# === Tests for get_bug_number ===


def test_git_get_bug_number() -> None:
    """Test _GitProvider.get_bug_number returns empty string."""
    provider = _GitProvider()
    success, bug = provider.get_bug_number("/workspace")

    assert success is True
    assert bug == ""


# === Tests for fix / upload (no-ops) ===


def test_git_fix_noop() -> None:
    """Test _GitProvider.fix returns success (no-op)."""
    provider = _GitProvider()
    success, error = provider.fix("/workspace")

    assert success is True
    assert error is None


def test_git_upload_noop() -> None:
    """Test _GitProvider.upload returns success (no-op)."""
    provider = _GitProvider()
    success, error = provider.upload("/workspace")

    assert success is True
    assert error is None


# === Tests for mail ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_mail_push_and_create_pr(mock_run: MagicMock) -> None:
    """Test _GitProvider.mail pushes and creates PR when none exists."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # git push
        MagicMock(returncode=1, stdout="", stderr="no PR"),  # gh pr view (no PR)
        MagicMock(returncode=0, stdout="", stderr=""),  # gh pr create
    ]

    provider = _GitProvider()
    success, error = provider.mail("feature-branch", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 3
    assert mock_run.call_args_list[0][0][0] == [
        "git",
        "push",
        "-u",
        "origin",
        "feature-branch",
    ]
    assert mock_run.call_args_list[2][0][0] == ["gh", "pr", "create", "--fill"]


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_mail_push_existing_pr(mock_run: MagicMock) -> None:
    """Test _GitProvider.mail just pushes when PR already exists."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # git push
        MagicMock(returncode=0, stdout="42\n", stderr=""),  # gh pr view (PR exists)
    ]

    provider = _GitProvider()
    success, error = provider.mail("feature-branch", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 2


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_mail_push_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.mail when push fails."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="permission denied"
    )

    provider = _GitProvider()
    success, error = provider.mail("feature-branch", "/workspace")

    assert success is False
    assert error is not None
    assert "git push failed" in error


# === Tests for reword_add_tag ===


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_reword_add_tag_success(mock_run: MagicMock) -> None:
    """Test _GitProvider.reword_add_tag appends tag to commit message."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="Existing message\n", stderr=""),  # git log
        MagicMock(returncode=0, stdout="", stderr=""),  # git commit --amend
    ]

    provider = _GitProvider()
    success, error = provider.reword_add_tag("BUG", "12345", "/workspace")

    assert success is True
    assert error is None
    # Verify the amended message includes the tag
    amend_call = mock_run.call_args_list[1]
    new_msg = amend_call[0][0][4]  # -m argument
    assert "Existing message\nBUG=12345" in new_msg


@patch("sase.vcs_provider._git.subprocess.run")
def test_git_reword_add_tag_log_fails(mock_run: MagicMock) -> None:
    """Test _GitProvider.reword_add_tag when git log fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a git repo")

    provider = _GitProvider()
    success, error = provider.reword_add_tag("BUG", "12345", "/workspace")

    assert success is False
    assert error is not None
