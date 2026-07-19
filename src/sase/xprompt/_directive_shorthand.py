"""Double-colon text-block shorthand for prompt directives."""

from __future__ import annotations

import re

from ._directive_alt import _ALT_DIRECTIVE_RE
from ._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
from ._disabled_regions import disabled_region_ranges
from ._exceptions import DirectiveError
from ._literal_zones import code_literal_ranges
from ._parsing import (
    find_matching_brace_for_args,
    find_matching_paren_for_args,
    parse_args,
)
from ._parsing_shorthand import format_as_text_block

_DIRECTIVE_TEXT_BLOCK_ARGUMENTS = {"clan": "summary"}
_CLAN_SUMMARY_ARGUMENTS = frozenset({"summary", "summary_script"})

_NEXT_PROMPT_ITEM_PATTERN = re.compile(
    r"\n(?=(?:%[a-zA-Z_][a-zA-Z0-9_]*|"
    r"#[a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
    r"(?:$|[\s(:+\[]))",
    re.MULTILINE,
)


def preprocess_directive_double_colon_shorthand(prompt: str) -> str:
    """Rewrite allowlisted ``%directive...:: text`` forms to named args.

    Directive shorthands and capture boundaries inside fenced code, inline
    code, or xprompt-disabled regions are ignored, matching normal directive
    extraction semantics.
    """
    ignored_ranges = [
        *code_literal_ranges(prompt),
        *disabled_region_ranges(prompt),
        *_alt_inner_ranges(prompt),
    ]
    replacements: list[tuple[int, int, str]] = []
    search_start = 0

    while match := re.search(
        _DIRECTIVE_PATTERN,
        prompt[search_start:],
        re.MULTILINE,
    ):
        match_start = search_start + match.start()
        match_end = search_start + match.end()
        if _is_inside_ranges(match_start, ignored_ranges):
            search_start = match_end
            continue

        raw_name = match.group(1)
        name = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
        target_arg = _DIRECTIVE_TEXT_BLOCK_ARGUMENTS.get(name)
        paren_open = match.group(2) is not None
        colon_arg = match.group(3)

        if paren_open:
            open_index = match_end - 1
            close_index = find_matching_paren_for_args(prompt, open_index)
            if close_index is None:
                search_start = match_end
                continue
            suffix_start = close_index + 1
            next_search_start = suffix_start
        else:
            close_index = None
            suffix_start = match_end
            next_search_start = match_end

        if (
            target_arg is None
            or (close_index is None and colon_arg is None)
            or not prompt.startswith(":: ", suffix_start)
        ):
            search_start = next_search_start
            continue

        if close_index is not None:
            args = prompt[open_index + 1 : close_index]
            _validate_no_explicit_text_argument(raw_name, args)
        else:
            assert colon_arg is not None
            args = _colon_arg_as_positional(colon_arg)

        text_start = suffix_start + 3
        text_end = _find_directive_double_colon_text_end(
            prompt,
            text_start,
            ignored_ranges=ignored_ranges,
        )
        text = prompt[text_start:text_end].rstrip()
        text_block = format_as_text_block(text)
        separator = ", " if args.strip() else ""
        replacement = f"%{raw_name}({args}{separator}{target_arg}=[[{text_block}]])"
        replacements.append((match_start, text_end, replacement))
        search_start = text_end

    rewritten = prompt
    for start, end, replacement in reversed(replacements):
        rewritten = rewritten[:start] + replacement + rewritten[end:]
    return rewritten


def _find_directive_double_colon_text_end(
    prompt: str,
    start: int,
    *,
    ignored_ranges: list[tuple[int, int]] | None = None,
) -> int:
    """Find the next line-start directive/xprompt reference or EOF."""
    ranges = ignored_ranges or []
    search_start = start
    while match := _NEXT_PROMPT_ITEM_PATTERN.search(prompt, search_start):
        item_start = match.start() + 1
        if not _is_inside_ranges(item_start, ranges):
            return match.start()
        search_start = item_start + 1
    return len(prompt)


def _validate_no_explicit_text_argument(raw_name: str, args: str) -> None:
    try:
        _, named_args = parse_args(args, reject_duplicate_named_args=True)
    except ValueError as exc:
        raise DirectiveError(str(exc)) from exc
    conflicts = sorted(_CLAN_SUMMARY_ARGUMENTS.intersection(named_args))
    if not conflicts:
        return
    rendered = " or ".join(f"{name}=" for name in conflicts)
    raise DirectiveError(
        f"Cannot combine %{raw_name}(...):: shorthand with explicit {rendered}."
    )


def _colon_arg_as_positional(colon_arg: str) -> str:
    if colon_arg.startswith("`") and colon_arg.endswith("`"):
        value = colon_arg[1:-1].replace("\\", "\\\\").replace('"', '\\"')
        return f'"{value}"'
    return colon_arg


def _alt_inner_ranges(prompt: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for match in _ALT_DIRECTIVE_RE.finditer(prompt):
        open_index = match.end() - 1
        if prompt[open_index] == "{":
            close_index = find_matching_brace_for_args(prompt, open_index)
        else:
            close_index = find_matching_paren_for_args(prompt, open_index)
        if close_index is not None:
            ranges.append((open_index + 1, close_index))
    return ranges


def _is_inside_ranges(position: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in ranges)
