"""Direct coverage for the shared ``VimTextArea`` base widget.

These exercise the extracted vim/readline layer through a bare widget (no prompt
bar), so they pin the behavior every host inherits: motions, operators, mode
transitions, the border-based mode display, and the two-stage Escape.
"""

from __future__ import annotations

from sase.ace.testing import VimEditorPage


async def test_normal_mode_dw_deletes_word() -> None:
    async with VimEditorPage("hello world", cursor=(0, 0)) as page:
        await page.press("d", "w")
        assert page.text == "world"


async def test_normal_mode_x_deletes_char_and_fires_no_prompt_coupling() -> None:
    async with VimEditorPage("abc", cursor=(0, 0)) as page:
        await page.press("x")
        assert page.text == "bc"


async def test_operator_with_count() -> None:
    async with VimEditorPage("one two three four", cursor=(0, 0)) as page:
        await page.press("2", "d", "w")
        assert page.text == "three four"


async def test_dot_repeats_last_change() -> None:
    async with VimEditorPage("aa bb cc dd", cursor=(0, 0)) as page:
        await page.press("d", "w")
        await page.press(".")
        assert page.text == "cc dd"


async def test_visual_mode_delete() -> None:
    async with VimEditorPage("hello world", cursor=(0, 0)) as page:
        await page.press("v", "e", "d")
        assert page.text == " world"


async def test_insert_escape_enters_normal_mode() -> None:
    async with VimEditorPage("hi", cursor=(0, 0), mode="insert") as page:
        assert page.mode == "insert"
        await page.press("escape")
        assert page.mode == "normal"


async def test_mode_shown_on_border_title() -> None:
    async with VimEditorPage("hi", cursor=(0, 0), mode="insert") as page:
        page.ta._update_vim_mode_display()
        assert page.ta.border_title == "[INSERT]"
        await page.press("escape")
        assert page.ta.border_title == "[NORMAL]"


async def test_pending_count_shown_in_border_subtitle() -> None:
    async with VimEditorPage("hello", cursor=(0, 0)) as page:
        await page.press("2")
        assert page.ta.border_subtitle == "2"
        assert page.ta._count_prefix == "2"


async def test_normal_escape_with_pending_count_clears_it() -> None:
    async with VimEditorPage("hello", cursor=(0, 0)) as page:
        await page.press("2")
        assert page.ta._count_prefix == "2"
        await page.press("escape")
        assert page.ta._count_prefix == ""
        # Still in NORMAL mode -- the Escape only cleared the pending count.
        assert page.mode == "normal"


async def test_readline_ctrl_a_ctrl_e_line_hops_in_insert() -> None:
    async with VimEditorPage("hello", cursor=(0, 2), mode="insert") as page:
        await page.press("ctrl+a")
        assert page.cursor == (0, 0)
        await page.press("ctrl+e")
        assert page.cursor == (0, 5)


async def test_normal_mode_join_keeps_bullet_marker_in_generic_host() -> None:
    async with VimEditorPage("- one\n- two", cursor=(0, 0)) as page:
        await page.press("J")
        assert page.text == "- one - two"
