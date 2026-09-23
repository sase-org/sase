"""sase's TUI PNG snapshots for the Services two-panel sidebar."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_axe_png_snapshot_tree_fixtures import (
    services_panels_data,
    services_panels_empty_routines_data,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_services_panels_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two titled Services panels with selection on the Scheduler row."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "services_panels_120x40",
            title="ACE services panels",
        )


async def test_services_panels_routine_selected_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selected job moves the gold focus border to Scheduled Routines."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        for _ in range(7):
            await page.press("j")
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "services_panels_routine_selected_120x40",
            title="ACE services panels routine selected",
        )


async def test_services_panels_empty_routines_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty routines panel placeholder plus the stopped-scheduler badge."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_empty_routines_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "services_panels_empty_routines_120x40",
            title="ACE services panels empty routines",
        )


async def test_services_panels_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sidebar width cap and title truncation on a narrow terminal."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches(), size=(70, 36)) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "services_panels_narrow_70x36",
            title="ACE services panels narrow",
        )
