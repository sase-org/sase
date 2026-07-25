"""Tests for PromptTextArea vim VISUAL and V-LINE modes."""

from textual.document._document import Selection

from sase.ace.testing import PromptPage


async def test_v_enters_charwise_visual_and_escape_returns_normal() -> None:
    """v enters charwise visual mode and Escape clears the selection."""
    async with PromptPage("abc") as page:
        await page.press("v")

        assert page.mode == "visual"
        assert page.ta._visual_anchor == (0, 0)
        assert page.ta._visual_cursor == (0, 0)
        assert page.ta.selection == Selection((0, 0), (0, 1))

        await page.press("escape")

        assert page.mode == "normal"
        assert page.ta.selection == Selection.cursor((0, 0))


async def test_v_toggles_back_to_normal_mode() -> None:
    """A second v exits charwise visual mode."""
    async with PromptPage("abc") as page:
        await page.press("v", "v")

        assert page.mode == "normal"
        assert page.ta.selection == Selection.cursor((0, 0))


async def test_V_enters_linewise_visual_and_selects_whole_line() -> None:
    """V enters linewise visual mode and selects the current line."""
    async with PromptPage("aaa\nbbb\nccc", cursor=(1, 2)) as page:
        await page.press("V")

        assert page.mode == "visual_line"
        assert page.ta.selection == Selection((1, 0), (2, 0))


async def test_charwise_visual_delete_writes_register() -> None:
    """v + motion + d deletes the selected characters."""
    async with PromptPage("abcde") as page:
        await page.press("v", "l", "d")

        assert page.text == "cde"
        assert page.mode == "normal"
        assert page.cursor == (0, 0)
        assert page.ta._vim_register.text == "ab"
        assert page.ta._vim_register.kind == "charwise"


async def test_space_extends_charwise_visual_selection_right() -> None:
    """Space is the visual-mode alias for the ``l`` motion."""
    async with PromptPage("abcde") as page:
        await page.press("v", "space")

        assert page.ta._visual_cursor == (0, 1)
        assert page.ta.selection == Selection((0, 0), (0, 2))


async def test_charwise_visual_yank_backward_selection() -> None:
    """Backward charwise selections normalize before yanking."""
    async with PromptPage("abcde", cursor=(0, 2)) as page:
        await page.press("v", "h", "y")

        assert page.text == "abcde"
        assert page.mode == "normal"
        assert page.cursor == (0, 1)
        assert page.ta._vim_register.text == "bc"
        assert page.ta._vim_register.kind == "charwise"


async def test_visual_text_object_selects_inner_word_for_yank() -> None:
    """Visual iw selects the word under the visual cursor."""
    async with PromptPage("hello world foo", cursor=(0, 7)) as page:
        await page.press("v", "i", "w", "y")

        assert page.ta._vim_register.text == "world"
        assert page.ta._vim_register.kind == "charwise"
        assert page.cursor == (0, 6)


async def test_visual_text_object_selects_inner_parentheses_for_yank() -> None:
    """Visual i( selects the innermost parenthesized content."""
    async with PromptPage("call(foo(bar), baz)", cursor=(0, 9)) as page:
        await page.press("v", "i", "(", "y")

        assert page.ta._vim_register.text == "bar"
        assert page.ta._vim_register.kind == "charwise"
        assert page.cursor == (0, 9)


async def test_visual_text_object_selects_a_quote_for_delete() -> None:
    """Visual a\" selects quotes and trailing whitespace."""
    async with PromptPage('foo "bar" baz', cursor=(0, 6)) as page:
        await page.press("v", "a", '"', "d")

        assert page.text == "foo baz"
        assert page.ta._vim_register.text == '"bar" '


async def test_visual_change_enters_insert_mode() -> None:
    """c changes the visual selection and enters INSERT mode."""
    async with PromptPage("abcde") as page:
        await page.press("v", "l", "c")

        assert page.text == "cde"
        assert page.mode == "insert"
        assert page.cursor == (0, 0)


async def test_visual_p_replaces_selection_and_stores_replaced_text() -> None:
    """p replaces the visual selection with the previous register."""
    async with PromptPage("one two") as page:
        await page.press("y", "w")
        page.cursor = (0, 4)

        await page.press("v", "e", "p")

        assert page.text == "one one "
        assert page.mode == "normal"
        assert page.ta._vim_register.text == "two"
        assert page.ta._vim_register.kind == "charwise"


async def test_visual_toggle_case_updates_selection_and_register() -> None:
    """~ toggles selected characters and stores the original text."""
    async with PromptPage("abCD") as page:
        await page.press("v", "l", "~")

        assert page.text == "ABCD"
        assert page.mode == "normal"
        assert page.ta._vim_register.text == "ab"
        assert page.ta._vim_register.kind == "charwise"


async def test_o_swaps_visual_anchor_and_cursor() -> None:
    """o swaps the active visual end before the next motion."""
    async with PromptPage("abcd", cursor=(0, 1)) as page:
        await page.press("v", "l", "o", "h", "y")

        assert page.ta._vim_register.text == "abc"
        assert page.cursor == (0, 0)


async def test_linewise_visual_yank() -> None:
    """V-line y yanks whole selected lines."""
    async with PromptPage("aaa\nbbb\nccc\nddd", cursor=(1, 1)) as page:
        await page.press("V", "j", "y")

        assert page.text == "aaa\nbbb\nccc\nddd"
        assert page.mode == "normal"
        assert page.cursor == (1, 0)
        assert page.ta._vim_register.text == "bbb\nccc"
        assert page.ta._vim_register.kind == "linewise"


async def test_linewise_visual_delete() -> None:
    """V-line d deletes whole selected lines."""
    async with PromptPage("aaa\nbbb\nccc\nddd", cursor=(1, 1)) as page:
        await page.press("V", "j", "d")

        assert page.text == "aaa\nddd"
        assert page.mode == "normal"
        assert page.cursor == (1, 0)
        assert page.ta._vim_register.text == "bbb\nccc"
        assert page.ta._vim_register.kind == "linewise"


async def test_linewise_visual_p_preserves_following_line() -> None:
    """V-line p replaces whole lines without joining the following line."""
    async with PromptPage("aaa\n  bbb\nccc", cursor=(1, 2)) as page:
        await page.press("y", "y")
        page.cursor = (2, 0)

        await page.press("V", "p")

        assert page.text == "aaa\n  bbb\n  bbb"
        assert page.mode == "normal"
        assert page.cursor == (2, 2)
        assert page.ta._vim_register.text == "ccc"
        assert page.ta._vim_register.kind == "linewise"


async def test_linewise_visual_toggle_case_preserves_line_boundaries() -> None:
    """V-line ~ toggles selected lines without joining surrounding lines."""
    async with PromptPage("aaa\nbbb\nccc\nddd", cursor=(1, 0)) as page:
        await page.press("V", "j", "~")

        assert page.text == "aaa\nBBB\nCCC\nddd"
        assert page.mode == "normal"
        assert page.cursor == (1, 0)
        assert page.ta._vim_register.text == "bbb\nccc"
        assert page.ta._vim_register.kind == "linewise"


async def test_charwise_visual_indent_applies_to_selected_lines() -> None:
    """Visual > indents every line touched by the selection."""
    async with PromptPage("aaa\nbbb\nccc") as page:
        await page.press("v", "j", ">")

        assert page.text == "  aaa\n  bbb\nccc"
        assert page.mode == "normal"
        assert page.cursor == (0, 2)


async def test_linewise_visual_dedent() -> None:
    """V-line < dedents whole selected lines."""
    async with PromptPage("  aaa\n    bbb\nccc") as page:
        await page.press("V", "j", "<")

        assert page.text == "aaa\n  bbb\nccc"
        assert page.mode == "normal"
        assert page.cursor == (0, 0)


async def test_visual_lowercase_selection() -> None:
    """Visual u lowercases selected characters."""
    async with PromptPage("ABcd") as page:
        await page.press("v", "l", "u")

        assert page.text == "abcd"
        assert page.mode == "normal"
        assert page.ta._vim_register.text == "AB"
        assert page.ta._vim_register.kind == "charwise"


async def test_visual_uppercase_selection() -> None:
    """Visual U uppercases selected characters."""
    async with PromptPage("abCD") as page:
        await page.press("v", "l", "U")

        assert page.text == "ABCD"
        assert page.mode == "normal"
        assert page.ta._vim_register.text == "ab"
        assert page.ta._vim_register.kind == "charwise"


async def test_dot_repeats_charwise_visual_delete_same_size() -> None:
    """Dot repeats a visual delete over a same-sized range."""
    async with PromptPage("abcdef") as page:
        await page.press("v", "l", "d")
        assert page.text == "cdef"

        await page.press(".")
        assert page.text == "ef"
        assert page.mode == "normal"


async def test_dot_repeats_linewise_visual_delete_same_size() -> None:
    """Dot repeats a V-line delete over the same number of lines."""
    async with PromptPage("aaa\nbbb\nccc\nddd\neee", cursor=(1, 0)) as page:
        await page.press("V", "j", "d")
        assert page.text == "aaa\nddd\neee"

        await page.press(".")
        assert page.text == "aaa"
        assert page.mode == "normal"


async def test_dot_repeats_visual_change_inserted_text() -> None:
    """Dot repeats a visual change and restores the typed replacement text."""
    async with PromptPage("one two three") as page:
        await page.press("v", "e", "c", "X", "escape")
        assert page.text == "X two three"
        assert page.mode == "normal"

        page.cursor = (0, 2)
        await page.press(".")
        assert page.text == "X X three"
        assert page.mode == "normal"


async def test_dot_repeats_visual_indent_same_line_count() -> None:
    """Dot repeats visual indent over the same number of touched lines."""
    async with PromptPage("aaa\nbbb\nccc\nddd") as page:
        await page.press("v", "j", ">")
        assert page.text == "  aaa\n  bbb\nccc\nddd"

        page.cursor = (2, 0)
        await page.press(".")
        assert page.text == "  aaa\n  bbb\n  ccc\n  ddd"
        assert page.mode == "normal"


async def test_dot_repeats_visual_case_same_char_count() -> None:
    """Dot repeats a visual case operation over the same character count."""
    async with PromptPage("ab cd ef") as page:
        await page.press("v", "l", "U")
        assert page.text == "AB cd ef"

        page.cursor = (0, 3)
        await page.press(".")
        assert page.text == "AB CD ef"
        assert page.mode == "normal"
