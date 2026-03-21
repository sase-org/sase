"""Tests for plugin discovery infrastructure."""

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.config import load_merged_config
from sase.main.plugin_discovery import discover_plugin_resources
from sase.vcs_provider._errors import VCSProviderNotFoundError
from sase.vcs_provider._registry import _create_provider_for


# === Tests for is_plugin_disabled ===


# === Tests for discover_plugin_resources ===


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
        "sase.main.plugin_discovery.importlib.metadata.entry_points",
        return_value=[ep_bad, ep_good],
    ):
        result = discover_plugin_resources("sase_xprompts")

    assert result == [good_mod]


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


# === Tests for workflow plugin discovery ===


# === Tests for config plugin merging ===


def _original_files(mod: str | types.ModuleType) -> MagicMock:
    """Fallback for the real importlib.resources.files call."""
    import importlib.resources

    return importlib.resources.files(mod)  # type: ignore[return-value]


def test_config_plugin_user_overrides_plugin(tmp_path: Path) -> None:
    """User config overrides plugin config values."""
    import yaml

    fake_module = types.ModuleType("fake_config_plugin")
    fake_module.__name__ = "fake_config_plugin"

    plugin_config_text = yaml.dump({"axe": {"max_hook_runners": 99}})

    mock_ref = MagicMock()
    mock_ref.read_text.return_value = plugin_config_text

    mock_files = MagicMock()
    mock_files.joinpath.return_value = mock_ref

    # User config that overrides plugin
    user_config = tmp_path / "sase.yml"
    user_config.write_text(yaml.dump({"axe": {"max_hook_runners": 3}}))

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch(
            "sase.main.plugin_discovery.discover_plugin_resources",
            return_value=[fake_module],
        ),
        patch(
            "sase.config.core.importlib.resources.files",
            side_effect=lambda mod: (
                mock_files if mod == fake_module else _original_files(mod)
            ),
        ),
        patch("sase.main.plugin_discovery.is_plugin_disabled", return_value=False),
    ):
        result = load_merged_config()

    # User's value wins over plugin
    assert result["axe"]["max_hook_runners"] == 3


def test_config_plugin_disabled_returns_defaults(tmp_path: Path) -> None:
    """Disabled config plugins fall back to just defaults."""
    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.main.plugin_discovery.is_plugin_disabled", return_value=True),
    ):
        result = load_merged_config()

    # Should have the default value, not any plugin value
    assert result["axe"]["max_hook_runners"] == 3


# === Tests for VCS registry with entry points ===


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
