"""Direct coverage for ``SingleLineVimTextArea`` (the ``Input`` replacement)."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.testing import VimEditorPage
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea

_ROOT = Path(__file__).resolve().parents[4]
_LONG_VALUE = "alpha beta gamma delta epsilon zeta eta theta iota kappa"


class _PlaceholderApp(App[None]):
    """Minimal app for rendering placeholder text."""

    CSS = """
    SingleLineVimTextArea {
        width: 100%;
        height: 3;
        border: solid white;
    }
    """

    def compose(self) -> ComposeResult:
        yield SingleLineVimTextArea("", placeholder="Type a value", id="ed")


class _WrappedSingleLineVimTextArea(SingleLineVimTextArea):
    """Single-line editor host that opts into a wrapped display."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("soft_wrap", True)
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]


class _NarrowSingleLineApp(App[None]):
    """Narrow non-wrapping editor with the production stylesheet."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
    CSS = """
    #ed {
        width: 22;
    }
    """

    def compose(self) -> ComposeResult:
        yield SingleLineVimTextArea(_LONG_VALUE, id="ed")


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


async def test_placeholder_renders_in_insert_and_normal_mode() -> None:
    app = _PlaceholderApp()
    async with app.run_test(size=(40, 8)) as pilot:
        editor = app.query_one("#ed", SingleLineVimTextArea)
        editor.focus()
        await pilot.pause()
        insert_screen = "\n".join(editor.render_line(y).text for y in range(3))
        assert "Type a value" in insert_screen

        editor._enter_normal_mode()
        await pilot.pause()
        normal_screen = "\n".join(editor.render_line(y).text for y in range(3))
        assert "Type a value" in normal_screen


async def test_soft_wrap_preserves_single_logical_line_editing_contract() -> None:
    async with VimEditorPage(
        _LONG_VALUE,
        cursor=(0, 12),
        mode="insert",
        size=(24, 10),
        widget_cls=_WrappedSingleLineVimTextArea,
    ) as page:
        assert page.ta.wrapped_document.height > 1

        await page.press("ctrl+a")
        assert page.cursor == (0, 0)
        await page.press("ctrl+e")
        assert page.cursor == (0, len(_LONG_VALUE))

        await page.press("escape", "0")
        assert page.cursor == (0, 0)
        await page.press("$")
        assert page.cursor == (0, len(_LONG_VALUE))

        await page.press("0", "d", "w")
        assert page.text == "beta gamma delta epsilon zeta eta theta iota kappa"

        await page.press("y", "y", "p")
        await page.pause()
        assert page.ta.document.line_count == 1
        assert "\n" not in page.text

        await page.press("enter")
        await page.pause()
        assert page.submitted == [page.text]


async def test_zero_size_scrollbars_preserve_nonwrapping_content_row() -> None:
    app = _NarrowSingleLineApp()
    async with app.run_test(size=(40, 8)) as pilot:
        editor = app.query_one("#ed", SingleLineVimTextArea)
        editor.focus()
        await pilot.press("ctrl+e")
        await pilot.pause()

        rendered_at_end = editor.render_line(0).text
        assert editor.soft_wrap is False
        assert editor.styles.scrollbar_size_horizontal == 0
        assert editor.styles.scrollbar_size_vertical == 0
        assert editor.show_horizontal_scrollbar is True
        assert editor.scrollable_content_region.height == 1
        assert editor.scroll_offset.x > 0
        assert "kappa" in rendered_at_end

        await pilot.press("ctrl+a")
        await pilot.pause()
        rendered_at_start = editor.render_line(0).text
        assert editor.scroll_offset.x == 0
        assert "alpha" in rendered_at_start
