"""Per-row rendering for the virtual pager body.

Textual-free. A :class:`BodyRenderer` binds a
:class:`BodyLayout <sase.pager._body_layout.BodyLayout>` to one
:class:`BodyPaintState` (one paint epoch) and paints any absolute row on
demand. Building the renderer stages each section's labeled styled text
once per epoch; every :meth:`render_row` after that costs O(its line),
independent of document size.

``render_row`` never raises: a row that fails to render paints an empty
row instead, so one corrupt line cannot take down the viewport.
"""

from __future__ import annotations

from array import array
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rich.text import Text

from sase.pager._body_layout import (
    BodyLayout,
    BodySectionLayout,
    effective_section_source,
)
from sase.pager._body_lines import (
    SpanIndex,
    build_span_index,
    logical_line_end,
    logical_line_starts,
    make_wrap_console,
    slice_styled_line,
    wrap_line_pieces,
)
from sase.pager._gutter import gutter_mark_styles, gutter_row, removal_anchor_row
from sase.pager._labels import PagerLabelLayer, render_section_with_labels
from sase.pager._line_mark import LineMark
from sase.pager.document import PagerSection


@dataclass(frozen=True, slots=True)
class BodyPaintState:
    """Everything that repaints rows without relaying out the document."""

    label_layer: PagerLabelLayer | None = None
    pending_prefix: str = ""
    prepared_sections: Mapping[int, Text] | None = None
    line_mark: LineMark | None = None
    goto_accent: str | None = None
    change_marks: Mapping[int, Mapping[int, str]] | None = None
    rail_styles: Mapping[int, str] | None = None
    history_styles: Any | None = None
    surface: str | None = None


@dataclass(frozen=True, slots=True)
class _SectionPaint:
    labeled: Text | None
    index: SpanIndex | None
    starts: array
    emphasis: tuple[int, int] | None
    accent: str | None
    marks: Mapping[int, str]
    rail_style: str | None


def _paint_labeled_text(
    section: PagerSection,
    labels: tuple[Any, ...],
    paint: BodyPaintState,
    prepared: Text | None,
) -> Text:
    source = effective_section_source(section, prepared)
    if not labels:
        if source is not None:
            return source.copy()
        return section.body_text
    return render_section_with_labels(
        section,
        labels,
        pending_prefix=paint.pending_prefix,
        source=source,
        surface=paint.surface,
    )


class BodyRenderer:
    """Paint rows of one layout under one paint epoch.

    ``rows_rendered`` counts painted rows and ``lines_materialized``
    counts styled lines sliced for them: painting one body row
    materializes exactly one line, which is how the scale tests prove a
    row costs O(its line) on a 100k-line document.
    """

    def __init__(self, layout: BodyLayout, paint: BodyPaintState) -> None:
        self._layout = layout
        self._paint = paint
        self.rows_rendered = 0
        self.lines_materialized = 0
        self._console = make_wrap_console(layout.content_width)
        self._mark_styles = gutter_mark_styles(paint.history_styles)
        sections = layout.bound_sections
        staged: list[_SectionPaint] = []
        for index, state in enumerate(layout.section_states):
            staged.append(self._stage_section(index, state, sections[index]))
        self._staged = tuple(staged)

    def _stage_section(
        self,
        index: int,
        state: BodySectionLayout,
        section: PagerSection,
    ) -> _SectionPaint:
        paint = self._paint
        mark = paint.line_mark
        emphasis = None
        accent = None
        if mark is not None and mark.section_index == index:
            lo, hi = mark.emphasis_range
            if lo > hi:
                lo, hi = hi, lo
            emphasis = (lo, hi)
            accent = paint.goto_accent
        marks: Mapping[int, str] = (
            paint.change_marks.get(index, {}) if paint.change_marks is not None else {}
        )
        rail_style = paint.rail_styles.get(index) if paint.rail_styles else None
        if state.kind != "text":
            return _SectionPaint(
                labeled=None,
                index=None,
                starts=array("Q"),
                emphasis=emphasis,
                accent=accent,
                marks=marks,
                rail_style=rail_style,
            )
        labels = (
            paint.label_layer.labels_by_section[index]
            if paint.label_layer is not None
            else ()
        )
        prepared = (
            paint.prepared_sections.get(index)
            if paint.prepared_sections is not None
            else None
        )
        labeled = _paint_labeled_text(section, tuple(labels), paint, prepared)
        return _SectionPaint(
            labeled=labeled,
            index=build_span_index(labeled),
            starts=logical_line_starts(labeled.plain),
            emphasis=emphasis,
            accent=accent,
            marks=marks,
            rail_style=rail_style,
        )

    def render_row(self, row: int) -> Text:
        """Return the row's Rich text, identical to the composer's row."""
        try:
            rendered = self._render_row(row)
        except Exception:
            return Text("")
        self.rows_rendered += 1
        return rendered

    def _render_row(self, row: int) -> Text:
        layout = self._layout
        location = layout.locate(row)
        states = layout.section_states
        if location.section_index >= len(states):
            return Text("")
        state = states[location.section_index]
        paint = self._staged[location.section_index]
        if location.kind == "rule":
            if state.rule is None:
                return Text("")
            return state.rule.copy()
        if location.kind == "anchor":
            return removal_anchor_row(layout.digits, self._mark_styles[2])
        if location.kind == "custom":
            if not state.prerendered:
                return Text("")
            slot = max(0, min(location.wrap_index, len(state.prerendered) - 1))
            return state.prerendered[slot].copy()
        if location.kind != "line" or paint.labeled is None or paint.index is None:
            return self._empty_body_row(layout)
        return self._render_line_row(layout, state, paint, location)

    def _render_line_row(
        self,
        layout: BodyLayout,
        state: BodySectionLayout,
        paint: _SectionPaint,
        location: Any,
    ) -> Text:
        labeled = paint.labeled
        assert labeled is not None and paint.index is not None
        starts = paint.starts
        line = location.line
        if line < 1 or line > len(starts):
            return Text("")
        start = starts[line - 1]
        end = logical_line_end(starts, line - 1, labeled.plain)
        line_text = slice_styled_line(labeled, start, end, index=paint.index)
        self.lines_materialized += 1
        # Always wrap: Rich expands tabs during wrapping even when the line
        # fits on one row, so skipping it would desync tabbed lines.
        pieces = wrap_line_pieces(line_text, layout.content_width, self._console)
        piece = pieces[min(location.wrap_index, len(pieces) - 1)]
        in_range = (
            paint.emphasis is not None
            and paint.emphasis[0] <= line <= paint.emphasis[1]
        )
        number = line if location.wrap_index == 0 else None
        change_kind = paint.marks.get(line) if location.wrap_index == 0 else None
        return gutter_row(
            piece,
            number=number,
            number_width=layout.digits,
            rail=in_range,
            emphasize=in_range and number is not None,
            accent=paint.accent,
            change_kind=change_kind if isinstance(change_kind, str) else None,
            mark_styles=self._mark_styles,
            rail_style=paint.rail_style,
        )

    def _empty_body_row(self, layout: BodyLayout) -> Text:
        paint = self._paint
        rail_style = paint.rail_styles.get(0) if paint.rail_styles else None
        return gutter_row(
            Text(),
            number=None,
            number_width=layout.digits,
            rail_style=rail_style,
        )


__all__ = [
    "BodyPaintState",
    "BodyRenderer",
]
