"""Leading ordered-marker detection and ``PromptTextArea`` overlay coverage."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rich.color import Color
from rich.style import Style

from sase.ace.tui.widgets import _bullet_highlight
from sase.ace.tui.widgets._bullet_highlight import (
    _bullet_dash_color,
    _ordered_marker_spans,
)
from sase.ace.tui.widgets._jinja_highlight import (
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


def _highlight_names(text_area: PromptTextArea) -> list[str]:
    return [name for row in text_area._highlights.values() for *_range, name in row]


@pytest.mark.parametrize(
    ("text", "expected_markers"),
    [
        ("1. item", 1),
        ("  12) nested item", 1),
        ("       3. deeply indented", 1),
        ("1. one\n2. two\n3. three", 3),
        ("intro\n1. first\nplain line\n  2. second", 2),
        ("0. zero-numbered item", 1),
        ("999999999. nine nines", 1),
        # Not markers: mid-prose digits, one digit too many, tight markers,
        # missing space, tab indent.
        ("The report from 2024. is attached", 0),
        ("1234567890. ten digits is one too many", 0),
        ("1.tight", 0),
        ("1)", 0),
        ("\t1. tab indent is not a space marker", 0),
    ],
)
def test_ordered_marker_contract(text: str, expected_markers: int) -> None:
    spans = _ordered_marker_spans(text)

    assert len(spans) == expected_markers
    # Every reported span covers exactly the digits and delimiter.
    assert all(text[start:end].rstrip(".)").isdigit() for start, end in spans)
    assert all(text[start:end][-1] in ".)" for start, end in spans)


def test_ordered_marker_only_spans_digits_and_delimiter_not_indent_or_space() -> None:
    text = "  12) buy milk"

    ((start, end),) = _ordered_marker_spans(text)

    assert (start, end) == (2, 5)
    assert text[start:end] == "12)"


def test_ordered_marker_fast_path_and_overlay_ceilings() -> None:
    with patch.object(_bullet_highlight, "_scan_ordered_marker_spans") as scan:
        assert _ordered_marker_spans("no ordered markers here at all") == ()
    scan.assert_not_called()

    oversized_bytes = "é" * (_MAX_OVERLAY_BYTES // 2 + 1) + "\n1. late marker"
    oversized_lines = "1. b\n" * (_MAX_OVERLAY_LINES + 2)
    assert _ordered_marker_spans(oversized_bytes) == ()
    assert _ordered_marker_spans(oversized_lines) == ()


def test_ordered_marker_empty_prompt() -> None:
    assert _ordered_marker_spans("") == ()


async def test_ordered_marker_overlay_uses_utf8_byte_columns_and_coexists_with_syntax() -> (
    None
):
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text(
            "🚀 café résumé header\n"
            "1. fix #gh:sase {% if root %}now{% endif %}\n"
            "  2. run the migration first"
        )
        text_area._build_highlight_map()

        # Leading markers map to byte columns 0-2 (flush) and 2-4 (two-space
        # indent), even though the prompt opens with multibyte characters on
        # line 0.
        assert (0, 2, "bullet.ordered") in text_area._highlights[1]
        assert (2, 4, "bullet.ordered") in text_area._highlights[2]

        # The marker overlay coexists with xprompt/jinja spans on the same line.
        names = _highlight_names(text_area)
        for name in ("bullet.ordered", "xprompt.invocation", "jinja.delimiter"):
            assert name in names


async def test_ordered_marker_overlay_wins_base_marker_but_yields_to_search_and_yank() -> (
    None
):
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("1. run `make` now")
        text_area._set_search_highlights(((0, 2),), 0)
        text_area._yank_flash_span = (0, 2)
        text_area._build_highlight_map()

        # Overlay precedence is decided within a row by append order: later
        # spans win the cell. The marker overlays the base list marker and
        # inline code, while the transient search and yank overlays still win
        # on top.
        row0 = [name for *_range, name in text_area._highlights[0]]
        for name in (
            "list.marker",
            "codeblock.inline",
            "bullet.ordered",
            "search.current",
            "yank.flash",
        ):
            assert name in row0
        assert row0.index("list.marker") < row0.index("bullet.ordered")
        assert row0.index("codeblock.inline") < row0.index("bullet.ordered")
        assert row0.index("bullet.ordered") < row0.index("search.current")
        assert row0.index("search.current") < row0.index("yank.flash")


async def test_ordered_marker_overlay_registers_theme_styles_and_updates_on_theme_change() -> (
    None
):
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("1. verify both themes")
        text_area._build_highlight_map()

        assert "bullet.ordered" in _highlight_names(text_area)
        dark_style = text_area._theme.syntax_styles["bullet.ordered"]
        assert dark_style.bold is True
        assert dark_style.bgcolor is None
        # Ordered markers share the dash's exact themed style.
        assert dark_style == text_area._theme.syntax_styles["bullet.dash"]
        expected_dark = _bullet_dash_color(
            app.current_theme.primary,
            app.current_theme.foreground,
        )
        assert dark_style.color == Color.parse(expected_dark.hex)

        text_area._theme.syntax_styles["bullet.ordered"] = Style(color="red")
        app.theme = "textual-light"
        await pilot.pause()

        light_style = text_area._theme.syntax_styles["bullet.ordered"]
        expected_light = _bullet_dash_color(
            app.current_theme.primary,
            app.current_theme.foreground,
        )
        assert light_style.color == Color.parse(expected_light.hex)
        assert light_style.bold is True
        assert light_style != dark_style
