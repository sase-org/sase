"""Direct coverage for ``SingleLineVimTextArea`` (the ``Input`` replacement)."""

from __future__ import annotations

from sase.ace.testing import VimEditorPage
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


async def test_enter_posts_submitted_from_insert_mode() -> None:
    async with VimEditorPage(
        "value", cursor=(0, 5), mode="insert", widget_cls=SingleLineVimTextArea
    ) as page:
        await page.press("enter")
        await page.pause()
        assert page.submitted == ["value"]
        # Enter did not insert a newline.
        assert "\n" not in page.text


async def test_enter_posts_submitted_from_normal_mode() -> None:
    async with VimEditorPage(
        "value", cursor=(0, 0), mode="normal", widget_cls=SingleLineVimTextArea
    ) as page:
        await page.press("enter")
        await page.pause()
        assert page.submitted == ["value"]


async def test_open_line_keys_suppressed() -> None:
    async with VimEditorPage(
        "abc", cursor=(0, 0), mode="normal", widget_cls=SingleLineVimTextArea
    ) as page:
        await page.press("o")
        await page.press("O")
        await page.pause()
        assert page.text == "abc"
        assert "\n" not in page.text


async def test_ctrl_j_does_not_insert_newline() -> None:
    async with VimEditorPage(
        "abc", cursor=(0, 3), mode="insert", widget_cls=SingleLineVimTextArea
    ) as page:
        await page.press("ctrl+j")
        await page.pause()
        assert page.text == "abc"
        assert "\n" not in page.text


async def test_linewise_paste_is_flattened() -> None:
    async with VimEditorPage(
        "a b c", cursor=(0, 0), mode="normal", widget_cls=SingleLineVimTextArea
    ) as page:
        # Yank the whole (single) line linewise, then paste it.
        await page.press("y", "y")
        await page.press("p")
        await page.pause()
        assert "\n" not in page.text


async def test_normal_edits_still_work() -> None:
    async with VimEditorPage(
        "hello world", cursor=(0, 0), mode="normal", widget_cls=SingleLineVimTextArea
    ) as page:
        await page.press("d", "w")
        assert page.text == "world"


async def test_typing_replaces_and_stays_single_line() -> None:
    async with VimEditorPage(
        "old", cursor=(0, 3), mode="insert", widget_cls=SingleLineVimTextArea
    ) as page:
        await page.press("!", "!")
        await page.pause()
        assert page.text == "old!!"
        assert "\n" not in page.text
