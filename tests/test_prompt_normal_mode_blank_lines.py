"""Tests for PromptTextArea NORMAL-mode blank-line commands."""

from textual.app import App, ComposeResult

from sase.ace.testing import PromptPage
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


async def test_blank_line_below_keeps_cursor_and_normal_mode() -> None:
    async with PromptPage("alpha\nbeta", cursor=(0, 2)) as page:
        await page.press("]", "space")
        assert page.text == "alpha\n\nbeta"
        assert page.cursor == (0, 2)
        assert page.mode == "normal"


async def test_blank_line_above_tracks_original_content_line() -> None:
    async with PromptPage("alpha\nbeta", cursor=(1, 3)) as page:
        await page.press("[", "space")
        assert page.text == "alpha\n\nbeta"
        assert page.cursor == (2, 3)
        assert page.mode == "normal"


async def test_blank_line_below_supports_count() -> None:
    async with PromptPage("alpha\nbeta", cursor=(0, 1)) as page:
        await page.press("3", "]", "space")
        assert page.text == "alpha\n\n\n\nbeta"
        assert page.cursor == (0, 1)


async def test_blank_line_above_supports_count() -> None:
    async with PromptPage("alpha\nbeta", cursor=(1, 1)) as page:
        await page.press("2", "[", "space")
        assert page.text == "alpha\n\n\nbeta"
        assert page.cursor == (3, 1)


async def test_blank_line_above_first_line() -> None:
    async with PromptPage("alpha\nbeta", cursor=(0, 4)) as page:
        await page.press("[", "space")
        assert page.text == "\nalpha\nbeta"
        assert page.cursor == (1, 4)


async def test_blank_line_below_last_line() -> None:
    async with PromptPage("alpha\nbeta", cursor=(1, 2)) as page:
        await page.press("]", "space")
        assert page.text == "alpha\nbeta\n"
        assert page.cursor == (1, 2)


async def test_blank_line_commands_handle_empty_buffer() -> None:
    async with PromptPage("") as page:
        await page.press("]", "space")
        assert page.text == "\n"
        assert page.cursor == (0, 0)
        assert page.mode == "normal"

    async with PromptPage("") as page:
        await page.press("[", "space")
        assert page.text == "\n"
        assert page.cursor == (1, 0)
        assert page.mode == "normal"


async def test_blank_line_insertion_is_single_undo_step() -> None:
    async with PromptPage("alpha\nbeta", cursor=(0, 2)) as page:
        await page.press("]", "space")
        assert page.text == "alpha\n\nbeta"

        await page.press("u")
        assert page.text == "alpha\nbeta"
        assert page.mode == "normal"


async def test_dot_repeats_blank_line_command() -> None:
    async with PromptPage("alpha\nbeta") as page:
        await page.press("]", "space")
        assert page.text == "alpha\n\nbeta"

        await page.press(".")
        assert page.text == "alpha\n\n\nbeta"
        assert page.mode == "normal"


async def test_unknown_bracket_continuation_is_noop_and_recovers() -> None:
    async with PromptPage("alpha", cursor=(0, 1)) as page:
        await page.press("[", "x")
        assert page.text == "alpha"
        assert page.cursor == (0, 1)
        assert page.ta._pending_keys == ""
        assert page.mode == "normal"

        await page.press("x")
        assert page.text == "apha"
        assert page.cursor == (0, 1)


class _BracketBindingApp(App[None]):
    BINDINGS = [
        ("left_square_bracket", "mark_left", "Left"),
        ("right_square_bracket", "mark_right", "Right"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.triggered: list[str] = []

    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")

    def action_mark_left(self) -> None:
        self.triggered.append("left")

    def action_mark_right(self) -> None:
        self.triggered.append("right")


async def test_bracket_prefix_is_consumed_before_app_bindings() -> None:
    app = _BracketBindingApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "alpha"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()
        ta.focus()

        await pilot.press("right_square_bracket", "space")

        assert ta.text == "alpha\n"
        assert ta.cursor_location == (0, 0)
        assert app.triggered == []

        await pilot.press("left_square_bracket", "space")

        assert ta.text == "\nalpha\n"
        assert ta.cursor_location == (1, 0)
        assert app.triggered == []
