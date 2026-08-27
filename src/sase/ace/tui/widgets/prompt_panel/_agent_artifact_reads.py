"""Compact ARTIFACTS ``Reads`` row renderer for the prompt-panel header."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.artifact_reads import ArtifactReadDisplayEvent, ArtifactReadRefSpec

from ._agent_context_common import (
    ARTIFACT_READ_GLYPH,
    COLOR_ARTIFACT_READ_GLYPH,
    COLOR_ARTIFACT_READ_PRIMARY,
    COLOR_TRUNCATION,
    append_context_reason,
    append_lane_row,
    format_local_hhmm,
    truncate_display,
)
from ._agent_display_state import HeaderHintState

MAX_VISIBLE_READS = 5
REF_LIMIT = 64
_SUBSECTION_ROW_PREFIX = "  "

__all__ = [
    "MAX_VISIBLE_READS",
    "REF_LIMIT",
    "append_agent_artifact_read_rows",
]


def append_agent_artifact_read_rows(
    text: Text,
    *,
    events: tuple[ArtifactReadDisplayEvent, ...],
    hint_state: HeaderHintState | None = None,
) -> None:
    """Append newest-first artifact-read rows under an ARTIFACTS ``Reads:`` header.

    The ARTIFACTS lane owns sub-section ordering and the summary counts; this
    helper only paints the compact rows, reasons, hints, and overflow footer.
    """
    visible = events[:MAX_VISIBLE_READS]
    show_role_column = any(item.agent_label for item in visible)
    extra_indent = len(_SUBSECTION_ROW_PREFIX)
    for item in visible:
        event = item.event
        hint_label = None
        if hint_state is not None and event.resolved_path:
            hint_number = hint_state.hint_counter
            hint_state.hint_mappings[hint_number] = event.resolved_path
            hint_state.artifact_read_refs[event.resolved_path] = ArtifactReadRefSpec(
                ref=event.ref,
                cwd=event.cwd,
            )
            hint_state.hint_counter += 1
            hint_label = Text(f"[{hint_number}] ", style="bold #FFFF00")
        text.append(_SUBSECTION_ROW_PREFIX)
        reason_indent = (
            append_lane_row(
                text,
                timestamp=event.timestamp,
                glyph=ARTIFACT_READ_GLYPH,
                glyph_style=COLOR_ARTIFACT_READ_GLYPH,
                primary=truncate_display(event.ref, REF_LIMIT),
                primary_style=COLOR_ARTIFACT_READ_PRIMARY,
                role_label=item.agent_label,
                show_role_column=show_role_column,
                hint_label=hint_label,
            )
            + extra_indent
        )
        text.append("\n")
        append_context_reason(text, event.reason, indent=reason_indent)

    overflow = len(events) - len(visible)
    if overflow > 0:
        earliest = events[-1].event
        text.append(
            f"  {_SUBSECTION_ROW_PREFIX}+ {overflow} more · "
            f"{format_local_hhmm(earliest.timestamp)} earliest\n",
            style=COLOR_TRUNCATION,
        )
