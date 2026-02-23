"""Tests for plugin discovery infrastructure."""

import os
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.config import load_merged_config
from sase.plugin_discovery import discover_plugin_resources, is_plugin_disabled
from sase.vcs_provider._errors import VCSProviderNotFoundError
from sase.vcs_provider._registry import _create_provider_for, _find_plugin_class


# === Tests for is_plugin_disabled ===


def test_disable_all_plugins() -> None:
    """SASE_DISABLE_PLUGINS disables all groups."""
    with patch.dict(os.environ, {"SASE_DISABLE_PLUGINS": "1"}):
        assert is_plugin_disabled("XPROMPTS") is True
        assert is_plugin_disabled("CONFIG") is True
        assert is_plugin_disabled("VCS") is True


def test_disable_specific_plugin_group() -> None:
    """SASE_DISABLE_PLUGIN_XPROMPTS disables only xprompts."""
    with patch.dict(os.environ, {"SASE_DISABLE_PLUGIN_XPROMPTS": "1"}, clear=False):
        os.environ.pop("SASE_DISABLE_PLUGINS", None)
        assert is_plugin_disabled("XPROMPTS") is True
        assert is_plugin_disabled("CONFIG") is False


def test_plugins_enabled_by_default() -> None:
    """Plugins are enabled when no env vars are set."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SASE_DISABLE_PLUGINS", None)
        os.environ.pop("SASE_DISABLE_PLUGIN_XPROMPTS", None)
        assert is_plugin_disabled("XPROMPTS") is False


def test_disable_all_empty_string_is_falsy() -> None:
    """Empty string env var does not disable."""
    with patch.dict(os.environ, {"SASE_DISABLE_PLUGINS": ""}):
        assert is_plugin_disabled("XPROMPTS") is False


# === Tests for discover_plugin_resources ===


def test_discover_plugin_resources_returns_modules() -> None:
    """Mock entry points return loaded modules."""
    mod = types.ModuleType("fake_plugin")

    ep = MagicMock()
    ep.name = "fake"
    ep.load.return_value = mod

    with patch(
        "sase.plugin_discovery.importlib.metadata.entry_points",
        return_value=[ep],
    ):
        result = discover_plugin_resources("sase_xprompts")

    assert result == [mod]


def test_discover_plugin_resources_sorted_by_name() -> None:
    """Modules are returned sorted by entry point name."""
    mod_b = types.ModuleType("plugin_b")
    mod_a = types.ModuleType("plugin_a")

    ep_b = MagicMock()
    ep_b.name = "b_plugin"
    ep_b.load.return_value = mod_b

    ep_a = MagicMock()
    ep_a.name = "a_plugin"
    ep_a.load.return_value = mod_a

    with patch(
        "sase.plugin_discovery.importlib.metadata.entry_points",
        return_value=[ep_b, ep_a],
    ):
        result = discover_plugin_resources("sase_xprompts")

    assert result == [mod_a, mod_b]


def test_discover_plugin_resources_skips_failures() -> None:
    """Entry points that fail to load are silently skipped."""
    good_mod = types.ModuleType("good")

    ep_bad = MagicMock()
    ep_bad.name = "bad"
    ep_bad.load.side_effect = ImportError("no such module")

    ep_good = MagicMock()
    ep_good.name = "good"
    ep_good.load.return_value = good_mod

    with patch(
        "sase.plugin_discovery.importlib.metadata.entry_points",
        return_value=[ep_bad, ep_good],
    ):
        result = discover_plugin_resources("sase_xprompts")

    assert result == [good_mod]


def test_discover_plugin_resources_empty_group() -> None:
    """Empty entry point group returns empty list."""
    with patch(
        "sase.plugin_discovery.importlib.metadata.entry_points",
        return_value=[],
    ):
        result = discover_plugin_resources("sase_xprompts")

    assert result == []


# === Tests for xprompt plugin discovery ===


def test_xprompt_plugin_discovery_loads_md_files(tmp_path: Path) -> None:
    """Plugin xprompts are loaded from entry point modules with xprompts/ dir."""
    from sase.xprompt.loader import _load_xprompts_from_plugins

    # Create a fake module with an xprompts/ resource directory
    xprompts_dir = tmp_path / "xprompts"
    xprompts_dir.mkdir()
    (xprompts_dir / "greet.md").write_text("Hello from plugin!")

    fake_module = types.ModuleType("fake_xprompt_plugin")
    fake_module.__name__ = "fake_xprompt_plugin"

    # Mock importlib.resources.files to return our tmp_path
    mock_files = MagicMock()
    mock_files.joinpath.return_value = xprompts_dir

    with (
        patch(
            "sase.xprompt.loader.discover_plugin_resources",
            return_value=[fake_module],
        ),
        patch(
            "sase.xprompt.loader.importlib.resources.files",
            return_value=mock_files,
        ),
        patch(
            "sase.xprompt.loader.is_plugin_disabled",
            return_value=False,
        ),
    ):
        result = _load_xprompts_from_plugins()

    assert "greet" in result
    assert result["greet"].content == "Hello from plugin!"
    assert "plugin:" in result["greet"].source_path


def test_xprompt_plugin_disabled_returns_empty() -> None:
    """Disabled plugin group returns empty dict."""
    from sase.xprompt.loader import _load_xprompts_from_plugins

    with patch("sase.xprompt.loader.is_plugin_disabled", return_value=True):
        result = _load_xprompts_from_plugins()

    assert result == {}


def test_xprompt_plugin_priority_in_get_all_xprompts(tmp_path: Path) -> None:
    """Plugin xprompts override internal but lose to config/project/filesystem."""
    from sase.xprompt.loader import get_all_xprompts
    from sase.xprompt.models import XPrompt

    plugin_xp = {
        "shared": XPrompt(
            name="shared", content="from plugin", inputs=[], source_path="plugin:test"
        )
    }
    internal_xp = {
        "shared": XPrompt(
            name="shared", content="from internal", inputs=[], source_path="internal"
        )
    }
    config_xp = {
        "shared": XPrompt(
            name="shared", content="from config", inputs=[], source_path="config"
        )
    }

    with (
        patch(
            "sase.xprompt.loader._load_xprompts_from_internal", return_value=internal_xp
        ),
        patch(
            "sase.xprompt.loader._load_xprompts_from_plugins", return_value=plugin_xp
        ),
        patch("sase.xprompt.loader._load_xprompts_from_config", return_value=config_xp),
        patch("sase.xprompt.loader._load_xprompts_from_files", return_value={}),
    ):
        result = get_all_xprompts()

    # Config overrides plugin, which overrides internal
    assert result["shared"].content == "from config"


def test_xprompt_plugin_overrides_internal() -> None:
    """Plugin xprompts override internal xprompts."""
    from sase.xprompt.loader import get_all_xprompts
    from sase.xprompt.models import XPrompt

    plugin_xp = {
        "shared": XPrompt(
            name="shared", content="from plugin", inputs=[], source_path="plugin:test"
        )
    }
    internal_xp = {
        "shared": XPrompt(
            name="shared", content="from internal", inputs=[], source_path="internal"
        )
    }

    with (
        patch(
            "sase.xprompt.loader._load_xprompts_from_internal", return_value=internal_xp
        ),
        patch(
            "sase.xprompt.loader._load_xprompts_from_plugins", return_value=plugin_xp
        ),
        patch("sase.xprompt.loader._load_xprompts_from_config", return_value={}),
        patch("sase.xprompt.loader._load_xprompts_from_files", return_value={}),
    ):
        result = get_all_xprompts()

    assert result["shared"].content == "from plugin"


# === Tests for workflow plugin discovery ===


def test_workflow_plugin_discovery_loads_yml_files(tmp_path: Path) -> None:
    """Plugin workflows are loaded from entry point modules with xprompts/ dir."""
    from sase.xprompt.workflow_loader import _load_workflows_from_plugins

    xprompts_dir = tmp_path / "xprompts"
    xprompts_dir.mkdir()
    (xprompts_dir / "my_flow.yml").write_text("steps:\n  - prompt_part: Do the thing\n")

    fake_module = types.ModuleType("fake_workflow_plugin")
    fake_module.__name__ = "fake_workflow_plugin"

    mock_files = MagicMock()
    mock_files.joinpath.return_value = xprompts_dir

    with (
        patch(
            "sase.xprompt.workflow_loader.discover_plugin_resources",
            return_value=[fake_module],
        ),
        patch(
            "sase.xprompt.workflow_loader.importlib.resources.files",
            return_value=mock_files,
        ),
        patch(
            "sase.xprompt.workflow_loader.is_plugin_disabled",
            return_value=False,
        ),
    ):
        result = _load_workflows_from_plugins()

    assert "my_flow" in result
    assert "plugin:" in result["my_flow"].source_path


def test_workflow_plugin_disabled_returns_empty() -> None:
    """Disabled plugin group returns empty dict for workflows."""
    from sase.xprompt.workflow_loader import _load_workflows_from_plugins

    with patch("sase.xprompt.workflow_loader.is_plugin_disabled", return_value=True):
        result = _load_workflows_from_plugins()

    assert result == {}


# === Tests for config plugin merging ===


def test_config_plugin_merging(tmp_path: Path) -> None:
    """Plugin configs merge between defaults and user config."""
    import yaml

    fake_module = types.ModuleType("fake_config_plugin")
    fake_module.__name__ = "fake_config_plugin"

    plugin_config_text = yaml.dump({"axe": {"max_runners": 99}})

    mock_ref = MagicMock()
    mock_ref.read_text.return_value = plugin_config_text

    mock_files = MagicMock()
    mock_files.joinpath.return_value = mock_ref

    with (
        patch("sase.config.CONFIG_DIR", tmp_path),
        patch(
            "sase.config.discover_plugin_resources",
            return_value=[fake_module],
        ),
        patch(
            "sase.config.importlib.resources.files",
            side_effect=lambda mod: (
                mock_files if mod == fake_module else _original_files(mod)
            ),
        ),
        patch("sase.config.is_plugin_disabled", return_value=False),
    ):
        result = load_merged_config()

    # Plugin overrides the default max_runners (5 → 99), no user config to override back
    assert result["axe"]["max_runners"] == 99


def _original_files(mod: str | types.ModuleType) -> MagicMock:
    """Fallback for the real importlib.resources.files call."""
    import importlib.resources

    return importlib.resources.files(mod)  # type: ignore[return-value]


def test_config_plugin_user_overrides_plugin(tmp_path: Path) -> None:
    """User config overrides plugin config values."""
    import yaml

    fake_module = types.ModuleType("fake_config_plugin")
    fake_module.__name__ = "fake_config_plugin"

    plugin_config_text = yaml.dump({"axe": {"max_runners": 99}})

    mock_ref = MagicMock()
    mock_ref.read_text.return_value = plugin_config_text

    mock_files = MagicMock()
    mock_files.joinpath.return_value = mock_ref

    # User config that overrides plugin
    user_config = tmp_path / "sase.yml"
    user_config.write_text(yaml.dump({"axe": {"max_runners": 3}}))

    with (
        patch("sase.config.CONFIG_DIR", tmp_path),
        patch(
            "sase.config.discover_plugin_resources",
            return_value=[fake_module],
        ),
        patch(
            "sase.config.importlib.resources.files",
            side_effect=lambda mod: (
                mock_files if mod == fake_module else _original_files(mod)
            ),
        ),
        patch("sase.config.is_plugin_disabled", return_value=False),
    ):
        result = load_merged_config()

    # User's value wins over plugin
    assert result["axe"]["max_runners"] == 3


def test_config_plugin_disabled_returns_defaults(tmp_path: Path) -> None:
    """Disabled config plugins fall back to just defaults."""
    with (
        patch("sase.config.CONFIG_DIR", tmp_path),
        patch("sase.config.is_plugin_disabled", return_value=True),
    ):
        result = load_merged_config()

    # Should have the default value, not any plugin value
    assert result["axe"]["max_runners"] == 5


# === Tests for VCS registry with entry points ===


def test_find_plugin_class_found() -> None:
    """_find_plugin_class returns class for matching entry point."""
    from sase.vcs_provider.plugins.github import GitHubPlugin

    ep = MagicMock()
    ep.name = "github"
    ep.load.return_value = GitHubPlugin

    with patch(
        "sase.vcs_provider._registry.importlib.metadata.entry_points",
        return_value=[ep],
    ):
        result = _find_plugin_class("github")

    assert result is GitHubPlugin


def test_find_plugin_class_not_found() -> None:
    """_find_plugin_class returns None when no match."""
    with patch(
        "sase.vcs_provider._registry.importlib.metadata.entry_points",
        return_value=[],
    ):
        result = _find_plugin_class("nonexistent")

    assert result is None


def test_create_provider_for_success() -> None:
    """_create_provider_for returns a VCSPluginManager for a valid plugin."""
    from sase.vcs_provider._plugin_manager import VCSPluginManager
    from sase.vcs_provider.plugins.hg import HgPlugin

    ep = MagicMock()
    ep.name = "hg"
    ep.load.return_value = HgPlugin

    with patch(
        "sase.vcs_provider._registry.importlib.metadata.entry_points",
        return_value=[ep],
    ):
        provider = _create_provider_for("hg", "/some/dir")

    assert isinstance(provider, VCSPluginManager)


def test_create_provider_for_not_found() -> None:
    """_create_provider_for raises VCSProviderNotFoundError for unknown name."""
    with patch(
        "sase.vcs_provider._registry.importlib.metadata.entry_points",
        return_value=[],
    ):
        with pytest.raises(VCSProviderNotFoundError) as exc_info:
            _create_provider_for("nonexistent", "/some/dir")

    assert "nonexistent" in str(exc_info.value)
    assert "Install the plugin" in str(exc_info.value)


def test_vcs_provider_not_found_error_custom_message() -> None:
    """VCSProviderNotFoundError accepts custom message."""
    err = VCSProviderNotFoundError("/dir", message="custom error msg")
    assert str(err) == "custom error msg"
    assert err.directory == "/dir"


def test_vcs_provider_not_found_error_default_message() -> None:
    """VCSProviderNotFoundError generates default message from directory."""
    err = VCSProviderNotFoundError("/dir")
    assert "/dir" in str(err)
