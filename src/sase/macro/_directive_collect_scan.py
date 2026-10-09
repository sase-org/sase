"""Directive match scanning outside ``%alt`` and code interiors."""

from __future__ import annotations

import re

from ._directive_alt import _ALT_DIRECTIVE_RE
from ._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
from ._parsing import find_matching_brace_for_args, find_matching_paren_for_args


def directive_matches_outside_alt(prompt: str) -> list[re.Match[str]]:
    """Return directive matches outside alt and code-directive interiors."""
    ignored_regions = [
        *_alt_inner_regions(prompt),
        *_code_directive_inner_ranges(prompt),
    ]

    def is_ignored(pos: int) -> bool:
        return any(start <= pos < end for start, end in ignored_regions)

    return [
        match
        for match in re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE)
        if not is_ignored(match.start())
    ]


def _code_directive_inner_ranges(prompt: str) -> list[tuple[int, int]]:
    """Keep `%proc(...)` / `%if(...)` argument interiors opaque."""
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE):
        name = _DIRECTIVE_ALIASES.get(match.group(1), match.group(1))
        if name not in {"if", "proc"} or match.group(2) is None:
            continue
        paren_end = find_matching_paren_for_args(prompt, match.end() - 1)
        if paren_end is not None:
            ranges.append((match.end(), paren_end))
    return ranges


def _alt_inner_regions(prompt: str) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    for alt_match in _ALT_DIRECTIVE_RE.finditer(prompt):
        open_pos = alt_match.end() - 1
        if prompt[open_pos] == "{":
            close_pos = find_matching_brace_for_args(prompt, open_pos)
        else:
            close_pos = find_matching_paren_for_args(prompt, open_pos)
        if close_pos is not None:
            regions.append((open_pos + 1, close_pos))
    return regions
