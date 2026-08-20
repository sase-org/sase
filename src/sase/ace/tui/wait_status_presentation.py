"""Shared ACE TUI presentation for wait dependency statuses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text

from sase.agent.status_buckets import (
    AGENT_STATUS_BUCKET_GLYPHS,
    AGENT_STATUS_BUCKETS,
    QUEUED_STATUS_COLOR,
)

if TYPE_CHECKING:
    from ._agent_completion_wait import WaitDependencyStatusCounts


@dataclass(frozen=True, slots=True)
class _WaitStatusBadge:
    """Glyph and Rich style for one compact wait-status badge."""

    glyph: str
    style: str


WAIT_UNKNOWN_GLYPH = "?"
WAIT_UNKNOWN_GLYPH_STYLE = "bold #FFAF5F"
WAIT_UNRESOLVABLE_GLYPH = "!"
WAIT_UNRESOLVABLE_GLYPH_STYLE = "bold #FF5F5F"

# Glyphs mirror ``AGENT_STATUS_BUCKET_GLYPHS``; colors mirror the established
# agent-row status accents.
WAIT_STATUS_BADGES: dict[str, _WaitStatusBadge] = {
    "Running": _WaitStatusBadge(AGENT_STATUS_BUCKET_GLYPHS["Running"], "bold #FFD700"),
    "Queued": _WaitStatusBadge(
        AGENT_STATUS_BUCKET_GLYPHS["Queued"],
        f"bold {QUEUED_STATUS_COLOR}",
    ),
    "Waiting": _WaitStatusBadge(AGENT_STATUS_BUCKET_GLYPHS["Waiting"], "bold #AF87FF"),
    "Starting": _WaitStatusBadge(
        AGENT_STATUS_BUCKET_GLYPHS["Starting"], "bold #87D7FF"
    ),
    "Done": _WaitStatusBadge(AGENT_STATUS_BUCKET_GLYPHS["Done"], "bold #5FD75F"),
    "Failed": _WaitStatusBadge(AGENT_STATUS_BUCKET_GLYPHS["Failed"], "bold #FF5F5F"),
    "Stopped": _WaitStatusBadge(AGENT_STATUS_BUCKET_GLYPHS["Stopped"], "bold #8787AF"),
}

WAIT_UNKNOWN_BADGE = _WaitStatusBadge(WAIT_UNKNOWN_GLYPH, WAIT_UNKNOWN_GLYPH_STYLE)
WAIT_STATUS_COUNT_BUCKETS: tuple[str, ...] = AGENT_STATUS_BUCKETS

BEAD_STATUS_TO_WAIT_BUCKET: dict[str, str] = {
    "closed": "Done",
    "in_progress": "Running",
    "claimed": "Starting",
    "open": "Waiting",
}


def _wait_status_badge(bucket: str | None) -> _WaitStatusBadge:
    """Return the wait badge for a normalized agent bucket or unknown value."""
    if bucket is None:
        return WAIT_UNKNOWN_BADGE
    return WAIT_STATUS_BADGES.get(bucket, WAIT_UNKNOWN_BADGE)


def wait_bead_status_bucket(status: str | None) -> str | None:
    """Normalize a waited-on bead status to an agent wait-status bucket."""
    if status is None:
        return None
    return BEAD_STATUS_TO_WAIT_BUCKET.get(status)


def append_wait_status_badge(text: Text, bucket: str | None) -> None:
    """Append the standard per-target badge for a wait dependency."""
    badge = _wait_status_badge(bucket)
    text.append(" ")
    text.append(badge.glyph, style=badge.style)


def append_wait_bead_status_badge(text: Text, status: str | None) -> None:
    """Append the standard per-bead badge for a wait dependency."""
    append_wait_status_badge(text, wait_bead_status_bucket(status))


def format_wait_dependency_status_counts(
    counts: WaitDependencyStatusCounts | None,
) -> Text:
    """Format a zero-suppressed compact status-count summary."""
    rendered = Text()
    if counts is None or not counts.has_any:
        return rendered

    first = True
    for bucket in WAIT_STATUS_COUNT_BUCKETS:
        count = counts.count_for_bucket(bucket)
        if count <= 0:
            continue
        if not first:
            rendered.append(" ")
        badge = _wait_status_badge(bucket)
        rendered.append(badge.glyph, style=badge.style)
        rendered.append(str(count), style=badge.style)
        first = False

    if counts.unknown > 0:
        if not first:
            rendered.append(" ")
        rendered.append(WAIT_UNKNOWN_BADGE.glyph, style=WAIT_UNKNOWN_BADGE.style)
        rendered.append(str(counts.unknown), style=WAIT_UNKNOWN_BADGE.style)

    return rendered


__all__ = [
    "BEAD_STATUS_TO_WAIT_BUCKET",
    "WAIT_STATUS_BADGES",
    "WAIT_STATUS_COUNT_BUCKETS",
    "WAIT_UNKNOWN_GLYPH",
    "WAIT_UNKNOWN_GLYPH_STYLE",
    "WAIT_UNRESOLVABLE_GLYPH",
    "WAIT_UNRESOLVABLE_GLYPH_STYLE",
    "append_wait_bead_status_badge",
    "append_wait_status_badge",
    "format_wait_dependency_status_counts",
    "wait_bead_status_bucket",
]
