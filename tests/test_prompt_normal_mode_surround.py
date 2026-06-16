"""Tests for PromptTextArea NORMAL-mode vim-surround support."""

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


async def test_ds_double_quote_removes_surrounding_quotes() -> None:
    async with PromptPage('Some "piece of text" goes here.', cursor=(0, 6)) as page:
        await page.press("d", "s", '"')

        assert page.text == "Some piece of text goes here."
        assert page.cursor == (0, 5)


async def test_ds_parenthesis_accepts_closing_key() -> None:
    async with PromptPage("hello (world)", cursor=(0, 8)) as page:
        await page.press("d", "s", ")")

        assert page.text == "hello world"


async def test_dsb_uses_parenthesis_alias() -> None:
    async with PromptPage("hello (world)", cursor=(0, 8)) as page:
        await page.press("d", "s", "b")

        assert page.text == "hello world"


async def test_ds_brace_uses_outer_count() -> None:
    async with PromptPage("one {two {three} four} five", cursor=(0, 10)) as page:
        await page.press("2", "d", "s", "{")

        assert page.text == "one two {three} four five"


async def test_ds_custom_same_character_surround() -> None:
    async with PromptPage("say *hello* now", cursor=(0, 6)) as page:
        await page.press("d", "s", "*")

        assert page.text == "say hello now"


async def test_ds_without_matching_surround_is_noop() -> None:
    async with PromptPage("plain text", cursor=(0, 2)) as page:
        await page.press("d", "s", '"')

        assert page.text == "plain text"
        assert page.ta._pending_operator == ""


async def test_ds_is_dot_repeatable() -> None:
    async with PromptPage('"one" "two" three', cursor=(0, 2)) as page:
        await page.press("d", "s", '"')
        page.cursor = (0, 5)

        await page.press(".")

        assert page.text == "one two three"


async def test_cs_double_quote_to_single_quote_changes_surround() -> None:
    async with PromptPage('Some "piece of text" goes here.', cursor=(0, 6)) as page:
        await page.press("c", "s", '"', "'")

        assert page.text == "Some 'piece of text' goes here."


async def test_cs_parenthesis_to_brackets_accepts_closing_keys() -> None:
    async with PromptPage("hello (world)", cursor=(0, 8)) as page:
        await page.press("c", "s", ")", "]")

        assert page.text == "hello [world]"


async def test_csb_uses_parenthesis_alias() -> None:
    async with PromptPage("hello (world)", cursor=(0, 8)) as page:
        await page.press("c", "s", "b", '"')

        assert page.text == 'hello "world"'


async def test_cs_brace_uses_outer_count() -> None:
    async with PromptPage("one {two {three} four} five", cursor=(0, 10)) as page:
        await page.press("2", "c", "s", "{", "[")

        assert page.text == "one [two {three} four] five"


async def test_cs_custom_same_character_surround() -> None:
    async with PromptPage("say *hello* now", cursor=(0, 6)) as page:
        await page.press("c", "s", "*", '"')

        assert page.text == 'say "hello" now'


async def test_cs_without_matching_surround_is_noop() -> None:
    async with PromptPage("plain text", cursor=(0, 2)) as page:
        await page.press("c", "s", '"', "'")

        assert page.text == "plain text"
        assert page.ta._pending_operator == ""
        assert page.ta._pending_keys == ""


async def test_cs_is_dot_repeatable() -> None:
    async with PromptPage('"one" "two" three', cursor=(0, 2)) as page:
        await page.press("c", "s", '"', "'")
        page.cursor = (0, 7)

        await page.press(".")

        assert page.text == "'one' 'two' three"
