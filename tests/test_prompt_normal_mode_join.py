"""Tests for PromptTextArea NORMAL-mode J (join lines) command."""

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _TestApp(App[None]):
    """Minimal app for testing PromptTextArea in isolation."""

    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")


# =============================================================================
# Basic join tests
# =============================================================================


async def test_join_two_lines() -> None:
    """J joins the current line with the next, inserting a space."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello\nworld"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("J")
        assert ta.text == "hello world"
        assert ta.cursor_location == (0, 5)


async def test_join_strips_leading_whitespace() -> None:
    """J strips leading whitespace from the joined line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello\n    world"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("J")
        assert ta.text == "hello world"
        assert ta.cursor_location == (0, 5)


async def test_join_strips_trailing_whitespace() -> None:
    """J strips trailing whitespace from the current line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello   \nworld"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("J")
        assert ta.text == "hello world"
        assert ta.cursor_location == (0, 5)


async def test_join_on_last_line_is_noop() -> None:
    """J on the last line does nothing."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "only line"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("J")
        assert ta.text == "only line"


async def test_join_empty_next_line() -> None:
    """J with an empty next line just removes the newline."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello\n\nworld"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("J")
        assert ta.text == "hello\nworld"


# =============================================================================
# Count support
# =============================================================================


async def test_join_with_count() -> None:
    """3J joins three lines together."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one\ntwo\nthree\nfour"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("3", "J")
        assert ta.text == "one two three\nfour"
        assert ta.cursor_location[0] == 0


async def test_join_with_count_exceeding_lines() -> None:
    """Count larger than remaining lines joins as many as possible."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one\ntwo\nthree"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("9", "J")
        assert ta.text == "one two three"


# =============================================================================
# Dot-repeat
# =============================================================================


async def test_dot_repeats_join() -> None:
    """Dot repeats J."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc\nddd"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("J")
        assert ta.text == "aaa bbb\nccc\nddd"

        await pilot.press(".")
        assert ta.text == "aaa bbb ccc\nddd"
