"""Reading anchors, section indexes, and search text for the pager body.

The width-cached composition that used to live here now lives in
:mod:`sase.pager._body_layout` (integer layout) and
:mod:`sase.pager._body_rows` (per-row painting). This module keeps the
width-independent helpers both paths share: reading anchors, the current
section index, and the unwrapped search corpus and its styled base.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Protocol

from rich.text import Text

from sase.pager._labels import (
    DanglingPredicate,
    PagerLabelLayer,
    style_target_accents,
)
from sase.pager.document import PagerDocument


@dataclass(frozen=True, slots=True)
class ReadingAnchor:
    """A width-independent reading position: section, logical line, wrap offset.

    ``line`` is 1-based. ``row_offset`` counts wrapped continuation rows below
    the line's first visual row.
    """

    section_index: int
    line: int
    row_offset: int


class _AnchorBody(Protocol):
    """The integer maps anchor lookup reads off a composed or virtual body."""

    section_offsets: tuple[int, ...]
    total_height: int
    section_line_rows: tuple[tuple[int, ...], ...]


def _section_body_start(offsets: tuple[int, ...], section_index: int) -> int:
    """Return the first body row of *section_index* (past its divider rule)."""
    return offsets[section_index] + (1 if section_index > 0 else 0)


def _section_body_end(body: _AnchorBody, section_index: int) -> int:
    """Return the exclusive end row of *section_index*'s body rows."""
    if section_index + 1 < len(body.section_offsets):
        return body.section_offsets[section_index + 1]
    return body.total_height


def reading_anchor_at_row(body: _AnchorBody, row: int) -> ReadingAnchor:
    """Capture the logical line at absolute *row* of *body*.

    A row sitting on a section divider rule anchors to that section's first
    line, so a width change never strands the viewport on a rule row that
    may move.
    """
    section_count = len(body.section_line_rows)
    if section_count == 0 or body.total_height <= 0:
        return ReadingAnchor(section_index=0, line=1, row_offset=0)
    clamped = max(0, min(row, body.total_height - 1))
    rule = bisect_left(body.section_offsets, clamped, 1)
    if rule < len(body.section_offsets) and body.section_offsets[rule] == clamped:
        return ReadingAnchor(section_index=rule, line=1, row_offset=0)
    body_starts = [
        _section_body_start(body.section_offsets, index)
        for index in range(len(body.section_offsets))
    ]
    section_index = max(0, bisect_right(body_starts, clamped) - 1)
    rows = body.section_line_rows[section_index]
    if not rows:
        return ReadingAnchor(section_index=section_index, line=1, row_offset=0)
    line_pos = max(0, bisect_right(rows, clamped) - 1)
    return ReadingAnchor(
        section_index=section_index,
        line=line_pos + 1,
        row_offset=clamped - rows[line_pos],
    )


def row_for_reading_anchor(body: _AnchorBody, anchor: ReadingAnchor) -> int:
    """Return the absolute row of *anchor* in *body*, clamping the offset.

    The wrapped height of a logical line depends on width, so a
    continuation-row offset recorded at one width is clamped into the same
    line's wrapped rows at the new width.
    """
    section_count = len(body.section_line_rows)
    if section_count == 0 or body.total_height <= 0:
        return 0
    section_index = max(0, min(anchor.section_index, section_count - 1))
    rows = body.section_line_rows[section_index]
    if not rows:
        return _section_body_start(body.section_offsets, section_index)
    line = max(1, min(anchor.line, len(rows)))
    start = rows[line - 1]
    if line < len(rows):
        end = rows[line]
    else:
        end = _section_body_end(body, section_index)
    wrapped = max(end - start, 1)
    offset = max(0, min(anchor.row_offset, wrapped - 1))
    return start + offset


def current_section_index(offsets: tuple[int, ...], scroll_y: int) -> int:
    """Return the index of the section whose rule is at or above ``scroll_y``."""
    return max(0, bisect_right(offsets, scroll_y) - 1)


def search_corpus(document: PagerDocument) -> str:
    """Return one logical-line-aligned corpus for the re-hosted vim search.

    Search renders unwrapped (design doc section D9's prior art always
    disables wrapping for the overlay), so a logical line here is exactly
    one visible row — unlike the wrapped body used outside search, whose
    row count depends on width.
    """
    sections = document.sections
    if not sections:
        return ""
    parts: list[str] = []
    total = len(sections)
    for index, section in enumerate(sections):
        if index > 0:
            parts.append(f"── {index + 1}/{total} · {section.title} ──\n")
        text = section.plain_text
        parts.append(text if text.endswith("\n") else f"{text}\n")
    return "".join(parts)


def styled_search_base(
    document: PagerDocument,
    *,
    prepared_sections: Mapping[int, Text] | None = None,
    dangling_refs: AbstractSet[object] = frozenset(),
    is_dangling: DanglingPredicate | None = None,
    surface: str | None = None,
) -> Text:
    """Build one styled ``Text`` matching ``search_corpus``'s exact text.

    Prepared syntax text stands in for a section's plain body where
    available, and link target spans are stylized with their marker accent
    without inserting capsule characters — search matches offsets against
    the unmodified corpus, so the plain text here must equal
    ``search_corpus(document)`` exactly.
    """
    sections = document.sections
    if not sections:
        return Text("")
    parts: list[Text] = []
    total = len(sections)
    for index, section in enumerate(sections):
        if index > 0:
            parts.append(Text(f"── {index + 1}/{total} · {section.title} ──\n"))
        base = prepared_sections.get(index) if prepared_sections is not None else None
        text = base.copy() if base is not None else section.body_text
        text = style_target_accents(
            text,
            section,
            index,
            document.origin,
            dangling_refs=dangling_refs,
            is_dangling=is_dangling,
            surface=surface,
        )
        if not text.plain.endswith("\n"):
            text.append("\n")
        parts.append(text)
    result = Text()
    for part in parts:
        result.append_text(part)
    return result


__all__ = [
    "ReadingAnchor",
    "current_section_index",
    "reading_anchor_at_row",
    "row_for_reading_anchor",
    "search_corpus",
    "styled_search_base",
]
