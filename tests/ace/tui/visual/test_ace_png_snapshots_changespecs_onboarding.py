"""ACE TUI PNG visual snapshot for the empty PRs-tab onboarding view."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage, make_changespec
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


async def test_changespecs_onboarding_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(
        query='"visual"',
        changespecs=[],
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        await page.expect_state("total", 0)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Every PR your agents produce")
        assert_page_svg_contains(page, "SASE Admin Center")
        ace_png_visual.assert_page_png(
            page,
            "changespecs_onboarding_120x40",
            title="ACE PRs onboarding",
        )


async def test_changespecs_onboarding_no_match_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(
        query='"missing"',
        changespecs=[make_changespec(name="visual_first")],
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        await page.expect_state("total", 0)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Search Query")
        assert_page_svg_contains(page, "No PRs match this query")
        assert_page_svg_contains(page, "exists")
        ace_png_visual.assert_page_png(
            page,
            "changespecs_onboarding_no_match_120x40",
            title="ACE PRs onboarding no match",
        )
