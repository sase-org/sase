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
from sase.bead_status_presentation import (
    BEAD_STATUS_PRESENTATIONS,
    bead_status_presentation,
)

if TYPE_CHECKING:
    from ._agent_completion_wait import (
        WaitAgentStatusCounts,
        WaitBeadStatusCounts,
        WaitDependencyStatusCounts,
    )


@dataclass(frozen=True, slots=True)
class _WaitStatusBadge:
    """Glyph and Rich style for one compact wait-status badge."""

    glyph: str
    style: str


WAIT_UNKNOWN_GLYPH = "?"
WAIT_UNKNOWN_GLYPH_STYLE = "bold #FFAF5F"
WAIT_UNRESOLVABLE_GLYPH = "!"
WAIT_UNRESOLVABLE_GLYPH_STYLE = "bold #FF5F5F"

WAIT_DOMAIN_SEPARATOR = "·"
WAIT_DOMAIN_SEPARATOR_STYLE = "dim"

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


def _wait_status_badge(bucket: str | None) -> _WaitStatusBadge:
    """Return the wait badge for a normalized agent bucket or unknown value."""
    if bucket is None:
        return WAIT_UNKNOWN_BADGE
    return WAIT_STATUS_BADGES.get(bucket, WAIT_UNKNOWN_BADGE)


def _wait_bead_status_token(status: str | None) -> tuple[str, str]:
    """Return the canonical status glyph and Rich style for a waited-on bead."""
    if status in BEAD_STATUS_PRESENTATIONS:
        presentation = bead_status_presentation(status)
        return (
            presentation.tui_glyph,
            presentation.rich_style,
        )
    return WAIT_UNKNOWN_GLYPH, WAIT_UNKNOWN_GLYPH_STYLE


def append_wait_status_badge(text: Text, bucket: str | None) -> None:
    """Append the standard per-target badge for a wait dependency."""
    badge = _wait_status_badge(bucket)
    text.append(" ")
    text.append(badge.glyph, style=badge.style)


def append_wait_bead_status_badge(text: Text, status: str | None) -> None:
    """Append the status-bearing bead wait token without a count."""
    token, style = _wait_bead_status_token(status)
    text.append(" ")
    text.append(token, style=style)


def _format_wait_agent_status_counts(
    counts: WaitAgentStatusCounts | None,
) -> Text:
    """Format a zero-suppressed compact agent wait-count group."""
    rendered = Text()
    if counts is None or not counts.has_any:
        return rendered

    first = True
    for bucket, count in counts.nonzero_buckets():
        if not first:
            rendered.append(" ")
        badge = _wait_status_badge(None if bucket == "unknown" else bucket)
        rendered.append(badge.glyph, style=badge.style)
        rendered.append(str(count), style=badge.style)
        first = False
    return rendered


def _format_wait_bead_status_counts(
    counts: WaitBeadStatusCounts | None,
) -> Text:
    """Format a zero-suppressed compact bead wait-count group."""
    rendered = Text()
    if counts is None or not counts.has_any:
        return rendered

    first = True
    for status, count in counts.nonzero_statuses():
        if not first:
            rendered.append(" ")
        token, style = _wait_bead_status_token(None if status == "unknown" else status)
        rendered.append(f"{token}{count}", style=style)
        first = False
    return rendered


def format_wait_dependency_status_counts(
    counts: WaitDependencyStatusCounts | None,
) -> Text:
    """Format a two-domain, zero-suppressed compact status-count summary."""
    rendered = Text()
    if counts is None or not counts.has_any:
        return rendered

    agent_text = _format_wait_agent_status_counts(counts.agents)
    bead_text = _format_wait_bead_status_counts(counts.beads)
    if agent_text.cell_len:
        rendered.append_text(agent_text)
    if agent_text.cell_len and bead_text.cell_len:
        rendered.append(" ")
        rendered.append(WAIT_DOMAIN_SEPARATOR, style=WAIT_DOMAIN_SEPARATOR_STYLE)
        rendered.append(" ")
    if bead_text.cell_len:
        rendered.append_text(bead_text)
    return rendered


__all__ = [
    "WAIT_DOMAIN_SEPARATOR",
    "WAIT_DOMAIN_SEPARATOR_STYLE",
    "WAIT_STATUS_BADGES",
    "WAIT_STATUS_COUNT_BUCKETS",
    "WAIT_UNKNOWN_GLYPH",
    "WAIT_UNKNOWN_GLYPH_STYLE",
    "WAIT_UNRESOLVABLE_GLYPH",
    "WAIT_UNRESOLVABLE_GLYPH_STYLE",
    "append_wait_bead_status_badge",
    "append_wait_status_badge",
    "format_wait_dependency_status_counts",
]
