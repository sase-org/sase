"""Uniform ``Model: PROVIDER(model) @ <effort>`` Rich rendering.

Shared by the ACE TUI agent panels and the ``sase agent show`` CLI so the
effective model / provider / reasoning-effort reads identically regardless of
which surface renders it. This module is intentionally free of Textual imports
so lightweight CLI paths can render the same label without paying the TUI
import cost.
"""

from __future__ import annotations

from rich.text import Text


def model_value_text(
    model: str | None,
    llm_provider: str | None,
    reasoning_effort: str | None = None,
) -> Text | None:
    """Return the styled ``PROVIDER(model) @ <effort>`` value, or None.

    Format: ``PROVIDER(model)`` with provider-specific colors, plus a uniform
    ``@ <effort>`` suffix (identical across every provider) when an effective
    reasoning effort is set. Falls back to plain model display when the
    provider is unknown.

    Args:
        model: Model name string (e.g., "opus", "gemini-3.6-flash-high").
        llm_provider: Provider name (e.g., "claude", "agy"), or None.
        reasoning_effort: Effective reasoning-effort level (e.g. "xhigh"), or
            None to omit the suffix.

    Returns:
        The styled value, or None when ``model`` is falsy.
    """
    if not model:
        return None

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

    value = Text()

    if provider == "claude":
        # Hotrod theme: flame orange for name, amber/gold for model
        value.append("CLAUDE", style="bold #FF5F00")
        value.append("(", style="#D75F00")
        value.append(model, style="#FFAF00")
        value.append(")", style="#D75F00")
    elif provider == "codex":
        # OpenAI theme: chartreuse/lime for name, lighter lime for model
        value.append("CODEX", style="bold #87FF00")
        value.append("(", style="#5FAF00")
        value.append(model, style="#AFFF5F")
        value.append(")", style="#5FAF00")
    elif provider:
        from sase.llm_provider.registry import provider_cli_status_color_map

        color = provider_cli_status_color_map().get(provider, "#AF87D7")
        value.append(provider.upper(), style=f"bold {color}")
        value.append("(", style=color)
        value.append(model, style=color)
        value.append(")", style=color)
    else:
        from sase.llm_provider.registry import format_provider_model_label

        value.append(format_provider_model_label(provider, model), style="#AF87D7")

    # Uniform reasoning-effort suffix, rendered the same way for every provider
    # so the effective effort reads identically regardless of which CLI ran.
    if reasoning_effort:
        value.append(" @ ", style="#878787")
        value.append(reasoning_effort, style="bold #AF87FF")

    return value


def append_model_field(
    header_text: Text,
    model: str | None,
    llm_provider: str | None,
    reasoning_effort: str | None = None,
) -> None:
    """Append the Model field with provider-themed styling.

    Args:
        header_text: Rich Text object to append to.
        model: Model name string (e.g., "opus", "gemini-3.6-flash-high").
        llm_provider: Provider name (e.g., "claude", "agy"), or None.
        reasoning_effort: Effective reasoning-effort level (e.g. "xhigh"), or
            None to omit the suffix.
    """
    value = model_value_text(model, llm_provider, reasoning_effort)
    if value is None:
        return
    header_text.append("Model: ", style="bold #87D7FF")
    header_text.append_text(value)
    header_text.append("\n")
