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


async def test_count_dot_overrides_replace_count() -> None:
    """3. after rx replays as 3rx, not rx three times at the same cursor."""
    async with PromptPage("abcdef") as page:
        await page.press("r", "x")
        assert page.text == "xbcdef"

        await page.press("3", ".")
        assert page.text == "xxxdef"
        assert page.cursor == (0, 2)


async def test_count_dot_overrides_indent_line_count() -> None:
    """3. after >> indents three lines, not one line three levels."""
    async with PromptPage("aaa\nbbb\nccc\nddd") as page:
        await page.press(">", ">")
        assert page.text == "  aaa\nbbb\nccc\nddd"

        page.cursor = (1, 0)
        await page.press("3", ".")
        assert page.text == "  aaa\n  bbb\n  ccc\n  ddd"
        assert page.cursor == (1, 2)


async def test_count_dot_overrides_delete_word_count() -> None:
    """3. after dw replays as d3w from the current cursor."""
    async with PromptPage("one two three four five") as page:
        await page.press("d", "w")
        assert page.text == "two three four five"

        await page.press("3", ".")
        assert page.text == "five"


async def test_plain_dot_reuses_recorded_operator_motion_count() -> None:
    """Dot after d2w deletes two words again."""
    async with PromptPage("one two three four five") as page:
        await page.press("d", "2", "w")
        assert page.text == "three four five"

        await page.press(".")
        assert page.text == "five"


async def test_count_dot_repeats_insert_text_count_times() -> None:
    """Counted dot after plain insert multiplies the captured insert text."""
    async with PromptPage("") as page:
        await page.press("i", "h", "i", "escape")
        assert page.text == "hi"
        assert page.mode == "normal"

        await page.press("3", ".")
        assert page.text == "hihihihi"
        assert page.mode == "normal"


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


async def test_dot_repeats_cw_inserted_text_and_returns_normal() -> None:
    """Dot repeats the text typed for a c-motion change."""
    async with PromptPage("one two three") as page:
        await page.press("c", "w", "f", "o", "o", "escape")
        assert page.text == "foo two three"
        assert page.mode == "normal"

        page.cursor = (0, 4)
        await page.press(".")
        assert page.text == "foo foo three"
        assert page.mode == "normal"


async def test_dot_repeats_plain_insert_text() -> None:
    """Dot repeats a plain i...Escape insertion."""
    async with PromptPage("world") as page:
        await page.press("i", "h", "i", " ", "escape")
        assert page.text == "hi world"

        page.cursor = (0, 3)
        await page.press(".")
        assert page.text == "hi hi world"
        assert page.mode == "normal"


async def test_dot_repeats_append_to_end_of_line_text() -> None:
    """Dot repeats A...Escape at the current line."""
    async with PromptPage("one\ntwo") as page:
        await page.press("A", ";", "escape")
        assert page.text == "one;\ntwo"

        page.cursor = (1, 0)
        await page.press(".")
        assert page.text == "one;\ntwo;"
        assert page.mode == "normal"


async def test_dot_repeats_open_line_below_text() -> None:
    """Dot repeats o...Escape without staying in INSERT mode."""
    async with PromptPage("one") as page:
        await page.press("o", "-", " ", "i", "t", "e", "m", "escape")
        assert page.text == "one\n- item"

        await page.press(".")
        assert page.text == "one\n- item\n- item"
        assert page.mode == "normal"


async def test_dot_after_pending_operator_repeats_last_mutation() -> None:
    """d. cancels the pending operator and performs dot-repeat."""
    async with PromptPage("one two three") as page:
        await page.press("d", "w")
        assert page.text == "two three"

        await page.press("d", ".")
        assert page.text == "three"
        assert page.ta._pending_operator == ""
        assert page.mode == "normal"
