"""Tests for width-cached body composition and section row bookkeeping."""

from __future__ import annotations

from rich.console import Group

from sase.pager._layout import (
    _measure_section_heights,
    _section_row_offsets,
    compose_body,
    current_section_index,
    search_corpus,
)
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection


def _section(title: str, body: str) -> PagerSection:
    return PagerSection(
        identity=f"file:/tmp/{title}", title=title, kind="file", body=body
    )


def test_measure_section_heights_counts_wrapped_lines() -> None:
    sections = (_section("a", "one\ntwo\nthree"), _section("b", "x" * 100))

    heights = _measure_section_heights(sections, width=20)

    assert heights[0] == 3
    assert heights[1] == 5  # 100 chars wrapped at width 20


def test_section_row_offsets_places_the_first_section_at_row_zero() -> None:
    offsets = _section_row_offsets((3, 5, 2))

    # section 0 has no leading rule; sections 1.. start after the previous
    # section's body plus the one-line divider before them.
    assert offsets == (0, 3, 3 + 1 + 5)


def test_section_row_offsets_handles_a_single_section() -> None:
    assert _section_row_offsets((4,)) == (0,)


def test_section_row_offsets_handles_no_sections() -> None:
    assert _section_row_offsets(()) == (0,)


def test_compose_body_renders_a_group_with_dividers_between_sections() -> None:
    sections = (
        _section("a", "alpha\n"),
        _section("b", "beta\n"),
        _section("c", "gamma\n"),
    )
    document = PagerDocument(
        sections=sections, title="3 files", origin=PagerOrigin.FILE
    )

    composed = compose_body(document, width=40)

    assert isinstance(composed.renderable, Group)
    # one body per section plus a rule before section 2 and section 3.
    assert len(list(composed.renderable.renderables)) == 5
    assert composed.section_offsets[0] == 0
    assert len(composed.section_offsets) == 3
    assert composed.total_height >= 3


def test_compose_body_handles_an_empty_document() -> None:
    document = PagerDocument(sections=(), title="empty", origin=PagerOrigin.FILE)

    composed = compose_body(document, width=40)

    assert composed.section_offsets == (0,)
    assert composed.total_height == 0


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
