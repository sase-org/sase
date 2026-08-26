"""Zoom-modal fixtures shared by Agents-tab PNG visual snapshot tests."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from textual.containers import VerticalScroll

from sase.ace.testing import AcePage
from sase.ace.tui.modals.zoom_panel_rendering import renderable_to_text
from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.artifact_read_log import ARTIFACT_READ_LOG_SCHEMA_VERSION, ArtifactReadEvent
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from sase.skills.use_log import SKILL_USE_LOG_SCHEMA_VERSION, SkillUseEvent
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)


def zoom_agent(
    tmp_path: Path,
    *,
    include_xprompts: bool = False,
    include_plan: bool = False,
) -> Agent:
    diff_path = tmp_path / "visual_zoom.diff"
    diff_path.write_text(
        "\n".join(
            [
                "diff --git a/src/app.py b/src/app.py",
                "index 1111111..2222222 100644",
                "--- a/src/app.py",
                "+++ b/src/app.py",
                "@@ -1,5 +1,8 @@",
                " def render_dashboard():",
                "-    return old_summary()",
                "+    summary = build_zoom_summary()",
                "+    summary.enable_live_refresh = True",
                "+    return summary",
                "",
                " def footer_hints():",
                "+    return 'j/k scroll  q close'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts_dir: Path | None = None
    if include_xprompts:
        artifacts_dir = tmp_path / "visual_zoom_artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "xprompts.json").write_text(
            json.dumps(
                [
                    {
                        "name": "gh",
                        "kind": "workflow",
                        "positional": ["sase-org/sase"],
                        "named": {},
                        "tags": ["vcs"],
                    },
                    {
                        "name": "propose",
                        "kind": "workflow",
                        "positional": [],
                        "named": {"note": "metadata"},
                        "tags": ["propose"],
                    },
                    {
                        "name": "review_checklist",
                        "kind": "part",
                        "positional": [],
                        "named": {},
                        "tags": [],
                    },
                ]
            ),
            encoding="utf-8",
        )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-zoom",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 5, 9, 10, 20, 0),
        stop_time=datetime(2026, 5, 9, 10, 28, 45),
        raw_suffix="20260509-102000-zoom",
        agent_name="zoom.snapshot.agent",
        llm_provider="codex",
        model="gpt-5",
        diff_path=str(diff_path),
        artifacts_dir=str(artifacts_dir) if artifacts_dir is not None else None,
    )
    if include_plan:
        relative_plan_path = Path("sase/repos/plans/202607/context lane.md")
        plan_path = tmp_path / relative_plan_path
        plan_path.parent.mkdir(parents=True)
        plan_path.write_text(
            "---\n"
            "tier: tale\n"
            "title: Unified agent context\n"
            "goal: Present the plan and audited context in one ranked list.\n"
            "size: medium\n"
            "---\n"
            "# Plan\n",
            encoding="utf-8",
        )
        agent.plan_path = relative_plan_path.as_posix()
        agent.sdd_plan_path = relative_plan_path.as_posix()
        agent.plan_committed = True
        agent.plan_action = "tale"
        agent.workspace_dir = str(tmp_path)
        agent.llm_provider = None
        agent.model = None
    return agent


def zoom_multi_file_agent(tmp_path: Path) -> Agent:
    agent = zoom_agent(tmp_path)
    notes_path = tmp_path / "review_notes.md"
    notes_path.write_text(
        "# Review Notes\n\n- Freeze file list on modal open.\n- Keep rail active row visible.\n",
        encoding="utf-8",
    )
    plan_path = tmp_path / "implementation_plan.md"
    plan_path.write_text(
        "# Implementation Plan\n\n1. Add frozen zoom file list.\n2. Render a file rail.\n",
        encoding="utf-8",
    )
    agent.extra_files = [str(notes_path), str(plan_path)]
    return agent


def waiting_unknown_agents() -> list[Agent]:
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="wait-unknown",
            project_file="/workspace/sase/visual_project.sase",
            status="WAITING",
            start_time=datetime(2026, 5, 9, 10, 30, 0),
            raw_suffix="20260509-103000-wait",
            agent_name="waiter",
            waiting_for=["coder", "builder", "reviewer", "ghost"],
            waiting_for_beads=["run-bead", "done-bead", "open-bead"],
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="coder",
            project_file="/workspace/sase/visual_project.sase",
            status="DONE",
            start_time=datetime(2026, 5, 9, 10, 20, 0),
            stop_time=datetime(2026, 5, 9, 10, 28, 0),
            raw_suffix="20260509-102000-coder",
            agent_name="coder",
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="builder",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=datetime(2026, 5, 9, 10, 29, 0),
            raw_suffix="20260509-102900-builder",
            agent_name="builder",
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="reviewer",
            project_file="/workspace/sase/visual_project.sase",
            status="FAILED",
            start_time=datetime(2026, 5, 9, 10, 22, 0),
            stop_time=datetime(2026, 5, 9, 10, 27, 0),
            raw_suffix="20260509-102200-reviewer",
            agent_name="reviewer",
            llm_provider="codex",
            model="gpt-5",
        ),
    ]


def waiting_tribe_agents() -> list[Agent]:
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-wait-tribe",
            project_file="/workspace/sase/visual_project.sase",
            status="WAITING",
            start_time=datetime(2026, 5, 9, 10, 30, 0),
            raw_suffix="20260509-103000-tribe-wait",
            agent_name="tribe.waiter",
            waiting_for=["@epic"],
            llm_provider="codex",
            model="gpt-5",
        ),
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-epic-builder",
            project_file="/workspace/sase/visual_project.sase",
            status="RUNNING",
            start_time=datetime(2026, 5, 9, 10, 31, 0),
            raw_suffix="20260509-103100-epic-builder",
            agent_name="epic.builder",
            tribe="epic",
            llm_provider="codex",
            model="gpt-5",
        ),
    ]


def context_artifact_reads() -> tuple[ArtifactReadDisplayEvent, ...]:
    return (
        ArtifactReadDisplayEvent(
            event=ArtifactReadEvent(
                schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
                id="visual-read-design",
                timestamp="2026-06-14T14:22:08+00:00",
                project="visual",
                cwd="/workspace/sase",
                ref="plan:202608/design.md",
                reason="compare the approved constraints with this implementation",
                agent_name="zoom.snapshot.agent",
                agent_source="SASE_AGENT_NAME",
                artifacts_dir="/workspace/sase/artifacts/visual-zoom",
                recorded_link=False,
                resolved_path="/workspace/sase/repos/plans/202608/design.md",
            ),
            agent_label="coder",
        ),
        ArtifactReadDisplayEvent(
            event=ArtifactReadEvent(
                schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
                id="visual-read-prior-art",
                timestamp="2026-06-14T14:18:31+00:00",
                project="visual",
                cwd="/workspace/sase",
                ref="research:202608/prior-art.md",
                reason="reuse the established interaction language",
                agent_name="zoom.snapshot.agent",
                agent_source="SASE_AGENT_NAME",
                artifacts_dir="/workspace/sase/artifacts/visual-zoom",
                recorded_link=False,
                resolved_path="/workspace/sase/repos/research/202608/prior-art.md",
            ),
            agent_label="plan",
        ),
    )


def context_memory_reads() -> list[MemoryReadEvent]:
    return [
        MemoryReadEvent(
            schema_version=READ_LOG_SCHEMA_VERSION,
            id="visual-read-generated-skills",
            timestamp="2026-06-14T14:22:08+00:00",
            project="visual",
            cwd="/workspace/sase",
            canonical_path="generated_skills.md",
            resolved_path="/workspace/sase/memory/generated_skills.md",
            agent_name="zoom.snapshot.agent",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/workspace/sase/artifacts/visual-zoom",
            reason="needed generated skill rules",
            byte_count=64,
            frontmatter_stripped=False,
        ),
    ]


def context_skill_uses() -> list[SkillUseEvent]:
    return [
        SkillUseEvent(
            schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
            id="visual-skill-plan",
            timestamp="2026-06-14T14:23:08+00:00",
            project="visual",
            cwd="/workspace/sase",
            skill_name="sase_plan",
            agent_name="zoom.snapshot.agent",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/workspace/sase/artifacts/visual-zoom",
            reason="needed an implementation plan",
            runtime="codex",
        )
    ]


def context_opened_workspaces() -> list[OpenedWorkspaceDisplayEvent]:
    return [
        OpenedWorkspaceDisplayEvent(
            name="sase-core",
            workspace_dir="/workspace/sase-core_13",
            reason="needed to inspect shared backend behavior",
            opened_at="2026-06-14T14:24:08+00:00",
        )
    ]


def pin_zoom_file_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the zoom modal's file-header path so it is host-independent.

    The static-diff header renders the file's expanded path, which for this
    test is a per-run pytest ``tmp_path`` (``pytest-<N>/popen-gwK/...``). Only
    the displayed ``expanded_path`` is rewritten (the stale-read check compares
    ``path``, and file visibility is unconditional for static diffs) so the
    real file is still read but the PNG golden stays deterministic.
    """
    from sase.ace.tui.widgets.file_panel import _display
    from sase.ace.tui.widgets.file_panel._static_read import StaticReadResult

    original_read = _display._read_static_file

    def _fixed_read(request_id: int, path: str, mode: str) -> StaticReadResult:
        result = original_read(request_id, path, mode)
        result.expanded_path = "/workspace/sase/visual_zoom.diff"
        return result

    monkeypatch.setattr(_display, "_read_static_file", _fixed_read)


async def wait_for_zoom_content(
    page: AcePage,
    sentinel: str,
    *,
    scroll_selector: str,
) -> None:
    """Wait for zoom content and its scheduled focus transfer to land."""
    await wait_for_svg_contains(page, sentinel)
    scroll = page.app.screen.query_one(scroll_selector, VerticalScroll)
    await wait_for_state(
        page,
        lambda: scroll.has_focus,
        description=f"zoom scroll focus on {scroll_selector}",
    )
    await wait_for_visual_idle(page)


async def wait_for_metadata_zoom_resolved(page: AcePage) -> None:
    """Wait until the async metadata sections have finished resolving."""

    def metadata_ready() -> bool:
        panel = page.app.screen.query_one("#zoom-metadata-panel", AgentPromptPanel)
        metadata = renderable_to_text(panel.content) or ""
        return (
            "Xprompts:" in metadata
            and "ARTIFACTS · 1 file" in metadata
            and "resolving..." not in metadata
        )

    await wait_for_state(
        page,
        metadata_ready,
        description="resolved agent metadata zoom context",
    )
    await wait_for_visual_idle(page)
