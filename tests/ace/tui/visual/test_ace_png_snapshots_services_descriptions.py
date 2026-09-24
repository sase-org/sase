"""sase's TUI PNG snapshots for Services service proc descriptions."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_axe_png_snapshot_tree_fixtures import (
    services_panels_data,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_services_proc_description_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scheduler selected with the expanded service description panel."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "services_proc_description_120x40",
            title="ACE services proc description",
        )


async def test_services_proc_description_collapsed_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same selection after ``d`` collapses the panel to one row."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await page.press("d")
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "services_proc_description_collapsed_120x40",
            title="ACE services proc description collapsed",
        )


async def test_services_proc_description_missing_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The description-less proc shows the fallback panel."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        for _ in range(3):
            await page.press("j")
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "services_proc_description_missing_120x40",
            title="ACE services proc description missing",
        )
