"""Tests for the big-digit renderer used by the sase ace startup splash."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets._big_digits import (
    DIGIT_COLS,
    GLYPH_ROWS,
    PUNCT_COLS,
    glyph,
    render_big_digits,
)


def test_digit_glyphs_are_5x6() -> None:
    """Every digit glyph is 5 rows tall and 6 columns wide."""
    for ch in "0123456789":
        rows = glyph(ch)
        assert len(rows) == GLYPH_ROWS
        for row in rows:
            assert len(row) == DIGIT_COLS, f"digit {ch!r} row {row!r}"


def test_punct_glyphs_are_5x2() -> None:
    """``.`` and ``:`` glyphs are 5 rows tall and 2 columns wide."""
    for ch in ".:":
        rows = glyph(ch)
        assert len(rows) == GLYPH_ROWS
        for row in rows:
            assert len(row) == PUNCT_COLS


def test_unsupported_character_raises() -> None:
    with pytest.raises(ValueError):
        glyph("a")


def test_render_empty_string_returns_empty() -> None:
    assert render_big_digits("") == ""


def test_render_single_digit_matches_glyph() -> None:
    """Rendering a single digit yields the literal glyph rows."""
    expected = "\n".join(glyph("3"))
    assert render_big_digits("3") == expected


def test_render_joins_with_single_column_gap() -> None:
    """Adjacent glyphs are joined with a single blank-column gap per row."""
    rendered = render_big_digits("12")
    rows = rendered.split("\n")
    assert len(rows) == GLYPH_ROWS
    # Each row should be DIGIT_COLS + 1 (gap) + DIGIT_COLS = 13 visual columns.
    expected_width = DIGIT_COLS + 1 + DIGIT_COLS
    for row in rows:
        assert len(row) == expected_width


def test_render_dot_shrinks_total_width() -> None:
    """Using ``.`` contributes only 2 cols to the row width."""
    rendered = render_big_digits("0.")
    rows = rendered.split("\n")
    expected_width = DIGIT_COLS + 1 + PUNCT_COLS
    assert all(len(row) == expected_width for row in rows)


def test_render_full_stopwatch_readout() -> None:
    """Rendering ``03.4`` yields a multi-line readout with the expected width."""
    rendered = render_big_digits("03.4")
    rows = rendered.split("\n")
    assert len(rows) == GLYPH_ROWS
    # Row width: three digits + dot + three gaps.
    expected_width = DIGIT_COLS * 3 + PUNCT_COLS + 3
    for row in rows:
        assert len(row) == expected_width


def test_render_raises_on_unsupported_in_mixed_string() -> None:
    with pytest.raises(ValueError):
        render_big_digits("1x")
