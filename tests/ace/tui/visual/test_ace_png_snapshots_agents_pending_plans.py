"""ACE TUI PNG snapshots for pending plan-review statuses."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _pending_plan_review_status_agents() -> list[Agent]:
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-pending-{status.lower()}",
            project_file="/workspace/sase/visual_project.sase",
            status=status,
            start_time=datetime(2026, 7, 19, 10, index, 0),
            raw_suffix=f"20260719100{index}00-pending-{status.lower()}",
            agent_name=f"pending.{status.lower()}",
        )
        for index, status in enumerate(("EPIC", "TALE", "PLAN"))
    ]


async def test_agent_pending_plan_status_colors_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_pending_plan_review_status_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        for status in ("EPIC", "TALE", "PLAN"):
            assert_page_svg_contains(page, status)
        ace_png_visual.assert_page_png(
            page,
            "agents_pending_plan_status_colors_120x40",
            title="ACE agents pending plan status colors",
        )
