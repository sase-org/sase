"""Dismiss and navigation tests for the command palette modal.

Split from ``tests.test_command_palette_modal``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from textual.widgets import Input, OptionList

from sase.ace.tui.commands import CommandPaletteResult
from sase.ace.tui.modals.command_palette_modal import CommandPaletteModal

from tests._command_palette_modal_helpers import (
    CommandPaletteTestApp,
    make_spec,
    modal_static_text,
)

__all__ = [
    "test_modal_colon_on_empty_filter_hops_to_command_line",
    "test_modal_ctrl_n_ctrl_p_navigate",
    "test_modal_down_arrow_moves_highlight",
    "test_modal_empty_state_names_command_line_fallback",
    "test_modal_enter_after_filter_returns_filtered_top",
    "test_modal_enter_returns_highlighted_id",
    "test_modal_enter_with_no_results_offers_command_line_fallback",
    "test_modal_escape_returns_none",
    "test_modal_position_updates_after_navigation",
    "test_modal_typing_q_does_not_cancel",
]


async def test_modal_enter_returns_highlighted_id() -> None:
    result: CommandPaletteResult | None = None

    async with CommandPaletteTestApp().run_test() as pilot:

        def on_dismiss(r: CommandPaletteResult | None) -> None:
            nonlocal result
            result = r

        specs = [
            make_spec("app.refresh", "Refresh tab"),
            make_spec("app.kill_agent", "Kill agent"),
        ]
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Default highlight is the first option ("app.refresh").
        await pilot.press("enter")
        await pilot.pause()

        assert result is not None
        assert result.selected_id == "app.refresh"


async def test_modal_enter_after_filter_returns_filtered_top() -> None:
    result: CommandPaletteResult | None = None

    async with CommandPaletteTestApp().run_test() as pilot:

        def on_dismiss(r: CommandPaletteResult | None) -> None:
            nonlocal result
            result = r

        specs = [
            make_spec("app.refresh", "Refresh tab"),
            make_spec("app.kill_agent", "Kill agent"),
        ]
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "kill"
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert result is not None
        assert result.selected_id == "app.kill_agent"


async def test_modal_escape_returns_none() -> None:
    result: CommandPaletteResult | None = None

    async with CommandPaletteTestApp().run_test() as pilot:

        def on_dismiss(r: CommandPaletteResult | None) -> None:
            nonlocal result
            r_actual: CommandPaletteResult | None = r
            result = r_actual

        modal = CommandPaletteModal(
            specs=[make_spec("app.refresh", "Refresh tab")],
            tab="changespecs",  # legacy tab id
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert result is not None
        assert result.selected_id is None


async def test_modal_enter_with_no_results_offers_command_line_fallback() -> None:
    """Enter with no match dismisses with a Command Line prefill (not run)."""
    result: CommandPaletteResult | None = None

    async with CommandPaletteTestApp().run_test() as pilot:

        def on_dismiss(r: CommandPaletteResult | None) -> None:
            nonlocal result
            result = r

        modal = CommandPaletteModal(
            specs=[make_spec("app.refresh", "Refresh tab")],
            tab="changespecs",  # legacy tab id
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "zzznoresult"
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert result is not None
        assert result.selected_id is None
        assert result.command_line_prefill == "zzznoresult"


async def test_modal_colon_on_empty_filter_hops_to_command_line() -> None:
    """Typing ``:`` into an empty filter preserves the Command Line draft."""
    result: CommandPaletteResult | None = None

    async with CommandPaletteTestApp().run_test() as pilot:

        def on_dismiss(r: CommandPaletteResult | None) -> None:
            nonlocal result
            result = r

        modal = CommandPaletteModal(
            specs=[make_spec("app.refresh", "Refresh tab")],
            tab="changespecs",  # legacy tab id
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = ":"
        await pilot.pause()

        assert result is not None
        assert result.selected_id is None
        assert result.command_line_prefill is None
        assert result.preserve_command_line_draft is True


async def test_modal_empty_state_names_command_line_fallback() -> None:
    """The no-match empty state advertises the fallback row."""
    specs = [make_spec("app.refresh", "Refresh tab")]
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "bead list"
        await pilot.pause()

        assert "Run `sase bead list` in Command Line" in modal_static_text(
            modal, "#command-palette-empty"
        )


async def test_modal_down_arrow_moves_highlight() -> None:
    specs = [
        make_spec("app.a", "Alpha"),
        make_spec("app.b", "Bravo"),
        make_spec("app.c", "Charlie"),
    ]
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#command-palette-list", OptionList)
        assert option_list.highlighted == 0

        await pilot.press("down")
        await pilot.pause()
        assert option_list.highlighted == 1

        await pilot.press("up")
        await pilot.pause()
        assert option_list.highlighted == 0


async def test_modal_position_updates_after_navigation() -> None:
    specs = [
        make_spec("app.a", "Alpha"),
        make_spec("app.b", "Bravo"),
        make_spec("app.c", "Charlie"),
    ]
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="agents")
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert "1/3" in modal_static_text(modal, "#command-palette-position")

        await pilot.press("down")
        await pilot.pause()
        assert "2/3" in modal_static_text(modal, "#command-palette-position")

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert "3/3" in modal_static_text(modal, "#command-palette-position")


async def test_modal_ctrl_n_ctrl_p_navigate() -> None:
    specs = [
        make_spec("app.a", "Alpha"),
        make_spec("app.b", "Bravo"),
    ]
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#command-palette-list", OptionList)

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert option_list.highlighted == 1

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert option_list.highlighted == 0


async def test_modal_typing_q_does_not_cancel() -> None:
    """Typing 'q' should go into the filter, not dismiss the modal."""
    dismiss_count = 0

    async with CommandPaletteTestApp().run_test() as pilot:

        def on_dismiss(_r: CommandPaletteResult | None) -> None:
            nonlocal dismiss_count
            dismiss_count += 1

        specs = [
            make_spec("app.quit", "Quit ace"),
            make_spec("app.refresh", "Refresh tab"),
        ]
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("q")
        await pilot.pause()

        assert dismiss_count == 0
        filter_input = modal.query_one("#command-palette-filter-input", Input)
        assert filter_input.value == "q"
