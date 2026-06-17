"""Interactive prompt input search tests."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


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

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._initial_value)

    def action_edit_query(self) -> None:
        self.edit_query_count += 1

    def action_show_help(self) -> None:
        self.show_help_count += 1


def _search_panel(bar: PromptInputBar) -> Static:
    return bar.query_one("#prompt-search-command", Static)


async def test_forward_search_previews_confirms_and_records_last_search() -> None:
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
        assert text_area._last_search == ("alpha", "forward")
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
        assert text_area._last_search is None
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
