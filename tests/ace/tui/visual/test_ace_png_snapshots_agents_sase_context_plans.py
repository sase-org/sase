"""sase's TUI PNG visual snapshots for Agents-tab SASE plan context lanes."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from sase.bead.model import Issue, IssueType
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_agents_sase_plan_metadata_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    relative_plan_path = Path("sase/repos/plans/202607/agent intent metadata.md")
    plan_path = tmp_path / relative_plan_path
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        "---\n"
        "tier: tale\n"
        "title: Agent intent metadata\n"
        "goal: >\n"
        "  Make the selected agent's intended outcome legible while preserving fast\n"
        "  navigation and the approved destination.\n"
        "size: medium\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-agent-intent",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 15, 9, 0, 0),
        raw_suffix="20260715090000",
        agent_name="visual.agent-intent",
        plan_path=relative_plan_path.as_posix(),
        sdd_plan_path=relative_plan_path.as_posix(),
        plan_committed=True,
        plan_action="tale",
        workspace_dir=str(tmp_path),
        llm_provider="codex",
        model="gpt-5",
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "SASE CONTEXT")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "SASE CONTEXT")
        assert_page_svg_contains(page, "PLAN")
        assert_page_svg_contains(page, "tale")
        assert_page_svg_contains(page, "Title:")
        assert_page_svg_contains(page, "Agent intent metadata")
        assert_page_svg_contains(page, "Goal:")
        assert_page_svg_contains(page, "Path:")
        assert_page_svg_contains(page, "sase/repos/plans/202607")
        assert_page_svg_contains(page, "intended outcome")
        assert_page_svg_contains(page, "approved")
        assert_page_svg_contains(page, "destination")
        ace_png_visual.assert_page_png(
            page,
            "agents_plan_goal_metadata_120x40",
            title="ACE agents SASE plan metadata",
        )


async def test_agents_epic_phase_roadmap_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    relative_plan_path = Path("sase/repos/plans/202607/epic phase roadmap.md")
    plan_path = tmp_path / relative_plan_path
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        "---\n"
        "tier: epic\n"
        "title: Epic phase roadmap\n"
        "goal: Show every validated phase in a responsive roadmap\n"
        "phases:\n"
        "  - id: core\n"
        "    title: Planner and safety checks\n"
        "    depends_on: []\n"
        "    description: Establish the normalized phase model.\n"
        "    size: small\n"
        "  - id: render\n"
        "    title: Responsive phase renderer\n"
        "    depends_on: [core]\n"
        "    size: medium\n"
        "    model: codex/gpt-5.6-sol\n"
        "  - id: verify\n"
        "    title: Visual verification\n"
        "    depends_on: [core, render]\n"
        "    size: large\n"
        "---\n"
        "# Plan\n\n"
        "Implement and verify the roadmap.\n",
        encoding="utf-8",
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-epic-roadmap",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 15, 10, 0, 0),
        raw_suffix="20260715100000",
        agent_name="visual.epic-roadmap",
        plan_path=relative_plan_path.as_posix(),
        sdd_plan_path=relative_plan_path.as_posix(),
        plan_committed=True,
        plan_action="epic",
        workspace_dir=str(tmp_path),
        llm_provider="codex",
        model="gpt-5",
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "3 phases")
        await wait_for_visual_idle(page)

        panel = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        metadata = renderable_to_text(panel.content) or ""
        for expected in (
            "Planner and safety checks",
            "small",
            "Responsive phase renderer",
            "medium",
            "no dependencies",
            "after core",
            "codex/gpt-5.6-sol",
            "Visual verification",
            "large",
            "after core, render",
        ):
            assert expected in metadata

        assert_page_svg_contains(page, "SASE CONTEXT")
        assert_page_svg_contains(page, "PLAN")
        assert_page_svg_contains(page, "epic")
        assert_page_svg_contains(page, "3 phases")
        assert_page_svg_contains(page, "Title:")
        assert_page_svg_contains(page, "Epic phase roadmap")
        await wait_for_svg_contains(page, "Visual verification")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_epic_phase_roadmap_120x40",
            title="ACE agents epic phase roadmap",
        )


async def test_agents_phase_bead_context_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    relative_plan_path = Path("sase/repos/plans/202607/phase bead context lane.md")
    plan_path = tmp_path / relative_plan_path
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        "---\n"
        "tier: epic\n"
        "title: Phase bead SASE context lane\n"
        "goal: Keep the complete epic roadmap private to its owner.\n"
        "phases:\n"
        "  - id: model\n"
        "    title: Typed phase metadata\n"
        "    depends_on: []\n"
        "    size: small\n"
        "  - id: render\n"
        "    title: Responsive BEAD lane\n"
        "    depends_on: [model]\n"
        "    description: >-\n"
        "      Present the selected phase identity and provenance without exposing\n"
        "      the full epic roadmap.\n"
        "    size: medium\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-phase-bead",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 17, 9, 30, 0),
        raw_suffix="20260717093000",
        agent_name="sase-visual.2",
        agent_session_role="phase",
        epic_bead_id="sase-visual",
        phase_bead_id="sase-visual.2",
        epic_plan_ref=relative_plan_path.as_posix(),
        plan_path=relative_plan_path.as_posix(),
        sdd_plan_path=relative_plan_path.as_posix(),
        plan_committed=True,
        workspace_dir=str(tmp_path),
        llm_provider="codex",
        model="gpt-5",
    )
    phase_issue = Issue(
        id="sase-visual.2",
        title="Responsive BEAD lane",
        issue_type=IssueType.PHASE,
        parent_id="sase-visual",
        created_at="2026-07-03T13:00:00Z",
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan._lookup_issue",
        lambda _agent, bead_id, **_kwargs: (
            phase_issue if bead_id == phase_issue.id else None
        ),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "Phase Title:")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "SASE CONTEXT")
        assert_page_svg_contains(page, "BEAD")
        svg = page.export_svg(title="ACE phase BEAD context assertion")
        assert re.search(
            r"phase&#160;</text><text[^>]*>sase-visual\.2</text>",
            svg,
        )
        assert_page_svg_contains(page, "Phase Title:")
        assert_page_svg_contains(page, "Responsive BEAD lane")
        assert_page_svg_contains(page, "Description:")
        assert_page_svg_contains(page, "Size:")
        assert_page_svg_contains(page, "medium")
        assert_page_svg_contains(page, "Epic Plan:")
        assert_page_svg_contains(page, "Epic Title:")
        assert_page_svg_contains(page, "Created:")
        assert_page_svg_contains(page, "2026-07-03")
        assert_page_svg_contains(page, "Phase bead SASE context lane")
        assert "Bead:" not in svg
        assert "ID:" not in svg
        assert "▸ PLAN" not in svg
        assert "Typed phase metadata" not in svg
        assert "small" not in svg
        assert "large" not in svg
        assert "Keep the complete epic roadmap" not in svg

        ace_png_visual.assert_page_png(
            page,
            "agents_phase_bead_context_120x40",
            title="ACE agents phase BEAD context lane",
        )
