"""Macro reference processing for prompts.

This module keeps the original public import path while implementation lives in
private modules organized by processing stage.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from sase.output import print_status

from ._jinja import is_jinja2_template, render_toplevel_jinja2
from ._processor_engine import process_loaded_macro_catalog
from ._processor_lexical import (
    LAUNCH_DEFERRED_MACRO_NAMES,
    prompt_may_reference_macro,
    resolve_macro_aliases,
)
from ._processor_render import expand_single_macro
from ._trace import ExpansionTrace
from .loader import get_all_macros
from .models import Macro


def process_macro_references(
    prompt: str,
    extra_macros: dict[str, Macro] | None = None,
    scope: dict[str, Any] | None = None,
    *,
    trace: ExpansionTrace | None = None,
    defer_macro_names: Collection[str] = frozenset(),
    raise_on_error: bool = False,
) -> str:
    """Process macro references in the prompt.

    Expands all #macro_name and #macro_name(arg1, arg2) patterns
    with their corresponding content from files or config.

    Supports:
    - Simple macros: #foo
    - Macros with positional args: #bar(arg1, arg2)
    - Macros with named args: #bar(name=value, other="text")
    - Mixed args: #bar(pos1, name=value)
    - Text block args: #bar([[multi-line content]])
    - Colon syntax for single arg: #foo:arg
    - Plus syntax (equivalent to :true): #foo+
    - Legacy placeholders: {1}, {2}, {1:default}
    - Jinja2 templates: {{ name }}, {% if %}, etc.
    - Recursive expansion (macros can reference other macros)

    Args:
        prompt: The prompt text to process
        extra_macros: Optional additional macros that take highest priority
            (e.g., workflow-local macros).
        scope: Optional base context (e.g., workflow execution context) passed
            through to Jinja2 template rendering. Macro-specific args take
            priority over scope values.
        trace: Optional ExpansionTrace to collect expansion records into.
            When provided, each macro expansion is recorded with its
            iteration, source, arguments, and result.
        defer_macro_names: Macro names to leave verbatim while expanding all
            other references, including references introduced recursively.
        raise_on_error: When True, raise ``MacroError`` instead of printing
            the failure and exiting. The default print-and-exit path is
            unchanged so existing callers keep their current behavior.

    Returns:
        The transformed prompt with macros expanded

    Raises:
        SystemExit: If any macro processing error occurs and
            ``raise_on_error`` is False
        MacroError: If any macro processing error occurs and
            ``raise_on_error`` is True
    """
    if "#" not in prompt:
        return prompt
    if not prompt_may_reference_macro(prompt, extra_macros):
        return prompt

    prompt = resolve_macro_aliases(prompt)
    if "#" not in prompt:
        return prompt
    if not prompt_may_reference_macro(prompt, extra_macros):
        return prompt

    from ._processor_lexical import registered_project_namespace_from_prompt

    project = registered_project_namespace_from_prompt(prompt)
    macros = get_all_macros() if project is None else get_all_macros(project=project)
    if extra_macros:
        macros.update(extra_macros)

    return process_macro_references_with_catalog(
        prompt,
        macros,
        extra_macros=extra_macros,
        scope=scope,
        trace=trace,
        aliases_resolved=True,
        defer_macro_names=defer_macro_names,
        raise_on_error=raise_on_error,
    )


def process_macro_references_with_catalog(
    prompt: str,
    macros: dict[str, Macro],
    extra_macros: dict[str, Macro] | None = None,
    scope: dict[str, Any] | None = None,
    *,
    trace: ExpansionTrace | None = None,
    aliases_resolved: bool = False,
    preserve_segment_separators: bool = False,
    defer_macro_names: Collection[str] = frozenset(),
    raise_on_error: bool = False,
) -> str:
    """Process macro references using an already-loaded macro catalog."""
    return process_loaded_macro_catalog(
        prompt,
        macros,
        extra_macros=extra_macros,
        scope=scope,
        trace=trace,
        aliases_resolved=aliases_resolved,
        preserve_segment_separators=preserve_segment_separators,
        defer_macro_names=defer_macro_names,
        raise_on_error=raise_on_error,
        print_status_fn=print_status,
        resolve_macro_aliases_fn=resolve_macro_aliases,
    )


__all__ = [
    "LAUNCH_DEFERRED_MACRO_NAMES",
    "is_jinja2_template",
    "prompt_may_reference_macro",
    "process_macro_references",
    "process_macro_references_with_catalog",
    "render_toplevel_jinja2",
    "resolve_macro_aliases",
]
