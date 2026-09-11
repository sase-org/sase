"""Widget-level tests for the auto-hiding ``AgentsFilterBar`` (sase-zf.4)."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.color import Color

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.widgets.agents_filter_bar import AgentsFilterBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea

_PROFILE = compiled_profile_for_builtin_pane("agents-live")
assert _PROFILE is not None


class _AgentsFilterBarApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.load_more_calls = 0
        self.prev_query_calls = 0
        self.next_query_calls = 0

    def compose(self) -> ComposeResult:
        yield AgentsFilterBar(profile=_PROFILE)

    def action_artifacts_load_more(self) -> None:
        self.load_more_calls += 1

    def action_artifacts_unload(self) -> None:
        pass

    def action_prev_query(self) -> None:
        self.prev_query_calls += 1

    def action_next_query(self) -> None:
        self.next_query_calls += 1


def test_accent_is_gold() -> None:
    assert AgentsFilterBar().ACCENT == "#FFD700"


def test_neither_persistent_nor_show_when_active() -> None:
    assert AgentsFilterBar.PERSISTENT is False
    assert AgentsFilterBar.SHOW_WHEN_ACTIVE is False


async def test_bar_is_hidden_at_rest_even_with_an_active_query() -> None:
    """Unlike every other pane, an active query never gets its own row."""
    app = _AgentsFilterBarApp()
    async with app.run_test():
        bar = app.query_one(AgentsFilterBar)
        assert bar.display is False
        bar.set_query("status:FAILED")
        assert bar.display is False


async def test_editor_is_not_focusable_at_rest() -> None:
    """Regression guard: a focusable hidden editor steals the app's default
    focus target and disables ``next_tab``/``prev_tab`` (see the widget's
    ``DISPLAY_ID`` docstring)."""
    app = _AgentsFilterBarApp()
    async with app.run_test():
        bar = app.query_one(AgentsFilterBar)
        editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)
        assert editor.can_focus is False
        assert editor.display is False
        assert app.focused is not editor


async def test_open_shows_and_focuses_the_editor() -> None:
    app = _AgentsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(AgentsFilterBar)
        bar.open("status:FAILED")
        await pilot.pause()
        assert bar.display is True
        editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)
        assert editor.display is True
        assert editor.can_focus is True
        assert editor.text == "status:FAILED"
        assert app.focused is editor


async def test_close_hides_the_bar_again_regardless_of_query_text() -> None:
    app = _AgentsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(AgentsFilterBar)
        bar.open("status:FAILED")
        await pilot.pause()
        bar.close()
        await pilot.pause()
        assert bar.display is False
        editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)
        assert editor.can_focus is False
        assert editor.display is False


async def test_accent_colors_sigil_and_input_border_via_css() -> None:
    """``_apply_accent`` never fires (neither PERSISTENT nor SHOW_WHEN_ACTIVE),
    so the gold accent must come from ``styles.tcss`` instead."""
    app = _AgentsFilterBarApp()
    app.stylesheet.add_source(
        """
        AgentsFilterBar .filter-bar-sigil { color: #FFD700; }
        AgentsFilterBar .filter-bar-input { border: solid #FFD700; }
        """,
        read_from=("test", ""),
    )
    async with app.run_test():
        app.stylesheet.apply(app)
        bar = app.query_one(AgentsFilterBar)
        sigil = bar.query_one(f"#{bar.SIGIL_ID}")
        editor = bar.query_one(f"#{bar.INPUT_ID}")
        expected = Color.parse("#FFD700")
        assert sigil.styles.color == expected
        assert editor.styles.border_top == ("solid", expected)


async def test_ctrl_j_does_not_reach_the_artifacts_paging_action() -> None:
    app = _AgentsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(AgentsFilterBar)
        bar.open("")
        await pilot.pause()
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert app.load_more_calls == 0


async def test_history_keys_forward_to_app_actions_instead_of_typing() -> None:
    app = _AgentsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(AgentsFilterBar)
        bar.open("")
        await pilot.pause()
        await pilot.press("circumflex_accent")
        await pilot.press("underscore")
        await pilot.pause()
        assert app.prev_query_calls == 1
        assert app.next_query_calls == 1
        editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)
        assert "^" not in editor.text
        assert "_" not in editor.text


async def test_key_completions_derive_from_the_agents_live_profile() -> None:
    app = _AgentsFilterBarApp()
    async with app.run_test():
        bar = app.query_one(AgentsFilterBar)
        keys = {key for key, _hint in bar.KEY_COMPLETIONS}
        assert "status" in keys
        assert "kind" in keys
        assert "cl" in keys
        assert "tribe" in keys
        # Removed legacy spellings (age/type) never appear in completions.
        assert "age" not in keys
        assert "type" not in keys
