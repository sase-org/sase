"""Interactive prompt input search tests."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets._jinja_highlight import _MAX_OVERLAY_LINES
from sase.ace.tui.widgets._vim_search import PromptSearchQuery
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _PromptSearchApp(App[None]):
    """Host a prompt bar and app-level slash/question-mark bindings."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        ("slash", "edit_query", "Edit Query"),
        ("question_mark", "show_help", "Help"),
    ]

    def __init__(self, initial_value: str) -> None:
        super().__init__()
        self._initial_value = initial_value
        self.edit_query_count = 0
        self.show_help_count = 0
        self.notifications: list[str] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._initial_value)

    def action_edit_query(self) -> None:
        self.edit_query_count += 1

    def action_show_help(self) -> None:
        self.show_help_count += 1

    def notify(self, message: str, *args: object, **kwargs: object) -> None:
        self.notifications.append(message)


def _search_panel(bar: PromptInputBar) -> Static:
    return bar.query_one("#prompt-search-command", Static)


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


async def test_forward_search_previews_confirms_and_records_search_register() -> None:
    app = _PromptSearchApp("alpha beta alpha")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)

        await pilot.press("slash", "a", "l", "p", "h", "a")
        await pilot.pause()

        panel = _search_panel(bar)
        assert text_area.cursor_location == (0, 11)
        assert not panel.has_class("hidden")
        assert "/alpha" in panel.render().plain
        assert "[2/2]" in panel.render().plain
        assert text_area._search_match_spans == ((0, 5), (11, 16))
        assert app.edit_query_count == 0

        await pilot.press("enter")
        await pilot.pause()

        assert text_area.cursor_location == (0, 11)
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )
        assert text_area._is_prompt_search_active() is False
        assert panel.has_class("hidden")


async def test_reverse_search_previews_previous_match_without_opening_help() -> None:
    app = _PromptSearchApp("alpha beta alpha")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 10)

        await pilot.press("question_mark", "a", "l", "p", "h", "a")
        await pilot.pause()

        panel = _search_panel(bar)
        assert text_area.cursor_location == (0, 0)
        assert "?alpha" in panel.render().plain
        assert "[1/2]" in panel.render().plain
        assert app.show_help_count == 0


async def test_search_updates_counter_as_query_grows_and_shrinks() -> None:
    app = _PromptSearchApp("alpha alp al")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("slash", "a", "l", "p")
        await pilot.pause()
        panel = _search_panel(bar)
        assert "[1/2]" in panel.render().plain

        await pilot.press("backspace")
        await pilot.pause()
        assert "[1/3]" in panel.render().plain

        await pilot.press("z")
        await pilot.pause()
        assert "pattern not found" in panel.render().plain
        assert text_area.cursor_location == (0, 0)


@pytest.mark.parametrize("cancel_key", ["escape", "ctrl+c"])
async def test_search_cancel_restores_origin_and_clears_highlights(
    cancel_key: str,
) -> None:
    app = _PromptSearchApp("zero alpha alpha")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 6)

        await pilot.press("slash", "a", "l", "p", "h", "a")
        await pilot.pause()
        assert text_area.cursor_location == (0, 11)
        assert text_area._search_match_spans

        await pilot.press(cancel_key)
        await pilot.pause()

        assert text_area.cursor_location == (0, 6)
        assert text_area._search_match_spans == ()
        assert bar.prompt_search_register() is None
        assert _search_panel(bar).has_class("hidden")


async def test_search_entry_keys_do_not_bubble_to_app_bindings() -> None:
    app = _PromptSearchApp("alpha beta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("escape")

        await pilot.press("slash")
        await pilot.press("escape")
        await pilot.press("question_mark")
        await pilot.press("escape")
        await pilot.pause()

    assert app.edit_query_count == 0
    assert app.show_help_count == 0


async def test_repeat_search_n_and_shift_n_respect_recorded_direction() -> None:
    app = _PromptSearchApp("alpha beta alpha beta alpha")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)

        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()
        assert text_area.cursor_location == (0, 11)

        await pilot.press("n")
        await pilot.pause()
        assert text_area.cursor_location == (0, 22)
        assert text_area._search_current_match_index == 2

        await pilot.press("N")
        await pilot.pause()
        assert text_area.cursor_location == (0, 11)
        assert text_area._search_current_match_index == 1


async def test_normal_mode_escape_clears_highlights_but_keeps_repeat_search() -> None:
    app = _PromptSearchApp("alpha beta alpha beta alpha")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)

        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()
        assert text_area.cursor_location == (0, 11)
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )
        assert text_area._search_match_spans == ((0, 5), (11, 16), (22, 27))
        assert any(name.startswith("search.") for name in _highlight_names(text_area))

        await pilot.press("escape")
        await pilot.pause()
        assert text_area.cursor_location == (0, 11)
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )
        assert text_area._search_match_spans == ()
        assert not any(
            name.startswith("search.") for name in _highlight_names(text_area)
        )

        await pilot.press("n")
        await pilot.pause()
        assert text_area.cursor_location == (0, 22)
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )
        assert text_area._search_match_spans == ((0, 5), (11, 16), (22, 27))
        assert text_area._search_current_match_index == 2
        assert any(name.startswith("search.") for name in _highlight_names(text_area))


async def test_repeat_search_wraps_with_vim_style_feedback() -> None:
    app = _PromptSearchApp("alpha beta alpha")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)

        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.press("n")
        await pilot.pause()

        assert text_area.cursor_location == (0, 0)
        assert app.notifications[-1] == "search hit BOTTOM, continuing at TOP"

        await pilot.press("N")
        await pilot.pause()

        assert text_area.cursor_location == (0, 11)
        assert app.notifications[-1] == "search hit TOP, continuing at BOTTOM"


async def test_repeat_search_without_previous_search_is_hint_only() -> None:
    app = _PromptSearchApp("alpha beta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 3)

        await pilot.press("n")
        await pilot.pause()

        assert text_area.cursor_location == (0, 3)
        assert text_area._search_match_spans == ()
        assert app.notifications[-1] == "no previous search"


async def test_repeat_search_reports_not_found_after_buffer_changes() -> None:
    app = _PromptSearchApp("alpha beta alpha")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()

        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )
        text_area.load_text("beta only")
        text_area.cursor_location = (0, 0)
        await pilot.press("n")
        await pilot.pause()

        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )
        assert text_area._search_match_spans == ()
        assert app.notifications[-1] == "pattern not found"


async def test_search_highlights_clear_on_insert_mode_entry() -> None:
    app = _PromptSearchApp("alpha beta alpha")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()
        assert text_area._search_match_spans

        await pilot.press("i")
        await pilot.pause()

        assert text_area._vim_mode == "insert"
        assert text_area._search_match_spans == ()


async def test_forward_search_register_is_shared_across_prompt_panes() -> None:
    app = _PromptSearchApp("top alpha alpha\n---\nbottom alpha alpha")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bottom = bar.active_text_area()
        await pilot.press("escape")
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )
        assert bottom._search_match_spans

        await pilot.press("g", "k")
        await pilot.pause()

        top = bar.active_text_area()
        assert bar._stack.selected_index == 0
        assert top is not bottom
        assert bottom._search_match_spans == ()
        assert _search_panel(bar).has_class("hidden")

        await pilot.press("n")
        await pilot.pause()

        assert top.cursor_location == (0, 4)
        assert top._search_match_spans == ((4, 9), (10, 15))
        assert top._search_current_match_index == 0
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )


async def test_forward_repeats_cross_panes_and_skip_panes_without_matches() -> None:
    app = _PromptSearchApp(
        "alpha alpha\n---\nno matching text\n---\nbottom alpha alpha"
    )

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape", "g", "k", "g", "k")
        await pilot.pause()

        top = bar.active_text_area()
        assert bar._stack.selected_index == 0
        top.cursor_location = (0, 0)
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.press("n")
        await pilot.pause()

        assert bar._stack.selected_index == 0
        assert top.cursor_location == (0, 6)
        assert app.notifications == []

        await pilot.press("n")
        await pilot.pause()

        bottom = bar.active_text_area()
        assert bar._stack.selected_index == 2
        assert bottom is not top
        assert bottom.cursor_location == (0, 7)
        assert bottom._vim_mode == "normal"
        assert app.focused is bottom
        assert top._search_match_spans == ()
        assert not any(name.startswith("search.") for name in _highlight_names(top))
        assert bottom._search_match_spans == ((7, 12), (13, 18))
        assert bottom._search_current_match_index == 0
        assert any(
            name.startswith("search.current") for name in _highlight_names(bottom)
        )
        assert app.notifications == []


async def test_reverse_repeats_cross_to_earlier_pane_and_shift_n_inverts() -> None:
    app = _PromptSearchApp(
        "alpha top alpha\n---\nno matching text\n---\nalpha lower alpha"
    )

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bottom = bar.active_text_area()
        await pilot.press("escape")
        await pilot.press("question_mark", "a", "l", "p", "h", "a", "enter")
        await pilot.press("n", "n")
        await pilot.pause()

        top = bar.active_text_area()
        assert bar._stack.selected_index == 0
        assert top is not bottom
        assert top.cursor_location == (0, 10)
        assert top._search_current_match_index == 1
        assert app.notifications == []

        await pilot.press("N")
        await pilot.pause()

        assert bar._stack.selected_index == 2
        assert bar.active_text_area() is bottom
        assert bottom.cursor_location == (0, 0)
        assert bottom._search_current_match_index == 0
        assert top._search_match_spans == ()
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="reverse"
        )
        assert app.notifications == []


async def test_counted_repeat_advances_across_multiple_prompt_panes() -> None:
    app = _PromptSearchApp(
        "alpha alpha\n---\nno matching text\n---\nbottom alpha alpha"
    )

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape", "g", "k", "g", "k")
        await pilot.pause()

        top = bar.active_text_area()
        top.cursor_location = (0, 0)
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.press("3", "n")
        await pilot.pause()

        bottom = bar.active_text_area()
        assert bar._stack.selected_index == 2
        assert bottom.cursor_location == (0, 13)
        assert bottom._search_current_match_index == 1
        assert top._search_match_spans == ()
        assert app.notifications == []


async def test_prompt_stack_wrap_feedback_only_reports_global_boundaries() -> None:
    app = _PromptSearchApp("alpha top\n---\nbottom alpha")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape", "g", "k")
        await pilot.pause()

        top = bar.active_text_area()
        top.cursor_location = (0, 0)
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.press("n")
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert app.notifications == []

        await pilot.press("n")
        await pilot.pause()

        assert bar._stack.selected_index == 0
        assert app.notifications[-1] == "search hit BOTTOM, continuing at TOP"

        await pilot.press("N")
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert app.notifications[-1] == "search hit TOP, continuing at BOTTOM"


async def test_reverse_search_register_direction_is_shared_across_panes() -> None:
    app = _PromptSearchApp("alpha one alpha two alpha\n---\nalpha lower alpha")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bottom = bar.active_text_area()
        await pilot.press("escape")

        await pilot.press("question_mark", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()

        assert bottom.cursor_location == (0, 12)
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="reverse"
        )

        await pilot.press("g", "k", "n")
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert bar.active_text_area() is bottom
        assert bottom.cursor_location == (0, 12)
        assert bottom._search_current_match_index == 1
        assert app.notifications[-1] == "search hit TOP, continuing at BOTTOM"

        await pilot.press("N")
        await pilot.pause()

        top = bar.active_text_area()
        assert bar._stack.selected_index == 0
        assert top.cursor_location == (0, 0)
        assert top._search_current_match_index == 0
        assert app.notifications[-1] == "search hit BOTTOM, continuing at TOP"
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="reverse"
        )


async def test_search_register_survives_prompt_stack_rebuild() -> None:
    app = _PromptSearchApp("top alpha\n---\nbottom alpha alpha")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        original = bar.active_text_area()
        await pilot.press("escape")
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()

        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )

        await pilot.press("g", "K")
        await pilot.pause()

        rebuilt = bar.active_text_area()
        assert rebuilt is not original
        assert rebuilt.text == "bottom alpha alpha"
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )

        await pilot.press("n")
        await pilot.pause()

        destination = bar.active_text_area()
        assert destination is not rebuilt
        assert destination.text == "top alpha"
        assert destination.cursor_location == (0, 4)
        assert destination._search_current_match_index == 0
        assert rebuilt._search_match_spans == ()
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )


async def test_cancel_failed_search_and_missing_pane_keep_search_register() -> None:
    app = _PromptSearchApp("target has no match\n---\nalpha beta alpha")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bottom = bar.active_text_area()
        await pilot.press("escape")
        bottom.cursor_location = (0, 1)
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()

        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )

        await pilot.press("slash", "b", "e", "t", "a", "escape")
        await pilot.pause()
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )

        await pilot.press("slash", "m", "i", "s", "s", "i", "n", "g", "enter")
        await pilot.pause()
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )

        await pilot.press("g", "k", "n")
        await pilot.pause()

        assert bar._stack.selected_index == 1
        assert bar.active_text_area() is bottom
        assert bottom.cursor_location == (0, 0)
        assert bottom._search_current_match_index == 0
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )


async def test_repeat_absent_from_every_pane_keeps_focus_cursor_and_register() -> None:
    app = _PromptSearchApp("top alpha\n---\nbottom alpha")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bottom = bar.active_text_area()
        await pilot.press("escape")
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()

        assert bottom._search_match_spans
        panes = list(bar.query(PromptTextArea))
        panes[0].load_text("top without the query")
        panes[1].load_text("bottom without the query")
        bottom.cursor_location = (0, 3)
        selected_index = bar._stack.selected_index
        focused = app.focused

        await pilot.press("n")
        await pilot.pause()

        assert bar._stack.selected_index == selected_index
        assert bar.active_text_area() is bottom
        assert app.focused is focused
        assert bottom.cursor_location == (0, 3)
        assert bar.prompt_search_register() == PromptSearchQuery(
            query="alpha", direction="forward"
        )
        assert all(pane._search_match_spans == () for pane in panes)
        assert app.notifications[-1] == "pattern not found"


async def test_large_buffer_search_jumps_even_when_overlay_is_skipped() -> None:
    app = _PromptSearchApp(
        "first needle\n" + ("filler\n" * (_MAX_OVERLAY_LINES + 1)) + "last needle"
    )

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")

        await pilot.press("slash", "n", "e", "e", "d", "l", "e")
        await pilot.pause()

        assert text_area.cursor_location == (0, 6)
        assert text_area._search_match_spans
        assert not any(
            name.startswith("search.") for name in _highlight_names(text_area)
        )
