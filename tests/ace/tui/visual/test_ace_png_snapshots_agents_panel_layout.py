"""ACE TUI PNG visual snapshots for Agents-tab panel layout and state."""

from __future__ import annotations

from datetime import datetime

import pytest
from textual.css.scalar import Unit

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentInfoPanel, AgentList
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _done_agents() -> list[Agent]:
    """Three completed agents in the ``Done`` bucket.

    Used by the unread-highlight snapshot — all three rows are then
    marked unread post-startup so the Agents-tab info-panel header
    renders a non-zero ``N unread`` count that exercises the yellow
    background style.
    """
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            stop_time=datetime(2026, 5, 9, 10, 7, 30),
            raw_suffix="20260509-100000-plan",
            agent_name="planner",
            llm_provider="codex",
            model="gpt-5",
            response_path="/workspace/sase/artifacts/visual-plan/response.md",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-code",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 8, 0),
            stop_time=datetime(2026, 5, 9, 10, 9, 5),
            raw_suffix="20260509-100800-code",
            agent_name="coder",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-review",
            project_file="/workspace/sase/visual_project.sase",
            status="PLAN DONE",
            start_time=datetime(2026, 5, 9, 10, 10, 0),
            stop_time=datetime(2026, 5, 9, 10, 12, 0),
            raw_suffix="20260509-101000-review",
            agent_name="reviewer",
            tribe="visual",
        ),
    ]


def _overflowing_panel_agents() -> list[Agent]:
    """Large no-tribe panel followed by two compact tribe panels."""
    project_file = "/workspace/sase/visual_project.sase"
    started = datetime(2026, 7, 18, 15, 0, 0)
    rows = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"visual-overflow-agent-{idx:02d}",
            project_file=project_file,
            status="RUNNING",
            start_time=started,
            raw_suffix=f"20260718-15{idx:02d}00-overflow-{idx:02d}",
            agent_name=f"overflow-agent-{idx:02d}",
        )
        for idx in range(28)
    ]
    rows.extend(
        [
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name="visual-compact-apple",
                project_file=project_file,
                status="WAITING",
                start_time=started,
                raw_suffix="20260718-160000-compact-apple",
                agent_name="compact-apple",
                tribe="apple",
            ),
            Agent(
                agent_type=AgentType.RUNNING,
                cl_name="visual-compact-banana",
                project_file=project_file,
                status="DONE",
                start_time=started,
                stop_time=datetime(2026, 7, 18, 16, 5, 0),
                raw_suffix="20260718-160100-compact-banana",
                agent_name="compact-banana",
                tribe="banana",
            ),
        ]
    )
    return rows


async def test_agents_overflowing_panel_uses_full_height_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _overflowing_panel_agents()
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", len(rows))
        await wait_for_visual_idle(page)

        container = page.app.query_one("#agent-list-container")
        widgets = list(container.query(AgentList).results(AgentList))
        assert page.app._panel_group.panel_keys == [None, "apple", "banana"]
        assert len(widgets) == 3
        no_tribe, apple, banana = widgets

        assert no_tribe.styles.height.unit is Unit.FRACTION
        assert no_tribe.option_count + 2 > no_tribe.region.height
        for compact in (apple, banana):
            assert compact.styles.height.unit is Unit.CELLS
            assert compact.styles.height.value == compact.option_count + 2
        assert banana.region.bottom == container.content_region.bottom

        ace_png_visual.assert_page_png(
            page,
            "agents_overflowing_panel_full_height_120x40",
            title="ACE agents overflowing panel full height",
        )


async def test_agents_unread_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done = _done_agents()
    patch_startup_loaders(monkeypatch, agents=done)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        identities = {agent.identity for agent in done}
        page.app._unread_completed_agent_ids = set(identities)
        page.app._manual_unread_agent_ids = set(identities)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        page.app._update_agents_info_panel()
        panel = page.app.query_one("#agent-info-panel", AgentInfoPanel)
        await wait_for_state(
            page,
            lambda: panel._unread_count == 3,
            description="three unread completed agents",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_unread_highlight_120x40",
            title="ACE agents unread highlight",
        )
