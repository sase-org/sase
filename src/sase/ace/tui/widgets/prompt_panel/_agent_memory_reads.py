"""Agent-specific MEMORY context section helpers for the prompt panel header."""

from __future__ import annotations

from rich.text import Text

from sase.memory.read_log import MemoryReadEvent

from ._agent_context_common import (
    COLOR_EMPTY,
    COLOR_FRONTMATTER,
    COLOR_MEMORY_GLYPH,
    COLOR_MEMORY_PRIMARY,
    COLOR_MEMORY_SUBHEADER,
    COLOR_TRUNCATION,
    FRONTMATTER_MARKER,
    MEMORY_GLYPH,
    REASON_WRAP_WIDTH,
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
    "REASON_WRAP_WIDTH",
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
    events: tuple[MemoryReadEvent, ...] = (),
    show_empty: bool = False,
) -> None:
    """Append a MEMORY sub-section listing the agent's audited reads."""
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

    distinct_paths = len({event.canonical_path for event in events})
    append_context_lane_header(
        text,
        "MEMORY",
        label_style=COLOR_MEMORY_SUBHEADER,
        details=(
            f"{count_phrase(len(events), 'read')} · "
            f"{count_phrase(distinct_paths, 'file')}"
        ),
    )

    visible = events[:MAX_VISIBLE_READS]
    for event in visible:
        reason_indent = append_lane_row(
            text,
            timestamp=event.timestamp,
            glyph=MEMORY_GLYPH,
            glyph_style=COLOR_MEMORY_GLYPH,
            primary=truncate_display(event.canonical_path, PATH_LIMIT),
            primary_style=COLOR_MEMORY_PRIMARY,
        )
        if event.frontmatter_stripped:
            text.append(f"  {FRONTMATTER_MARKER}", style=COLOR_FRONTMATTER)
        text.append("\n")
        append_context_reason(text, event.reason, indent=reason_indent)

    overflow = len(events) - len(visible)
    if overflow > 0:
        earliest = events[-1]
        text.append(
            f"  + {overflow} more · {format_local_hhmm(earliest.timestamp)} earliest\n",
            style=COLOR_TRUNCATION,
        )
