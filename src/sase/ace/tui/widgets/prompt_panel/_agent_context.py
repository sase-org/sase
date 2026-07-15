"""SASE CONTEXT section rendering for the prompt panel header."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent

from ._agent_memory_reads import append_agent_memory_reads_section
from ._agent_opened_workspaces import append_agent_opened_workspaces_section
from ._agent_skill_uses import append_agent_skills_section
from ._helpers import append_major_section_divider, append_section_heading

_COLOR_HEADER = "bold #D7AF5F underline"


def append_agent_context_section(
    text: Text,
    *,
    memory_reads: tuple[MemoryReadDisplayEvent, ...] = (),
    skill_uses: tuple[SkillUseDisplayEvent, ...] = (),
    opened_workspaces: tuple[OpenedWorkspaceDisplayEvent, ...] = (),
) -> None:
    """Append the SASE CONTEXT section when any audited context exists."""
    if not memory_reads and not skill_uses and not opened_workspaces:
        return

    append_major_section_divider(text)
    append_section_heading(text, "SASE CONTEXT", style=_COLOR_HEADER)
    rendered_lane = False
    if memory_reads:
        append_agent_memory_reads_section(text, events=memory_reads)
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
