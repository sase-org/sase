"""Tests for pager line-number gutter primitives."""

from __future__ import annotations

from sase.pager._gutter import (
    gutter_width,
    logical_line_count,
    number_width,
)


def test_gutter_width_uses_a_minimum_of_two_digit_columns() -> None:
    assert number_width(1) == 2
    assert number_width(9) == 2
    assert gutter_width(1) == 4
    assert gutter_width(99) == 4


def test_gutter_width_grows_at_one_hundred_and_one_thousand_lines() -> None:
    assert number_width(100) == 3
    assert gutter_width(100) == 5
    assert number_width(1000) == 4
    assert gutter_width(1000) == 6


def test_logical_line_count_drops_a_phantom_trailing_newline() -> None:
    assert logical_line_count("") == 0
    assert logical_line_count("a") == 1
    assert logical_line_count("a\n") == 1
    assert logical_line_count("\n") == 1
    assert logical_line_count("a\n\n") == 2
    assert logical_line_count("a\nb") == 2
