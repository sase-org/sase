"""Tests for the git VCS provider — query/info methods and Phase 5 additions.

Covers: get_branch_name, get_description, has_local_changes, get_workspace_name,
reword, get_change_url, get_cl_number, get_bug_number,
fix, upload, mail, reword_add_tag.
"""

from unittest.mock import MagicMock, patch

from sase.vcs_provider.plugins.bare_git import BareGitPlugin
from sase.vcs_provider.plugins.github import GitHubPlugin

# === Tests for get_branch_name ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_branch_name_success(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_branch_name on success."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="feature-branch\n", stderr=""
    )

    plugin = GitHubPlugin()
    success, name = plugin.vcs_get_branch_name("/workspace")

    assert success is True
    assert name == "feature-branch"


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_branch_name_detached_head(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_branch_name returns None in detached HEAD."""
    mock_run.return_value = MagicMock(returncode=0, stdout="HEAD\n", stderr="")

    plugin = GitHubPlugin()
    success, name = plugin.vcs_get_branch_name("/workspace")

    assert success is True
    assert name is None


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_branch_name_failure(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_branch_name on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a git repo")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_get_branch_name("/workspace")

    assert success is False
    assert error is not None
    assert "failed" in error


# === Tests for get_description ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_description_full(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_description returns full description."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout="Full commit message\n\nBody text\n", stderr=""
    )

    plugin = GitHubPlugin()
    success, desc = plugin.vcs_get_description("abc123", "/workspace", short=False)

    assert success is True
    assert desc is not None
    assert "Full commit message" in desc
    assert mock_run.call_args[0][0] == ["git", "log", "--format=%B", "-n1", "abc123"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_description_short(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_description with short=True."""
    mock_run.return_value = MagicMock(returncode=0, stdout="Short subject\n", stderr="")

    plugin = GitHubPlugin()
    success, desc = plugin.vcs_get_description("abc123", "/workspace", short=True)

    assert success is True
    assert desc is not None
    assert "Short subject" in desc
    assert mock_run.call_args[0][0] == ["git", "log", "--format=%s", "-n1", "abc123"]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_description_failure(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_description on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="unknown revision"
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_get_description("bad_rev", "/workspace", short=False)

    assert success is False
    assert error is not None
    assert "unknown revision" in error


# === Tests for has_local_changes ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_has_local_changes_with_changes(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_has_local_changes when changes exist."""
    mock_run.return_value = MagicMock(
        returncode=0, stdout=" M file.py\n?? new.py\n", stderr=""
    )

    plugin = GitHubPlugin()
    success, text = plugin.vcs_has_local_changes("/workspace")

    assert success is True
    assert text is not None
    assert "file.py" in text


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_has_local_changes_clean(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_has_local_changes when workspace is clean."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
    success, text = plugin.vcs_has_local_changes("/workspace")

    assert success is True
    assert text is None


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_has_local_changes_failure(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_has_local_changes on failure."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a repo")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_has_local_changes("/workspace")

    assert success is False
    assert error is not None
    assert "not a repo" in error


# === Tests for get_workspace_name ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_workspace_name_from_remote(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_workspace_name extracts from remote URL."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="https://github.com/user/my-repo.git\n",
        stderr="",
    )

    plugin = GitHubPlugin()
    success, name = plugin.vcs_get_workspace_name("/workspace")

    assert success is True
    assert name == "my-repo"


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_workspace_name_no_git_suffix(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_workspace_name with URL without .git suffix."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="https://github.com/user/my-repo\n",
        stderr="",
    )

    plugin = GitHubPlugin()
    success, name = plugin.vcs_get_workspace_name("/workspace")

    assert success is True
    assert name == "my-repo"


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_workspace_name_fallback_to_root(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_workspace_name falls back to repo root."""
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout="", stderr=""),  # no remote
        MagicMock(
            returncode=0, stdout="/home/user/my-project\n", stderr=""
        ),  # toplevel
    ]

    plugin = GitHubPlugin()
    success, name = plugin.vcs_get_workspace_name("/workspace")

    assert success is True
    assert name == "my-project"


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_workspace_name_both_fail(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_workspace_name when everything fails."""
    mock_run.side_effect = [
        MagicMock(returncode=1, stdout="", stderr=""),  # no remote
        MagicMock(returncode=1, stdout="", stderr=""),  # no toplevel
    ]

    plugin = GitHubPlugin()
    success, error = plugin.vcs_get_workspace_name("/workspace")

    assert success is False
    assert error is not None
    assert "Could not determine workspace name" in error


# === Tests for reword ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_reword_success(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_reword on success."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_reword("new description", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == [
        "git",
        "commit",
        "--amend",
        "-m",
        "new description",
    ]


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_reword_failure(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_reword on failure."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="nothing to amend"
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_reword("desc", "/workspace")

    assert success is False
    assert error is not None
    assert "git commit --amend failed" in error


# === Tests for get_change_url ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_change_url_with_pr(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_change_url when PR exists."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="https://github.com/user/repo/pull/42\n",
        stderr="",
    )

    plugin = GitHubPlugin()
    success, url = plugin.vcs_get_change_url("/workspace")

    assert success is True
    assert url == "https://github.com/user/repo/pull/42"


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_change_url_no_pr(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_change_url when no PR exists."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="no pull requests found"
    )

    plugin = GitHubPlugin()
    success, url = plugin.vcs_get_change_url("/workspace")

    assert success is True
    assert url is None


# === Tests for get_cl_number (PR number) ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_cl_number_with_pr(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_cl_number when PR exists."""
    mock_run.return_value = MagicMock(returncode=0, stdout="42\n", stderr="")

    plugin = GitHubPlugin()
    success, number = plugin.vcs_get_cl_number("/workspace")

    assert success is True
    assert number == "42"


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_get_cl_number_no_pr(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_get_cl_number when no PR exists."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="no pull requests found"
    )

    plugin = GitHubPlugin()
    success, number = plugin.vcs_get_cl_number("/workspace")

    assert success is True
    assert number is None


# === Tests for get_bug_number ===


def test_git_get_bug_number() -> None:
    """Test GitHubPlugin.vcs_get_bug_number returns empty string."""
    plugin = GitHubPlugin()
    success, bug = plugin.vcs_get_bug_number("/workspace")

    assert success is True
    assert bug == ""


# === Tests for fix / upload (no-ops) ===


def test_git_fix_noop() -> None:
    """Test GitHubPlugin.vcs_fix returns success (no-op)."""
    plugin = GitHubPlugin()
    success, error = plugin.vcs_fix("/workspace")

    assert success is True
    assert error is None


def test_git_upload_noop() -> None:
    """Test GitHubPlugin.vcs_upload returns success (no-op)."""
    plugin = GitHubPlugin()
    success, error = plugin.vcs_upload("/workspace")

    assert success is True
    assert error is None


# === Tests for mail ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_mail_push_and_create_pr(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_mail pushes and creates PR when none exists."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # git push
        MagicMock(returncode=1, stdout="", stderr="no PR"),  # gh pr view (no PR)
        MagicMock(returncode=0, stdout="", stderr=""),  # gh pr create
    ]

    plugin = GitHubPlugin()
    success, error = plugin.vcs_mail("feature-branch", "/workspace")

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


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_mail_push_existing_pr(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_mail just pushes when PR already exists."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # git push
        MagicMock(returncode=0, stdout="42\n", stderr=""),  # gh pr view (PR exists)
    ]

    plugin = GitHubPlugin()
    success, error = plugin.vcs_mail("feature-branch", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 2


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_mail_push_fails(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_mail when push fails."""
    mock_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="permission denied"
    )

    plugin = GitHubPlugin()
    success, error = plugin.vcs_mail("feature-branch", "/workspace")

    assert success is False
    assert error is not None
    assert "git push failed" in error


# === Tests for reword_add_tag ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_reword_add_tag_success(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_reword_add_tag appends tag to commit message."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="Existing message\n", stderr=""),  # git log
        MagicMock(returncode=0, stdout="", stderr=""),  # git commit --amend
    ]

    plugin = GitHubPlugin()
    success, error = plugin.vcs_reword_add_tag("BUG", "12345", "/workspace")

    assert success is True
    assert error is None
    # Verify the amended message includes the tag
    amend_call = mock_run.call_args_list[1]
    new_msg = amend_call[0][0][4]  # -m argument
    assert "Existing message\nBUG=12345" in new_msg


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_reword_add_tag_log_fails(mock_run: MagicMock) -> None:
    """Test GitHubPlugin.vcs_reword_add_tag when git log fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not a git repo")

    plugin = GitHubPlugin()
    success, error = plugin.vcs_reword_add_tag("BUG", "12345", "/workspace")

    assert success is False
    assert error is not None


# === Tests for bare remote behavior in mail/get_change_url/get_cl_number ===


@patch("sase.vcs_provider._command_runner.subprocess.run")
def test_git_mail_bare_remote_push_only(mock_run: MagicMock) -> None:
    """Test BareGitPlugin.vcs_mail pushes without PR creation for bare remotes."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    plugin = BareGitPlugin()
    success, error = plugin.vcs_mail("feature-branch", "/workspace")

    assert success is True
    assert error is None
    # Should only call push, no gh pr commands
    assert mock_run.call_count == 1
    assert mock_run.call_args_list[0][0][0] == [
        "git",
        "push",
        "-u",
        "origin",
        "feature-branch",
    ]


def test_git_get_change_url_bare_remote() -> None:
    """Test BareGitPlugin.vcs_get_change_url returns None for bare remotes."""
    plugin = BareGitPlugin()
    success, url = plugin.vcs_get_change_url("/workspace")

    assert success is True
    assert url is None


def test_git_get_cl_number_bare_remote() -> None:
    """Test BareGitPlugin.vcs_get_cl_number returns None for bare remotes."""
    plugin = BareGitPlugin()
    success, number = plugin.vcs_get_cl_number("/workspace")

    assert success is True
    assert number is None
