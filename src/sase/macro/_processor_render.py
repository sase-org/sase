"""Render individual macro definitions and their local helpers."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import replace
from typing import Any

from .cmdsub_source import (
    CmdsubProvenance,
    GeneratedTextGuard,
    PromptTextKind,
    execute_eligible_commands,
    resolve_provenance,
)
from ._exceptions import MacroError
from ._jinja import substitute_placeholders, validate_and_convert_args
from .code_value import CodeValue
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
    cmdsub_provenance: CmdsubProvenance | None = None,
    cmdsub_guard: GeneratedTextGuard | None = None,
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
        cmdsub_provenance: Provenance of the prompt that referenced this
            macro. Admitted-definition commands in the body execute only
            for source-kind text in a human launch; generated text and
            agent launches expand without executing. ``None`` presents the
            reference as human source with launch-stamp authorship.
        cmdsub_guard: Guard hiding generated spans from the definition
            boundary. ``None`` mints an ephemeral guard unwrapped before
            returning, so direct callers always get clean text.

    Returns:
        The expanded macro content.

    Raises:
        MacroArgumentError: If arguments don't match placeholders.
        MacroError: If nested local-helper expansion fails and
            ``raise_on_error`` is True.
    """
    provenance = resolve_provenance(cmdsub_provenance)
    own_guard = cmdsub_guard is None
    guard = cmdsub_guard if cmdsub_guard is not None else GeneratedTextGuard()
    # Each admitted definition is its own source boundary: body commands
    # execute here, before substituted argument/scope values (hidden behind
    # guard tokens) can reach the execution pass.
    if provenance.may_execute:
        body_provenance = CmdsubProvenance(
            kind=PromptTextKind.ADMITTED_DEFINITION,
            launch_authorship=provenance.launch_authorship,
        )
    else:
        body_provenance = provenance

    # Argument commands have already been resolved. Reveal only this guard's
    # data for validation and Jinja logic; rendering protects it again.
    revealed_positional = [guard.unwrap(arg) for arg in positional_args]
    revealed_named = {key: guard.unwrap(value) for key, value in named_args.items()}
    conv_positional, conv_named = validate_and_convert_args(
        macro_def, revealed_positional, revealed_named
    )

    revealed = {
        value
        for raw, value in (
            *zip(positional_args, revealed_positional, strict=True),
            *((named_args[key], value) for key, value in revealed_named.items()),
        )
        if value != raw
    }

    def _rehide(value: Any) -> Any:
        # Helpers mint a separate guard and unwrap on return. Keep newly
        # revealed data protected by this outer guard across that boundary.
        if isinstance(value, str) and value in revealed:
            return guard.wrap(value)
        if isinstance(value, list):
            return [_rehide(item) for item in value]
        if isinstance(value, tuple):
            return tuple(_rehide(item) for item in value)
        if isinstance(value, CodeValue) and value.source in revealed:
            return replace(value, source=guard.wrap(value.source))
        return value

    render_scope = _skill_render_scope(macro_def, scope)
    rendered = substitute_placeholders(
        macro_def.content,
        conv_positional,
        conv_named,
        macro_def.name,
        scope=render_scope,
        guard=guard,
    )
    # Filter conditional segments before the boundary executes: only text
    # that survives into the output may execute, mirroring the Jinja rule
    # that a false branch never runs a command.
    rendered = _filter_conditional_macro_segments(rendered, guard)
    rendered = execute_eligible_commands(
        rendered, provenance=body_provenance, guard=guard
    )
    if not rendered.strip():
        return guard.unwrap(rendered) if own_guard else rendered
    rendered = _expand_local_macro_references(
        macro_def,
        rendered,
        [_rehide(value) for value in conv_positional],
        {key: _rehide(value) for key, value in conv_named.items()},
        render_scope,
        preserve_segment_separators=preserve_segment_separators,
        defer_macro_names=defer_macro_names,
        raise_on_error=raise_on_error,
        # Nested helper boundaries mint their own ephemeral guard: sharing
        # this boundary's guard would let the nested mid-pass unwrap expose
        # outer generated spans to this pass's execution boundary early.
        cmdsub_provenance=body_provenance,
    )
    rendered = _filter_conditional_macro_segments(rendered, guard)
    if not rendered.strip():
        return guard.unwrap(rendered) if own_guard else rendered
    if preserve_segment_separators:
        return guard.unwrap(rendered) if own_guard else rendered

    from sase.agent.multi_prompt import split_segments_protecting_fences
    from sase.macro.segment_separators import macro_has_segment_separators

    if not macro_has_segment_separators(macro_def):
        return guard.unwrap(rendered) if own_guard else rendered

    segments = split_segments_protecting_fences(rendered)
    result = segments[0] if segments else ""
    return guard.unwrap(result) if own_guard else result


def _filter_conditional_macro_segments(
    rendered: str, guard: GeneratedTextGuard | None = None
) -> str:
    if "%if(" not in rendered:
        return rendered
    from sase.core.agent_launch_facade import filter_conditional_prompt_text

    if guard is not None:
        rendered = _unwrap_condition_tokens(rendered, guard)
    return filter_conditional_prompt_text(rendered)


def _unwrap_condition_tokens(rendered: str, guard: GeneratedTextGuard) -> str:
    """Expose guard-hidden values inside ``%if(...)`` conditions.

    The segment filter parses each condition value and consumes the
    directive, so no unwrapped span survives filtering; every other guard
    token stays hidden for downstream execution boundaries. Guard tokens
    never contain parentheses, so paren balancing can skip straight past
    them while locating each condition's end.
    """
    import re

    token_ends = dict(guard.spans_in(rendered))
    if not token_ends:
        return rendered
    parts: list[str] = []
    pos = 0
    for match in re.finditer(r"%if\(", rendered):
        start = match.start()
        parts.append(rendered[pos:start])
        depth = 1
        cursor = match.end()
        while cursor < len(rendered) and depth > 0:
            if cursor in token_ends:
                cursor = token_ends[cursor]
                continue
            if rendered[cursor] == "(":
                depth += 1
            elif rendered[cursor] == ")":
                depth -= 1
            cursor += 1
        parts.append(guard.unwrap(rendered[start:cursor]))
        pos = cursor
    parts.append(rendered[pos:])
    return "".join(parts)


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
    cmdsub_provenance: CmdsubProvenance | None = None,
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
        cmdsub_provenance=cmdsub_provenance,
    )
