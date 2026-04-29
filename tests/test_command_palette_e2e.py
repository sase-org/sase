"""Phase 5 end-to-end coverage for the ``:`` command palette key.

The Phase 3 wiring tests in ``tests/test_command_palette_wiring.py``
already prove that ``:`` opens the palette on the CLs tab and that the
palette dispatches selections through the existing app actions. This
suite locks in equivalent behavior on the **Agents** and **AXE** tabs
and protects the user-visible acceptance from the Phase 5 plan that
``:`` is bound consistently across every tab.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.testing import AcePage, make_changespec
from sase.ace.tui import AceApp
from sase.ace.tui.modals.command_palette_modal import CommandPaletteModal


async def test_colon_opens_command_palette_from_agents_tab() -> None:
    """Pressing ``:`` from the Agents tab opens the palette with the agents badge."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("tab")
            await page.expect_state("tab", "agents")

            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")

            modal = page.app.screen
            assert isinstance(modal, CommandPaletteModal)
            assert modal._tab == "agents"
            assert "Agents" in modal._build_title().plain


async def test_colon_opens_command_palette_from_axe_tab() -> None:
    """Pressing ``:`` from the AXE tab opens the palette with the AXE badge."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("tab")
            await page.expect_state("tab", "agents")
            await page.press("tab")
            await page.expect_state("tab", "axe")

            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")

            modal = page.app.screen
            assert isinstance(modal, CommandPaletteModal)
            assert modal._tab == "axe"
            assert "AXE" in modal._build_title().plain


async def test_semicolon_opens_command_palette_from_agents_and_axe_tabs() -> None:
    """Pressing ``;`` opens the palette from each non-CL tab."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("tab")
            await page.expect_state("tab", "agents")

            await page.press("semicolon")
            await page.expect_modal("CommandPaletteModal")
            modal = page.app.screen
            assert isinstance(modal, CommandPaletteModal)
            assert modal._tab == "agents"
            await page.press("escape")
            await page.expect_no_modal()

            await page.press("tab")
            await page.expect_state("tab", "axe")

            await page.press("semicolon")
            await page.expect_modal("CommandPaletteModal")
            modal = page.app.screen
            assert isinstance(modal, CommandPaletteModal)
            assert modal._tab == "axe"


async def test_palette_executes_refresh_from_agents_tab() -> None:
    """Selecting refresh from the Agents-tab palette calls ``action_refresh``."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
        patch.object(AceApp, "action_refresh") as refresh_mock,
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("tab")
            await page.expect_state("tab", "agents")

            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")
            for ch in "refresh":
                await page.press(ch)
            await page.press("enter")
            await page.expect_no_modal()

    refresh_mock.assert_called()


async def test_palette_executes_refresh_from_axe_tab() -> None:
    """Selecting refresh from the AXE-tab palette calls ``action_refresh``."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
        patch.object(AceApp, "action_refresh") as refresh_mock,
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            await page.press("tab")
            await page.press("tab")
            await page.expect_state("tab", "axe")

            await page.press("colon")
            await page.expect_modal("CommandPaletteModal")
            for ch in "refresh":
                await page.press(ch)
            await page.press("enter")
            await page.expect_no_modal()

    refresh_mock.assert_called()


async def test_palette_escape_dismisses_from_each_tab() -> None:
    """Esc dismisses the palette on every tab without side effects."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(
            query="test_feature",
            changespecs=[make_changespec()],
        ) as page:
            for expected_tab in ("changespecs", "agents", "axe"):
                if expected_tab != "changespecs":
                    await page.press("tab")
                await page.expect_state("tab", expected_tab)

                await page.press("colon")
                await page.expect_modal("CommandPaletteModal")
                await page.press("escape")
                await page.expect_no_modal()
                # Tab focus is preserved across the open/close cycle.
                await page.expect_state("tab", expected_tab)
