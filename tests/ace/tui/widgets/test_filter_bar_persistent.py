"""Widget-level tests for the shared persistent-bar idle chrome."""

from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.color import Color
from textual.widgets import Static

from sase.ace.query_profile import (
    compile_query_profile,
    compiled_profile_for_builtin_pane,
)
from sase.ace.query_profile.profiles import beads_query_schema
from sase.ace.tui.widgets.artifacts.commit_filter_bar import CommitFilterBar
from sase.ace.tui.widgets.artifacts.patch_filter_bar import PatchFilterBar
from sase.ace.tui.widgets.filter_bar import FilterBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea

_BEADS_PROFILE = compile_query_profile(beads_query_schema())


class _PersistentTestBar(FilterBar):
    """Minimal persistent bar for exercising the shared base-class chrome."""

    PERSISTENT: ClassVar[bool] = True
    DISPLAY_ID: ClassVar[str | None] = "test-filter-display"
    ACCENT = "#00D7AF"


class _PersistentTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.clicks = 0

    def compose(self) -> ComposeResult:
        yield _PersistentTestBar(profile=_BEADS_PROFILE)

    def on_filter_bar_clicked(self, event: FilterBar.Clicked) -> None:
        del event
        self.clicks += 1


async def test_idle_persistent_bar_shows_display_and_hides_unfocusable_editor() -> None:
    app = _PersistentTestApp()
    async with app.run_test():
        bar = app.query_one(_PersistentTestBar)
        display = bar.query_one("#test-filter-display", Static)
        editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)

        assert display.display is True
        assert editor.display is False
        assert editor.can_focus is False


async def test_open_reverses_idle_display_and_close_restores_it() -> None:
    app = _PersistentTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(_PersistentTestBar)
        display = bar.query_one("#test-filter-display", Static)
        editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)

        bar.open("status:open")
        await pilot.pause()
        assert editor.display is True
        assert editor.can_focus is True
        assert display.display is False

        bar.close()
        await pilot.pause()
        assert editor.display is False
        assert editor.can_focus is False
        assert display.display is True


async def test_empty_query_renders_free_text_hint_placeholder() -> None:
    app = _PersistentTestApp()
    async with app.run_test():
        bar = app.query_one(_PersistentTestBar)
        display = bar.query_one("#test-filter-display", Static)
        assert display.render().plain == _BEADS_PROFILE.free_text_hint


async def test_nonempty_query_renders_highlighted_committed_text() -> None:
    app = _PersistentTestApp()
    async with app.run_test():
        bar = app.query_one(_PersistentTestBar)
        bar.set_query("status:open")
        display = bar.query_one("#test-filter-display", Static)
        assert display.render().plain == "status:open"


async def test_clicking_idle_bar_posts_clicked() -> None:
    app = _PersistentTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(_PersistentTestBar)
        await pilot.click(bar)
        await pilot.pause()
        assert app.clicks == 1


async def test_clicking_open_bar_does_not_post_clicked() -> None:
    app = _PersistentTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(_PersistentTestBar)
        bar.open("")
        await pilot.pause()

        await pilot.click(bar)
        await pilot.pause()

        assert app.clicks == 0
        assert bar._editing  # type: ignore[attr-defined]


async def test_idle_bar_resolves_border_and_sigil_colors_from_accent() -> None:
    app = _PersistentTestApp()
    async with app.run_test():
        bar = app.query_one(_PersistentTestBar)
        sigil = bar.query_one(f"#{bar.SIGIL_ID}", Static)
        editor = bar.query_one(f"#{bar.INPUT_ID}", SingleLineVimTextArea)
        display = bar.query_one("#test-filter-display", Static)
        completion = bar.query_one(f"#{bar.COMPLETION_ID}")

        expected = Color.parse(bar.ACCENT)
        assert sigil.styles.color == expected
        assert editor.styles.border_top == ("solid", expected)
        assert display.styles.border_top == ("solid", expected)
        assert completion.styles.border_top == ("solid", expected)


async def test_stitch_bar_shows_no_normal_title_while_idle() -> None:
    app_bar = CommitFilterBar()

    class _App(App[None]):
        ENABLE_COMMAND_PALETTE = False

        def compose(self) -> ComposeResult:
            yield app_bar

    async with _App().run_test():
        editor = app_bar.query_one(f"#{app_bar.INPUT_ID}", SingleLineVimTextArea)
        assert editor.display is False
        assert not editor.border_title


async def test_patch_bar_closed_display_comes_from_shared_path() -> None:
    profile = compiled_profile_for_builtin_pane("patches")
    assert profile is not None
    app_bar = PatchFilterBar(profile=profile)

    class _App(App[None]):
        ENABLE_COMMAND_PALETTE = False

        def compose(self) -> ComposeResult:
            yield app_bar

    async with _App().run_test():
        display = app_bar.query_one(f"#{app_bar.DISPLAY_ID}", Static)
        assert display.render().plain == profile.free_text_hint

        app_bar.set_query('status:"WIP"')
        assert display.render().plain == 'status:"WIP"'
