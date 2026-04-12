"""Tests for PromptTextArea NORMAL-mode ~ (toggle case) command."""

from sase.ace.testing import PromptPage


# =============================================================================
# Basic toggle case tests
# =============================================================================


async def test_toggle_lowercase_to_uppercase() -> None:
    """~ toggles a lowercase letter to uppercase."""
    async with PromptPage("hello") as page:
        await page.press("~")
        assert page.text == "Hello"
        assert page.cursor == (0, 1)


async def test_toggle_uppercase_to_lowercase() -> None:
    """~ toggles an uppercase letter to lowercase."""
    async with PromptPage("HELLO") as page:
        await page.press("~")
        assert page.text == "hELLO"
        assert page.cursor == (0, 1)


async def test_toggle_non_alpha_advances_cursor() -> None:
    """~ on a non-alphabetic character advances the cursor without change."""
    async with PromptPage("1abc") as page:
        await page.press("~")
        assert page.text == "1abc"
        assert page.cursor == (0, 1)


async def test_toggle_at_end_of_line_is_noop() -> None:
    """~ at the end of a line does nothing."""
    async with PromptPage("hi", cursor=(0, 2)) as page:
        await page.press("~")
        assert page.text == "hi"
        assert page.cursor == (0, 2)


async def test_toggle_mid_word() -> None:
    """~ in the middle of a word toggles that character."""
    async with PromptPage("heLLo", cursor=(0, 2)) as page:
        await page.press("~")
        assert page.text == "helLo"
        assert page.cursor == (0, 3)


# =============================================================================
# Count support
# =============================================================================


async def test_toggle_with_count() -> None:
    """3~ toggles three characters."""
    async with PromptPage("hello") as page:
        await page.press("3", "~")
        assert page.text == "HELlo"
        assert page.cursor == (0, 3)


async def test_toggle_count_clamps_to_line_end() -> None:
    """Count larger than remaining chars clamps to end of line."""
    async with PromptPage("Hi") as page:
        await page.press("9", "~")
        assert page.text == "hI"
        assert page.cursor == (0, 2)


# =============================================================================
# Dot-repeat
# =============================================================================


async def test_dot_repeats_toggle_case() -> None:
    """Dot repeats ~."""
    async with PromptPage("abcdef") as page:
        await page.press("~")
        assert page.text == "Abcdef"
        assert page.cursor == (0, 1)

        await page.press(".")
        assert page.text == "ABcdef"
        assert page.cursor == (0, 2)
