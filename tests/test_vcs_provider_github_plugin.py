"""Tests for the GitHub pluggy plugin.

Verifies that :class:`GitHubPlugin` works correctly when routed through
:class:`VCSPluginManager`.
"""

from unittest.mock import MagicMock, patch

import pluggy
import pytest
from sase.vcs_provider._base import VCSProvider
from sase.vcs_provider._command_runner import CommandRunner
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.plugins.github import GitHubPlugin

_MOCK_TARGET = "sase.vcs_provider._command_runner.subprocess.run"


@pytest.fixture
def github_provider() -> VCSPluginManager:
    """Create a VCSPluginManager backed by GitHubPlugin."""
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(GitHubPlugin())
    return VCSPluginManager(pm)


# === Tests for isinstance / type checks ===


def test_github_plugin_provider_is_vcs_provider(
    github_provider: VCSPluginManager,
) -> None:
    """The plugin-backed provider is a VCSProvider."""
    assert isinstance(github_provider, VCSProvider)


def test_github_plugin_is_command_runner() -> None:
    """GitHubPlugin inherits from CommandRunner."""
    plugin = GitHubPlugin()
    assert isinstance(plugin, CommandRunner)


# === Tests for core git operations via plugin ===


@patch(_MOCK_TARGET)
def test_plugin_checkout_success(
    mock_run: MagicMock, github_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = github_provider.checkout("main", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "checkout", "main"]


@patch(_MOCK_TARGET)
def test_plugin_diff_success(
    mock_run: MagicMock, github_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="diff output", stderr="")
    success, text = github_provider.diff("/workspace")

    assert success is True
    assert text == "diff output"


@patch(_MOCK_TARGET)
def test_plugin_add_remove(
    mock_run: MagicMock, github_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = github_provider.add_remove("/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "add", "-A"]


@patch(_MOCK_TARGET)
def test_plugin_commit(mock_run: MagicMock, github_provider: VCSPluginManager) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = github_provider.commit("feature", "/tmp/msg.txt", "/workspace")

    assert success is True
    assert error is None


# === Tests for GitHub-specific operations ===


@patch(_MOCK_TARGET)
def test_plugin_get_change_url_with_pr(
    mock_run: MagicMock, github_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(
        returncode=0, stdout="https://github.com/user/repo/pull/42\n", stderr=""
    )
    success, url = github_provider.get_change_url("/workspace")

    assert success is True
    assert url == "https://github.com/user/repo/pull/42"


@patch(_MOCK_TARGET)
def test_plugin_get_change_url_no_pr(
    mock_run: MagicMock, github_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="no PR")
    success, url = github_provider.get_change_url("/workspace")

    assert success is True
    assert url is None


@patch(_MOCK_TARGET)
def test_plugin_get_cl_number_with_pr(
    mock_run: MagicMock, github_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="42\n", stderr="")
    success, number = github_provider.get_cl_number("/workspace")

    assert success is True
    assert number == "42"


@patch(_MOCK_TARGET)
def test_plugin_get_cl_number_no_pr(
    mock_run: MagicMock, github_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="no PR")
    success, number = github_provider.get_cl_number("/workspace")

    assert success is True
    assert number is None


@patch(_MOCK_TARGET)
def test_plugin_mail_creates_pr(
    mock_run: MagicMock, github_provider: VCSPluginManager
) -> None:
    """mail pushes and creates a PR when none exists."""
    # First call: git push (success)
    # Second call: gh pr view (fail = no existing PR)
    # Third call: gh pr create (success)
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),
        MagicMock(returncode=1, stdout="", stderr="no PR"),
        MagicMock(returncode=0, stdout="", stderr=""),
    ]
    success, error = github_provider.mail("feature-branch", "/workspace")

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


@patch(_MOCK_TARGET)
def test_plugin_mail_existing_pr(
    mock_run: MagicMock, github_provider: VCSPluginManager
) -> None:
    """mail pushes but skips PR creation when PR already exists."""
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # git push
        MagicMock(returncode=0, stdout="42\n", stderr=""),  # gh pr view (PR exists)
    ]
    success, error = github_provider.mail("feature-branch", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_count == 2


# === Tests for prepare_description_for_reword ===


def test_plugin_prepare_description_passthrough(
    github_provider: VCSPluginManager,
) -> None:
    """Git plugins pass description through unchanged."""
    result = github_provider.prepare_description_for_reword("hello\nworld")
    assert result == "hello\nworld"


# === Test registry integration ===


@patch("sase.vcs_provider._registry._resolve_vcs_name", return_value="github")
def test_registry_routes_github_through_plugin(mock_resolve: MagicMock) -> None:
    """get_vcs_provider returns a VCSPluginManager for github."""
    from sase.vcs_provider._registry import get_vcs_provider

    provider = get_vcs_provider("/workspace")
    assert isinstance(provider, VCSPluginManager)
    assert isinstance(provider, VCSProvider)
