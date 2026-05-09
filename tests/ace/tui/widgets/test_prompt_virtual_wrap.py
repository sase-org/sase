"""Tests for prompt input virtual wrapping."""

from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual._xterm_parser import XTermParser

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


async def _press_terminal_sequence(pilot: Any, sequence: str) -> None:
    """Send raw terminal input through Textual's xterm parser."""
    driver = pilot._app._driver
    assert driver is not None
    messages = list(XTermParser().feed(sequence))
    assert messages
    for message in messages:
        message.set_sender(pilot._app)
        driver.send_message(message)
    await pilot.pause()


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


async def test_prompt_text_area_resize_resyncs_stale_bar_height() -> None:
    initial = "gamma " * 20 + "tail"
    app = _PromptBarApp(initial)

    async with app.run_test(size=(30, 16)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        text_area = app.query_one(PromptTextArea)
        expected_height = min(
            text_area.wrapped_document.height + 2,
            app.screen.size.height - 2,
        )
        assert expected_height > 3

        bar.styles.height = expected_height - 1

        text_area._on_resize()
        await pilot.pause()

        assert _style_height_value(bar.styles.height) == expected_height


async def test_cursor_line_end_moves_to_physical_line_end_not_wrap_boundary() -> None:
    prompt = "abcdefghijklmnopqrstuvwxyz0123456789"
    app = _PromptBarApp(prompt)

    async with app.run_test(size=(24, 12)) as pilot:
        await pilot.pause()

        text_area = app.query_one(PromptTextArea)
        text_area.move_cursor((0, 5))
        assert text_area.wrapped_document.height > text_area.document.line_count

        text_area.action_cursor_line_end()

        assert text_area.cursor_location == (0, len(prompt))


async def test_cursor_line_start_moves_to_physical_line_start_not_wrap_boundary() -> (
    None
):
    prompt = "abcdefghijklmnopqrstuvwxyz0123456789"
    app = _PromptBarApp(prompt)

    async with app.run_test(size=(24, 12)) as pilot:
        await pilot.pause()

        text_area = app.query_one(PromptTextArea)
        text_area.move_cursor((0, 30))
        assert text_area.wrapped_document.height > text_area.document.line_count

        text_area.action_cursor_line_start()

        assert text_area.cursor_location == (0, 0)


async def test_alt_b_moves_to_previous_word_in_insert_mode() -> None:
    prompt = "alpha beta gamma"
    app = _PromptBarApp(prompt)

    async with app.run_test() as pilot:
        await pilot.pause()

        text_area = app.query_one(PromptTextArea)
        text_area.move_cursor((0, len(prompt)))

        await pilot.press("alt+b")

        assert text_area.cursor_location == (0, prompt.index("gamma"))
        assert text_area.text == prompt
        assert text_area._vim_mode == "insert"


async def test_alt_f_moves_to_next_word_boundary_in_insert_mode() -> None:
    prompt = "alpha beta gamma"
    app = _PromptBarApp(prompt)

    async with app.run_test() as pilot:
        await pilot.pause()

        text_area = app.query_one(PromptTextArea)
        text_area.move_cursor((0, 0))

        await pilot.press("alt+f")

        assert text_area.cursor_location == (0, len("alpha"))
        assert text_area.text == prompt
        assert text_area._vim_mode == "insert"


@pytest.mark.parametrize(
    ("sequence", "start", "expected"),
    [
        ("\x1bb", len("alpha beta gamma"), len("alpha beta ")),
        ("\x1bf", 0, len("alpha")),
    ],
)
async def test_esc_prefixed_word_keys_move_by_word_in_insert_mode(
    sequence: str,
    start: int,
    expected: int,
) -> None:
    prompt = "alpha beta gamma"
    app = _PromptBarApp(prompt)

    async with app.run_test() as pilot:
        await pilot.pause()

        text_area = app.query_one(PromptTextArea)
        text_area.move_cursor((0, start))

        await _press_terminal_sequence(pilot, sequence)

        assert text_area.cursor_location == (0, expected)
        assert text_area.text == prompt
        assert text_area._vim_mode == "insert"


async def test_repeated_cursor_line_end_moves_to_next_physical_line_end() -> None:
    first_line = "alpha"
    second_line = "bravo charlie delta"
    app = _PromptBarApp(f"{first_line}\n{second_line}")

    async with app.run_test(size=(18, 12)) as pilot:
        await pilot.pause()

        text_area = app.query_one(PromptTextArea)
        text_area.move_cursor((0, len(first_line)))

        text_area.action_cursor_line_end()

        assert text_area.cursor_location == (1, len(second_line))


async def test_repeated_cursor_line_start_moves_to_previous_physical_line_start() -> (
    None
):
    first_line = "alpha"
    second_line = "bravo charlie delta"
    app = _PromptBarApp(f"{first_line}\n{second_line}")

    async with app.run_test(size=(18, 12)) as pilot:
        await pilot.pause()

        text_area = app.query_one(PromptTextArea)
        text_area.move_cursor((1, 0))

        text_area.action_cursor_line_start()

        assert text_area.cursor_location == (0, 0)
