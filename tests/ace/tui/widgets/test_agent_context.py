"""Tests for the SASE CONTEXT prompt-panel section renderer."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from rich.text import Text

from sase.ace.tui.models.agent_associated_plan import AssociatedPlanSummary
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.ace.tui.widgets.prompt_panel import _agent_context_common
from sase.ace.tui.widgets.prompt_panel._agent_context_common import count_phrase
from sase.ace.tui.widgets.prompt_panel._agent_context import (
    append_agent_context_section,
)
from sase.ace.tui.widgets.prompt_panel._agent_plan_section import (
    ResponsivePlanSection,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from sase.skills.use_log import SKILL_USE_LOG_SCHEMA_VERSION, SkillUseEvent
from tests.ace.tui.widgets._agent_display_metadata_helpers import (
    assert_logical_section_is_compact,
    assert_rendered_section_is_compact,
)


@pytest.fixture(autouse=True)
def _pin_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _agent_context_common,
        "get_timezone",
        lambda: ZoneInfo("UTC"),
    )


def _memory_event() -> MemoryReadDisplayEvent:
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


def _skill_event() -> SkillUseDisplayEvent:
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


def _workspace_event(
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


def _plan_section() -> ResponsivePlanSection:
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
        )
    )


def _span_style_for(text: Text, needle: str) -> str:
    start = text.plain.index(needle)
    end = start + len(needle)
    styles = [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= end
    ]
    assert len(styles) == 1
    return styles[0]


def test_empty_context_appends_nothing() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(), skill_uses=())
    assert text.plain == ""


def test_plan_only_context_renders_plan_lane_and_returns_its_range() -> None:
    text = Text()
    plan_section = _plan_section()

    plan_range = append_agent_context_section(text, plan_section=plan_section)

    assert plan_range is not None
    plan_start, plan_end = plan_range
    assert text[plan_start:plan_end].plain == plan_section.logical_text.plain
    assert "SASE CONTEXT\n" in text.plain
    assert "▸ PLAN · tale\n" in text.plain
    assert "  Title: Plan lane\n" in text.plain
    assert "▸ MEMORY" not in text.plain
    assert "▸ SKILLS" not in text.plain
    assert "▸ WORKSPACES" not in text.plain


def test_memory_only_context_omits_empty_skills_lane() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(_memory_event(),), skill_uses=())

    plain = text.plain
    assert "SASE CONTEXT\n" in plain
    assert "▸ MEMORY · 1 read · 1 file\n" in plain
    assert "generated_skills.md" in plain
    assert "▸ SKILLS" not in plain
    assert "▸ WORKSPACES" not in plain
    assert "▸ PLAN" not in plain
    assert "none recorded" not in plain
    assert_logical_section_is_compact(text, "SASE CONTEXT", "▸ MEMORY")
    assert_rendered_section_is_compact(text, "SASE CONTEXT", "▸ MEMORY")


def test_skills_only_context_omits_empty_memory_lane() -> None:
    text = Text()
    append_agent_context_section(text, memory_reads=(), skill_uses=(_skill_event(),))

    plain = text.plain
    assert "SASE CONTEXT\n" in plain
    assert "▸ SKILLS · 1 use · 1 skill\n" in plain
    assert "sase_plan" in plain
    assert "▸ PLAN" not in plain
    assert "▸ MEMORY" not in plain
    assert "▸ WORKSPACES" not in plain
    assert "none recorded" not in plain


def test_workspaces_only_context_omits_empty_other_lanes() -> None:
    text = Text()
    append_agent_context_section(
        text,
        opened_workspaces=(_workspace_event(),),
    )

    plain = text.plain
    assert "SASE CONTEXT\n" in plain
    assert "▸ WORKSPACES · 1 open · 1 repo\n" in plain
    assert "▣ sase-core" in plain
    assert "→ /tmp/workspaces/sase-core_13" in plain
    assert "↳ needed to inspect core boundary" in plain
    assert "▸ MEMORY" not in plain
    assert "▸ SKILLS" not in plain
    assert "▸ PLAN" not in plain
    assert "none recorded" not in plain


def test_context_lanes_render_in_parent_context_order() -> None:
    text = Text()
    append_agent_context_section(
        text,
        plan_section=_plan_section(),
        memory_reads=(_memory_event(),),
        skill_uses=(_skill_event(),),
        opened_workspaces=(_workspace_event(),),
    )

    plain = text.plain
    assert plain.index("SASE CONTEXT\n") < plain.index("▸ PLAN")
    assert plain.index("▸ PLAN") < plain.index("▸ MEMORY")
    assert plain.index("▸ MEMORY") < plain.index("▸ SKILLS")
    assert plain.index("▸ SKILLS") < plain.index("▸ WORKSPACES")
    assert "needed generated skill rules" in plain
    assert "needed an implementation plan" in plain
    assert "needed to inspect core boundary" in plain


def test_count_phrase_pluralizes_context_counts() -> None:
    assert count_phrase(1, "read") == "1 read"
    assert count_phrase(2, "read") == "2 reads"
    assert count_phrase(1, "file") == "1 file"
    assert count_phrase(3, "file") == "3 files"
    assert count_phrase(1, "use") == "1 use"
    assert count_phrase(2, "skill") == "2 skills"
    assert count_phrase(1, "open") == "1 open"
    assert count_phrase(2, "repo") == "2 repos"


def test_lane_subheaders_use_distinct_accent_colors() -> None:
    text = Text()
    append_agent_context_section(
        text,
        plan_section=_plan_section(),
        memory_reads=(_memory_event(),),
        skill_uses=(_skill_event(),),
        opened_workspaces=(_workspace_event(),),
    )

    plan_style = _span_style_for(text, "▸ PLAN").lower()
    memory_style = _span_style_for(text, "▸ MEMORY").lower()
    skills_style = _span_style_for(text, "▸ SKILLS").lower()
    workspaces_style = _span_style_for(text, "▸ WORKSPACES").lower()
    assert plan_style == "bold #af87ff"
    assert memory_style == "bold #5fd7ff"
    assert skills_style == "bold #5fd75f"
    assert workspaces_style == "bold #ff87d7"
    assert len({plan_style, memory_style, skills_style, workspaces_style}) == 4


def test_context_rows_share_columns() -> None:
    text = Text()
    append_agent_context_section(
        text,
        memory_reads=(_memory_event(),),
        skill_uses=(_skill_event(),),
        opened_workspaces=(_workspace_event(),),
    )

    lines = text.plain.splitlines()
    memory_row = next(line for line in lines if "◇ generated_skills.md" in line)
    skill_row = next(line for line in lines if "◆ sase_plan" in line)
    workspace_row = next(line for line in lines if "▣ sase-core" in line)
    memory_reason = next(
        line for line in lines if "needed generated skill rules" in line
    )
    skill_reason = next(
        line for line in lines if "needed an implementation plan" in line
    )
    workspace_reason = next(
        line for line in lines if "needed to inspect core boundary" in line
    )

    assert memory_row.index("◇") == skill_row.index("◆")
    assert memory_row.index("◇") == workspace_row.index("▣")
    assert memory_row.index("generated_skills.md") == skill_row.index("sase_plan")
    assert memory_row.index("generated_skills.md") == workspace_row.index("sase-core")
    assert memory_reason.index("↳") == skill_reason.index("↳")
    assert memory_reason.index("↳") == workspace_reason.index("↳")
    assert memory_reason.index("↳") == memory_row.index("generated_skills.md")


def test_context_hints_apply_only_to_memory_rows() -> None:
    text = Text()
    hint_state = HeaderHintState(
        hint_counter=8,
        hint_mappings={},
        workspace_dir=None,
        tool_call_reports={},
    )

    append_agent_context_section(
        text,
        memory_reads=(_memory_event(),),
        skill_uses=(_skill_event(),),
        opened_workspaces=(_workspace_event(),),
        hint_state=hint_state,
    )

    assert "◇ [8] generated_skills.md" in text.plain
    assert "◆ sase_plan" in text.plain
    assert "▣ sase-core" in text.plain
    assert "[9]" not in text.plain
    assert hint_state.hint_mappings == {8: "/tmp/test/memory/generated_skills.md"}
    assert hint_state.hint_counter == 9


def test_workspace_lane_overflow_shows_earliest_open() -> None:
    text = Text()
    events = tuple(
        _workspace_event(
            name=f"repo-{index}",
            opened_at=f"2026-06-14T14:2{index}:00+00:00",
            reason=f"reason {index}",
        )
        for index in range(6, -1, -1)
    )

    append_agent_context_section(text, opened_workspaces=events)

    plain = text.plain
    assert "▸ WORKSPACES · 7 opens · 7 repos\n" in plain
    assert "repo-6" in plain
    assert "repo-2" in plain
    assert "repo-1" not in plain
    assert "repo-0" not in plain
    assert "+ 2 more · 14:20 earliest\n" in plain
