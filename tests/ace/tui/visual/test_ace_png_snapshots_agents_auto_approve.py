"""ACE TUI PNG visual snapshots for Agents-tab auto-approve metadata."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.zoom_panel_rendering import renderable_to_text
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_associated_plan import (
    BeadSummary,
    _AgentPlanEnrichment,
)
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _auto_approve_agents() -> list[Agent]:
    """Three running agents, one per auto-approve kind, for the row-icon snapshot.

    ``approve`` stays ``True`` for every kind (it drives the ⚡ glyph); the
    ``auto_approve_plan_action`` selects the ⚡ / ⚡T / ⚡E suffix.
    """
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-plan",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=datetime(2026, 5, 9, 10, 0, 0),
            raw_suffix="20260509-100000-plan",
            agent_name="planner",
            approve=True,
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-tale",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=datetime(2026, 5, 9, 10, 1, 0),
            raw_suffix="20260509-100100-tale",
            agent_name="teller",
            approve=True,
            auto_approve_plan_action="tale",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-epic",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=datetime(2026, 5, 9, 10, 2, 0),
            raw_suffix="20260509-100200-epic",
            agent_name="epicer",
            approve=True,
            auto_approve_plan_action="epic",
        ),
    ]


def _auto_approve_workflow_child_agents() -> list[Agent]:
    """Expanded workflow family for auto-approve child-row alignment coverage."""
    root_timestamp = "20260509-100000-workflow"
    project_file = "/workspace/sase/visual_project.sase"
    started = datetime(2026, 5, 9, 10, 0, 0)
    return [
        Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="visual-auto-workflow",
            project_file=project_file,
            status="EPIC APPROVED",
            start_time=started,
            raw_suffix=root_timestamp,
            workflow="sase",
            approve=True,
            auto_approve_plan_action="epic",
        ),
        Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="main",
            project_file=project_file,
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 5),
            raw_suffix=root_timestamp,
            workflow="sase",
            parent_workflow="sase",
            parent_timestamp=root_timestamp,
            step_name="main",
            step_type="agent",
            step_index=0,
            total_steps=4,
            agent_name="visual.sase--plan",
            approve=True,
            auto_approve_plan_action="epic",
        ),
        Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="setup",
            project_file=project_file,
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 10),
            raw_suffix=root_timestamp,
            workflow="sase",
            parent_workflow="sase",
            parent_timestamp=root_timestamp,
            step_name="setup",
            step_type="bash",
            step_index=1,
            total_steps=4,
            agent_name="visual.setup",
        ),
        Agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="diff",
            project_file=project_file,
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 0, 15),
            raw_suffix=root_timestamp,
            workflow="sase",
            parent_workflow="sase",
            parent_timestamp=root_timestamp,
            step_name="diff",
            step_type="python",
            step_index=2,
            total_steps=4,
            agent_name="visual.diff",
        ),
    ]


async def test_agents_auto_approve_icons_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _auto_approve_agents()
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_svg_contains(page, "⚡T ")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "⚡ ")
        assert_page_svg_contains(page, "⚡T ")
        assert_page_svg_contains(page, "⚡E ")

        ace_png_visual.assert_page_png(
            page,
            "agents_auto_approve_icons_120x40",
            title="ACE agents auto-approve icons",
        )


async def test_agents_auto_approve_workflow_child_alignment_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _auto_approve_workflow_child_agents()
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        page.app._fold_manager.expand("20260509-100000-workflow")
        page.app._refilter_agents()
        await page.expect_state("agent_count", 4)
        await wait_for_svg_contains(page, "⚡E ")
        await wait_for_visual_idle(page)

        svg_plain = page.export_svg(title="ACE auto child alignment").replace(
            "&#160;",
            " ",
        )
        assert svg_plain.count("⚡E ") == 2
        for token in ("sase", "main", "setup", "diff", "🐚 ", "🐍 "):
            assert token in svg_plain
        connector_positions = re.findall(
            r'x="([^"]+)" y="([^"]+)"[^>]*>  └─ </text>',
            svg_plain,
        )
        assert len(connector_positions) == 3
        assert len({x for x, _ in connector_positions}) == 1
        connector_y = {y for _, y in connector_positions}
        child_bolt_positions = [
            (x, y)
            for x, y in re.findall(
                r'x="([^"]+)" y="([^"]+)"[^>]*>⚡E </text>',
                svg_plain,
            )
            if y in connector_y
        ]
        assert len(child_bolt_positions) == 1
        assert float(child_bolt_positions[0][0]) > float(connector_positions[0][0])

        ace_png_visual.assert_page_png(
            page,
            "agents_auto_approve_workflow_child_alignment_120x40",
            title="ACE agents auto-approve workflow child alignment",
        )


async def test_agents_auto_approve_metadata_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = _auto_approve_agents()
    patch_startup_loaders(monkeypatch, agents=agents)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)

        for idx, (token, snapshot_name, title) in enumerate(
            (
                ("⚡ PLAN", "agents_auto_approve_metadata_plan_120x40", "PLAN"),
                ("⚡ TALE", "agents_auto_approve_metadata_tale_120x40", "TALE"),
                ("⚡ EPIC", "agents_auto_approve_metadata_epic_120x40", "EPIC"),
            )
        ):
            if idx:
                await page.press("j")
            await wait_for_state(
                page,
                lambda idx=idx: page.app.current_idx == idx,
                description=f"selected auto-approve agent index {idx}",
            )
            await wait_for_svg_contains(page, token)
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "Auto:")
            assert_page_svg_contains(page, token)

            ace_png_visual.assert_page_png(
                page,
                snapshot_name,
                title=f"ACE agents auto-approve metadata {title}",
            )


def _auto_approve_xprompts_agent(artifacts_dir: Path) -> Agent:
    """One approved agent whose artifacts dir carries ``xprompts.json``.

    Exercises the combined metadata layout where the ``Auto:`` and ``Model:``
    fields render in order immediately before the disk-enriched ``Xprompts:``
    section.
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "xprompts.json").write_text(
        json.dumps(
            [
                {"kind": "workflow", "name": "auto_before_xprompts"},
                {"kind": "part", "name": "plan_part"},
            ]
        ),
        encoding="utf-8",
    )
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-plan",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 9, 10, 0, 0),
        raw_suffix="20260509-100000-plan",
        agent_name="planner",
        approve=True,
        llm_provider="claude",
        model="opus",
        artifacts_dir=str(artifacts_dir),
    )


async def test_agents_auto_approve_xprompts_metadata_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = _auto_approve_xprompts_agent(tmp_path / "xprompt-artifacts")
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "Xprompts:")
        await wait_for_visual_idle(page)

        svg = page.export_svg(title="ACE auto/xprompts metadata")
        svg_plain = svg.replace("&#160;", " ")
        assert "Auto:" in svg_plain
        assert "Model:" in svg_plain
        assert "Xprompts:" in svg_plain
        assert (
            svg_plain.index("Auto:")
            < svg_plain.index("Model:")
            < svg_plain.index("Xprompts:")
        )

        ace_png_visual.assert_page_png(
            page,
            "agents_auto_approve_xprompts_metadata_120x40",
            title="ACE agents auto-approve xprompts metadata",
        )


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

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
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

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "3 phases")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "SASE CONTEXT")
        assert_page_svg_contains(page, "PLAN")
        assert_page_svg_contains(page, "epic")
        assert_page_svg_contains(page, "3 phases")
        assert_page_svg_contains(page, "Title:")
        assert_page_svg_contains(page, "Epic phase roadmap")
        for title_word in ("Planner", "safety", "checks"):
            assert_page_svg_contains(page, title_word)
        assert_page_svg_contains(page, "small")
        assert_page_svg_contains(page, "medium")
        assert_page_svg_contains(page, "large")
        assert_page_svg_contains(page, "no dependencies")
        assert_page_svg_contains(page, "after core")
        assert_page_svg_contains(page, "codex/gpt-5.6-sol")
        assert_page_svg_contains(page, "after core, render")
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
        agent_family_role="phase",
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
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
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


async def test_agents_task_bead_notes_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    notes = (
        "[2026-08-01T14:03:00Z · alice] Confirmed the notes row belongs "
        "directly under the task description.\n\n"
        "[2026-08-01T14:07:00Z · bob] This second note is intentionally long "
        "enough to wrap in the BEAD lane while keeping attribution readable."
    )
    bead = BeadSummary(
        id="sase-notes.4",
        phase_title="Display persisted bead notes",
        description="Render task metadata without requiring a plan file.",
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size="medium",
        bead_type="task",
        notes=notes,
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-task-notes",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 8, 1, 14, 0, 0),
        raw_suffix="20260801140000",
        agent_name="sase-notes.4",
        step_type="bash",
        workspace_dir=str(tmp_path),
        llm_provider="codex",
        model="gpt-5",
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_display_header_summary."
        "resolve_agent_plan_enrichment",
        lambda *_args, **_kwargs: _AgentPlanEnrichment("task", bead, None, ()),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual-task-notes"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "Notes:")
        await wait_for_visual_idle(page)

        svg_plain = page.export_svg(title="ACE task BEAD notes assertion").replace(
            "&#160;",
            " ",
        )
        assert "Task Title:" in svg_plain
        assert "Description:" in svg_plain
        assert "Notes:" in svg_plain
        assert "Size:" in svg_plain
        assert "alice" in svg_plain
        assert "bob" in svg_plain
        assert "attribution readable" in svg_plain
        assert "Epic Plan:" not in svg_plain
        assert "Epic Title:" not in svg_plain

        ace_png_visual.assert_page_png(
            page,
            "agents_task_bead_notes_120x40",
            title="ACE agents task BEAD notes lane",
        )


async def test_agents_phase_family_bead_and_plan_context_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    epic_ref = Path("p/epic.md")
    epic_path = tmp_path / epic_ref
    epic_path.parent.mkdir(parents=True)
    epic_path.write_text(
        "---\n"
        "tier: epic\n"
        "title: Parent epic\n"
        "goal: Coordinate provider updates without leaking the full roadmap.\n"
        "phases:\n"
        "  - id: snapshot\n"
        "    title: Provider update snapshot\n"
        "    depends_on: []\n"
        "    description: Provider context.\n"
        "    size: small\n"
        "  - id: render\n"
        "    title: Render update awareness\n"
        "    depends_on: [snapshot]\n"
        "    size: medium\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    authored_ref = Path("p/phase.md")
    authored_path = tmp_path / authored_ref
    authored_path.write_text(
        "---\n"
        "tier: tale\n"
        "title: Phase plan\n"
        "goal: Approved handoff beside the parent.\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-phase-plan-family",
        project_file="/workspace/sase/visual_project.sase",
        status="TALE APPROVED",
        start_time=datetime(2026, 7, 20, 10, 30, 0),
        stop_time=datetime(2026, 7, 20, 10, 36, 0),
        raw_suffix="20260720103000",
        role_suffix="--plan",
        agent_name="sase-83.1--plan",
        agent_family="sase-83.1",
        agent_family_role="root",
        plan_chain_root=True,
        epic_bead_id="sase-83",
        phase_bead_id="sase-83.1",
        epic_plan_ref=epic_ref.as_posix(),
        archived_plan_path=authored_ref.as_posix(),
        sdd_plan_path=authored_ref.as_posix(),
        plan_committed=True,
        plan_action="tale",
        workspace_dir=str(tmp_path),
        llm_provider="codex",
        model="gpt-5",
    )
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-phase-plan-family-code",
        project_file=root.project_file,
        status="DONE",
        start_time=datetime(2026, 7, 20, 10, 37, 0),
        stop_time=datetime(2026, 7, 20, 10, 45, 0),
        raw_suffix="20260720103700",
        parent_timestamp=root.raw_suffix,
        role_suffix="--code",
        agent_name="sase-83.1--code",
        agent_family="sase-83.1",
        agent_family_role="code",
        epic_bead_id="sase-83",
        phase_bead_id="sase-83.1",
        epic_plan_ref=epic_ref.as_posix(),
        archived_plan_path=authored_ref.as_posix(),
        sdd_plan_path=authored_ref.as_posix(),
        plan_committed=True,
        workspace_dir=str(tmp_path),
        llm_provider="codex",
        model="gpt-5",
    )
    patch_startup_loaders(monkeypatch, agents=[root, coder])

    async with AcePage(
        query='"visual-phase-plan-family"', changespecs=changespecs()
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("p")
        panel = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        await page.wait_for(
            lambda _state: "Phase plan" in (renderable_to_text(panel.content) or "")
        )
        await page.press("Z")
        await page.expect_modal("ZoomPanelModal")
        panel = page.app.screen.query_one("#zoom-metadata-panel", AgentPromptPanel)
        await page.wait_for(
            lambda _state: "Phase plan" in (renderable_to_text(panel.content) or "")
        )
        await wait_for_visual_idle(page)

        metadata = renderable_to_text(panel.content) or ""
        assert metadata.index("▸ BEAD") < metadata.index("▸ PLAN")
        svg = page.export_svg(title="ACE phase family dual context assertion")
        svg_plain = svg.replace("&#160;", " ")
        assert "SASE CONTEXT" in svg_plain
        assert "BEAD" in svg_plain
        assert "PLAN" in svg_plain
        assert svg_plain.index("BEAD") < svg_plain.index("PLAN")
        assert "sase-83.1" in svg_plain
        assert "Parent epic" in svg_plain
        assert "Provider update snapshot" in svg_plain
        assert "Render update awareness" not in svg_plain
        assert "small" in svg_plain
        assert "medium" not in svg_plain
        assert "Phase plan" in svg_plain
        assert "tale" in svg_plain

        ace_png_visual.assert_page_png(
            page,
            "agents_phase_bead_and_plan_context_120x40",
            title="ACE agents phase family BEAD and PLAN context lanes",
        )
