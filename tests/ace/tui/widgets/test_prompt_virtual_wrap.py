"""Tests for prompt input virtual wrapping."""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _PromptBarApp(App[None]):
    """Minimal app that hosts a prompt input bar."""

    def __init__(self, initial_value: str = "") -> None:
        super().__init__()
        self._initial_value = initial_value

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._initial_value)


def _style_height_value(value: Any) -> int:
    """Return a numeric height from a Textual style value."""
    scalar_value = getattr(value, "value", value)
    return int(scalar_value)


async def test_prompt_text_area_uses_markdown_soft_wrap() -> None:
    app = _PromptBarApp()

    async with app.run_test(size=(40, 12)):
        text_area = app.query_one(PromptTextArea)

        assert text_area.soft_wrap is True
        assert text_area.language == "markdown"


async def test_typing_past_narrow_width_does_not_insert_newlines() -> None:
    app = _PromptBarApp()
    typed = "abcdefghijklmnopqrstuvwxyz0123456789"

    async with app.run_test(size=(24, 12)) as pilot:
        await pilot.press(*typed)
        await pilot.pause()

        text_area = app.query_one(PromptTextArea)
        assert text_area.text == typed
        assert "\n" not in text_area.text
        assert text_area.wrapped_document.height > text_area.document.line_count


async def test_initial_long_prompt_is_preserved_and_bar_grows_to_wrap() -> None:
    initial = "alpha " * 20 + "omega"
    app = _PromptBarApp(initial)

    async with app.run_test(size=(30, 16)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = app.query_one(PromptTextArea)

        assert text_area.text == initial
        assert "\n" not in text_area.text
        assert bar._get_visual_line_count() == text_area.wrapped_document.height
        assert bar._get_visual_line_count() > text_area.document.line_count
        assert _style_height_value(bar.styles.height) == min(
            text_area.wrapped_document.height + 2,
            app.screen.size.height - 2,
        )


async def test_wrapped_prompt_height_includes_completion_panel() -> None:
    initial = "beta " * 18 + "tail"
    app = _PromptBarApp(initial)

    async with app.run_test(size=(32, 18)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        visual_lines = bar._get_visual_line_count()
        bar._completion_visible = True
        bar._completion_line_count = 4
        bar._update_height()

        assert _style_height_value(bar.styles.height) == min(
            visual_lines + 2 + 4,
            app.screen.size.height - 2,
        )
