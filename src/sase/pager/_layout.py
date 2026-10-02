"""Width-cached body composition for the pager's virtualized content.

The pager renders every section into one Rich renderable painted by a single
``Static`` (Textual's compositor virtualizes which rows actually draw — see
``AgentFilePanel``/``AgentPromptPanel`` for the same "one big renderable, no
per-line widgets" shape). This module only computes *what* to paint and
*where* each section starts, at a given width; callers own the caching (the
Textual layer rebuilds only when the body's actual width changes, per
``tui_perf`` rule 8).
"""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.text import Text

from sase.pager._chrome import section_rule
from sase.pager._gutter import (
    apply_gutter,
    gutter_width,
    logical_line_count,
    number_width,
)
from sase.pager._labels import (
    DanglingPredicate,
    PagerLabelLayer,
    render_section_with_labels,
    row_for_character_offset,
    style_target_accents,
)
from sase.pager._line_mark import LineMark
from sase.pager.document import PagerDocument, PagerSection

_DIVIDER_LINES = 1


@dataclass(frozen=True, slots=True)
class ComposedBody:
    """One document rendered at a fixed width."""

    renderable: RenderableType
    section_offsets: tuple[int, ...]
    total_height: int
    section_line_counts: tuple[int, ...] = ()
    section_line_rows: tuple[tuple[int, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class ReadingAnchor:
    """A width-independent reading position: section, logical line, wrap offset.

    ``line`` is 1-based. ``row_offset`` counts wrapped continuation rows below
    the line's first visual row.
    """

    section_index: int
    line: int
    row_offset: int


def _section_body_start(offsets: tuple[int, ...], section_index: int) -> int:
    """Return the first body row of *section_index* (past its divider rule)."""
    return offsets[section_index] + (1 if section_index > 0 else 0)


def _section_body_end(body: ComposedBody, section_index: int) -> int:
    """Return the exclusive end row of *section_index*'s body rows."""
    if section_index + 1 < len(body.section_offsets):
        return body.section_offsets[section_index + 1]
    return body.total_height


def reading_anchor_at_row(body: ComposedBody, row: int) -> ReadingAnchor:
    """Capture the logical line at absolute *row* of *body*.

    A row sitting on a section divider rule anchors to that section's first
    line, so a width change never strands the viewport on a rule row that
    may move.
    """
    section_count = len(body.section_line_rows)
    if section_count == 0 or body.total_height <= 0:
        return ReadingAnchor(section_index=0, line=1, row_offset=0)
    clamped = max(0, min(row, body.total_height - 1))
    for index in range(1, len(body.section_offsets)):
        if clamped == body.section_offsets[index]:
            return ReadingAnchor(section_index=index, line=1, row_offset=0)
    section_index = 0
    for index, _offset in enumerate(body.section_offsets):
        if _section_body_start(body.section_offsets, index) <= clamped:
            section_index = index
        else:
            break
    rows = body.section_line_rows[section_index]
    if not rows:
        return ReadingAnchor(section_index=section_index, line=1, row_offset=0)
    line_pos = 0
    for pos, start in enumerate(rows):
        if start <= clamped:
            line_pos = pos
        else:
            break
    return ReadingAnchor(
        section_index=section_index,
        line=line_pos + 1,
        row_offset=clamped - rows[line_pos],
    )


def row_for_reading_anchor(body: ComposedBody, anchor: ReadingAnchor) -> int:
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


def _section_row_offsets(heights: tuple[int, ...]) -> tuple[int, ...]:
    """Return the row where each section's own rule (or the top) sits.

    Section 0 has no leading rule — the chrome band already identifies the
    document — so its offset is row 0. Every later section's offset is the
    row its transition rule occupies, which is exactly the row
    ``ctrl+n``/``ctrl+p`` scroll to (design doc section D5).
    """
    if not heights:
        return (0,)
    offsets = [0]
    row = heights[0]
    for height in heights[1:]:
        offsets.append(row)
        row += _DIVIDER_LINES + height
    return tuple(offsets)


def compose_body(
    document: PagerDocument,
    width: int,
    *,
    label_layer: PagerLabelLayer | None = None,
    pending_prefix: str = "",
    prepared_sections: Mapping[int, Text] | None = None,
    line_mark: LineMark | None = None,
    goto_accent: str | None = None,
    change_marks: Mapping[int, Mapping[int, str]] | None = None,
    removal_anchors: Mapping[int, set[int]] | None = None,
    rail_styles: Mapping[int, str] | None = None,
    history_styles: Any | None = None,
    surface: str | None = None,
) -> ComposedBody:
    """Render *document* at ``width``: gutterized bodies plus transition rules.

    ``prepared_sections`` maps a section index to syntax-styled ``Text`` that
    should stand in for that section's plain body — omitted indices render
    exactly as before. ``line_mark`` is the last jump or link landing; its
    inclusive range paints an accent rail with ``goto_accent``.
    ``change_marks``/``removal_anchors`` carry read-view history marks per
    section index; a goto rail wins when both coincide. ``rail_styles``
    paints the plain gutter separator of each section index — the
    past-accent rail for sections pinned in the past — under change
    marks but over nothing else.
    """
    sections = document.sections
    if not sections:
        return ComposedBody(renderable=Group(), section_offsets=(0,), total_height=0)

    paint_width = max(width, 1)
    max_count = max(
        (logical_line_count(section.plain_text) for section in sections),
        default=0,
    )
    digits = number_width(max_count)
    content_width = max(paint_width - gutter_width(max_count), 1)
    total = len(sections)

    parts: list[RenderableType] = []
    heights: list[int] = []
    relative_line_rows: list[tuple[int, ...]] = []
    for index, section in enumerate(sections):
        if index > 0:
            parts.append(
                section_rule(section, index=index + 1, total=total, width=paint_width)
            )
        resolved_surface = surface
        if resolved_surface is None and history_styles is not None:
            try:
                candidate = getattr(history_styles, "background", None)
                if isinstance(candidate, str) and candidate:
                    resolved_surface = candidate
            except Exception:
                resolved_surface = None
        renderable = _section_renderable(
            section,
            section_index=index,
            label_layer=label_layer,
            pending_prefix=pending_prefix,
            prepared_text=None
            if prepared_sections is None
            else prepared_sections.get(index),
            surface=resolved_surface,
        )
        emphasis_range = (
            line_mark.emphasis_range
            if line_mark is not None and line_mark.section_index == index
            else None
        )
        section_marks = None if change_marks is None else change_marks.get(index)
        section_anchors = (
            None if removal_anchors is None else removal_anchors.get(index)
        )
        section_rail = None if rail_styles is None else rail_styles.get(index)
        painted, height, line_rows = _paint_section_body(
            renderable,
            section,
            paint_width=paint_width,
            content_width=content_width,
            digits=digits,
            emphasis_range=emphasis_range,
            accent=goto_accent if emphasis_range is not None else None,
            change_marks=dict(section_marks) if section_marks is not None else None,
            removal_anchors=set(section_anchors)
            if section_anchors is not None
            else None,
            rail_style=section_rail,
            history_styles=history_styles,
        )
        parts.append(painted)
        heights.append(height)
        relative_line_rows.append(line_rows)

    height_tuple = tuple(heights)
    offsets = _section_row_offsets(height_tuple)
    absolute_line_rows = tuple(
        _absolute_line_rows(offsets[index], index, rows)
        for index, rows in enumerate(relative_line_rows)
    )
    divider_rows = _DIVIDER_LINES * max(len(sections) - 1, 0)
    return ComposedBody(
        renderable=Group(*parts),
        section_offsets=offsets,
        total_height=sum(heights) + divider_rows,
        section_line_counts=tuple(len(rows) for rows in relative_line_rows),
        section_line_rows=absolute_line_rows,
    )


def _paint_section_body(
    renderable: RenderableType,
    section: PagerSection,
    *,
    paint_width: int,
    content_width: int,
    digits: int,
    emphasis_range: tuple[int, int] | None,
    accent: str | None,
    change_marks: dict[int, str] | None = None,
    removal_anchors: set[int] | None = None,
    rail_style: str | None = None,
    history_styles: Any | None = None,
) -> tuple[RenderableType, int, tuple[int, ...]]:
    """Gutterize a ``Text`` body; keep a no-gutter fallback for other renderables."""
    if isinstance(renderable, Text):
        guttered = apply_gutter(
            renderable,
            content_width=content_width,
            number_width=digits,
            emphasis_range=emphasis_range,
            accent=accent,
            change_marks=change_marks,
            removal_anchors=removal_anchors,
            rail_style=rail_style,
            history_styles=history_styles,
        )
        return guttered.text, guttered.row_count, guttered.line_rows
    console = Console(width=max(paint_width, 1), color_system=None, highlight=False)
    height = max(len(console.render_lines(renderable, pad=False)), 1)
    return renderable, height, _estimated_line_rows(section.plain_text, paint_width)


def _absolute_line_rows(
    section_offset: int,
    section_index: int,
    relative: tuple[int, ...],
) -> tuple[int, ...]:
    body_start = section_offset + (0 if section_index == 0 else _DIVIDER_LINES)
    return tuple(body_start + row for row in relative)


def _estimated_line_rows(text: str, width: int) -> tuple[int, ...]:
    count = logical_line_count(text)
    if count == 0:
        return ()
    rows: list[int] = []
    cursor = 0
    for _index in range(count):
        rows.append(row_for_character_offset(text, cursor, width))
        newline = text.find("\n", cursor)
        cursor = len(text) if newline < 0 else newline + 1
    return tuple(rows)


def current_section_index(offsets: tuple[int, ...], scroll_y: int) -> int:
    """Return the index of the section whose rule is at or above ``scroll_y``."""
    index = 0
    for candidate, offset in enumerate(offsets):
        if offset <= scroll_y:
            index = candidate
        else:
            break
    return index


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


def _section_renderable(
    section: PagerSection,
    *,
    section_index: int,
    label_layer: PagerLabelLayer | None,
    pending_prefix: str,
    prepared_text: Text | None = None,
    surface: str | None = None,
) -> RenderableType:
    if label_layer is None:
        if prepared_text is not None:
            return prepared_text.copy()
        return section.body_renderable
    labels = label_layer.labels_by_section[section_index]
    if not labels:
        if prepared_text is not None:
            return prepared_text.copy()
        return section.body_renderable
    return render_section_with_labels(
        section,
        labels,
        pending_prefix=pending_prefix,
        source=prepared_text,
        surface=surface,
    )


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
    "ComposedBody",
    "ReadingAnchor",
    "compose_body",
    "current_section_index",
    "reading_anchor_at_row",
    "render_section_with_labels",
    "row_for_reading_anchor",
    "search_corpus",
    "styled_search_base",
]
