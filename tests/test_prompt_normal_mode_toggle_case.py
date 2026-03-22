"""Tests for PromptTextArea NORMAL-mode ~ (toggle case) command."""

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _TestApp(App[None]):
    """Minimal app for testing PromptTextArea in isolation."""

    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")


# =============================================================================
# Basic toggle case tests
# =============================================================================


async def test_toggle_lowercase_to_uppercase() -> None:
    """~ toggles a lowercase letter to uppercase."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("~")
        assert ta.text == "Hello"
        assert ta.cursor_location == (0, 1)


async def test_toggle_uppercase_to_lowercase() -> None:
    """~ toggles an uppercase letter to lowercase."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "HELLO"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("~")
        assert ta.text == "hELLO"
        assert ta.cursor_location == (0, 1)


async def test_toggle_non_alpha_advances_cursor() -> None:
    """~ on a non-alphabetic character advances the cursor without change."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "1abc"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("~")
        assert ta.text == "1abc"
        assert ta.cursor_location == (0, 1)


async def test_toggle_at_end_of_line_is_noop() -> None:
    """~ at the end of a line does nothing."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hi"
        ta.cursor_location = (0, 2)
        ta._enter_normal_mode()

        await pilot.press("~")
        assert ta.text == "hi"
        assert ta.cursor_location == (0, 2)


async def test_toggle_mid_word() -> None:
    """~ in the middle of a word toggles that character."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "heLLo"
        ta.cursor_location = (0, 2)
        ta._enter_normal_mode()

        await pilot.press("~")
        assert ta.text == "helLo"
        assert ta.cursor_location == (0, 3)


# =============================================================================
# Count support
# =============================================================================


async def test_toggle_with_count() -> None:
    """3~ toggles three characters."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("3", "~")
        assert ta.text == "HELlo"
        assert ta.cursor_location == (0, 3)


async def test_toggle_count_clamps_to_line_end() -> None:
    """Count larger than remaining chars clamps to end of line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "Hi"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("9", "~")
        assert ta.text == "hI"
        assert ta.cursor_location == (0, 2)


# =============================================================================
# Dot-repeat
# =============================================================================


async def test_dot_repeats_toggle_case() -> None:
    """Dot repeats ~."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "abcdef"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("~")
        assert ta.text == "Abcdef"
        assert ta.cursor_location == (0, 1)

        await pilot.press(".")
        assert ta.text == "ABcdef"
        assert ta.cursor_location == (0, 2)
