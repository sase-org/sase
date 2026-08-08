"""Shared provider/model styling helpers for TUI surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from sase.integrations.provider_badges import (
    provider_emoji_badge as _shared_provider_emoji_badge,
)
from rich.markup import escape
from rich.text import Text


@dataclass(frozen=True)
class _ProviderStyle:
    """Resolved color palette for one LLM provider."""

    name_style: str
    delimiter_style: str
    model_style: str
    secondary_style: str
    dim_style: str


_NEUTRAL_PROVIDER_STYLE = _ProviderStyle(
    name_style="bold #AF87D7",
    delimiter_style="#875FAF",
    model_style="#D7AFFF",
    secondary_style="#875FAF",
    dim_style="dim #AF87D7",
)

_PROVIDER_FALLBACK_STYLES: dict[str, _ProviderStyle] = {
    "claude": _ProviderStyle(
        name_style="bold #FF5F00",
        delimiter_style="#D75F00",
        model_style="#FFAF00",
        secondary_style="#D75F00",
        dim_style="dim #D7AF87",
    ),
    "anthropic": _ProviderStyle(
        name_style="bold #FF5F00",
        delimiter_style="#D75F00",
        model_style="#FFAF00",
        secondary_style="#D75F00",
        dim_style="dim #D7AF87",
    ),
    "codex": _ProviderStyle(
        name_style="bold #10A37F",
        delimiter_style="#0E8F70",
        model_style="#63D9B6",
        secondary_style="#0E8F70",
        dim_style="dim #8FE6CF",
    ),
    "fakey": _ProviderStyle(
        name_style="bold #FF5FAF",
        delimiter_style="#D74F93",
        model_style="#FF9FCD",
        secondary_style="#D74F93",
        dim_style="dim #E78FBB",
    ),
    "openai": _ProviderStyle(
        name_style="bold #10A37F",
        delimiter_style="#0E8F70",
        model_style="#63D9B6",
        secondary_style="#0E8F70",
        dim_style="dim #8FE6CF",
    ),
    "qwen": _ProviderStyle(
        name_style="bold #D75FFF",
        delimiter_style="#AF5FD7",
        model_style="#E6A8FF",
        secondary_style="#AF5FD7",
        dim_style="dim #D7AFFF",
    ),
    "opencode": _ProviderStyle(
        name_style="bold #FFD75F",
        delimiter_style="#D7AF00",
        model_style="#FFE08A",
        secondary_style="#D7AF00",
        dim_style="dim #E6D18A",
    ),
    "agy": _ProviderStyle(
        name_style="bold #6E5DE7",
        delimiter_style="#5B4FD0",
        model_style="#A99CF5",
        secondary_style="#5B4FD0",
        dim_style="dim #B7ACF0",
    ),
    "muse": _ProviderStyle(
        name_style="bold #0064E0",
        delimiter_style="#0064E0",
        model_style="#4A9DFF",
        secondary_style="#1877F2",
        dim_style="dim #4A9DFF",
    ),
    "meta": _ProviderStyle(
        name_style="bold #0064E0",
        delimiter_style="#0064E0",
        model_style="#4A9DFF",
        secondary_style="#1877F2",
        dim_style="dim #4A9DFF",
    ),
}


def _normalize_provider(provider: str | None) -> str | None:
    if provider is None:
        return None
    normalized = provider.strip().lower()
    return normalized or None


def _with_primary(style: _ProviderStyle, primary: str) -> _ProviderStyle:
    return _ProviderStyle(
        name_style=f"bold {primary}",
        delimiter_style=style.delimiter_style,
        model_style=style.model_style,
        secondary_style=style.secondary_style,
        dim_style=style.dim_style,
    )


def _provider_style_for(provider: str | None) -> _ProviderStyle:
    """Return a deterministic provider palette.

    Provider plugin metadata supplies the primary color. Built-in fallback
    palettes keep the related delimiter/model colors distinct for dense UI rows.
    """
    normalized = _normalize_provider(provider)
    if normalized is None:
        return _NEUTRAL_PROVIDER_STYLE

    from sase.llm_provider.registry import provider_cli_status_color_map

    fallback = _PROVIDER_FALLBACK_STYLES.get(normalized, _NEUTRAL_PROVIDER_STYLE)
    primary = provider_cli_status_color_map().get(normalized)
    if primary:
        return _with_primary(fallback, primary)
    return fallback


def provider_emoji_badge(provider: str | None) -> str | None:
    """Return the compact row emoji for known LLM providers."""
    return _shared_provider_emoji_badge(provider)


def provider_name_style(provider: str | None) -> str:
    """Return the Rich style used for a provider-colored display name."""
    return _provider_style_for(provider).name_style


def _resolve_provider_and_model(
    llm_provider: str | None,
    model: str | None,
) -> tuple[str | None, str | None]:
    """Infer the provider/model pair for display without changing semantics."""
    provider = _normalize_provider(llm_provider)
    display_model = model
    if model:
        from sase.llm_provider.registry import resolve_model_provider

        resolved_provider, resolved_model = resolve_model_provider(model)
        if not provider and resolved_provider:
            provider = resolved_provider
            display_model = resolved_model
        elif resolved_provider == provider:
            display_model = resolved_model
    return provider, display_model


def provider_model_badge_markup(
    llm_provider: str | None,
    model: str | None,
) -> str:
    """Render ``PROVIDER(model)`` as Rich markup with provider theming."""
    if not llm_provider and not model:
        return ""

    from sase.llm_provider.registry import format_provider_model_label

    provider, display_model = _resolve_provider_and_model(llm_provider, model)
    if provider is None:
        label = format_provider_model_label(llm_provider, display_model)
        style = _provider_style_for(None)
        return f"[{style.name_style}]{escape(label)}[/]"

    style = _provider_style_for(provider)
    provider_name = provider.upper()
    if display_model:
        return (
            f"[{style.name_style}]{escape(provider_name)}[/]"
            f"[{style.delimiter_style}]([/]"
            f"[{style.model_style}]{escape(display_model)}[/]"
            f"[{style.delimiter_style}])[/]"
        )
    return f"[{style.name_style}]{escape(provider_name)}[/]"


def provider_header_text(provider: str, model_count: int) -> Text:
    """Render a compact provider group header."""
    style = _provider_style_for(provider)
    label = Text("  ")
    label.append("━ ", style=style.secondary_style)
    label.append(provider.upper(), style=style.name_style)
    noun = "model" if model_count == 1 else "models"
    label.append(f"  {model_count} {noun}", style=style.dim_style)
    return label


def model_option_text(
    *,
    provider: str | None,
    model_id: str,
    alias: str | None = None,
    hint: str | None = None,
) -> Text:
    """Render a dense selectable model row."""
    style = _provider_style_for(provider)
    label = Text()
    if hint:
        label.append(f"{hint:>2} ", style=style.name_style)
    else:
        label.append("   ")
    label.append(model_id, style=style.model_style)
    if alias:
        label.append("  ")
        label.append(alias, style=style.dim_style)
    return label
