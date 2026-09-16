"""Prompt search match-count readout tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rich.cells import cell_len
from rich.color import Color as RichColor
from textual.app import App, ComposeResult
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets._prompt_search_readout import (
    PromptSearchReadout,
    format_search_readout,
    _display_query,
    _readout_sigil,
    _search_readout_colors,
    stack_match_position,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _PromptSearchReadoutApp(App[None]):
    """Host a prompt bar and app-level slash/question-mark bindings."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        ("slash", "edit_query", "Edit Query"),
        ("question_mark", "show_help", "Help"),
    ]

    def __init__(
        self,
        initial_value: str = "",
        *,
        initial_panes: list[str] | None = None,
        initial_selected_pane: int | None = None,
    ) -> None:
        super().__init__()
        self._initial_value = initial_value
        self._initial_panes = initial_panes
        self._initial_selected_pane = initial_selected_pane
        self.notifications: list[str] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            initial_panes=self._initial_panes,
            initial_selected_pane=self._initial_selected_pane,
        )

    def action_edit_query(self) -> None:
        pass

    def action_show_help(self) -> None:
        pass

    def notify(self, message: str, *args: object, **kwargs: object) -> None:
        self.notifications.append(message)


def _search_panel(bar: PromptInputBar) -> Static:
    return bar.query_one("#prompt-search-command", Static)


def _subtitle_plain(bar: PromptInputBar) -> str:
    return bar._render_subtitle(bar._subtitle_base).plain


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


def _theme(
    *,
    accent: str = "#6B4FBB",
    warning: str = "#FFA62B",
) -> SimpleNamespace:
    return SimpleNamespace(accent=accent, warning=warning)


@pytest.mark.parametrize(
    ("direction", "whole_word", "expected"),
    [
        ("forward", False, "/"),
        ("reverse", False, "?"),
        ("forward", True, "*"),
        ("reverse", True, "#"),
    ],
)
def test_readout_sigil(direction: str, whole_word: bool, expected: str) -> None:
    assert _readout_sigil(direction, whole_word) == expected


def test_display_query_sanitizes_and_elides_by_cell_width() -> None:
    assert _display_query("a\nb\tc\x01") == "a↵b⇥c·"

    value = _display_query("alpha你好omega", max_cells=8)

    assert cell_len(value) <= 8
    assert value.endswith("…")
    assert value.startswith("alpha")


@pytest.mark.parametrize(
    ("counts", "origin", "local", "expected"),
    [
        ((3,), 0, 1, (2, 3)),
        ((2, 0, 3), 2, 1, (4, 5)),
        ((2, 0, 3), 1, None, (None, 5)),
        ((0, 0), 0, None, (None, 0)),
    ],
)
def test_stack_match_position(
    counts: tuple[int, ...],
    origin: int,
    local: int | None,
    expected: tuple[int | None, int],
) -> None:
    assert stack_match_position(counts, origin, local) == expected


def test_format_search_readout_plain_text_and_count_only() -> None:
    readout = PromptSearchReadout(
        query="alpha",
        direction="forward",
        whole_word=False,
        ordinal=2,
        total=3,
        pane_text="alpha beta alpha",
    )

    assert format_search_readout(readout, theme=_theme()).plain == "/alpha  2/3"
    assert (
        format_search_readout(readout, theme=_theme(), include_query=False).plain
        == "2/3"
    )


def test_search_readout_count_background_uses_theme_warning() -> None:
    readout = PromptSearchReadout(
        query="alpha",
        direction="forward",
        whole_word=False,
        ordinal=2,
        total=3,
        pane_text="alpha beta alpha",
    )

    count = format_search_readout(readout, theme=_theme(), include_query=False)

    assert count.style.bgcolor == RichColor.parse("#FFA62B")


def test_query_and_count_backgrounds_differ_when_theme_reuses_colors() -> None:
    query_style, _sigil_style, count_style = _search_readout_colors(
        _theme(accent="#FFA62B", warning="#FFA62B")
    )

    assert query_style.bgcolor != count_style.bgcolor


async def test_typing_count_moves_to_bar_pill_and_repeats_update_it() -> None:
    app = _PromptSearchReadoutApp("alpha beta alpha beta alpha")

    async with app.run_test(size=(88, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)

        await pilot.press("slash", "a", "l", "p", "h", "a")
        await pilot.pause()

        panel = _search_panel(bar)
        panel_plain = panel.render().plain
        assert "2/3" in panel_plain
        assert "[2/3]" not in panel_plain
        assert "/alpha" not in _subtitle_plain(bar)

        await pilot.press("enter")
        await pilot.pause()

        plain = _subtitle_plain(bar)
        assert "/alpha" in plain
        assert plain.index("2/3") < plain.index("Ln ")

        await pilot.press("n")
        await pilot.pause()
        assert "3/3" in _subtitle_plain(bar)

        await pilot.press("N")
        await pilot.pause()
        assert "2/3" in _subtitle_plain(bar)

        await pilot.press("n", "n")
        await pilot.pause()
        assert "1/3" in _subtitle_plain(bar)
        assert app.notifications[-1] == "search hit BOTTOM, continuing at TOP"


async def test_search_readout_clears_and_safety_net_ignores_unchanged_text() -> None:
    app = _PromptSearchReadoutApp("alpha beta alpha")

    async with app.run_test(size=(88, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()

        assert "/alpha" in _subtitle_plain(bar)
        text_area.post_message(TextArea.Changed(text_area))
        await pilot.pause()
        assert "/alpha" in _subtitle_plain(bar)

        text_area.load_text("beta only")
        await pilot.pause()
        assert "/alpha" not in _subtitle_plain(bar)
        assert text_area._search_match_spans == ()
        assert not any(
            name.startswith("search.") for name in _highlight_names(text_area)
        )

        await pilot.press("n")
        await pilot.pause()
        assert "pattern not found" in app.notifications[-1]


async def test_search_readout_clears_on_escape_insert_edit_and_new_search() -> None:
    app = _PromptSearchReadoutApp("alpha beta alpha")

    async with app.run_test(size=(88, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()
        assert "/alpha" in _subtitle_plain(bar)

        await pilot.press("escape")
        await pilot.pause()
        assert "/alpha" not in _subtitle_plain(bar)

        await pilot.press("n", "i")
        await pilot.pause()
        assert "/alpha" not in _subtitle_plain(bar)

        await pilot.press("escape", "n")
        await pilot.pause()
        assert "/alpha" in _subtitle_plain(bar)

        await pilot.press("x")
        await pilot.pause()
        assert "/alpha" not in _subtitle_plain(bar)

        await pilot.press("slash", "a")
        await pilot.pause()
        assert bar._search_command_visible
        assert "/alpha" not in _subtitle_plain(bar)


async def test_word_and_reverse_search_sigils() -> None:
    app = _PromptSearchReadoutApp("alpha beta alpha")

    async with app.run_test(size=(88, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 0)

        await pilot.press("*")
        await pilot.pause()
        assert "*alpha" in _subtitle_plain(bar)

        await pilot.press("escape")
        text_area.cursor_location = (0, 11)
        await pilot.press("#")
        await pilot.pause()
        assert "#alpha" in _subtitle_plain(bar)

        await pilot.press("escape")
        text_area.cursor_location = (0, 0)
        await pilot.press("g", "*")
        await pilot.pause()
        assert "/alpha" in _subtitle_plain(bar)

        await pilot.press("question_mark", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()
        assert "?alpha" in _subtitle_plain(bar)


async def test_multi_pane_stack_global_counts_and_no_local_match_status() -> None:
    app = _PromptSearchReadoutApp(
        initial_panes=["alpha x alpha", "alpha"],
        initial_selected_pane=1,
    )

    async with app.run_test(size=(88, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape")

        await pilot.press("slash", "a", "l", "p", "h", "a")
        await pilot.pause()
        assert "3/3" in _search_panel(bar).render().plain

        await pilot.press("enter")
        await pilot.pause()
        assert "3/3" in _subtitle_plain(bar)

        await pilot.press("n")
        await pilot.pause()
        assert bar._stack.selected_index == 0
        assert "1/3" in _subtitle_plain(bar)

        await pilot.press("n")
        await pilot.pause()
        assert "2/3" in _subtitle_plain(bar)

        bar.focus_item(1)
        await pilot.pause()
        await pilot.press("slash", "x")
        await pilot.pause()
        assert "no match in this pane · 1 in stack" in _search_panel(bar).render().plain


async def test_narrow_subtitle_keeps_count_and_cursor_readout() -> None:
    app = _PromptSearchReadoutApp("alpha beta alpha")

    async with app.run_test(size=(48, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        await pilot.press("escape")
        text_area.cursor_location = (0, 1)
        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()

        plain = _subtitle_plain(bar)
        assert "2/2" in plain
        assert "Ln " in plain


async def test_search_panel_subtitle_renders_literal_enter_hint() -> None:
    app = _PromptSearchReadoutApp("alpha")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await pilot.press("escape", "slash", "a")
        await pilot.pause()

        subtitle = _search_panel(bar).border_subtitle
        plain = subtitle.plain if hasattr(subtitle, "plain") else str(subtitle)
        assert "[enter] accept" in plain
