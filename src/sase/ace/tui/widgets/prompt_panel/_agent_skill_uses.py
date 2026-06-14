"""Agent-specific SKILLS context section helpers for the prompt panel header."""

from __future__ import annotations

from rich.text import Text

from sase.skills.use_log import SkillUseEvent

from ._agent_memory_reads import (
    append_context_reason,
    format_local_hhmm,
    format_local_hhmmss,
    normalize_context_display,
)

MAX_VISIBLE_SKILL_USES = 5
SKILL_NAME_LIMIT = 48

_COLOR_SUBHEADER = "bold #5FD7FF"
_COLOR_SUMMARY = "dim"
_COLOR_TIMESTAMP = "dim"
_COLOR_SKILL_GLYPH = "bold #5FD75F"
_COLOR_SKILL_NAME = "bold #87FF87"
_COLOR_TRUNCATION = "dim italic"
_COLOR_EMPTY = "dim italic"
_EMPTY_PLACEHOLDER = "  — none recorded —\n"


def _truncate_skill_name(value: str, limit: int) -> str:
    value = normalize_context_display(value)
    if len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def append_agent_skills_section(
    text: Text,
    *,
    events: tuple[SkillUseEvent, ...] = (),
    show_empty: bool = False,
) -> None:
    """Append a SKILLS sub-section listing the agent's audited skill uses."""
    if not events:
        if show_empty:
            text.append("▸ SKILLS\n", style=_COLOR_SUBHEADER)
            text.append(_EMPTY_PLACEHOLDER, style=_COLOR_EMPTY)
        return

    distinct_skills = len({event.skill_name for event in events})
    latest = events[0]

    text.append("▸ SKILLS\n", style=_COLOR_SUBHEADER)
    text.append(
        f"  {len(events)} uses · {distinct_skills} skills "
        f"· last {format_local_hhmmss(latest.timestamp)}\n\n",
        style=_COLOR_SUMMARY,
    )

    visible = events[:MAX_VISIBLE_SKILL_USES]
    for event in visible:
        text.append(
            f"  {format_local_hhmmss(event.timestamp)}  ", style=_COLOR_TIMESTAMP
        )
        text.append("◆ ", style=_COLOR_SKILL_GLYPH)
        text.append(
            _truncate_skill_name(event.skill_name, SKILL_NAME_LIMIT),
            style=_COLOR_SKILL_NAME,
        )
        text.append("\n")
        append_context_reason(text, event.reason)

    overflow = len(events) - len(visible)
    if overflow > 0:
        earliest = events[-1]
        text.append(
            f"  + {overflow} more  ({format_local_hhmm(earliest.timestamp)} earliest)\n",
            style=_COLOR_TRUNCATION,
        )
