"""Tests for the provider-colored plain-text palette in ``provider_styles``."""

from __future__ import annotations

import pytest
from textual.color import Color

from sase.ace.tui import provider_styles
from sase.ace.tui.provider_styles import (
    _NEUTRAL_PROVIDER_STYLE,
    _PROVIDER_FALLBACK_STYLES,
    ProviderTextPalette,
    provider_text_palette,
)

_NEUTRAL = ProviderTextPalette(
    subject_style=_NEUTRAL_PROVIDER_STYLE.model_style,
    detail_style=_NEUTRAL_PROVIDER_STYLE.dim_style,
)


def _plugin_colors(
    monkeypatch: pytest.MonkeyPatch,
    colors: dict[str, str],
) -> None:
    """Serve *colors* as the plugin-declared provider primaries."""
    monkeypatch.setattr(
        "sase.llm_provider.registry.provider_cli_status_color_map",
        lambda: dict(colors),
    )


@pytest.fixture(autouse=True)
def _no_plugin_colors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep palette results independent of the plugins installed on the host."""
    _plugin_colors(monkeypatch, {})


def test_registered_provider_returns_table_model_and_dim_hues() -> None:
    palette = provider_text_palette("grok")

    grok = _PROVIDER_FALLBACK_STYLES["grok"]
    assert palette.subject_style == grok.model_style
    assert palette.detail_style == grok.dim_style


def test_provider_lookup_is_case_and_whitespace_insensitive() -> None:
    assert provider_text_palette("  Claude ") == provider_text_palette("claude")


def test_plugin_primary_does_not_change_a_registered_providers_text_palette(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plugin primary only recolors the provider *name*, never the model."""
    before = provider_text_palette("codex")
    _plugin_colors(monkeypatch, {"codex": "#123456"})

    assert provider_text_palette("codex") == before


def test_different_registered_providers_have_different_subject_hues() -> None:
    subjects = {
        provider: provider_text_palette(provider).subject_style
        for provider in ("claude", "codex", "grok", "qwen", "opencode", "agy")
    }

    assert len(set(subjects.values())) == len(subjects)


def test_unregistered_provider_with_plugin_color_derives_its_own_palette(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plugin_colors(monkeypatch, {"acme": "#FF5500", "zeta": "#3366FF"})

    acme = provider_text_palette("acme")
    zeta = provider_text_palette("zeta")

    assert acme != _NEUTRAL
    assert zeta != _NEUTRAL
    assert acme.subject_style != zeta.subject_style
    assert acme.detail_style != zeta.detail_style


def test_derived_palette_lifts_the_subject_and_dims_the_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = "#3366FF"
    _plugin_colors(monkeypatch, {"acme": primary})

    palette = provider_text_palette("acme")

    assert Color.parse(palette.subject_style).brightness > (
        Color.parse(primary).brightness
    )
    assert palette.detail_style.startswith("dim ")
    assert Color.parse(palette.detail_style.removeprefix("dim ")).brightness > (
        Color.parse(primary).brightness
    )


def test_unregistered_provider_with_unparseable_color_is_neutral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plugin_colors(monkeypatch, {"acme": "not-a-color"})

    assert provider_text_palette("acme") == _NEUTRAL


def test_unknown_colorless_provider_is_neutral() -> None:
    assert provider_text_palette("acme") == _NEUTRAL


def test_none_and_blank_provider_are_neutral() -> None:
    assert provider_text_palette(None) == _NEUTRAL
    assert provider_text_palette("   ") == _NEUTRAL


def test_registry_failure_degrades_to_the_neutral_palette(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> dict[str, str]:
        raise RuntimeError("plugin metadata walk failed")

    monkeypatch.setattr(
        "sase.llm_provider.registry.provider_cli_status_color_map", boom
    )

    assert provider_text_palette("acme") == _NEUTRAL


def test_registry_failure_keeps_a_registered_providers_built_in_palette(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> dict[str, str]:
        raise RuntimeError("plugin metadata walk failed")

    monkeypatch.setattr(
        "sase.llm_provider.registry.provider_cli_status_color_map", boom
    )

    grok = _PROVIDER_FALLBACK_STYLES["grok"]
    assert provider_text_palette("grok") == ProviderTextPalette(
        subject_style=grok.model_style,
        detail_style=grok.dim_style,
    )


def test_derived_style_is_deterministic() -> None:
    assert provider_styles._derived_style("#FF5500") == provider_styles._derived_style(
        "#FF5500"
    )
