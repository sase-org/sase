"""Tests for PromptTextArea NORMAL-mode gu/gU/g~ case operators."""

from sase.ace.testing import PromptPage


async def test_gu_inner_word_lowercases_text_object() -> None:
    """guiw lowercases the word under the cursor."""
    async with PromptPage("Hello WORLD", cursor=(0, 7)) as page:
        await page.press("g", "u", "i", "w")

        assert page.text == "Hello world"
        assert page.cursor == (0, 6)


async def test_gU_to_line_end_uppercases_range() -> None:
    """gU$ uppercases from cursor to end of line."""
    async with PromptPage("hello mixed case", cursor=(0, 6)) as page:
        await page.press("g", "U", "$")

        assert page.text == "hello MIXED CASE"
        assert page.cursor == (0, 6)


async def test_g_tilde_word_toggles_case() -> None:
    """g~w toggles case through the next word start."""
    async with PromptPage("ab cd") as page:
        await page.press("g", "~", "w")

        assert page.text == "AB cd"
        assert page.cursor == (0, 0)


async def test_case_line_forms() -> None:
    """guu, gUU, and g~~ transform whole lines."""
    async with PromptPage("AAA\nbbb\nCcC") as page:
        await page.press("g", "u", "u")
        page.cursor = (1, 0)
        await page.press("g", "U", "U")
        page.cursor = (2, 0)
        await page.press("g", "~", "~")

        assert page.text == "aaa\nBBB\ncCc"


async def test_counted_case_line_form_lowercases_multiple_lines() -> None:
    """2guu lowercases the current line and the next line."""
    async with PromptPage("AAA\nBBB\nCCC") as page:
        await page.press("2", "g", "u", "u")

        assert page.text == "aaa\nbbb\nCCC"
        assert page.cursor == (0, 0)


async def test_case_operator_is_dot_repeatable() -> None:
    """Dot repeats the previous case operator."""
    async with PromptPage("one two") as page:
        await page.press("g", "U", "w")
        page.cursor = (0, 4)
        await page.press(".")

        assert page.text == "ONE TWO"
        assert page.cursor == (0, 4)
