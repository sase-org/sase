"""Tests for the virtual body layout and section row bookkeeping."""

from __future__ import annotations

import random

from rich.console import Console
from rich.text import Text

from sase.pager._body_layout import BodyLayout, build_body_layout
from sase.pager._body_rows import BodyPaintState, BodyRenderer
from sase.pager._labels import _row_for_character_offset, build_label_layer
from sase.pager._layout import (
    ReadingAnchor,
    current_section_index,
    reading_anchor_at_row,
    row_for_reading_anchor,
    search_corpus,
    styled_search_base,
)
from sase.pager._line_mark import LineMark
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager._gutter import logical_line_count

_CONSOLE = Console(color_system="truecolor")


def _section(title: str, body: str) -> PagerSection:
    return PagerSection(
        identity=f"file:/tmp/{title}", title=title, kind="file", body=body
    )


def _layout(document: PagerDocument, width: int, **kwargs: object) -> BodyLayout:
    return build_body_layout(document, width, **kwargs)  # type: ignore[arg-type]


def _rendered_row(
    layout: BodyLayout, row: int, paint: BodyPaintState | None = None
) -> Text:
    return BodyRenderer(layout, paint or BodyPaintState()).render_row(row)


def test_section_row_offsets_places_the_first_section_at_row_zero() -> None:
    document = PagerDocument(
        sections=(
            _section("a", "alpha\n"),
            _section("b", "beta\n"),
            _section("c", "gamma\n"),
        ),
        title="3 files",
        origin=PagerOrigin.FILE,
    )

    layout = _layout(document, 40)

    # section 0 has no leading rule; sections 1.. start after the previous
    # section's body plus the one-line divider before them.
    assert layout.section_offsets == (0, 1, 3)


def test_section_row_offsets_handles_a_single_section() -> None:
    document = PagerDocument(
        sections=(_section("a", "alpha\n"),), title="a", origin=PagerOrigin.FILE
    )

    assert _layout(document, 40).section_offsets == (0,)


def test_section_row_offsets_handles_no_sections() -> None:
    document = PagerDocument(sections=(), title="empty", origin=PagerOrigin.FILE)

    assert _layout(document, 40).section_offsets == (0,)


def test_body_layout_records_dividers_between_sections() -> None:
    sections = (
        _section("a", "alpha\n"),
        _section("b", "beta\n"),
        _section("c", "gamma\n"),
    )
    document = PagerDocument(
        sections=sections, title="3 files", origin=PagerOrigin.FILE
    )

    layout = _layout(document, 40)

    assert layout.section_offsets[0] == 0
    assert len(layout.section_offsets) == 3
    assert layout.total_height >= 3


def test_body_layout_handles_an_empty_document() -> None:
    document = PagerDocument(sections=(), title="empty", origin=PagerOrigin.FILE)

    layout = _layout(document, 40)

    assert layout.section_offsets == (0,)
    assert layout.total_height == 0
    assert layout.section_line_counts == ()
    assert layout.section_line_rows == ()


def test_body_layout_records_exact_line_maps_and_paints_the_gutter() -> None:
    sections = (
        _section("a", "one\ntwo\nthree\n"),
        _section("b", "x" * 50),
    )
    document = PagerDocument(
        sections=sections, title="2 files", origin=PagerOrigin.FILE
    )

    layout = _layout(document, 20)

    # max logical lines is 3 → two digit columns + fence = 4 cells; wrap at 16.
    assert layout.section_line_counts == (3, 1)
    assert layout.section_offsets == (0, 3)
    assert layout.section_line_rows[0] == (0, 1, 2)
    assert layout.section_line_rows[1][0] == 4  # after the section-1 rule
    assert layout.total_height == 3 + 1 + 4  # bodies plus one divider rule
    first = _rendered_row(layout, 0)
    second_first = _rendered_row(layout, 4)
    second_second = _rendered_row(layout, 5)
    assert first.plain.startswith(" 1│ ")
    assert second_first.plain.startswith(" 1│ ")
    assert second_second.plain.startswith("  │ ")


def test_body_layout_emphasizes_the_goto_mark_number() -> None:
    document = PagerDocument(
        sections=(_section("a", "one\ntwo\nthree\n"),),
        title="a",
        origin=PagerOrigin.FILE,
    )

    layout = _layout(document, 40)
    paint = BodyPaintState(line_mark=LineMark(0, 2, 2), goto_accent="#FFAF5F")
    rendered = _rendered_row(layout, 1, paint)

    style = rendered.get_style_at_offset(_CONSOLE, 1)
    assert style.bold is True
    assert "2┃ " in rendered.plain


def test_body_layout_rails_a_marked_range() -> None:
    document = PagerDocument(
        sections=(_section("a", "one\ntwo\nthree\nfour\n"),),
        title="a",
        origin=PagerOrigin.FILE,
    )

    layout = _layout(document, 40)
    paint = BodyPaintState(line_mark=LineMark(0, 2, 3), goto_accent="#FFAF5F")
    rows = [_rendered_row(layout, row, paint).plain for row in range(4)]

    assert rows[0].startswith(" 1│ ")
    assert rows[1].startswith(" 2┃ ")
    assert rows[2].startswith(" 3┃ ")
    assert rows[3].startswith(" 4│ ")


def test_reading_anchor_round_trips_a_wrapped_line_across_widths() -> None:
    document = PagerDocument(
        sections=(_section("a", "x" * 50 + "\n" + "y\n"),),
        title="a",
        origin=PagerOrigin.FILE,
    )
    narrow = _layout(document, 20)
    wide = _layout(document, 80)

    # the 50-char line wraps at width 20 (content 16) but not at 80.
    assert len(narrow.section_line_rows[0]) == 2
    assert len(wide.section_line_rows[0]) == 2
    narrow_second_row = narrow.section_line_rows[0][0] + 1
    assert narrow_second_row < narrow.section_line_rows[0][1]

    anchor = reading_anchor_at_row(narrow, narrow_second_row)

    assert anchor == ReadingAnchor(section_index=0, line=1, row_offset=1)
    assert row_for_reading_anchor(wide, anchor) == wide.section_line_rows[0][0]
    assert row_for_reading_anchor(narrow, anchor) == narrow_second_row


def test_reading_anchor_on_a_section_rule_belongs_to_that_section() -> None:
    document = PagerDocument(
        sections=(_section("a", "alpha\n"), _section("b", "beta\n")),
        title="2 files",
        origin=PagerOrigin.FILE,
    )
    body = _layout(document, 40)

    rule_row = body.section_offsets[1]
    anchor = reading_anchor_at_row(body, rule_row)

    assert anchor == ReadingAnchor(section_index=1, line=1, row_offset=0)
    assert row_for_reading_anchor(body, anchor) == rule_row + 1


def test_reading_anchor_clamps_offset_and_line_to_the_new_width() -> None:
    document = PagerDocument(
        sections=(_section("a", "x" * 50 + "\n"),),
        title="a",
        origin=PagerOrigin.FILE,
    )
    narrow = _layout(document, 20)
    wide = _layout(document, 80)

    deep = ReadingAnchor(section_index=0, line=1, row_offset=3)
    assert row_for_reading_anchor(wide, deep) == wide.section_line_rows[0][0]
    assert row_for_reading_anchor(narrow, deep) == (narrow.section_line_rows[0][0] + 3)

    # out-of-range sections and lines clamp instead of raising.
    assert (
        row_for_reading_anchor(
            wide, ReadingAnchor(section_index=9, line=99, row_offset=-5)
        )
        == wide.section_line_rows[0][0]
    )


def test_reading_anchor_of_an_empty_document_is_the_origin() -> None:
    document = PagerDocument(sections=(), title="empty", origin=PagerOrigin.FILE)
    body = _layout(document, 40)

    assert reading_anchor_at_row(body, 0) == ReadingAnchor(
        section_index=0, line=1, row_offset=0
    )
    assert row_for_reading_anchor(body, ReadingAnchor(0, 1, 0)) == 0


def test_current_section_index_picks_the_last_offset_at_or_before_scroll_y() -> None:
    offsets = (0, 4, 10)

    assert current_section_index(offsets, 0) == 0
    assert current_section_index(offsets, 3) == 0
    assert current_section_index(offsets, 4) == 1
    assert current_section_index(offsets, 9) == 1
    assert current_section_index(offsets, 10) == 2
    assert current_section_index(offsets, 999) == 2


def test_search_corpus_joins_sections_with_a_single_divider_line() -> None:
    sections = (_section("a", "alpha"), _section("b", "beta"))
    document = PagerDocument(
        sections=sections, title="2 files", origin=PagerOrigin.FILE
    )

    corpus = search_corpus(document)

    lines = corpus.splitlines()
    assert lines[0] == "alpha"
    assert "2/2" in lines[1]
    assert lines[2] == "beta"


def test_search_corpus_of_a_single_section_has_no_divider() -> None:
    document = PagerDocument(
        sections=(_section("a", "alpha"),), title="a", origin=PagerOrigin.FILE
    )

    assert search_corpus(document) == "alpha\n"


def test_prepared_sections_change_color_but_not_wrapping_or_row_counts() -> None:
    """Adding style must never change what the layout already measured."""
    sections = (
        _section("a", "\tif café:\n    value = '🐍'\n"),
        _section("b", "x" * 100),
    )
    document = PagerDocument(
        sections=sections, title="2 files", origin=PagerOrigin.FILE
    )
    plain = _layout(document, 20)

    styled_text = sections[0].body_text
    styled_text.stylize("bold green", 0, 5)
    prepared = {0: styled_text}
    colored = _layout(document, 20, prepared_sections=prepared)

    assert colored.section_offsets == plain.section_offsets
    assert colored.total_height == plain.total_height


def test_prepared_sections_stand_in_for_the_plain_body_in_painted_rows() -> None:
    document = PagerDocument(
        sections=(_section("a", "hello\n"),), title="a", origin=PagerOrigin.FILE
    )
    styled_text = document.sections[0].body_text
    styled_text.stylize("bold red", 0, 5)

    layout = _layout(document, 40, prepared_sections={0: styled_text})
    rendered = _rendered_row(
        layout, 0, BodyPaintState(prepared_sections={0: styled_text})
    )

    assert rendered.spans


def test_prepared_sections_thread_through_the_labeled_render_path_too() -> None:
    document = PagerDocument(
        sections=(_section("a", "see https://example.test/x\n"),),
        title="a",
        origin=PagerOrigin.FILE,
    )
    styled_text = document.sections[0].body_text
    styled_text.stylize("bold green", 0, 3)
    layer = build_label_layer(document, width=80)

    layout = _layout(
        document,
        80,
        label_layer=layer,
        prepared_sections={0: styled_text},
    )
    rendered = _rendered_row(
        layout,
        0,
        BodyPaintState(label_layer=layer, prepared_sections={0: styled_text}),
    )

    assert "[0]" in rendered.plain
    content_start = rendered.plain.index("see")
    style = rendered.get_style_at_offset(_CONSOLE, content_start)
    assert style.bold is True
    assert rendered.plain.startswith(" 1│ ")


def test_styled_search_base_matches_search_corpus_text_exactly() -> None:
    sections = (_section("a", "alpha\n"), _section("b", "beta"))
    document = PagerDocument(
        sections=sections, title="2 files", origin=PagerOrigin.FILE
    )

    assert styled_search_base(document).plain == search_corpus(document)


def test_styled_search_base_of_empty_document_matches_search_corpus() -> None:
    document = PagerDocument(sections=(), title="empty", origin=PagerOrigin.FILE)

    assert styled_search_base(document).plain == search_corpus(document)


def _reference_reading_anchor_at_row(body: BodyLayout, row: int) -> ReadingAnchor:
    """The pre-bisect anchor lookup: linear scans over offsets and rows."""
    section_count = len(body.section_line_rows)
    if section_count == 0 or body.total_height <= 0:
        return ReadingAnchor(section_index=0, line=1, row_offset=0)
    clamped = max(0, min(row, body.total_height - 1))
    for index in range(1, len(body.section_offsets)):
        if clamped == body.section_offsets[index]:
            return ReadingAnchor(section_index=index, line=1, row_offset=0)
    section_index = 0
    for index, offset in enumerate(body.section_offsets):
        start = offset + (1 if index > 0 else 0)
        if start <= clamped:
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


def _reference_current_section_index(offsets: tuple[int, ...], scroll_y: int) -> int:
    """The pre-bisect section lookup: linear scan for the last offset."""
    index = 0
    for candidate, offset in enumerate(offsets):
        if offset <= scroll_y:
            index = candidate
        else:
            break
    return index


def _reference_estimated_line_rows(text: str, width: int) -> tuple[int, ...]:
    """The pre-prefix estimator: one offset walk per logical line."""
    count = logical_line_count(text)
    if count == 0:
        return ()
    rows: list[int] = []
    cursor = 0
    for _index in range(count):
        rows.append(_row_for_character_offset(text, cursor, width))
        newline = text.find("\n", cursor)
        cursor = len(text) if newline < 0 else newline + 1
    return tuple(rows)


def _parity_document() -> PagerDocument:
    return PagerDocument(
        sections=(
            _section("a", "alpha\nbeta gamma delta\n"),
            _section("b", "x" * 100 + "\nshort\n"),
            _section("c", "日本語の行🎉\nlast"),
        ),
        title="3 files",
        origin=PagerOrigin.FILE,
    )


def test_bisect_lookups_match_the_linear_reference() -> None:
    """Fixed-seed check: bisect anchor/section lookups keep exact results."""
    random.seed(20261002)
    document = _parity_document()
    for width in (10, 40, 120):
        body = _layout(document, width)
        rows = [-5, -1, 0, 1]
        rows.extend(random.randint(0, body.total_height + 5) for _ in range(60))
        rows.extend([body.total_height - 1, body.total_height, body.total_height + 100])
        for row in rows:
            assert reading_anchor_at_row(body, row) == (
                _reference_reading_anchor_at_row(body, row)
            )
        scrolls = [-5, -1, 0, 1]
        scrolls.extend(random.randint(0, body.total_height + 5) for _ in range(60))
        scrolls.extend(
            [body.total_height - 1, body.total_height, body.total_height + 100]
        )
        for scroll_y in scrolls:
            assert current_section_index(
                body.section_offsets, scroll_y
            ) == _reference_current_section_index(body.section_offsets, scroll_y)


def test_estimated_line_rows_match_the_per_line_walk() -> None:
    """The memoized prefix carries exactly the old per-line row estimates."""
    from sase.pager._body_layout import _estimated_line_rows

    random.seed(424242)
    lines = ("alpha", "x" * 100, "日本語🎉", "", "  tail  ")
    for _trial in range(20):
        text = "\n".join(random.choice(lines) for _ in range(random.randint(1, 12)))
        if random.random() < 0.5:
            text += "\n"
        width = random.choice([1, 10, 40, 120])
        section = _section("rows", text)
        assert _estimated_line_rows(section, width) == (
            _reference_estimated_line_rows(text, width)
        )


def test_styled_search_base_uses_prepared_text_and_link_accents_without_capsules() -> (
    None
):
    document = PagerDocument(
        sections=(_section("a", "see src/sase/pager/app.py now\n"),),
        title="a",
        origin=PagerOrigin.FILE,
    )
    styled_text = document.sections[0].body_text
    styled_text.stylize("bold magenta", 0, 3)  # pretend "see" is a syntax keyword

    base = styled_search_base(document, prepared_sections={0: styled_text})

    assert base.plain == search_corpus(document)
    assert "[" not in base.plain
    assert base.get_style_at_offset(_CONSOLE, 0).bold is True
    target_start = base.plain.index("src/sase/pager/app.py")
    assert base.get_style_at_offset(_CONSOLE, target_start).bold is True
