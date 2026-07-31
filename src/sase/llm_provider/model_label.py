"""Uniform ``Model: PROVIDER(model) @ <effort>`` Rich rendering.

Shared by the ACE TUI agent panels and the ``sase agent show`` CLI so the
effective model / provider / reasoning-effort reads identically regardless of
which surface renders it. This module is intentionally free of Textual imports
so lightweight CLI paths can render the same label without paying the TUI
import cost.
"""

from __future__ import annotations

from rich.text import Text


def append_model_field(
    header_text: Text,
    model: str | None,
    llm_provider: str | None,
    reasoning_effort: str | None = None,
) -> None:
    """Append the Model field with provider-themed styling.

    Format: ``Model: PROVIDER(model)`` with provider-specific colors, plus a
    uniform ``@ <effort>`` suffix (identical across every provider) when an
    effective reasoning effort is set. Falls back to plain model display when
    the provider is unknown.

    Args:
        header_text: Rich Text object to append to.
        model: Model name string (e.g., "opus", "gemini-3.6-flash-high").
        llm_provider: Provider name (e.g., "claude", "agy"), or None.
        reasoning_effort: Effective reasoning-effort level (e.g. "xhigh"), or
            None to omit the suffix.
    """
    if not model:
        return

    # Infer provider from model name if not explicitly stored
    provider = llm_provider
    if not provider:
        from sase.llm_provider.registry import resolve_model_provider

        resolved_provider, resolved_model = resolve_model_provider(model)
        if resolved_provider:
            provider = resolved_provider
            model = resolved_model
    else:
        from sase.llm_provider.config import resolve_model_alias

        resolved_model = resolve_model_alias(model)
        prefix, sep, rest = resolved_model.partition("/")
        if sep and prefix == provider:
            model = rest
        elif not sep:
            model = resolved_model

    header_text.append("Model: ", style="bold #87D7FF")

    if provider == "claude":
        # Hotrod theme: flame orange for name, amber/gold for model
        header_text.append("CLAUDE", style="bold #FF5F00")
        header_text.append("(", style="#D75F00")
        header_text.append(model, style="#FFAF00")
        header_text.append(")", style="#D75F00")
    elif provider == "codex":
        # OpenAI theme: chartreuse/lime for name, lighter lime for model
        header_text.append("CODEX", style="bold #87FF00")
        header_text.append("(", style="#5FAF00")
        header_text.append(model, style="#AFFF5F")
        header_text.append(")", style="#5FAF00")
    elif provider:
        from sase.llm_provider.registry import provider_cli_status_color_map

        color = provider_cli_status_color_map().get(provider, "#AF87D7")
        header_text.append(provider.upper(), style=f"bold {color}")
        header_text.append("(", style=color)
        header_text.append(model, style=color)
        header_text.append(")", style=color)
    else:
        from sase.llm_provider.registry import format_provider_model_label

        header_text.append(
            format_provider_model_label(provider, model), style="#AF87D7"
        )

    # Uniform reasoning-effort suffix, rendered the same way for every provider
    # so the effective effort reads identically regardless of which CLI ran.
    if reasoning_effort:
        header_text.append(" @ ", style="#878787")
        header_text.append(reasoning_effort, style="bold #AF87FF")

    header_text.append("\n")
