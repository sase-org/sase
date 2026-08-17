"""Shared builders and assertions for agent-context renderer tests."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from rich.style import Style as RichStyle
from rich.text import Text

from sase.ace.tui.models.agent_associated_plan import (
    AssociatedPlanSummary,
    BeadSummary,
    PhaseBeadSummary,
)
from sase.ace.tui.glossary_reads import GlossaryReadDisplayEvent
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_bead_section import (
    ResponsiveBeadSection,
)
from sase.ace.tui.widgets.prompt_panel._agent_plan_section import (
    ResponsivePlanSection,
)
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_MARKER_META_KEY,
)
from sase.glossary.read_log import GLOSSARY_READ_LOG_SCHEMA_VERSION, GlossaryReadEvent
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from sase.skills.use_log import SKILL_USE_LOG_SCHEMA_VERSION, SkillUseEvent

EXPECTED_CONTEXT_LANE_ORDER = (
    "PLAN",
    "BEAD",
    "ARTIFACTS",
    "MEMORY",
    "GLOSSARY",
    "SKILLS",
    "WORKSPACES",
)


def pin_context_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def memory_event() -> MemoryReadDisplayEvent:
    return MemoryReadDisplayEvent(
        event=MemoryReadEvent(
            schema_version=READ_LOG_SCHEMA_VERSION,
            id="read-a",
            timestamp="2026-06-14T14:22:08+00:00",
            project="test",
            cwd="/tmp/test",
            canonical_path="generated_skills.md",
            resolved_path="/tmp/test/memory/generated_skills.md",
            agent_name="alpha",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/tmp/test/artifacts",
            reason="needed generated skill rules",
            byte_count=64,
            frontmatter_stripped=False,
        )
    )


def glossary_event() -> GlossaryReadDisplayEvent:
    return GlossaryReadDisplayEvent(
        event=GlossaryReadEvent(
            schema_version=GLOSSARY_READ_LOG_SCHEMA_VERSION,
            id="glossary-read-a",
            timestamp="2026-06-14T14:22:38+00:00",
            project="test",
            cwd="/tmp/test",
            agent_name="alpha",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/tmp/test/artifacts",
            reason="needed the hood/agent distinction",
            terms=("Agent Hood",),
            related_terms=("Sase Agent",),
            depth_limit=None,
            definition_bytes=64,
            source_path="/tmp/test/sase/sase.yml",
        )
    )


def skill_event() -> SkillUseDisplayEvent:
    return SkillUseDisplayEvent(
        event=SkillUseEvent(
            schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
            id="skill-a",
            timestamp="2026-06-14T14:23:08+00:00",
            project="test",
            cwd="/tmp/test",
            skill_name="sase_plan",
            agent_name="alpha",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/tmp/test/artifacts",
            reason="needed an implementation plan",
            runtime="codex",
        )
    )


def workspace_event(
    *,
    name: str = "sase-core",
    opened_at: str = "2026-06-14T14:24:08+00:00",
    reason: str = "needed to inspect core boundary",
) -> OpenedWorkspaceDisplayEvent:
    return OpenedWorkspaceDisplayEvent(
        name=name,
        workspace_dir=f"/tmp/workspaces/{name}_13",
        reason=reason,
        opened_at=opened_at,
    )


def plan_section() -> ResponsivePlanSection:
    return ResponsivePlanSection(
        AssociatedPlanSummary(
            title="Plan lane",
            goal="Keep every agent input together.",
            authored_tier="tale",
            effective_tier="tale",
            actual_path="/tmp/workspace/sase/repos/plans/plan.md",
            display_path="sase/repos/plans/plan.md",
            committed=True,
            exists=True,
            readable=True,
            frontmatter_readable=True,
            phase_availability="not-applicable",
            phases=(),
            size="medium",
        )
    )


def bead_section() -> ResponsiveBeadSection:
    return ResponsiveBeadSection(
        PhaseBeadSummary(
            id="sase-42.3",
            phase_title="Selected phase metadata",
            description="Render only the selected phase metadata.",
            actual_plan_path="/tmp/workspace/sase/repos/plans/epic.md",
            display_plan_path="sase/repos/plans/epic.md",
            plan_exists=True,
            plan_readable=True,
            epic_title="Phase-local context lane",
            size="medium",
            created_at="2026-08-01T14:30:00Z",
        )
    )


def task_bead_section() -> ResponsiveBeadSection:
    return ResponsiveBeadSection(
        BeadSummary(
            id="sase-task",
            phase_title="Task authored a plan",
            description="Render both task and authored-plan context.",
            actual_plan_path=None,
            display_plan_path=None,
            plan_exists=False,
            plan_readable=False,
            epic_title=None,
            size="medium",
            created_at="2026-08-01T14:30:00Z",
            bead_type="task",
        )
    )


def span_style_for(text: Text, needle: str) -> str:
    start = text.plain.index(needle)
    end = start + len(needle)
    styles = [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= end
    ]
    assert len(styles) == 1
    return styles[0]


def section_marker_ids(text: Text) -> list[str]:
    return [
        identity
        for span in text.spans
        if isinstance(span.style, RichStyle)
        and isinstance(
            identity := span.style.meta.get(SECTION_MARKER_META_KEY),
            str,
        )
    ]
