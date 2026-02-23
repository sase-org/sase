"""Tests for the git VCS provider — commit and branch operations.

Covers: commit, amend, rename_branch, rebase, archive, prune, stash_and_clean.
"""

from unittest.mock import MagicMock, mock_open, patch

from sase.vcs_provider.plugins.github import GitHubPlugin

# === Tests for commit ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_commit_success(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_commit commits on current branch."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_commit("feature", "/tmp/msg.txt", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 1
    assert mock_run.call_args[0][0] == ["git", "commit", "-F", "/tmp/msg.txt"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_commit_failure(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_commit when commit fails."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="nothing to commit"
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_commit("feature", "/tmp/msg.txt", "/workspace")

    assert success is False
    assert error is not None
    assert "git commit failed" in error


# === Tests for amend ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_amend_success(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_amend on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_amend("fix typo", "/workspace", no_upload=False)

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "commit", "--amend", "-m", "fix typo"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_amend_no_upload_ignored(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_amend silently ignores no_upload flag."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
    success, _ = plugin.vcs_amend("fix typo", "/workspace", no_upload=True)

    assert success is True
    # Same command regardless of no_upload
    assert mock_run.call_args[0][0] == ["git", "commit", "--amend", "-m", "fix typo"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_amend_failure(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_amend on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="nothing to amend"
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_amend("note", "/workspace", no_upload=False)

    assert success is False
    assert error is not None
    assert "git commit --amend failed" in error


# === Tests for rename_branch ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_rename_branch_success(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_rename_branch on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_rename_branch("new_name", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "branch", "-m", "new_name"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_rename_branch_failure(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_rename_branch on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="fatal: rename failed"
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_rename_branch("bad", "/workspace")

    assert success is False
    assert error is not None
    assert "git branch -m failed" in error


# === Tests for rebase ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_rebase_success(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_rebase on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_rebase("feature", "main", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "rebase", "--onto", "main", "feature"]
    # Verify 600s timeout
    assert mock_run.call_args[1]["timeout"] == 600


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_rebase_failure(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_rebase on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="merge conflict")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_rebase("feature", "main", "/workspace")

    assert success is False
    assert error is not None
    assert "git rebase failed" in error


# === Tests for archive ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_archive_success(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_archive on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
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
def test_git_archive_tag_fails(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_archive when tagging fails."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="tag already exists"
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_archive("old-feature", "/workspace")

    assert success is False
    assert error is not None
    assert "git tag failed" in error
    # Should not attempt branch delete
    mock_run.assert_called_once()


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_archive_branch_delete_fails(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_archive when branch delete fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # tag succeeds
        MagicMock(returncode=1, stdout="", stderr="branch not found"),  # delete fails
    ]

    plugin = GitHubPlugin()
    success, error = plugin.vcs_archive("old-feature", "/workspace")

    assert success is False
    assert error is not None
    assert "git branch -D failed" in error


# === Tests for prune ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_prune_success(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_prune on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_prune("dead-branch", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "branch", "-D", "dead-branch"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_prune_failure(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_prune on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="error: branch not found"
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_prune("nonexistent", "/workspace")

    assert success is False
    assert error is not None
    assert "git branch -D failed" in error


# === Tests for stash_and_clean ===


@patch("builtins.open", mock_open())
@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_stash_and_clean_success(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_stash_and_clean on success."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="diff content", stderr=""),  # diff
        MagicMock(returncode=0, stdout="", stderr=""),  # reset
        MagicMock(returncode=0, stdout="", stderr=""),  # clean
    ]

    plugin = GitHubPlugin()
    success, error = plugin.vcs_stash_and_clean(
        "/tmp/backup.diff", "/workspace", timeout=300
    )

    assert success is True
    assert error is None
    assert mock_run.call_count == 3


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_stash_and_clean_diff_fails(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_stash_and_clean when diff fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="diff error")

    plugin = GitHubPlugin()
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
    """Test GitHubPlugin.vcs_stash_and_clean when file write fails."""
    mock_run.return_value = MagicMock(returncode=0, stdout="diff content", stderr="")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_stash_and_clean(
        "/tmp/backup.diff", "/workspace", timeout=300
    )

    assert success is False
    assert error is not None
    assert "Failed to write diff file" in error


@patch("builtins.open", mock_open())
@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_stash_and_clean_reset_fails(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_stash_and_clean when reset step fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="diff content", stderr=""),  # diff
        MagicMock(returncode=1, stdout="", stderr="reset error"),  # reset
    ]

    plugin = GitHubPlugin()
    success, error = plugin.vcs_stash_and_clean(
        "/tmp/backup.diff", "/workspace", timeout=300
    )

    assert success is False
    assert error is not None
    assert "git reset --hard failed" in error


@patch("builtins.open", mock_open())
@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_stash_and_clean_clean_fails(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_stash_and_clean when clean step fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="diff content", stderr=""),  # diff
        MagicMock(returncode=0, stdout="", stderr=""),  # reset ok
        MagicMock(returncode=1, stdout="", stderr="clean error"),  # clean fails
    ]

    plugin = GitHubPlugin()
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

    plugin = GitHubPlugin()
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

    plugin = GitHubPlugin()
    result = plugin.vcs_resolve_revision("sase_dull_basin__1", "sase", "/workspace")

    assert result == "dull-basin"


# === Tests for show_revision ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_show_revision_success(mock_run: MagicMock) -> None:
    """Test vcs_show_revision returns patch content on success."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="diff --git a/f b/f\n+hello\n", stderr=""
    )

    plugin = GitHubPlugin()
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

    plugin = GitHubPlugin()
    success, error = plugin.vcs_show_revision("bad-ref", "/workspace")

    assert success is False
    assert error is not None
    assert "git show failed" in error
