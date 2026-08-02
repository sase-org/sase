"""Frontend-agnostic xprompt syntax highlight spans."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from typing import Literal, cast

from sase.artifact_refs import scan_artifact_refs

from . import alt_inspect, jinja_inspect, xprompt_inspect
from ._fenced_blocks import fenced_block_details
from ._literal_zones import inline_literal_ranges
from .placeholder_completion import PlaceholderPosition, placeholder_spans

MAX_HIGHLIGHT_BYTES = 80_000
MAX_HIGHLIGHT_LINES = 1_200

XPromptHighlightRole = Literal[
    "xprompt.invocation",
    "xprompt.invocation_arg",
    "xprompt.directive",
    "xprompt.directive_arg",
    "xprompt.separator",
    "xprompt.skill",
    "jinja.delimiter",
    "jinja.statement",
    "jinja.variable",
    "jinja.comment",
    "jinja.filter",
    "jinja.keyword",
    "jinja.operator",
    "alt.delimiter",
    "alt.separator",
    "alt.branch_name",
    "alt.error",
    "placeholder",
    "artifact_ref",
    "code.fence",
    "code.inline",
]


@dataclass(frozen=True, slots=True)
class HighlightSpan:
    """A half-open character range carrying one semantic highlight role."""

    start: int
    end: int
    role: XPromptHighlightRole


@dataclass(frozen=True, slots=True)
class _Candidate:
    candidate_id: int
    start: int
    end: int
    role: XPromptHighlightRole


# Lower numbers win. Keeping every role explicit makes precedence additions
# deliberate and gives same-family overlaps a deterministic result.
_ROLE_PRECEDENCE: dict[XPromptHighlightRole, int] = {
    "code.fence": 0,
    "code.inline": 1,
    "xprompt.invocation": 10,
    "xprompt.invocation_arg": 11,
    "xprompt.directive": 12,
    "xprompt.directive_arg": 13,
    "xprompt.separator": 14,
    "xprompt.skill": 15,
    "alt.delimiter": 20,
    "alt.separator": 21,
    "alt.branch_name": 22,
    "alt.error": 23,
    "jinja.delimiter": 30,
    "jinja.statement": 31,
    "jinja.variable": 32,
    "jinja.comment": 33,
    "jinja.filter": 34,
    "jinja.keyword": 35,
    "jinja.operator": 36,
    "placeholder": 40,
    "artifact_ref": 50,
}


def highlight_spans(
    text: str,
    *,
    known_skills: frozenset[str] = frozenset(),
    include_artifact_refs: bool = True,
) -> list[HighlightSpan]:
    """Return a flat, ordered, non-overlapping role partition of *text*."""
    if (
        len(text.encode("utf-8")) > MAX_HIGHLIGHT_BYTES
        or text.count("\n") > MAX_HIGHLIGHT_LINES
    ):
        return []

    collected: list[HighlightSpan] = []

    try:
        xprompt_tokens = xprompt_inspect.tokenize(text, known_skills=known_skills)
    except Exception:
        xprompt_tokens = []
    collected.extend(
        HighlightSpan(
            span.start,
            span.end,
            cast(XPromptHighlightRole, f"xprompt.{span.kind}"),
        )
        for span in xprompt_tokens
    )

    try:
        jinja_tokens = jinja_inspect.tokenize(text)
    except Exception:
        jinja_tokens = []
    collected.extend(
        HighlightSpan(
            span.start,
            span.end,
            cast(XPromptHighlightRole, f"jinja.{span.kind}"),
        )
        for span in jinja_tokens
    )

    try:
        alt_tokens = alt_inspect.tokenize(text)
    except Exception:
        alt_tokens = []
    collected.extend(
        HighlightSpan(
            span.start,
            span.end,
            cast(XPromptHighlightRole, f"alt.{span.kind}"),
        )
        for span in alt_tokens
    )

    try:
        placeholders = placeholder_spans(text)
    except Exception:
        placeholders = ()
    for span in placeholders:
        if not span.raw:
            continue
        start = _position_to_offset(text, span.range.start)
        end = _position_to_offset(text, span.range.end)
        if start is not None and end is not None:
            collected.append(HighlightSpan(start, end, "placeholder"))

    if include_artifact_refs:
        try:
            artifact_candidates = scan_artifact_refs(text)
        except Exception:
            artifact_candidates = ()
        byte_offsets = _byte_to_character_offsets(text)
        for candidate in artifact_candidates:
            start = byte_offsets.get(candidate.candidate_span.start)
            end = byte_offsets.get(candidate.candidate_span.end)
            if start is not None and end is not None:
                collected.append(HighlightSpan(start, end, "artifact_ref"))

    try:
        fenced_blocks = fenced_block_details(text)
    except Exception:
        fenced_blocks = []
    collected.extend(
        HighlightSpan(block.block_range[0], block.block_range[1], "code.fence")
        for block in fenced_blocks
    )

    try:
        inline_ranges = inline_literal_ranges(text)
    except Exception:
        inline_ranges = []
    collected.extend(
        HighlightSpan(start, end, "code.inline") for start, end in inline_ranges
    )

    return _flatten_spans(collected, text_length=len(text))


def _flatten_spans(
    spans: list[HighlightSpan],
    *,
    text_length: int,
) -> list[HighlightSpan]:
    candidates: list[_Candidate] = []
    for candidate_id, span in enumerate(spans):
        start = max(0, min(span.start, text_length))
        end = max(0, min(span.end, text_length))
        if end <= start:
            continue
        candidates.append(_Candidate(candidate_id, start, end, span.role))
    if not candidates:
        return []

    starts: dict[int, list[_Candidate]] = {}
    ends: dict[int, list[int]] = {}
    for candidate in candidates:
        starts.setdefault(candidate.start, []).append(candidate)
        ends.setdefault(candidate.end, []).append(candidate.candidate_id)
    boundaries = sorted({*starts, *ends})
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    active: set[int] = set()
    heap: list[tuple[int, int]] = []
    pieces: list[tuple[_Candidate, int, int]] = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        active.difference_update(ends.get(start, ()))
        for candidate in starts.get(start, ()):
            active.add(candidate.candidate_id)
            heapq.heappush(
                heap,
                (_ROLE_PRECEDENCE[candidate.role], candidate.candidate_id),
            )
        while heap and heap[0][1] not in active:
            heapq.heappop(heap)
        if not heap:
            continue
        winner = by_id[heap[0][1]]
        if pieces and pieces[-1][0].candidate_id == winner.candidate_id:
            pieces[-1] = (winner, pieces[-1][1], end)
        else:
            pieces.append((winner, start, end))

    return [
        HighlightSpan(start=start, end=end, role=candidate.role)
        for candidate, start, end in pieces
    ]


def _position_to_offset(text: str, position: PlaceholderPosition) -> int | None:
    """Convert a zero-based LSP UTF-16 position to a character offset."""
    if position.line < 0 or position.character < 0:
        return None
    line_start = 0
    for _ in range(position.line):
        newline = text.find("\n", line_start)
        if newline == -1:
            return None
        line_start = newline + 1

    newline = text.find("\n", line_start)
    line_end = len(text) if newline == -1 else newline
    utf16_offset = 0
    for offset in range(line_start, line_end):
        if utf16_offset == position.character:
            return offset
        utf16_offset += 2 if ord(text[offset]) > 0xFFFF else 1
        if utf16_offset > position.character:
            return None
    return line_end if utf16_offset == position.character else None


def _byte_to_character_offsets(text: str) -> dict[int, int]:
    offsets = {0: 0}
    byte_offset = 0
    for character_offset, char in enumerate(text, start=1):
        byte_offset += len(char.encode("utf-8"))
        offsets[byte_offset] = character_offset
    return offsets


__all__ = [
    "MAX_HIGHLIGHT_BYTES",
    "MAX_HIGHLIGHT_LINES",
    "HighlightSpan",
    "XPromptHighlightRole",
    "highlight_spans",
]
