"""Tests for PromptTextArea NORMAL-mode delete operators (d<motion>, D, d^)."""

from sase.ace.testing import PromptPage


# =============================================================================
# d<motion> operator tests
# =============================================================================


async def test_dd_deletes_current_line() -> None:
    """dd deletes the current line."""
    async with PromptPage("aaa\nbbb\nccc", cursor=(1, 0)) as page:
        await page.press("d", "d")
        assert page.text == "aaa\nccc"
        assert page.cursor == (1, 0)
        assert page.mode == "normal"


async def test_2dd_deletes_two_lines() -> None:
    """2dd deletes 2 lines starting from cursor."""
    async with PromptPage("aaa\nbbb\nccc\nddd", cursor=(1, 0)) as page:
        await page.press("2", "d", "d")
        assert page.text == "aaa\nddd"
        assert page.cursor == (1, 0)


async def test_dd_last_line() -> None:
    """dd on the last line removes it and moves cursor up."""
    async with PromptPage("aaa\nbbb\nccc", cursor=(2, 0)) as page:
        await page.press("d", "d")
        assert page.text == "aaa\nbbb"
        assert page.cursor == (1, 0)


async def test_dd_only_line() -> None:
    """dd on the only line clears the document."""
    async with PromptPage("hello") as page:
        await page.press("d", "d")
        assert page.text == ""
        assert page.cursor == (0, 0)


async def test_dw_deletes_word() -> None:
    """dw deletes from cursor to start of next word."""
    async with PromptPage("one two three") as page:
        await page.press("d", "w")
        assert page.text == "two three"
        assert page.cursor == (0, 0)


async def test_d3w_deletes_three_words() -> None:
    """d3w deletes the next 3 words."""
    async with PromptPage("one two three four five") as page:
        await page.press("d", "3", "w")
        assert page.text == "four five"
        assert page.cursor == (0, 0)


async def test_d3W_deletes_three_WORDS() -> None:
    """d3W deletes the next 3 WORDs."""
    async with PromptPage("one two three four five") as page:
        await page.press("d", "3", "W")
        assert page.text == "four five"
        assert page.cursor == (0, 0)


async def test_2dw_with_count_on_operator() -> None:
    """2dw (count on operator) deletes 2 words."""
    async with PromptPage("one two three four") as page:
        await page.press("2", "d", "w")
        assert page.text == "three four"
        assert page.cursor == (0, 0)


async def test_de_deletes_to_end_of_word() -> None:
    """de deletes to end of word (inclusive)."""
    async with PromptPage("hello world") as page:
        await page.press("d", "e")
        assert page.text == " world"
        assert page.cursor == (0, 0)


async def test_db_deletes_backward_word() -> None:
    """db deletes backward to start of previous word."""
    async with PromptPage("one two three", cursor=(0, 8)) as page:
        await page.press("d", "b")
        assert page.text == "one three"
        assert page.cursor == (0, 4)


async def test_d_dollar_deletes_to_end_of_line() -> None:
    """d$ deletes from cursor to end of line."""
    async with PromptPage("hello world", cursor=(0, 5)) as page:
        await page.press("d", "$")
        assert page.text == "hello"
        assert page.cursor == (0, 5)


async def test_d0_deletes_to_start_of_line() -> None:
    """d0 deletes from cursor to start of line."""
    async with PromptPage("hello world", cursor=(0, 6)) as page:
        await page.press("d", "0")
        assert page.text == "world"
        assert page.cursor == (0, 0)


async def test_dj_deletes_current_and_next_line() -> None:
    """dj deletes current line and the line below (linewise)."""
    async with PromptPage("aaa\nbbb\nccc\nddd", cursor=(1, 0)) as page:
        await page.press("d", "j")
        assert page.text == "aaa\nddd"
        assert page.cursor == (1, 0)


async def test_dk_deletes_current_and_above_line() -> None:
    """dk deletes current line and the line above (linewise)."""
    async with PromptPage("aaa\nbbb\nccc\nddd", cursor=(2, 0)) as page:
        await page.press("d", "k")
        assert page.text == "aaa\nddd"
        assert page.cursor == (1, 0)


async def test_dG_deletes_to_end_of_document() -> None:
    """dG deletes from current line to end of document."""
    async with PromptPage("aaa\nbbb\nccc\nddd", cursor=(2, 0)) as page:
        await page.press("d", "G")
        assert page.text == "aaa\nbbb"
        assert page.cursor == (1, 0)


async def test_dgg_deletes_to_top_of_document() -> None:
    """dgg deletes from current line to top of document."""
    async with PromptPage("aaa\nbbb\nccc\nddd", cursor=(2, 0)) as page:
        await page.press("d", "g", "g")
        assert page.text == "ddd"
        assert page.cursor == (0, 0)


async def test_dl_deletes_character_at_cursor() -> None:
    """dl deletes the character at cursor (like x)."""
    async with PromptPage("abcde", cursor=(0, 2)) as page:
        await page.press("d", "l")
        assert page.text == "abde"
        assert page.cursor == (0, 2)


async def test_dh_deletes_character_before_cursor() -> None:
    """dh deletes the character before cursor."""
    async with PromptPage("abcde", cursor=(0, 2)) as page:
        await page.press("d", "h")
        assert page.text == "acde"
        assert page.cursor == (0, 1)


# =============================================================================
# D (delete to end of line) tests
# =============================================================================


async def test_D_deletes_to_end_of_line() -> None:
    """D deletes from cursor to end of line."""
    async with PromptPage("hello world", cursor=(0, 5)) as page:
        await page.press("D")
        assert page.text == "hello"
        assert page.mode == "normal"


async def test_D_at_start_of_line_deletes_entire_line_content() -> None:
    """D from column 0 deletes all content on the line."""
    async with PromptPage("aaa\nbbb\nccc", cursor=(1, 0)) as page:
        await page.press("D")
        assert page.text == "aaa\n\nccc"
        assert page.cursor == (1, 0)


async def test_D_at_end_of_line_is_noop() -> None:
    """D at end of line deletes nothing."""
    async with PromptPage("hello", cursor=(0, 5)) as page:
        await page.press("D")
        assert page.text == "hello"
        assert page.mode == "normal"


# =============================================================================
# d^ (delete to first non-whitespace) test
# =============================================================================


async def test_d_caret_deletes_to_first_nonwhitespace() -> None:
    """d^ deletes from cursor to first non-whitespace character."""
    async with PromptPage("    hello", cursor=(0, 7)) as page:
        await page.press("d", "^")
        assert page.text == "    lo"
        assert page.cursor == (0, 4)
