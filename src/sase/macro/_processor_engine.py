"""Expand macro references using a loaded catalog."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Collection
from typing import Any, NoReturn

from sase.content import (
    apply_section_marker_handling,
    content_ends_with_markdown_heading,
)
from sase.macro.cmdsub_source import (
    CmdsubProvenance,
    GeneratedTextGuard,
    execute_eligible_commands,
    generated_provenance,
    resolve_provenance,
)
from sase.macro._disabled_regions import (
    ensure_disabled_region_at_line_start,
    protect_disabled_regions,
    unprotect_disabled_regions,
)
from sase.macro._exceptions import LocalMacroTrustError, MacroError
from sase.macro._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from sase.macro.code_value import (
    protect_owned_code_directives,
    unprotect_owned_code_directives,
)
from ._parsing import (
    decode_macro_args,
    double_colon_text_start,
    find_double_colon_text_end,
    find_matching_paren_for_args,
    find_shorthand_text_end,
    iter_macro_references,
    parse_args,
)
from ._processor_lexical import (
    MACRO_PATTERN,
    prompt_may_reference_macro,
)
from ._processor_render import expand_single_macro
from ._trace import ExpansionTrace, format_circular_ref_diagnostic
from .models import Macro

_MAX_EXPANSION_ITERATIONS = 100


def _resolve_command_substitution_in_args(
    positional_args: list[str],
    named_args: dict[str, str],
    *,
    provenance: CmdsubProvenance,
    guard: GeneratedTextGuard,
) -> tuple[list[str], dict[str, str]]:
    """Resolve $(cmd) command substitutions in macro arguments.

    Only argument text from authorized source executes, at this source
    boundary. Generated spans (guard tokens hiding interpolated data and
    command stdout) are planned as protected ranges, and generated text or
    agent launches resolve nothing.

    Args:
        positional_args: Positional argument values.
        named_args: Named argument values.
        provenance: Explicit boundary provenance.
        guard: Guard hiding generated spans in the argument text.

    Returns:
        Tuple of (resolved_positional, resolved_named) with authorized
        $(cmd) patterns replaced by their command output.
    """
    if not provenance.may_execute:
        return positional_args, named_args
    has_cmd_sub = any("$(" in a for a in positional_args) or any(
        "$(" in v for v in named_args.values()
    )
    if not has_cmd_sub:
        return positional_args, named_args

    resolved_positional = [
        execute_eligible_commands(arg, provenance=provenance, guard=guard)
        if "$(" in arg
        else arg
        for arg in positional_args
    ]
    resolved_named = {
        k: execute_eligible_commands(v, provenance=provenance, guard=guard)
        if "$(" in v
        else v
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


def process_loaded_macro_catalog(
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
    print_status_fn: Callable[[str, str], None],
    resolve_macro_aliases_fn: Callable[[str], str],
    cmdsub_provenance: CmdsubProvenance | None = None,
    cmdsub_guard: GeneratedTextGuard | None = None,
) -> str:
    """Process macro references using an already-loaded macro catalog.

    The catalog expands in two passes. The first pass resolves references
    visible in the presented text with *cmdsub_provenance* (source text in
    a human launch executes argument and definition commands at their own
    boundaries; generated text and agent launches only expand). Generated
    spans stay hidden behind guard tokens through that pass, so only
    genuinely authored commands can execute. The first pass result is then
    unwrapped and a second, generated (expand-only) pass expands references
    that arrived inside interpolated data without executing anything.
    """
    provenance = resolve_provenance(cmdsub_provenance)
    guard = cmdsub_guard if cmdsub_guard is not None else GeneratedTextGuard()
    result = _catalog_expand_with_provenance(
        prompt,
        macros,
        extra_macros=extra_macros,
        scope=scope,
        trace=trace,
        aliases_resolved=aliases_resolved,
        preserve_segment_separators=preserve_segment_separators,
        defer_macro_names=defer_macro_names,
        raise_on_error=raise_on_error,
        print_status_fn=print_status_fn,
        resolve_macro_aliases_fn=resolve_macro_aliases_fn,
        provenance=provenance,
        guard=guard,
    )
    return guard.unwrap(result)


def _catalog_expand_with_provenance(
    prompt: str,
    macros: dict[str, Macro],
    *,
    extra_macros: dict[str, Macro] | None,
    scope: dict[str, Any] | None,
    trace: ExpansionTrace | None,
    aliases_resolved: bool,
    preserve_segment_separators: bool,
    defer_macro_names: Collection[str],
    raise_on_error: bool,
    print_status_fn: Callable[[str, str], None],
    resolve_macro_aliases_fn: Callable[[str], str],
    provenance: CmdsubProvenance,
    guard: GeneratedTextGuard,
) -> str:
    """Run alias resolution plus the source and generated expansion passes."""
    if "#" not in prompt:
        return prompt
    if not prompt_may_reference_macro(prompt, extra_macros):
        return prompt

    if not aliases_resolved:
        prompt = resolve_macro_aliases_fn(prompt)
        if "#" not in prompt:
            return prompt
        if not prompt_may_reference_macro(prompt, extra_macros):
            return prompt

    if extra_macros:
        macros = {**macros, **extra_macros}

    expandable_names = set(macros).difference(defer_macro_names)
    if not expandable_names:
        return prompt

    # Check if there are any potential macro references
    if "#" not in prompt:
        return prompt

    extra_names = set(extra_macros) if extra_macros else None
    prompt = _expansion_fixpoint(
        prompt,
        macros,
        expandable_names,
        extra_names=extra_names,
        scope=scope,
        trace=trace,
        preserve_segment_separators=preserve_segment_separators,
        defer_macro_names=defer_macro_names,
        raise_on_error=raise_on_error,
        print_status_fn=print_status_fn,
        provenance=provenance,
        guard=guard,
    )
    # Expose interpolated data so references that arrived inside rendered
    # values expand. The second pass always runs generated (expand-only):
    # it never executes argument or definition commands. It is also what
    # expands data references on ineligible launches, where the first pass
    # already skipped every execution.
    prompt = guard.unwrap(prompt)
    return _expansion_fixpoint(
        prompt,
        macros,
        expandable_names,
        extra_names=extra_names,
        scope=scope,
        trace=trace,
        preserve_segment_separators=preserve_segment_separators,
        defer_macro_names=defer_macro_names,
        raise_on_error=raise_on_error,
        print_status_fn=print_status_fn,
        provenance=generated_provenance(provenance.launch_authorship),
        guard=guard,
    )


def _expansion_fixpoint(
    prompt: str,
    macros: dict[str, Macro],
    expandable_names: set[str],
    *,
    extra_names: set[str] | None,
    scope: dict[str, Any] | None,
    trace: ExpansionTrace | None,
    preserve_segment_separators: bool,
    defer_macro_names: Collection[str],
    raise_on_error: bool,
    print_status_fn: Callable[[str, str], None],
    provenance: CmdsubProvenance,
    guard: GeneratedTextGuard,
) -> str:
    """Expand references to a fixpoint with one provenance.

    Blocked local-executable references are refused in every pass: data
    cannot smuggle a blocked reference past the trust check by arriving
    inside an interpolated value.
    """
    _refuse_blocked_local_macro_refs(
        prompt,
        macros,
        extra_names=extra_names,
        raise_on_error=raise_on_error,
        print_status_fn=print_status_fn,
    )

    if not macros:
        return prompt  # No macros defined

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
        matches = list(re.finditer(MACRO_PATTERN, prompt, re.MULTILINE))

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

                # Skip if this isn't a known macro. Blocked local
                # executables were already refused above so a remaining
                # catalog hit is a higher-priority filesystem namesake.
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

                # Resolve any $(cmd) command substitutions in arguments.
                # Only source-kind text in a human launch executes here;
                # generated spans stay hidden behind guard tokens.
                positional_args, named_args = _resolve_command_substitution_in_args(
                    positional_args,
                    named_args,
                    provenance=provenance,
                    guard=guard,
                )

                expanded = expand_single_macro(
                    macro_def,
                    positional_args,
                    named_args,
                    scope=scope,
                    preserve_segment_separators=preserve_segment_separators,
                    defer_macro_names=defer_macro_names,
                    raise_on_error=raise_on_error,
                    cmdsub_provenance=provenance,
                    cmdsub_guard=guard,
                )

                if trace is not None:
                    trace.add(
                        iteration=iteration,
                        name=name,
                        source_path=macro_def.source_path,
                        positional_args=[guard.unwrap(arg) for arg in positional_args],
                        named_args={
                            key: guard.unwrap(value)
                            for key, value in named_args.items()
                        },
                        expanded_text=guard.unwrap(expanded),
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
            _abort_expansion(
                e,
                raise_on_error=raise_on_error,
                print_status_fn=print_status_fn,
            )

        # Protect any new owned fences, then ordinary fences, from expansion.
        prompt = protect_owned_code_directives(prompt, owned_blocks)
        prompt = protect_fenced_blocks(prompt, fenced_blocks)

        iteration += 1

    if trace is not None:
        # A second (generated) pass must not erase the first pass count.
        trace.total_iterations = max(trace.total_iterations, iteration)

    if iteration >= _MAX_EXPANSION_ITERATIONS:
        if trace is not None and trace.records:
            msg = format_circular_ref_diagnostic(trace, _MAX_EXPANSION_ITERATIONS)
        else:
            msg = (
                f"Maximum macro expansion depth ({_MAX_EXPANSION_ITERATIONS}) "
                "exceeded. Check for circular references."
            )
        _abort_expansion(
            MacroError(msg),
            raise_on_error=raise_on_error,
            print_status_fn=print_status_fn,
        )

    # Restore disabled regions (markers preserved for downstream stages)
    prompt = unprotect_disabled_regions(prompt, disabled_regions)

    # Restore all fenced code blocks
    prompt = unprotect_fenced_blocks(prompt, fenced_blocks)
    prompt = unprotect_owned_code_directives(prompt, owned_blocks)

    return prompt


def _refuse_blocked_local_macro_refs(
    prompt: str,
    macros: dict[str, Macro],
    *,
    extra_names: set[str] | None,
    raise_on_error: bool,
    print_status_fn: Callable[[str, str], None],
) -> None:
    """Abort expansion when the prompt names a blocked local executable macro."""
    if "#" not in prompt:
        return
    from sase.macro.local_trust import blocked_local_macro_message

    seen: set[str] = set()
    for ref in iter_macro_references(prompt):
        name = ref.name
        if name in seen:
            continue
        seen.add(name)
        message = blocked_local_macro_message(
            name,
            catalog_item=macros.get(name),
            extra_names=extra_names,
        )
        if message:
            _abort_expansion(
                LocalMacroTrustError(message),
                raise_on_error=raise_on_error,
                print_status_fn=print_status_fn,
            )


def _abort_expansion(
    error: MacroError,
    *,
    raise_on_error: bool,
    print_status_fn: Callable[[str, str], None],
) -> NoReturn:
    """Raise *error* or print it and exit, depending on the caller opt-in."""
    if raise_on_error:
        raise error
    print_status_fn(str(error), "error")
    sys.exit(1)
