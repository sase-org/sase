"""Tests for the git VCS provider — core operations.

Covers: registry detection, private helpers, checkout, diff, diff_revision,
apply_patch, apply_patches, add_remove, clean_workspace, create_proposal.
"""

import subprocess
from unittest.mock import MagicMock, patch

from sase.vcs_provider.plugins.bare_git import BareGitPlugin

_SAVE_DIFF_TARGET = "sase.workflows.commit_utils.workspace.save_diff"
_CLEAN_WS_TARGET = "sase.workflows.commit_utils.workspace.clean_workspace"

# === Tests for registry detection ===


# === Tests for private helpers ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_run_timeout(mock_run: MagicMock) -> None:
    """Test BareGitPlugin._run handles timeout."""
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=300)

    plugin = BareGitPlugin()
    success, error = plugin.vcs_checkout("main", "/workspace")

    assert success is False
    assert error is not None
    assert "timed out" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_run_command_not_found(mock_run: MagicMock) -> None:
    """Test BareGitPlugin._run handles command not found."""
    mock_run.side_effect = FileNotFoundError()

    plugin = BareGitPlugin()
    success, error = plugin.vcs_checkout("main", "/workspace")

    assert success is False
    assert error is not None
    assert "not found" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_run_generic_exception(mock_run: MagicMock) -> None:
    """Test BareGitPlugin._run handles generic exceptions."""
    mock_run.side_effect = OSError("permission denied")

    plugin = BareGitPlugin()
    success, error = plugin.vcs_checkout("main", "/workspace")

    assert success is False
    assert error is not None
    assert "Error running" in error


# === Tests for checkout ===


# === Tests for diff ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_diff_with_changes(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_diff returns diff text when changes exist."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="diff --git a/file.py b/file.py\n+new line",
        stderr="",
    )

    plugin = BareGitPlugin()
    success, diff_text = plugin.vcs_diff("/workspace")

    assert success is True
    assert diff_text is not None
    assert "new line" in diff_text
    assert mock_run.call_args[0][0] == ["git", "diff", "HEAD"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_diff_fallback_empty_repo(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_diff falls back to 'git diff' for empty repos."""
    # First call (git diff HEAD) fails, second (git diff) succeeds
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout="", stderr="fatal: bad revision 'HEAD'"),
        MagicMock(returncode=0, stdout="diff content", stderr=""),
    ]

    plugin = BareGitPlugin()
    success, diff_text = plugin.vcs_diff("/workspace")

    assert success is True
    assert diff_text == "diff content"
    assert mock_run.call_count == 2


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_diff_both_fail(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_diff when both HEAD and plain diff fail."""
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout="", stderr="fatal: bad revision 'HEAD'"),
        MagicMock(returncode=1, stdout="", stderr="repository error"),
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_diff("/workspace")

    assert success is False
    assert error is not None
    assert "git diff failed" in error


# === Tests for diff_revision ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_diff_revision_success(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_diff_revision uses merge-base diff."""
    mock_run.side_effect = [
        # _get_default_branch: git symbolic-ref refs/remotes/origin/HEAD
        MagicMock(returncode=0, stdout="refs/remotes/origin/main\n", stderr=""),
        # Primary: git diff origin/main...abc123
        MagicMock(returncode=0, stdout="diff output", stderr=""),
    ]

    plugin = BareGitPlugin()
    success, diff_text = plugin.vcs_diff_revision("abc123", "/workspace")

    assert success is True
    assert diff_text == "diff output"
    assert mock_run.call_args[0][0] == ["git", "diff", "origin/main...abc123"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_diff_revision_fallback_single_commit(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_diff_revision falls back to single-commit diff."""
    mock_run.side_effect = [
        # _get_default_branch
        MagicMock(returncode=0, stdout="refs/remotes/origin/main\n", stderr=""),
        # Primary merge-base diff fails
        MagicMock(returncode=1, stdout="", stderr="fatal: bad revision"),
        # Fallback 1: single-commit diff succeeds
        MagicMock(returncode=0, stdout="single commit diff", stderr=""),
    ]

    plugin = BareGitPlugin()
    success, diff_text = plugin.vcs_diff_revision("abc123", "/workspace")

    assert success is True
    assert diff_text == "single commit diff"
    assert mock_run.call_args[0][0] == ["git", "diff", "abc123~1", "abc123"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_diff_revision_root_commit_fallback(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_diff_revision falls back to git show for root commits."""
    mock_run.side_effect = [
        # _get_default_branch
        MagicMock(returncode=0, stdout="refs/remotes/origin/main\n", stderr=""),
        # Primary merge-base diff fails
        MagicMock(returncode=1, stdout="", stderr="fatal: bad revision"),
        # Fallback 1: single-commit diff fails
        MagicMock(returncode=1, stdout="", stderr="fatal: bad revision"),
        # Fallback 2: git show succeeds
        MagicMock(returncode=0, stdout="root diff", stderr=""),
    ]

    plugin = BareGitPlugin()
    success, diff_text = plugin.vcs_diff_revision("abc123", "/workspace")

    assert success is True
    assert diff_text == "root diff"
    assert mock_run.call_args[0][0] == [
        "git",
        "show",
        "--format=",
        "--patch",
        "abc123",
    ]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_diff_revision_all_fail(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_diff_revision when all attempts fail."""
    mock_run.side_effect = [
        # _get_default_branch
        MagicMock(returncode=0, stdout="refs/remotes/origin/main\n", stderr=""),
        # Primary merge-base diff fails
        MagicMock(returncode=1, stdout="", stderr="bad revision"),
        # Fallback 1: single-commit diff fails
        MagicMock(returncode=1, stdout="", stderr="bad revision"),
        # Fallback 2: git show fails
        MagicMock(returncode=1, stdout="", stderr="unknown revision"),
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_diff_revision("bad_rev", "/workspace")

    assert success is False
    assert error is not None
    assert "git diff failed" in error


# === Tests for apply_patch ===


@patch("os.path.exists", return_value=False)
def test_git_apply_patch_file_not_found(mock_exists: MagicMock) -> None:
    """Test BareGitPlugin.vcs_apply_patch when file doesn't exist."""
    plugin = BareGitPlugin()
    success, error = plugin.vcs_apply_patch("/tmp/missing.patch", "/workspace")

    assert success is False
    assert error is not None
    assert "Diff file not found" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
@patch("os.path.exists", return_value=True)
def test_git_apply_patch_failure(mock_exists: MagicMock, mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_apply_patch when git apply fails."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="patch does not apply"
    )

    plugin = BareGitPlugin()
    success, error = plugin.vcs_apply_patch("/tmp/bad.patch", "/workspace")

    assert success is False
    assert error is not None
    assert "patch does not apply" in error


# === Tests for apply_patches ===


def test_git_apply_patches_empty_list() -> None:
    """Test BareGitPlugin.vcs_apply_patches with empty list."""
    plugin = BareGitPlugin()
    success, error = plugin.vcs_apply_patches([], "/workspace")

    assert success is True
    assert error is None


@patch("sase.vcs_provider._command_runner.subprocess.run")
@patch("os.path.exists", return_value=True)
def test_git_apply_patches_success(mock_exists: MagicMock, mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_apply_patches on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = BareGitPlugin()
    success, error = plugin.vcs_apply_patches(
        ["/tmp/a.patch", "/tmp/b.patch"], "/workspace"
    )

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "apply", "/tmp/a.patch", "/tmp/b.patch"]


@patch("os.path.exists", side_effect=[True, False])
def test_git_apply_patches_missing_file(mock_exists: MagicMock) -> None:
    """Test BareGitPlugin.vcs_apply_patches when a file is missing."""
    plugin = BareGitPlugin()
    success, error = plugin.vcs_apply_patches(
        ["/tmp/a.patch", "/tmp/missing.patch"], "/workspace"
    )

    assert success is False
    assert error is not None
    assert "Diff file not found" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
@patch("os.path.exists", return_value=True)
def test_git_apply_patches_failure(mock_exists: MagicMock, mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_apply_patches when git apply fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="conflict")

    plugin = BareGitPlugin()
    success, error = plugin.vcs_apply_patches(["/tmp/a.patch"], "/workspace")

    assert success is False
    assert error is not None
    assert "conflict" in error


# === Tests for add_remove ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_add_remove_failure(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_add_remove on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="fatal: not a git repo"
    )

    plugin = BareGitPlugin()
    success, error = plugin.vcs_add_remove("/workspace")

    assert success is False
    assert error is not None
    assert "git add -A failed" in error


# === Tests for clean_workspace ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_clean_workspace_reset_fails(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_clean_workspace when reset fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="reset error")

    plugin = BareGitPlugin()
    success, error = plugin.vcs_clean_workspace("/workspace")

    assert success is False
    assert error is not None
    assert "git reset --hard failed" in error


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_clean_workspace_clean_fails(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_clean_workspace when clean step fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # reset succeeds
        MagicMock(returncode=1, stdout="", stderr="clean error"),  # clean fails
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_clean_workspace("/workspace")

    assert success is False
    assert error is not None
    assert "git clean -fd failed" in error


# === Tests for create_proposal ===


@patch(_CLEAN_WS_TARGET)
@patch(_SAVE_DIFF_TARGET, return_value="~/diffs/my_cl_20260326_120000.diff")
def test_git_create_proposal_saves_diff_and_cleans(
    mock_save: MagicMock, mock_clean: MagicMock
) -> None:
    """create_proposal saves a diff, cleans workspace, returns diff path."""
    plugin = BareGitPlugin()
    ok, result = plugin.vcs_create_proposal(
        {"name": "my_cl", "message": "propose"}, "/workspace"
    )

    assert ok is True
    assert result == "~/diffs/my_cl_20260326_120000.diff"
    mock_save.assert_called_once_with("my_cl", target_dir="/workspace")
    mock_clean.assert_called_once_with("/workspace")


@patch(_SAVE_DIFF_TARGET, return_value=None)
def test_git_create_proposal_no_changes(mock_save: MagicMock) -> None:
    """create_proposal returns failure when save_diff finds no changes."""
    plugin = BareGitPlugin()
    ok, error = plugin.vcs_create_proposal({"message": "propose"}, "/workspace")

    assert ok is False
    assert error is not None
    assert "No changes" in error


@patch(_CLEAN_WS_TARGET)
@patch(_SAVE_DIFF_TARGET, return_value="~/diffs/cl_20260326.diff")
def test_git_create_proposal_uses_cl_name_fallback(
    mock_save: MagicMock, mock_clean: MagicMock
) -> None:
    """create_proposal falls back to _cl_name when name is absent."""
    plugin = BareGitPlugin()
    ok, _ = plugin.vcs_create_proposal(
        {"_cl_name": "fallback_cl", "message": "propose"}, "/workspace"
    )

    assert ok is True
    mock_save.assert_called_once_with("fallback_cl", target_dir="/workspace")
