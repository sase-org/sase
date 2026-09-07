"""Tests for pager line-number gutter primitives."""

from __future__ import annotations

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from sase.pager._gutter import (
    apply_gutter,
    gutter_width,
    logical_line_count,
    number_width,
)

_CONSOLE = Console(color_system="truecolor")


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


def test_apply_gutter_drops_phantom_trailing_newline() -> None:
    with_newline = apply_gutter(Text("a\n"), content_width=20, number_width=2)
    without = apply_gutter(Text("a"), content_width=20, number_width=2)

    assert with_newline.line_rows == without.line_rows == (0,)
    assert with_newline.row_count == without.row_count == 1


def test_apply_gutter_empty_body_has_one_visual_row_and_no_lines() -> None:
    result = apply_gutter(Text(""), content_width=20, number_width=2)

    assert result.line_rows == ()
    assert result.row_count == 1
    assert result.text.plain.startswith("  │ ")


def test_apply_gutter_hanging_continuation_rows_keep_the_fence() -> None:
    result = apply_gutter(Text("x" * 25), content_width=10, number_width=2)
    rows = result.text.plain.split("\n")

    assert rows[0].startswith(" 1│ ")
    assert rows[1].startswith("  │ ")
    assert result.line_rows == (0,)
    assert result.row_count == 3
    for row in rows:
        assert cell_len(row) - 4 <= 10


def test_apply_gutter_line_rows_are_exact_under_wrapping() -> None:
    result = apply_gutter(
        Text("short\n" + "x" * 25 + "\nend"),
        content_width=10,
        number_width=2,
    )

    assert result.line_rows == (0, 1, 4)
    assert result.row_count == 5
    rows = result.text.plain.split("\n")
    assert rows[0].startswith(" 1│ ")
    assert rows[1].startswith(" 2│ ")
    assert rows[2].startswith("  │ ")
    assert rows[4].startswith(" 3│ ")


def test_apply_gutter_emphasizes_the_marked_line_number() -> None:
    result = apply_gutter(
        Text("one\ntwo\nthree"),
        content_width=20,
        number_width=2,
        emphasis_line=2,
        accent="#FFAF5F",
    )
    # " 2│ two" sits on visual row 1; the '2' is at offset 1.
    second = result.text.plain.split("\n")[1]
    assert second.startswith(" 2│ ")
    offset = result.text.plain.index("2")
    style = result.text.get_style_at_offset(_CONSOLE, offset)
    assert style.bold is True
    first_style = result.text.get_style_at_offset(
        _CONSOLE, result.text.plain.index("1")
    )
    assert first_style.bold is not True


def test_apply_gutter_wraps_wide_characters_by_cell_width() -> None:
    result = apply_gutter(
        Text("你好世界你好世界"),
        content_width=10,
        number_width=2,
    )
    rows = result.text.plain.split("\n")
    assert result.line_rows == (0,)
    assert result.row_count == 2
    for row in rows:
        content = row[4:]
        assert cell_len(content) <= 10
