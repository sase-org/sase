"""Tests for the git VCS provider — commit and branch operations.

Covers: commit, amend, rename_branch, rebase, archive, prune, stash_and_clean.
"""

from unittest.mock import MagicMock, mock_open, patch

from sase.vcs_provider.plugins.bare_git import BareGitPlugin

# === Tests for commit ===


# === Tests for amend ===


# === Tests for rename_branch ===


# === Tests for rebase ===


# === Tests for archive ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_archive_success(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_archive on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = BareGitPlugin()
    success, error = plugin.vcs_archive("old-feature", "/workspace")

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


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_archive_branch_delete_fails(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_archive when branch delete fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # tag succeeds
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
def test_git_stash_and_clean_diff_fails(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_stash_and_clean when diff fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="diff error")

    plugin = BareGitPlugin()
    success, error = plugin.vcs_stash_and_clean(
        "/tmp/backup.diff", "/workspace", timeout=300
    )

    assert success is False
    assert error is not None
    assert "diff error" in error


@patch("builtins.open", side_effect=OSError("permission denied"))
@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_stash_and_clean_write_fails(
    mock_run: MagicMock, mock_open_fn: MagicMock
) -> None:
    """Test BareGitPlugin.vcs_stash_and_clean when file write fails."""
    mock_run.return_value = MagicMock(returncode=0, stdout="diff content", stderr="")

    plugin = BareGitPlugin()
    success, error = plugin.vcs_stash_and_clean(
        "/tmp/backup.diff", "/workspace", timeout=300
    )

    assert success is False
    assert error is not None
    assert "Failed to write diff file" in error


@patch("builtins.open", mock_open())
@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_stash_and_clean_reset_fails(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_stash_and_clean when reset step fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="diff content", stderr=""),  # diff
        MagicMock(returncode=1, stdout="", stderr="reset error"),  # reset
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_stash_and_clean(
        "/tmp/backup.diff", "/workspace", timeout=300
    )

    assert success is False
    assert error is not None
    assert "git reset --hard failed" in error


@patch("builtins.open", mock_open())
@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_stash_and_clean_clean_fails(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_stash_and_clean when clean step fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="diff content", stderr=""),  # diff
        MagicMock(returncode=0, stdout="", stderr=""),  # reset ok
        MagicMock(returncode=1, stdout="", stderr="clean error"),  # clean fails
    ]

    plugin = BareGitPlugin()
    success, error = plugin.vcs_stash_and_clean(
        "/tmp/backup.diff", "/workspace", timeout=300
    )

    assert success is False
    assert error is not None
    assert "git clean -fd failed" in error


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
    """Test vcs_resolve_revision derives branch name when ref is invalid."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")

    plugin = BareGitPlugin()
    result = plugin.vcs_resolve_revision("sase_dull_basin__1", "sase", "/workspace")

    assert result == "dull-basin"


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
