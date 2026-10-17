"""Freeze the Textual-free provider palette against the pre-move capture table."""

from __future__ import annotations

import pytest
from textual.color import Color

from sase.integrations.provider_palette import (
    NEUTRAL_PROVIDER_STYLE,
    PROVIDER_FALLBACK_STYLES,
    ProviderPalette,
    _derived_style,
    provider_style_for,
)

_FALLBACK_CAPTURE: dict[str, ProviderPalette] = {
    "agy": ProviderPalette(
        name_style="bold #6E5DE7",
        delimiter_style="#5B4FD0",
        model_style="#A99CF5",
        secondary_style="#5B4FD0",
        dim_style="dim #B7ACF0",
    ),
    "anthropic": ProviderPalette(
        name_style="bold #FF5F00",
        delimiter_style="#D75F00",
        model_style="#FFAF00",
        secondary_style="#D75F00",
        dim_style="dim #D7AF87",
    ),
    "claude": ProviderPalette(
        name_style="bold #FF5F00",
        delimiter_style="#D75F00",
        model_style="#FFAF00",
        secondary_style="#D75F00",
        dim_style="dim #D7AF87",
    ),
    "codex": ProviderPalette(
        name_style="bold #10A37F",
        delimiter_style="#0E8F70",
        model_style="#63D9B6",
        secondary_style="#0E8F70",
        dim_style="dim #8FE6CF",
    ),
    "fakey": ProviderPalette(
        name_style="bold #FF5FAF",
        delimiter_style="#D74F93",
        model_style="#FF9FCD",
        secondary_style="#D74F93",
        dim_style="dim #E78FBB",
    ),
    "grok": ProviderPalette(
        name_style="bold #00C8D7",
        delimiter_style="#00A0AD",
        model_style="#5FE3EF",
        secondary_style="#00A0AD",
        dim_style="dim #7FD4DD",
    ),
    "meta": ProviderPalette(
        name_style="bold #3D9BFF",
        delimiter_style="#1877F2",
        model_style="#8CC4FF",
        secondary_style="#1877F2",
        dim_style="dim #8CC4FF",
    ),
    "muse": ProviderPalette(
        name_style="bold #3D9BFF",
        delimiter_style="#1877F2",
        model_style="#8CC4FF",
        secondary_style="#1877F2",
        dim_style="dim #8CC4FF",
    ),
    "openai": ProviderPalette(
        name_style="bold #10A37F",
        delimiter_style="#0E8F70",
        model_style="#63D9B6",
        secondary_style="#0E8F70",
        dim_style="dim #8FE6CF",
    ),
    "opencode": ProviderPalette(
        name_style="bold #FFD75F",
        delimiter_style="#D7AF00",
        model_style="#FFE08A",
        secondary_style="#D7AF00",
        dim_style="dim #E6D18A",
    ),
    "qwen": ProviderPalette(
        name_style="bold #D75FFF",
        delimiter_style="#AF5FD7",
        model_style="#E6A8FF",
        secondary_style="#AF5FD7",
        dim_style="dim #D7AFFF",
    ),
    "xai": ProviderPalette(
        name_style="bold #00C8D7",
        delimiter_style="#00A0AD",
        model_style="#5FE3EF",
        secondary_style="#00A0AD",
        dim_style="dim #7FD4DD",
    ),
}
_DERIVED_CAPTURE: dict[str, ProviderPalette] = {
    "#00C8D7": ProviderPalette(
        name_style="bold #00C8D7",
        delimiter_style="#00A0AC",
        model_style="#66DEE7",
        secondary_style="#00A0AC",
        dim_style="dim #59DBE5",
    ),
    "#3366FF": ProviderPalette(
        name_style="bold #3366FF",
        delimiter_style="#2851CC",
        model_style="#84A3FF",
        secondary_style="#2851CC",
        dim_style="dim #7A9BFF",
    ),
    "#6E5DE7": ProviderPalette(
        name_style="bold #6E5DE7",
        delimiter_style="#584AB8",
        model_style="#A89DF0",
        secondary_style="#584AB8",
        dim_style="dim #A095EF",
    ),
    "#FF5500": ProviderPalette(
        name_style="bold #FF5500",
        delimiter_style="#CC4400",
        model_style="#FF9966",
        secondary_style="#CC4400",
        dim_style="dim #FF9059",
    ),
    "#FFB454": ProviderPalette(
        name_style="bold #FFB454",
        delimiter_style="#CC9043",
        model_style="#FFD298",
        secondary_style="#CC9043",
        dim_style="dim #FFCE8F",
    ),
}


@pytest.fixture(autouse=True)
def _no_plugin_colors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the capture table independent of plugins installed on the host."""
    monkeypatch.setattr(
        "sase.llm_provider.registry.provider_cli_status_color_map",
        lambda: {},
    )


def test_fallback_palettes_match_the_pre_move_capture_table() -> None:
    assert PROVIDER_FALLBACK_STYLES == _FALLBACK_CAPTURE
    assert set(PROVIDER_FALLBACK_STYLES) == set(_FALLBACK_CAPTURE)


def test_style_for_returns_the_captured_fallback_without_plugin_colors() -> None:
    for provider, expected in _FALLBACK_CAPTURE.items():
        assert provider_style_for(provider) == expected
        assert provider_style_for(f"  {provider.upper()} ") == expected


def test_neutral_palette_matches_the_pre_move_capture() -> None:
    assert NEUTRAL_PROVIDER_STYLE == ProviderPalette(
        name_style="bold #AF87D7",
        delimiter_style="#875FAF",
        model_style="#D7AFFF",
        secondary_style="#875FAF",
        dim_style="dim #AF87D7",
    )
    assert provider_style_for(None) == NEUTRAL_PROVIDER_STYLE
    assert provider_style_for("mystery") == NEUTRAL_PROVIDER_STYLE


def test_derived_palettes_match_the_pre_move_capture_table() -> None:
    for primary, expected in _DERIVED_CAPTURE.items():
        assert _derived_style(primary) == expected


@pytest.mark.parametrize("primary", list(_DERIVED_CAPTURE))
def test_derived_style_matches_textual_color_blend(primary: str) -> None:
    base = Color.parse(primary)
    white = Color(255, 255, 255)
    black = Color(0, 0, 0)
    derived = _derived_style(primary)

    assert derived.name_style == f"bold {base.hex}"
    assert derived.delimiter_style == base.blend(black, 0.20).hex
    assert derived.model_style == base.blend(white, 0.40).hex
    assert derived.secondary_style == derived.delimiter_style
    assert derived.dim_style == f"dim {base.blend(white, 0.35).hex}"


def test_derived_style_accepts_rgb_and_short_hex() -> None:
    assert _derived_style("rgb(255, 85, 0)") == _DERIVED_CAPTURE["#FF5500"]
    assert _derived_style("#F50") == _DERIVED_CAPTURE["#FF5500"]


def test_unparseable_named_css_color_degrades_to_neutral() -> None:
    assert _derived_style("red") == NEUTRAL_PROVIDER_STYLE
    assert _derived_style("not-a-color") == NEUTRAL_PROVIDER_STYLE
