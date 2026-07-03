"""ACE TUI PNG visual snapshot for the empty PRs-tab onboarding view."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    BROAD_SCREENSHOT_MAX_DIFF_RATIO,
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
        await page.expect_state("tab", "changespecs")
        await page.expect_state("total", 0)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "shipped as PRs")
        assert_page_svg_contains(page, "https://sase.sh/change_spec/")
        ace_png_visual.assert_page_png(
            page,
            "changespecs_onboarding_120x40",
            title="ACE PRs onboarding",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
