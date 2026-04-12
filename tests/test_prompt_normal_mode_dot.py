"""Tests for PromptTextArea NORMAL-mode dot-repeat (.) command."""

from sase.ace.testing import PromptPage


# =============================================================================
# Basic dot-repeat tests
# =============================================================================


async def test_dot_repeats_dw() -> None:
    """Dot repeats dw (delete word)."""
    async with PromptPage("one two three four") as page:
        await page.press("d", "w")
        assert page.text == "two three four"

        await page.press(".")
        assert page.text == "three four"


async def test_dot_repeats_d3w() -> None:
    """Dot repeats d3w (delete 3 words)."""
    async with PromptPage("one two three four five six seven") as page:
        await page.press("d", "3", "w")
        assert page.text == "four five six seven"

        await page.press(".")
        assert page.text == "seven"


async def test_dot_repeats_dd() -> None:
    """Dot repeats dd (delete line)."""
    async with PromptPage("aaa\nbbb\nccc\nddd") as page:
        await page.press("d", "d")
        assert page.text == "bbb\nccc\nddd"

        await page.press(".")
        assert page.text == "ccc\nddd"


async def test_dot_repeats_2dd() -> None:
    """Dot repeats 2dd (delete 2 lines)."""
    async with PromptPage("aaa\nbbb\nccc\nddd\neee\nfff") as page:
        await page.press("2", "d", "d")
        assert page.text == "ccc\nddd\neee\nfff"

        await page.press(".")
        assert page.text == "eee\nfff"


async def test_dot_repeats_D() -> None:
    """Dot repeats D (delete to end of line)."""
    async with PromptPage("hello world\nfoo bar", cursor=(0, 5)) as page:
        await page.press("D")
        assert page.text == "hello\nfoo bar"

        page.cursor = (1, 3)
        await page.press(".")
        assert page.text == "hello\nfoo"


async def test_dot_repeats_de() -> None:
    """Dot repeats de (delete to end of word)."""
    async with PromptPage("one two three") as page:
        await page.press("d", "e")
        assert page.text == " two three"

        await page.press("d", "w")  # overwrite last mutation
        await page.press(".")  # should repeat dw, not de
        assert page.text == "three"


# =============================================================================
# Count with dot
# =============================================================================


async def test_count_dot_repeats_multiple_times() -> None:
    """3. repeats the last mutation 3 times."""
    async with PromptPage("one two three four") as page:
        await page.press("d", "w")
        assert page.text == "two three four"

        await page.press("2", ".")
        assert page.text == "four"


# =============================================================================
# Edge cases
# =============================================================================


async def test_dot_noop_without_prior_mutation() -> None:
    """Dot with no prior mutation is a no-op."""
    async with PromptPage("hello world") as page:
        await page.press(".")
        assert page.text == "hello world"
        assert page.cursor == (0, 0)


async def test_dot_not_overwritten_by_motion() -> None:
    """Pure motions do not overwrite the last mutation."""
    async with PromptPage("one two three four") as page:
        await page.press("d", "w")
        assert page.text == "two three four"

        # Move with pure motions
        await page.press("w", "w")
        # Dot should still repeat dw
        await page.press(".")
        assert page.text == "two three "
