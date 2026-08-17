"""Agent-specific GLOSSARY context section helpers for the prompt panel header."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.glossary_reads import GlossaryReadDisplayEvent

from ._agent_display_state import HeaderHintState
from ._agent_context_common import (
    COLOR_EMPTY,
    COLOR_GLOSSARY_GLYPH,
    COLOR_GLOSSARY_PRIMARY,
    COLOR_GLOSSARY_SUBHEADER,
    COLOR_TRUNCATION,
    GLOSSARY_GLYPH,
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
TERMS_LIMIT = 64

__all__ = [
    "MAX_VISIBLE_READS",
    "TERMS_LIMIT",
    "append_agent_glossary_reads_section",
    "append_context_reason",
    "format_local_hhmm",
    "format_local_hhmmss",
    "normalize_context_display",
    "truncate_display",
]


def append_agent_glossary_reads_section(
    text: Text,
    *,
    events: tuple[GlossaryReadDisplayEvent, ...] = (),
    show_empty: bool = False,
    hint_state: HeaderHintState | None = None,
) -> None:
    """Append a GLOSSARY sub-section listing the family's audited reads."""
    if not events:
        if show_empty:
            append_context_lane_header(
                text,
                "GLOSSARY",
                label_style=COLOR_GLOSSARY_SUBHEADER,
                details="none recorded",
                details_style=COLOR_EMPTY,
            )
        return

    distinct_terms = len({term for item in events for term in item.event.terms})
    distinct_agents = len({item.agent_label for item in events if item.agent_label})
    details = (
        f"{count_phrase(len(events), 'read')} · {count_phrase(distinct_terms, 'term')}"
    )
    if distinct_agents > 1:
        details += f" · {count_phrase(distinct_agents, 'agent')}"
    append_context_lane_header(
        text,
        "GLOSSARY",
        label_style=COLOR_GLOSSARY_SUBHEADER,
        details=details,
    )

    visible = events[:MAX_VISIBLE_READS]
    show_role_column = any(item.agent_label for item in visible)
    for item in visible:
        event = item.event
        hint_label = None
        if hint_state is not None and event.source_path is not None:
            hint_number = hint_state.hint_counter
            hint_state.hint_mappings[hint_number] = event.source_path
            hint_state.hint_counter += 1
            hint_label = Text(f"[{hint_number}] ", style="bold #FFFF00")
        reason_indent = append_lane_row(
            text,
            timestamp=event.timestamp,
            glyph=GLOSSARY_GLYPH,
            glyph_style=COLOR_GLOSSARY_GLYPH,
            primary=truncate_display(", ".join(event.terms), TERMS_LIMIT),
            primary_style=COLOR_GLOSSARY_PRIMARY,
            role_label=item.agent_label,
            show_role_column=show_role_column,
            hint_label=hint_label,
        )
        if event.related_terms:
            text.append(f" +{len(event.related_terms)} related", style=COLOR_TRUNCATION)
        text.append("\n")
        append_context_reason(text, event.reason, indent=reason_indent)

    overflow = len(events) - len(visible)
    if overflow > 0:
        earliest = events[-1].event
        text.append(
            f"  + {overflow} more · {format_local_hhmm(earliest.timestamp)} earliest\n",
            style=COLOR_TRUNCATION,
        )
