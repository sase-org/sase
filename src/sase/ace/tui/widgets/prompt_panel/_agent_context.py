"""SASE CONTEXT section rendering for the prompt panel header."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent

from ._agent_memory_reads import append_agent_memory_reads_section
from ._agent_opened_workspaces import append_agent_opened_workspaces_section
from ._agent_plan_section import ResponsivePlanSection
from ._agent_skill_uses import append_agent_skills_section
from ._agent_display_state import HeaderHintState
from ._helpers import append_major_section_divider, append_section_heading

_COLOR_HEADER = "bold #D7AF5F underline"


def append_agent_context_section(
    text: Text,
    *,
    memory_reads: tuple[MemoryReadDisplayEvent, ...] = (),
    skill_uses: tuple[SkillUseDisplayEvent, ...] = (),
    opened_workspaces: tuple[OpenedWorkspaceDisplayEvent, ...] = (),
    plan_section: ResponsivePlanSection | None = None,
    hint_state: HeaderHintState | None = None,
) -> tuple[int, int] | None:
    """Append SASE CONTEXT when a plan or audited event lane exists."""
    if (
        plan_section is None
        and not memory_reads
        and not skill_uses
        and not opened_workspaces
    ):
        return None

    append_major_section_divider(text)
    append_section_heading(text, "SASE CONTEXT", style=_COLOR_HEADER)
    rendered_lane = False
    plan_range: tuple[int, int] | None = None
    if plan_section is not None:
        if hint_state is not None and plan_section.hint_number is None:
            hint_number = hint_state.hint_counter
            hint_state.hint_mappings[hint_number] = plan_section.summary.actual_path
            hint_state.hint_counter += 1
            plan_section.hint_number = hint_number
        plan_start = len(text)
        text.append_text(plan_section.logical_text)
        plan_range = (plan_start, len(text))
        rendered_lane = True
    if memory_reads:
        if rendered_lane:
            text.append("\n")
        append_agent_memory_reads_section(
            text,
            events=memory_reads,
            hint_state=hint_state,
        )
        rendered_lane = True
    if skill_uses:
        if rendered_lane:
            text.append("\n")
        append_agent_skills_section(text, events=skill_uses)
        rendered_lane = True
    if opened_workspaces:
        if rendered_lane:
            text.append("\n")
        append_agent_opened_workspaces_section(text, events=opened_workspaces)
    return plan_range
