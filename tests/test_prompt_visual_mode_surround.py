"""Tests for visual-mode surround support in the shared Vim editor."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from sase.ace.testing import PromptPage, VimEditorPage
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _PromptBarApp(App[None]):
    """Minimal host for assertions against prompt-bar mode chrome."""

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value="abc", id="prompt-input-bar")


async def test_visual_surround_wraps_forward_selection_and_lands_on_opening() -> None:
    async with PromptPage("abcde") as page:
        await page.press("v", "l", "S")

        assert page.text == "abcde"
        assert page.mode == "visual"
        assert page.ta._pending_keys == "visual-surround"

        await page.press('"')

        assert page.text == '"ab"cde'
        assert page.mode == "normal"
        assert page.cursor == (0, 0)
        assert page.ta._pending_keys == ""
        assert page.ta._pending_visual_surround_range is None
        assert page.ta._visual_anchor is None
        assert page.ta._visual_cursor is None


async def test_visual_surround_normalizes_backward_selection_exactly() -> None:
    async with PromptPage(" abcd ", cursor=(0, 5)) as page:
        await page.press("v", "5", "h", "S", '"')

        assert page.text == '" abcd "'
        assert page.cursor == (0, 0)


@pytest.mark.parametrize(
    ("delimiter", "expected"),
    [
        ("]", "[ab]c"),
        ("space", " ab c"),
        ("*", "*ab*c"),
    ],
)
async def test_visual_surround_reuses_delimiter_rules(
    delimiter: str,
    expected: str,
) -> None:
    async with PromptPage("abc") as page:
        await page.press("v", "l", "S", delimiter)

        assert page.text == expected
        assert page.mode == "normal"


async def test_visual_surround_preserves_exact_multiline_selection() -> None:
    async with PromptPage("ab\ncd", cursor=(0, 1)) as page:
        await page.press("v", "j", "S", "]")

        assert page.text == "a[b\ncd]"
        assert page.cursor == (0, 1)


async def test_vline_surround_preserves_neighboring_line_separators() -> None:
    async with PromptPage("aaa\nbbb\nccc\nddd", cursor=(1, 1)) as page:
        await page.press("V", "j", "S", ")")

        assert page.text == "aaa\n(bbb\nccc)\nddd"
        assert page.mode == "normal"
        assert page.cursor == (1, 0)


async def test_bare_vim_text_area_shows_visual_surround_pending_indicator() -> None:
    async with VimEditorPage("abc") as page:
        await page.press("v", "S")

        assert page.ta.border_subtitle == "S"
        assert page.mode == "visual"

        await page.press('"')

        assert page.ta.border_subtitle == ""
        assert page.mode == "normal"


async def test_prompt_bar_shows_visual_surround_pending_indicator() -> None:
    app = _PromptBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        text_area.text = "abc"
        text_area.cursor_location = (0, 0)
        text_area.focus()
        text_area._enter_normal_mode()
        await pilot.pause()
        await pilot.press("v", "S")

        assert text_area._vim_mode == "visual"
        assert bar._mode_subtitle == ("[Esc] normal  [o] swap ends  [^C] cancel  S")


@pytest.mark.parametrize("cancel_key", ["escape", "ctrl+x"])
async def test_visual_surround_cancellation_preserves_previous_dot_change(
    cancel_key: str,
) -> None:
    async with PromptPage("abcdef") as page:
        await page.press("v", "l", "d")
        previous_change = page.ta._last_visual_mutation

        await page.press("v", "S", cancel_key)

        assert page.text == "cdef"
        assert page.mode == "normal"
        assert page.ta._pending_keys == ""
        assert page.ta._pending_visual_surround_range is None
        assert page.ta._last_visual_mutation == previous_change

        await page.press(".")
        assert page.text == "ef"


async def test_empty_visual_surround_preserves_previous_dot_change() -> None:
    async with PromptPage("ab") as page:
        await page.press("v", "l", "d")
        previous_change = page.ta._last_visual_mutation
        assert page.text == ""

        await page.press("v", "S")

        assert page.mode == "normal"
        assert page.ta._pending_keys == ""
        assert page.ta._pending_visual_surround_range is None
        assert page.ta._last_visual_mutation == previous_change


async def test_visual_surround_is_one_undo_and_preserves_register() -> None:
    async with PromptPage("one two") as page:
        await page.press("y", "w")
        register = page.ta._vim_register
        page.cursor = (0, 4)

        await page.press("v", "e", "S", '"')

        assert page.text == 'one "two"'
        assert page.ta._vim_register == register

        await page.press("u")
        assert page.text == "one two"
        assert page.ta._vim_register == register


async def test_dot_repeats_charwise_visual_surround_shape() -> None:
    async with PromptPage("ab cd ef") as page:
        await page.press("v", "l", "S", '"')
        page.cursor = (0, 5)

        await page.press(".")

        assert page.text == '"ab" "cd" ef'
        assert page.cursor == (0, 5)


async def test_dot_repeats_vline_visual_surround_shape() -> None:
    async with PromptPage("a\nb\nc\nd\ne", cursor=(1, 0)) as page:
        await page.press("V", "j", "S", ")")
        page.cursor = (3, 0)

        await page.press(".")

        assert page.text == "a\n(b\nc)\n(d\ne)"
        assert page.cursor == (3, 0)


async def test_dot_count_scales_saved_visual_surround_shape() -> None:
    async with PromptPage("ab cdef gh") as page:
        await page.press("v", "l", "S", "*")
        page.cursor = (0, 5)

        await page.press("2", ".")

        assert page.text == "*ab* *cdef* gh"
        assert page.cursor == (0, 5)


async def test_visual_lowercase_s_keeps_change_semantics() -> None:
    async with PromptPage("abc") as page:
        await page.press("v", "l", "s")

        assert page.text == "c"
        assert page.mode == "insert"
