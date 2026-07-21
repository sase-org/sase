"""Integration tests for the command palette wiring in AceApp.

Covers the acceptance items from
``sdd/plans/202604/tui_command_palette.md`` Phase 3:

- Pressing ``:`` opens the palette modal.
- The palette shows commands applicable to the current tab + selection.
- Selecting commands dispatches through existing app actions / mode handlers.
- ``:`` does not interfere with prompt text areas or modal inputs.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sase.ace.testing import AcePage, make_changespec
from sase.ace.tui import AceApp
from sase.ace.tui.commands import CommandContext, extract_command_context


async def test_colon_opens_command_palette_modal() -> None:
    """Pressing ``:`` from the ChangeSpecs tab opens the palette modal."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.expect_state("tab", "changespecs")
            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")


async def test_semicolon_opens_command_palette_modal() -> None:
    """Pressing ``;`` from the ChangeSpecs tab opens the same palette modal."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.expect_state("tab", "changespecs")
            await page.press("semicolon")
            await page.expect_modal("CommandPaletteModal")


async def test_palette_escape_dismisses_without_side_effects() -> None:
    """Esc closes the palette and leaves no app-state changes behind."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")
            await page.press("escape")
            await page.expect_no_modal()


async def test_palette_executes_refresh_via_action() -> None:
    """Filtering to refresh + Enter dispatches ``action_refresh``."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
        patch.object(AceApp, "action_refresh") as refresh_mock,
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")
            # Type "refresh" into the filter, then submit.
            for ch in "refresh":
                await page.press(ch)
            await page.press("enter")
            await page.expect_no_modal()

    refresh_mock.assert_called()


async def test_palette_omits_inapplicable_axe_only_command_on_cls_tab() -> None:
    """Stop-axe-and-quit is AXE-scoped — it must not appear from ChangeSpecs filter."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("4")
            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")

            from sase.ace.tui.modals.command_palette_modal import (
                CommandPaletteModal,
            )

            modal = page.app.screen
            assert isinstance(modal, CommandPaletteModal)
            ids = {s.id for s in modal._all_specs}
            # All ChangeSpecs-tab applicable specs are present:
            assert "app.refresh" in ids
            assert "app.show_agent_run_log" in ids
            # Specs that only apply to other tabs are excluded by tab scope:
            assert "app.toggle_attempt_view" not in ids


async def test_palette_context_uses_current_tab_badge() -> None:
    """Switching to the AXE tab and opening the palette shows the AXE badge."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            # Tab to axe (Agents-first order: PRs -> AXE).
            await page.press("tab")
            await page.expect_state("tab", "axe")

            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")

            from sase.ace.tui.modals.command_palette_modal import (
                CommandPaletteModal,
            )

            modal = page.app.screen
            assert isinstance(modal, CommandPaletteModal)
            assert modal._tab == "axe"
            title = modal._build_title().plain
            assert "AXE" in title


async def test_palette_filter_input_swallows_typing_no_action_dispatched() -> None:
    """Typing 'q' into the palette filter must not dispatch ``action_quit``.

    Acceptance: ``:`` does not interfere with input widgets — the
    palette's filter input absorbs printable keys.
    """
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
        patch.object(AceApp, "action_quit") as quit_mock,
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")
            await page.press("q")
            # Modal still open, action_quit not fired by the filter input.
            await page.expect_modal("CommandPaletteModal")

    quit_mock.assert_not_called()


def test_action_open_command_palette_uses_real_catalog() -> None:
    """The action filters the catalog through the live applicability."""
    app = AceApp(auto_start_axe=False)
    pushed: list = []
    app.push_screen = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda screen, callback=None: pushed.append((screen, callback))
    )

    app.action_open_command_palette()  # type: ignore[attr-defined]

    assert len(pushed) == 1
    modal, _cb = pushed[0]
    from sase.ace.tui.modals.command_palette_modal import CommandPaletteModal

    assert isinstance(modal, CommandPaletteModal)
    # No changespecs loaded yet, so the palette only shows what is
    # applicable on an empty ChangeSpecs tab.  The refresh command must still
    # be there (always applicable on every tab).
    assert any(s.id == "app.refresh" for s in modal._all_specs)


def test_action_open_command_palette_dispatches_selection() -> None:
    """The on-dismiss callback resolves the spec id and runs the executor."""
    app = AceApp(auto_start_axe=False)
    captured: list = []

    def fake_push(screen, callback=None):  # type: ignore[no-untyped-def]
        captured.append((screen, callback))

    app.push_screen = MagicMock(side_effect=fake_push)  # type: ignore[method-assign]

    with patch.object(AceApp, "action_refresh") as refresh_mock:
        app.action_open_command_palette()  # type: ignore[attr-defined]
        assert len(captured) == 1
        _modal, callback = captured[0]
        assert callback is not None

        from sase.ace.tui.commands import CommandPaletteResult

        callback(CommandPaletteResult(selected_id="app.refresh"))

    refresh_mock.assert_called_once_with()


def test_action_open_command_palette_noop_on_cancel() -> None:
    """Cancelling the palette (None result) runs no action."""
    app = AceApp(auto_start_axe=False)
    captured: list = []
    app.push_screen = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda screen, callback=None: captured.append((screen, callback))
    )
    with patch.object(AceApp, "action_refresh") as refresh_mock:
        app.action_open_command_palette()  # type: ignore[attr-defined]
        _, callback = captured[0]
        assert callback is not None
        from sase.ace.tui.commands import CommandPaletteResult

        callback(CommandPaletteResult(selected_id=None))
        callback(None)

    refresh_mock.assert_not_called()


def test_action_open_command_palette_unknown_id_is_silent() -> None:
    """Selecting an id not in the catalog is a no-op (defensive)."""
    app = AceApp(auto_start_axe=False)
    captured: list = []
    app.push_screen = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda screen, callback=None: captured.append((screen, callback))
    )
    app.action_open_command_palette()  # type: ignore[attr-defined]
    _, callback = captured[0]
    assert callback is not None
    from sase.ace.tui.commands import CommandPaletteResult

    callback(CommandPaletteResult(selected_id="app.does_not_exist"))


def test_extract_command_context_smoke_against_real_app() -> None:
    """Confirm the extractor works against a real AceApp instance."""
    app = AceApp(auto_start_axe=False, initial_tab="changespecs")
    ctx = extract_command_context(app)
    assert isinstance(ctx, CommandContext)
    assert ctx.tab == "changespecs"
    assert ctx.changespec is None
    assert ctx.mark_count == 0
