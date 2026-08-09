"""ACE TUI PNG visual snapshots for Agents-tab panel cleanup."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import ConfirmDismissAllModal
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _cleanup_confirmation_agents() -> list[Agent]:
    """A small lane roster backed by many concrete cleanup targets."""
    project_file = "/workspace/sase/visual_project.sase"
    started = datetime(2026, 7, 24, 10, 0, 0)
    stopped = datetime(2026, 7, 24, 10, 20, 0)

    def done(
        cl_name: str,
        suffix: str,
        *,
        agent_name: str | None,
        tribe: str | None = None,
        agent_type: AgentType = AgentType.RUNNING,
        workflow: str | None = None,
        parent_timestamp: str | None = None,
        parent_workflow: str | None = None,
        step_name: str | None = None,
        agent_family: str | None = None,
        agent_family_role: str | None = None,
        role_suffix: str | None = None,
    ) -> Agent:
        return Agent(
            agent_type=agent_type,
            cl_name=cl_name,
            project_file=project_file,
            status="DONE",
            start_time=started,
            stop_time=stopped,
            raw_suffix=suffix,
            agent_name=agent_name,
            tribe=tribe,
            workflow=workflow,
            parent_timestamp=parent_timestamp,
            parent_workflow=parent_workflow,
            step_name=step_name,
            step_type="agent" if parent_workflow else None,
            is_hidden_step=bool(parent_workflow),
            agent_family=agent_family,
            agent_family_role=agent_family_role,
            role_suffix=role_suffix,
        )

    standalone = done(
        "lane-cleanup-standalone",
        "20260724-100000-standalone",
        agent_name="lane.cleanup.standalone",
        tribe="cleanup",
    )
    workflow = done(
        "lane-cleanup-workflow",
        "20260724-100100-workflow",
        agent_name="lane.cleanup.workflow",
        tribe="cleanup",
        agent_type=AgentType.WORKFLOW,
        workflow="lane-cleanup-workflow",
    )
    workflow.appears_as_agent = True
    workflow_steps = [
        done(
            f"internal-workflow-step-{index}",
            f"20260724-10010{index}-step",
            agent_name=f"internal.workflow.step.{index}",
            agent_type=AgentType.WORKFLOW,
            parent_timestamp=workflow.raw_suffix,
            parent_workflow="lane-cleanup-workflow",
            step_name=f"internal-step-{index}",
        )
        for index in range(3)
    ]
    for step in workflow_steps:
        step.parent_appears_as_agent = True
    family = done(
        "lane-cleanup-family",
        "20260724-100200-family",
        agent_name="lane.cleanup.family--plan",
        tribe="cleanup",
        agent_family="lane.cleanup.family",
        agent_family_role="root",
        role_suffix="--plan",
    )
    family_members = [
        done(
            "lane-cleanup-family",
            f"20260724-10020{index}-family",
            agent_name=f"lane.cleanup.family--phase-{index}",
            parent_timestamp=family.raw_suffix,
            agent_family="lane.cleanup.family",
            role_suffix=f"--phase-{index}",
        )
        for index in range(1, 4)
    ]
    neighbor = done(
        "lane-cleanup-neighbor",
        "20260724-100300-neighbor",
        agent_name="lane.cleanup.neighbor",
    )
    return [
        neighbor,
        standalone,
        workflow,
        *workflow_steps,
        family,
        *family_members,
    ]


async def test_agent_lane_cleanup_confirmation_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _cleanup_confirmation_agents()
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        cleanup_targets = [
            agent for agent in agents if agent.agent_name != "lane.cleanup.neighbor"
        ]
        page.app._present_bulk_kill_modal(
            cleanup_targets,
            header="Tribe: @cleanup",
        )
        await page.expect_modal("ConfirmDismissAllModal")
        modal = page.app.screen
        assert isinstance(modal, ConfirmDismissAllModal)
        description = modal.agent_description
        assert "Dismiss: 3 lanes · 9 agents" in description
        assert "lane.cleanup.standalone" in description
        assert "lane.cleanup.workflow" in description
        assert "lane.cleanup.family" in description
        assert "internal.workflow.step" not in description
        assert "lane.cleanup.family--" not in description
        assert "lane.cleanup.neighbor" not in description

        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agent_lane_cleanup_confirmation_120x40",
            title="ACE agent lane cleanup confirmation",
        )
