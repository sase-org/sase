"""Render and filter tests for the command palette modal.

Split from ``tests.test_command_palette_modal``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from textual.widgets import Input, OptionList, Static

from sase.ace.tui.modals.command_palette_modal import (
    COMMAND_PALETTE_INPUT_HINT,
    CommandPaletteModal,
)

from tests._command_palette_modal_helpers import (
    CommandPaletteTestApp,
    live_specs,
    make_spec,
    modal_static_text,
)

__all__ = [
    "test_modal_empty_state_shown_when_no_match",
    "test_modal_filtering_narrows_list",
    "test_modal_filtering_resets_highlight_to_top",
    "test_modal_focuses_input_on_mount",
    "test_modal_renders_key_filter_hint",
    "test_modal_renders_nonempty_applicable_list",
    "test_modal_status_count_switches_to_filtered_form",
    "test_modal_status_empty_filter_shows_zero_position",
    "test_modal_title_includes_tab_badge",
]


async def test_modal_renders_nonempty_applicable_list() -> None:
    specs = live_specs()
    assert specs, "expected applicable specs on the patches tab"

    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#command-palette-list", OptionList)
        assert option_list.option_count == len(specs)


async def test_modal_focuses_input_on_mount() -> None:
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(
            specs=[make_spec("app.refresh", "Refresh tab")],
            tab="changespecs",  # legacy tab id
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        assert filter_input.has_focus


async def test_modal_renders_key_filter_hint() -> None:
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(
            specs=[make_spec("app.refresh", "Refresh tab")],
            tab="changespecs",  # legacy tab id
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        hint = modal.query_one("#command-palette-input-hint", Static)
        assert hint.content == COMMAND_PALETTE_INPUT_HINT
        assert "key:<key>" in COMMAND_PALETTE_INPUT_HINT
        assert "key:j" in COMMAND_PALETTE_INPUT_HINT


async def test_modal_title_includes_tab_badge() -> None:
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(
            specs=[make_spec("app.refresh", "Refresh tab")],
            tab="agents",
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        title = modal._build_title().plain
        assert "Command Palette" in title
        assert "Agents" in title
        assert "1 command" in title


async def test_modal_filtering_narrows_list() -> None:
    specs = [
        make_spec("app.refresh", "Refresh tab"),
        make_spec("app.kill_agent", "Kill agent"),
        make_spec("app.next", "Next entry"),
    ]
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "kill"
        await pilot.pause()

        option_list = modal.query_one("#command-palette-list", OptionList)
        assert option_list.option_count == 1
        assert modal._filtered_specs[0].id == "app.kill_agent"


async def test_modal_status_count_switches_to_filtered_form() -> None:
    specs = [
        make_spec("app.git_status", "Git status"),
        make_spec("app.git_branch", "Git branch"),
        make_spec("app.refresh", "Refresh tab"),
    ]
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="agents")
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert "3 commands" in modal_static_text(modal, "#command-palette-title")

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "git"
        await pilot.pause()

        assert "2 of 3 commands" in modal_static_text(modal, "#command-palette-title")
        assert "1/2" in modal_static_text(modal, "#command-palette-position")


async def test_modal_filtering_resets_highlight_to_top() -> None:
    specs = [
        make_spec("app.refresh", "Refresh tab"),
        make_spec("app.kill_agent", "Kill agent"),
        make_spec("app.next", "Next entry"),
    ]
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#command-palette-list", OptionList)
        option_list.highlighted = 2
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "n"  # narrows the list
        await pilot.pause()

        assert option_list.highlighted == 0


async def test_modal_empty_state_shown_when_no_match() -> None:
    specs = [make_spec("app.refresh", "Refresh tab")]
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "zzznoresult"
        await pilot.pause()

        empty = modal.query_one("#command-palette-empty")
        option_list = modal.query_one("#command-palette-list", OptionList)
        assert empty.display is True
        assert option_list.display is False


async def test_modal_status_empty_filter_shows_zero_position() -> None:
    specs = [make_spec("app.refresh", "Refresh tab")]
    async with CommandPaletteTestApp().run_test() as pilot:
        modal = CommandPaletteModal(specs=specs, tab="changespecs")  # legacy tab id
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#command-palette-filter-input", Input)
        filter_input.value = "zzznoresult"
        await pilot.pause()

        assert "0 of 1 command" in modal_static_text(modal, "#command-palette-title")
        assert "0/0" in modal_static_text(modal, "#command-palette-position")
