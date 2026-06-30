"""ACE TUI PNG visual snapshot for the empty Agents-tab onboarding view."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents import _onboarding_launch_targets
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    BROAD_SCREENSHOT_MAX_DIFF_RATIO,
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_agents_onboarding_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        _onboarding_launch_targets,
        "discover_agents_onboarding_launch_targets_available",
        lambda: False,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 0)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Welcome to sase ace")
        assert_page_svg_contains(page, "https://sase.sh")
        assert "pick a project or CL first." not in page.screen
        ace_png_visual.assert_page_png(
            page,
            "agents_onboarding_120x40",
            title="ACE agents onboarding",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
