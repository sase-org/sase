"""Composition of fenced, disabled, and inline prompt literal zones."""

from __future__ import annotations

from bisect import bisect_right
import re

from ._directive_types import (
    _DEPRECATED_DIRECTIVES,
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
    _KNOWN_DIRECTIVES,
)
from ._disabled_regions import disabled_region_ranges
from ._fenced_blocks import fenced_block_ranges
from ._inline_code import inline_code_spans
from ._parsing_args import find_matching_paren_for_args
from ._parsing_references import (
    XPROMPT_REFERENCE_PATTERN,
    xprompt_reference_from_match,
)

_DIRECTIVE_RE = re.compile(_DIRECTIVE_PATTERN, re.MULTILINE)


def inline_literal_ranges(text: str) -> list[tuple[int, int]]:
    """Return inline-code ranges after applying launch-parser precedence."""
    if "`" not in text:
        return []

    fenced = fenced_block_ranges(text)
    return _inline_literal_ranges(text, fenced)


def _inline_literal_ranges(
    text: str,
    fenced: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    disabled = disabled_region_ranges(text)
    masks = [*fenced, *disabled]
    protected = _merge_ranges(masks)
    for match in XPROMPT_REFERENCE_PATTERN.finditer(text):
        if _position_in_ranges(match.start(), protected):
            continue
        reference = xprompt_reference_from_match(text, match)
        masks.append((reference.start, reference.end))
    for match in _DIRECTIVE_RE.finditer(text):
        if _position_in_ranges(match.start(), protected):
            continue
        raw_name = match.group(1)
        name = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
        if name not in _KNOWN_DIRECTIVES and name not in _DEPRECATED_DIRECTIVES:
            continue
        end = _directive_end(text, match)
        masks.append((match.start(), end))

    return inline_code_spans(text, masked_ranges=masks)


def code_literal_ranges(text: str) -> list[tuple[int, int]]:
    """Return fenced and inline code ranges, excluding disabled regions."""
    fenced = fenced_block_ranges(text)
    if "`" not in text:
        return fenced
    return sorted([*fenced, *_inline_literal_ranges(text, fenced)])


def literal_zone_ranges(text: str) -> list[tuple[int, int]]:
    """Return all launch-inert ranges: fenced, disabled, and inline code."""
    return _merge_ranges([*code_literal_ranges(text), *disabled_region_ranges(text)])


def _directive_end(text: str, match: re.Match[str]) -> int:
    if match.group(2) is None:
        return match.end()
    paren_end = find_matching_paren_for_args(text, match.end() - 1)
    return match.end() if paren_end is None else paren_end + 1


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _position_in_ranges(position: int, ranges: list[tuple[int, int]]) -> bool:
    candidate = bisect_right(ranges, (position, 1 << 63)) - 1
    return candidate >= 0 and position < ranges[candidate][1]


__all__ = [
    "code_literal_ranges",
    "inline_literal_ranges",
    "literal_zone_ranges",
]
