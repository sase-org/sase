"""AGENT CONTEXT section rendering for the prompt panel header."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent

from ._agent_memory_reads import append_agent_memory_reads_section
from ._agent_skill_uses import append_agent_skills_section

_COLOR_HEADER = "bold #D7AF5F underline"
_MAJOR_SECTION_RULE = "\u2500" * 50


def _append_major_section_divider(text: Text) -> None:
    text.append("\n")
    text.append(_MAJOR_SECTION_RULE + "\n", style="dim")
    text.append("\n")


def append_agent_context_section(
    text: Text,
    *,
    memory_reads: tuple[MemoryReadDisplayEvent, ...] = (),
    skill_uses: tuple[SkillUseDisplayEvent, ...] = (),
) -> None:
    """Append the AGENT CONTEXT section when any audited context exists."""
    if not memory_reads and not skill_uses:
        return

    _append_major_section_divider(text)
    text.append("AGENT CONTEXT\n", style=_COLOR_HEADER)
    text.append("\n")
    append_agent_memory_reads_section(text, events=memory_reads, show_empty=True)
    text.append("\n")
    append_agent_skills_section(text, events=skill_uses, show_empty=True)
