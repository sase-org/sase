"""Placeholder completion and highlighting in ``PromptTextArea``."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
    _editor_position_for_offset,
    _editor_position_to_offset,
    build_placeholder_completion_result,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


def test_builder_maps_utf16_ranges_to_python_offsets() -> None:
    text = "😀 <Alpha> use <A>"
    result = build_placeholder_completion_result(text, text.index("A>", 10) + 1)

    assert result is not None
    assert result.prefix == "A"
    assert (result.replacement_start, result.replacement_end) == (
        text.rindex("<") + 1,
        text.rindex(">"),
    )
    assert [candidate.insertion for candidate in result.candidates] == ["Alpha"]

    position = _editor_position_for_offset(text, text.index("<"))
    assert position is not None
    assert position.character == 3
    assert _editor_position_to_offset(text, position) == text.index("<")


async def test_typing_open_bracket_auto_opens_and_live_narrows() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> and <alpine> then ")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("<")

        assert ta._completion_kind == PLACEHOLDER_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == [
            "alpha",
            "alpine",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "placeholder"
        assert "<> alpha" in panel.render().plain  # type: ignore[union-attr]

        await pilot.press("a", "l", "p", "h")

        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["alpha"]


async def test_accept_replaces_inner_text_with_and_without_closing_bracket() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> then <a>")
        ta.cursor_location = (0, len(ta.text) - 1)
        assert ta._try_auto_placeholder_completion() is True

        await pilot.press("enter")

        assert ta.text == "Use <alpha> then <alpha>"
        assert ta.cursor_location == (0, len(ta.text))

        ta.load_text("Use <alpha> then <a")
        ta.cursor_location = (0, len(ta.text))
        assert ta._try_auto_placeholder_completion() is True

        await pilot.press("enter")

        assert ta.text == "Use <alpha> then <alpha>"
        assert ta.cursor_location == (0, len(ta.text))


async def test_placeholder_free_prompt_stays_silent() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("<")

        assert ta.text == "<"
        assert ta._file_completion_active is False
        assert ta._file_completion_candidates == []


async def test_ctrl_t_explicitly_accepts_single_placeholder_with_auto_off() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> then <a")
        ta.cursor_location = (0, len(ta.text))

        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto="off"),
        ):
            await pilot.press("ctrl+t")

        assert ta.text == "Use <alpha> then <alpha>"
        assert ta._file_completion_active is False


async def test_snippet_tabstop_opens_completion_and_survives_accept() -> None:
    app = CompletionTestApp(snippets={"cbi": "`<$1>`$0"})
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Reuse <alpha>: cbi")
        ta.cursor_location = (0, len(ta.text))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda self: app),
        ):
            await pilot.press("tab")

            assert ta.text == "Reuse <alpha>: `<>`"
            assert ta._completion_kind == PLACEHOLDER_COMPLETION_KIND
            assert ta._file_completion_active is True
            assert ta.cursor_location == (0, ta.text.rindex("<") + 1)

            await pilot.press("enter")

            assert ta.text == "Reuse <alpha>: `<alpha>`"
            assert ta.cursor_location == (0, ta.text.rindex(">") + 1)

            await pilot.press("tab")

            assert ta.cursor_location == (0, len(ta.text))


async def test_placeholder_highlight_uses_cached_rust_spans() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use `<alpha>` and <beta>")
        ta._build_highlight_map()

        names = _highlight_names(ta)
        assert names.count("placeholder.delimiter") >= 4
        assert names.count("placeholder.inner") >= 2
        assert "placeholder.delimiter" in ta._theme.syntax_styles
        assert "placeholder.inner" in ta._theme.syntax_styles

        cached = ta._placeholder_cached_spans
        ta._build_highlight_map()
        assert ta._placeholder_cached_spans is cached

        ta.load_text("Use <gamma>")
        ta._build_highlight_map()
        assert ta._placeholder_cached_spans is not cached
