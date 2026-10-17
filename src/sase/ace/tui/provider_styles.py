"""Shared provider/model styling helpers for TUI surfaces."""

from __future__ import annotations

from sase.integrations.provider_badges import (
    provider_emoji_badge as _shared_provider_emoji_badge,
)
from sase.integrations.provider_palette import (
    ProviderPalette,
    ProviderTextPalette,
    provider_bar_style,
    provider_name_style,
    provider_style_for,
    provider_text_palette,
)
from rich.markup import escape
from rich.text import Text


def provider_emoji_badge(provider: str | None) -> str | None:
    """Return the compact row emoji for known LLM providers."""
    return _shared_provider_emoji_badge(provider)


def _resolve_provider_and_model(
    llm_provider: str | None,
    model: str | None,
) -> tuple[str | None, str | None]:
    """Infer the provider/model pair for display without changing semantics."""
    provider = llm_provider.strip().lower() if llm_provider else None
    if provider == "":
        provider = None
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
        style = provider_style_for(None)
        return f"[{style.name_style}]{escape(label)}[/]"

    style = provider_style_for(provider)
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
    style = provider_style_for(provider)
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
    advisory_label: str | None = None,
    advisory_severity: str | None = None,
) -> Text:
    """Render a dense selectable model row."""
    style = provider_style_for(provider)
    label = Text()
    if hint:
        label.append(f"{hint:>2} ", style=style.name_style)
    else:
        label.append("   ")
    label.append(model_id, style=style.model_style)
    if alias:
        label.append("  ")
        label.append(alias, style=style.dim_style)
    if advisory_label:
        # Deliberately not provider-colored: an advisory has to read as a
        # warning rather than as more of the provider's own branding.
        from sase.llm_provider.registry import (
            model_advisory_color,
            model_advisory_marker,
        )

        color = model_advisory_color(advisory_severity)
        label.append("  ")
        label.append(model_advisory_marker(advisory_severity), style=f"bold {color}")
        label.append(f" {advisory_label}", style=color)
    return label


__all__ = [
    "ProviderPalette",
    "ProviderTextPalette",
    "model_option_text",
    "provider_bar_style",
    "provider_emoji_badge",
    "provider_header_text",
    "provider_model_badge_markup",
    "provider_name_style",
    "provider_style_for",
    "provider_text_palette",
]
