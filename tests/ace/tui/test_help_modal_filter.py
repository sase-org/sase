"""Integration tests for the Help panel's live keymap filter bar."""

from __future__ import annotations

from textual.containers import Horizontal
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals import HelpModal
from sase.ace.tui.modals.help_modal.filter_bar import HelpFilterInput


def _modal(page: AcePage) -> HelpModal:
    modal = page.app.screen_stack[-1]
    assert isinstance(modal, HelpModal)
    return modal


def _static_plain(modal: HelpModal, selector: str) -> str:
    widget = modal.query_one(selector, Static)
    content = widget.content
    return getattr(content, "plain", str(content))


def _combined_columns(modal: HelpModal) -> str:
    return _static_plain(modal, "#help-left-column") + _static_plain(
        modal, "#help-right-column"
    )


def _help_title(page: AcePage) -> str:
    return _static_plain(_modal(page), "#help-title")


async def test_slash_opens_and_focuses_filter_bar() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        modal = _modal(page)

        await page.press("slash")
        await page.wait_for(
            lambda _s: (
                page.app.focused is not None
                and page.app.focused.id == "help-filter-input"
            )
        )

        bar = modal.query_one("#help-filter-bar", Horizontal)
        assert bar.display is True


async def test_typing_live_filters_columns_and_status() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        modal = _modal(page)
        modal.action_focus_filter()

        await page.press("b", "e", "a", "d", "s")
        await page.wait_for(lambda _s: "Beads Pane" in _combined_columns(modal))

        combined = _combined_columns(modal)
        assert "Beads Pane" in combined
        assert "Prompt Input" not in combined
        status = _static_plain(modal, "#help-filter-status")
        assert status.strip() != ""
        assert "0 keymaps" not in status


async def test_typing_q_while_focused_does_not_close_modal() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        modal = _modal(page)
        modal.action_focus_filter()

        await page.press("q")
        await page.pause()

        assert isinstance(page.app.screen, HelpModal)
        filter_input = modal.query_one("#help-filter-input", HelpFilterInput)
        assert filter_input.value == "q"


async def test_enter_applies_filter_and_focuses_results() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        modal = _modal(page)
        modal.action_focus_filter()
        await page.press("b", "e", "a", "d", "s")
        await page.wait_for(lambda _s: "Beads Pane" in _combined_columns(modal))
        before = _combined_columns(modal)

        await page.press("enter")
        await page.wait_for(
            lambda _s: (
                page.app.focused is not None
                and page.app.focused.id == "help-keymaps-scroll"
            )
        )

        assert _combined_columns(modal) == before


async def test_escape_clears_filter_before_closing_modal() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        modal = _modal(page)
        modal.action_focus_filter()
        await page.press("b", "e", "a", "d", "s")
        await page.wait_for(lambda _s: modal._filter_query == "beads")

        await page.press("escape")
        await page.wait_for(lambda _s: modal._filter_query == "")
        assert isinstance(page.app.screen, HelpModal)

        await page.press("escape")
        await page.expect_no_modal()


async def test_slash_on_guide_tab_switches_to_keymaps_and_focuses() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        modal = _modal(page)

        await page.press("]")
        await page.wait_for(lambda _s: modal._active_panel_tab == "help-guide-view")

        await page.press("slash")
        await page.wait_for(
            lambda _s: (
                modal._active_panel_tab == "help-keymaps-view"
                and page.app.focused is not None
                and page.app.focused.id == "help-filter-input"
            )
        )


async def test_nonsense_query_shows_empty_state() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        modal = _modal(page)
        modal.action_focus_filter()

        await page.press("z", "z", "z", "z", "z", "q", "q", "q", "q", "q")
        await page.wait_for(
            lambda _s: modal.query_one("#help-filter-empty", Static).display is True
        )

        columns = modal.query_one("#help-columns", Horizontal)
        assert columns.display is False


async def test_filter_persists_across_ace_tab_switch() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        modal = _modal(page)
        modal.action_focus_filter()
        await page.press("a", "g", "e", "n", "t")
        await page.wait_for(lambda _s: modal._filter_query == "agent")

        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.wait_for(lambda _s: "Agents Tab" in _help_title(page))

        assert modal._filter_query == "agent"
        assert "Agent Actions" in _combined_columns(modal)


async def test_reopen_after_close_starts_unfiltered() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        modal = _modal(page)
        modal.action_focus_filter()
        await page.press("b", "e", "a", "d", "s")
        await page.wait_for(lambda _s: modal._filter_query == "beads")

        await page.press("escape")
        await page.wait_for(lambda _s: modal._filter_query == "")
        await page.press("escape")
        await page.expect_no_modal()

        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        reopened = _modal(page)
        assert reopened._filter_query == ""
        bar = reopened.query_one("#help-filter-bar", Horizontal)
        assert bar.display is False


async def test_filter_then_clear_restores_byte_identical_columns() -> None:
    async with AcePage(initial_tab="changespecs") as page:
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        modal = _modal(page)
        before_left = _static_plain(modal, "#help-left-column")
        before_right = _static_plain(modal, "#help-right-column")

        modal.action_focus_filter()
        await page.press("b", "e", "a", "d", "s")
        await page.wait_for(lambda _s: "Beads Pane" in _combined_columns(modal))

        await page.press("escape")
        await page.wait_for(lambda _s: modal._filter_query == "")

        assert _static_plain(modal, "#help-left-column") == before_left
        assert _static_plain(modal, "#help-right-column") == before_right
