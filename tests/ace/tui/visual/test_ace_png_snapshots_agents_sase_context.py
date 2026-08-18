"""ACE TUI PNG visual snapshots for Agents-tab SASE context metadata."""

from __future__ import annotations

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
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    should_refresh_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import DetailContextLane
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
        created_at="2026-07-03T13:00:00Z",
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

    async with AcePage(query='"visual-task-notes"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_svg_contains(page, "Notes:")
        await page.press("z", "z")
        await wait_for_svg_contains(page, "alice")
        await wait_for_svg_contains(page, "attribution readable")
        await wait_for_visual_idle(page)

        svg_plain = page.export_svg(title="ACE task BEAD notes assertion").replace(
            "&#160;",
            " ",
        )
        assert "Task Title:" in svg_plain
        assert "Description:" in svg_plain
        assert "Notes:" in svg_plain
        assert "Size:" in svg_plain
        assert "Task Type:" in svg_plain
        assert "untyped" in svg_plain
        assert "Created:" in svg_plain
        assert "2026-07-03" in svg_plain
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
        "size: small\n"
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
    phase_issue = Issue(
        id="sase-83.1",
        title="Provider update snapshot",
        issue_type=IssueType.PHASE,
        parent_id="sase-83",
        created_at="2026-07-03T13:00:00Z",
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_associated_plan._lookup_issue",
        lambda _agent, bead_id, **_kwargs: (
            phase_issue if bead_id == phase_issue.id else None
        ),
    )
    patch_startup_loaders(monkeypatch, agents=[root, coder])

    async with AcePage(query='"visual-phase-plan-family"', patches=patches()) as page:
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
        assert metadata.index("▸ PLAN") < metadata.index("▸ BEAD")
        svg = page.export_svg(title="ACE phase family dual context assertion")
        svg_plain = svg.replace("&#160;", " ")
        assert "SASE CONTEXT" in svg_plain
        assert "BEAD" in svg_plain
        assert "PLAN" in svg_plain
        assert svg_plain.index("PLAN") < svg_plain.index("BEAD")
        assert "sase-83.1" in svg_plain
        assert "Parent epic" in svg_plain
        assert "Provider update snapshot" in svg_plain
        assert "Created:" in svg_plain
        assert "2026-07-03" in svg_plain
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


async def test_agents_partially_streamed_context_lanes_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Mid-stream SASE CONTEXT marks unresolved lanes (bead sase-l6.4).

    Lanes resolve cheapest-first and publish as they land, so the section is
    routinely on screen while the store-backed lanes are still resolving.
    Holding ``memory`` and ``skills`` back for the whole capture makes that
    transient state a stable frame: the enrichment worker still runs to
    completion (so the page reaches visual idle) but never marks those two
    lanes ready, which is exactly what the renderer sees between two
    streamed publishes.
    """
    workspace = tmp_path / "sase_42"
    relative_plan_path = Path("sase/repos/plans/202608/streaming context lanes.md")
    plan_path = workspace / relative_plan_path
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        "---\n"
        "tier: tale\n"
        "title: Streaming SASE context lanes\n"
        "goal: Render each context lane as soon as it resolves.\n"
        "size: medium\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-streaming-lanes",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 8, 13, 18, 15, 0),
        raw_suffix="20260813181500",
        agent_name="visual.streaming-lanes",
        plan_path=relative_plan_path.as_posix(),
        sdd_plan_path=relative_plan_path.as_posix(),
        plan_committed=True,
        plan_action="tale",
        workspace_dir=str(workspace),
        llm_provider="codex",
        model="gpt-5",
        step_output={
            "meta_commits": [
                {
                    "message": "feat(ace): stream SASE CONTEXT lanes",
                    "sha": "1234567890abcdef",
                    "cwd": str(workspace),
                }
            ],
        },
    )

    withheld: frozenset[DetailContextLane] = frozenset({"memory", "skills"})

    def _refresh_without_store_lanes(
        panel: AgentPromptPanel,
        row: Agent,
    ) -> frozenset[DetailContextLane]:
        return frozenset(should_refresh_detail_header_summary(panel, row) - withheld)

    monkeypatch.setattr(
        AgentPromptPanel,
        "_should_refresh_detail_header_summary",
        _refresh_without_store_lanes,
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        panel = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        await page.wait_for(
            lambda _state: "resolving" in (renderable_to_text(panel.content) or "")
        )
        await wait_for_visual_idle(page)

        metadata = renderable_to_text(panel.content) or ""
        assert "SASE CONTEXT" in metadata
        assert "Streaming SASE context lanes" in metadata
        for resolved_label in ("PLAN", "ARTIFACTS"):
            assert f"▸ {resolved_label} · resolving…\n" not in metadata
        for pending_label in ("MEMORY", "SKILLS"):
            assert f"▸ {pending_label} · resolving…\n" in metadata
        assert metadata.index("▸ ARTIFACTS") < metadata.index("▸ MEMORY")
        assert metadata.index("▸ MEMORY") < metadata.index("▸ SKILLS")
        assert_page_svg_contains(page, "SASE CONTEXT")
        assert_page_svg_contains(page, "resolving")

        ace_png_visual.assert_page_png(
            page,
            "agents_partially_streamed_context_lanes_120x40",
            title="ACE agents partially streamed SASE context lanes",
        )
