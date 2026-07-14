"""PromptTextArea fenced and inline code highlighting coverage."""

from __future__ import annotations

from rich.color import Color
from rich.style import Style
from textual.app import App, ComposeResult
from textual.widgets.text_area import Selection

from sase.ace.tui.util.code_injection import language_for_info_string
from sase.ace.tui.widgets._codeblock_syntax_highlight import (
    CodeBlockHighlightMixin,
)
from sase.ace.tui.widgets._line_rendering import LineRenderingMixin
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


def _highlight_names(text_area: PromptTextArea) -> list[str]:
    return [name for row in text_area._highlights.values() for *_range, name in row]


class _CodeBlockRenderApp(App[None]):
    CSS = "PromptTextArea { width: 40; height: 8; }"

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        yield PromptTextArea(
            self._text,
            language="markdown",
            soft_wrap=True,
            show_line_numbers=True,
            highlight_cursor_line=True,
        )


def _background_at(text_area: PromptTextArea, y: int, cell: int) -> Color | None:
    cell_strip = text_area.render_line(y).crop(cell, cell + 1)
    for segment in cell_strip._segments:
        if segment.control is None and segment.style is not None:
            return segment.style.bgcolor
    return None


def test_codeblock_info_string_language_aliases_and_unknowns() -> None:
    assert language_for_info_string("py title=demo") == "python"
    assert language_for_info_string("ZSH") == "bash"
    assert language_for_info_string("yml") == "yaml"
    assert language_for_info_string("not-a-parser") is None


async def test_codeblock_overlay_registers_styles_and_injects_python() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text(
            "```python\ndef greet(name):\n    return f'hello {name}'\n```\n"
            "Use `#literal` but expand #active"
        )
        text_area._build_highlight_map()

        names = _highlight_names(text_area)
        for name in (
            "codeblock.fence",
            "codeblock.lang",
            "codeblock.content",
            "codeblock.inline",
            "codeblock.delimiter",
        ):
            assert name in names
            assert name in text_area._theme.syntax_styles
        assert "keyword.function" in names
        assert "function" in names
        assert names.index("codeblock.content") < names.index("xprompt.invocation")

        styles = text_area._theme.syntax_styles
        assert styles["codeblock.content"].color is None
        assert styles["codeblock.content"].bgcolor is not None
        assert styles["codeblock.inline"].bgcolor is not None
        assert not styles["codeblock.fence"].dim
        assert not styles["codeblock.delimiter"].dim
        assert styles["codeblock.lang"].color == Color.parse(app.current_theme.accent)
        assert styles["codeblock.lang"].italic is True
        assert PromptTextArea.__mro__.index(
            CodeBlockHighlightMixin
        ) < PromptTextArea.__mro__.index(LineRenderingMixin)


async def test_codeblock_band_lines_follow_fenced_block_details() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        cases = [
            ("```\nbody\n```", frozenset({0, 1, 2})),
            ("intro\n```\nbody\n", frozenset({1, 2, 3})),
            (
                "```\na\n```\nplain\n~~~sh\nb\n~~~",
                frozenset({0, 1, 2, 4, 5, 6}),
            ),
            ("  ~~~\nvalue\n  ~~~", frozenset({0, 1, 2})),
            ("Use `inline` only", frozenset()),
        ]
        for text, expected in cases:
            text_area.load_text(text)
            text_area._build_highlight_map()
            assert text_area._codeblock_band_lines == expected


async def test_inline_code_pill_tints_delimiters_and_content() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("Use `sase bead` now")
        text_area._build_highlight_map()

        row = text_area._highlights[0]
        assert (4, 15, "codeblock.inline") in row
        assert (4, 5, "codeblock.delimiter") in row
        assert (14, 15, "codeblock.delimiter") in row


async def test_codeblock_band_fills_content_and_preserves_overlays() -> None:
    text = "before\n```\nneedle\n```\nafter"
    app = _CodeBlockRenderApp(text)
    async with app.run_test(size=(50, 12)) as pilot:
        text_area = app.query_one(PromptTextArea)
        text_area.focus()
        text_area._build_highlight_map()
        await pilot.pause()

        gutter_width = text_area.gutter_width
        last_cell = text_area.render_line(2).cell_length - 1
        styles = text_area._theme.syntax_styles
        card_background = styles["codeblock.content"].bgcolor
        gutter_background = text_area._theme.gutter_style.bgcolor
        assert _background_at(text_area, 2, gutter_width - 1) == gutter_background
        assert {
            _background_at(text_area, 2, cell)
            for cell in range(gutter_width, last_cell + 1)
        } == {card_background}

        text_area.selection = Selection((2, 0), (2, 3))
        assert _background_at(text_area, 2, gutter_width) == (
            text_area._theme.selection_style.bgcolor
        )
        assert _background_at(text_area, 2, gutter_width + 4) == card_background

        text_area.selection = Selection.cursor((0, 0))
        text_area._set_search_highlights(((11, 17),), 0, refresh=False)
        text_area._build_highlight_map()
        assert _background_at(text_area, 2, gutter_width) == (
            styles["search.current"].bgcolor
        )
        assert _background_at(text_area, 2, last_cell) == card_background


async def test_codeblock_band_replaces_cursor_line_fill_but_not_cursor() -> None:
    app = _CodeBlockRenderApp("```\nvalue\n```")
    async with app.run_test(size=(50, 12)) as pilot:
        text_area = app.query_one(PromptTextArea)
        text_area.focus()
        text_area.cursor_location = (1, 2)
        text_area._build_highlight_map()
        await pilot.pause()

        gutter_width = text_area.gutter_width
        last_cell = text_area.render_line(1).cell_length - 1
        card_background = text_area._theme.syntax_styles["codeblock.content"].bgcolor
        assert _background_at(text_area, 1, gutter_width) == card_background
        assert _background_at(text_area, 1, last_cell) == card_background
        assert _background_at(text_area, 1, gutter_width + 2) == (
            text_area._theme.cursor_style.bgcolor
        )


async def test_codeblock_overlay_suppresses_other_syntax_inside_literals() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text(
            "```text\n#fenced %auto {{ fenced }}\n```\n`#inline %m:opus {{ inline }}`"
        )
        text_area._build_highlight_map()

        names = _highlight_names(text_area)
        assert any(name.startswith("codeblock.") for name in names)
        assert not any(name.startswith("xprompt.") for name in names)
        assert not any(name.startswith("jinja.") for name in names)


async def test_codeblock_styles_reregister_after_app_theme_switch() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        text_area = app.query_one(PromptTextArea)
        sentinel = Style(bgcolor="red")
        text_area._theme.syntax_styles["codeblock.content"] = sentinel

        app.theme = "textual-light"
        await pilot.pause()

        after = text_area._theme.syntax_styles["codeblock.content"]
        assert after.bgcolor is not None
        assert after != sentinel


async def test_unclosed_fence_tints_to_eof_then_gains_closing_fence() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("```python\nvalue = 1")
        text_area._build_highlight_map()

        open_names = _highlight_names(text_area)
        assert "codeblock.content" in open_names
        assert open_names.count("codeblock.fence") == 1

        text_area.load_text("```python\nvalue = 1\n```")
        text_area._build_highlight_map()

        closed_names = _highlight_names(text_area)
        assert "codeblock.content" in closed_names
        assert closed_names.count("codeblock.fence") == 2


async def test_oversized_block_keeps_tint_but_skips_injection() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        text_area.load_text("```python\nvalue = '" + ("x" * 41_000) + "'\n```")
        text_area._build_highlight_map()

        names = _highlight_names(text_area)
        assert "codeblock.content" in names
        assert "codeblock.fence" in names
        assert "keyword" not in names
        assert "string" not in names


async def test_overlay_caps_disable_codeblock_band() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        text_area = app.query_one(PromptTextArea)
        for text in (
            "```\n" + ("x" * 80_001),
            "```\n" + ("x\n" * 1_201),
        ):
            text_area.load_text(text)
            text_area._build_highlight_map()
            assert text_area._codeblock_band_lines == frozenset()
            assert not any(
                name.startswith("codeblock.") for name in _highlight_names(text_area)
            )
