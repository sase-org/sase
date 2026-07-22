"""Leading bullet-dash detection and ``PromptTextArea`` overlay coverage."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rich.color import Color
from rich.style import Style

from sase.ace.tui.widgets import _bullet_highlight
from sase.ace.tui.widgets._bullet_highlight import (
    _bullet_dash_color,
    _bullet_dash_spans,
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
    ("text", "expected_dashes"),
    [
        ("- item", 1),
        ("  - nested item", 1),
        ("       - deeply indented", 1),
        ("- one\n- two\n- three", 3),
        ("intro\n- first\nplain line\n  - second", 2),
        # Not bullets: mid-line dashes, rules, tight dashes, missing space.
        ("text - dash", 0),
        ("a-b - c", 0),
        ("--- horizontal rule", 0),
        ("-- en dash start", 0),
        ("-tight", 0),
        ("-", 0),
        ("\t- tab indent is not a space bullet", 0),
    ],
)
def test_bullet_dash_contract(text: str, expected_dashes: int) -> None:
    spans = _bullet_dash_spans(text)

    assert len(spans) == expected_dashes
    # Every reported span covers exactly one dash character.
    assert all(text[start:end] == "-" for start, end in spans)


def test_bullet_dash_only_spans_the_dash_not_indent_or_space() -> None:
    text = "  - buy milk"

    ((start, end),) = _bullet_dash_spans(text)

    assert (start, end) == (2, 3)
    assert text[start:end] == "-"


def test_bullet_dash_fast_path_and_overlay_ceilings() -> None:
    with patch.object(_bullet_highlight, "_scan_bullet_dash_spans") as scan:
        assert _bullet_dash_spans("no bullet dashes here at all") == ()
    scan.assert_not_called()

    oversized_bytes = "é" * (_MAX_OVERLAY_BYTES // 2 + 1) + "\n- late bullet"
    oversized_lines = "- b\n" * (_MAX_OVERLAY_LINES + 2)
    assert _bullet_dash_spans(oversized_bytes) == ()
    assert _bullet_dash_spans(oversized_lines) == ()


def test_bullet_dash_empty_prompt() -> None:
    assert _bullet_dash_spans("") == ()


@pytest.mark.parametrize(
    ("primary", "foreground", "expected"),
    [
        # Dark theme: lift the primary blue toward near-white so it pops.
        ("#205EA6", "#FFFCF0", "#628DBC"),
        # Light theme: lift toward near-black so it stays legible.
        ("#205EA6", "#000000", "#164174"),
        # No foreground available: fall back to the raw primary hue.
        ("#205EA6", None, "#205EA6"),
        # No primary available: fall back to the flexoki primary blue.
        (None, None, "#205EA6"),
    ],
)
def test_bullet_dash_color_lifts_primary_toward_foreground(
    primary: str | None,
    foreground: str | None,
    expected: str,
) -> None:
    assert _bullet_dash_color(primary, foreground).hex == expected


async def test_bullet_overlay_uses_utf8_byte_columns_and_coexists_with_syntax() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text(
            "🚀 café résumé header\n"
            "- fix #gh:sase {% if root %}now{% endif %}\n"
            "  - run the migration first"
        )
        text_area._build_highlight_map()

        # Leading dashes map to byte column 0 (flush) and 2 (two-space indent),
        # even though the prompt opens with multibyte characters on line 0.
        assert (0, 1, "bullet.dash") in text_area._highlights[1]
        assert (2, 3, "bullet.dash") in text_area._highlights[2]

        # The dash overlay coexists with xprompt/jinja spans on the same line.
        names = _highlight_names(text_area)
        for name in ("bullet.dash", "xprompt.invocation", "jinja.delimiter"):
            assert name in names


async def test_bullet_overlay_wins_base_marker_but_yields_to_search_and_yank() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("- run `make` now")
        text_area._set_search_highlights(((0, 1),), 0)
        text_area._yank_flash_span = (0, 1)
        text_area._build_highlight_map()

        # Overlay precedence is decided within a row by append order: later
        # spans win the cell. The dash overlays the base list marker and inline
        # code, while the transient search and yank overlays still win on top.
        row0 = [name for *_range, name in text_area._highlights[0]]
        for name in (
            "list.marker",
            "codeblock.inline",
            "bullet.dash",
            "search.current",
            "yank.flash",
        ):
            assert name in row0
        assert row0.index("list.marker") < row0.index("bullet.dash")
        assert row0.index("codeblock.inline") < row0.index("bullet.dash")
        assert row0.index("bullet.dash") < row0.index("search.current")
        assert row0.index("search.current") < row0.index("yank.flash")


async def test_bullet_overlay_registers_theme_styles_and_updates_on_theme_change() -> (
    None
):
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("- verify both themes")
        text_area._build_highlight_map()

        assert "bullet.dash" in _highlight_names(text_area)
        dark_style = text_area._theme.syntax_styles["bullet.dash"]
        assert dark_style.bold is True
        assert dark_style.bgcolor is None
        expected_dark = _bullet_dash_color(
            app.current_theme.primary,
            app.current_theme.foreground,
        )
        assert dark_style.color == Color.parse(expected_dark.hex)

        text_area._theme.syntax_styles["bullet.dash"] = Style(color="red")
        app.theme = "textual-light"
        await pilot.pause()

        light_style = text_area._theme.syntax_styles["bullet.dash"]
        expected_light = _bullet_dash_color(
            app.current_theme.primary,
            app.current_theme.foreground,
        )
        assert light_style.color == Color.parse(expected_light.hex)
        assert light_style.bold is True
        assert light_style != dark_style
