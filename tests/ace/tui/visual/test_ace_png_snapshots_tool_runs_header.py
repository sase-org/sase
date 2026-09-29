"""ACE PNG snapshots for ToolRun header chips (epic sase-1bt, cutover).

Every surface reads deterministic fixtures through one loader seam each
for glance, node summaries, and run detail, with pinned clocks and no
SQLite. Generation is not approval: inspect every new PNG.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent
from sase.core.tool_run import ToolRunGlance, ToolRunNodeSummary
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_tool_runs_png_snapshot_shared import (
    TOOL_RUN_EPOCH_INT,
    local_now_ts,
    pin_tool_run_clocks,
    seed_tool_run_surfaces,
    select_agent,
    tool_run_agent,
    tool_run_brief,
    tool_run_glance,
    tool_run_summary,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _header_agents() -> list[Agent]:
    return [
        tool_run_agent("tr-h-live"),
        tool_run_agent("tr-h-silent"),
        tool_run_agent("tr-h-pass", status="DONE"),
        tool_run_agent("tr-h-new", status="DONE"),
        tool_run_agent("tr-h-known", status="DONE"),
        tool_run_agent("tr-h-undet", status="DONE"),
        tool_run_agent("tr-h-killed", status="DONE"),
        tool_run_agent("tr-h-stopped", status="DONE"),
        tool_run_agent("tr-h-lost", status="DONE"),
    ]


def _header_glances() -> list[ToolRunGlance]:
    return [
        tool_run_glance("a1" * 16, agent="tr-h-live"),
        tool_run_glance(
            "a2" * 16,
            agent="tr-h-silent",
            label="test",
            last_activity_ts=int(local_now_ts()) - 2 * 86400,
        ),
    ]


def _header_summaries() -> dict[str, ToolRunNodeSummary]:
    settled_ts = TOOL_RUN_EPOCH_INT - 81
    out: dict[str, ToolRunNodeSummary] = {
        "agent:tr-h-live": tool_run_summary("agent:tr-h-live"),
        "agent:tr-h-silent": tool_run_summary("agent:tr-h-silent"),
    }
    cases = [
        ("tr-h-pass", "pass", {}),
        ("tr-h-new", "new_failures", {"new": 3, "known": 1}),
        ("tr-h-known", "known_only", {"known": 2}),
        ("tr-h-undet", "undetermined", {"unknown": 2}),
        ("tr-h-killed", "killed", {}),
        ("tr-h-stopped", "stopped", {}),
        ("tr-h-lost", "lost", {}),
    ]
    for name, bucket, counts in cases:
        terminal = (
            "signal"
            if bucket == "killed"
            else ("stop_requested" if bucket == "stopped" else None)
        )
        if bucket == "lost":
            terminal = "wrapper_lost"
        out[f"agent:{name}"] = tool_run_summary(
            f"agent:{name}",
            (
                tool_run_brief(
                    f"{name}-run".ljust(32, "0")[:32],
                    bucket=bucket,
                    agent=name,
                    settled_ts=settled_ts,
                    terminal_cause=terminal,
                    **counts,
                ),
            ),
        )
    return out


_HEADER_CHIPS: tuple[tuple[str, str, str], ...] = (
    ("tr-h-live", "7/11", "tool_runs_header_live_120x40"),
    ("tr-h-silent", "silent 48h", "tool_runs_header_silent_120x40"),
    ("tr-h-pass", "✓", "tool_runs_header_pass_120x40"),
    ("tr-h-new", "3 NEW", "tool_runs_header_new_120x40"),
    ("tr-h-known", "known only", "tool_runs_header_known_120x40"),
    ("tr-h-undet", "2 UNKNOWN", "tool_runs_header_undetermined_120x40"),
    ("tr-h-killed", "killed", "tool_runs_header_killed_120x40"),
    ("tr-h-stopped", "stopped", "tool_runs_header_stopped_120x40"),
    ("tr-h-lost", "lost", "tool_runs_header_lost_120x40"),
)


async def test_tool_runs_header_chips_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_tool_run_clocks(monkeypatch)
    seed_tool_run_surfaces(
        monkeypatch,
        glances=_header_glances(),
        summaries=_header_summaries(),
    )
    patch_startup_loaders(monkeypatch, agents=_header_agents())

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 9)
        for name, fragment, snapshot_name in _HEADER_CHIPS:
            await select_agent(page, name)
            await wait_for_svg_contains(page, fragment)
            await wait_for_visual_idle(page)
            ace_png_visual.assert_page_png(
                page, snapshot_name, title=f"ACE tool run header chip ({name})"
            )
