"""Tests for the pager line/range mark and reading-position math."""

from __future__ import annotations

from sase.pager._line_mark import LineMark, reading_scroll_y


def test_line_mark_normalizes_inverted_range() -> None:
    mark = LineMark(0, 40, 12)

    assert mark.start_line == 40
    assert mark.end_line == 40
    assert mark.emphasis_range == (40, 40)


def test_line_mark_suffix_uses_colon_and_en_dash() -> None:
    assert LineMark(0, 27, 27).suffix == ":27"
    assert LineMark(0, 27, 44).suffix == ":27–44"


def test_reading_scroll_y_places_context_above_the_start() -> None:
    assert (
        reading_scroll_y(
            start_row=20,
            end_row=20,
            viewport_height=10,
            max_scroll_y=100,
        )
        == 18
    )


def test_reading_scroll_y_keeps_a_fitting_range_on_screen() -> None:
    assert (
        reading_scroll_y(
            start_row=20,
            end_row=28,
            viewport_height=10,
            max_scroll_y=100,
        )
        == 19
    )


def test_reading_scroll_y_leaves_a_tall_range_at_the_reading_position() -> None:
    assert (
        reading_scroll_y(
            start_row=20,
            end_row=40,
            viewport_height=10,
            max_scroll_y=100,
        )
        == 18
    )


def test_reading_scroll_y_clamps_to_the_scroll_bounds() -> None:
    assert (
        reading_scroll_y(
            start_row=1,
            end_row=1,
            viewport_height=10,
            max_scroll_y=100,
        )
        == 0
    )
    assert (
        reading_scroll_y(
            start_row=100,
            end_row=100,
            viewport_height=10,
            max_scroll_y=50,
        )
        == 50
    )
