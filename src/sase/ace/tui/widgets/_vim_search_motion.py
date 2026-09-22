"""Pure Vim operator + search-motion resolver for the prompt input.

Implements the exclusive ``/{pattern}`` / ``?{pattern}`` motion semantics used
when a NORMAL-mode operator is followed by a search motion (``d/foo``,
``d?foo``, ``dn`` / ``dN``). No Textual or widget imports: the whole
resolution is unit-testable against plain text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.ace.tui.widgets._vim_registers import first_non_blank_col
from sase.ace.tui.widgets._vim_search import (
    SearchDirection,
    SearchSpan,
    find_search_matches,
)
from sase.ace.tui.widgets.vim_search_controller import (
    line_start_offsets,
    offset_to_row_col,
)

SearchOperatorFamily = Literal["destructive", "yank", "transform"]

SEARCH_MOTION_MUTATING_OPERATORS = frozenset({"d", "c", "gu", "gU", "g~", ">", "<"})

_OPERATOR_FAMILIES: dict[str, SearchOperatorFamily] = {
    "d": "destructive",
    "c": "destructive",
    "y": "yank",
    "gu": "transform",
    "gU": "transform",
    "g~": "transform",
    ">": "transform",
    "<": "transform",
    "ys": "transform",
}

_OPERATOR_VERBS: dict[str, str] = {
    "d": "delete",
    "c": "change",
    "y": "yank",
    "gu": "lowercase",
    "gU": "uppercase",
    "g~": "toggle case",
    ">": "indent",
    "<": "dedent",
    "ys": "surround",
}


@dataclass(frozen=True)
class SearchOperatorRequest:
    """An operator awaiting a search motion plus its total count."""

    operator: str
    count: int


@dataclass(frozen=True)
class SearchMotionRange:
    """Resolved exclusive motion range with absolute offsets (end exclusive)."""

    linewise: bool
    start: int
    end: int
    first_row: int
    last_row: int


@dataclass(frozen=True)
class SearchMotionResolution:
    """Pane-local resolution of a search motion from an origin offset."""

    spans: tuple[SearchSpan, ...]
    target_index: int | None
    reachable: int
    opposite: int
    motion_range: SearchMotionRange | None


@dataclass(frozen=True)
class SearchOperatorPreview:
    """Data the text area hands to the search command-line bar."""

    operator: str
    count: int
    direction: SearchDirection
    family: SearchOperatorFamily
    verb: str
    effect: str | None
    miss: str | None
    ordinal: int | None
    total: int


def search_operator_family(op: str) -> SearchOperatorFamily:
    """Return the preview family for operator *op*."""
    return _OPERATOR_FAMILIES.get(op, "transform")


def search_operator_verb(op: str) -> str:
    """Return the human verb for operator *op* (e.g. ``delete`` for ``d``)."""
    return _OPERATOR_VERBS.get(op, op)


def describe_search_motion_effect(op: str, motion_range: SearchMotionRange) -> str:
    """Describe the effect of *op* over *motion_range* for the panel."""
    verb = search_operator_verb(op)
    rows = motion_range.last_row - motion_range.first_row + 1
    if motion_range.linewise or op in {">", "<"}:
        noun = "line" if rows == 1 else "lines"
        return f"{verb} {rows} {noun}"
    char_count = max(0, motion_range.end - motion_range.start)
    if rows <= 1:
        noun = "char" if char_count == 1 else "chars"
        return f"{verb} {char_count:,} {noun}"
    char_noun = "char" if char_count == 1 else "chars"
    line_noun = "line" if rows == 1 else "lines"
    return f"{verb} {char_count:,} {char_noun} · {rows} {line_noun}"


def search_motion_miss_message(
    resolution: SearchMotionResolution,
    direction: SearchDirection,
    count: int,
    query: str,
) -> str:
    """Return the pane-local no-target wording for the panel status.

    The zero-match toast form appends ``: {query}`` at the call site; this
    helper always returns the panel form so both surfaces share one source.
    """
    _ = query
    total = len(resolution.spans)
    if total == 0:
        return "pattern not found"
    if resolution.reachable == 0:
        if direction == "forward":
            base = "no match after cursor"
            if resolution.opposite > 0:
                return f"{base} · {resolution.opposite} before"
            return base
        base = "no match before cursor"
        if resolution.opposite > 0:
            return f"{base} · {resolution.opposite} after"
        return base
    if resolution.reachable < max(1, count):
        side = "after cursor" if direction == "forward" else "before cursor"
        noun = "match" if resolution.reachable == 1 else "matches"
        return f"only {resolution.reachable} {noun} {side}"
    return ""


def _exclusive_motion_range(text: str, start: int, end: int) -> SearchMotionRange:
    """Apply Vim's exclusive adjustment to raw range [*start*, *end*)."""
    length = len(text)
    start = max(0, min(start, length))
    end = max(0, min(end, length))
    if end < start:
        start, end = end, start
    line_starts = line_start_offsets(text)
    lines = text.split("\n")

    def _row(offset: int) -> int:
        row, _col = offset_to_row_col(line_starts, offset)
        return row

    if end <= start:
        row = _row(start)
        return SearchMotionRange(
            linewise=False, start=start, end=end, first_row=row, last_row=row
        )

    sr, sc = offset_to_row_col(line_starts, start)
    er, ec = offset_to_row_col(line_starts, end)
    if not (ec == 0 and er > sr):
        first_row = sr
        last_row = _row(end - 1)
        return SearchMotionRange(
            linewise=False,
            start=start,
            end=end,
            first_row=first_row,
            last_row=last_row,
        )

    line_sr = lines[sr] if 0 <= sr < len(lines) else ""
    if not line_sr.strip():
        is_linewise_start = True
    else:
        is_linewise_start = sc <= first_non_blank_col(line_sr)

    if is_linewise_start:
        linewise_start = line_starts[sr] if 0 <= sr < len(line_starts) else start
        linewise_end = line_starts[er] if 0 <= er < len(line_starts) else end
        return SearchMotionRange(
            linewise=True,
            start=linewise_start,
            end=linewise_end,
            first_row=sr,
            last_row=er - 1,
        )

    prev_row = er - 1
    prev_line = lines[prev_row] if 0 <= prev_row < len(lines) else ""
    prev_start = line_starts[prev_row] if 0 <= prev_row < len(line_starts) else start
    adjusted_end = prev_start + len(prev_line)
    if adjusted_end <= start:
        first_row = sr
        last_row = _row(end - 1)
        return SearchMotionRange(
            linewise=False,
            start=start,
            end=end,
            first_row=first_row,
            last_row=last_row,
        )
    return SearchMotionRange(
        linewise=False,
        start=start,
        end=adjusted_end,
        first_row=sr,
        last_row=prev_row,
    )


def resolve_search_motion(
    text: str,
    origin: int,
    query: str,
    direction: SearchDirection,
    *,
    count: int = 1,
    whole_word: bool = False,
    smartcase: bool = True,
) -> SearchMotionResolution:
    """Resolve an exclusive search motion from *origin* for *query*."""
    wanted = max(1, count)
    spans = find_search_matches(text, query, whole_word=whole_word, smartcase=smartcase)
    origin = max(0, min(origin, len(text)))
    if direction == "forward":
        candidates = [index for index, (s, _e) in enumerate(spans) if s > origin]
        opposite = sum(1 for s, _e in spans if s < origin)
    else:
        candidates = [
            index for index in range(len(spans) - 1, -1, -1) if spans[index][0] < origin
        ]
        opposite = sum(1 for s, _e in spans if s > origin)
    reachable = len(candidates)
    if reachable < wanted:
        return SearchMotionResolution(
            spans=spans,
            target_index=None,
            reachable=reachable,
            opposite=opposite,
            motion_range=None,
        )
    target_index = candidates[wanted - 1]
    match_start, _match_end = spans[target_index]
    if direction == "forward":
        raw_start, raw_end = origin, match_start
    else:
        raw_start, raw_end = match_start, origin
    motion_range = _exclusive_motion_range(text, raw_start, raw_end)
    return SearchMotionResolution(
        spans=spans,
        target_index=target_index,
        reachable=reachable,
        opposite=opposite,
        motion_range=motion_range,
    )


__all__ = [
    "SEARCH_MOTION_MUTATING_OPERATORS",
    "SearchMotionRange",
    "SearchMotionResolution",
    "SearchOperatorPreview",
    "SearchOperatorRequest",
    "describe_search_motion_effect",
    "resolve_search_motion",
    "search_motion_miss_message",
    "search_operator_family",
    "search_operator_verb",
]
