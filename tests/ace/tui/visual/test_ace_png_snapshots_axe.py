"""ACE TUI PNG snapshots for core AXE tab states.

Description, chop-run, and layout snapshots live in the neighboring
``test_ace_png_snapshots_axe_*`` modules. Shared data builders live in
``_ace_axe_png_snapshot_fixtures``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_axe_png_snapshot_fixtures import (
    axe_bgcmd_data,
    axe_chop_overrun_data,
    axe_disabled_chop_data,
    axe_lumberjack_tree_data,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    axe_collected_data,
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_axe_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, axe_data=axe_bgcmd_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await page.press("j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_selected_row_120x40",
            title="ACE axe selected row",
        )


async def test_axe_lumberjack_tree_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lumberjack tree with expanded chops and a bgcmd row below."""
    patch_startup_loaders(monkeypatch, axe_data=axe_lumberjack_tree_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_lumberjack_tree_120x40",
            title="ACE axe lumberjack tree",
        )


async def test_axe_disabled_chop_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled chops stay visible and clearly marked in the AXE tree."""
    patch_startup_loaders(monkeypatch, axe_data=axe_disabled_chop_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await page.press("j")
        await page.press("j")
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_disabled_chop_row_120x40",
            title="ACE axe disabled chop row",
        )


async def test_axe_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AXE tab with no lumberjacks and no bgcmds (empty-state placeholder)."""
    patch_startup_loaders(monkeypatch, axe_data=axe_collected_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_empty_120x40",
            title="ACE axe empty",
        )


async def test_axe_chop_overrun_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sidebar chips, roll-up chip, PACE column, and advisory line together."""
    patch_startup_loaders(monkeypatch, axe_data=axe_chop_overrun_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_overrun_120x40",
            title="ACE axe chop overrun",
        )


async def test_axe_chop_overrun_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The overrun indicators degrade sanely in the narrow compact layout."""
    patch_startup_loaders(monkeypatch, axe_data=axe_chop_overrun_data())

    async with AcePage(query='"visual"', patches=patches(), size=(70, 36)) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_overrun_narrow_70x36",
            title="ACE axe chop overrun narrow",
        )
