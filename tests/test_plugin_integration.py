"""Integration tests for plugin lifecycle with real installed plugins.

These tests verify end-to-end behavior with the actual sase-github and
sase-hg plugin packages installed.  Tests that require a specific plugin
are skipped when that plugin is not available.
"""

import os
from importlib.metadata import entry_points
from unittest.mock import patch

import pytest


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


# === Xprompt discovery ===


class TestXpromptDiscovery:
    """Verify xprompts contributed by plugins are discoverable."""


# === Workflow discovery ===


class TestWorkflowDiscovery:
    """Verify workflows contributed by plugins are discoverable."""


# === Config merging ===


class TestConfigMerging:
    """Verify plugin config defaults merge correctly."""


# === SASE_DISABLE_PLUGINS env var ===


class TestDisablePlugins:
    """Verify SASE_DISABLE_PLUGINS blocks plugin discovery."""

    @skip_no_both
    def test_disable_all_blocks_workflows(self) -> None:
        """SASE_DISABLE_PLUGINS=1 prevents plugin workflow loading."""
        from sase.xprompt.workflow_loader import _load_workflows_from_plugins

        with patch.dict(os.environ, {"SASE_DISABLE_PLUGINS": "1"}):
            workflows = _load_workflows_from_plugins()

        assert len(workflows) == 0


# === Graceful error on missing plugin ===


class TestMissingPlugin:
    """Verify graceful behavior when a plugin is not installed."""
