"""Tests for PromptTextArea NORMAL-mode yank, registers, and paste."""

from sase.ace.testing import PromptPage


async def test_yw_yanks_without_modifying_text() -> None:
    """yw yanks to the next word start and leaves the buffer unchanged."""
    async with PromptPage("one two three") as page:
        await page.press("y", "w")

        assert page.text == "one two three"
        assert page.ta._vim_register.text == "one "
        assert page.ta._vim_register.kind == "charwise"
        assert page.cursor == (0, 0)


async def test_yiw_yanks_inner_word_and_moves_to_start() -> None:
    """yiw yanks the word under the cursor."""
    async with PromptPage("hello world foo", cursor=(0, 7)) as page:
        await page.press("y", "i", "w")

        assert page.text == "hello world foo"
        assert page.ta._vim_register.text == "world"
        assert page.ta._vim_register.kind == "charwise"
        assert page.cursor == (0, 6)


async def test_yf_yanks_through_character_search_match() -> None:
    """yf{char} yanks through the found character inclusively."""
    async with PromptPage("foo(bar) baz", cursor=(0, 3)) as page:
        await page.press("y", "f", ")")

        assert page.text == "foo(bar) baz"
        assert page.ta._vim_register.text == "(bar)"
        assert page.ta._vim_register.kind == "charwise"
        assert page.cursor == (0, 3)


async def test_yae_yanks_entire_buffer_linewise() -> None:
    """yae yanks the entire buffer as a linewise register."""
    async with PromptPage("aaa\nbbb\nccc", cursor=(1, 0)) as page:
        await page.press("y", "a", "e")

        assert page.text == "aaa\nbbb\nccc"
        assert page.ta._vim_register.text == "aaa\nbbb\nccc"
        assert page.ta._vim_register.kind == "linewise"
        assert page.cursor == (1, 0)


async def test_yy_yanks_current_line_without_moving_cursor() -> None:
    """yy stores a linewise register and leaves the cursor where it was."""
    async with PromptPage("aaa\n  bbb\nccc", cursor=(1, 2)) as page:
        await page.press("y", "y")

        assert page.text == "aaa\n  bbb\nccc"
        assert page.ta._vim_register.text == "  bbb"
        assert page.ta._vim_register.kind == "linewise"
        assert page.cursor == (1, 2)


async def test_Y_yanks_from_cursor_to_end_of_line() -> None:
    """Y yanks charwise from the cursor to the end of the line, like y$."""
    async with PromptPage("aaa\n  bbb ccc\nddd", cursor=(1, 6)) as page:
        await page.press("Y")

        assert page.text == "aaa\n  bbb ccc\nddd"
        assert page.ta._vim_register.text == "ccc"
        assert page.ta._vim_register.kind == "charwise"
        assert page.cursor == (1, 6)


async def test_Y_at_column_zero_yanks_whole_line_charwise() -> None:
    """Y at column zero yanks the whole line, but still charwise."""
    async with PromptPage("aaa\n  bbb ccc\nddd", cursor=(1, 0)) as page:
        await page.press("Y")

        assert page.text == "aaa\n  bbb ccc\nddd"
        assert page.ta._vim_register.text == "  bbb ccc"
        assert page.ta._vim_register.kind == "charwise"
        assert page.cursor == (1, 0)


async def test_Y_with_count_spans_through_end_of_last_line() -> None:
    """{count}Y == {count}y$: charwise through the end of the last line."""
    async with PromptPage("aaa\nbbb\nccc\nddd", cursor=(1, 0)) as page:
        await page.press("2", "Y")

        assert page.text == "aaa\nbbb\nccc\nddd"
        assert page.ta._vim_register.text == "bbb\nccc"
        assert page.ta._vim_register.kind == "charwise"
        assert page.cursor == (1, 0)


async def test_Y_at_end_of_line_leaves_register_untouched() -> None:
    """Y on an empty range is a no-op that does not clear the register."""
    async with PromptPage("one two\n\nthree") as page:
        await page.press("y", "w")
        assert page.ta._vim_register.text == "one "

        page.cursor = (1, 0)
        await page.press("Y")

        assert page.text == "one two\n\nthree"
        assert page.ta._vim_register.text == "one "


async def test_Y_register_pastes_inline() -> None:
    """Y's charwise register pastes inline rather than opening a new line."""
    async with PromptPage("abc def\nxyz", cursor=(0, 4)) as page:
        await page.press("Y")
        assert page.ta._vim_register.text == "def"

        page.cursor = (1, 0)
        await page.press("p")

        assert page.text == "abc def\nxdefyz"


async def test_p_pastes_charwise_after_cursor_with_count_and_undo() -> None:
    """p pastes charwise text after the cursor; count is one undoable edit."""
    async with PromptPage("one two") as page:
        await page.press("y", "w")
        page.cursor = (0, len(page.text))

        await page.press("2", "p")
        assert page.text == "one twoone one "
        assert page.cursor == (0, len(page.text) - 1)

        await page.press("u")
        assert page.text == "one two"


async def test_P_pastes_charwise_before_cursor() -> None:
    """P pastes charwise text before the cursor."""
    async with PromptPage("one two") as page:
        await page.press("y", "w")
        page.cursor = (0, 4)

        await page.press("P")
        assert page.text == "one one two"


async def test_dot_repeats_charwise_paste() -> None:
    """Charwise paste is dot-repeatable."""
    async with PromptPage("one two") as page:
        await page.press("y", "w")
        page.cursor = (0, len(page.text))

        await page.press("p")
        await page.press(".")

        assert page.text == "one twoone one "


async def test_p_pastes_linewise_below_cursor_on_first_nonblank() -> None:
    """Linewise p opens lines below and moves to the first non-blank column."""
    async with PromptPage("aaa\n  bbb\nccc", cursor=(1, 2)) as page:
        await page.press("y", "y")
        page.cursor = (0, 0)

        await page.press("p")

        assert page.text == "aaa\n  bbb\n  bbb\nccc"
        assert page.cursor == (1, 2)


async def test_P_pastes_linewise_above_cursor() -> None:
    """Linewise P opens lines above the cursor."""
    async with PromptPage("aaa\nbbb\nccc", cursor=(1, 0)) as page:
        await page.press("y", "y")
        page.cursor = (2, 0)

        await page.press("P")

        assert page.text == "aaa\nbbb\nbbb\nccc"
        assert page.cursor == (2, 0)


async def test_linewise_paste_count_repeats_lines_in_one_edit() -> None:
    """A count prefix repeats linewise register lines as one paste edit."""
    async with PromptPage("aaa\nbbb\nccc") as page:
        await page.press("y", "y")
        page.cursor = (1, 0)

        await page.press("2", "p")
        assert page.text == "aaa\nbbb\naaa\naaa\nccc"

        await page.press("u")
        assert page.text == "aaa\nbbb\nccc"


async def test_delete_writes_charwise_register_for_paste() -> None:
    """Deleting text updates the unnamed register used by p/P."""
    async with PromptPage("one two") as page:
        await page.press("d", "w")
        assert page.text == "two"
        assert page.ta._vim_register.text == "one "
        assert page.ta._vim_register.kind == "charwise"

        page.cursor = (0, len(page.text))
        await page.press("p")
        assert page.text == "twoone "


async def test_change_writes_charwise_register_for_paste() -> None:
    """Changing text updates the unnamed register before entering insert mode."""
    async with PromptPage("one two") as page:
        await page.press("c", "w")
        assert page.mode == "insert"
        assert page.ta._vim_register.text == "one"
        assert page.ta._vim_register.kind == "charwise"

        await page.press("escape")
        page.cursor = (0, len(page.text))
        await page.press("p")
        assert page.text == " twoone"


async def test_dd_register_pastes_back_into_empty_buffer() -> None:
    """Linewise delete writes a register that can paste into an empty prompt."""
    async with PromptPage("only") as page:
        await page.press("d", "d")
        assert page.text == ""
        assert page.ta._vim_register.text == "only"
        assert page.ta._vim_register.kind == "linewise"

        await page.press("p")
        assert page.text == "only"
        assert page.cursor == (0, 0)
