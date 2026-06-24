"""Cross-provider contract tests.

Verifies that Hg-plugin, GitHub-plugin, and BareGit-plugin providers all
conform to the same VCSProvider interface contract using parameterized tests.
"""

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pluggy
import pytest
from sase.vcs_provider._base import VCSProvider
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.plugins.bare_git import BareGitPlugin


def _make_bare_git_plugin_provider() -> VCSPluginManager:
    """Create a VCSPluginManager backed by BareGitPlugin."""
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(BareGitPlugin())
    return VCSPluginManager(pm)


# Shared parameterization for all providers.
_PROVIDERS = pytest.mark.parametrize(
    "provider_factory,mock_target",
    [
        (
            _make_bare_git_plugin_provider,
            "sase.vcs_provider._command_runner.subprocess.run",
        ),
    ],
    ids=["bare_git_plugin"],
)


# === Tests for isinstance check ===


# === Tests for checkout contract ===


# === Tests for diff contract ===


# === Tests for add_remove contract ===


# === Tests for amend contract ===


@_PROVIDERS
def test_amend_success_returns_true_none(
    provider_factory: Callable[[], VCSProvider], mock_target: str
) -> None:
    """amend returns (True, None) on success."""
    with patch(mock_target) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        provider = provider_factory()
        success, error = provider.amend("fix typo", "/workspace")

    assert success is True
    assert error is None


# === Tests for rename_branch contract ===


@_PROVIDERS
def test_rename_branch_success_returns_true_none(
    provider_factory: Callable[[], VCSProvider], mock_target: str
) -> None:
    """rename_branch returns (True, None) on success."""
    with patch(mock_target) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        provider = provider_factory()
        success, error = provider.rename_branch("new_name", "/workspace")

    assert success is True
    assert error is None


# === Tests for rebase contract ===


@_PROVIDERS
def test_rebase_failure_returns_false_str(
    provider_factory: Callable[[], VCSProvider], mock_target: str
) -> None:
    """rebase returns (False, str) on failure."""
    with patch(mock_target) as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="conflict")
        provider = provider_factory()
        success, error = provider.rebase("feature", "main", "/workspace")

    assert success is False
    assert isinstance(error, str)


# === Tests for clean_workspace contract ===


# === Tests for archive contract ===


@_PROVIDERS
def test_archive_failure_returns_false_str(
    provider_factory: Callable[[], VCSProvider], mock_target: str
) -> None:
    """archive returns (False, str) on failure."""
    with patch(mock_target) as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="archive error"
        )
        provider = provider_factory()
        success, error = provider.archive("old-feature", "/workspace")

    assert success is False
    assert isinstance(error, str)


# === Tests for prepare_description_for_reword contract ===


# Both providers should handle the input without error;
# the actual escaping differs (Hg escapes newlines, Git passes through)
