"""Render individual macro definitions and their local helpers."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from ._exceptions import MacroError
from ._jinja import substitute_placeholders, validate_and_convert_args
from .models import Macro


def expand_single_macro(
    macro_def: Macro,
    positional_args: list[str],
    named_args: dict[str, str],
    scope: dict[str, Any] | None = None,
    *,
    preserve_segment_separators: bool = False,
    defer_macro_names: Collection[str] = frozenset(),
    raise_on_error: bool = False,
) -> str:
    """Expand a single macro with its arguments.

    Args:
        macro: The Macro to expand.
        positional_args: List of positional argument values.
        named_args: Dictionary of named argument values.
        scope: Optional base context (e.g., workflow execution context).
            Macro-specific args take priority over scope values.
        preserve_segment_separators: When True, return a rendered multi-prompt
            macro body intact. Normal prompt-part expansion keeps only the
            first rendered segment.
        raise_on_error: When True, nested local-helper expansion raises
            ``MacroError`` instead of printing and exiting.

    Returns:
        The expanded macro content.

    Raises:
        MacroArgumentError: If arguments don't match placeholders.
        MacroError: If nested local-helper expansion fails and
            ``raise_on_error`` is True.
    """
    # Validate and convert args if macro has typed inputs
    conv_positional, conv_named = validate_and_convert_args(
        macro_def, positional_args, named_args
    )

    render_scope = _skill_render_scope(macro_def, scope)
    rendered = substitute_placeholders(
        macro_def.content,
        conv_positional,
        conv_named,
        macro_def.name,
        scope=render_scope,
    )
    rendered = _filter_conditional_macro_segments(rendered)
    if not rendered.strip():
        return ""
    rendered = _expand_local_macro_references(
        macro_def,
        rendered,
        conv_positional,
        conv_named,
        render_scope,
        preserve_segment_separators=preserve_segment_separators,
        defer_macro_names=defer_macro_names,
        raise_on_error=raise_on_error,
    )
    rendered = _filter_conditional_macro_segments(rendered)
    if not rendered.strip():
        return ""
    if preserve_segment_separators:
        return rendered

    from sase.agent.multi_prompt import split_segments_protecting_fences
    from sase.macro.segment_separators import macro_has_segment_separators

    if not macro_has_segment_separators(macro_def):
        return rendered

    segments = split_segments_protecting_fences(rendered)
    return segments[0] if segments else ""


def _filter_conditional_macro_segments(rendered: str) -> str:
    if "%if(" not in rendered:
        return rendered
    from sase.core.agent_launch_facade import filter_conditional_prompt_text

    return filter_conditional_prompt_text(rendered)


def _skill_render_scope(
    macro_def: Macro,
    scope: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Add provider template variables when expanding provider-backed skills."""
    if not macro_def.skill_name:
        return scope

    from sase.llm_provider.registry import get_default_provider_name
    from sase.main._init_skills_sources import provider_context

    try:
        provider = get_default_provider_name()
    except RuntimeError:
        return scope

    context: dict[str, Any] = provider_context(provider)
    if scope:
        context.update(scope)
    return context


def _scope_for_local_macros(
    scope: dict[str, Any] | None,
    positional_args: list[Any],
    named_args: dict[str, Any],
) -> dict[str, Any]:
    """Build the context inherited by local helpers from their owning macro."""
    local_scope = dict(scope or {})
    for i, arg in enumerate(positional_args, 1):
        local_scope[f"_{i}"] = arg
    local_scope["_args"] = positional_args
    local_scope.update(named_args)
    return local_scope


def _expand_local_macro_references(
    macro_def: Macro,
    rendered: str,
    positional_args: list[Any],
    named_args: dict[str, Any],
    scope: dict[str, Any] | None,
    *,
    preserve_segment_separators: bool,
    defer_macro_names: Collection[str],
    raise_on_error: bool = False,
) -> str:
    """Expand helpers scoped to *macro* without consulting the global catalog."""
    if not macro_def.local_macros or "#" not in rendered:
        return rendered

    from .processor import process_macro_references_with_catalog

    return process_macro_references_with_catalog(
        rendered,
        dict(macro_def.local_macros),
        extra_macros=macro_def.local_macros,
        scope=_scope_for_local_macros(scope, positional_args, named_args),
        aliases_resolved=True,
        preserve_segment_separators=preserve_segment_separators,
        defer_macro_names=defer_macro_names,
        raise_on_error=raise_on_error,
    )
