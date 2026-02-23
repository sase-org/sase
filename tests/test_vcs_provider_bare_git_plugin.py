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


def test_bare_git_plugin_provider_is_vcs_provider(
    bare_git_provider: VCSPluginManager,
) -> None:
    """The plugin-backed provider is a VCSProvider."""
    assert isinstance(bare_git_provider, VCSProvider)


def test_bare_git_plugin_is_command_runner() -> None:
    """BareGitPlugin inherits from CommandRunner."""
    plugin = BareGitPlugin()
    assert isinstance(plugin, CommandRunner)


# === Tests for core git operations via plugin ===


@patch(_MOCK_TARGET)
def test_plugin_checkout_success(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = bare_git_provider.checkout("main", "/workspace")

    assert success is True
    assert error is None
    assert mock_run.call_args[0][0] == ["git", "checkout", "main"]


@patch(_MOCK_TARGET)
def test_plugin_diff_success(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="diff output", stderr="")
    success, text = bare_git_provider.diff("/workspace")

    assert success is True
    assert text == "diff output"


@patch(_MOCK_TARGET)
def test_plugin_add_remove(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = bare_git_provider.add_remove("/workspace")

    assert success is True
    assert error is None


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
def test_plugin_mail_push_only(
    mock_run: MagicMock, bare_git_provider: VCSPluginManager
) -> None:
    """mail only pushes, no PR creation."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    success, error = bare_git_provider.mail("feature-branch", "/workspace")

    assert success is True
    assert error is None
    # Only one call (git push), no gh commands
    assert mock_run.call_count == 1
    assert mock_run.call_args[0][0] == [
        "git",
        "push",
        "-u",
        "origin",
        "feature-branch",
    ]


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


def test_plugin_prepare_description_passthrough(
    bare_git_provider: VCSPluginManager,
) -> None:
    """Git plugins pass description through unchanged."""
    result = bare_git_provider.prepare_description_for_reword("hello\nworld")
    assert result == "hello\nworld"


# === Test registry integration ===


@patch("sase.vcs_provider._registry._resolve_vcs_name", return_value="bare_git")
def test_registry_routes_bare_git_through_plugin(mock_resolve: MagicMock) -> None:
    """get_vcs_provider returns a VCSPluginManager for bare_git."""
    from sase.vcs_provider._registry import get_vcs_provider

    provider = get_vcs_provider("/workspace")
    assert isinstance(provider, VCSPluginManager)
    assert isinstance(provider, VCSProvider)
