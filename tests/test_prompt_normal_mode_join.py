"""Tests for PromptTextArea NORMAL-mode J (join lines) command."""

from sase.ace.testing import PromptPage


# =============================================================================
# Basic join tests
# =============================================================================


async def test_join_two_lines() -> None:
    """J joins the current line with the next, inserting a space."""
    async with PromptPage("hello\nworld") as page:
        await page.press("J")
        assert page.text == "hello world"
        assert page.cursor == (0, 5)


async def test_join_strips_leading_whitespace() -> None:
    """J strips leading whitespace from the joined line."""
    async with PromptPage("hello\n    world") as page:
        await page.press("J")
        assert page.text == "hello world"
        assert page.cursor == (0, 5)


async def test_join_strips_trailing_whitespace() -> None:
    """J strips trailing whitespace from the current line."""
    async with PromptPage("hello   \nworld") as page:
        await page.press("J")
        assert page.text == "hello world"
        assert page.cursor == (0, 5)


async def test_join_on_last_line_is_noop() -> None:
    """J on the last line does nothing."""
    async with PromptPage("only line") as page:
        await page.press("J")
        assert page.text == "only line"


async def test_join_empty_next_line() -> None:
    """J with an empty next line just removes the newline."""
    async with PromptPage("hello\n\nworld") as page:
        await page.press("J")
        assert page.text == "hello\nworld"


# =============================================================================
# Count support
# =============================================================================


async def test_join_with_count() -> None:
    """3J joins three lines together."""
    async with PromptPage("one\ntwo\nthree\nfour") as page:
        await page.press("3", "J")
        assert page.text == "one two three\nfour"
        assert page.cursor[0] == 0


async def test_join_with_count_exceeding_lines() -> None:
    """Count larger than remaining lines joins as many as possible."""
    async with PromptPage("one\ntwo\nthree") as page:
        await page.press("9", "J")
        assert page.text == "one two three"


# =============================================================================
# Dot-repeat
# =============================================================================


async def test_dot_repeats_join() -> None:
    """Dot repeats J."""
    async with PromptPage("aaa\nbbb\nccc\nddd") as page:
        await page.press("J")
        assert page.text == "aaa bbb\nccc\nddd"

        await page.press(".")
        assert page.text == "aaa bbb ccc\nddd"


# =============================================================================
# Virtual-wrap integration
# =============================================================================


async def test_join_does_not_create_background_formatter_state() -> None:
    """J edits text directly; prompt wrapping remains visual-only."""
    async with PromptPage("hello\nworld") as page:
        await page.press("J")
        assert page.text == "hello world"
        assert not hasattr(page.ta, "_format_with_prettier")
        assert not hasattr(page.ta, "_prettier_format_task")
