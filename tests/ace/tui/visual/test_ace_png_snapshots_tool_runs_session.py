"""ACE PNG snapshots for the ToolRun session rail (epic sase-1bt, cutover).

Every surface reads deterministic fixtures through one loader seam each
for glance, node summaries, and run detail, with pinned clocks and no
SQLite. Generation is not approval: inspect every new PNG.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.tool_runs.detail import LoadedToolRunDetail
from sase.core.tool_run_views import ToolRunDetail
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_tool_runs_png_snapshot_shared import (
    pin_tool_run_clocks,
    seed_tool_run_surfaces,
    select_agent,
    show_runs_card,
    tool_run_agent,
    tool_run_brief,
    tool_run_summary,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


# NOTE: no 80-column Runs card snapshot. At 80 cols the responsive layout
# is list-only (the detail deck is hidden), so narrow widths cover rows
# (see test_tool_runs_rows_png_snapshots); the card is covered at 120.
async def test_tool_runs_session_rail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_tool_run_clocks(monkeypatch)
    root = tool_run_agent(
        "tr-sess",
        agent_session="tr-sess",
        agent_session_role="root",
    )
    child_a = tool_run_agent(
        "tr-sess--a",
        status="DONE",
        agent_session="tr-sess",
        agent_session_role="code",
        role_suffix="--a",
        parent_timestamp=root.raw_suffix,
    )
    child_b = tool_run_agent(
        "tr-sess--b",
        status="DONE",
        agent_session="tr-sess",
        agent_session_role="reviewer",
        role_suffix="--b",
        parent_timestamp=root.raw_suffix,
    )
    root.followup_agents = [child_a, child_b]
    briefs = (
        tool_run_brief(
            "s1" + "0" * 30, bucket="new_failures", new=1, agent="tr-sess--a"
        ),
        tool_run_brief(
            "s2" + "0" * 30, bucket="known_only", known=2, agent="tr-sess--b"
        ),
        tool_run_brief("s3" + "0" * 30, bucket="pass", agent="tr-sess"),
    )
    from sase.ace.tui.tool_runs.summaries import selector_for_agent

    key = selector_for_agent(root)
    assert key is not None
    summary = tool_run_summary(key.key, briefs)
    details = {
        brief.run_id: LoadedToolRunDetail(
            run_id=brief.run_id,
            detail=ToolRunDetail(
                store_exists=True,
                found=True,
                display_argv=("just", "check"),
                stages=(),
                brief=brief,
            ),
            tail=None,
        )
        for brief in briefs
    }
    seed_tool_run_surfaces(
        monkeypatch, glances=[], summaries={key.key: summary}, details=details
    )
    patch_startup_loaders(monkeypatch, agents=[root, child_a, child_b])

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await select_agent(page, "tr-sess")
        await show_runs_card(page)
        await wait_for_svg_contains(page, "s1000000")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "tool_runs_card_session_120x40",
            title="ACE tool runs card session rail",
        )
        page.app.action_toggle_deck_split_right()
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "tool_runs_split_120x40",
            title="ACE tools reply split",
        )
