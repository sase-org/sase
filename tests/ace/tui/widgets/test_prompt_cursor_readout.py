"""Tests for the prompt cursor line/column readout formatting."""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets._prompt_cursor_readout import (
    CURSOR_READOUT_MODE_COLORS,
    cursor_readout_cell_width,
    cursor_readout_position,
    format_cursor_readout,
)


@dataclass
class _FakeTextArea:
    cursor_location: tuple[int, int]


def _digit_styles(text: Text, *digits: str) -> list[str]:
    """Return the style string covering each of *digits* in *text*."""
    styles = []
    for span in text.spans:
        substring = text.plain[span.start : span.end]
        if substring in digits:
            styles.append(str(span.style))
    return styles


def test_cursor_readout_position_converts_zero_based_to_one_based() -> None:
    assert cursor_readout_position(_FakeTextArea((0, 0))) == (1, 1)
    assert cursor_readout_position(_FakeTextArea((2, 11))) == (3, 12)


def test_format_cursor_readout_renders_expected_words() -> None:
    assert format_cursor_readout(1, 1, vim_mode="insert").plain == "Ln 1, Col 1"
    assert format_cursor_readout(3, 12, vim_mode="insert").plain == "Ln 3, Col 12"


def test_format_cursor_readout_colors_digits_by_mode() -> None:
    for mode, color in CURSOR_READOUT_MODE_COLORS.items():
        text = format_cursor_readout(3, 12, vim_mode=mode)
        styles = _digit_styles(text, "3", "12")
        assert styles
        assert all(color in style for style in styles)


def test_format_cursor_readout_defaults_unknown_mode_to_insert_color() -> None:
    text = format_cursor_readout(3, 12, vim_mode="some-unknown-mode")
    styles = _digit_styles(text, "3", "12")
    assert styles
    assert all(CURSOR_READOUT_MODE_COLORS["insert"] in style for style in styles)


def test_format_cursor_readout_keeps_labels_dim() -> None:
    text = format_cursor_readout(3, 12, vim_mode="normal")
    label_spans = [
        span
        for span in text.spans
        if text.plain[span.start : span.end] in ("Ln ", ", ", "Col ")
    ]
    assert label_spans
    assert all(str(span.style) == "dim" for span in label_spans)


def test_cursor_readout_cell_width_matches_rendered_text() -> None:
    for line, column in [(1, 1), (12, 9), (100, 999)]:
        text = format_cursor_readout(line, column, vim_mode="insert")
        assert cursor_readout_cell_width(line, column) == cell_len(text.plain)
