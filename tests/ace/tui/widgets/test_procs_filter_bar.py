"""Widget-level tests for ``ProcsFilterBar``'s show-while-active resting mode."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.color import Color
from textual.widgets import OptionList, Static

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.modals.procs_filter_bar import ProcsFilterBar
from sase.ace.tui.proc_gear_chips import PROC_GEAR_HUE
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea

_PROFILE = compiled_profile_for_builtin_pane("procs")
assert _PROFILE is not None


class _ProcsFilterBarApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.load_more_calls = 0

    def compose(self) -> ComposeResult:
        yield ProcsFilterBar(profile=_PROFILE)

    def action_artifacts_load_more(self) -> None:
        self.load_more_calls += 1

    def action_artifacts_unload(self) -> None:
        pass


def _option_labels(option_list: OptionList) -> list[str]:
    return [
        option_list.get_option_at_index(index).prompt.plain
        for index in range(option_list.option_count)
    ]


def test_accent_is_the_procs_teal() -> None:
    assert ProcsFilterBar().ACCENT == PROC_GEAR_HUE == "#48CAE4"


async def test_bar_is_hidden_at_rest_with_an_empty_query() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test():
        bar = app.query_one(ProcsFilterBar)
        assert bar.display is False


async def test_bar_becomes_visible_and_read_only_once_a_query_is_set() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test():
        bar = app.query_one(ProcsFilterBar)
        bar.set_query("monitor")
        assert bar.display is True
        display = bar.query_one(f"#{bar.DISPLAY_ID}", Static)
        editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)
        assert display.display is True
        assert display.render().plain == "monitor"
        assert editor.display is False
        assert editor.can_focus is False


async def test_bar_hides_again_once_the_query_is_cleared() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test():
        bar = app.query_one(ProcsFilterBar)
        bar.set_query("monitor")
        assert bar.display is True
        bar.set_query("")
        assert bar.display is False


async def test_open_shows_the_editor_even_with_an_empty_query() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(ProcsFilterBar)
        bar.open("")
        await pilot.pause()
        assert bar.display is True
        editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)
        assert editor.display is True
        assert editor.can_focus is True


async def test_close_after_commit_hides_bar_when_query_ended_up_empty() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(ProcsFilterBar)
        bar.open("")
        await pilot.pause()
        bar.close()
        await pilot.pause()
        assert bar.display is False


async def test_close_after_commit_shows_readonly_display_when_query_is_active() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(ProcsFilterBar)
        bar.open("monitor")
        await pilot.pause()
        bar.close()
        await pilot.pause()
        assert bar.display is True
        editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)
        assert editor.display is False
        assert editor.can_focus is False


async def test_accent_colors_sigil_and_borders_while_active() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test():
        bar = app.query_one(ProcsFilterBar)
        bar.set_query("monitor")
        sigil = bar.query_one(f"#{bar.SIGIL_ID}", Static)
        display = bar.query_one(f"#{bar.DISPLAY_ID}", Static)
        expected = Color.parse(bar.ACCENT)
        assert sigil.styles.color == expected
        assert display.styles.border_top == ("solid", expected)


async def test_ctrl_j_does_not_reach_the_artifacts_paging_action() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(ProcsFilterBar)
        bar.open("")
        await pilot.pause()
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert app.load_more_calls == 0


async def test_bool_field_offers_bare_flag_completion_alongside_the_key() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(ProcsFilterBar)
        bar.open("moni")
        await pilot.pause()
        completion = bar.query_one(f"#{bar.COMPLETION_ID}", OptionList)
        labels = _option_labels(completion)
        assert any(label.startswith("monitor:") for label in labels)
        assert any(
            label.startswith("monitor") and not label.startswith("monitor:")
            for label in labels
        )


async def test_negated_bare_flag_completion_keeps_the_minus() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(ProcsFilterBar)
        bar.open("-moni")
        await pilot.pause()
        completion = bar.query_one(f"#{bar.COMPLETION_ID}", OptionList)
        labels = _option_labels(completion)
        assert any(label.startswith("-monitor:") for label in labels)
        assert any(
            label.startswith("-monitor") and not label.startswith("-monitor:")
            for label in labels
        )


async def test_string_field_offers_no_bare_flag_completion() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(ProcsFilterBar)
        bar.open("nam")
        await pilot.pause()
        completion = bar.query_one(f"#{bar.COMPLETION_ID}", OptionList)
        labels = _option_labels(completion)
        assert labels == ["name:  ·  row label / display name"]


async def test_has_highlighted_completion_tracks_the_completion_menu() -> None:
    app = _ProcsFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(ProcsFilterBar)
        bar.open("moni")
        await pilot.pause()
        assert bar.has_highlighted_completion() is False

        await pilot.press("down")
        await pilot.pause()
        assert bar.has_highlighted_completion() is True

        await pilot.press("escape")
        await pilot.pause()
        assert bar.has_highlighted_completion() is False
