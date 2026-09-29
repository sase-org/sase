"""ACE PNG snapshots for ToolRun agent-list rows (epic sase-1bt, cutover).

Every surface reads deterministic fixtures through one loader seam each
for glance, node summaries, and run detail, with pinned clocks and no
SQLite. Generation is not approval: inspect every new PNG.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent
from sase.core.tool_run import ToolRunGlance
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_tool_runs_png_snapshot_shared import (
    local_now_ts,
    pin_tool_run_clocks,
    seed_tool_run_surfaces,
    tool_run_agent,
    tool_run_glance,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _rows_agents() -> list[Agent]:
    return [
        tool_run_agent("tr-live"),
        tool_run_agent("tr-silent"),
        tool_run_agent("tr-start"),
        tool_run_agent("tr-plus"),
    ]


def _rows_glances() -> list[ToolRunGlance]:
    return [
        tool_run_glance("11" * 16, agent="tr-live"),
        tool_run_glance(
            "22" * 16,
            agent="tr-silent",
            label="test",
            last_activity_ts=int(local_now_ts()) - 2 * 86400,
        ),
        tool_run_glance("33" * 16, agent="tr-start", state="created", stages_done=0),
        tool_run_glance("44" * 16, agent="tr-plus", stages_done=2),
        tool_run_glance("55" * 16, agent="tr-plus", label="lint", stages_done=1),
    ]


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "tool_runs_rows_120x40"),
        ((80, 40), "tool_runs_rows_80x40"),
        ((60, 40), "tool_runs_rows_60x40"),
    ],
)
async def test_tool_runs_rows_png_snapshots(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_tool_run_clocks(monkeypatch)
    seed_tool_run_surfaces(monkeypatch, glances=_rows_glances(), summaries={})
    patch_startup_loaders(monkeypatch, agents=_rows_agents())

    async with AcePage(query='"visual"', patches=patches(), size=size) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_svg_contains(page, "⚒ check 7/11")
        await wait_for_svg_contains(page, "silent 48h")
        await wait_for_svg_contains(page, "starting")
        await wait_for_svg_contains(page, "+1")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page, snapshot_name, title=f"ACE tool run rows ({size[0]}x{size[1]})"
        )
