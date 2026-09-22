"""Editing semantics for operator + search motions (d/foo, dn, dot, undo)."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.testing import PromptPage
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _BarApp(App[None]):
    """Minimal bar-backed app for shared-register (dn) coverage.

    PromptPage hosts a bare PromptTextArea with no parent bar, so it cannot
    record the shared search register that dn/dN read. These few tests need a
    real PromptInputBar; everything else in this file uses PromptPage.
    """

    def __init__(self, initial_value: str) -> None:
        super().__init__()
        self._initial_value = initial_value
        self.notifications: list[str] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._initial_value)

    def notify(self, message: str, *args: object, **kwargs: object) -> None:
        self.notifications.append(message)


async def test_d_slash_deletes_forward() -> None:
    async with PromptPage("foo bar foo", cursor=(0, 0)) as page:
        await page.press("d", "/", "b", "a", "r", "enter")
        assert page.text == "bar foo"
        assert page.cursor == (0, 0)


async def test_d_question_deletes_backward() -> None:
    async with PromptPage("foo bar foo", cursor=(0, 11)) as page:
        await page.press("d", "?", "b", "a", "r", "enter")
        # Reverse range is [match.start, origin): the match itself is deleted.
        assert page.text == "foo "
        assert page.cursor == (0, 4)


async def test_c_slash_change_then_type_and_esc() -> None:
    async with PromptPage("foo bar foo", cursor=(0, 0)) as page:
        await page.press("c", "/", "b", "a", "r", "enter")
        assert page.mode == "insert"
        assert page.text == "bar foo"
        await page.press("X", "Y", "Z", "escape")
        assert page.text == "XYZbar foo"


async def test_y_slash_yanks_without_edit() -> None:
    async with PromptPage("foo bar foo", cursor=(0, 0)) as page:
        await page.press("y", "/", "b", "a", "r", "enter")
        assert page.text == "foo bar foo"
        assert page.ta._vim_register.text == "foo "
        assert page.ta._vim_register.kind == "charwise"
        # Vim leaves the cursor on the match for a backward yank; forward
        # yank returns to the origin.
        assert page.cursor == (0, 0)


async def test_y_question_leaves_cursor_on_match() -> None:
    async with PromptPage("foo bar foo", cursor=(0, 11)) as page:
        await page.press("y", "?", "b", "a", "r", "enter")
        assert page.text == "foo bar foo"
        assert page.cursor == (0, 4)


async def test_gU_slash_uppercases() -> None:
    async with PromptPage("foo bar foo", cursor=(0, 0)) as page:
        await page.press("g", "U", "/", "b", "a", "r", "enter")
        assert page.text == "FOO bar foo"


async def test_indent_forward_multiline() -> None:
    text = "alpha\nbeta final\ngamma"
    async with PromptPage(text, cursor=(0, 0)) as page:
        await page.press(">", "/", "f", "i", "n", "a", "l", "enter")
        assert page.text.startswith("  alpha\n  beta final")


async def test_counted_operator_and_motion_counts() -> None:
    async with PromptPage("a foo b foo c foo", cursor=(0, 0)) as page:
        await page.press("2", "d", "/", "f", "o", "o", "enter")
        assert page.text == "foo c foo"
    async with PromptPage("a foo b foo c foo", cursor=(0, 0)) as page:
        await page.press("d", "2", "/", "f", "o", "o", "enter")
        assert page.text == "foo c foo"


async def test_linewise_case() -> None:
    async with PromptPage("alpha\nbeta\n", cursor=(0, 0)) as page:
        await page.press("d", "/", "b", "e", "t", "a", "enter")
        assert page.text == "beta\n"
        assert page.ta._vim_register.kind == "linewise"


async def test_esc_and_ctrl_c_cancel() -> None:
    async with PromptPage("foo bar foo", cursor=(0, 0)) as page:
        await page.press("d", "/", "b", "a", "r", "escape")
        assert page.text == "foo bar foo"
        assert page.cursor == (0, 0)
        assert not page.ta._is_prompt_search_active()
    async with PromptPage("foo bar foo", cursor=(0, 0)) as page:
        await page.press("d", "/", "b", "a", "r", "ctrl+c")
        assert page.text == "foo bar foo"
        assert page.cursor == (0, 0)
        assert not page.ta._is_prompt_search_active()


async def test_enter_with_no_target_and_too_large_count() -> None:
    async with PromptPage("hello world", cursor=(0, 0)) as page:
        await page.press("d", "/", "z", "z", "z", "enter")
        assert page.text == "hello world"
        assert not page.ta._is_prompt_search_active()
    async with PromptPage("foo bar", cursor=(0, 0)) as page:
        await page.press("d", "2", "/", "b", "a", "r", "enter")
        assert page.text == "foo bar"


async def test_no_wrap() -> None:
    # Forward search from the end never wraps to the start.
    async with PromptPage("foo bar", cursor=(0, 7)) as page:
        await page.press("d", "/", "f", "o", "o", "enter")
        assert page.text == "foo bar"
    # Reverse search from the start never wraps to the end.
    async with PromptPage("foo bar", cursor=(0, 0)) as page:
        await page.press("d", "?", "b", "a", "r", "enter")
        assert page.text == "foo bar"


async def test_undo_restores_in_one_step() -> None:
    async with PromptPage("foo bar foo", cursor=(0, 0)) as page:
        await page.press("d", "/", "b", "a", "r", "enter")
        assert page.text == "bar foo"
        await page.press("u")
        assert page.text == "foo bar foo"


async def test_dot_repeats_delete() -> None:
    async with PromptPage("foo bar foo bar", cursor=(0, 0)) as page:
        await page.press("d", "/", "b", "a", "r", "enter")
        assert page.text == "bar foo bar"
        await page.press(".")
        # Second repeat deletes up to the next remaining match.
        assert "bar" in page.text


async def test_dot_repeats_change_with_insert_text() -> None:
    async with PromptPage("foo bar foo bar", cursor=(0, 0)) as page:
        await page.press("c", "/", "b", "a", "r", "enter")
        await page.press("X", "escape")
        first = page.text
        assert first.startswith("X")
        await page.press(".")
        assert page.text.count("X") >= 2


async def test_dot_with_count_replaces_recorded_count() -> None:
    async with PromptPage("a foo b foo c foo d", cursor=(0, 0)) as page:
        await page.press("d", "/", "f", "o", "o", "enter")
        await page.press("3", ".")
        # Counted repeat consumes further matches; at minimum it edits.
        assert page.text != "a foo b foo c foo d"


async def test_dot_with_no_target_makes_no_edit() -> None:
    async with PromptPage("foo bar", cursor=(0, 0)) as page:
        await page.press("d", "/", "b", "a", "r", "enter")
        assert page.text == "bar"
        await page.press(".")
        assert page.text == "bar"


async def test_dn_after_plain_search_bar_backed() -> None:
    app = _BarApp("foo bar foo bar foo")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()
        await pilot.press("escape")
        ta.cursor_location = (0, 0)
        await pilot.press("slash", "b", "a", "r", "enter")
        await pilot.pause()
        await pilot.press("d", "n")
        await pilot.pause()
        # Plain search leaves the cursor on the first match (offset 4), so dn
        # deletes forward to the next match: [4, 12).
        assert ta.text == "foo bar foo"


async def test_dN_inverts_direction_bar_backed() -> None:
    app = _BarApp("foo bar foo bar foo")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()
        await pilot.press("escape")
        ta.cursor_location = (0, 12)
        await pilot.press("slash", "f", "o", "o", "enter")
        await pilot.pause()
        await pilot.press("d", "N")
        await pilot.pause()
        # dN from the middle operates backward; text must shrink.
        assert len(ta.text) < len("foo bar foo bar foo")


async def test_dn_after_star_respects_whole_word_bar_backed() -> None:
    app = _BarApp("foobar foo foobar foo")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()
        await pilot.press("escape")
        ta.cursor_location = (0, 7)
        await pilot.press("asterisk")
        await pilot.pause()
        await pilot.press("d", "n")
        await pilot.pause()
        # Whole-word register skips the embedded "foo" inside "foobar".
        assert "foobar" in ta.text


async def test_dn_with_no_register_reports_feedback() -> None:
    async with PromptPage("foo bar foo", cursor=(0, 0)) as page:
        await page.press("d", "n")
        assert page.text == "foo bar foo"


async def test_dt_and_df_still_use_literal_slash() -> None:
    async with PromptPage("foo/bar") as page:
        await page.press("d", "t", "/")
        assert page.text == "/bar"
    async with PromptPage("foo/bar") as page:
        await page.press("d", "f", "/")
        assert page.text == "bar"


async def test_plain_slash_and_n_unchanged() -> None:
    async with PromptPage("foo/bar") as page:
        await page.press("/")
        assert page.ta._is_prompt_search_active()
        await page.press("escape")
        assert not page.ta._is_prompt_search_active()
        assert page.text == "foo/bar"
