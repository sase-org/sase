"""Tests for PromptTextArea NORMAL-mode dot-repeat (.) command."""

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _TestApp(App[None]):
    """Minimal app for testing PromptTextArea in isolation."""

    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")


# =============================================================================
# Basic dot-repeat tests
# =============================================================================


async def test_dot_repeats_dw() -> None:
    """Dot repeats dw (delete word)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "w")
        assert ta.text == "two three four"

        await pilot.press(".")
        assert ta.text == "three four"


async def test_dot_repeats_d3w() -> None:
    """Dot repeats d3w (delete 3 words)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four five six seven"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "3", "w")
        assert ta.text == "four five six seven"

        await pilot.press(".")
        assert ta.text == "seven"


async def test_dot_repeats_dd() -> None:
    """Dot repeats dd (delete line)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc\nddd"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "d")
        assert ta.text == "bbb\nccc\nddd"

        await pilot.press(".")
        assert ta.text == "ccc\nddd"


async def test_dot_repeats_2dd() -> None:
    """Dot repeats 2dd (delete 2 lines)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc\nddd\neee\nfff"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("2", "d", "d")
        assert ta.text == "ccc\nddd\neee\nfff"

        await pilot.press(".")
        assert ta.text == "eee\nfff"


async def test_dot_repeats_D() -> None:
    """Dot repeats D (delete to end of line)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world\nfoo bar"
        ta.cursor_location = (0, 5)
        ta._enter_normal_mode()

        await pilot.press("D")
        assert ta.text == "hello\nfoo bar"

        ta.cursor_location = (1, 3)
        await pilot.press(".")
        assert ta.text == "hello\nfoo"


async def test_dot_repeats_de() -> None:
    """Dot repeats de (delete to end of word)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "e")
        assert ta.text == " two three"

        await pilot.press("d", "w")  # overwrite last mutation
        await pilot.press(".")  # should repeat dw, not de
        assert ta.text == "three"


# =============================================================================
# Count with dot
# =============================================================================


async def test_count_dot_repeats_multiple_times() -> None:
    """3. repeats the last mutation 3 times."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "w")
        assert ta.text == "two three four"

        await pilot.press("2", ".")
        assert ta.text == "four"


# =============================================================================
# Edge cases
# =============================================================================


async def test_dot_noop_without_prior_mutation() -> None:
    """Dot with no prior mutation is a no-op."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press(".")
        assert ta.text == "hello world"
        assert ta.cursor_location == (0, 0)


async def test_dot_not_overwritten_by_motion() -> None:
    """Pure motions do not overwrite the last mutation."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "w")
        assert ta.text == "two three four"

        # Move with pure motions
        await pilot.press("w", "w")
        # Dot should still repeat dw
        await pilot.press(".")
        assert ta.text == "two three "
