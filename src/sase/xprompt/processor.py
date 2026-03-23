"""XPrompt reference processing for prompts."""

from __future__ import annotations

import re
import sys
from typing import Any

from sase.xprompt._disabled_regions import (
    protect_disabled_regions,
    unprotect_disabled_regions,
)
from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks

from sase.output import print_status
from sase.content import (
    apply_section_marker_handling,
    content_ends_with_markdown_heading,
)

from ._exceptions import XPromptError
from ._jinja import (
    is_jinja2_template,
    render_toplevel_jinja2,
    substitute_placeholders,
    validate_and_convert_args,
)
from ._parsing import (
    find_double_colon_text_end,
    find_shorthand_text_end,
    find_matching_paren_for_args,
    parse_args,
    preprocess_shorthand_syntax,
)
from ._trace import ExpansionTrace, format_circular_ref_diagnostic
from .loader import get_all_xprompts
from .models import XPrompt

# Maximum number of expansion iterations to prevent infinite loops
_MAX_EXPANSION_ITERATIONS = 100

# Matches content starting with a %xprompts_enabled:false marker.
_DISABLED_REGION_START_RE = re.compile(r"[ \t]*%xprompts_enabled:false")

# Pattern to match xprompt references: #name, #name(, #name:arg, or #name+
# Must be at start of string, after whitespace, or after certain punctuation
# Note: No space allowed after # (to avoid matching markdown headings)
# Supports:
#   - #name - simple xprompt (no args)
#   - #name( - parenthesis syntax start (matching ) found programmatically)
#   - #name:arg - colon syntax for single arg (word-like chars only)
#   - #name:`arg` - colon syntax with backtick-delimited arg (any content)
#   - #name:$(cmd) - colon syntax with command substitution
#   - #name+ - plus syntax, equivalent to #name:true
_XPROMPT_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"  # Must be at start, after whitespace, or after ([{"'
    r"#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"  # Group 1: xprompt name with optional namespace
    r"(?:(\()|:(`[^`]*`|\$\([^)]*\)|[a-zA-Z0-9_.~/-]*[a-zA-Z0-9_~/-])|(\+))?"  # Group 2: open paren OR Group 3: colon arg (backtick, $(cmd), or word) OR Group 4: plus
)


def resolve_xprompt_aliases(prompt: str) -> str:
    """Resolve xprompt aliases via raw text substitution.

    Aliases are defined in the ``xprompt_aliases`` config field and are
    substituted *before* any other xprompt processing.  This allows aliases
    like ``#gh_sase`` → ``#gh:sase`` where the colon syntax must be present
    in the raw text for VCS directory-switching logic.
    """
    from sase.config import load_merged_config

    aliases: dict[str, str] = load_merged_config().get("xprompt_aliases", {})
    if not aliases or "#" not in prompt:
        return prompt

    for alias_name, target in aliases.items():
        pattern = (
            r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
            r"#" + re.escape(alias_name) + r"(?![a-zA-Z0-9_/])"
        )
        prompt = re.sub(pattern, f"#{target}", prompt, flags=re.MULTILINE)

    return prompt


def _expand_single_xprompt(
    xprompt: XPrompt,
    positional_args: list[str],
    named_args: dict[str, str],
    scope: dict[str, Any] | None = None,
) -> str:
    """Expand a single xprompt with its arguments.

    Args:
        xprompt: The XPrompt to expand.
        positional_args: List of positional argument values.
        named_args: Dictionary of named argument values.
        scope: Optional base context (e.g., workflow execution context).
            Xprompt-specific args take priority over scope values.

    Returns:
        The expanded xprompt content.

    Raises:
        _XPromptArgumentError: If arguments don't match placeholders.
    """
    # Validate and convert args if xprompt has typed inputs
    conv_positional, conv_named = validate_and_convert_args(
        xprompt, positional_args, named_args
    )

    return substitute_placeholders(
        xprompt.content, conv_positional, conv_named, xprompt.name, scope=scope
    )


def _resolve_command_substitution_in_args(
    positional_args: list[str],
    named_args: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    """Resolve $(cmd) command substitutions in xprompt arguments.

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

    # Lazy import to avoid circular import:
    # processor -> gemini_wrapper.__init__ -> xprompt -> processor
    from sase.gemini_wrapper.file_references import process_command_substitution

    resolved_positional = [
        process_command_substitution(arg) if "$(" in arg else arg
        for arg in positional_args
    ]
    resolved_named = {
        k: process_command_substitution(v) if "$(" in v else v
        for k, v in named_args.items()
    }
    return resolved_positional, resolved_named


def process_xprompt_references(
    prompt: str,
    extra_xprompts: dict[str, XPrompt] | None = None,
    scope: dict[str, Any] | None = None,
    *,
    trace: ExpansionTrace | None = None,
    hooks_collector: list[str] | None = None,
) -> str:
    """Process xprompt references in the prompt.

    Expands all #xprompt_name and #xprompt_name(arg1, arg2) patterns
    with their corresponding content from files or config.

    Supports:
    - Simple xprompts: #foo
    - XPrompts with positional args: #bar(arg1, arg2)
    - XPrompts with named args: #bar(name=value, other="text")
    - Mixed args: #bar(pos1, name=value)
    - Text block args: #bar([[multi-line content]])
    - Colon syntax for single arg: #foo:arg
    - Plus syntax (equivalent to :true): #foo+
    - Legacy placeholders: {1}, {2}, {1:default}
    - Jinja2 templates: {{ name }}, {% if %}, etc.
    - Recursive expansion (xprompts can reference other xprompts)

    Args:
        prompt: The prompt text to process
        extra_xprompts: Optional additional xprompts that take highest priority
            (e.g., workflow-local xprompts).
        scope: Optional base context (e.g., workflow execution context) passed
            through to Jinja2 template rendering. Xprompt-specific args take
            priority over scope values.
        trace: Optional ExpansionTrace to collect expansion records into.
            When provided, each xprompt expansion is recorded with its
            iteration, source, arguments, and result.
        hooks_collector: Optional list to collect hook commands from expanded
            xprompts into. When provided, hook commands from each expanded
            xprompt's ``hooks`` field are appended to this list.

    Returns:
        The transformed prompt with xprompts expanded

    Raises:
        SystemExit: If any xprompt processing error occurs
    """
    prompt = resolve_xprompt_aliases(prompt)

    xprompts = get_all_xprompts()
    if extra_xprompts:
        xprompts.update(extra_xprompts)
    if not xprompts:
        return prompt  # No xprompts defined

    # Check if there are any potential xprompt references
    if "#" not in prompt:
        return prompt

    # Protect fenced code blocks from expansion.  Content inside
    # triple-backtick blocks is replaced with null-byte placeholders so
    # that neither shorthand preprocessing nor the xprompt regex treats
    # anything inside them as a reference.  After the loop completes we
    # restore the original code block content.
    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    # Protect disabled regions (%xprompts_enabled:false/true pairs).
    disabled_regions: list[str] = []
    prompt = protect_disabled_regions(prompt, disabled_regions)

    iteration = 0
    while iteration < _MAX_EXPANSION_ITERATIONS:
        # Pre-process shorthand syntax on each iteration
        # (expanded content may contain shorthand that needs processing)
        prompt = preprocess_shorthand_syntax(prompt, set(xprompts.keys()))

        # Find all xprompt references
        matches = list(re.finditer(_XPROMPT_PATTERN, prompt, re.MULTILINE))

        if not matches:
            break  # No more xprompts to expand

        # Check if any matches are actual xprompts we know about
        has_known_xprompt = False
        for match in matches:
            name = match.group(1).replace("__", "/")
            if name in xprompts:
                has_known_xprompt = True
                break

        if not has_known_xprompt:
            break  # No known xprompts to expand

        # Expand from last to first to preserve positions
        try:
            for match in reversed(matches):
                name = match.group(1).replace("__", "/")

                # Skip if this isn't a known xprompt
                if name not in xprompts:
                    continue

                xprompt = xprompts[name]

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
                        positional_args, named_args = parse_args(paren_content)
                        match_end = paren_end + 1  # Include the closing )

                        # Handle ": text" or ":: text" shorthand after closing
                        # paren. This is a fallback for references introduced
                        # mid-iteration by prior expansions.
                        after_close = prompt[match_end:]
                        if after_close.startswith(":: ") or after_close.startswith(
                            ": "
                        ):
                            is_double = after_close.startswith(":: ")
                            text_start = match_end + (3 if is_double else 2)
                            text_end = (
                                find_double_colon_text_end(prompt, text_start)
                                if is_double
                                else find_shorthand_text_end(prompt, text_start)
                            )
                            shorthand_text = prompt[text_start:text_end].rstrip()
                            if shorthand_text:
                                # Map to first input not already provided
                                for inp in xprompt.inputs:
                                    if inp.name not in named_args:
                                        named_args[inp.name] = shorthand_text
                                        break
                                else:
                                    positional_args.append(shorthand_text)
                                match_end = text_end
                elif colon_arg is not None:
                    # Strip backticks if present (backtick-delimited syntax)
                    if colon_arg.startswith("`") and colon_arg.endswith("`"):
                        colon_arg = colon_arg[1:-1]
                    positional_args, named_args = [colon_arg], {}
                elif plus_suffix is not None:
                    positional_args, named_args = ["true"], {}
                else:
                    positional_args, named_args = [], {}

                # Resolve any $(cmd) command substitutions in arguments
                positional_args, named_args = _resolve_command_substitution_in_args(
                    positional_args, named_args
                )

                expanded = _expand_single_xprompt(
                    xprompt, positional_args, named_args, scope=scope
                )

                if trace is not None:
                    trace.add(
                        iteration=iteration,
                        name=name,
                        source_path=xprompt.source_path,
                        positional_args=list(positional_args),
                        named_args=dict(named_args),
                        expanded_text=expanded,
                    )

                if hooks_collector is not None and xprompt.hooks:
                    hooks_collector.extend(xprompt.hooks)

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

                # Ensure disabled-region markers start on their own line.
                # When expanded content begins with %xprompts_enabled:false
                # but the insertion point is mid-line (e.g. after an
                # unexpanded VCS ref), prepend a newline so downstream
                # protect/strip_disabled_region_markers can match it.
                if (
                    expanded
                    and not is_at_line_start
                    and _DISABLED_REGION_START_RE.match(expanded)
                ):
                    expanded = "\n" + expanded

                prompt = prompt[: match.start()] + expanded + prompt[match_end:]
        except XPromptError as e:
            print_status(str(e), "error")
            sys.exit(1)

        # Protect any new fenced code blocks introduced by expanded content
        prompt = protect_fenced_blocks(prompt, fenced_blocks)

        iteration += 1

    if trace is not None:
        trace.total_iterations = iteration

    if iteration >= _MAX_EXPANSION_ITERATIONS:
        if trace is not None and trace.records:
            msg = format_circular_ref_diagnostic(trace, _MAX_EXPANSION_ITERATIONS)
        else:
            msg = (
                f"Maximum xprompt expansion depth ({_MAX_EXPANSION_ITERATIONS}) "
                "exceeded. Check for circular references."
            )
        print_status(msg, "error")
        sys.exit(1)

    # Restore disabled regions (markers preserved for downstream stages)
    prompt = unprotect_disabled_regions(prompt, disabled_regions)

    # Restore all fenced code blocks
    prompt = unprotect_fenced_blocks(prompt, fenced_blocks)

    return prompt


__all__ = [
    "is_jinja2_template",
    "process_xprompt_references",
    "render_toplevel_jinja2",
    "resolve_xprompt_aliases",
]
