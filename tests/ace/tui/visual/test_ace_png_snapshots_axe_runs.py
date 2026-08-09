"""ACE TUI PNG snapshots for AXE chop-run and error status panels."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.bgcmd_list import ChopItem
from tests.ace.tui.visual._ace_axe_png_snapshot_fixtures import (
    axe_chop_report_absent_120x40,
    axe_chop_report_error_120x40,
    axe_chop_report_narrow_70x36,
    axe_chop_report_rich_120x40,
    axe_lumberjack_error_data,
    axe_lumberjack_tree_data,
    axe_running_chop_data,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def _select_first_chop(page: AcePage) -> ChopItem:
    await wait_for_startup(page)
    await page.press("tab")
    await page.expect_state("tab", "axe")
    await page.press("j")
    assert page.app.current_idx == 1, (
        f"expected idx 1 (first chop), got {page.app.current_idx}"
    )
    selected = page.app._axe_items[page.app.current_idx]
    assert isinstance(selected, ChopItem), (
        f"expected ChopItem at idx 1, got {type(selected).__name__}"
    )
    page.app._refresh_axe_display()
    await wait_for_visual_idle(page)
    return selected


async def test_axe_chop_run_info_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chop row selected → chop-run-detail view exercises update_chop_status."""
    patch_startup_loaders(monkeypatch, axe_data=axe_lumberjack_tree_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        # Items are: [hooks LJ, hooks/fast_lint chop, hooks/slow_typecheck chop,
        # checks LJ, checks/smoke chop, bgcmd slot 1]. Two j presses from the
        # default idx=0 lands on hooks/slow_typecheck (the chop with a
        # failure run + non-empty output_tail).
        await page.press("j")
        await page.press("j")
        assert page.app.current_idx == 2, (
            f"expected idx 2 (hooks/slow_typecheck), got {page.app.current_idx}"
        )
        selected = page.app._axe_items[page.app.current_idx]
        assert isinstance(selected, ChopItem), (
            f"expected ChopItem at idx 2, got {type(selected).__name__}"
        )
        assert (selected.lumberjack_name, selected.chop_name) == (
            "hooks",
            "slow_typecheck",
        )
        # j-navigation routes the dashboard repaint through a 0.15s debouncer;
        # force the chop-run-detail view to render before snapshotting so the
        # output panel reflects the new selection rather than the idx=0
        # lumberjack overview.
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_run_info_panel_120x40",
            title="ACE axe chop run info panel",
        )


async def test_axe_lumberjack_error_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Errored lumberjack exercises red/warning styling in tree row + panel."""
    patch_startup_loaders(monkeypatch, axe_data=axe_lumberjack_error_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_lumberjack_error_120x40",
            title="ACE axe lumberjack error",
        )


async def test_axe_chop_run_info_panel_running_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chop detail view for an in-flight manual run: ● running + Source: manual."""
    patch_startup_loaders(monkeypatch, axe_data=axe_running_chop_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        # Items: [hooks LJ, hooks/slow_typecheck chop]. j lands on the chop.
        await page.press("j")
        assert page.app.current_idx == 1, (
            f"expected idx 1 (hooks/slow_typecheck), got {page.app.current_idx}"
        )
        selected = page.app._axe_items[page.app.current_idx]
        assert isinstance(selected, ChopItem), (
            f"expected ChopItem at idx 1, got {type(selected).__name__}"
        )
        # Force the chop-run-detail view to render past the debouncer.
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_run_info_panel_running_120x40",
            title="ACE axe chop run info panel (running)",
        )


async def test_axe_chop_report_rich_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rich structured reports render above the OUTPUT tail on the AXE tab."""
    patch_startup_loaders(monkeypatch, axe_data=axe_chop_report_rich_120x40())

    async with AcePage(query='"visual"', patches=patches()) as page:
        selected = await _select_first_chop(page)
        assert (selected.lumberjack_name, selected.chop_name) == ("reports", "ci_watch")

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_report_rich_120x40",
            title="ACE axe chop report rich",
        )


async def test_axe_chop_report_absent_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run without ``report`` still has a complete RESULT card and OUTPUT."""
    patch_startup_loaders(monkeypatch, axe_data=axe_chop_report_absent_120x40())

    async with AcePage(query='"visual"', patches=patches()) as page:
        selected = await _select_first_chop(page)
        assert (selected.lumberjack_name, selected.chop_name) == ("reports", "cleanup")

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_report_absent_120x40",
            title="ACE axe chop report absent",
        )


async def test_axe_chop_report_error_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A check_error run surfaces reason and error in the RESULT card."""
    patch_startup_loaders(monkeypatch, axe_data=axe_chop_report_error_120x40())

    async with AcePage(query='"visual"', patches=patches()) as page:
        selected = await _select_first_chop(page)
        assert (selected.lumberjack_name, selected.chop_name) == (
            "reports",
            "recent_bug_audit",
        )

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_report_error_120x40",
            title="ACE axe chop report error",
        )


async def test_axe_chop_report_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Narrow AXE panes stack report rows and kv pairs without mid-value cuts."""
    patch_startup_loaders(monkeypatch, axe_data=axe_chop_report_narrow_70x36())

    async with AcePage(query='"visual"', patches=patches(), size=(70, 36)) as page:
        selected = await _select_first_chop(page)
        assert (selected.lumberjack_name, selected.chop_name) == ("reports", "ci_watch")

        ace_png_visual.assert_page_png(
            page,
            "axe_chop_report_narrow_70x36",
            title="ACE axe chop report narrow",
        )
