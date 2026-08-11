"""ACE TUI PNG visual snapshot coverage for the Patches tab and footer.

Other PNG snapshot coverage lives in feature-specific siblings:
``test_ace_png_snapshots_agents*`` (Agents tab),
``test_ace_png_snapshots_axe`` (Axe tab),
``test_ace_png_snapshots_saved_groups`` (saved agent group revival modal), and
``test_ace_png_snapshots_finder`` (recursive file finder modal).
Shared fixtures live in ``_ace_png_snapshot_helpers``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_patch_initial_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await page.expect_state("selected.name", "visual_auth")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            # legacy compatibility retained PNG filename
            "changespec_initial_120x40",
            title="ACE changespec initial",  # legacy compatibility retained PNG title
        )


async def test_patch_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await page.press("j")
        await page.expect_state("selected.name", "visual_billing")
        page.app._refresh_patch_detail_only()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            # legacy compatibility retained PNG filename
            "changespec_selected_row_120x40",
            title="ACE changespec selected row",  # legacy compatibility retained PNG title
        )


async def test_query_edit_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await page.press("slash")
        await page.expect_modal("QueryEditModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "query_edit_modal_120x40",
            title="ACE query edit modal",
        )


async def _render_leader_footer(page: AcePage) -> None:
    """Force the keybinding footer into LEADER mode and let it lay out.

    LEADER mode is the worst case for footer width — ~15 chips on patches
    tab — so it's the right target for grid-overflow snapshots.
    """
    from sase.ace.tui.widgets import KeybindingFooter

    footer = page.app.query_one(KeybindingFooter)
    footer.update_leader_bindings(current_tab="patches")
    await wait_for_visual_idle(page)


async def test_footer_leader_overflow_wide_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LEADER mode at 120x40: chips overflow into a deterministic grid."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await _render_leader_footer(page)

        ace_png_visual.assert_page_png(
            page,
            "footer_leader_overflow_120x40",
            title="ACE footer LEADER grid (wide)",
        )


async def test_footer_leader_overflow_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LEADER mode at 80x30: narrower width drops more chips into more rows."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(80, 30)) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await _render_leader_footer(page)

        ace_png_visual.assert_page_png(
            page,
            "footer_leader_overflow_80x30",
            title="ACE footer LEADER grid (narrow)",
        )
