"""Agent-specific MEMORY context section helpers for the prompt panel header."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.memory_reads import MemoryReadDisplayEvent

from ._agent_display_state import HeaderHintState
from ._agent_context_common import (
    COLOR_EMPTY,
    COLOR_FRONTMATTER,
    COLOR_MEMORY_GLYPH,
    COLOR_MEMORY_PRIMARY,
    COLOR_MEMORY_SUBHEADER,
    COLOR_TRUNCATION,
    FRONTMATTER_MARKER,
    MEMORY_GLYPH,
    append_context_lane_header,
    append_context_reason,
    append_lane_row,
    count_phrase,
    format_local_hhmm,
    format_local_hhmmss,
    normalize_context_display,
    truncate_display,
)

MAX_VISIBLE_READS = 5
PATH_LIMIT = 64

__all__ = [
    "MAX_VISIBLE_READS",
    "PATH_LIMIT",
    "append_agent_memory_reads_section",
    "append_context_reason",
    "format_local_hhmm",
    "format_local_hhmmss",
    "normalize_context_display",
    "truncate_display",
]


def append_agent_memory_reads_section(
    text: Text,
    *,
    events: tuple[MemoryReadDisplayEvent, ...] = (),
    show_empty: bool = False,
    hint_state: HeaderHintState | None = None,
) -> None:
    """Append a MEMORY sub-section listing the family's audited reads."""
    if not events:
        if show_empty:
            append_context_lane_header(
                text,
                "MEMORY",
                label_style=COLOR_MEMORY_SUBHEADER,
                details="none recorded",
                details_style=COLOR_EMPTY,
            )
        return

    distinct_paths = len({item.event.canonical_path for item in events})
    distinct_agents = len({item.agent_label for item in events if item.agent_label})
    details = (
        f"{count_phrase(len(events), 'read')} · {count_phrase(distinct_paths, 'file')}"
    )
    if distinct_agents > 1:
        details += f" · {count_phrase(distinct_agents, 'agent')}"
    append_context_lane_header(
        text,
        "MEMORY",
        label_style=COLOR_MEMORY_SUBHEADER,
        details=details,
    )

    visible = events[:MAX_VISIBLE_READS]
    show_role_column = any(item.agent_label for item in visible)
    for item in visible:
        event = item.event
        hint_label = None
        if hint_state is not None:
            hint_number = hint_state.hint_counter
            hint_state.hint_mappings[hint_number] = event.resolved_path
            hint_state.hint_counter += 1
            hint_label = Text(f"[{hint_number}] ", style="bold #FFFF00")
        reason_indent = append_lane_row(
            text,
            timestamp=event.timestamp,
            glyph=MEMORY_GLYPH,
            glyph_style=COLOR_MEMORY_GLYPH,
            primary=truncate_display(event.canonical_path, PATH_LIMIT),
            primary_style=COLOR_MEMORY_PRIMARY,
            role_label=item.agent_label,
            show_role_column=show_role_column,
            hint_label=hint_label,
        )
        if event.frontmatter_stripped:
            text.append(f"  {FRONTMATTER_MARKER}", style=COLOR_FRONTMATTER)
        text.append("\n")
        append_context_reason(text, event.reason, indent=reason_indent)

    overflow = len(events) - len(visible)
    if overflow > 0:
        earliest = events[-1].event
        text.append(
            f"  + {overflow} more · {format_local_hhmm(earliest.timestamp)} earliest\n",
            style=COLOR_TRUNCATION,
        )
