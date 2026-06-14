"""Agent-specific SKILLS context section helpers for the prompt panel header."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.skill_uses import SkillUseDisplayEvent

from ._agent_context_common import (
    COLOR_EMPTY,
    COLOR_SKILL_GLYPH,
    COLOR_SKILL_NAME,
    COLOR_SKILLS_SUBHEADER,
    COLOR_TRUNCATION,
    SKILL_GLYPH,
    append_context_lane_header,
    append_context_reason,
    append_lane_row,
    count_phrase,
    format_local_hhmm,
    truncate_display,
)

MAX_VISIBLE_SKILL_USES = 5
SKILL_NAME_LIMIT = 48


def append_agent_skills_section(
    text: Text,
    *,
    events: tuple[SkillUseDisplayEvent, ...] = (),
    show_empty: bool = False,
) -> None:
    """Append a SKILLS sub-section listing the family's audited skill uses."""
    if not events:
        if show_empty:
            append_context_lane_header(
                text,
                "SKILLS",
                label_style=COLOR_SKILLS_SUBHEADER,
                details="none recorded",
                details_style=COLOR_EMPTY,
            )
        return

    distinct_skills = len({item.event.skill_name for item in events})
    distinct_agents = len({item.agent_label for item in events if item.agent_label})
    details = (
        f"{count_phrase(len(events), 'use')} · {count_phrase(distinct_skills, 'skill')}"
    )
    if distinct_agents > 1:
        details += f" · {count_phrase(distinct_agents, 'agent')}"
    append_context_lane_header(
        text,
        "SKILLS",
        label_style=COLOR_SKILLS_SUBHEADER,
        details=details,
    )

    visible = events[:MAX_VISIBLE_SKILL_USES]
    show_role_column = any(item.agent_label for item in visible)
    for item in visible:
        event = item.event
        reason_indent = append_lane_row(
            text,
            timestamp=event.timestamp,
            glyph=SKILL_GLYPH,
            glyph_style=COLOR_SKILL_GLYPH,
            primary=truncate_display(event.skill_name, SKILL_NAME_LIMIT),
            primary_style=COLOR_SKILL_NAME,
            role_label=item.agent_label,
            show_role_column=show_role_column,
        )
        text.append("\n")
        append_context_reason(text, event.reason, indent=reason_indent)

    overflow = len(events) - len(visible)
    if overflow > 0:
        earliest = events[-1].event
        text.append(
            f"  + {overflow} more · {format_local_hhmm(earliest.timestamp)} earliest\n",
            style=COLOR_TRUNCATION,
        )
