"""Macro reference processing for prompts."""

from __future__ import annotations

import re
import sys
from collections.abc import Collection
from typing import Any, NoReturn

from sase.macro._disabled_regions import (
    ensure_disabled_region_at_line_start,
    protect_disabled_regions,
    unprotect_disabled_regions,
)
from sase.macro._directive_types import KEY_MARKER_PATTERN
from sase.macro._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from sase.macro.code_value import (
    protect_owned_code_directives,
    unprotect_owned_code_directives,
)

from sase.output import print_status
from sase.content import (
    apply_section_marker_handling,
    content_ends_with_markdown_heading,
)

from ._exceptions import MacroError
from ._jinja import (
    is_jinja2_template,
    render_toplevel_jinja2,
    substitute_placeholders,
    validate_and_convert_args,
)
from ._parsing import (
    decode_macro_args,
    double_colon_text_start,
    find_double_colon_text_end,
    find_shorthand_text_end,
    find_matching_paren_for_args,
    iter_macro_references,
    parse_args,
)
from ._trace import ExpansionTrace, format_circular_ref_diagnostic
from .loader import get_all_macros
from .models import Macro
from .project_identity import (
    canonical_macro_project,
    known_project_namespaces,
)

# Maximum number of expansion iterations to prevent infinite loops
_MAX_EXPANSION_ITERATIONS = 100

# Pattern to match macro references: #name, #name(, #name:arg, or #name+
# Must be at start of string, after whitespace, or after certain punctuation
# Note: No space allowed after # (to avoid matching markdown headings)
# Supports:
#   - #name - simple macro (no args)
#   - #name( - parenthesis syntax start (matching ) found programmatically)
#   - #name:arg - colon syntax for args (word-like chars, comma-separated for multiple)
#   - #name:`arg` - colon syntax with backtick-delimited arg (any content)
#   - #name:$(cmd) - colon syntax with command substitution
#   - #name+ - plus syntax, equivalent to #name:true
# The colon arg also admits a keyed `{@<id>}` agent-name marker as an
# indivisible unit, so #fork:research.{@1!}.final survives lexing.
_MACRO_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"  # Must be at start, after whitespace, or after ([{"'
    r"#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"  # Group 1: macro name with optional namespace
    r"(?:(\()|:(`[^`]*`|\$\([^)]*\)|"  # Group 2: open paren OR Group 3: colon arg (backtick, $(cmd), or word)
    rf"(?:{KEY_MARKER_PATTERN}|[a-zA-Z0-9_.~,+/@-])*"  # arg body
    rf"(?:{KEY_MARKER_PATTERN}|[a-zA-Z0-9_~,+/@-])"  # arg must not end in .
    r")|(\+))?"  # Group 4: plus
)

_COMMON_VCS_MACRO_NAMES = frozenset({"gh", "git", "p4"})

# Launch analysis must discover metadata contributed by ordinary macros without
# executing workflows whose expansion reads mutable agent state.  Callers retain
# these references until the runner has admitted their dependency barrier.
LAUNCH_DEFERRED_MACRO_NAMES: frozenset[str] = frozenset({"fork"})


def _candidate_name(match: re.Match[str]) -> str:
    """Return the macro name represented by a regex match."""
    return match.group(1).replace("__", "/")


def _is_obvious_vcs_only_reference(match: re.Match[str], prompt: str) -> bool:
    """Return True for common leading VCS tags that are not macro refs."""
    prefix = prompt[: match.start()].strip()
    if prefix and not all(part.startswith("%") for part in prefix.split()):
        return False

    raw_name = match.group(1)
    if raw_name in _COMMON_VCS_MACRO_NAMES:
        return (
            match.group(2) is not None
            or match.group(3) is not None
            or match.group(4) is not None
        )
    return any(raw_name.startswith(f"{name}_") for name in _COMMON_VCS_MACRO_NAMES)


def prompt_may_reference_macro(
    prompt: str, extra_macros: dict[str, Macro] | None = None
) -> bool:
    """Cheaply detect whether *prompt* might contain a macro reference.

    This is intentionally lexical and conservative.  It avoids loading the
    full macro catalog for prompts that clearly cannot expand, while still
    returning True for ambiguous ``#name`` forms so the normal processor can
    decide using the real catalog.
    """
    if "#" not in prompt:
        return False

    extra_names = set(extra_macros or {})
    for match in re.finditer(_MACRO_PATTERN, prompt, re.MULTILINE):
        name = _candidate_name(match)
        if name in extra_names:
            return True
        if _is_obvious_vcs_only_reference(match, prompt):
            continue
        return True
    return False


def resolve_macro_aliases(prompt: str) -> str:
    """Resolve project aliases and macro aliases via raw text substitution.

    Aliases are defined in the ``macro_aliases`` config field and are
    substituted *before* any other macro processing.  This allows aliases
    like ``#c`` → ``#commit`` where the expanded syntax must be present
    in the raw text for later resolution logic.
    """
    if "#" not in prompt:
        return prompt

    from sase.project_aliases import canonicalize_project_aliases_in_prompt

    prompt = canonicalize_project_aliases_in_prompt(prompt)

    from sase.config import load_merged_config

    aliases: dict[str, str] = load_merged_config().get("macro_aliases", {})
    if not aliases:
        return prompt

    for alias_name, target in aliases.items():
        pattern = (
            r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
            r"#" + re.escape(alias_name) + r"(?![a-zA-Z0-9_/])"
        )
        prompt = re.sub(pattern, f"#{target}", prompt, flags=re.MULTILINE)

    return prompt


def _registered_project_namespace_from_prompt(prompt: str) -> str | None:
    """Return the first registered namespace referenced by *prompt*."""
    known_projects = known_project_namespaces()
    if not known_projects:
        return None

    for reference in iter_macro_references(prompt):
        namespace, separator, _name = reference.name.partition("/")
        if not separator:
            continue
        canonical = canonical_macro_project(namespace)
        if canonical in known_projects:
            return canonical
    return None


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


def _resolve_command_substitution_in_args(
    positional_args: list[str],
    named_args: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    """Resolve $(cmd) command substitutions in macro arguments.

    Args:
        positional_args: Positional argument values.
        named_args: Named argument values.

    Returns:
        Tuple of (resolved_positional, resolved_named) with any $(cmd)
        patterns replaced by their command output.
    """
    has_cmd_sub = any("$(" in a for a in positional_args) or any(
        "$(" in v for v in named_args.values()
    )
    if not has_cmd_sub:
        return positional_args, named_args

    # Lazy import keeps the file-reference helper out of the import-time graph.
    from sase.file_references import process_command_substitution

    resolved_positional = [
        process_command_substitution(arg) if "$(" in arg else arg
        for arg in positional_args
    ]
    resolved_named = {
        k: process_command_substitution(v) if "$(" in v else v
        for k, v in named_args.items()
    }
    return resolved_positional, resolved_named


def _consume_trailing_shorthand_text(prompt: str, end: int) -> tuple[list[str], int]:
    """Bind a ``: text``/``:: text`` shorthand payload trailing *end* structurally.

    Returns the payload as a single-element positional list (empty when no
    shorthand text follows *end*) plus the position past the consumed text.
    The payload is bound directly from source, never re-serialized into
    ``[[...]]`` and re-lexed, so prose containing ``]]`` survives intact.
    """
    double_start = double_colon_text_start(prompt, end)
    if double_start is not None:
        text_start = double_start
        text_end = find_double_colon_text_end(prompt, text_start)
    elif prompt[end:].startswith(": "):
        text_start = end + 2
        text_end = find_shorthand_text_end(prompt, text_start)
    else:
        return [], end
    shorthand_text = prompt[text_start:text_end].rstrip()
    if not shorthand_text:
        return [], end

    return [shorthand_text], text_end


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

    project = _registered_project_namespace_from_prompt(prompt)
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
    if "#" not in prompt:
        return prompt
    if not prompt_may_reference_macro(prompt, extra_macros):
        return prompt

    if not aliases_resolved:
        prompt = resolve_macro_aliases(prompt)
        if "#" not in prompt:
            return prompt
        if not prompt_may_reference_macro(prompt, extra_macros):
            return prompt

    if extra_macros:
        macros = {**macros, **extra_macros}
    if not macros:
        return prompt  # No macros defined

    expandable_names = set(macros).difference(defer_macro_names)
    if not expandable_names:
        return prompt

    # Check if there are any potential macro references
    if "#" not in prompt:
        return prompt

    # Protect directive-owned `%if::` / `%proc::` fences before ordinary
    # literal-zone protection so later macro/Jinja scans cannot see the body.
    owned_blocks: list[str] = []
    prompt = protect_owned_code_directives(prompt, owned_blocks)

    # Protect fenced code blocks from expansion.  Content inside
    # triple-backtick blocks is replaced with null-byte placeholders so
    # that neither shorthand preprocessing nor the macro regex treats
    # anything inside them as a reference.  After the loop completes we
    # restore the original code block content.
    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    # Protect disabled regions (%macros_enabled:false/true pairs).
    disabled_regions: list[str] = []
    prompt = protect_disabled_regions(prompt, disabled_regions)

    iteration = 0
    while iteration < _MAX_EXPANSION_ITERATIONS:
        # Find all macro references
        matches = list(re.finditer(_MACRO_PATTERN, prompt, re.MULTILINE))

        if not matches:
            break  # No more macros to expand

        # Check if any matches are actual macros we know about
        has_known_macro = False
        for match in matches:
            name = match.group(1).replace("__", "/")
            if name in expandable_names:
                has_known_macro = True
                break

        if not has_known_macro:
            break  # No known macros to expand

        # Expand from last to first to preserve positions
        try:
            for match in reversed(matches):
                name = match.group(1).replace("__", "/")

                # Skip if this isn't a known macro
                if name not in expandable_names:
                    continue

                macro_def = macros[name]

                # Extract arguments from parenthesis, colon, or plus syntax
                # Group 2: open paren marker, Group 3: colon arg, Group 4: plus
                has_open_paren = match.group(2) is not None
                colon_arg = match.group(3)
                plus_suffix = match.group(4)

                # Track the actual end position (may extend beyond match.end())
                match_end = match.end()

                positional_args: list[str]
                named_args: dict[str, str]
                if has_open_paren:
                    # Two-phase parsing: regex matched #name(, now find matching )
                    paren_start = match.end() - 1  # Position of the '('
                    paren_end = find_matching_paren_for_args(prompt, paren_start)
                    if paren_end is None:
                        # Unclosed paren - treat as no args
                        positional_args, named_args = [], {}
                    else:
                        # Extract content between ( and )
                        paren_content = prompt[paren_start + 1 : paren_end]
                        positional_args, named_args = parse_args(
                            paren_content, preserve_empty_args=True
                        )
                        match_end = paren_end + 1  # Include the closing )

                        # Handle "#name(args): text" / "#name(args):: text"
                        # shorthand: the payload is appended as an extra
                        # positional, bound directly from source rather than
                        # re-serialized into "[[...]]" and re-lexed.
                        shorthand_positional, shorthand_end = (
                            _consume_trailing_shorthand_text(prompt, match_end)
                        )
                        if shorthand_positional:
                            positional_args.extend(shorthand_positional)
                            match_end = shorthand_end
                elif colon_arg is not None:
                    # Strip backticks if present (backtick-delimited syntax);
                    # a quoted value is never decoded.
                    if colon_arg.startswith("`") and colon_arg.endswith("`"):
                        colon_arg = colon_arg[1:-1]
                        positional_args, named_args = [colon_arg], {}
                    else:
                        positional_args, named_args = decode_macro_args(
                            colon_arg.split(","), {}
                        )
                elif plus_suffix is not None:
                    positional_args, named_args = ["true"], {}
                else:
                    # Handle "#name: text" / "#name:: text" shorthand: the
                    # payload is bound directly from source as a single
                    # positional, rather than re-serialized into "[[...]]"
                    # and re-lexed.
                    named_args = {}
                    positional_args, match_end = _consume_trailing_shorthand_text(
                        prompt, match_end
                    )

                # Resolve any $(cmd) command substitutions in arguments
                positional_args, named_args = _resolve_command_substitution_in_args(
                    positional_args, named_args
                )

                expanded = expand_single_macro(
                    macro_def,
                    positional_args,
                    named_args,
                    scope=scope,
                    preserve_segment_separators=preserve_segment_separators,
                    defer_macro_names=defer_macro_names,
                    raise_on_error=raise_on_error,
                )

                if trace is not None:
                    trace.add(
                        iteration=iteration,
                        name=name,
                        source_path=macro_def.source_path,
                        positional_args=list(positional_args),
                        named_args=dict(named_args),
                        expanded_text=expanded,
                    )

                # Handle section markers (### or ---) with proper line positioning
                is_at_line_start = (
                    match.start() == 0 or prompt[match.start() - 1] == "\n"
                )
                expanded = apply_section_marker_handling(expanded, is_at_line_start)

                # When the expanded content ends with a markdown heading and
                # there's more content on the same line after the reference,
                # append a blank line so the following text appears below the
                # heading.  We use two newlines (\n\n) rather than one because
                # a single \n gets collapsed by the prettier formatting pass.
                if (
                    expanded
                    and content_ends_with_markdown_heading(expanded)
                    and match_end < len(prompt)
                    and prompt[match_end] != "\n"
                ):
                    expanded += "\n\n"

                expanded = ensure_disabled_region_at_line_start(
                    expanded, is_at_line_start
                )

                prompt = prompt[: match.start()] + expanded + prompt[match_end:]
        except MacroError as e:
            _abort_expansion(e, raise_on_error=raise_on_error)

        # Protect any new owned fences, then ordinary fences, from expansion.
        prompt = protect_owned_code_directives(prompt, owned_blocks)
        prompt = protect_fenced_blocks(prompt, fenced_blocks)

        iteration += 1

    if trace is not None:
        trace.total_iterations = iteration

    if iteration >= _MAX_EXPANSION_ITERATIONS:
        if trace is not None and trace.records:
            msg = format_circular_ref_diagnostic(trace, _MAX_EXPANSION_ITERATIONS)
        else:
            msg = (
                f"Maximum macro expansion depth ({_MAX_EXPANSION_ITERATIONS}) "
                "exceeded. Check for circular references."
            )
        _abort_expansion(MacroError(msg), raise_on_error=raise_on_error)

    # Restore disabled regions (markers preserved for downstream stages)
    prompt = unprotect_disabled_regions(prompt, disabled_regions)

    # Restore all fenced code blocks
    prompt = unprotect_fenced_blocks(prompt, fenced_blocks)
    prompt = unprotect_owned_code_directives(prompt, owned_blocks)

    return prompt


def _abort_expansion(error: MacroError, *, raise_on_error: bool) -> NoReturn:
    """Raise *error* or print it and exit, depending on the caller opt-in."""
    if raise_on_error:
        raise error
    print_status(str(error), "error")
    sys.exit(1)


__all__ = [
    "LAUNCH_DEFERRED_MACRO_NAMES",
    "is_jinja2_template",
    "prompt_may_reference_macro",
    "process_macro_references",
    "process_macro_references_with_catalog",
    "render_toplevel_jinja2",
    "resolve_macro_aliases",
]
