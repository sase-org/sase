"""ACE TUI PNG visual snapshot for the empty PRs-tab onboarding view."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage, make_patch
from sase.ace.tui.widgets.tab_quickstart import TabQuickStart
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _assert_single_prs_quickstart(page: AcePage) -> None:
    artifacts_view = page.query_one_widget("#artifacts-view")
    quickstarts = list(artifacts_view.query(TabQuickStart))
    assert [quickstart.id for quickstart in quickstarts] == ["patch-quickstart-panel"]


async def test_patches_onboarding_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(
        query='"visual"',
        patches=[],
        initial_tab="patches",
    ) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        await page.expect_state("total", 0)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Every PR your agents produce")
        assert_page_svg_contains(page, "SASE Admin Center")
        _assert_single_prs_quickstart(page)
        ace_png_visual.assert_page_png(
            page,
            # legacy compatibility retained PNG filename
            "changespecs_onboarding_120x40",
            title="ACE PRs onboarding",
        )


async def test_patches_onboarding_no_match_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(
        query='"missing"',
        patches=[make_patch(name="visual_first")],
        initial_tab="patches",
    ) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        await page.expect_state("total", 0)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Search Query")
        assert_page_svg_contains(page, "No PRs match this query")
        assert_page_svg_contains(page, "exists")
        _assert_single_prs_quickstart(page)
        ace_png_visual.assert_page_png(
            page,
            # legacy compatibility retained PNG filename
            "changespecs_onboarding_no_match_120x40",
            title="ACE PRs onboarding no match",
        )
