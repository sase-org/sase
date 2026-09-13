"""Tests for the pager ``?`` binding sheet."""

from __future__ import annotations

from sase.pager._help import _pager_help_text


def test_help_lists_goto_line_after_top_bottom() -> None:
    text = _pager_help_text(section_total=1).plain

    assert "; or :" in text
    assert "Jump to a line (1-N)" in text
    assert text.index("g / G") < text.index("; or :") < text.index("backspace")


def test_help_lists_line_addressed_link_landing() -> None:
    text = _pager_help_text(section_total=1).plain

    assert "path:12 / path:12-40 / #L12" in text
    assert "Land on and rail that line; E opens the editor there" in text
    assert text.index("; or :") < text.index("path:12") < text.index("backspace")


def test_help_inserts_section_rows_after_back_and_before_forward() -> None:
    text = _pager_help_text(section_total=3).plain

    assert text.index("; or :") < text.index("backspace")
    assert text.index("backspace") < text.index("ctrl+n / ctrl+p")
    assert text.index("ctrl+n / ctrl+p") < text.index("ctrl+i")
    assert "<tab>" not in text
