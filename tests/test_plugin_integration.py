"""Integration tests for plugin lifecycle with real installed plugins.

These tests verify end-to-end behavior with the actual sase-github and
sase-hg plugin packages installed.  Tests that require a specific plugin
are skipped when that plugin is not available.
"""

import os
from importlib.metadata import entry_points
from unittest.mock import patch

import pytest

from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider._registry import _create_provider_for, _find_plugin_class

# --- Plugin availability helpers ---

_vcs_eps = {ep.name for ep in entry_points(group="sase_vcs")}

has_github = "github" in _vcs_eps
has_hg = "hg" in _vcs_eps
has_bare_git = "bare_git" in _vcs_eps

skip_no_github = pytest.mark.skipif(not has_github, reason="sase-github not installed")
skip_no_hg = pytest.mark.skipif(not has_hg, reason="sase-hg not installed")
skip_no_both = pytest.mark.skipif(
    not (has_github and has_hg), reason="both sase-github and sase-hg required"
)


# === VCS provider resolution ===


class TestVCSProviderResolution:
    """Verify that all three VCS providers resolve via entry points."""

    def test_bare_git_always_available(self) -> None:
        """bare_git is built into core and always resolvable."""
        cls = _find_plugin_class("bare_git")
        assert cls is not None
        provider = _create_provider_for("bare_git", "/tmp")
        assert isinstance(provider, VCSPluginManager)

    @skip_no_github
    def test_github_resolves(self) -> None:
        """github provider resolves when sase-github is installed."""
        cls = _find_plugin_class("github")
        assert cls is not None
        provider = _create_provider_for("github", "/tmp")
        assert isinstance(provider, VCSPluginManager)

    @skip_no_hg
    def test_hg_resolves(self) -> None:
        """hg provider resolves when sase-hg is installed."""
        cls = _find_plugin_class("hg")
        assert cls is not None
        provider = _create_provider_for("hg", "/tmp")
        assert isinstance(provider, VCSPluginManager)

    @skip_no_both
    def test_all_three_providers_coexist(self) -> None:
        """All three VCS providers can be created in the same process."""
        providers = {
            name: _create_provider_for(name, "/tmp")
            for name in ("bare_git", "github", "hg")
        }
        assert len(providers) == 3
        assert all(isinstance(p, VCSPluginManager) for p in providers.values())


# === Xprompt discovery ===


class TestXpromptDiscovery:
    """Verify xprompts contributed by plugins are discoverable."""

    @skip_no_hg
    def test_hg_md_xprompts_discovered(self) -> None:
        """sase-hg contributes cldd and crs as .md xprompt parts."""
        from sase.xprompt.loader import _load_xprompts_from_plugins

        xprompts = _load_xprompts_from_plugins()
        # Only .md files are loaded as xprompts; .yml files are workflows
        for name in ("cldd", "crs"):
            assert name in xprompts, f"missing xprompt: {name}"

    @skip_no_hg
    def test_plugin_xprompts_have_plugin_source_path(self) -> None:
        """Plugin xprompts are tagged with a 'plugin:' source path."""
        from sase.xprompt.loader import _load_xprompts_from_plugins

        xprompts = _load_xprompts_from_plugins()
        for name in ("cldd", "crs"):
            source = xprompts[name].source_path
            assert source is not None and "plugin:" in source


# === Workflow discovery ===


class TestWorkflowDiscovery:
    """Verify workflows contributed by plugins are discoverable."""

    @skip_no_github
    def test_github_workflows_discovered(self) -> None:
        """sase-github contributes gh, pr, and new_pr_desc workflows."""
        from sase.xprompt.workflow_loader import _load_workflows_from_plugins

        workflows = _load_workflows_from_plugins()
        for name in ("gh", "pr", "new_pr_desc"):
            assert name in workflows, f"missing workflow: {name}"

    @skip_no_hg
    def test_hg_workflows_discovered(self) -> None:
        """sase-hg contributes hg, cl, and propose workflows."""
        from sase.xprompt.workflow_loader import _load_workflows_from_plugins

        workflows = _load_workflows_from_plugins()
        for name in ("hg", "cl", "propose"):
            assert name in workflows, f"missing workflow: {name}"


# === Config merging ===


class TestConfigMerging:
    """Verify plugin config defaults merge correctly."""

    @skip_no_hg
    def test_hg_plugin_config_merges(self) -> None:
        """sase-hg default_config.yml is loaded into merge chain."""
        from sase.config import _load_plugin_configs

        configs = _load_plugin_configs()
        # sase-hg's default_config.yml exists (may be empty/comments-only)
        # The function should complete without error even with empty config
        assert isinstance(configs, list)


# === SASE_DISABLE_PLUGINS env var ===


class TestDisablePlugins:
    """Verify SASE_DISABLE_PLUGINS blocks plugin discovery."""

    @skip_no_hg
    def test_disable_all_blocks_xprompts(self) -> None:
        """SASE_DISABLE_PLUGINS=1 prevents plugin xprompt loading."""
        from sase.xprompt.loader import _load_xprompts_from_plugins

        with patch.dict(os.environ, {"SASE_DISABLE_PLUGINS": "1"}):
            xprompts = _load_xprompts_from_plugins()

        assert len(xprompts) == 0

    @skip_no_both
    def test_disable_all_blocks_workflows(self) -> None:
        """SASE_DISABLE_PLUGINS=1 prevents plugin workflow loading."""
        from sase.xprompt.workflow_loader import _load_workflows_from_plugins

        with patch.dict(os.environ, {"SASE_DISABLE_PLUGINS": "1"}):
            workflows = _load_workflows_from_plugins()

        assert len(workflows) == 0

    @skip_no_hg
    def test_disable_xprompts_only(self) -> None:
        """SASE_DISABLE_PLUGIN_XPROMPTS blocks xprompts but not VCS."""
        from sase.xprompt.loader import _load_xprompts_from_plugins

        env = {"SASE_DISABLE_PLUGIN_XPROMPTS": "1"}
        with patch.dict(os.environ, env):
            os.environ.pop("SASE_DISABLE_PLUGINS", None)
            xprompts = _load_xprompts_from_plugins()

        assert len(xprompts) == 0
        # VCS should still work
        assert _find_plugin_class("hg") is not None


# === Graceful error on missing plugin ===


class TestMissingPlugin:
    """Verify graceful behavior when a plugin is not installed."""

    def test_unknown_vcs_provider_raises(self) -> None:
        """Requesting an unregistered VCS provider gives a helpful error."""
        from sase.vcs_provider._errors import VCSProviderNotFoundError

        with pytest.raises(VCSProviderNotFoundError) as exc_info:
            _create_provider_for("nonexistent_vcs", "/tmp")

        assert "nonexistent_vcs" in str(exc_info.value)
        assert "Install the plugin" in str(exc_info.value)

    def test_find_plugin_class_returns_none_for_missing(self) -> None:
        """_find_plugin_class returns None for unregistered names."""
        assert _find_plugin_class("nonexistent_vcs") is None
