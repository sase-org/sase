"""Bar and panel coverage for operator + search motions."""

from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.search_command_line import render_search_command_line


class _OperatorSearchApp(App[None]):
    """Host a prompt bar plus app-level slash/question bindings."""

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


def _subtitle_plain(bar: PromptInputBar) -> str:
    return bar._render_subtitle(bar._subtitle_base).plain


async def test_operator_panel_chrome_and_destructive_class() -> None:
    app = _OperatorSearchApp("alpha beta final alpha")
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()
        await pilot.press("escape")
        ta.cursor_location = (0, 0)
        await pilot.press("d", "slash", "f", "i", "n", "a", "l")
        await pilot.pause()
        panel = _search_panel(bar)
        plain = panel.render().plain
        assert "d" in plain
        assert "/final" in plain
        assert panel.border_title == "delete to match"
        subtitle = panel.border_subtitle
        sub_plain = subtitle.plain if hasattr(subtitle, "plain") else str(subtitle)
        assert "[enter] delete" in sub_plain
        assert panel.has_class("operator-destructive")
        assert not panel.has_class("hidden")
        assert app.edit_query_count == 0
        assert app.show_help_count == 0


async def test_yank_panel_uses_yank_class() -> None:
    app = _OperatorSearchApp("alpha beta final alpha")
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()
        await pilot.press("escape")
        ta.cursor_location = (0, 0)
        await pilot.press("y", "slash", "f", "i", "n", "a", "l")
        await pilot.pause()
        panel = _search_panel(bar)
        assert panel.has_class("operator-yank")
        assert panel.border_title == "yank to match"


async def test_effect_summary_and_pane_local_count() -> None:
    app = _OperatorSearchApp("alpha beta final alpha")
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()
        await pilot.press("escape")
        ta.cursor_location = (0, 0)
        await pilot.press("d", "slash", "f", "i", "n", "a", "l")
        await pilot.pause()
        plain = _search_panel(bar).render().plain
        assert "delete" in plain
        assert "chars" in plain or "char" in plain
        # Pane-local count for the single "final" match.
        assert "1/1" in plain


async def test_miss_messages_shown_in_panel() -> None:
    app = _OperatorSearchApp("hello world")
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()
        await pilot.press("escape")
        ta.cursor_location = (0, 0)
        await pilot.press("d", "slash", "z", "z", "z")
        await pilot.pause()
        assert "pattern not found" in _search_panel(bar).render().plain


async def test_region_span_style_and_preview_cursor() -> None:
    app = _OperatorSearchApp("foo bar foo")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()
        await pilot.press("escape")
        ta.cursor_location = (0, 0)
        await pilot.press("d", "slash", "b", "a", "r")
        await pilot.pause()
        region = ta._search_operator_region
        assert region is not None
        start, end, style_name = region
        assert (start, end) == (0, 4)
        assert style_name == "search.operator.destructive"
        # Other matches highlighted; preview cursor sits on the target.
        assert ta._search_match_spans == ((4, 7),)
        assert ta.cursor_location == (0, 4)


async def test_enter_does_not_submit_and_pill_absent() -> None:
    app = _OperatorSearchApp("foo bar foo")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()
        await pilot.press("escape")
        ta.cursor_location = (0, 0)
        await pilot.press("d", "slash", "b", "a", "r")
        await pilot.pause()
        # Pill absent during the operator search.
        assert "/bar" not in _subtitle_plain(bar)
        await pilot.press("enter")
        await pilot.pause()
        assert ta.text == "bar foo"
        assert not ta._is_prompt_search_active()
        # Pill still absent after an operator edit.
        assert "/bar" not in _subtitle_plain(bar)
        assert _search_panel(bar).has_class("hidden")


async def test_register_recorded_so_following_n_works() -> None:
    app = _OperatorSearchApp("foo bar foo bar foo")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()
        await pilot.press("escape")
        ta.cursor_location = (0, 0)
        await pilot.press("y", "slash", "b", "a", "r", "enter")
        await pilot.pause()
        assert bar.prompt_search_register() is not None
        assert bar.prompt_search_register().query == "bar"
        first = ta.cursor_location
        await pilot.press("n")
        await pilot.pause()
        assert ta.cursor_location != first


async def test_operator_classes_removed_on_hide() -> None:
    app = _OperatorSearchApp("foo bar foo")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()
        await pilot.press("escape")
        ta.cursor_location = (0, 0)
        await pilot.press("d", "slash", "b", "a", "r")
        await pilot.pause()
        panel = _search_panel(bar)
        assert panel.has_class("operator-destructive")
        await pilot.press("escape")
        await pilot.pause()
        assert panel.has_class("hidden")
        assert not panel.has_class("operator-destructive")
        assert not panel.has_class("operator-yank")
        assert not panel.has_class("operator-transform")


async def test_pattern_only_in_other_pane_reports_not_found() -> None:
    app = _OperatorSearchApp("alpha top alpha\n---\nno matching text here")
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bottom = bar.active_text_area()
        assert bar._stack.selected_index == 1
        await pilot.press("escape")
        await pilot.press("d", "slash", "a", "l", "p", "h", "a")
        await pilot.pause()
        assert "pattern not found" in _search_panel(bar).render().plain
        await pilot.press("enter")
        await pilot.pause()
        assert bottom.text == "no matching text here"
        assert bar._stack.selected_index == 1


def test_render_search_command_line_with_prefix_and_narrow_width() -> None:
    prefix = Text(no_wrap=True)
    prefix.append("d ", style="bold")
    full = render_search_command_line(
        direction="forward",
        query="final",
        current_index=None,
        total=0,
        width=120,
        status=Text("delete 10 chars", no_wrap=True),
        prefix=prefix,
    )
    assert "d " in full.plain
    assert "/final" in full.plain
    assert "delete 10 chars" in full.plain

    narrow = render_search_command_line(
        direction="forward",
        query="final",
        current_index=None,
        total=0,
        width=10,
        status=Text("delete 10 chars", no_wrap=True),
        prefix=prefix,
    )
    # Narrow widths never wrap mid-word; the renderer crops via overflow.
    assert "/final" in narrow.plain

    plain = render_search_command_line(
        direction="forward",
        query="alpha",
        current_index=0,
        total=2,
        width=80,
    )
    assert "1/2" in plain.plain or "2" in plain.plain
