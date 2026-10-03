"""Width-dependent virtual body layout for the pager.

Textual-free. :func:`build_body_layout` computes the integer maps
``section_offsets``, ``total_height``, ``section_line_counts`` and
``section_line_rows`` — plus the per-line wrap state a row lookup needs,
without retaining any styled text. Only compact integer arrays are kept per
section; the field names match what ``goto``, trail, history, diff and
reading-anchor callers already read, so they keep working unchanged.

Layout inputs are the document, the paint width, the label layer and the
removal anchors. Everything else (pending label prefix, syntax-prepared
text styles, goto emphasis, change marks, rail styles, theme surface) is
paint state owned by ``_body_rows`` and never affects these row counts:
prepared text carries the exact same plain text as the section body, and
pending prefixes or accent styles never change a capsule's characters.
"""

from __future__ import annotations

from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import blake2b
from typing import Any

from rich.console import Console, RenderableType
from rich.text import Text

from sase.pager._body_lines import (
    logical_line_end,
    logical_line_starts,
    make_wrap_console,
    wrap_line_pieces,
)
from sase.pager._chrome_sections import section_rule
from sase.pager._gutter import gutter_width, logical_line_count, number_width
from sase.pager._labels import PagerLabel, PagerLabelLayer, render_section_with_labels
from sase.pager.document import (
    PagerDocument,
    PagerSection,
    section_line_prefix,
)

_DIVIDER_LINES = 1


@dataclass(frozen=True, slots=True)
class _RowLocation:
    """One absolute row resolved to its document position.

    ``kind`` is ``"rule"`` (a section-transition rule), ``"anchor"`` (a
    removal-anchor row, with ``anchor_after`` holding the 1-based logical
    line it follows, or 0 for before-first), ``"line"`` (a body row, with
    1-based ``line`` and 0-based ``wrap_index``), ``"empty"`` (the single
    visual row of a zero-line body) or ``"custom"`` (a pre-rendered
    non-``Text`` row, with ``wrap_index`` holding the row's offset inside
    the section).
    """

    kind: str
    section_index: int
    line: int = 0
    wrap_index: int = 0
    anchor_after: int = 0


def effective_section_source(
    section: PagerSection, prepared: Text | None
) -> Text | None:
    """Return the prepared text to lay out, or ``None`` for the plain body.

    Prepared syntax text is guaranteed to carry the section's exact plain
    text; a mismatch means the guarantee was violated, so the plain body
    wins and layout stays aligned with the label offsets. Paint uses this
    same rule, so both sides always wrap the same characters.
    """
    if prepared is not None and prepared.plain == section.plain_text:
        return prepared
    return None


def _renderable_rows(renderable: RenderableType, width: int) -> tuple[Text, ...]:
    """Pre-render a non-``Text`` section body into one row text per row.

    Uses the same fallback console the height estimate measures with,
    so row counts match the reported height.
    """
    console = Console(width=max(width, 1), color_system=None, highlight=False)
    lines = console.render_lines(renderable, pad=False)
    rows: list[Text] = []
    for segments in lines:
        row = Text()
        for segment in segments:
            row.append(segment.text, style=segment.style)
        rows.append(row)
    if not rows:
        rows.append(Text())
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class BodySectionLayout:
    """Integer layout state for one section (never mutated after build)."""

    kind: str  # "text" or "custom"
    starts: array
    counts: array
    rows: array  # section-relative first row of each logical line
    fingerprints: array
    capsules: array  # 1 where a label capsule sits on the line
    anchor_after: frozenset[int]
    anchor_before: bool
    height: int  # body rows including anchors, excluding the rule
    label_key: tuple[tuple[int, int, str, bool], ...]
    rule: Text | None
    prerendered: tuple[Text, ...] | None
    estimated: array | None
    fingerprinted: bool = False


def _label_key(
    labels: tuple[PagerLabel, ...],
) -> tuple[tuple[int, int, str, bool], ...]:
    ordered = sorted(labels, key=lambda item: item.target.start)
    return tuple(
        (item.target.start, item.target.end, item.hint, item.dangling)
        for item in ordered
    )


def _section_kind(section: PagerSection, labels: tuple[PagerLabel, ...]) -> str:
    if not labels and not isinstance(section.body_renderable, Text):
        return "custom"
    return "text"


def _fingerprint(line_plain: str) -> int:
    return int.from_bytes(blake2b(line_plain.encode("utf-8"), digest_size=8).digest())


_PRINTABLE_ASCII = bytes(range(0x20, 0x7F))


def _is_single_row_plain(plain: str, *, has_capsule: bool, content_width: int) -> bool:
    """Fast path: an ASCII line with no tab or capsule that fits is one row."""
    if has_capsule or len(plain) > content_width:
        return False
    if not plain:
        return True
    try:
        raw = plain.encode("ascii")
    except UnicodeEncodeError:
        return False
    # C-speed check: strip printable ASCII; anything left disqualifies.
    return not raw.translate(None, delete=_PRINTABLE_ASCII)


def _estimated_line_rows(section: PagerSection, width: int) -> tuple[int, ...]:
    """Estimated first row of each logical line, for non-``Text`` bodies."""
    count = logical_line_count(section.plain_text)
    if count == 0:
        return ()
    _starts, start_rows = section_line_prefix(section, width)
    return start_rows[:count]


def _section_row_offsets(heights: tuple[int, ...]) -> tuple[int, ...]:
    if not heights:
        return (0,)
    offsets = [0]
    row = heights[0]
    for height in heights[1:]:
        offsets.append(row)
        row += _DIVIDER_LINES + height
    return tuple(offsets)


def _labeled_text(
    section: PagerSection,
    labels: tuple[PagerLabel, ...],
    prepared: dict[int, Text],
) -> Text:
    source = effective_section_source(section, prepared.get(id(section)))
    if not labels:
        if source is not None:
            return source.copy()
        return section.body_text
    return render_section_with_labels(
        section,
        labels,
        pending_prefix="",
        source=source,
        surface=None,
    )


def _line_has_capsule(label_starts: list[int], start: int, end: int) -> bool:
    # A capsule inserted exactly at a newline offset paints on the line the
    # newline terminates, so the end bound is inclusive.
    pos = bisect_left(label_starts, start)
    return pos < len(label_starts) and label_starts[pos] <= end


def _count_line(
    line_plain: str,
    template: Text,
    has_capsule: bool,
    *,
    content_width: int,
    wrap_console: Console,
) -> int:
    if _is_single_row_plain(
        line_plain, has_capsule=has_capsule, content_width=content_width
    ):
        return 1
    piece = Text(line_plain)
    piece.tab_size = template.tab_size
    piece.justify = template.justify
    return len(wrap_line_pieces(piece, content_width, wrap_console))


def _place_rows(
    counts: array, anchor_after: frozenset[int], anchor_before: bool
) -> tuple[array, int]:
    """Return per-line relative rows and the section body height."""
    rows = array("Q")
    cursor = 1 if anchor_before else 0
    for line_pos in range(len(counts)):
        rows.append(cursor)
        cursor += counts[line_pos]
        if line_pos + 1 in anchor_after:
            cursor += 1
    height = cursor if len(counts) else 1
    return rows, height


@dataclass(frozen=True, slots=True)
class _SectionSpec:
    section: PagerSection
    index: int
    labels: tuple[PagerLabel, ...]
    anchors: frozenset[int]
    rule: Text | None


def _build_text_section(
    spec: _SectionSpec,
    prepared: dict[int, Text],
    *,
    content_width: int,
    wrap_console: Console,
    labeled: Text | None = None,
    previous: BodySectionLayout | None = None,
) -> tuple[BodySectionLayout, int]:
    """Lay out one ``Text`` section; return it with its laid-out line count.

    With *previous* set, only lines whose fingerprint changed are
    recounted and only those count toward the returned delta.
    """
    text = (
        labeled
        if labeled is not None
        else _labeled_text(spec.section, spec.labels, prepared)
    )
    plain = text.plain
    starts = logical_line_starts(plain)
    label_starts = sorted(item.target.start for item in spec.labels)
    track = bool(label_starts)
    anchor_after = frozenset(a for a in spec.anchors if a != 0)
    anchor_before = 0 in spec.anchors
    # Only a fresh build with no labels skips fingerprinting (the 100k-line
    # fast path). Every other build hashes each line so a later relabel can
    # diff granularly in either direction — labels added or removed.
    fast = previous is None and not track
    baseline = None
    if (
        previous is not None
        and previous.fingerprinted
        and len(starts) == len(previous.starts)
    ):
        baseline = previous
    counts = array("I", baseline.counts) if baseline is not None else array("I")
    if baseline is not None:
        fingerprints = array("Q", baseline.fingerprints)
        capsules = array("b", baseline.capsules)
    elif fast:
        fingerprints = array("Q", [0]) * len(starts) or array("Q")
        capsules = array("b", [0]) * len(starts) or array("b")
    else:
        fingerprints = array("Q")
        capsules = array("b")
    changed = 0
    for line_pos in range(len(starts)):
        line_end = logical_line_end(starts, line_pos, plain)
        line_plain = plain[starts[line_pos] : line_end]
        if not fast:
            fingerprint = _fingerprint(line_plain)
            if baseline is not None and fingerprint == baseline.fingerprints[line_pos]:
                continue
        has_capsule = (
            _line_has_capsule(label_starts, starts[line_pos], line_end)
            if track
            else False
        )
        recounted = _count_line(
            line_plain,
            text,
            has_capsule,
            content_width=content_width,
            wrap_console=wrap_console,
        )
        if baseline is not None:
            capsules[line_pos] = 1 if has_capsule else 0
            counts[line_pos] = recounted
            fingerprints[line_pos] = fingerprint
        elif fast:
            counts.append(recounted)
        else:
            capsules.append(1 if has_capsule else 0)
            counts.append(recounted)
            fingerprints.append(fingerprint)
        changed += 1
    rows, height = _place_rows(counts, anchor_after, anchor_before)
    return BodySectionLayout(
        kind="text",
        starts=starts,
        counts=counts,
        rows=rows,
        fingerprints=fingerprints,
        capsules=capsules,
        anchor_after=anchor_after,
        anchor_before=anchor_before,
        height=height,
        label_key=_label_key(spec.labels),
        rule=spec.rule,
        prerendered=None,
        estimated=None,
        fingerprinted=not fast,
    ), (changed if baseline is not None else len(starts))


def _build_custom_section(spec: _SectionSpec, *, width: int) -> BodySectionLayout:
    rows = _renderable_rows(spec.section.body_renderable, width)
    return BodySectionLayout(
        kind="custom",
        starts=array("Q"),
        counts=array("I"),
        rows=array("Q"),
        fingerprints=array("Q"),
        capsules=array("b"),
        anchor_after=frozenset(),
        anchor_before=False,
        height=max(len(rows), 1),
        label_key=_label_key(spec.labels),
        rule=spec.rule,
        prerendered=rows,
        estimated=array("Q", _estimated_line_rows(spec.section, width)),
        fingerprinted=False,
    )


@dataclass
class BodyLayout:
    """Virtual body layout: integer maps plus per-section wrap state.

    ``lines_laid_out`` counts laid-out logical lines (a full build lays
    out every line once; :meth:`relabel` counts only relaid lines), the
    hook later work-counter tests assert on. The layout retains its
    sections (the view already holds the same document) so :meth:`relabel`
    can recompute changed lines without new input.
    """

    section_offsets: tuple[int, ...]
    total_height: int
    section_line_counts: tuple[int, ...]
    section_line_rows: tuple[tuple[int, ...], ...]
    width: int
    digits: int
    content_width: int
    lines_laid_out: int = 0

    _sections: tuple[BodySectionLayout, ...] = ()
    _label_layer: PagerLabelLayer | None = None
    _kept_sections: tuple[PagerSection, ...] = ()
    _prepared: dict[int, Text] = field(default_factory=dict, repr=False)
    _anchors: tuple[frozenset[int], ...] = ()

    @property
    def section_states(self) -> tuple[BodySectionLayout, ...]:
        """Per-section wrap state, for the row renderer."""
        return self._sections

    @property
    def bound_sections(self) -> tuple[PagerSection, ...]:
        """Sections this layout was built from, for the row renderer."""
        return self._kept_sections

    def locate(self, row: int) -> _RowLocation:
        """Resolve absolute *row* to a rule, anchor, line or custom row."""
        if not self._sections or self.total_height <= 0:
            return _RowLocation(kind="empty", section_index=0)
        clamped = max(0, min(row, self.total_height - 1))
        rule = bisect_left(self.section_offsets, clamped, 1)
        if rule < len(self.section_offsets) and self.section_offsets[rule] == clamped:
            return _RowLocation(kind="rule", section_index=rule)
        body_starts = [
            self.section_offsets[index] + (1 if index > 0 else 0)
            for index in range(len(self.section_offsets))
        ]
        section_index = max(0, bisect_right(body_starts, clamped) - 1)
        section = self._sections[section_index]
        relative = clamped - body_starts[section_index]
        if section.kind == "custom":
            return self._locate_custom(section, section_index, relative)
        if len(section.starts) == 0:
            if section.anchor_before:
                return _RowLocation(
                    kind="anchor", section_index=section_index, anchor_after=0
                )
            return _RowLocation(kind="empty", section_index=section_index)
        if relative == 0 and section.anchor_before:
            return _RowLocation(
                kind="anchor", section_index=section_index, anchor_after=0
            )
        # Section rows already include the before-first anchor offset.
        adjusted = relative
        line_pos = max(0, bisect_right(section.rows, adjusted) - 1)
        line_start = section.rows[line_pos]
        if adjusted >= line_start + section.counts[line_pos]:
            return _RowLocation(
                kind="anchor",
                section_index=section_index,
                anchor_after=line_pos + 1,
            )
        return _RowLocation(
            kind="line",
            section_index=section_index,
            line=line_pos + 1,
            wrap_index=adjusted - line_start,
        )

    def _locate_custom(
        self, section: BodySectionLayout, section_index: int, relative: int
    ) -> _RowLocation:
        estimated = section.estimated or array("Q")
        if not estimated:
            return _RowLocation(kind="empty", section_index=section_index)
        line_pos = max(0, bisect_right(estimated, relative) - 1)
        return _RowLocation(
            kind="custom",
            section_index=section_index,
            line=line_pos + 1,
            wrap_index=relative,
        )

    def relabel(self, new_layer: PagerLabelLayer | None) -> BodyLayout:
        """Recompute only lines whose label content changed.

        Sections whose label key is identical are shared untouched (zero
        relaid lines). A section that flips between the ``Text`` and
        pre-rendered paths is rebuilt whole.
        """
        sections = self._kept_sections
        if new_layer is not None and len(new_layer.labels_by_section) != len(sections):
            raise ValueError("relabel layer covers a different section count")
        wrap_console = make_wrap_console(self.content_width)
        rebuilt: list[BodySectionLayout] = []
        relaid = 0
        for index, current in enumerate(self._sections):
            labels = new_layer.labels_by_section[index] if new_layer is not None else ()
            labels = tuple(labels)
            if (
                _label_key(labels) == current.label_key
                and _section_kind(sections[index], labels) == current.kind
            ):
                rebuilt.append(current)
                continue
            spec = _SectionSpec(
                section=sections[index],
                index=index,
                labels=labels,
                anchors=self._anchors[index],
                rule=current.rule,
            )
            if _section_kind(sections[index], labels) == "custom":
                rebuilt.append(_build_custom_section(spec, width=self.width))
                continue
            if current.kind != "text":
                fresh, delta = _build_text_section(
                    spec,
                    self._prepared,
                    content_width=self.content_width,
                    wrap_console=wrap_console,
                )
                rebuilt.append(fresh)
                relaid += delta
                continue
            labeled = _labeled_text(sections[index], labels, self._prepared)
            if len(logical_line_starts(labeled.plain)) != len(current.starts):
                fresh, delta = _build_text_section(
                    spec,
                    self._prepared,
                    content_width=self.content_width,
                    wrap_console=wrap_console,
                    labeled=labeled,
                )
                rebuilt.append(fresh)
                relaid += delta
                continue
            fresh, delta = _build_text_section(
                spec,
                self._prepared,
                content_width=self.content_width,
                wrap_console=wrap_console,
                labeled=labeled,
                previous=current,
            )
            rebuilt.append(fresh)
            relaid += delta
        return _assemble(
            rebuilt,
            width=self.width,
            digits=self.digits,
            content_width=self.content_width,
            lines_laid_out=relaid,
            layer=new_layer,
            kept=self._kept_sections,
            prepared=self._prepared,
            anchors=self._anchors,
        )


def _assemble(
    built: list[BodySectionLayout],
    *,
    width: int,
    digits: int,
    content_width: int,
    lines_laid_out: int,
    layer: PagerLabelLayer | None,
    kept: tuple[PagerSection, ...],
    prepared: dict[int, Text],
    anchors: tuple[frozenset[int], ...],
) -> BodyLayout:
    heights = tuple(section.height for section in built)
    offsets = _section_row_offsets(heights)
    line_rows: list[tuple[int, ...]] = []
    for index, section in enumerate(built):
        body_start = offsets[index] + (0 if index == 0 else _DIVIDER_LINES)
        line_rows.append(tuple(body_start + row for row in section.rows))
    divider_rows = _DIVIDER_LINES * max(len(built) - 1, 0)
    return BodyLayout(
        section_offsets=offsets,
        total_height=sum(heights) + divider_rows,
        section_line_counts=tuple(len(section.starts) for section in built),
        section_line_rows=tuple(line_rows),
        width=width,
        digits=digits,
        content_width=content_width,
        lines_laid_out=lines_laid_out,
        _sections=tuple(built),
        _label_layer=layer,
        _kept_sections=kept,
        _prepared=prepared,
        _anchors=anchors,
    )


def build_body_layout(
    document: PagerDocument,
    width: int,
    *,
    label_layer: PagerLabelLayer | None = None,
    prepared_sections: Mapping[int, Text] | None = None,
    removal_anchors: Mapping[int, set[int]] | None = None,
) -> BodyLayout:
    """Lay out *document* at *width* into integer row maps.

    Row counts use exactly ``Text.wrap(..., overflow="fold")`` semantics on
    each labeled display line; an ASCII fast path skips Rich only when the
    line provably fits on one row. The returned ``section_offsets``,
    ``total_height``, ``section_line_counts`` and ``section_line_rows``
    equal the composer's.
    """
    paint_width = max(width, 1)
    sections = document.sections
    if not sections:
        return BodyLayout(
            section_offsets=(0,),
            total_height=0,
            section_line_counts=(),
            section_line_rows=(),
            width=paint_width,
            digits=number_width(0),
            content_width=max(paint_width - gutter_width(0), 1),
        )
    max_count = max(
        (logical_line_count(section.plain_text) for section in sections),
        default=0,
    )
    digits = number_width(max_count)
    content_width = max(paint_width - gutter_width(max_count), 1)
    anchors = tuple(
        frozenset(
            removal_anchors.get(index, frozenset()) if removal_anchors else frozenset()
        )
        for index in range(len(sections))
    )
    prepared = {
        id(section): prepared_sections[index]
        for index, section in enumerate(sections)
        if prepared_sections is not None and index in prepared_sections
    }
    wrap_console = make_wrap_console(content_width)
    total = len(sections)
    built: list[BodySectionLayout] = []
    total_lines = 0
    for index, section in enumerate(sections):
        labels = label_layer.labels_by_section[index] if label_layer is not None else ()
        labels = tuple(labels)
        rule = None
        if index > 0:
            rule = section_rule(
                section, index=index + 1, total=total, width=paint_width
            )
        spec = _SectionSpec(
            section=section,
            index=index,
            labels=labels,
            anchors=anchors[index],
            rule=rule,
        )
        if _section_kind(section, labels) == "custom":
            built.append(_build_custom_section(spec, width=paint_width))
            continue
        entry, _delta = _build_text_section(
            spec,
            prepared,
            content_width=content_width,
            wrap_console=wrap_console,
        )
        built.append(entry)
        total_lines += len(entry.starts)
    return _assemble(
        built,
        width=paint_width,
        digits=digits,
        content_width=content_width,
        lines_laid_out=total_lines,
        layer=label_layer,
        kept=tuple(sections),
        prepared=prepared,
        anchors=anchors,
    )


__all__ = [
    "BodyLayout",
    "BodySectionLayout",
    "build_body_layout",
    "effective_section_source",
]
