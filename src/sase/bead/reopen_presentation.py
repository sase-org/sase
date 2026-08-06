"""Shared language and palette for bead reopen and close-history presentation.

This module is the single source of truth for every surface that renders a
bead's archived close history or marks the ``+1`` entry that reopened it. The
four consumer surfaces (CLI, TaskTriage gate, ACE, generated pages) depend on
this module and on nothing else from each other.
"""

from __future__ import annotations

from collections.abc import Iterable

from sase.ansi_style import ansi_sgr
from sase.bead.model import CloseRecord, ReopenCause, TaskPlusOneEvidence

REOPEN_ACCENT = "#FF8700"
REOPEN_RICH_STYLE = f"bold {REOPEN_ACCENT}"
REOPEN_CLI_STYLE = ansi_sgr(color=REOPEN_ACCENT, bold=True)
REOPEN_GLYPH = "↺"
REOPEN_SECTION_LABEL = "PREVIOUSLY CLOSED"
REOPEN_EVIDENCE_MARKER = f"{REOPEN_GLYPH} reopened this task"


def reopen_badge(count: int) -> str:
    """Return the compact reopen-count badge, or an empty string for zero."""

    return f"{REOPEN_GLYPH}{count}" if count > 0 else ""


def close_record_label(record: CloseRecord) -> str:
    """Return the shared label for one archived close episode."""

    resolution = record.resolution.value if record.resolution else "(unrecorded)"
    return f"{REOPEN_GLYPH} Closed {record.closed_at} · {resolution}"


def close_record_reopened_label(record: CloseRecord) -> str:
    """Return the shared cause-specific label for how a close was undone."""

    if record.reopened_via == ReopenCause.PLUS_ONE:
        if record.reopened_by:
            return f"Reopened {record.reopened_at} by a +1 from @{record.reopened_by}"
        return f"Reopened {record.reopened_at} by a +1"
    if record.reopened_via == ReopenCause.OPEN:
        return f"Reopened {record.reopened_at} by `sase bead open`"
    if record.reopened_via == ReopenCause.UPDATE:
        return f"Reopened {record.reopened_at} by a status update"
    return f"Reopened {record.reopened_at} by an epic work preclaim"


def close_history_display_order(
    history: Iterable[CloseRecord],
) -> tuple[CloseRecord, ...]:
    """Return archived close records newest first for rendering."""

    return tuple(reversed(tuple(history)))


def close_history_search_text(history: Iterable[CloseRecord]) -> str:
    """Flatten archived close reasons, resolutions, and timestamps for search."""

    return "\n".join(
        value
        for record in history
        for value in (
            record.close_reason,
            record.resolution.value if record.resolution else None,
            record.closed_at,
            record.reopened_at,
        )
        if value
    )


def evidence_reopened_bead(
    evidence: TaskPlusOneEvidence, close_history: Iterable[CloseRecord]
) -> bool:
    """Return whether this ``+1`` entry is the one that reopened the bead."""

    return any(
        record.reopened_via == ReopenCause.PLUS_ONE
        and record.reopened_by == evidence.reporter
        and record.reopened_at == evidence.timestamp
        for record in close_history
    )


__all__ = [
    "REOPEN_ACCENT",
    "REOPEN_CLI_STYLE",
    "REOPEN_EVIDENCE_MARKER",
    "REOPEN_GLYPH",
    "REOPEN_RICH_STYLE",
    "REOPEN_SECTION_LABEL",
    "close_history_display_order",
    "close_history_search_text",
    "close_record_label",
    "close_record_reopened_label",
    "evidence_reopened_bead",
    "reopen_badge",
]
