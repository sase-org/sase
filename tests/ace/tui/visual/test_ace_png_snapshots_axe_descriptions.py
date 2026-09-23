"""sase's TUI PNG snapshots for AXE lumberjack and chop descriptions."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_axe_png_snapshot_fixtures import (
    axe_description_overflow_data,
    axe_lumberjack_tree_data,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_axe_lumberjack_description_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selected lumberjack keeps its description above scrolling output."""
    patch_startup_loaders(monkeypatch, axe_data=axe_lumberjack_tree_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        # Items are: [bgcmd slot 1, hooks LJ, hooks/fast_lint chop,
        # hooks/slow_typecheck chop, checks LJ, checks/smoke chop]. One j
        # press from the default idx=0 lands on the hooks lumberjack.
        await page.press("j")
        assert page.app.current_idx == 1, (
            f"expected idx 1 (hooks lumberjack), got {page.app.current_idx}"
        )
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_lumberjack_description_120x40",
            title="ACE axe lumberjack description banner",
        )


async def test_axe_chop_description_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selected chop keeps its description above scrolling run output."""
    patch_startup_loaders(monkeypatch, axe_data=axe_lumberjack_tree_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        # Items are: [bgcmd slot 1, hooks LJ, hooks/fast_lint chop, ...].
        # Two j presses from the default idx=0 land on the fast_lint chop.
        await page.press("j")
        await page.press("j")
        assert page.app.current_idx == 2, (
            f"expected idx 2 (hooks/fast_lint), got {page.app.current_idx}"
        )
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_description_120x40",
            title="ACE axe chop description banner",
        )


async def test_axe_chop_description_collapsed_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The session toggle collapses a chop body to its summary."""
    patch_startup_loaders(monkeypatch, axe_data=axe_lumberjack_tree_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        # Items are: [bgcmd slot 1, hooks LJ, hooks/fast_lint chop, ...].
        # Two j presses from the default idx=0 land on the fast_lint chop.
        await page.press("j")
        await page.press("j")
        assert page.app.current_idx == 2, (
            f"expected idx 2 (hooks/fast_lint), got {page.app.current_idx}"
        )
        await page.press("d")
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_description_collapsed_120x40",
            title="ACE axe chop collapsed description",
        )


async def test_axe_description_overflow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capped expanded panel states how many rendered rows were omitted."""
    patch_startup_loaders(monkeypatch, axe_data=axe_description_overflow_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        # Overflow data extends the tree fixture: [bgcmd slot 1, hooks LJ,
        # hooks/fast_lint chop, ...]. Two j presses land on fast_lint.
        await page.press("j")
        await page.press("j")
        assert page.app.current_idx == 2, (
            f"expected idx 2 (hooks/fast_lint), got {page.app.current_idx}"
        )
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_description_overflow_120x40",
            title="ACE axe description overflow",
        )
