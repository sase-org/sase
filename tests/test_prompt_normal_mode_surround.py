"""Tests for PromptTextArea NORMAL-mode vim-surround ``ys`` support."""

from sase.ace.testing import PromptPage


async def test_ys_counted_word_motion_wraps_words_without_trailing_space() -> None:
    async with PromptPage("Some piece of text goes here.", cursor=(0, 5)) as page:
        await page.press("y", "s", "3", "w", '"')

        assert page.text == 'Some "piece of text" goes here.'


async def test_ys_inner_word_wraps_text_object() -> None:
    async with PromptPage("hello world foo", cursor=(0, 7)) as page:
        await page.press("y", "s", "i", "w", "'")

        assert page.text == "hello 'world' foo"


async def test_ys_inner_word_accepts_bracket_pair() -> None:
    async with PromptPage("hello world", cursor=(0, 6)) as page:
        await page.press("y", "s", "i", "w", ")")

        assert page.text == "hello (world)"


async def test_yss_wraps_current_line() -> None:
    async with PromptPage("aaa\nbbb\nccc", cursor=(1, 1)) as page:
        await page.press("y", "s", "s", '"')

        assert page.text == 'aaa\n"bbb"\nccc'


async def test_ys_is_dot_repeatable() -> None:
    async with PromptPage("one two three") as page:
        await page.press("y", "s", "w", '"')
        page.cursor = (0, 6)

        await page.press(".")

        assert page.text == '"one" "two" three'
