"""Plugin ``sase_config`` layers stay out of the default test fixture.

A required plugin's ``default_config.yml`` belongs in production merge, not
in suite expectations. Tests assert bundled defaults; request
``real_plugin_config`` when the merge itself is the subject.
"""

from __future__ import annotations

from collections.abc import Iterator
import importlib.resources
from pathlib import Path
import types

import pytest
import yaml
from sase.config.core import (
    clear_config_cache,
    load_config_layers,
    load_merged_config,
)
from sase.config.loading import load_plugin_configs
from sase.main.plugin_discovery import is_plugin_disabled

_FAKE_PLUGIN_MODULE = "fake_isolation_plugin"
_RESEARCH_TRIBE = {
    "icon": "∴",
    "color": "#5FD7AF",
    "description": "Research swarm agents from a plugin default_config.",
}
_PLUGIN_CONFIG = {
    "ace": {"tribes": {"research": _RESEARCH_TRIBE}},
}


@pytest.fixture(autouse=True)
def _clear_tribe_display_cache() -> Iterator[None]:
    from sase.ace.tui.models import tribe_display

    tribe_display._tribe_displays_for_token.cache_clear()
    yield
    tribe_display._tribe_displays_for_token.cache_clear()


def _install_fake_sase_config_plugin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> types.ModuleType:
    """Discover a fake ``sase_config`` module whose YAML lives under *tmp_path*."""
    module = types.ModuleType(_FAKE_PLUGIN_MODULE)
    module.__name__ = _FAKE_PLUGIN_MODULE
    config_dir = tmp_path / _FAKE_PLUGIN_MODULE
    config_dir.mkdir()
    (config_dir / "default_config.yml").write_text(
        yaml.dump(_PLUGIN_CONFIG), encoding="utf-8"
    )
    real_files = importlib.resources.files

    def fake_discover(group: str) -> list[types.ModuleType]:
        return [module] if group == "sase_config" else []

    def fake_files(package: object) -> object:
        if (
            package is module
            or getattr(package, "__name__", None) == _FAKE_PLUGIN_MODULE
        ):
            return config_dir
        return real_files(package)

    monkeypatch.setattr(
        "sase.main.plugin_discovery.discover_plugin_resources", fake_discover
    )
    monkeypatch.setattr("sase.config.core.importlib.resources.files", fake_files)
    return module


def test_default_test_fixture_disables_plugin_config() -> None:
    """The suite sets ``SASE_DISABLE_PLUGIN_CONFIG`` so tests see bundled defaults."""
    assert is_plugin_disabled("CONFIG") is True
    tribes = load_merged_config()["ace"]["tribes"]
    assert "research" not in tribes
    assert set(tribes) == {"default", "epic", "chop", "pinned", "review"}


def test_default_fixture_skips_discovering_sase_config_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Isolation wins before entry-point discovery, even if a plugin is installed."""
    calls: list[str] = []

    def boom(group: str) -> list[types.ModuleType]:
        calls.append(group)
        raise AssertionError("plugin config discovery must stay disabled")

    monkeypatch.setattr("sase.main.plugin_discovery.discover_plugin_resources", boom)

    assert load_plugin_configs(importlib.resources.files) == []
    assert calls == []
    assert all(not layer.name.startswith("plugin:") for layer in load_config_layers())


def test_default_fixture_drops_a_discoverable_plugin_config_layer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A fake plugin tribe must not leak into merged config under the default fixture."""
    _install_fake_sase_config_plugin(monkeypatch, tmp_path)
    clear_config_cache()

    merged = load_merged_config()
    assert "research" not in merged["ace"]["tribes"]
    assert load_plugin_configs(importlib.resources.files) == []


def test_plugin_sase_config_layer_merges_when_opted_in(
    real_plugin_config: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Production merge still folds a plugin ``default_config.yml`` when asked."""
    _install_fake_sase_config_plugin(monkeypatch, tmp_path)
    clear_config_cache()

    assert is_plugin_disabled("CONFIG") is False
    merged = load_merged_config()
    assert merged["ace"]["tribes"]["research"] == _RESEARCH_TRIBE

    plugin_layers = [
        layer for layer in load_config_layers() if layer.name.startswith("plugin:")
    ]
    assert plugin_layers
    assert any(
        layer.data.get("ace", {}).get("tribes", {}).get("research") == _RESEARCH_TRIBE
        for layer in plugin_layers
    )

    from sase.ace.tui.models.tribe_display import tribe_display_for

    display = tribe_display_for("research")
    assert display.icon == "∴"
    assert display.color == "#5FD7AF"


def test_isolated_tribe_display_keeps_research_unstyled() -> None:
    """The visual snapshot premise: ``@research`` is not a bundled tribe."""
    from sase.ace.tui.models.tribe_display import (
        DEFAULT_TRIBE_DISPLAY,
        TRIBE_IDENTITY_FALLBACK_COLOR,
        tribe_display_for,
        tribe_identity_color,
    )

    assert tribe_display_for("research") == DEFAULT_TRIBE_DISPLAY
    assert tribe_identity_color("research") == TRIBE_IDENTITY_FALLBACK_COLOR
