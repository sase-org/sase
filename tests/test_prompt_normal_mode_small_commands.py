"""Tests for PromptTextArea NORMAL-mode small vim commands."""

from sase.ace.testing import PromptPage


async def test_cw_on_nonblank_behaves_like_ce() -> None:
    async with PromptPage("one two three") as page:
        await page.press("c", "w")
        assert page.mode == "insert"
        assert page.text == " two three"
        assert page.cursor == (0, 0)


async def test_cw_count_behaves_like_ce_count() -> None:
    async with PromptPage("one two three") as page:
        await page.press("2", "c", "w")
        assert page.mode == "insert"
        assert page.text == " three"


async def test_cw_on_blank_keeps_w_motion_behavior() -> None:
    async with PromptPage("one   two", cursor=(0, 3)) as page:
        await page.press("c", "w")
        assert page.mode == "insert"
        assert page.text == "onetwo"
        assert page.cursor == (0, 3)


async def test_cW_on_nonblank_behaves_like_cE() -> None:
    async with PromptPage("foo.bar baz") as page:
        await page.press("c", "W")
        assert page.mode == "insert"
        assert page.text == " baz"


async def test_r_replaces_character() -> None:
    async with PromptPage("abcde", cursor=(0, 2)) as page:
        await page.press("r", "x")
        assert page.text == "abxde"
        assert page.cursor == (0, 2)


async def test_r_with_count_replaces_multiple_characters() -> None:
    async with PromptPage("abcde") as page:
        await page.press("3", "r", "x")
        assert page.text == "xxxde"
        assert page.cursor == (0, 2)


async def test_r_noop_when_too_few_characters_remain() -> None:
    async with PromptPage("abc", cursor=(0, 1)) as page:
        await page.press("3", "r", "x")
        assert page.text == "abc"
        assert page.cursor == (0, 1)


async def test_dot_repeats_r() -> None:
    async with PromptPage("abcde") as page:
        await page.press("r", "x")
        await page.press("l", ".")
        assert page.text == "xxcde"
        assert page.cursor == (0, 1)


async def test_ctrl_r_redoes_undo() -> None:
    async with PromptPage("one two three") as page:
        await page.press("d", "w")
        assert page.text == "two three"
        await page.press("u")
        assert page.text == "one two three"
        await page.press("ctrl+r")
        assert page.text == "two three"


async def test_X_deletes_character_before_cursor() -> None:
    async with PromptPage("abcde", cursor=(0, 3)) as page:
        await page.press("X")
        assert page.text == "abde"
        assert page.cursor == (0, 2)


async def test_X_with_count_deletes_before_cursor() -> None:
    async with PromptPage("abcde", cursor=(0, 4)) as page:
        await page.press("3", "X")
        assert page.text == "ae"
        assert page.cursor == (0, 1)


async def test_S_changes_current_line() -> None:
    async with PromptPage("aaa\nbbb\nccc", cursor=(1, 1)) as page:
        await page.press("S")
        assert page.mode == "insert"
        assert page.text == "aaa\n\nccc"
        assert page.cursor == (1, 0)


async def test_S_with_count_changes_multiple_lines() -> None:
    async with PromptPage("aaa\nbbb\nccc\nddd", cursor=(1, 0)) as page:
        await page.press("2", "S")
        assert page.mode == "insert"
        assert page.text == "aaa\n\nddd"
        assert page.cursor == (1, 0)


async def test_ge_moves_to_previous_word_end() -> None:
    async with PromptPage("one two three", cursor=(0, 8)) as page:
        await page.press("g", "e")
        assert page.cursor == (0, 6)


async def test_ge_with_count_moves_multiple_word_ends() -> None:
    async with PromptPage("one two three four", cursor=(0, 14)) as page:
        await page.press("2", "g", "e")
        assert page.cursor == (0, 6)


async def test_gE_moves_to_previous_WORD_end() -> None:
    async with PromptPage("foo.bar baz", cursor=(0, 8)) as page:
        await page.press("g", "E")
        assert page.cursor == (0, 6)


async def test_dge_deletes_back_to_previous_word_end() -> None:
    async with PromptPage("one two three", cursor=(0, 8)) as page:
        await page.press("d", "g", "e")
        assert page.text == "one twhree"
        assert page.cursor == (0, 6)


async def test_dgE_deletes_back_to_previous_WORD_end() -> None:
    async with PromptPage("foo.bar baz", cursor=(0, 8)) as page:
        await page.press("d", "g", "E")
        assert page.text == "foo.baaz"
        assert page.cursor == (0, 6)


async def test_dge_at_buffer_start_aborts_without_deleting() -> None:
    async with PromptPage("one two", cursor=(0, 0)) as page:
        await page.press("d", "g", "e")
        assert page.text == "one two"
        assert page.cursor == (0, 0)


async def test_dgE_at_buffer_start_aborts_without_deleting() -> None:
    async with PromptPage("foo.bar baz", cursor=(0, 0)) as page:
        await page.press("d", "g", "E")
        assert page.text == "foo.bar baz"
        assert page.cursor == (0, 0)


async def test_ge_with_huge_count_terminates_at_buffer_start() -> None:
    # Regression: the motion loop must stop once pinned at the buffer-start
    # clamp instead of iterating the full count.
    async with PromptPage("one two three", cursor=(0, 12)) as page:
        await page.press("9", "9", "9", "9", "9", "9", "9", "9", "g", "e")
        assert page.cursor == (0, 0)


async def test_noop_X_preserves_dot_repeat() -> None:
    async with PromptPage("one two three") as page:
        await page.press("d", "w")
        assert page.text == "two three"
        await page.press("X")  # column 0: nothing to delete
        assert page.text == "two three"
        await page.press(".")
        assert page.text == "three"
