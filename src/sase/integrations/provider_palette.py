"""Textual-free provider color palettes.

Derived hues use the same RGB blend as Textual's ``Color.blend``:
``int(src + (dst - src) * factor)`` toward white or black. Plugin-declared
brand colors that cannot be parsed as hex or ``rgb()`` degrade to the
neutral palette.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DERIVED_MODEL_LIFT = 0.40
_DERIVED_DIM_LIFT = 0.35
_DERIVED_SHADE_BLEND = 0.20
_HEX_RE = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
)
_RGB_RE = re.compile(
    r"^rgb\(\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*([0-9]+(?:\.[0-9]+)?)\s*,\s*"
    r"([0-9]+(?:\.[0-9]+)?)(?:\s*,\s*[0-9]+(?:\.[0-9]+)?)?\s*\)$"
)


@dataclass(frozen=True)
class ProviderPalette:
    """Resolved color palette for one LLM provider."""

    name_style: str
    delimiter_style: str
    model_style: str
    secondary_style: str
    dim_style: str


@dataclass(frozen=True, slots=True)
class ProviderTextPalette:
    """Two-tone foreground palette for provider-colored plain text."""

    subject_style: str
    detail_style: str


NEUTRAL_PROVIDER_STYLE = ProviderPalette(
    name_style="bold #AF87D7",
    delimiter_style="#875FAF",
    model_style="#D7AFFF",
    secondary_style="#875FAF",
    dim_style="dim #AF87D7",
)

PROVIDER_FALLBACK_STYLES: dict[str, ProviderPalette] = {
    "claude": ProviderPalette(
        name_style="bold #FF5F00",
        delimiter_style="#D75F00",
        model_style="#FFAF00",
        secondary_style="#D75F00",
        dim_style="dim #D7AF87",
    ),
    "anthropic": ProviderPalette(
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
    "openai": ProviderPalette(
        name_style="bold #10A37F",
        delimiter_style="#0E8F70",
        model_style="#63D9B6",
        secondary_style="#0E8F70",
        dim_style="dim #8FE6CF",
    ),
    "qwen": ProviderPalette(
        name_style="bold #D75FFF",
        delimiter_style="#AF5FD7",
        model_style="#E6A8FF",
        secondary_style="#AF5FD7",
        dim_style="dim #D7AFFF",
    ),
    "opencode": ProviderPalette(
        name_style="bold #FFD75F",
        delimiter_style="#D7AF00",
        model_style="#FFE08A",
        secondary_style="#D7AF00",
        dim_style="dim #E6D18A",
    ),
    "agy": ProviderPalette(
        name_style="bold #6E5DE7",
        delimiter_style="#5B4FD0",
        model_style="#A99CF5",
        secondary_style="#5B4FD0",
        dim_style="dim #B7ACF0",
    ),
    "muse": ProviderPalette(
        name_style="bold #3D9BFF",
        delimiter_style="#1877F2",
        model_style="#8CC4FF",
        secondary_style="#1877F2",
        dim_style="dim #8CC4FF",
    ),
    "meta": ProviderPalette(
        name_style="bold #3D9BFF",
        delimiter_style="#1877F2",
        model_style="#8CC4FF",
        secondary_style="#1877F2",
        dim_style="dim #8CC4FF",
    ),
    "xai": ProviderPalette(
        name_style="bold #00C8D7",
        delimiter_style="#00A0AD",
        model_style="#5FE3EF",
        secondary_style="#00A0AD",
        dim_style="dim #7FD4DD",
    ),
}


def _normalize_provider(provider: str | None) -> str | None:
    if provider is None:
        return None
    normalized = provider.strip().lower()
    return normalized or None


def _clamp_byte(value: float) -> int:
    return max(0, min(255, int(value)))


def _parse_rgb(primary: str) -> tuple[int, int, int] | None:
    text = primary.strip()
    hex_match = _HEX_RE.fullmatch(text)
    if hex_match is not None:
        digits = text[1:]
        if len(digits) in {3, 4}:
            r, g, b = digits[0], digits[1], digits[2]
            return int(r + r, 16), int(g + g, 16), int(b + b, 16)
        return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
    rgb_match = _RGB_RE.fullmatch(text)
    if rgb_match is not None:
        return (
            _clamp_byte(float(rgb_match.group(1))),
            _clamp_byte(float(rgb_match.group(2))),
            _clamp_byte(float(rgb_match.group(3))),
        )
    return None


def _blend(
    source: tuple[int, int, int],
    destination: tuple[int, int, int],
    factor: float,
) -> tuple[int, int, int]:
    if factor <= 0:
        return source
    if factor >= 1:
        return destination
    r1, g1, b1 = source
    r2, g2, b2 = destination
    return (
        int(r1 + (r2 - r1) * factor),
        int(g1 + (g2 - g1) * factor),
        int(b1 + (b2 - b1) * factor),
    )


def _hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _with_primary(style: ProviderPalette, primary: str) -> ProviderPalette:
    return ProviderPalette(
        name_style=f"bold {primary}",
        delimiter_style=style.delimiter_style,
        model_style=style.model_style,
        secondary_style=style.secondary_style,
        dim_style=style.dim_style,
    )


def _derived_style(primary: str) -> ProviderPalette:
    """Derive a whole palette from one plugin-declared brand color.

    Used for providers with no ``PROVIDER_FALLBACK_STYLES`` entry, so a
    third-party provider still gets its own hue family instead of the shared
    neutral violet. An unparseable color degrades to the neutral palette.
    """
    parsed = _parse_rgb(primary)
    if parsed is None:
        return NEUTRAL_PROVIDER_STYLE
    white = (255, 255, 255)
    black = (0, 0, 0)
    shade = _hex(_blend(parsed, black, _DERIVED_SHADE_BLEND))
    return ProviderPalette(
        name_style=f"bold {_hex(parsed)}",
        delimiter_style=shade,
        model_style=_hex(_blend(parsed, white, _DERIVED_MODEL_LIFT)),
        secondary_style=shade,
        dim_style=f"dim {_hex(_blend(parsed, white, _DERIVED_DIM_LIFT))}",
    )


def _plugin_primary_color(provider: str) -> str | None:
    """Return the plugin-declared primary color, or ``None`` when unavailable.

    Called from render paths, so a registry failure must degrade to the
    built-in palettes rather than raise.
    """
    try:
        from sase.llm_provider.registry import provider_cli_status_color_map

        return provider_cli_status_color_map().get(provider)
    except Exception:
        return None


def provider_style_for(provider: str | None) -> ProviderPalette:
    """Return a deterministic provider palette.

    Provider plugin metadata supplies the primary color. Built-in fallback
    palettes keep the related delimiter/model colors distinct for dense UI rows;
    a provider without one derives its whole palette from the primary instead.
    """
    normalized = _normalize_provider(provider)
    if normalized is None:
        return NEUTRAL_PROVIDER_STYLE

    fallback = PROVIDER_FALLBACK_STYLES.get(normalized)
    primary = _plugin_primary_color(normalized)
    if fallback is None:
        return _derived_style(primary) if primary else NEUTRAL_PROVIDER_STYLE
    return _with_primary(fallback, primary) if primary else fallback


def provider_name_style(provider: str | None) -> str:
    """Return the Rich style used for a provider-colored display name."""
    return provider_style_for(provider).name_style


def provider_bar_style(provider: str | None) -> str:
    """Return the un-bolded model hue used for provider-colored usage bars."""
    return provider_style_for(provider).model_style


def provider_text_palette(provider: str | None) -> ProviderTextPalette:
    """Return the subject/detail hues for provider-colored plain text.

    Both hues come from one provider resolution so they cannot drift apart at a
    call site: the subject is the un-bolded model hue and the detail is the
    recessive dim tint from the same hue family.
    """
    style = provider_style_for(provider)
    return ProviderTextPalette(
        subject_style=style.model_style,
        detail_style=style.dim_style,
    )


__all__ = [
    "NEUTRAL_PROVIDER_STYLE",
    "PROVIDER_FALLBACK_STYLES",
    "ProviderPalette",
    "ProviderTextPalette",
    "provider_bar_style",
    "provider_name_style",
    "provider_style_for",
    "provider_text_palette",
]
