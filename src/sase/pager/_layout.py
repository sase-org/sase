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


def _measure_section_heights(
    sections: tuple[PagerSection, ...],
    width: int,
    *,
    label_layer: PagerLabelLayer | None = None,
    pending_prefix: str = "",
    prepared_sections: Mapping[int, Text] | None = None,
) -> tuple[int, ...]:
    """Return each section's wrapped line count at ``width``, no I/O.

    Prepared syntax text only adds *style* over the same characters, so it
    can never change a wrapped row count — it is threaded through here
    purely so a section rendered with labels starts from the styled base
    rather than the plain body.
    """
    console = Console(width=max(width, 1), color_system=None, highlight=False)
    heights = []
    for index, section in enumerate(sections):
        prepared_text = (
            None if prepared_sections is None else prepared_sections.get(index)
        )
        lines = console.render_lines(
            _section_renderable(
                section,
                section_index=index,
                label_layer=label_layer,
                pending_prefix=pending_prefix,
                prepared_text=prepared_text,
            ),
            pad=False,
        )
        heights.append(max(len(lines), 1))
    return tuple(heights)


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
    goto_mark: tuple[int, int] | None = None,
    goto_accent: str | None = None,
) -> ComposedBody:
    """Render *document* at ``width``: gutterized bodies plus transition rules.

    ``prepared_sections`` maps a section index to syntax-styled ``Text`` that
    should stand in for that section's plain body — omitted indices render
    exactly as before. ``goto_mark`` is ``(section_index, line_number)`` for
    the last jump; its gutter number is emphasized with ``goto_accent``.
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
        renderable = _section_renderable(
            section,
            section_index=index,
            label_layer=label_layer,
            pending_prefix=pending_prefix,
            prepared_text=None
            if prepared_sections is None
            else prepared_sections.get(index),
        )
        emphasis_line = (
            goto_mark[1] if goto_mark is not None and goto_mark[0] == index else None
        )
        painted, height, line_rows = _paint_section_body(
            renderable,
            section,
            paint_width=paint_width,
            content_width=content_width,
            digits=digits,
            emphasis_line=emphasis_line,
            accent=goto_accent if emphasis_line is not None else None,
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
    return ComposedBody(
        renderable=Group(*parts),
        section_offsets=offsets,
        total_height=offsets[-1] + heights[-1],
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
    emphasis_line: int | None,
    accent: str | None,
) -> tuple[RenderableType, int, tuple[int, ...]]:
    """Gutterize a ``Text`` body; keep a no-gutter fallback for other renderables."""
    if isinstance(renderable, Text):
        guttered = apply_gutter(
            renderable,
            content_width=content_width,
            number_width=digits,
            emphasis_line=emphasis_line,
            accent=accent,
        )
        return guttered.text, guttered.row_count, guttered.line_rows
    height = _renderable_height(renderable, paint_width)
    return renderable, height, _estimated_line_rows(section.plain_text, paint_width)


def _absolute_line_rows(
    section_offset: int,
    section_index: int,
    relative: tuple[int, ...],
) -> tuple[int, ...]:
    body_start = section_offset + (0 if section_index == 0 else _DIVIDER_LINES)
    return tuple(body_start + row for row in relative)


def _renderable_height(renderable: RenderableType, width: int) -> int:
    console = Console(width=max(width, 1), color_system=None, highlight=False)
    lines = console.render_lines(renderable, pad=False)
    return max(len(lines), 1)


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
    )


def styled_search_base(
    document: PagerDocument,
    *,
    prepared_sections: Mapping[int, Text] | None = None,
    dangling_refs: AbstractSet[object] = frozenset(),
    is_dangling: DanglingPredicate | None = None,
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
    "compose_body",
    "current_section_index",
    "render_section_with_labels",
    "search_corpus",
    "styled_search_base",
]
