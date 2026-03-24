"""Tests for the BareGit pluggy plugin.

Verifies that :class:`BareGitPlugin` works correctly when routed through
:class:`VCSPluginManager`.
"""

from unittest.mock import MagicMock, patch

import pluggy
import pytest
from sase.vcs_provider._base import VCSProvider
from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.plugins.bare_git import BareGitPlugin

_MOCK_TARGET = "sase.vcs_provider._command_runner.subprocess.run"


@pytest.fixture
def bare_git_provider() -> VCSPluginManager:
    """Create a VCSPluginManager backed by BareGitPlugin."""
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(BareGitPlugin())
    return VCSPluginManager(pm)


# === Tests for isinstance / type checks ===


def test_bare_git_plugin_is_command_runner() -> None:
    """BareGitPlugin inherits from CommandRunner."""
    plugin = BareGitPlugin()
    assert isinstance(plugin, CommandRunner)


# === Tests for core git operations via plugin ===


# === Tests for bare-git-specific operations ===


def test_plugin_get_change_url_returns_none(
    bare_git_provider: VCSPluginManager,
) -> None:
    """Bare git repos have no PR URL."""
    success, url = bare_git_provider.get_change_url("/workspace")

    assert success is True
    assert url is None


def test_plugin_get_cl_number_returns_none(
    bare_git_provider: VCSPluginManager,
) -> None:
    """Bare git repos have no PR number."""
    success, number = bare_git_provider.get_cl_number("/workspace")

    assert success is True
    assert number is None


@patch(_MOCK_TARGET)
def test_plugin_mail_push_failure(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """mail returns failure when push fails."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="push rejected")
    success, error = bare_git_provider.mail("feature-branch", "/workspace")

    assert success is False
    assert isinstance(error, str)


# === Tests for prepare_description_for_reword ===


# === Test registry integration ===


# === Tests for commit dispatch hooks ===


@patch(_MOCK_TARGET)
def test_vcs_create_commit_success(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """All git commands (add, commit, push, rev-parse) succeed."""
    mock_run.return_value = MagicMock(returncode=0, stdout="abc1234", stderr="")
    ok, result = bare_git_provider.create_commit(
        {"message": "fix: bug", "files": ["a.py"]}, "/workspace"
    )

    assert ok is True
    assert result == "abc1234"
    assert mock_run.call_count == 4  # add, commit, push, rev-parse


@patch(_MOCK_TARGET)
def test_vcs_create_commit_no_files_uses_add_all(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """Empty files list falls back to git add -A."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    bare_git_provider.create_commit({"message": "chore: sync", "files": []}, "/ws")

    add_call = mock_run.call_args_list[0]
    cmd = add_call[0][0]
    assert cmd == ["git", "add", "-A"]


@patch(_MOCK_TARGET)
def test_vcs_create_commit_push_fails(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """Returns error tuple when push fails."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # git add
        MagicMock(returncode=0, stdout="", stderr=""),  # git commit
        MagicMock(returncode=1, stdout="", stderr="push rejected"),  # git push
    ]
    ok, err = bare_git_provider.create_commit({"message": "test", "files": []}, "/ws")

    assert ok is False
    assert isinstance(err, str)


@patch(_MOCK_TARGET)
def test_vcs_create_proposal_delegates(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """create_proposal delegates to create_commit (same behavior for bare git)."""
    mock_run.return_value = MagicMock(returncode=0, stdout="abc1234", stderr="")
    ok, result = bare_git_provider.create_proposal(
        {"message": "propose: change"}, "/ws"
    )

    assert ok is True
    # Same sequence as create_commit: add, commit, push, rev-parse
    assert mock_run.call_count == 4


@patch(_MOCK_TARGET)
def test_vcs_create_pull_request_creates_branch(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """create_pull_request creates a new branch, commits, and pushes."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    ok, err = bare_git_provider.create_pull_request(
        {"name": "feat-x", "message": "add feature", "files": []}, "/ws"
    )

    assert ok is True
    checkout_call = mock_run.call_args_list[0]
    cmd = checkout_call[0][0]
    assert cmd == ["git", "checkout", "-b", "feat-x"]
    # 4 calls: checkout -b, add, commit, push -u
    assert mock_run.call_count == 4


@patch(_MOCK_TARGET)
def test_vcs_create_pull_request_push_fails(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """Returns error when push fails during pull request creation."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # checkout -b
        MagicMock(returncode=0, stdout="", stderr=""),  # add
        MagicMock(returncode=0, stdout="", stderr=""),  # commit
        MagicMock(returncode=1, stdout="", stderr="push failed"),  # push
    ]
    ok, err = bare_git_provider.create_pull_request(
        {"name": "feat-x", "message": "test", "files": []}, "/ws"
    )

    assert ok is False
    assert isinstance(err, str)


# === Test registry integration ===


@patch("sase.vcs_provider._registry._resolve_vcs_name", return_value="bare_git")
def test_registry_routes_bare_git_through_plugin(mock_resolve: MagicMock) -> None:
    """get_vcs_provider returns a VCSPluginManager for bare_git."""
    from sase.vcs_provider._registry import get_vcs_provider

    provider = get_vcs_provider("/workspace")
    assert isinstance(provider, VCSPluginManager)
    assert isinstance(provider, VCSProvider)
