"""Tests for width-cached body composition and section row bookkeeping."""

from __future__ import annotations

from rich.console import Console, Group
from rich.text import Text

from sase.pager._labels import build_label_layer
from sase.pager._layout import (
    _measure_section_heights,
    _section_row_offsets,
    compose_body,
    current_section_index,
    search_corpus,
    styled_search_base,
)
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection

_CONSOLE = Console(color_system="truecolor")


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


def test_prepared_sections_change_color_but_not_wrapping_or_row_counts() -> None:
    """Adding style must never change what ``compose_body`` already measured."""
    sections = (
        _section("a", "\tif café:\n    value = '🐍'\n"),
        _section("b", "x" * 100),
    )
    document = PagerDocument(
        sections=sections, title="2 files", origin=PagerOrigin.FILE
    )
    plain = compose_body(document, width=20)

    styled_text = sections[0].body_text
    styled_text.stylize("bold green", 0, 5)
    prepared = {0: styled_text}
    colored = compose_body(document, width=20, prepared_sections=prepared)

    assert colored.section_offsets == plain.section_offsets
    assert colored.total_height == plain.total_height


def test_prepared_sections_stand_in_for_the_plain_body_in_composed_output() -> None:
    document = PagerDocument(
        sections=(_section("a", "hello\n"),), title="a", origin=PagerOrigin.FILE
    )
    styled_text = document.sections[0].body_text
    styled_text.stylize("bold red", 0, 5)

    composed = compose_body(document, width=40, prepared_sections={0: styled_text})

    assert isinstance(composed.renderable, Group)
    rendered = list(composed.renderable.renderables)[0]
    assert isinstance(rendered, Text)
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

    composed = compose_body(
        document,
        width=80,
        label_layer=layer,
        prepared_sections={0: styled_text},
    )

    assert isinstance(composed.renderable, Group)
    rendered = list(composed.renderable.renderables)[0]
    assert isinstance(rendered, Text)
    assert "[0]" in rendered.plain
    style = rendered.get_style_at_offset(_CONSOLE, 0)
    assert style.bold is True


def test_styled_search_base_matches_search_corpus_text_exactly() -> None:
    sections = (_section("a", "alpha\n"), _section("b", "beta"))
    document = PagerDocument(
        sections=sections, title="2 files", origin=PagerOrigin.FILE
    )

    assert styled_search_base(document).plain == search_corpus(document)


def test_styled_search_base_of_empty_document_matches_search_corpus() -> None:
    document = PagerDocument(sections=(), title="empty", origin=PagerOrigin.FILE)

    assert styled_search_base(document).plain == search_corpus(document)


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
