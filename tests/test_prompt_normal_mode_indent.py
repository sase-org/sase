"""Tests for PromptTextArea NORMAL-mode indent and dedent operators."""

from sase.ace.testing import PromptPage


async def test_shift_right_indents_current_line() -> None:
    """>> indents the current line by two spaces."""
    async with PromptPage("aaa\nbbb", cursor=(1, 0)) as page:
        await page.press(">", ">")

        assert page.text == "aaa\n  bbb"
        assert page.cursor == (1, 2)


async def test_counted_shift_right_indents_multiple_lines() -> None:
    """2>> indents the current line and the next line."""
    async with PromptPage("aaa\nbbb\nccc") as page:
        await page.press("2", ">", ">")

        assert page.text == "  aaa\n  bbb\nccc"
        assert page.cursor == (0, 2)


async def test_shift_left_dedents_up_to_one_unit() -> None:
    """<< removes up to one two-space indent unit."""
    async with PromptPage("    aaa\n bbb\nccc") as page:
        await page.press("<", "<")
        page.cursor = (1, 0)
        await page.press("<", "<")
        page.cursor = (2, 0)
        await page.press("<", "<")

        assert page.text == "  aaa\nbbb\nccc"


async def test_shift_right_with_line_motion() -> None:
    """>j indents the current line and the line below."""
    async with PromptPage("aaa\nbbb\nccc") as page:
        await page.press(">", "j")

        assert page.text == "  aaa\n  bbb\nccc"
        assert page.cursor == (0, 2)


async def test_shift_right_is_dot_repeatable() -> None:
    """>> can be repeated with dot."""
    async with PromptPage("aaa") as page:
        await page.press(">", ">")
        await page.press(".")

        assert page.text == "    aaa"
        assert page.cursor == (0, 4)


async def test_indent_operator_with_text_object_indents_touched_line() -> None:
    """>iw indents the line containing the text object."""
    async with PromptPage("hello world", cursor=(0, 6)) as page:
        await page.press(">", "i", "w")

        assert page.text == "  hello world"
        assert page.cursor == (0, 2)
