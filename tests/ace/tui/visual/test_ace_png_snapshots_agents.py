"""ACE TUI PNG visual snapshot coverage for Agents-tab list states.

ChangeSpecs-tab and footer snapshots live in ``test_ace_png_snapshots``.
Agents-tab modal and detail snapshots live in sibling
``test_ace_png_snapshots_agents_*`` modules.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    agents_with_stopped_status,
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_agent_list_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_list_120x40",
            title="ACE agents list",
        )


async def test_agent_reverted_indicator_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = agents()
    rows[0].reverted = True
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "↺")
        ace_png_visual.assert_page_png(
            page,
            "agents_reverted_indicator_120x40",
            title="ACE agents reverted indicator",
        )


async def test_agent_stopped_status_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents_with_stopped_status())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Ø STOPPED")
        ace_png_visual.assert_page_png(
            page,
            "agents_stopped_status_120x40",
            title="ACE agents stopped status",
        )


def _plan_handoff_status_agents() -> list[Agent]:
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan-approved",
            project_file="/workspace/sase/visual_project.sase",
            status="PLAN APPROVED",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            raw_suffix="20260509-100000-plan-approved",
            agent_name="plan.approved",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-tale-approved",
            project_file="/workspace/sase/visual_project.sase",
            status="TALE APPROVED",
            start_time=datetime(2026, 5, 9, 10, 1, 0),
            raw_suffix="20260509-100100-tale-approved",
            agent_name="tale.approved",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-working-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="WORKING PLAN",
            start_time=datetime(2026, 5, 9, 10, 2, 0),
            raw_suffix="20260509-100200-working-plan",
            agent_name="working.plan",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-working-tale",
            project_file="/workspace/sase/visual_project.sase",
            status="WORKING TALE",
            start_time=datetime(2026, 5, 9, 10, 3, 0),
            raw_suffix="20260509-100300-working-tale",
            agent_name="working.tale",
        ),
    ]


def _waiting_family_child_agents() -> list[Agent]:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parent",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 5, 21, 0, 0),
        raw_suffix="20260705-210000-parent",
        agent_name="visual-parent",
        llm_provider="codex",
        model="gpt-5",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-parent--reviewer",
        project_file="/workspace/sase/visual_project.sase",
        status="WAITING",
        start_time=datetime(2026, 7, 5, 21, 1, 0),
        run_start_time=None,
        wait_start_time=datetime(2026, 7, 5, 21, 1, 0),
        raw_suffix="20260705-210100-reviewer",
        parent_timestamp=parent.raw_suffix,
        agent_name="visual-parent--reviewer",
        agent_family="visual-parent",
        agent_family_role="reviewer",
        role_suffix="--reviewer",
        waiting_for=["visual-parent"],
        llm_provider="codex",
        model="gpt-5",
    )
    return [parent, child]


async def test_agent_plan_handoff_status_colors_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_plan_handoff_status_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 4)
        await wait_for_visual_idle(page)

        for status in (
            "PLAN APPROVED",
            "TALE APPROVED",
            "WORKING PLAN",
            "WORKING TALE",
        ):
            assert_page_svg_contains(page, status)
        ace_png_visual.assert_page_png(
            page,
            "agents_plan_handoff_status_colors_120x40",
            title="ACE agents plan handoff status colors",
        )


async def test_waiting_family_child_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=_waiting_family_child_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("l")
        await page.expect_state("agent_count", 2)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "visual-parent")
        assert_page_svg_contains(page, "RUNNING")
        assert_page_svg_contains(page, "visual-parent--reviewer")
        assert_page_svg_contains(page, "WAITING")
        ace_png_visual.assert_page_png(
            page,
            "agents_waiting_family_child_120x40",
            title="ACE agents waiting family child",
        )


async def test_agents_selected_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        initial_idx = page.app.current_idx
        for _ in range(8):
            await page.press("j")
            if page.app.current_idx != initial_idx:
                break
        else:
            raise AssertionError("j navigation did not move off the initial agent row")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_selected_row_120x40",
            title="ACE agents selected row",
        )
