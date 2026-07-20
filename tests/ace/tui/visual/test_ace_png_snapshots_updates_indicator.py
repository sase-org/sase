"""ACE TUI PNG visual snapshots for the updates badge states."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import UpdatesAvailableIndicator
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_updates_indicator_routine_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Routine updates retain the compact purple badge."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(3)
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " ↑ 3 ",
            description="routine updates indicator",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "updates_indicator_routine_120x40",
            title="ACE routine updates indicator",
        )


async def test_updates_indicator_core_rebuild_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pending core update adds a legible amber rebuild signal."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(3, core=True)
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " ↑ 3 * ",
            description="core-rebuild updates indicator",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "updates_indicator_core_rebuild_120x40",
            title="ACE core rebuild updates indicator",
        )


async def test_updates_indicator_agent_cli_only_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent-CLI-only updates use an explicit cyan segment."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(0, agent_cli_count=2)
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " CLI ↑ 2 ",
            description="agent-CLI-only updates indicator",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "updates_indicator_agent_cli_only_120x40",
            title="ACE agent-CLI-only updates indicator",
        )


async def test_updates_indicator_mixed_routine_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed routine updates join purple and cyan segments."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(3, agent_cli_count=2)
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " ↑ 3 CLI ↑ 2 ",
            description="mixed routine updates indicator",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "updates_indicator_mixed_routine_120x40",
            title="ACE mixed routine updates indicator",
        )


async def test_updates_indicator_mixed_core_rebuild_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed core updates retain amber rebuild and cyan CLI segments."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(3, core=True, agent_cli_count=2)
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " ↑ 3 * CLI ↑ 2 ",
            description="mixed core-rebuild updates indicator",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "updates_indicator_mixed_core_rebuild_120x40",
            title="ACE mixed core-rebuild updates indicator",
        )
